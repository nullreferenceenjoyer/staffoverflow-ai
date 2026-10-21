"""Нормативная численность: анализ, данные учреждения, импорт и заявки из анализа.

Видят раздел администратор, аналитик (регион), специалист управления (свой
муниципалитет), директор (своё учреждение) и наблюдатель (только сводка).
Сотрудник, хозслужба и бригады раздела не видят.
"""

from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.deps import Scope, audit, get_scope
from app.models import Municipality, Organization, PersonnelGroup, Role, StaffingLine
from app.schemas import (
    PositionIn,
    RecalculateIn,
    StaffingDataIn,
    StaffingRequestIn,
    WorkloadSettingsIn,
)
from app.services import (
    app_settings,
    cleaning,
    helpdesk,
    norms,
    payroll,
    staffing,
    staffing_analysis,
    summary,
    workload,
)
from app.services.spreadsheet import TableError, build_template, read_table
from app.services.staffing_analysis import (
    BASIS_TITLES,
    CATEGORY_TITLES,
    STATUS_TITLES,
    current_year,
)

router = APIRouter(prefix="/staffing", tags=["staffing"])
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
STATUS_ORDER = {"deficit": 0, "surplus": 0, "warning": 0, "no_data": 1, "normal": 2}


def viewer(scope: Scope = Depends(get_scope)) -> Scope:
    if not staffing.can_view(scope.user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Раздел недоступен для вашей роли")
    return scope


def _details(scope: Scope) -> None:
    if scope.user.role == Role.observer:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Наблюдателю доступна только сводка без деталей")


def _editor(scope: Scope) -> None:
    if scope.user.role not in staffing.DATA_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Менять данные может директор, "
                                                       "специалист управления или аналитик")


def _year(year: str | None) -> str:
    year = year or current_year()
    try:
        staffing_analysis.period(year)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return year


def _check(value: str, allowed, what: str) -> str:
    if value not in allowed:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Неизвестное значение: {what}")
    return value


@router.get("/meta")
def meta(scope: Scope = Depends(viewer)):
    user, db = scope.user, scope.db
    this_year = current_year()
    start = int(this_year[:4])
    years = sorted(set(staffing_analysis.years_with_data(db))
                   | {this_year, f"{start + 1}/{start + 2}"}, reverse=True)
    if scope.is_regional:
        municipalities = db.scalars(select(Municipality).order_by(Municipality.name)).all()
    elif user.role == Role.municipal_specialist:
        municipalities = db.scalars(select(Municipality)
                                    .where(Municipality.id == user.municipality_id)).all()
    else:
        municipalities = []
    organization = (db.get(Organization, user.organization_id)
                    if user.role == Role.director and user.organization_id else None)
    groups = db.scalars(select(PersonnelGroup).order_by(PersonnelGroup.sort_order,
                                                        PersonnelGroup.id)).all()
    every = db.scalars(select(Municipality.name).order_by(Municipality.id)).all()
    return {
        # Система работает в одном округе — его название показывается вместо «регион»
        "okrug": every[0] if len(every) == 1 else None,
        "years": years, "current_year": this_year,
        "categories": [{"code": k, "title": v} for k, v in CATEGORY_TITLES.items()],
        "bases": [{"code": k, "title": v} for k, v in BASIS_TITLES.items()],
        "statuses": [{"code": k.value, "title": v} for k, v in STATUS_TITLES.items()],
        "metrics": [{"code": k, "title": v} for k, v in norms.METRICS.items()],
        "institution_types": [{"code": k, "title": v} for k, v in norms.INSTITUTION_TYPES.items()],
        "scope_levels": [{"code": k, "title": v} for k, v in norms.SCOPE_LEVELS.items()],
        "doc_types": list(norms.DOC_TYPES),
        "doc_statuses": [{"code": k, "title": v} for k, v in norms.DOC_STATUSES.items()],
        "groups": [staffing.group_out(g) for g in groups],
        "municipalities": [{"id": m.id, "name": m.name} for m in municipalities],
        "organization": ({"id": organization.id, "name": organization.name,
                          "org_type": organization.org_type} if organization else None),
        "permissions": {
            "details": user.role != Role.observer,
            "edit_data": user.role in staffing.DATA_ROLES,
            "create_requests": user.role != Role.observer,
            "edit_norms": user.role in staffing.NORM_ROLES,
            "edit_regional_norms": user.role in (Role.admin, Role.regional_analyst),
            "import": user.role in staffing.IMPORT_ROLES,
            "import_norms": user.role in (Role.admin, Role.regional_analyst),
            "edit_workload": user.role in staffing.NORM_ROLES,
        },
    }


