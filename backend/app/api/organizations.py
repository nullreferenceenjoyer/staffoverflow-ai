from dataclasses import asdict

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy import select

from app.deps import EDITORS, PLANNERS, Scope, audit, get_scope, require_roles
from app.models import (
    Building,
    Enrollment,
    Municipality,
    Organization,
    Role,
    StaffPosition,
    User,
)
from app.schemas import (
    BuildingIn,
    BuildingOut,
    EnrollmentIn,
    EnrollmentOut,
    MunicipalityOut,
    OrganizationIn,
    PositionIn,
    PositionOut,
)
from app.services import analytics, forecast, importer
from app.services.functions import BY_CODE, classify_title
from app.services.staffing import DRIVERS, OrgReport

router = APIRouter(tags=["organizations"])

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def report_summary(report: OrgReport) -> dict:
    return {
        "id": report.org_id,
        "name": report.name,
        "org_type": report.org_type,
        "municipality_id": report.municipality_id,
        "municipality": report.municipality,
        "students": int(report.metrics["students_total"]),
        "actual": report.actual_total,
        "norm": report.norm_total,
        "surplus": report.surplus,
        "shortage": report.shortage,
        "compliance": report.compliance,
        "fot_actual_year": report.fot_actual_year,
        "saving_potential_year": report.saving_potential_year,
    }


def report_details(report: OrgReport) -> dict:
    return {
        **report_summary(report),
        "metrics": [
            {"key": key, "title": DRIVERS[key], "value": value}
            for key, value in report.metrics.items()
            if value and key != "organization"
        ],
        "categories": report.by_category(),
        "lines": [
            {**asdict(line), "delta": line.delta, "has_norm": line.norm_rate is not None}
            for line in report.lines
        ],
        "allowances": [
            {"title": a.rule.title, "value": a.value, "explanation": a.explanation,
             "legal_ref": a.rule.legal_ref}
            for a in report.allowances
        ],
    }


@router.get("/municipalities", response_model=list[MunicipalityOut])
def list_municipalities(scope: Scope = Depends(get_scope)):
    query = select(Municipality).order_by(Municipality.name)
    if not scope.is_regional:
        ids = scope.organizations().with_only_columns(Organization.municipality_id)
        query = query.where(Municipality.id.in_(ids))
    return scope.db.scalars(query).all()


@router.get("/organizations")
def list_organizations(municipality_id: int | None = None, search: str = "",
                       scope: Scope = Depends(get_scope)):
    reports = analytics.load_reports(scope.db, scope.org_ids(municipality_id))
    if search:
        needle = search.lower()
        reports = [r for r in reports if needle in r.name.lower()]
    return [report_summary(r) for r in reports]


