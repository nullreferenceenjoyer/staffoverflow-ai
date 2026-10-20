"""Анализ нормативной численности: норматив, факт, отклонение и статус.

Для каждого учреждения, учебного года, категории (АУП / вспомогательный) и основы
сравнения (утверждённая штатка / фактическая занятость) считается:
  - строка по каждой группе нормирования;
  - итог по категории (строка без группы).

Отклонение = факт − норматив: плюс — сверх норматива, минус — дефицит. В пределах
допуска — норма. Если не хватает данных, система не показывает ни дефицит, ни излишек,
а говорит, чего не хватает.

Результаты хранятся со снимком нормативов и показателей. Пересчёт заменяет текущие
строки, но строки, на которые ссылаются заявки, остаются как история.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import delete, insert, select, update
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.models import (
    AnalysisStatus,
    InstitutionMetrics,
    NormativeCoefficient,
    Organization,
    PersonnelGroup,
    RequestStaffingLink,
    ScheduleStatus,
    StaffCategory,
    StaffingAnalysisResult,
    StaffingSchedule,
)
from app.services import norms
from app.services.norms import ZERO, dec

A = AnalysisStatus
BASES = ("occupied", "approved")
CATEGORIES = (StaffCategory.aup.value, StaffCategory.support.value)
CATEGORY_TITLES = {"aup": "АУП", "support": "Вспомогательный персонал"}
BASIS_TITLES = {"occupied": "по занятости", "approved": "по штатке"}
STATUS_TITLES = {
    A.deficit: "Дефицит", A.surplus: "Сверх норматива", A.normal: "Норма",
    A.no_data: "Нет данных", A.warning: "Требует проверки",
}
METRIC_FIELDS = ("students_count", "classes_count", "groups_count", "total_area_m2")
PROBLEMS = (A.deficit, A.surplus, A.warning, A.no_data)
SEVERITY_RANK = {"high": 3, "medium": 2, "low": 1, None: 0}


# --- учебный год ---------------------------------------------------------------------


def current_year(today: date | None = None) -> str:
    today = today or date.today()
    start = today.year if today.month >= 9 else today.year - 1
    return f"{start}/{start + 1}"


def period(year: str) -> tuple[date, date]:
    """«2026/2027» -> 1 сентября 2026 — 31 августа 2027."""
    try:
        start, end = (int(part) for part in year.split("/"))
    except ValueError as exc:
        raise ValueError("Учебный год пишется так: 2026/2027") from exc
    if end != start + 1 or not 2000 <= start <= 2100:
        raise ValueError("Учебный год пишется так: 2026/2027")
    return date(start, 9, 1), date(end, 8, 31)


def analysis_date(year: str, today: date | None = None) -> date:
    """На какую дату считать: сегодня, если оно внутри учебного года, иначе его край."""
    start, end = period(year)
    today = today or date.today()
    return min(max(today, start), end)


# --- расчёт --------------------------------------------------------------------------


@dataclass
class Row:
    organization_id: int
    group_id: int | None
    group_name: str | None
    category: str
    basis: str
    required: Decimal | None = None
    approved: Decimal | None = None
    occupied: Decimal | None = None
    fact: Decimal | None = None
    deviation: Decimal | None = None
    pct: Decimal | None = None
    status: str = A.no_data
    severity: str | None = None
    reasons: list[str] = field(default_factory=list)
    coefficients: list[dict] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    def as_db(self, year: str, moment: date, calculated_at: datetime) -> dict:
        return {
            "organization_id": self.organization_id, "personnel_group_id": self.group_id,
            "top_category": self.category, "academic_year": year, "period_date": moment,
            "basis": self.basis, "required_fte": self.required,
            "approved_fte": self.approved, "occupied_fte": self.occupied,
            "fact_fte": self.fact, "deviation_fte": self.deviation,
            "deviation_pct": self.pct, "status": self.status, "severity": self.severity,
            "missing_reasons": self.reasons, "coefficients_snapshot": self.coefficients,
            "metrics_snapshot": self.metrics, "calculated_at": calculated_at,
            "is_current": True,
        }


def group_applies(group, org) -> bool:
    return group.is_active and (not group.institution_types
                                or org.org_type in group.institution_types)


def severity(deviation: Decimal, required: Decimal | None) -> str:
    s = get_settings()
    size = abs(deviation)
    pct = size / required * 100 if required else None

    def over(fte: float, percent: float) -> bool:
        return size >= dec(fte) or (pct is not None and pct >= dec(percent))

    if over(s.staffing_high_fte, s.staffing_high_pct):
        return "high"
    if over(s.staffing_medium_fte, s.staffing_medium_pct):
        return "medium"
    return "low"


def _compare(row: Row, coefs: list) -> None:
    """Отклонение, статус и важность по уже известным нормативу и факту."""
    s = get_settings()
    row.deviation = (row.fact - row.required).quantize(norms.CENT)
    row.pct = ((row.deviation / row.required * 100).quantize(Decimal("0.1"))
               if row.required else None)
    allowed = norms.tolerance(coefs, row.required, s.staffing_tolerance_fte,
                              s.staffing_tolerance_pct)
    if abs(row.deviation) <= allowed:
        row.status = A.normal
    else:
        row.status = A.deficit if row.deviation < 0 else A.surplus
        row.severity = severity(row.deviation, row.required)


def schedule_problem(schedule, year: str) -> str | None:
    if schedule is None:
        return f"нет штатного расписания на {year}"
    if schedule.status == ScheduleStatus.draft:
        return "штатное расписание не утверждено (черновик)"
    if schedule.status == ScheduleStatus.archived:
        return "штатное расписание в архиве"
    return None


def _group_row(org, group, selected: list, line: tuple | None, basis: str, category: str,
               problem: str | None, metrics: dict, snapshot: dict) -> Row | None:
    approved, occupied = line if line is not None else (ZERO, ZERO)
    row = Row(org.id, group.id, group.name, category, basis, approved=approved,
              occupied=occupied, metrics=snapshot)
    parts = [norms.compute(c, metrics) for c in selected]
    row.coefficients = [p.snapshot for p in parts]
    missing = [p.missing for p in parts if p.missing]
    if selected and not missing:
        row.required = sum((p.fte for p in parts), ZERO).quantize(norms.CENT)
    row.fact = approved if basis == "approved" else occupied

    if not selected:
        row.status, row.severity = A.warning, "low"
        row.reasons = ["норматив не настроен"]
    elif missing:
        row.reasons = list(dict.fromkeys(missing))
    elif problem:
        row.reasons = [problem]
    elif row.fact is None:
        row.reasons = ["нет данных о занятых ставках"]
    else:
        _compare(row, selected)
        if row.status == A.normal and row.required == 0 and row.fact == 0:
            return None  # норматив ничего не дал и ставок нет — показывать нечего
    return row


def _total_row(org, category: str, basis: str, groups: list[Row], problem: str | None,
               snapshot: dict) -> Row:
    row = Row(org.id, None, None, category, basis, metrics=snapshot)
    computed = [g for g in groups if g.required is not None]
    no_norm = [g for g in groups if g.status == A.warning and g.required is None]
    lacking = [g for g in groups if g.status == A.no_data]
    metric_missing = any(g.required is None and g.status == A.no_data for g in groups)

    if computed and not metric_missing:
        row.required = sum((g.required for g in computed), ZERO)
    if computed:
        row.approved = sum((g.approved or ZERO for g in computed), ZERO)
        occupied = [g.occupied for g in computed]
        row.occupied = None if any(v is None for v in occupied) else sum(occupied, ZERO)

    if problem:
        row.reasons = [problem]
        return row
    if not groups:
        row.reasons = ["нет нормативов и штатных данных по категории"]
        return row
    if lacking:
        # «не указано: общая площадь помещений (Уборка помещений, Техническое обслуживание)»
        by_reason: dict[str, list[str]] = defaultdict(list)
        for g in lacking:
            for reason in g.reasons:
                by_reason[reason].append(g.group_name or "")
        row.reasons = [f"{reason} ({', '.join(names)})" for reason, names in by_reason.items()]
        return row
    if not computed:
        row.status, row.severity = A.warning, "low"
        row.reasons = [f"норматив не настроен: {', '.join(g.group_name for g in no_norm)}"]
        return row

    row.fact = row.approved if basis == "approved" else row.occupied
    _compare(row, [])
    off = [g for g in groups if g.status in (A.deficit, A.surplus)]
    if no_norm:
        row.reasons.append(f"норматив не настроен: {', '.join(g.group_name for g in no_norm)}")
    if row.status == A.normal and (off or no_norm):
        row.status = A.warning
        if off:
            row.reasons.insert(0, "отклонения по группам компенсируют друг друга")
        row.severity = max((g.severity for g in off), key=SEVERITY_RANK.get, default="low")
    return row


def analyze(org, groups: list, coefficients: list, schedule, metrics_row, year: str,
            moment: date) -> list[Row]:
    """Все строки анализа одного учреждения: по обеим основам и категориям."""
    metrics = {key: getattr(metrics_row, key) if metrics_row else None for key in METRIC_FIELDS}
    snapshot = {key: None if value is None else float(value) for key, value in metrics.items()}
    snapshot["confirmed_at"] = (metrics_row.confirmed_at.isoformat()
                                if metrics_row and metrics_row.confirmed_at else None)
    snapshot["schedule_status"] = schedule.status if schedule else None
    snapshot["schedule_approved_at"] = (schedule.approved_at.isoformat()
                                        if schedule and schedule.approved_at else None)
    problem = schedule_problem(schedule, year)

    lines: dict[int, tuple[Decimal, Decimal | None]] = {}
    for line in schedule.lines if schedule else []:
        approved, occupied = lines.get(line.personnel_group_id, (ZERO, ZERO))
        approved += dec(line.approved_fte) or ZERO
        # Занятость неизвестна хотя бы в одной строке группы — неизвестна по группе
        occupied = (None if occupied is None or line.occupied_fte is None
                    else occupied + dec(line.occupied_fte))
        lines[line.personnel_group_id] = (approved, occupied)

    rows: list[Row] = []
    for basis in BASES:
        for category in CATEGORIES:
            group_rows = []
            for group in groups:
                if group.top_category != category or not group_applies(group, org):
                    continue
                selected = norms.select(coefficients, org, group.id, moment, metrics)
                line = lines.get(group.id)
                if not selected and line is None:
                    continue
                row = _group_row(org, group, selected, line, basis, category, problem,
                                 metrics, snapshot)
                if row is not None:
                    group_rows.append(row)
            rows.append(_total_row(org, category, basis, group_rows, problem, snapshot))
            rows.extend(group_rows)
    return rows


# --- пересчёт и хранение -------------------------------------------------------------


def recalculate(db: Session, year: str, org_ids: list[int] | None = None,
                today: date | None = None) -> int:
    """Пересчитывает анализ за учебный год. Без org_ids — по всем учреждениям."""
    moment = analysis_date(year, today)
    calculated_at = datetime.now(UTC)
    query = select(Organization).order_by(Organization.id)
    if org_ids is not None:
        if not org_ids:
            return 0
        query = query.where(Organization.id.in_(org_ids))
    orgs = list(db.scalars(query))
    ids = [o.id for o in orgs]
    groups = list(db.scalars(select(PersonnelGroup).order_by(PersonnelGroup.sort_order,
                                                              PersonnelGroup.id)))
    coefficients = list(db.scalars(select(NormativeCoefficient)
                                   .options(selectinload(NormativeCoefficient.document))))
    schedules = {s.organization_id: s for s in db.scalars(
        select(StaffingSchedule).where(StaffingSchedule.academic_year == year,
                                       StaffingSchedule.organization_id.in_(ids))
        .options(selectinload(StaffingSchedule.lines)))}
    metrics = {m.organization_id: m for m in db.scalars(
        select(InstitutionMetrics).where(InstitutionMetrics.academic_year == year,
                                         InstitutionMetrics.organization_id.in_(ids)))}

    current = (StaffingAnalysisResult.academic_year == year, StaffingAnalysisResult.is_current,
               StaffingAnalysisResult.organization_id.in_(ids))
    linked = select(RequestStaffingLink.analysis_result_id)
    db.execute(delete(StaffingAnalysisResult)
               .where(*current, StaffingAnalysisResult.id.not_in(linked))
               .execution_options(synchronize_session=False))
    db.execute(update(StaffingAnalysisResult).where(*current).values(is_current=False)
               .execution_options(synchronize_session=False))

    batch: list[dict] = []
    for org in orgs:
        rows = analyze(org, groups, coefficients, schedules.get(org.id), metrics.get(org.id),
                       year, moment)
        batch.extend(row.as_db(year, moment, calculated_at) for row in rows)
        if len(batch) >= 2000:
            db.execute(insert(StaffingAnalysisResult), batch)
            batch = []
    if batch:
        db.execute(insert(StaffingAnalysisResult), batch)
    return len(orgs)


def years_with_data(db: Session) -> list[str]:
    years = set(db.scalars(select(StaffingSchedule.academic_year).distinct()))
    years |= set(db.scalars(select(InstitutionMetrics.academic_year).distinct()))
    years |= set(db.scalars(select(StaffingAnalysisResult.academic_year)
                            .where(StaffingAnalysisResult.is_current).distinct()))
    return sorted(years, reverse=True)


def recalculate_all(db: Session) -> int:
    """После смены нормативов: пересчитать все годы, по которым есть данные."""
    years = set(years_with_data(db)) | {current_year()}
    for year in years:
        recalculate(db, year)
    return len(years)


def ensure(db: Session, year: str, org_ids: list[int]) -> None:
    """Досчитывает учреждения, по которым за год ещё нет результата (например, новые)."""
    have = set(db.scalars(select(StaffingAnalysisResult.organization_id).where(
        StaffingAnalysisResult.academic_year == year, StaffingAnalysisResult.is_current,
        StaffingAnalysisResult.personnel_group_id.is_(None)).distinct()))
    missing = [i for i in org_ids if i not in have]
    if missing:
        recalculate(db, year, missing)
        db.commit()
