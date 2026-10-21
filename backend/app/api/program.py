"""Программа оптимизации: итог по документам, уволенные, должности, уборщицы, хозотдел.

Директор видит свою школу (и общий итог округа), управление образования и администратор —
все школы. Уволенных ведёт управление и администратор; три цифры для расчёта уборщиц
и ставки хозотдела вносит директор своей школы или управление.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.staffing import viewer
from app.deps import Scope, audit
from app.models import Dismissal, InstitutionMetrics, Organization, Role
from app.schemas import (
    CleaningInputIn,
    CleaningNormIn,
    DismissalIn,
    ExplainIn,
    ExplainWarmIn,
    MaintenanceInputIn,
)
from app.services import (
    app_settings,
    explain,
    llm,
    program,
    simple,
    staffing,
    staffing_analysis,
)
from app.services.norms import dec

router = APIRouter(prefix="/program", tags=["program"])
DEPARTMENT = (Role.admin, Role.regional_analyst, Role.municipal_specialist)


def _orgs(scope: Scope) -> list[Organization]:
    return list(scope.db.scalars(scope.organizations()
                                 .options(selectinload(Organization.municipality))
                                 .order_by(Organization.name)))


def _year(year: str | None) -> str:
    return year or staffing_analysis.current_year()


@router.get("/overview")
def overview(scope: Scope = Depends(viewer)):
    """Итог программы и школы, которые видит пользователь."""
    ids = None if scope.user.role in DEPARTMENT or scope.is_regional else \
        [o.id for o in _orgs(scope)]
    data = program.overview(scope.db, ids)
    data["own_school"] = scope.user.role == Role.director
    if scope.user.role == Role.observer:
        for school in data["schools"]:
            for person in school["dismissals"]:
                person["full_name"] = "—"
    return data


@router.get("/positions")
def positions(scope: Scope = Depends(viewer)):
    return program.positions(scope.db)


# --- уволенные -----------------------------------------------------------------------


def _department(scope: Scope) -> None:
    if scope.user.role not in DEPARTMENT:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Список уволенных ведёт управление "
                                                       "образования или администратор")


@router.get("/dismissals")
def dismissals(scope: Scope = Depends(viewer)):
    ids = [o.id for o in _orgs(scope)]
    rows = scope.db.scalars(select(Dismissal).where(Dismissal.organization_id.in_(ids))
                            .options(selectinload(Dismissal.organization))
                            .order_by(Dismissal.dismissed_on, Dismissal.id))
    items = [program.dismissal_out(r) for r in rows]
    if scope.user.role == Role.observer:
        for item in items:
            item["full_name"] = "—"
    return {"items": items, "can_edit": scope.user.role in DEPARTMENT,
            "bases": program.BASIS_TITLES}


def _apply(item: Dismissal, body: DismissalIn) -> None:
    for key, value in body.model_dump(exclude={"apply_to_schedule"}).items():
        setattr(item, key, value.strip() or None if isinstance(value, str) else value)
    item.full_name = " ".join(body.full_name.split())
    item.position = " ".join(body.position.split())
    item.fte = dec(body.fte)


@router.post("/dismissals", status_code=status.HTTP_201_CREATED)
def add_dismissal(body: DismissalIn, request: Request, scope: Scope = Depends(viewer)):
    _department(scope)
    scope.get_org(body.organization_id)
    item = Dismissal()
    _apply(item, body)
    scope.db.add(item)
    scope.db.flush()
    if body.apply_to_schedule:
        program.apply_dismissal(scope.db, item, scope.user, _year(None))
    audit(scope.db, scope.user, "dismissal_added", entity="dismissal", entity_id=item.id,
          details={"organization_id": item.organization_id, "fte": body.fte,
                   "basis": body.basis, "order": body.order_number}, request=request)
    scope.db.commit()
    scope.db.refresh(item)
    return program.dismissal_out(item)


def _get(scope: Scope, item_id: int) -> Dismissal:
    item = scope.db.get(Dismissal, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Запись не найдена")
    scope.get_org(item.organization_id)
    return item


@router.put("/dismissals/{item_id}")
def update_dismissal(item_id: int, body: DismissalIn, request: Request,
                     scope: Scope = Depends(viewer)):
    _department(scope)
    item = _get(scope, item_id)
    scope.get_org(body.organization_id)
    # Школа, должность или ставка могли поменяться — учёт в штатке делается заново
    program.revert_dismissal(scope.db, item, scope.user)
    _apply(item, body)
    scope.db.flush()
    if body.apply_to_schedule:
        program.apply_dismissal(scope.db, item, scope.user, _year(None))
    audit(scope.db, scope.user, "dismissal_updated", entity="dismissal", entity_id=item.id,
          details={"fte": body.fte, "basis": body.basis, "order": body.order_number},
          request=request)
    scope.db.commit()
    scope.db.refresh(item)
    return program.dismissal_out(item)


@router.delete("/dismissals/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dismissal(item_id: int, request: Request, scope: Scope = Depends(viewer)):
    _department(scope)
    item = _get(scope, item_id)
    # Запись удалили — увольнения не было: ставка снова занята
    program.revert_dismissal(scope.db, item, scope.user)
    audit(scope.db, scope.user, "dismissal_deleted", entity="dismissal", entity_id=item.id,
          details={"organization_id": item.organization_id, "order": item.order_number},
          request=request)
    scope.db.delete(item)
    scope.db.commit()


@router.post("/dismissals/{item_id}/apply")
def apply_dismissal(item_id: int, request: Request, scope: Scope = Depends(viewer)):
    """Учесть увольнение в штатке — для записей, загруженных из документов «до»."""
    _department(scope)
    item = _get(scope, item_id)
    if not program.apply_dismissal(scope.db, item, scope.user, _year(None)):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"В штатке школы нет должности «{item.position}» с занятыми "
                            "ставками — поправьте должность в записи или штатку школы")
    audit(scope.db, scope.user, "dismissal_applied", entity="dismissal", entity_id=item.id,
          details={"fte": float(item.applied_fte)}, request=request)
    scope.db.commit()
    scope.db.refresh(item)
    return program.dismissal_out(item)


@router.delete("/dismissals/{item_id}/apply")
def revert_dismissal(item_id: int, request: Request, scope: Scope = Depends(viewer)):
    _department(scope)
    item = _get(scope, item_id)
    program.revert_dismissal(scope.db, item, scope.user)
    audit(scope.db, scope.user, "dismissal_reverted", entity="dismissal", entity_id=item.id,
          request=request)
    scope.db.commit()
    scope.db.refresh(item)
    return program.dismissal_out(item)


# --- уборщицы и хозотдел -------------------------------------------------------------


def _metrics(scope: Scope, org: Organization, year: str) -> InstitutionMetrics:
    staffing_analysis.period(year)
    metrics = scope.db.scalar(select(InstitutionMetrics).where(
        InstitutionMetrics.organization_id == org.id, InstitutionMetrics.academic_year == year))
    if metrics is None:
        start, end = staffing_analysis.period(year)
        metrics = InstitutionMetrics(organization_id=org.id, academic_year=year,
                                     period_start=start, period_end=end, source="manual")
        scope.db.add(metrics)
    return metrics


def _school_editor(scope: Scope) -> None:
    if scope.user.role not in staffing.DATA_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Данные школы вносит директор или "
                                                       "управление образования")


@router.get("/cleaning")
def cleaning(year: str | None = None, scope: Scope = Depends(viewer)):
    data = simple.cleaning(scope.db, _orgs(scope), _year(year))
    data["can_edit"] = scope.user.role in staffing.DATA_ROLES
    data["can_edit_norm"] = scope.user.role in DEPARTMENT
    return data


@router.put("/cleaning/{org_id}")
def save_cleaning(org_id: int, body: CleaningInputIn, request: Request,
                  scope: Scope = Depends(viewer)):
    _school_editor(scope)
    org = scope.get_org(org_id)
    metrics = _metrics(scope, org, body.year)
    metrics.classes_count = body.classes_count
    metrics.total_area_m2 = dec(body.total_area_m2)
    metrics.cleaners_fte = dec(body.cleaners_fte)
    scope.db.flush()
    staffing_analysis.recalculate(scope.db, body.year, [org.id])
    audit(scope.db, scope.user, "cleaning_input_saved", entity="organization",
          entity_id=org.id, details=body.model_dump(), request=request)
    scope.db.commit()
    return simple.cleaning(scope.db, [org], body.year)["items"][0]


@router.put("/cleaning-norm")
def save_cleaning_norm(body: CleaningNormIn, request: Request, scope: Scope = Depends(viewer)):
    if scope.user.role not in DEPARTMENT:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Норму уборщиц задаёт управление "
                                                       "образования")
    saved = app_settings.save_cleaning(scope.db, body.model_dump())
    audit(scope.db, scope.user, "cleaning_norm_saved", details=saved, request=request)
    scope.db.commit()
    return saved


@router.get("/maintenance")
def maintenance(year: str | None = None, days: int = 90, scope: Scope = Depends(viewer)):
    data = simple.maintenance(scope.db, _orgs(scope), _year(year), days,
                              territory=scope.user.role != Role.director)
    data["can_edit"] = scope.user.role in staffing.DATA_ROLES
    data["can_edit_brigades"] = scope.user.role == Role.admin
    if scope.user.role == Role.observer:
        for unit in data["brigades"]:
            unit["members"], unit["candidates"] = [], []
        for school in data["schools"]:
            school["people"] = []
    return data


@router.get("/requests")
def requests_board(days: int = 90, topic: str | None = None, scope: Scope = Depends(viewer)):
    """Дашборд хозяйственных заявок; topic=cleaning — только уборка."""
    data = simple.requests_board(scope.db, _orgs(scope), days, [topic] if topic else None)
    if scope.user.role == Role.observer:
        data["by_assignee"] = []
    return data


@router.get("/maintenance/detail")
def maintenance_detail(brigade_id: int | None = None, organization_id: int | None = None,
                       days: int = 90, year: str | None = None,
                       scope: Scope = Depends(viewer)):
    """Карточка бригады или своего хозотдела школы: люди, школы, заявки, расчёт."""
    if brigade_id is not None:
        data = simple.brigade_detail(scope.db, _orgs(scope), brigade_id, days,
                                     territory=scope.user.role != Role.director)
        if data is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Бригада не найдена")
    elif organization_id is not None:
        data = simple.school_detail(scope.db, scope.get_org(organization_id), _year(year), days)
    else:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Укажите бригаду или школу")
    if scope.user.role == Role.observer:
        # Наблюдатель видит цифры, но не фамилии
        for person in data.get("people", []) + data.get("unit", {}).get("members", []):
            person["name"] = "—"
        for key in ("requests", "brigade_requests"):
            for item in data.get(key, {}).get("recent", []):
                item["assignee"] = None
    return data


@router.put("/maintenance/{org_id}")
def save_maintenance(org_id: int, body: MaintenanceInputIn, request: Request,
                     scope: Scope = Depends(viewer)):
    _school_editor(scope)
    org = scope.get_org(org_id)
    metrics = _metrics(scope, org, body.year)
    metrics.maintenance_fte = dec(body.maintenance_fte)
    audit(scope.db, scope.user, "maintenance_input_saved", entity="organization",
          entity_id=org.id, details=body.model_dump(), request=request)
    scope.db.commit()
    return {"ok": True}


# --- разъяснения ---------------------------------------------------------------------


def _explain_scope(scope: Scope, organization_id: int | None):
    orgs = _orgs(scope)
    if organization_id is not None:
        return orgs, scope.get_org(organization_id)
    if scope.user.role == Role.director and len(orgs) == 1:
        return orgs, orgs[0]
    return orgs, None


@router.post("/explain/warm", status_code=status.HTTP_202_ACCEPTED)
def explain_warm(body: ExplainWarmIn, tasks: BackgroundTasks, scope: Scope = Depends(viewer)):
    """Прогрев: вкладку открыли или сменили школу — модель заранее читает справку, и
    ответ на вопрос начинается почти сразу."""
    if not llm.should_try():
        return {"warm": False}
    orgs, org = _explain_scope(scope, body.organization_id)
    messages = explain.messages(scope.db, orgs, org, "Готов?", body.position, [], _year(None))

    def warm():
        try:
            llm.complete(messages, max_tokens=1)
        except llm.LLMUnavailable:
            pass

    tasks.add_task(warm)
    return {"warm": True}


@router.post("/explain")
def explain_cut(body: ExplainIn, request: Request, scope: Scope = Depends(viewer)):
    """Ответ модели потоком: текст появляется по мере генерации."""
    if not llm.should_try():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            llm.status().get("error") or "Модель недоступна")
    orgs, org = _explain_scope(scope, body.organization_id)
    question = " ".join(body.question.split())
    messages = explain.messages(scope.db, orgs, org, question, body.position,
                                [t.model_dump() for t in body.history], _year(None))
    audit(scope.db, scope.user, "explain_asked", entity="organization",
          entity_id=org.id if org else None,
          details={"question": question[:200], "position": body.position}, request=request)
    scope.db.commit()

    def chunks():
        try:
            yield from llm.stream(messages, max_tokens=explain.MAX_TOKENS)
        except llm.LLMUnavailable as exc:
            yield f"\n\n[{exc}]"

    return StreamingResponse(chunks(), media_type="text/plain; charset=utf-8",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

