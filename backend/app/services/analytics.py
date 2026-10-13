"""Загрузка данных из БД и сводная аналитика по набору учреждений."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    Building,
    Category,
    Enrollment,
    IncomingRequest,
    Municipality,
    Norm,
    Organization,
    StaffPosition,
)
from app.services import routing, workload
from app.services.functions import CATEGORY_TITLES, function_title
from app.services.staffing import NormRule, OrgReport, build_report, collect_metrics

# Недельная норма часов на ставку (приказ Минобрнауки № 1601)
HOURS_PER_RATE = {"teacher": 18, "speech_therapist": 20, "defectologist": 20,
                  "educator": 36, "psychologist": 36, "social_pedagogue": 36}
UNDERLOAD_SHARE = 0.8


def load_rules(db: Session) -> list[NormRule]:
    norms = db.scalars(select(Norm).where(Norm.is_active)).all()
    return [NormRule.from_model(n) for n in norms]


def load_reports(db: Session, org_ids: list[int] | None = None) -> list[OrgReport]:
    """Строит отчёты по учреждениям. org_ids=None — по всем.

    Данные читаются четырьмя запросами независимо от числа учреждений,
    штатные расписания агрегируются на стороне БД.
    """
    settings = get_settings()

    orgs_query = select(Organization, Municipality.name).join(Municipality)
    if org_ids is not None:
        if not org_ids:
            return []
        orgs_query = orgs_query.where(Organization.id.in_(org_ids))
    orgs = db.execute(orgs_query.order_by(Organization.name)).all()

    def scoped(query, column):
        return query if org_ids is None else query.where(column.in_(org_ids))

    enrollments = defaultdict(list)
    for row in db.scalars(scoped(select(Enrollment), Enrollment.organization_id)):
        enrollments[row.organization_id].append(row)

    buildings = defaultdict(list)
    for row in db.scalars(scoped(select(Building), Building.organization_id)):
        buildings[row.organization_id].append(row)

    staff_query = select(
        StaffPosition.organization_id,
        StaffPosition.function_code,
        func.min(StaffPosition.category).label("category"),
        func.sum(StaffPosition.rate).label("rate"),
        func.sum(StaffPosition.monthly_pay).label("pay"),
        func.sum(
            case((StaffPosition.employee_ref.is_(None), StaffPosition.rate), else_=0)
        ).label("vacant_rate"),
    ).group_by(StaffPosition.organization_id, StaffPosition.function_code)
    staff = defaultdict(list)
    for row in db.execute(scoped(staff_query, StaffPosition.organization_id)):
        staff[row.organization_id].append(row._asdict())

    rules = load_rules(db)
    return [
        build_report(
            org_id=org.id,
            name=org.name,
            org_type=org.org_type,
            municipality_id=org.municipality_id,
            municipality=municipality,
            metrics=collect_metrics(enrollments[org.id], buildings[org.id]),
            actual=staff[org.id],
            rules=rules,
            payroll_tax_rate=settings.payroll_tax_rate,
            tolerance=settings.deviation_tolerance,
        )
        for org, municipality in orgs
    ]


def load_sites(db: Session, org_ids: list[int] | None = None,
               radius_m: float = workload.DEFAULT_RADIUS_M) -> dict:
    """Отчёт о загрузке АУП и ВП по площадкам (см. services/workload.py)."""
    if org_ids is not None and not org_ids:
        return workload.analyze([], [], {}, [], radius_m=radius_m)

    def scoped(query, column):
        return query if org_ids is None else query.where(column.in_(org_ids))

    orgs = {
        org.id: (org, municipality)
        for org, municipality in db.execute(
            scoped(select(Organization, Municipality.name).join(Municipality), Organization.id)
        )
    }
    enrollments = defaultdict(list)
    for row in db.scalars(scoped(select(Enrollment), Enrollment.organization_id)):
        enrollments[row.organization_id].append(row)

    rows = db.scalars(scoped(select(Building), Building.organization_id).order_by(Building.id))
    by_org = defaultdict(list)
    buildings = []
    for row in rows:
        org, municipality = orgs[row.organization_id]
        by_org[org.id].append(row)
        buildings.append(workload.SiteBuilding(
            id=row.id, org_id=org.id, org_name=org.name, org_type=org.org_type,
            municipality_id=org.municipality_id, municipality=municipality, name=row.name,
            area=float(row.area_sqm), floors=row.floors, address=row.address or org.address,
            lat=None if row.latitude is None else float(row.latitude),
            lon=None if row.longitude is None else float(row.longitude),
            capacity=row.capacity, occupancy=row.occupancy,
        ))

    staff_query = select(
        StaffPosition.organization_id,
        StaffPosition.building_id,
        StaffPosition.function_code,
        func.min(StaffPosition.category).label("category"),
        func.sum(StaffPosition.rate).label("rate"),
        func.sum(StaffPosition.monthly_pay).label("pay"),
        func.sum(
            case((StaffPosition.employee_ref.is_(None), StaffPosition.rate), else_=0)
        ).label("vacant_rate"),
        func.count(StaffPosition.employee_ref).label("people"),
    ).where(StaffPosition.category.in_(workload.CATEGORIES)).group_by(
        StaffPosition.organization_id, StaffPosition.building_id, StaffPosition.function_code
    )
    staff = [
        workload.StaffRow(org_id=row.organization_id, building_id=row.building_id,
                          function_code=row.function_code, category=row.category,
                          rate=float(row.rate), pay=float(row.pay),
                          vacant_rate=float(row.vacant_rate), people=row.people)
        for row in db.execute(scoped(staff_query, StaffPosition.organization_id))
    ]

    # Заявки за квартал — косвенный признак того, сколько работы у хозяйственной службы
    since = datetime.now(UTC) - timedelta(days=90)
    requests_query = (
        select(IncomingRequest.building_id, IncomingRequest.topic, func.count())
        .where(IncomingRequest.building_id.is_not(None), IncomingRequest.created_at >= since)
        .group_by(IncomingRequest.building_id, IncomingRequest.topic)
    )
    requests: dict[tuple[int, str], int] = defaultdict(int)
    for building_id, topic, count in db.execute(
        scoped(requests_query, IncomingRequest.organization_id)
    ):
        function_code = routing.TOPICS[topic].function_code if topic in routing.TOPICS else None
        if function_code:
            requests[building_id, function_code] += count

    metrics = {org_id: collect_metrics(enrollments[org_id], by_org[org_id]) for org_id in orgs}
    return workload.analyze(
        buildings, staff, metrics, load_rules(db), radius_m=radius_m,
        payroll_tax_rate=get_settings().payroll_tax_rate, requests=dict(requests),
    )


def summarize(reports: list[OrgReport]) -> dict:
    """Итоги по набору учреждений: KPI для дашборда и разрезы."""
    categories = {
        c.value: {"key": c.value, "title": CATEGORY_TITLES[c], "actual": 0.0, "norm": 0.0,
                  "surplus": 0.0, "shortage": 0.0}
        for c in Category
    }
    municipalities: dict[int, dict] = {}
    norm_base = deviation = 0.0

    for report in reports:
        for key, values in report.by_category().items():
            for field in ("actual", "norm", "surplus", "shortage"):
                categories[key][field] += values[field]
        for line in report.lines:
            if line.norm_rate is not None:
                norm_base += line.norm_rate
                deviation += abs(line.delta)

        m = municipalities.setdefault(
            report.municipality_id,
            {"id": report.municipality_id, "name": report.municipality, "organizations": 0,
             "actual": 0.0, "norm": 0.0, "surplus": 0.0, "shortage": 0.0, "saving": 0.0},
        )
        m["organizations"] += 1
        m["actual"] += report.actual_total
        m["norm"] += report.norm_total
        m["surplus"] += report.surplus
        m["shortage"] += report.shortage
        m["saving"] += report.saving_potential_year

    def rounded(item: dict) -> dict:
        return {k: round(v, 2) if isinstance(v, float) else v for k, v in item.items()}

    return {
        "organizations": len(reports),
        "students": int(sum(r.metrics["students_total"] for r in reports)),
        "actual_total": round(sum(r.actual_total for r in reports), 2),
        "norm_total": round(sum(r.norm_total for r in reports), 2),
        "surplus": round(sum(r.surplus for r in reports), 2),
        "shortage": round(sum(r.shortage for r in reports), 2),
        "compliance": round(max(0.0, 100 - deviation / norm_base * 100), 1) if norm_base else 100.0,
        "fot_actual_year": sum(r.fot_actual_year for r in reports),
        "saving_potential_year": sum(r.saving_potential_year for r in reports),
        "categories": [rounded(c) for c in categories.values()],
        "municipalities": sorted(
            (rounded(m) for m in municipalities.values()), key=lambda m: m["name"]
        ),
    }


def top_deviations(
    reports: list[OrgReport], category: str | None = None, limit: int = 50
) -> list[dict]:
    """Самые крупные расхождения «учреждение × функция»."""
    tolerance = get_settings().deviation_tolerance
    rows = []
    for report in reports:
        for line in report.lines:
            if abs(line.delta) <= tolerance or (category and line.category != category):
                continue
            rows.append({
                "organization_id": report.org_id,
                "organization": report.name,
                "municipality": report.municipality,
                "function_code": line.function_code,
                "title": line.title,
                "category": line.category,
                "actual": line.actual_rate,
                "norm": line.norm_rate,
                "delta": line.delta,
                "fot_effect_year": round(
                    line.delta * line.pay_per_rate * 12 * (1 + report.payroll_tax_rate)
                ),
                "explanations": line.explanations,
            })
    rows.sort(key=lambda r: abs(r["delta"]), reverse=True)
    return rows[:limit]


def find_internal_duplicates(db: Session, org_ids: list[int] | None) -> list[dict]:
    """Одна и та же функция АУП ведётся в нескольких подразделениях одного ОУ."""
    departments = func.count(func.distinct(func.coalesce(StaffPosition.department, "")))
    query = (
        select(
            Organization.id,
            Organization.name,
            StaffPosition.function_code,
            departments.label("departments"),
            func.sum(StaffPosition.rate).label("rate"),
            func.array_agg(func.distinct(func.coalesce(StaffPosition.department, "—"))).label(
                "names"
            ),
        )
        .join(Organization, Organization.id == StaffPosition.organization_id)
        .where(StaffPosition.category == Category.admin)
        .where(StaffPosition.function_code.notin_(("director", "deputy_director")))
        .group_by(Organization.id, Organization.name, StaffPosition.function_code)
        .having(departments > 1)
        .order_by(func.sum(StaffPosition.rate).desc())
        .limit(200)
    )
    if org_ids is not None:
        query = query.where(StaffPosition.organization_id.in_(org_ids))
    return [
        {
            "organization_id": row.id,
            "organization": row.name,
            "function_code": row.function_code,
            "title": function_title(row.function_code),
            "departments": sorted(row.names),
            "rate": float(row.rate),
        }
        for row in db.execute(query)
    ]


def find_inefficient_positions(db: Session, org_ids: list[int] | None) -> dict:
    """Ставки, которые используются не полностью: недогруз по часам и вакансии."""

    def scoped(query):
        if org_ids is None:
            return query
        return query.where(StaffPosition.organization_id.in_(org_ids))

    norm_hours = case(
        *[(StaffPosition.function_code == code, hours) for code, hours in HOURS_PER_RATE.items()],
        else_=None,
    )
    expected = norm_hours * StaffPosition.rate
    underloaded_query = scoped(
        select(StaffPosition, Organization.name, expected.label("expected"))
        .join(Organization, Organization.id == StaffPosition.organization_id)
        .where(StaffPosition.weekly_hours.is_not(None))
        .where(StaffPosition.weekly_hours < expected * UNDERLOAD_SHARE)
        .order_by((expected - StaffPosition.weekly_hours).desc())
        .limit(200)
    )
    underloaded = [
        {
            "organization_id": position.organization_id,
            "organization": org_name,
            "title": position.title,
            "rate": float(position.rate),
            "weekly_hours": float(position.weekly_hours),
            "expected_hours": float(expected_hours),
        }
        for position, org_name, expected_hours in db.execute(underloaded_query)
    ]

    vacancies_query = scoped(
        select(
            Organization.id,
            Organization.name,
            StaffPosition.function_code,
            func.sum(StaffPosition.rate).label("rate"),
            func.sum(StaffPosition.monthly_pay).label("pay"),
        )
        .join(Organization, Organization.id == StaffPosition.organization_id)
        .where(StaffPosition.employee_ref.is_(None))
        .group_by(Organization.id, Organization.name, StaffPosition.function_code)
        .order_by(func.sum(StaffPosition.rate).desc())
        .limit(200)
    )
    vacancies = [
        {
            "organization_id": row.id,
            "organization": row.name,
            "title": function_title(row.function_code),
            "rate": float(row.rate),
            "monthly_pay": float(row.pay),
        }
        for row in db.execute(vacancies_query)
    ]
    return {"underloaded": underloaded, "vacancies": vacancies}
