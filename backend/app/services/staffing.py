"""Нормативная численность: права, данные учреждения, импорт и связь с заявками.

Хранятся только агрегаты: ставки и средний оклад по группам должностей, показатели
учреждения, нормативы и результаты расчёта. Сотрудников и ФИО здесь нет.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    IncomingRequest,
    InstitutionMetrics,
    NormativeCoefficient,
    NormativeDocument,
    Organization,
    PersonnelGroup,
    RequestStaffingLink,
    Role,
    ScheduleStatus,
    StaffingAnalysisResult,
    StaffingLine,
    StaffingSchedule,
    User,
)
from app.services import helpdesk, norms, routing, staffing_analysis, staffing_routing
from app.services.directory import ROLE_TITLES, ImportResult
from app.services.norms import dec
from app.services.spreadsheet import Column, normalize, number
from app.services.staffing_analysis import (
    BASIS_TITLES,
    CATEGORY_TITLES,
    METRIC_FIELDS,
    STATUS_TITLES,
    period,
)

# Кто видит раздел. Сотрудник, хозслужба и бригады — нет: им он ни к чему
VIEW_ROLES = (Role.admin, Role.regional_analyst, Role.municipal_specialist, Role.director,
              Role.observer)
# Кто вносит штатку, занятость и показатели (в пределах своей территории)
DATA_ROLES = (Role.admin, Role.regional_analyst, Role.municipal_specialist, Role.director)
# Кто правит нормативы: региональные — аналитик и администратор, местные — ещё и специалист
NORM_ROLES = (Role.admin, Role.regional_analyst, Role.municipal_specialist)
IMPORT_ROLES = (Role.admin, Role.regional_analyst, Role.municipal_specialist)
STAFFING_TOPICS = ("staff_increase", "staff_reduction", "norms", "data_fix")


def can_view(user: User) -> bool:
    return user.role in VIEW_ROLES


def can_edit_norm(db: Session, user: User, scope_level: str, scope_id: int | None) -> bool:
    if user.role in (Role.admin, Role.regional_analyst):
        return True
    if user.role != Role.municipal_specialist or scope_id is None:
        return False
    if scope_level == "municipality":
        return scope_id == user.municipality_id
    if scope_level == "organization":
        org = db.get(Organization, scope_id)
        return org is not None and org.municipality_id == user.municipality_id
    return False


def visible_norm(user: User, coef: NormativeCoefficient, orgs_in_scope: dict[int, Organization],
                 own_org: Organization | None) -> bool:
    """Директор видит только нормативы, применимые к его учреждению; специалист — свои
    муниципальные и региональные."""
    if user.role in (Role.admin, Role.regional_analyst, Role.observer):
        return True
    if user.role == Role.municipal_specialist:
        if coef.scope_level == "municipality":
            return coef.scope_id == user.municipality_id
        if coef.scope_level == "organization":
            return coef.scope_id in orgs_in_scope
        return True
    if own_org is None:
        return False
    return coef.institution_type in ("all", own_org.org_type) and norms.scope_matches(coef,
                                                                                      own_org)


# --- выдача --------------------------------------------------------------------------


def _f(value) -> float | None:
    return None if value is None else float(value)


def result_out(r: StaffingAnalysisResult) -> dict:
    return {
        "id": r.id, "group_id": r.personnel_group_id,
        "group": r.group.name if r.group else None,
        "category": r.top_category, "basis": r.basis, "year": r.academic_year,
        "period_date": r.period_date.isoformat(),
        "required": _f(r.required_fte), "approved": _f(r.approved_fte),
        "occupied": _f(r.occupied_fte), "fact": _f(r.fact_fte),
        "deviation": _f(r.deviation_fte), "deviation_pct": _f(r.deviation_pct),
        "status": r.status, "status_title": STATUS_TITLES[r.status], "severity": r.severity,
        "reasons": r.missing_reasons or [], "coefficients": r.coefficients_snapshot or [],
        "metrics": r.metrics_snapshot or {}, "calculated_at": r.calculated_at,
        "is_current": r.is_current,
    }


def group_out(g: PersonnelGroup) -> dict:
    return {"id": g.id, "code": g.code, "name": g.name, "category": g.top_category,
            "subcategory": g.subcategory, "institution_types": g.institution_types or [],
            "positions": g.positions, "is_active": g.is_active}


def document_out(d: NormativeDocument, used: int = 0) -> dict:
    return {
        "id": d.id, "title": d.title, "doc_type": d.doc_type, "number": d.number,
        "issued_at": d.issued_at, "effective_from": d.effective_from,
        "effective_to": d.effective_to, "issuer": d.issuer, "scope_level": d.scope_level,
        "status": d.status, "status_title": norms.DOC_STATUSES.get(d.status, d.status),
        "source_ref": d.source_ref, "label": norms.document_title(d), "coefficients": used,
    }


def coefficient_out(c: NormativeCoefficient, today: date | None = None) -> dict:
    today = today or date.today()
    if c.document is not None and c.document.status != "active":
        state = "inactive"
    elif c.effective_from and today < c.effective_from:
        state = "future"
    elif c.effective_to and today > c.effective_to:
        state = "expired"
    else:
        state = "active"
    return {
        "id": c.id, "group_id": c.personnel_group_id, "group": c.group.name,
        "category": c.group.top_category, "document_id": c.document_id,
        "document": norms.document_title(c.document) if c.document else None,
        "institution_type": c.institution_type,
        "institution_type_title": norms.INSTITUTION_TYPES.get(c.institution_type,
                                                              c.institution_type),
        "scope_level": c.scope_level, "scope_id": c.scope_id, "metric": c.metric,
        "metric_title": norms.METRICS.get(c.metric, c.metric),
        "unit_size": _f(c.unit_size), "fte_per_unit": _f(c.fte_per_unit),
        "min_fte": _f(c.min_fte), "max_fte": _f(c.max_fte),
        "applies_from": _f(c.applies_from), "applies_to": _f(c.applies_to),
        "rounding_step": _f(c.rounding_step), "rounding_mode": c.rounding_mode,
        "tolerance_abs": _f(c.tolerance_abs), "tolerance_pct": _f(c.tolerance_pct),
        "priority": c.priority, "effective_from": c.effective_from,
        "effective_to": c.effective_to, "is_mandatory": c.is_mandatory, "comment": c.comment,
        "rule": norms.describe(c), "state": state,
    }


def current_rows(db: Session, year: str, org_ids: list[int], *, category: str | None = None,
                 basis: str | None = None, totals_only: bool = False):
    query = (select(StaffingAnalysisResult)
             .where(StaffingAnalysisResult.academic_year == year,
                    StaffingAnalysisResult.is_current,
                    StaffingAnalysisResult.organization_id.in_(org_ids))
             .options(selectinload(StaffingAnalysisResult.group)))
    if category:
        query = query.where(StaffingAnalysisResult.top_category == category)
    if basis:
        query = query.where(StaffingAnalysisResult.basis == basis)
    if totals_only:
        query = query.where(StaffingAnalysisResult.personnel_group_id.is_(None))
    return list(db.scalars(query.order_by(StaffingAnalysisResult.id)))


def documents_of(rows: list[dict]) -> list[str]:
    """Документы-основания, на которые ссылаются нормативы в строках анализа."""
    seen: dict[str, None] = {}
    for row in rows:
        for coef in row.get("coefficients", []):
            if coef.get("document"):
                seen[coef["document"]] = None
    return list(seen)


# --- данные учреждения ---------------------------------------------------------------


def groups_for(db: Session, org: Organization) -> list[PersonnelGroup]:
    groups = db.scalars(select(PersonnelGroup).order_by(PersonnelGroup.sort_order,
                                                        PersonnelGroup.id))
    return [g for g in groups if staffing_analysis.group_applies(g, org)]


def org_data(db: Session, org: Organization, year: str) -> dict:
    """Штатка и показатели учреждения на год — для формы «Исправить данные»."""
    schedule = db.scalar(select(StaffingSchedule).where(
        StaffingSchedule.organization_id == org.id, StaffingSchedule.academic_year == year)
        .options(selectinload(StaffingSchedule.lines)))
    metrics = db.scalar(select(InstitutionMetrics).where(
        InstitutionMetrics.organization_id == org.id, InstitutionMetrics.academic_year == year))
    lines: dict[int, dict] = {}
    for line in schedule.lines if schedule else []:
        item = lines.setdefault(line.personnel_group_id, {"approved": Decimal(0),
                                                          "occupied": Decimal(0),
                                                          "salary": None})
        item["approved"] += line.approved_fte
        item["occupied"] = (None if item["occupied"] is None or line.occupied_fte is None
                            else item["occupied"] + line.occupied_fte)
        if line.salary_rub is not None:
            item["salary"] = line.salary_rub
    groups = groups_for(db, org)
    # Строки по группам, которые потом отключили или не подходят типу, тоже показываем
    extra = [g for g in db.scalars(select(PersonnelGroup).where(
        PersonnelGroup.id.in_(list(lines)))) if g not in groups]
    return {
        "organization_id": org.id, "organization": org.name, "org_type": org.org_type,
        "year": year,
        "schedule": None if schedule is None else {
            "id": schedule.id, "status": schedule.status, "approved_at": schedule.approved_at,
            "comment": schedule.comment, "updated_at": schedule.updated_at},
        "metrics": {
            **{key: _f(getattr(metrics, key)) if metrics else None for key in METRIC_FIELDS},
            "source": metrics.source if metrics else None,
            "confirmed_at": metrics.confirmed_at if metrics else None},
        "lines": [
            {**group_out(g),
             "approved": _f(lines[g.id]["approved"]) if g.id in lines else None,
             "occupied": _f(lines[g.id]["occupied"]) if g.id in lines else None,
             "salary": _f(lines[g.id]["salary"]) if g.id in lines else None}
            for g in [*groups, *extra]
        ],
    }


def save_metrics(db: Session, org: Organization, year: str, values: dict,
                 source: str = "manual") -> list[str]:
    """Записывает показатели; возвращает, какие поля поменялись."""
    start, end = period(year)
    metrics = db.scalar(select(InstitutionMetrics).where(
        InstitutionMetrics.organization_id == org.id, InstitutionMetrics.academic_year == year))
    if metrics is None:
        metrics = InstitutionMetrics(organization_id=org.id, academic_year=year,
                                     period_start=start, period_end=end)
        db.add(metrics)
    changed = []
    for key in METRIC_FIELDS:
        if key not in values:
            continue
        new = values[key]
        old = getattr(metrics, key)
        if (None if old is None else float(old)) != (None if new is None else float(new)):
            setattr(metrics, key, new)
            changed.append(key)
    metrics.source = source
    metrics.confirmed_at = datetime.now(UTC)
    return changed


def get_schedule(db: Session, org: Organization, year: str) -> StaffingSchedule:
    schedule = db.scalar(select(StaffingSchedule).where(
        StaffingSchedule.organization_id == org.id, StaffingSchedule.academic_year == year)
        .options(selectinload(StaffingSchedule.lines)))
    if schedule is None:
        start, end = period(year)
        schedule = StaffingSchedule(organization_id=org.id, academic_year=year,
                                    period_start=start, period_end=end,
                                    status=ScheduleStatus.draft, lines=[])
        db.add(schedule)
    return schedule


def set_status(schedule: StaffingSchedule, status: str) -> None:
    if status == ScheduleStatus.approved and schedule.status != ScheduleStatus.approved:
        schedule.approved_at = datetime.now(UTC)
    schedule.status = status


def default_position(group: PersonnelGroup) -> str:
    """Первая типовая должность группы: «Уборщик служебных помещений, гардеробщик» ->
    «Уборщик служебных помещений». Ею подписывается строка, заведённая итогом по группе."""
    first = (group.positions or "").split(",")[0].strip()
    return first[:1].upper() + first[1:] if first else group.name


def position_name(line: StaffingLine, group: PersonnelGroup | None) -> str:
    return line.position or (default_position(group) if group else "Должность")


def set_lines(schedule: StaffingSchedule,
              values: dict, replace_all: bool) -> int:
    """Ставки: {(группа, должность): (утверждено, занято, оклад)}. Ключ — группа без
    должности (или просто группа) заменяет все строки группы, с должностью — только эту
    должность. Пустые строки не храним."""
    keyed = {(key if isinstance(key, tuple) else (key, None)): value
             for key, value in values.items()}
    whole = {gid for gid, position in keyed if position is None}
    named = {(gid, position.lower()) for gid, position in keyed if position}

    def replaced(line: StaffingLine) -> bool:
        return (line.personnel_group_id in whole
                or (line.personnel_group_id, (line.position or "").lower()) in named)

    schedule.lines[:] = [line for line in schedule.lines
                         if not replace_all and not replaced(line)]
    for (group_id, position), (approved, occupied, salary) in keyed.items():
        if not approved and occupied in (None, 0):
            continue
        schedule.lines.append(StaffingLine(personnel_group_id=group_id, position=position,
                                           approved_fte=dec(approved or 0),
                                           occupied_fte=dec(occupied),
                                           salary_rub=dec(salary)))
    return len(schedule.lines)


# --- заявка из анализа ---------------------------------------------------------------


def find_row(db: Session, org_id: int, year: str, category: str, basis: str,
             group_id: int | None) -> StaffingAnalysisResult | None:
    query = select(StaffingAnalysisResult).where(
        StaffingAnalysisResult.organization_id == org_id,
        StaffingAnalysisResult.academic_year == year, StaffingAnalysisResult.is_current,
        StaffingAnalysisResult.top_category == category, StaffingAnalysisResult.basis == basis)
    query = query.where(StaffingAnalysisResult.personnel_group_id == group_id
                        if group_id is not None
                        else StaffingAnalysisResult.personnel_group_id.is_(None))
    return db.scalar(query.options(selectinload(StaffingAnalysisResult.group)))


def request_draft(db: Session, org: Organization, row: StaffingAnalysisResult,
                  author: User) -> dict:
    siblings = current_rows(db, row.academic_year, [org.id], category=row.top_category,
                            basis=row.basis)
    groups = [result_out(r) for r in siblings if r.personnel_group_id is not None]
    related = [result_out(row)] if row.personnel_group_id else groups
    off = [(g["group"], g["deviation"]) for g in groups
           if g["status"] in ("deficit", "surplus") and g["deviation"] is not None]
    off.sort(key=lambda pair: -abs(pair[1]))
    from app.services import payroll  # noqa: PLC0415 — payroll сам импортирует этот модуль

    topic, role = staffing_routing.plan(row.status, row.top_category, row.severity, author.role)
    cost = (payroll.deviation_cost(db, row) if row.status in ("deficit", "surplus")
            else None)
    title, text = staffing_routing.compose(
        org_name=org.name, year=row.academic_year,
        category_title=CATEGORY_TITLES[row.top_category], basis=row.basis, status=row.status,
        group_name=row.group.name if row.group else None, required=row.required_fte,
        approved=row.approved_fte, occupied=row.occupied_fte, deviation=row.deviation_fte,
        reasons=row.missing_reasons or [], groups=off, documents=documents_of(related),
        cost=None if cost is None else payroll.rub(cost))
    return {"result_id": row.id, "status": row.status, "topic": topic,
            "topic_title": routing.TOPICS[topic].title, "routed_role": role,
            "routed_role_title": ROLE_TITLES[role], "title": title, "text": text}


def link(db: Session, request: IncomingRequest, row: StaffingAnalysisResult,
         user: User | None) -> RequestStaffingLink:
    item = RequestStaffingLink(request_id=request.id, analysis_result_id=row.id,
                               link_type=staffing_routing.link_type(row.status),
                               created_by="user" if user else "system",
                               created_by_id=user.id if user else None)
    db.add(item)
    what = row.group.name if row.group else CATEGORY_TITLES[row.top_category]
    deviation = ("" if row.deviation_fte is None
                 else f", отклонение {staffing_routing.signed(row.deviation_fte)}")
    helpdesk.log(request, user, "staffing",
                 f"Связана с нормативным анализом: {what}, {row.academic_year}, "
                 f"{STATUS_TITLES[row.status].lower()}{deviation}")
    return item


def request_context(db: Session, request_id: int) -> list[dict]:
    """Блок «Нормативная численность» в карточке заявки."""
    links = db.scalars(select(RequestStaffingLink).where(
        RequestStaffingLink.request_id == request_id).order_by(RequestStaffingLink.id)
        .options(selectinload(RequestStaffingLink.result)
                 .selectinload(StaffingAnalysisResult.group)))
    result = []
    for item in links:
        row = result_out(item.result)
        result.append({
            **row, "link_id": item.id, "link_type": item.link_type,
            "created_by": item.created_by, "organization_id": item.result.organization_id,
            "category_title": CATEGORY_TITLES[item.result.top_category],
            "basis_title": BASIS_TITLES[item.result.basis],
            "documents": documents_of([row]),
        })
    return result


# Слова в тексте заявки, по которым её можно связать с группой без участия человека
GROUP_KEYWORDS = {
    "aup_deputies": ("заместител", "завуч"),
    "aup_accounting": ("бухгалт", "экономист"),
    "aup_clerical": ("секретар", "делопроизвод", "архивист", "документовед"),
    "aup_household": ("завхоз", "хозяйственн част", "заведующ хозяйств"),
    "support_edu": ("логопед", "психолог", "дефектолог", "социальн педагог", "библиотекар",
                    "тьютор", "методист"),
    "support_assistants": ("помощник воспитател", "помощника воспитател", "младш воспитател"),
    "support_cleaning": ("уборщ", "уборк помещ", "клининг"),
    "support_security": ("охран", "сторож", "вахтер"),
    "support_kitchen": ("повар", "пищеблок", "кухн"),
    "support_maintenance": ("электрик", "сантехник", "дворник", "рабоч по обслуж",
                            "плотник", "слесар"),
}


def guess_group(db: Session, text: str) -> PersonnelGroup | None:
    normalized = re.sub(r"[^\w\s]", " ", text.lower().replace("ё", "е"))
    stems = " ".join(normalized.split())
    scores = {}
    for code, words in GROUP_KEYWORDS.items():
        score = sum(all(part in stems for part in word.split()) for word in words)
        if score:
            scores[code] = score
    if not scores:
        return None
    code = max(scores, key=scores.get)
    return db.scalar(select(PersonnelGroup).where(PersonnelGroup.code == code))


def auto_link(db: Session, request: IncomingRequest) -> RequestStaffingLink | None:
    """Кадровая заявка без явной связи: ищем результат анализа по группе из текста."""
    if request.topic not in STAFFING_TOPICS:
        return None
    text = f"{request.title} {request.text}"
    group = guess_group(db, text)
    category = group.top_category if group else None
    lowered = text.lower()
    if category is None:
        if any(w in lowered for w in ("ауп", "административн", "управленческ")):
            category = "aup"
        elif any(w in lowered for w in ("вспомогательн", "обслуживающ")):
            category = "support"
    if category is None:
        return None
    year = staffing_analysis.current_year()
    group_id = group.id if group else None
    row = find_row(db, request.organization_id, year, category, "occupied", group_id)
    if row is None or row.status == "no_data":
        # Занятость не ведётся — показываем хотя бы расчёт по штатке
        fallback = find_row(db, request.organization_id, year, category, "approved", group_id)
        row = fallback if fallback is not None and fallback.status != "no_data" else row
    if row is None:
        return None
    return link(db, request, row, None)


# --- импорт --------------------------------------------------------------------------

INSTITUTION_COLUMN = Column(
    "institution", "Код учреждения",
    ("institution_code", "код", "external_id", "учреждение", "название", "наименование"),
    required=True, note="Код учреждения во внешней системе или его название, как в системе")
YEAR_COLUMN = Column("period", "Учебный год", ("period", "год", "период", "academic_year"),
                     required=True, note="Например: 2026/2027")

METRIC_COLUMNS = [
    INSTITUTION_COLUMN, YEAR_COLUMN,
    Column("students_count", "Обучающиеся", ("students_count", "учащиеся", "воспитанники",
                                             "контингент", "число обучающихся"),
           note="Число обучающихся (в детском саду — воспитанников)"),
    Column("classes_count", "Классы", ("classes_count", "число классов", "классов"),
           note="Число классов. Для детского сада оставьте пустым"),
    Column("groups_count", "Группы", ("groups_count", "число групп", "групп"),
           note="Число групп детского сада или дошкольного отделения"),
    Column("total_area_m2", "Площадь, м²", ("total_area_m2", "площадь", "общая площадь",
                                           "площадь м2", "площадь, м2"),
           note="Общая площадь помещений, м². Десятичная запятая допускается"),
    Column("rooms_count", "Кабинеты", ("rooms_count", "кабинеты", "число кабинетов",
                                       "помещения", "кабинетов"),
           note="Сколько кабинетов и других помещений убирают — для норматива уборщиков"),
]
LINE_COLUMNS = [
    INSTITUTION_COLUMN, YEAR_COLUMN,
    Column("group", "Группа", ("group_code", "код группы", "группа персонала",
                               "группа нормирования"), required=True,
           note="Код группы (aup_clerical) или её название (Делопроизводство). "
                "Список групп — на вкладке «Нормативы»"),
    Column("position", "Должность", ("position", "должность", "наименование должности"),
           note="Например: Уборщик служебных помещений. Пусто — строка итогом по группе "
                "и заменяет все должности группы"),
    Column("approved_fte", "Утверждено ставок", ("approved_fte", "утверждено", "по штату",
                                                 "ставок по штату"), required=True,
           note="Сколько ставок группы в штатном расписании. Например: 2,5"),
    Column("occupied_fte", "Занято ставок", ("occupied_fte", "занято", "фактически занято"),
           note="Сколько ставок фактически занято, без ФИО. Пусто — занятость не ведётся"),
    Column("salary_rub", "Оклад за ставку", ("salary_rub", "оклад", "средний оклад",
                                              "оклад за ставку", "оклад руб"),
           note="Средний оклад одной ставки группы, ₽ в месяц, без надбавок. По нему "
                "считается ФОТ: оклад × ставки × 12"),
    Column("status", "Статус штатки", ("status", "статус"),
           note="«Утверждено» или «Черновик». Пусто — утверждено: в анализе участвует "
                "только утверждённая штатка"),
]
NORM_COLUMNS = [
    Column("group", "Группа", ("group_code", "код группы", "группа персонала"), required=True,
           note="Код группы (aup_clerical) или её название"),
    Column("institution_type", "Тип учреждения", ("institution_type", "тип", "для кого"),
           note="Все, школа, детский сад или комплекс. Пусто — все"),
    Column("metric", "Показатель", ("metric",), required=True,
           note="Обучающиеся, классы, группы, площадь или «нет» — фиксированное число ставок"),
    Column("unit_size", "На сколько единиц", ("unit_size", "единица", "на единиц"),
           note="Например, 300 — «на каждые 300 обучающихся». Пусто — ставки не зависят "
                "от размера показателя"),
    Column("fte_per_unit", "Ставок", ("fte_per_unit", "ставок на единицу", "ставки"),
           required=True, note="Сколько ставок положено на единицу или всего"),
    Column("min_fte", "Минимум ставок", ("min_fte", "минимум")),
    Column("max_fte", "Максимум ставок", ("max_fte", "максимум")),
    Column("applies_from", "Показатель от", ("applies_from", "от"),
           note="Норматив действует, только если показатель не меньше этого числа"),
    Column("applies_to", "Показатель до", ("applies_to", "до"),
           note="…и не больше этого числа"),
    Column("rounding_step", "Шаг округления", ("rounding_step", "округление"),
           note="0,25, 0,5 или 1. Округление — в большую сторону"),
    Column("document_number", "Номер документа", ("document_number", "документ", "номер"),
           note="Номер документа-основания. Документ сначала заводится на вкладке «Нормативы»"),
    Column("effective_from", "Действует с", ("effective_from", "с"),
           note="Дата: 01.09.2026 или 2026-09-01"),
    Column("effective_to", "Действует до", ("effective_to", "по"),
           note="Пусто — бессрочно"),
]

METRIC_ALIASES = {
    "students_count": ("обучающиеся", "учащиеся", "воспитанники", "контингент", "дети"),
    "classes_count": ("классы", "класс"),
    "groups_count": ("группы", "группа"),
    "total_area_m2": ("площадь", "м2", "м²", "площадь м2"),
    "rooms_count": ("кабинеты", "кабинет", "помещения"),
    "none": ("нет", "без показателя", "фиксированно", "-"),
}
TYPE_ALIASES = {
    "all": ("все", "все учреждения", ""),
    "school": ("школа", "школы", "сош"),
    "preschool": ("детский сад", "детские сады", "доу", "сад"),
    "complex": ("комплекс", "комплексы", "образовательный комплекс"),
}

TEMPLATES = {
    "metrics": ("Показатели", METRIC_COLUMNS, [
        ["OU-001-0001", "2026/2027", "840", "34", "", "12000", "48"],
        ["Детский сад № 12 «Солнышко»", "2026/2027", "260", "", "12", "1800", "30"],
    ], ["Повторная загрузка обновляет показатели учреждения за тот же год.",
        "Пустые ячейки не затирают уже введённые значения."]),
    "lines": ("Штатка", LINE_COLUMNS, [
        ["OU-001-0001", "2026/2027", "aup_deputies", "Заместитель директора по УВР", "2",
         "2", "62000", "Утверждено"],
        ["OU-001-0001", "2026/2027", "Делопроизводство", "Секретарь", "2", "2", "32000", ""],
        ["OU-001-0001", "2026/2027", "support_cleaning", "Уборщик служебных помещений", "9",
         "8,5", "22500", ""],
        ["OU-001-0001", "2026/2027", "support_cleaning", "Гардеробщик", "1", "1", "21000",
         ""],
    ], ["Строка — должность: ставки по штатке, занято и средний оклад. ФИО не нужны.",
        "Повторная загрузка заменяет должности из файла; остальные должности учреждения "
        "не трогаются. Строка без должности заменяет всю группу."]),
    "norms": ("Нормативы", NORM_COLUMNS, [
        ["aup_deputies", "Школа", "Классы", "12", "1", "", "", "", "", "0,25", "123",
         "01.09.2026", ""],
        ["aup_clerical", "Школа", "Обучающиеся", "300", "1", "", "", "", "", "0,25", "123",
         "01.09.2026", ""],
        ["support_cleaning", "Все", "Площадь", "1000", "1", "", "", "", "", "0,25", "45",
         "01.09.2026", ""],
    ], ["Норматив узнаётся по группе, типу учреждения, показателю, диапазону и документу: "
        "повторная загрузка обновит его, а не создаст второй."]),
}


def _orgs_index(db: Session, scope_query) -> tuple[dict, dict]:
    orgs = list(db.scalars(scope_query))
    by_code = {o.external_id: o for o in orgs if o.external_id}
    by_name: dict[str, list[Organization]] = {}
    for org in orgs:
        by_name.setdefault(normalize(org.name), []).append(org)
    return by_code, by_name


def _find_org(value: str, by_code: dict, by_name: dict) -> Organization | str:
    value = value.strip()
    if value in by_code:
        return by_code[value]
    same = by_name.get(normalize(value), [])
    if len(same) == 1:
        return same[0]
    if len(same) > 1:
        return f"Учреждений «{value}» несколько — укажите код"
    return f"Учреждение «{value}» не найдено или недоступно вам"


def _year(value: str) -> str:
    year = value.strip().replace(" ", "").replace("-", "/")
    period(year)  # бросит ValueError с понятным текстом
    return year


def _int(value: str) -> int | None:
    parsed = number(value)
    if parsed is None:
        return None
    if parsed < 0 or parsed != int(parsed):
        raise ValueError
    return int(parsed)


def parse_date(value: str) -> date | None:
    value = (value or "").strip()
    if not value:
        return None
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})", value)
    if match:
        return date(*(int(p) for p in match.groups()))
    match = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$", value)
    if match:
        day, month, year = (int(p) for p in match.groups())
        return date(year, month, day)
    raise ValueError(f"Непонятная дата «{value}»: нужна 01.09.2026 или 2026-09-01")


def _groups_index(db: Session) -> dict[str, PersonnelGroup]:
    index = {}
    for group in db.scalars(select(PersonnelGroup)):
        index[normalize(group.code)] = group
        index[normalize(group.name)] = group
    return index


def import_metrics(db: Session, rows: list[tuple[int, dict]], scope_query) -> tuple[
        ImportResult, set[tuple[int, str]]]:
    result = ImportResult()
    by_code, by_name = _orgs_index(db, scope_query)
    touched: set[tuple[int, str]] = set()
    for row, values in rows:
        org = _find_org(values.get("institution", ""), by_code, by_name)
        if isinstance(org, str):
            result.fail(row, org)
            continue
        try:
            year = _year(values.get("period", ""))
        except ValueError as exc:
            result.fail(row, str(exc))
            continue
        if (org.id, year) in touched:
            result.fail(row, "Учреждение за этот год уже встречалось выше — строка пропущена")
            continue
        try:
            parsed = {
                "students_count": _int(values.get("students_count", "")),
                "classes_count": _int(values.get("classes_count", "")),
                "groups_count": _int(values.get("groups_count", "")),
                "rooms_count": _int(values.get("rooms_count", "")),
            }
            area = number(values.get("total_area_m2", ""))
        except ValueError:
            result.fail(row, "Обучающиеся, классы, группы и кабинеты — целые неотрицательные "
                             "числа")
            continue
        if area is not None and area < 0:
            result.fail(row, "Площадь не может быть отрицательной")
            continue
        parsed["total_area_m2"] = None if area is None else round(area, 1)
        # Пустые ячейки не затирают введённое раньше
        values_to_set = {k: v for k, v in parsed.items() if v is not None}
        if not values_to_set:
            result.fail(row, "Нет ни одного показателя")
            continue
        existed = db.scalar(select(InstitutionMetrics.id).where(
            InstitutionMetrics.organization_id == org.id,
            InstitutionMetrics.academic_year == year))
        save_metrics(db, org, year, values_to_set, source="import")
        db.flush()
        touched.add((org.id, year))
        if existed:
            result.updated += 1
        else:
            result.created += 1
    return result, touched


def _status(value: str) -> str | None:
    key = normalize(value)
    if key in ("", "утверждено", "утверждена", "утвержден", "approved", "да"):
        return ScheduleStatus.approved
    if key in ("черновик", "draft", "проект", "нет"):
        return ScheduleStatus.draft
    return None


def import_lines(db: Session, rows: list[tuple[int, dict]], scope_query,
                 author: User | None = None) -> tuple[ImportResult, set[tuple[int, str]]]:
    from app.services import payroll  # noqa: PLC0415 — payroll сам импортирует этот модуль

    result = ImportResult()
    by_code, by_name = _orgs_index(db, scope_query)
    groups = _groups_index(db)
    parsed: dict[tuple[int, str], dict] = {}
    seen: set[tuple[int, str, int]] = set()
    for row, values in rows:
        org = _find_org(values.get("institution", ""), by_code, by_name)
        if isinstance(org, str):
            result.fail(row, org)
            continue
        try:
            year = _year(values.get("period", ""))
        except ValueError as exc:
            result.fail(row, str(exc))
            continue
        group = groups.get(normalize(values.get("group", "")))
        if group is None:
            result.fail(row, f"Группа «{values.get('group', '')}» не найдена")
            continue
        if not staffing_analysis.group_applies(group, org):
            result.fail(row, f"Группа «{group.name}» не применяется к этому типу учреждения")
            continue
        try:
            approved = number(values.get("approved_fte", ""))
            occupied = number(values.get("occupied_fte", ""))
            salary = number(values.get("salary_rub", ""))
        except ValueError:
            result.fail(row, "Ставки и оклад должны быть числами, например 2,5 и 32000")
            continue
        if salary is not None and not 0 < salary <= 10_000_000:
            result.fail(row, "Оклад — сумма в рублях в месяц, больше нуля")
            continue
        if approved is None or approved < 0 or approved > 500 or (
                occupied is not None and not 0 <= occupied <= 500):
            result.fail(row, "Ставки — число от 0 до 500; «Утверждено ставок» обязательно")
            continue
        status = _status(values.get("status", ""))
        if status is None:
            result.fail(row, f"Непонятный статус «{values.get('status')}»: нужно «Утверждено» "
                             "или «Черновик»")
            continue
        position = " ".join((values.get("position") or "").split())[:200] or None
        key = (org.id, year, group.id, (position or "").lower())
        if key in seen:
            what = f"Должность «{position}»" if position else f"Группа «{group.name}»"
            result.fail(row, f"{what} для учреждения за этот год уже встречалась выше — "
                             "строка пропущена")
            continue
        seen.add(key)
        item = parsed.setdefault((org.id, year), {"org": org, "status": status, "lines": {}})
        if values.get("status"):
            item["status"] = status
        item["lines"][(group.id, position)] = (approved, occupied, salary)

    for (_, year), item in parsed.items():
        schedule = get_schedule(db, item["org"], year)
        created = schedule.id is None
        set_lines(schedule, item["lines"], replace_all=False)
        set_status(schedule, item["status"])
        db.flush()
        payroll.snapshot(db, schedule, author, "import")
        if created:
            result.created += len(item["lines"])
        else:
            result.updated += len(item["lines"])
    return result, set(parsed)


def _choice(value: str, aliases: dict[str, tuple[str, ...]]) -> str | None:
    key = normalize(value)
    for code, words in aliases.items():
        if key == code or key in words:
            return code
    return None


def import_norms(db: Session, rows: list[tuple[int, dict]]) -> ImportResult:
    result = ImportResult()
    groups = _groups_index(db)
    documents = {}
    for document in db.scalars(select(NormativeDocument)):
        if document.number:
            documents.setdefault(normalize(document.number), document)
    existing = list(db.scalars(select(NormativeCoefficient).where(
        NormativeCoefficient.scope_level == "region")))

    for row, values in rows:
        group = groups.get(normalize(values.get("group", "")))
        if group is None:
            result.fail(row, f"Группа «{values.get('group', '')}» не найдена")
            continue
        institution_type = _choice(values.get("institution_type", ""), TYPE_ALIASES)
        metric = _choice(values.get("metric", ""), METRIC_ALIASES)
        if institution_type is None:
            result.fail(row, f"Непонятный тип учреждения «{values.get('institution_type')}»")
            continue
        if metric is None:
            result.fail(row, f"Непонятный показатель «{values.get('metric')}»")
            continue
        try:
            numbers = {key: number(values.get(key, "")) for key in (
                "unit_size", "fte_per_unit", "min_fte", "max_fte", "applies_from", "applies_to",
                "rounding_step")}
            effective_from = parse_date(values.get("effective_from", ""))
            effective_to = parse_date(values.get("effective_to", ""))
        except ValueError as exc:
            message = str(exc) if "дата" in str(exc) else "Числа — например 0,25 или 300"
            result.fail(row, message)
            continue
        if numbers["fte_per_unit"] is None or numbers["fte_per_unit"] < 0:
            result.fail(row, "«Ставок» — обязательное неотрицательное число")
            continue
        if numbers["unit_size"] is not None and numbers["unit_size"] <= 0:
            result.fail(row, "«На сколько единиц» должно быть больше нуля")
            continue
        if metric == "none" and numbers["unit_size"]:
            result.fail(row, "Без показателя «На сколько единиц» не заполняется")
            continue
        if (numbers["min_fte"] is not None and numbers["max_fte"] is not None
                and numbers["min_fte"] > numbers["max_fte"]):
            result.fail(row, "Минимум больше максимума")
            continue
        if effective_from and effective_to and effective_from > effective_to:
            result.fail(row, "«Действует с» позже, чем «Действует до»")
            continue
        document = None
        if values.get("document_number"):
            document = documents.get(normalize(values["document_number"]))
            if document is None:
                result.fail(row, f"Документ № {values['document_number']} не найден — "
                                 "заведите его на вкладке «Нормативы»")
                continue
            if document.status != "active":
                result.fail(row, f"Документ № {document.number} не действует")
                continue

        applies = (dec(numbers["applies_from"]), dec(numbers["applies_to"]))
        coef = next((c for c in existing if c.personnel_group_id == group.id
                     and c.institution_type == institution_type and c.metric == metric
                     and (c.applies_from, c.applies_to) == applies
                     and c.document_id == (document.id if document else None)), None)
        if coef is None:
            coef = NormativeCoefficient(personnel_group_id=group.id, scope_level="region",
                                        institution_type=institution_type, metric=metric,
                                        rounding_mode="up", priority=0, is_mandatory=True)
            db.add(coef)
            existing.append(coef)
            result.created += 1
        else:
            result.updated += 1
        coef.document_id = document.id if document else None
        coef.unit_size = dec(numbers["unit_size"])
        coef.fte_per_unit = dec(numbers["fte_per_unit"])
        coef.min_fte = dec(numbers["min_fte"])
        coef.max_fte = dec(numbers["max_fte"])
        coef.applies_from, coef.applies_to = applies
        coef.rounding_step = dec(numbers["rounding_step"])
        coef.effective_from = effective_from or (document.effective_from if document else None)
        coef.effective_to = effective_to or (document.effective_to if document else None)
        db.flush()
    return result