def _orgs(scope: Scope, municipality_id: int | None = None,
          organization_id: int | None = None) -> list[Organization]:
    query = scope.organizations().options(selectinload(Organization.municipality))
    if municipality_id is not None:
        query = query.where(Organization.municipality_id == municipality_id)
    if organization_id is not None:
        query = query.where(Organization.id == organization_id)
    return list(scope.db.scalars(query.order_by(Organization.name)))


@router.get("/analysis")
def analysis(year: str | None = None, category: str = "aup", basis: str = "occupied",
             municipality_id: int | None = None, organization_id: int | None = None,
             scope: Scope = Depends(viewer)):
    """Таблица учреждений: норматив, факт, отклонение, статус и что не так."""
    year = _year(year)
    _check(category, CATEGORY_TITLES, "категория")
    _check(basis, BASIS_TITLES, "основа сравнения")
    orgs = _orgs(scope, municipality_id, organization_id)
    ids = [o.id for o in orgs]
    staffing_analysis.ensure(scope.db, year, ids)
    rows = staffing.current_rows(scope.db, year, ids, category=category, basis=basis)
    totals = {r.organization_id: r for r in rows if r.personnel_group_id is None}
    problems: dict[int, list[dict]] = {}
    for r in rows:
        if r.personnel_group_id is not None and r.status != "normal":
            problems.setdefault(r.organization_id, []).append({
                "group": r.group.name if r.group else "", "status": r.status,
                "deviation": float(r.deviation_fte) if r.deviation_fte is not None else None,
                "reasons": r.missing_reasons or []})
    items = []
    for org in orgs:
        total = totals.get(org.id)
        if total is None:
            continue
        found = sorted(problems.get(org.id, []), key=lambda p: (
            p["status"] == "no_data", -abs(p["deviation"] or 0)))
        items.append({
            "organization_id": org.id, "organization": org.name, "org_type": org.org_type,
            "municipality_id": org.municipality_id, "municipality": org.municipality.name,
            **staffing.result_out(total), "problems": found,
        })
    items.sort(key=lambda i: (STATUS_ORDER[i["status"]], -abs(i["deviation"] or 0),
                              i["organization"]))
    summary = dict.fromkeys(STATUS_ORDER, 0)
    for item in items:
        summary[item["status"]] += 1
    calculated = [r.calculated_at for r in totals.values()]
    return {"year": year, "category": category, "basis": basis, "summary": summary,
            "calculated_at": max(calculated) if calculated else None, "items": items}


@router.get("/institutions/{org_id}/analysis")
def institution_analysis(org_id: int, year: str | None = None, scope: Scope = Depends(viewer)):
    """Всё по учреждению: обе категории и обе основы, разбивка по группам и формулы."""
    _details(scope)
    year = _year(year)
    org = scope.get_org(org_id)
    staffing_analysis.ensure(scope.db, year, [org.id])
    rows = staffing.current_rows(scope.db, year, [org.id])
    result: dict = {category: {basis: {"total": None, "groups": []} for basis in BASIS_TITLES}
                    for category in CATEGORY_TITLES}
    for row in rows:
        item = staffing.result_out(row)
        slot = result[row.top_category][row.basis]
        if row.personnel_group_id is None:
            slot["total"] = item
        else:
            slot["groups"].append(item)
    documents = staffing.documents_of([g for c in result.values() for b in c.values()
                                       for g in b["groups"]])
    any_total = next((r for r in rows if r.personnel_group_id is None), None)
    return {
        "organization_id": org.id, "organization": org.name, "org_type": org.org_type,
        "municipality": org.municipality.name, "year": year, "analysis": result,
        "documents": documents,
        "metrics": any_total.metrics_snapshot if any_total else {},
        "calculated_at": any_total.calculated_at if any_total else None,
        "can_edit": scope.user.role in staffing.DATA_ROLES,
        "buildings": len(org.buildings),
    }


