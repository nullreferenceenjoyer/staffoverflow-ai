from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import PLANNERS, Scope, audit, get_current_user, get_scope, require_roles
from app.models import Project, Role, Task, TaskStatus, User, WorkflowTemplate
from app.schemas import (
    TaskIn,
    TaskOut,
    TaskUpdate,
    WorkflowStart,
    WorkflowTemplateIn,
    WorkflowTemplateOut,
)
from app.services import workflow

router = APIRouter(tags=["workflow"])


def _get_template(db: Session, template_id: int) -> WorkflowTemplate:
    template = db.get(WorkflowTemplate, template_id)
    if template is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сценарий не найден")
    return template


@router.get("/workflow/templates", response_model=list[WorkflowTemplateOut])
def list_templates(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.scalars(select(WorkflowTemplate).order_by(WorkflowTemplate.id)).all()


@router.post("/workflow/templates", response_model=WorkflowTemplateOut,
             status_code=status.HTTP_201_CREATED)
def create_template(body: WorkflowTemplateIn, request: Request, db: Session = Depends(get_db),
                    user: User = Depends(require_roles(*PLANNERS))):
    template = WorkflowTemplate(**body.model_dump(mode="json"))
    db.add(template)
    db.flush()
    audit(db, user, "workflow_template_created", entity="workflow_template",
          entity_id=template.id, request=request)
    db.commit()
    return template


@router.put("/workflow/templates/{template_id}", response_model=WorkflowTemplateOut)
def update_template(template_id: int, body: WorkflowTemplateIn, request: Request,
                    db: Session = Depends(get_db),
                    user: User = Depends(require_roles(*PLANNERS))):
    template = _get_template(db, template_id)
    for key, value in body.model_dump(mode="json").items():
        setattr(template, key, value)
    audit(db, user, "workflow_template_updated", entity="workflow_template",
          entity_id=template.id, request=request)
    db.commit()
    return template


@router.delete("/workflow/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(template_id: int, request: Request, db: Session = Depends(get_db),
                    user: User = Depends(require_roles(*PLANNERS))):
    template = _get_template(db, template_id)
    audit(db, user, "workflow_template_deleted", entity="workflow_template",
          entity_id=template.id, details={"name": template.name}, request=request)
    db.delete(template)
    db.commit()


@router.post("/workflow/templates/{template_id}/start", response_model=list[TaskOut],
             status_code=status.HTTP_201_CREATED)
def start_workflow(template_id: int, body: WorkflowStart, request: Request,
                   user: User = Depends(require_roles(*PLANNERS)),
                   scope: Scope = Depends(get_scope)):
    db = scope.db
    template = _get_template(db, template_id)
    project = None
    municipality_id = body.municipality_id
    if body.project_id is not None:
        project = db.get(Project, body.project_id)
        if project is None or not scope.can_see_project(project):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Проект не найден")
        municipality_id = project.municipality_id
    elif user.role == Role.municipal_specialist:
        municipality_id = user.municipality_id

    tasks = workflow.start_run(db, template, project, municipality_id, body.start_date)
    db.flush()
    audit(db, user, "workflow_started", entity="workflow_template", entity_id=template.id,
          details={"project_id": body.project_id, "tasks": len(tasks)}, request=request)
    db.commit()
    return tasks


def _visible_tasks(scope: Scope):
    query = select(Task).order_by(Task.due_date.nulls_last(), Task.id)
    user = scope.user
    if scope.is_regional:
        return query
    if user.role == Role.municipal_specialist:
        return query.where(Task.municipality_id == user.municipality_id)
    # Директору показываем только то, что адресовано директорам по его учреждению
    return query.join(Project, Project.id == Task.project_id).where(
        Task.assignee_role == Role.director, Project.organization_id == user.organization_id
    )


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(project_id: int | None = None, scope: Scope = Depends(get_scope)):
    query = _visible_tasks(scope)
    if project_id is not None:
        query = query.where(Task.project_id == project_id)
    return scope.db.scalars(query.limit(500)).all()


@router.post("/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
def create_task(body: TaskIn, request: Request,
                user: User = Depends(require_roles(*PLANNERS)),
                scope: Scope = Depends(get_scope)):
    data = body.model_dump()
    if user.role == Role.municipal_specialist:
        data["municipality_id"] = user.municipality_id
    task = Task(**data)
    scope.db.add(task)
    scope.db.flush()
    audit(scope.db, user, "task_created", entity="task", entity_id=task.id, request=request)
    scope.db.commit()
    return task


@router.patch("/tasks/{task_id}", response_model=TaskOut)
def update_task(task_id: int, body: TaskUpdate, request: Request,
                scope: Scope = Depends(get_scope)):
    user = scope.user
    task = scope.db.scalar(_visible_tasks(scope).where(Task.id == task_id))
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Задача не найдена")
    is_planner = user.role in PLANNERS
    # Статус своей задачи может менять и исполнитель, остальное — только те, кто планирует
    is_assignee = task.assignee_id == user.id or (
        task.assignee_id is None and task.assignee_role == user.role
    )
    if not (is_planner or is_assignee):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостаточно прав")

    changes = body.model_dump(exclude_unset=True)
    if "status" in changes:
        if task.status == TaskStatus.waiting and not is_planner:
            raise HTTPException(status.HTTP_409_CONFLICT, "Предыдущий шаг ещё не завершён")
        workflow.set_status(scope.db, task, changes.pop("status"))
    if changes:
        if not is_planner:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостаточно прав")
        for key, value in changes.items():
            setattr(task, key, value)
    audit(scope.db, user, "task_updated", entity="task", entity_id=task.id,
          details=body.model_dump(exclude_unset=True, mode="json"), request=request)
    scope.db.commit()
    return task