@router.post("/organizations", status_code=status.HTTP_201_CREATED)
def create_organization(body: OrganizationIn, request: Request,
                        user: User = Depends(require_roles(*PLANNERS)),
                        scope: Scope = Depends(get_scope)):
    if not scope.can_see_municipality(body.municipality_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Нет доступа к муниципалитету")
    org = Organization(**body.model_dump())
    scope.db.add(org)
    scope.db.flush()
    audit(scope.db, user, "organization_created", entity="organization", entity_id=org.id,
          request=request)
    scope.db.commit()
    return {"id": org.id}


@router.get("/organizations/{org_id}")
def get_organization(org_id: int, scope: Scope = Depends(get_scope)):
    org = scope.get_org(org_id)
    report = analytics.load_reports(scope.db, [org.id])[0]
    return {
        **report_details(report),
        "address": org.address,
        "external_id": org.external_id,
        "buildings": [BuildingOut.model_validate(b) for b in org.buildings],
        "enrollments": [
            EnrollmentOut.model_validate(e)
            for e in sorted(org.enrollments, key=lambda e: (-e.academic_year, e.level))
        ],
    }


@router.delete("/organizations/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_organization(org_id: int, request: Request,
                        user: User = Depends(require_roles(Role.admin)),
                        scope: Scope = Depends(get_scope)):
    org = scope.get_org(org_id)
    audit(scope.db, user, "organization_deleted", entity="organization", entity_id=org.id,
          details={"name": org.name}, request=request)
    scope.db.delete(org)
    scope.db.commit()


@router.get("/organizations/{org_id}/forecast")
def get_forecast(org_id: int, scope: Scope = Depends(get_scope)):
    org = scope.get_org(org_id)
    return forecast.forecast_organization(
        org.org_type, org.enrollments, org.buildings, analytics.load_rules(scope.db)
    )


# --- здания и контингент -------------------------------------------------------------


@router.post("/organizations/{org_id}/buildings", response_model=BuildingOut,
             status_code=status.HTTP_201_CREATED)
def add_building(org_id: int, body: BuildingIn, request: Request,
                 user: User = Depends(require_roles(*EDITORS)),
                 scope: Scope = Depends(get_scope)):
    org = scope.get_org(org_id)
    building = Building(organization_id=org.id, **body.model_dump())
    scope.db.add(building)
    audit(scope.db, user, "building_added", entity="organization", entity_id=org.id,
          request=request)
    scope.db.commit()
    return building


@router.delete("/buildings/{building_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_building(building_id: int, request: Request,
                    user: User = Depends(require_roles(*EDITORS)),
                    scope: Scope = Depends(get_scope)):
    building = scope.db.get(Building, building_id)
    if building is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Здание не найдено")
    scope.get_org(building.organization_id)
    audit(scope.db, user, "building_deleted", entity="organization",
          entity_id=building.organization_id, request=request)
    scope.db.delete(building)
    scope.db.commit()


@router.put("/organizations/{org_id}/enrollments", response_model=EnrollmentOut)
def upsert_enrollment(org_id: int, body: EnrollmentIn, request: Request,
                      user: User = Depends(require_roles(*EDITORS)),
                      scope: Scope = Depends(get_scope)):
    """Строка контингента однозначно задаётся годом, ступенью и формой обучения."""
    org = scope.get_org(org_id)
    row = scope.db.scalar(select(Enrollment).where(
        Enrollment.organization_id == org.id,
        Enrollment.academic_year == body.academic_year,
        Enrollment.level == body.level,
        Enrollment.study_form == body.study_form,
    ))
    if row is None:
        row = Enrollment(organization_id=org.id)
        scope.db.add(row)
    for key, value in body.model_dump().items():
        setattr(row, key, value)
    audit(scope.db, user, "enrollment_saved", entity="organization", entity_id=org.id,
          details={"year": body.academic_year, "level": body.level}, request=request)
    scope.db.commit()
    return row


@router.delete("/enrollments/{enrollment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_enrollment(enrollment_id: int, request: Request,
                      user: User = Depends(require_roles(*EDITORS)),
                      scope: Scope = Depends(get_scope)):
    row = scope.db.get(Enrollment, enrollment_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Запись не найдена")
    scope.get_org(row.organization_id)
    audit(scope.db, user, "enrollment_deleted", entity="organization",
          entity_id=row.organization_id, request=request)
    scope.db.delete(row)
    scope.db.commit()


# --- штатное расписание --------------------------------------------------------------


@router.get("/organizations/{org_id}/positions", response_model=list[PositionOut])
def list_positions(org_id: int, scope: Scope = Depends(get_scope)):
    org = scope.get_org(org_id)
    return scope.db.scalars(
        select(StaffPosition)
        .where(StaffPosition.organization_id == org.id)
        .order_by(StaffPosition.category, StaffPosition.title, StaffPosition.id)
    ).all()


@router.post("/organizations/{org_id}/positions", response_model=PositionOut,
             status_code=status.HTTP_201_CREATED)
def add_position(org_id: int, body: PositionIn, request: Request,
                 user: User = Depends(require_roles(*EDITORS)),
                 scope: Scope = Depends(get_scope)):
    org = scope.get_org(org_id)
    function = BY_CODE.get(body.function_code or "") or classify_title(body.title)
    data = body.model_dump(exclude={"function_code", "is_vacant"})
    position = StaffPosition(
        organization_id=org.id,
        category=function.category.value,
        function_code=function.code,
        # У введённой вручную занятой ставки исходного ФИО нет — ставим метку
        employee_ref=None if body.is_vacant else "manual",
        **data,
    )
    scope.db.add(position)
    audit(scope.db, user, "position_added", entity="organization", entity_id=org.id,
          details={"title": body.title, "rate": str(body.rate)}, request=request)
    scope.db.commit()
    return position


@router.delete("/positions/{position_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_position(position_id: int, request: Request,
                    user: User = Depends(require_roles(*EDITORS)),
                    scope: Scope = Depends(get_scope)):
    position = scope.db.get(StaffPosition, position_id)
    if position is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Строка не найдена")
    scope.get_org(position.organization_id)
    audit(scope.db, user, "position_deleted", entity="organization",
          entity_id=position.organization_id,
          details={"title": position.title, "rate": str(position.rate)}, request=request)
    scope.db.delete(position)
    scope.db.commit()


# --- импорт выгрузок -----------------------------------------------------------------


@router.post("/import/{kind}")
def import_file(kind: str, request: Request, file: UploadFile = File(...),
                replace: bool = Form(True),
                user: User = Depends(require_roles(*EDITORS)),
                scope: Scope = Depends(get_scope)):
    if kind not in ("staffing", "enrollment"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Неизвестный тип импорта")
    content = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Файл больше 20 МБ")

    db = scope.db
    org_ids = scope.org_ids()
    allowed = None if org_ids is None else set(org_ids)
    try:
        rows = importer.read_table(file.filename or "", content)
        if kind == "staffing":
            result = importer.import_staffing(db, rows, allowed_org_ids=allowed, replace=replace)
        else:
            result = importer.import_enrollment(db, rows, allowed_org_ids=allowed)
    except importer.ImportFormatError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    audit(db, user, f"import_{kind}", details={
        "file": file.filename, "imported": result.imported, "skipped": result.skipped,
    }, request=request)
    db.commit()
    return asdict(result)