@router.get("/institutions/{org_id}/data")
def institution_data(org_id: int, year: str | None = None, scope: Scope = Depends(viewer)):
    _details(scope)
    return staffing.org_data(scope.db, scope.get_org(org_id), _year(year))


@router.put("/institutions/{org_id}/data")
def save_institution_data(org_id: int, body: StaffingDataIn, request: Request,
                          scope: Scope = Depends(viewer)):
    """Показатели, штатка и занятость учреждения за год одним сохранением."""
    _editor(scope)
    year = _year(body.year)
    org = scope.get_org(org_id)
    db = scope.db
    allowed = {g.id: g for g in staffing.groups_for(db, org)}
    current = staffing.org_data(db, org, year)
    known = {line["id"] for line in current["lines"]}
    values = {}
    for line in body.lines or []:
        if line.group_id not in allowed and line.group_id not in known:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "Группа не применяется к этому учреждению")
        if line.group_id in values:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "Группа указана дважды")
        values[line.group_id] = (line.approved_fte, line.occupied_fte, line.salary_rub)
    changed = staffing.save_metrics(db, org, year, {
        "students_count": body.students_count, "classes_count": body.classes_count,
        "groups_count": body.groups_count,
        "total_area_m2": None if body.total_area_m2 is None else round(body.total_area_m2, 1),
        "rooms_count": body.rooms_count,
    })
    schedule = staffing.get_schedule(db, org, year)
    previous_status = schedule.status
    # Без строк форма меняет только показатели и статус: должности правятся по одной
    count = (staffing.set_lines(schedule, values, replace_all=True) if body.lines is not None
             else len(schedule.lines))
    staffing.set_status(schedule, body.status)
    schedule.comment = body.comment or None
    db.flush()
    version = payroll.snapshot(db, schedule, scope.user, "manual")
    staffing_analysis.recalculate(db, year, [org.id])
    audit(db, scope.user, "staffing_data_saved", entity="organization", entity_id=org.id,
          details={"year": year, "metrics_changed": changed, "lines": count,
                   "status": body.status, "previous_status": previous_status,
                   "payroll_approved": None if version is None or version.payroll_approved
                   is None else float(version.payroll_approved)},
          request=request)
    if body.status == "approved" and previous_status != "approved":
        audit(db, scope.user, "staffing_schedule_approved", entity="organization",
              entity_id=org.id, details={"year": year}, request=request)
    db.commit()
    return staffing.org_data(db, org, year)


@router.post("/analysis/recalculate")
def recalculate(body: RecalculateIn, request: Request, scope: Scope = Depends(viewer)):
    _editor(scope)
    year = _year(body.year)
    if body.organization_id is not None:
        ids = [scope.get_org(body.organization_id).id]
    else:
        ids = [o.id for o in _orgs(scope)]
    count = staffing_analysis.recalculate(scope.db, year, ids)
    audit(scope.db, scope.user, "staffing_recalculated",
          entity="organization" if body.organization_id else None,
          entity_id=body.organization_id, details={"year": year, "organizations": count},
          request=request)
    scope.db.commit()
    return {"organizations": count}


def _position_saved(scope: Scope, org: Organization, schedule, year: str, action: str,
                    comment: str, details: dict, request: Request) -> dict:
    db = scope.db
    db.flush()
    payroll.snapshot(db, schedule, scope.user, "manual", comment=comment)
    staffing_analysis.recalculate(db, year, [org.id])
    audit(db, scope.user, action, entity="organization", entity_id=org.id,
          details={"year": year, **details}, request=request)
    db.commit()
    return payroll.institution(db, org, year, "occupied")


def _group_for(scope: Scope, org: Organization, group_id: int) -> PersonnelGroup:
    group = scope.db.get(PersonnelGroup, group_id)
    if group is None or not staffing_analysis.group_applies(group, org):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Эта группа должностей не применяется к учреждению")
    return group


