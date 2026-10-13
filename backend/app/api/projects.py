from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.config import get_settings
from app.deps import APPROVERS, PLANNERS, Scope, audit, get_scope, require_roles
from app.models import GeneratedDocument, Municipality, Project, ProjectStatus, Role, User
from app.schemas import (
    DocumentGenerate,
    DocumentOut,
    ProjectDetail,
    ProjectGenerate,
    ProjectOut,
    ProjectStatusChange,
)
from app.services import analytics, documents
from app.services import projects as project_service

router = APIRouter(tags=["projects"])

# Какие переходы статуса допустимы и кому
TRANSITIONS: dict[ProjectStatus, dict[ProjectStatus, tuple[Role, ...]]] = {
    ProjectStatus.draft: {ProjectStatus.review: PLANNERS},
    ProjectStatus.review: {
        ProjectStatus.approved: APPROVERS,
        ProjectStatus.rejected: APPROVERS,
        ProjectStatus.draft: PLANNERS,
    },
    ProjectStatus.approved: {ProjectStatus.implemented: PLANNERS},
    ProjectStatus.rejected: {ProjectStatus.draft: PLANNERS},
    ProjectStatus.implemented: {},
}


def _get_project(project_id: int, scope: Scope) -> Project:
    project = scope.db.get(Project, project_id)
    if project is None or not scope.can_see_project(project):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Проект не найден")
    return project


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(scope: Scope = Depends(get_scope)):
    projects = scope.db.scalars(select(Project).order_by(Project.created_at.desc())).all()
    return [p for p in projects if scope.can_see_project(p)]


@router.get("/projects/{project_id}", response_model=ProjectDetail)
def get_project(project_id: int, scope: Scope = Depends(get_scope)):
    return _get_project(project_id, scope)


@router.post("/projects/generate", response_model=ProjectDetail,
             status_code=status.HTTP_201_CREATED)
def generate_project(body: ProjectGenerate, request: Request,
                     user: User = Depends(require_roles(*PLANNERS)),
                     scope: Scope = Depends(get_scope)):
    """Формирует проект по текущим данным: для одного ОУ или для муниципалитета."""
    db = scope.db
    if body.kind == "normalization":
        if body.organization_id is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Укажите учреждение")
        org = scope.get_org(body.organization_id)
        # Средняя стоимость ставки считается по муниципалитету — зарплаты там сопоставимы
        neighbours = analytics.load_reports(db, scope.org_ids(org.municipality_id))
        report = next(r for r in neighbours if r.org_id == org.id)
        project = project_service.normalization_project(report, user, _average_pay(neighbours))
    else:
        if body.municipality_id is None or not scope.can_see_municipality(body.municipality_id):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Укажите муниципалитет")
        org_ids = scope.org_ids(body.municipality_id)
        if body.kind == "workload":
            municipality = db.get(Municipality, body.municipality_id)
            report = analytics.load_sites(db, org_ids, get_settings().site_radius_m)
            project = project_service.workload_project(report, municipality.id,
                                                       municipality.name, user)
        else:
            reports = analytics.load_reports(db, org_ids)
            project = project_service.centralization_project(reports, user)

    if project is None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Отклонений не найдено — проект формировать не из чего")
    db.add(project)
    db.flush()
    audit(db, user, "project_generated", entity="project", entity_id=project.id,
          details={"kind": project.kind}, request=request)
    db.commit()
    return project


def _average_pay(reports) -> dict[str, float]:
    totals: dict[str, list[float]] = {}
    for report in reports:
        for line in report.lines:
            pay, rate = totals.setdefault(line.category, [0.0, 0.0])
            totals[line.category] = [pay + line.actual_pay, rate + line.actual_rate]
    return {category: pay / rate for category, (pay, rate) in totals.items() if rate}


@router.post("/projects/{project_id}/status", response_model=ProjectOut)
def change_status(project_id: int, body: ProjectStatusChange, request: Request,
                  scope: Scope = Depends(get_scope)):
    project = _get_project(project_id, scope)
    user = scope.user
    allowed = TRANSITIONS[ProjectStatus(project.status)].get(body.status)
    if allowed is None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Из статуса «{project.status}» нельзя перейти в «{body.status}»")
    if user.role not in allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостаточно прав для этого решения")

    audit(scope.db, user, "project_status_changed", entity="project", entity_id=project.id,
          details={"from": project.status, "to": body.status}, request=request)
    project.status = body.status
    if body.status in (ProjectStatus.approved, ProjectStatus.rejected):
        project.decided_by_id = user.id
        project.decided_at = datetime.now(UTC)
    scope.db.commit()
    return project


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: int, request: Request,
                   user: User = Depends(require_roles(*PLANNERS)),
                   scope: Scope = Depends(get_scope)):
    project = _get_project(project_id, scope)
    if project.status not in (ProjectStatus.draft, ProjectStatus.rejected):
        raise HTTPException(status.HTTP_409_CONFLICT, "Удалить можно только черновик")
    audit(scope.db, user, "project_deleted", entity="project", entity_id=project.id,
          details={"title": project.title}, request=request)
    scope.db.delete(project)
    scope.db.commit()


@router.post("/projects/{project_id}/documents", response_model=DocumentOut,
             status_code=status.HTTP_201_CREATED)
def generate_document(project_id: int, body: DocumentGenerate, request: Request,
                      user: User = Depends(require_roles(*PLANNERS)),
                      scope: Scope = Depends(get_scope)):
    project = _get_project(project_id, scope)
    document = documents.generate(project, body.kind, user)
    scope.db.add(document)
    scope.db.flush()
    audit(scope.db, user, "document_generated", entity="project", entity_id=project.id,
          details={"kind": body.kind, "llm": document.written_by_llm}, request=request)
    scope.db.commit()
    return document


@router.get("/documents/{document_id}/download")
def download_document(document_id: int, scope: Scope = Depends(get_scope)):
    document = scope.db.get(GeneratedDocument, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Документ не найден")
    _get_project(document.project_id, scope)
    path = Path(get_settings().storage_dir) / document.file_path
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Файл документа не найден в хранилище")
    return FileResponse(
        path,
        filename=f"{document.kind}-{document.project_id}.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