@router.post("/institutions/{org_id}/positions", status_code=status.HTTP_201_CREATED)
def add_position(org_id: int, body: PositionIn, request: Request,
                 scope: Scope = Depends(viewer)):
    """Добавить должность в штатку."""
    _editor(scope)
    year = _year(body.year)
    org = scope.get_org(org_id)
    group = _group_for(scope, org, body.group_id)
    schedule = staffing.get_schedule(scope.db, org, year)
    if any((line.position or staffing.default_position(group)).lower() == body.position.lower()
           and line.personnel_group_id == group.id for line in schedule.lines):
        raise HTTPException(status.HTTP_409_CONFLICT, "Такая должность в штатке уже есть — "
                                                      "измените её ставки")
    schedule.lines.append(StaffingLine(
        personnel_group_id=group.id, position=body.position,
        approved_fte=norms.dec(body.approved_fte), occupied_fte=norms.dec(body.occupied_fte),
        salary_rub=norms.dec(body.salary_rub)))
    return _position_saved(scope, org, schedule, year, "staffing_position_added",
                           f"Добавлена должность: {body.position}",
                           {"position": body.position, "approved_fte": body.approved_fte},
                           request)


def _line(scope: Scope, org: Organization, year: str, line_id: int):
    schedule = staffing.get_schedule(scope.db, org, year)
    line = next((x for x in schedule.lines if x.id == line_id), None)
    if line is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Такой должности в штатке нет")
    return schedule, line


@router.put("/institutions/{org_id}/positions/{line_id}")
def update_position(org_id: int, line_id: int, body: PositionIn, request: Request,
                    scope: Scope = Depends(viewer)):
    """Изменить должность: название, группу, ставки, занятость, оклад."""
    _editor(scope)
    year = _year(body.year)
    org = scope.get_org(org_id)
    group = _group_for(scope, org, body.group_id)
    schedule, line = _line(scope, org, year, line_id)
    before = (line.position, float(line.approved_fte),
              None if line.occupied_fte is None else float(line.occupied_fte))
    line.personnel_group_id = group.id
    line.position = body.position
    line.approved_fte = norms.dec(body.approved_fte)
    line.occupied_fte = norms.dec(body.occupied_fte)
    line.salary_rub = norms.dec(body.salary_rub)
    return _position_saved(scope, org, schedule, year, "staffing_position_updated",
                           f"Изменена должность: {body.position}",
                           {"line_id": line_id, "before": before,
                            "after": [body.position, body.approved_fte, body.occupied_fte]},
                           request)


@router.delete("/institutions/{org_id}/positions/{line_id}")
def delete_position(org_id: int, line_id: int, request: Request, year: str | None = None,
                    scope: Scope = Depends(viewer)):
    """Убрать должность из штатки: такой должности в учреждении нет."""
    _editor(scope)
    year = _year(year)
    org = scope.get_org(org_id)
    schedule, line = _line(scope, org, year, line_id)
    name = staffing.position_name(line, scope.db.get(PersonnelGroup, line.personnel_group_id))
    removed = float(line.approved_fte or 0)
    schedule.lines.remove(line)
    return _position_saved(scope, org, schedule, year, "staffing_position_deleted",
                           f"Удалена должность: {name}",
                           {"line_id": line_id, "position": name, "approved_fte": removed},
                           request)


@router.delete("/institutions/{org_id}/lines/{group_id}")
def delete_line(org_id: int, group_id: int, request: Request, year: str | None = None,
                scope: Scope = Depends(viewer)):
    """Убрать должность из штатки: такой должности в учреждении нет."""
    _editor(scope)
    year = _year(year)
    org = scope.get_org(org_id)
    db = scope.db
    schedule = staffing.get_schedule(db, org, year)
    before = [line for line in schedule.lines if line.personnel_group_id == group_id]
    if not before:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Такой должности в штатке нет")
    removed = sum(float(line.approved_fte or 0) for line in before)
    schedule.lines[:] = [line for line in schedule.lines if line.personnel_group_id != group_id]
    db.flush()
    group = db.get(PersonnelGroup, group_id)
    payroll.snapshot(db, schedule, scope.user, "manual",
                     comment=f"Удалена должность: {group.name if group else group_id}")
    staffing_analysis.recalculate(db, year, [org.id])
    audit(db, scope.user, "staffing_line_deleted", entity="organization", entity_id=org.id,
          details={"year": year, "group_id": group_id, "approved_fte": removed},
          request=request)
    db.commit()
    return payroll.institution(db, org, year, "occupied")


# --- итог и загрузка хозслужбы -------------------------------------------------------


def _days(days: int) -> int:
    return days if days in workload.PERIODS else 90


@router.get("/cleaning")
def cleaning_view(year: str | None = None, days: int = 90, municipality_id: int | None = None,
                  scope: Scope = Depends(viewer)):
    """Уборщики: норматив по кабинетам и площади, сколько есть, сколько на одного."""
    _details(scope)
    orgs = _orgs(scope, municipality_id)
    return cleaning.build(scope.db, orgs, _year(year), _days(days),
                          territory=scope.user.role != Role.director)


@router.get("/summary")
def summary_view(year: str | None = None, days: int = 90,
                 municipality_id: int | None = None, scope: Scope = Depends(viewer)):
    """Сколько ставок можно сократить и какие должности: по нормативу, вакансиям и загрузке."""
    orgs = _orgs(scope, municipality_id)
    data = summary.build(scope.db, orgs, _year(year), _days(days),
                         territory=scope.user.role != Role.director)
    data["organization"] = (
        {"id": orgs[0].id, "name": orgs[0].name}
        if scope.user.role == Role.director and orgs else None)
    if scope.user.role == Role.observer:
        # Наблюдателю — обезличенная сводка: без фамилий
        for unit in [*data["brigades"], *data["onsite"]]:
            unit["members"], unit["candidates"] = [], []
    return data


@router.get("/workload")
def workload_view(days: int = 90, municipality_id: int | None = None,
                  scope: Scope = Depends(viewer)):
    """Загрузка бригад и хозотделов: часы работы, дорога, заявки, сколько людей нужно."""
    _details(scope)
    orgs = _orgs(scope, municipality_id)
    data = workload.analyze(scope.db, orgs, _days(days),
                            territory=scope.user.role != Role.director)
    data["titles"] = app_settings.WORKLOAD_TITLES
    data["can_edit"] = scope.user.role in staffing.NORM_ROLES
    return data


@router.put("/workload/settings")
def save_workload_settings(body: WorkloadSettingsIn, request: Request,
                           scope: Scope = Depends(viewer)):
    if scope.user.role not in staffing.NORM_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Нормы загрузки меняет управление "
                                                       "образования или администратор")
    before = app_settings.workload(scope.db)
    saved = app_settings.save_workload(scope.db, body.model_dump())
    audit(scope.db, scope.user, "workload_settings_saved",
          details={"before": before, "after": saved}, request=request)
    scope.db.commit()
    return saved


# --- дашборд, штатка и факт ----------------------------------------------------------


@router.get("/dashboard")
def dashboard(year: str | None = None, basis: str = "occupied",
              municipality_id: int | None = None, scope: Scope = Depends(viewer)):
    """Сводка: статусы, дефицит и излишек в ставках и рублях, ФОТ, изменения штаток."""
    _check(basis, BASIS_TITLES, "основа сравнения")
    orgs = _orgs(scope, municipality_id)
    return payroll.dashboard(scope.db, orgs, _year(year), basis)


@router.get("/schedules")
def schedules(year: str | None = None, municipality_id: int | None = None,
              scope: Scope = Depends(viewer)):
    """Штатка и занятость по учреждениям: ставки, вакансии, ФОТ, последнее изменение."""
    return payroll.territory(scope.db, _orgs(scope, municipality_id), _year(year))


@router.get("/institutions/{org_id}/schedule")
def institution_schedule(org_id: int, year: str | None = None, basis: str = "occupied",
                         scope: Scope = Depends(viewer)):
    """Штатка учреждения по группам: ставки, оклады, ФОТ, норматив и история изменений."""
    _details(scope)
    _check(basis, BASIS_TITLES, "основа сравнения")
    data = payroll.institution(scope.db, scope.get_org(org_id), _year(year), basis)
    data["can_edit"] = scope.user.role in staffing.DATA_ROLES
    return data


# --- заявка из анализа ---------------------------------------------------------------


def _row_for(scope: Scope, org: Organization, year: str, category: str, basis: str,
             group_id: int | None):
    staffing_analysis.ensure(scope.db, year, [org.id])
    row = staffing.find_row(scope.db, org.id, year, category, basis, group_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Результат анализа не найден — "
                                                       "пересчитайте анализ")
    return row


@router.get("/request-draft")
def request_draft(organization_id: int, year: str, category: str, basis: str = "occupied",
                  group_id: int | None = None, scope: Scope = Depends(viewer)):
    """Что получится, если создать заявку: тема, адресат и текст по шаблону."""
    _details(scope)
    _check(category, CATEGORY_TITLES, "категория")
    _check(basis, BASIS_TITLES, "основа сравнения")
    org = scope.get_org(organization_id)
    row = _row_for(scope, org, _year(year), category, basis, group_id)
    return staffing.request_draft(scope.db, org, row, scope.user)


@router.post("/requests", status_code=status.HTTP_201_CREATED)
def create_request(body: StaffingRequestIn, request: Request, scope: Scope = Depends(viewer)):
    """Обычная заявка, предзаполненная по анализу и связанная с его результатом."""
    _details(scope)
    user, db = scope.user, scope.db
    org = scope.get_org(body.organization_id)
    row = _row_for(scope, org, _year(body.year), body.category, body.basis, body.group_id)
    draft = staffing.request_draft(db, org, row, user)
    title = (body.title or "").strip() or draft["title"]
    text = (body.text or "").strip() or draft["text"]
    if len(title) < 5:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Заголовок слишком короткий")
    item = helpdesk.create(db, user, org, title=title, text=text, topic=draft["topic"],
                           role=draft["routed_role"])
    staffing.link(db, item, row, user)
    audit(db, user, "request_created", entity="request", entity_id=item.id,
          details={"topic": item.topic, "kind": item.kind, "assignee_id": item.assignee_id,
                   "by": "staffing"}, request=request)
    audit(db, user, "request_staffing_linked", entity="request", entity_id=item.id,
          details={"result_id": row.id, "status": row.status, "year": row.academic_year,
                   "category": row.top_category, "group_id": row.personnel_group_id},
          request=request)
    db.commit()
    return {"request_id": item.id, "routed_role": item.routed_role,
            "assignee": item.assignee.full_name if item.assignee else None}


# --- импорт и шаблоны ----------------------------------------------------------------

IMPORTERS = {"metrics": staffing.METRIC_COLUMNS, "lines": staffing.LINE_COLUMNS,
             "norms": staffing.NORM_COLUMNS}


@router.post("/import/{kind}")
async def import_table(kind: str, request: Request, file: UploadFile = File(...),
                       scope: Scope = Depends(viewer)):
    if kind not in IMPORTERS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Нет такой загрузки")
    user, db = scope.user, scope.db
    allowed = (Role.admin, Role.regional_analyst) if kind == "norms" else staffing.IMPORT_ROLES
    if user.role not in allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Загрузка недоступна для вашей роли")
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Файл больше 10 МБ")
    try:
        rows = read_table(content, file.filename or "", IMPORTERS[kind])
    except TableError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    if kind == "norms":
        result = staffing.import_norms(db, rows)
        db.flush()
        staffing_analysis.recalculate_all(db)
    else:
        if kind == "lines":
            result, touched = staffing.import_lines(db, rows, scope.organizations(), user)
        else:
            result, touched = staffing.import_metrics(db, rows, scope.organizations())
        db.flush()
        by_year: dict[str, list[int]] = {}
        for org_id, year in touched:
            by_year.setdefault(year, []).append(org_id)
        for year, ids in by_year.items():
            staffing_analysis.recalculate(db, year, ids)
    audit(db, user, f"staffing_import_{kind}", details={
        "file": file.filename, "created": result.created, "updated": result.updated,
        "skipped": result.skipped}, request=request)
    db.commit()
    return result.as_dict()


@router.get("/templates/{kind}.xlsx")
def template(kind: str, scope: Scope = Depends(viewer)):
    if kind not in staffing.TEMPLATES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Нет такого шаблона")
    title, columns, examples, help_rows = staffing.TEMPLATES[kind]
    content = build_template(columns, examples, help_rows, title)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="staffing-{kind}-'
                                        f'{date.today():%Y%m%d}.xlsx"'},
    )
