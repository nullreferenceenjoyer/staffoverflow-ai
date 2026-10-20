"""ФОТ по штатке, версии штатного расписания и сводка для дашборда.

ФОТ группы за год = средний оклад за ставку × ставки × 12. Без надбавок и начислений:
этого достаточно, чтобы сравнить учреждения и увидеть, во что обходится изменение
штатки. Оклад вносится итогом по группе, отдельных людей и их окладов здесь нет.

Каждое сохранение или загрузка штатки оставляет версию — снимок ставок и окладов.
Разница двух соседних версий показывает, как изменение штатки сдвинуло ФОТ.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Organization,
    PersonnelGroup,
    StaffingAnalysisResult,
    StaffingSchedule,
    StaffingScheduleVersion,
    User,
)
from app.services import staffing, staffing_analysis
from app.services.norms import CENT, ZERO, dec, num

MONTHS = 12
SOURCES = {"manual": "вручную", "import": "загрузка из файла", "demo": "демо-данные"}
STATUSES = {"approved": "утверждена", "draft": "черновик", "archived": "в архиве"}


def annual(fte: Decimal | None, salary: Decimal | None) -> Decimal | None:
    if fte is None or salary is None:
        return None
    return (dec(fte) * dec(salary) * MONTHS).quantize(CENT)


def rub(value) -> str:
    """«1 234 567 ₽», со знаком минус, если меньше нуля."""
    if value is None:
        return "—"
    amount = int(Decimal(str(value)).quantize(Decimal(1)))
    text = f"{abs(amount):,}".replace(",", " ")
    return f"{'−' if amount < 0 else ''}{text} ₽"


def signed_rub(value) -> str:
    if value is None:
        return "—"
    return ("+" if Decimal(str(value)) > 0 else "") + rub(value)


def _f(value) -> float | None:
    return None if value is None else float(value)


# --- строки штатки -------------------------------------------------------------------


@dataclass
class Item:
    """Итог группы в штатке: в штатке может быть несколько строк одной группы."""

    approved: Decimal = ZERO
    occupied: Decimal | None = ZERO
    salary_sum: Decimal = ZERO  # Σ оклад × ставки — для средневзвешенного оклада
    salary_fte: Decimal = ZERO

    @property
    def salary(self) -> Decimal | None:
        if not self.salary_fte:
            return None
        return (self.salary_sum / self.salary_fte).quantize(CENT)

    @property
    def vacant(self) -> Decimal | None:
        return None if self.occupied is None else max(self.approved - self.occupied, ZERO)


def items_of(schedule: StaffingSchedule | None) -> dict[int, Item]:
    result: dict[int, Item] = {}
    for line in schedule.lines if schedule else []:
        item = result.setdefault(line.personnel_group_id, Item())
        approved = dec(line.approved_fte) or ZERO
        item.approved += approved
        item.occupied = (None if item.occupied is None or line.occupied_fte is None
                         else item.occupied + dec(line.occupied_fte))
        if line.salary_rub is not None:
            weight = approved or Decimal(1)
            item.salary_sum += dec(line.salary_rub) * weight
            item.salary_fte += weight
    return result


@dataclass
class Totals:
    approved: Decimal = ZERO
    occupied: Decimal | None = ZERO
    payroll_approved: Decimal | None = None
    payroll_occupied: Decimal | None = None
    missing_salary: int = 0  # групп со ставками, но без оклада

    @property
    def vacant(self) -> Decimal | None:
        return None if self.occupied is None else max(self.approved - self.occupied, ZERO)

    @property
    def vacant_payroll(self) -> Decimal | None:
        if self.payroll_approved is None or self.payroll_occupied is None:
            return None
        return self.payroll_approved - self.payroll_occupied

    def out(self) -> dict:
        return {"approved": _f(self.approved), "occupied": _f(self.occupied),
                "vacant": _f(self.vacant), "payroll_approved": _f(self.payroll_approved),
                "payroll_occupied": _f(self.payroll_occupied),
                "vacant_payroll": _f(self.vacant_payroll),
                "missing_salary": self.missing_salary}


def totals_of(items: dict[int, Item]) -> Totals:
    total = Totals()
    for item in items.values():
        total.approved += item.approved
        total.occupied = (None if total.occupied is None or item.occupied is None
                          else total.occupied + item.occupied)
        if item.salary is None:
            if item.approved:
                total.missing_salary += 1
            continue
        total.payroll_approved = (total.payroll_approved or ZERO) + annual(item.approved,
                                                                            item.salary)
        if item.occupied is not None:
            total.payroll_occupied = (total.payroll_occupied or ZERO) + annual(item.occupied,
                                                                                item.salary)
    if total.occupied is None:
        total.payroll_occupied = None
    return total


# --- версии --------------------------------------------------------------------------


def _lines_json(items: dict[int, Item]) -> list[dict]:
    return [{"group_id": gid, "approved": _f(item.approved), "occupied": _f(item.occupied),
             "salary": _f(item.salary)} for gid, item in sorted(items.items())]


def snapshot(db: Session, schedule: StaffingSchedule, author: User | None, source: str,
             comment: str | None = None) -> StaffingScheduleVersion | None:
    """Новая версия, если штатка правда изменилась. Пересохранение без правок — не версия."""
    items = items_of(schedule)
    lines = _lines_json(items)
    last = db.scalar(select(StaffingScheduleVersion)
                     .where(StaffingScheduleVersion.schedule_id == schedule.id)
                     .order_by(StaffingScheduleVersion.id.desc()).limit(1))
    if last is not None and last.lines == lines and last.status == schedule.status:
        return None
    total = totals_of(items)
    version = StaffingScheduleVersion(
        schedule_id=schedule.id, organization_id=schedule.organization_id,
        academic_year=schedule.academic_year, author_id=author.id if author else None,
        source=source, status=schedule.status, comment=comment or schedule.comment,
        lines=lines, approved_fte=total.approved, occupied_fte=total.occupied,
        payroll_approved=total.payroll_approved, payroll_occupied=total.payroll_occupied)
    db.add(version)
    return version


def diff(before: list[dict] | None, after: list[dict], names: dict[int, str]) -> list[dict]:
    """Что поменялось по группам между двумя версиями и как это сдвинуло ФОТ."""
    old = {line["group_id"]: line for line in before or []}
    new = {line["group_id"]: line for line in after}
    changes = []
    for gid in sorted(set(old) | set(new), key=lambda g: names.get(g, "")):
        a, b = old.get(gid, {}), new.get(gid, {})
        approved_a, approved_b = dec(a.get("approved")) or ZERO, dec(b.get("approved")) or ZERO
        salary_a, salary_b = dec(a.get("salary")), dec(b.get("salary"))
        if approved_a == approved_b and salary_a == salary_b:
            continue
        payroll_a = annual(approved_a, salary_a if salary_a is not None else salary_b)
        payroll_b = annual(approved_b, salary_b if salary_b is not None else salary_a)
        delta = None if payroll_a is None or payroll_b is None else payroll_b - payroll_a
        changes.append({
            "group_id": gid, "group": names.get(gid, f"группа {gid}"),
            "approved_before": _f(approved_a), "approved_after": _f(approved_b),
            "approved_delta": _f(approved_b - approved_a),
            "salary_before": _f(salary_a), "salary_after": _f(salary_b),
            "payroll_delta": _f(delta),
        })
    return changes


def change_text(change: dict) -> str:
    """«Уборка помещений: 10 → 8 ставок, ФОТ −528 000 ₽/год»."""
    parts = []
    if change["approved_delta"]:
        parts.append(f"{num(change['approved_before'])} → {num(change['approved_after'])} "
                     "ставок")
    if change["salary_before"] != change["salary_after"]:
        parts.append(f"оклад {rub(change['salary_before'])} → {rub(change['salary_after'])}")
    if change["payroll_delta"] is not None:
        parts.append(f"ФОТ {signed_rub(change['payroll_delta'])}/год")
    return f"{change['group']}: {', '.join(parts)}"


def group_names(db: Session) -> dict[int, str]:
    return {g.id: g.name for g in db.scalars(select(PersonnelGroup))}


def version_out(version: StaffingScheduleVersion, previous: StaffingScheduleVersion | None,
                names: dict[int, str]) -> dict:
    changes = diff(previous.lines if previous else None, version.lines, names) \
        if previous else []
    payroll_delta = None
    if previous is not None and version.payroll_approved is not None \
            and previous.payroll_approved is not None:
        payroll_delta = version.payroll_approved - previous.payroll_approved
    return {
        "id": version.id, "created_at": version.created_at,
        "author": version.author.full_name if version.author else None,
        "source": version.source, "source_title": SOURCES.get(version.source, version.source),
        "status": version.status, "status_title": STATUSES.get(version.status, version.status),
        "comment": version.comment, "first": previous is None,
        "approved": _f(version.approved_fte), "occupied": _f(version.occupied_fte),
        "payroll_approved": _f(version.payroll_approved),
        "payroll_occupied": _f(version.payroll_occupied),
        "approved_delta": None if previous is None else _f(version.approved_fte
                                                           - previous.approved_fte),
        "payroll_delta": _f(payroll_delta),
        "changes": changes,
    }


def versions_of(db: Session, org_ids: list[int], year: str) -> dict[int, list]:
    """Версии штаток учреждений за год, от старых к новым."""
    result: dict[int, list] = defaultdict(list)
    if not org_ids:
        return result
    query = (select(StaffingScheduleVersion)
             .where(StaffingScheduleVersion.organization_id.in_(org_ids),
                    StaffingScheduleVersion.academic_year == year)
             .options(selectinload(StaffingScheduleVersion.author))
             .order_by(StaffingScheduleVersion.created_at, StaffingScheduleVersion.id))
    for version in db.scalars(query):
        result[version.organization_id].append(version)
    return result


def history(db: Session, org_id: int, year: str, limit: int = 30) -> list[dict]:
    """История штатки учреждения, новые сверху."""
    versions = versions_of(db, [org_id], year).get(org_id, [])
    names = group_names(db)
    out = [version_out(v, versions[i - 1] if i else None, names)
           for i, v in enumerate(versions)]
    return list(reversed(out))[:limit]


# --- штатка учреждения ----------------------------------------------------------------


def _schedules(db: Session, org_ids: list[int], year: str) -> dict[int, StaffingSchedule]:
    if not org_ids:
        return {}
    return {s.organization_id: s for s in db.scalars(
        select(StaffingSchedule).where(StaffingSchedule.academic_year == year,
                                       StaffingSchedule.organization_id.in_(org_ids))
        .options(selectinload(StaffingSchedule.lines)))}


def average_salaries(schedules: dict[int, StaffingSchedule]) -> dict[int, Decimal]:
    """Средний оклад группы по территории — оценка, если в штатке группы нет вовсе."""
    sums: dict[int, list[Decimal]] = defaultdict(lambda: [ZERO, ZERO])
    for schedule in schedules.values():
        for gid, item in items_of(schedule).items():
            if item.salary is not None:
                weight = item.approved or Decimal(1)
                sums[gid][0] += item.salary * weight
                sums[gid][1] += weight
    return {gid: (s / w).quantize(CENT) for gid, (s, w) in sums.items() if w}


def institution(db: Session, org: Organization, year: str, basis: str) -> dict:
    """Штатка учреждения с окладами, ФОТ, нормативом и ценой отклонения по группам."""
    staffing_analysis.ensure(db, year, [org.id])
    schedule = _schedules(db, [org.id], year).get(org.id)
    items = items_of(schedule)
    rows = {r.personnel_group_id: r for r in staffing.current_rows(db, year, [org.id],
                                                                   basis=basis)}
    groups = staffing.groups_for(db, org)
    extra = [g for g in db.scalars(select(PersonnelGroup).where(
        PersonnelGroup.id.in_(list(items)))) if g not in groups]
    fallback = average_salaries(_schedules(db, [o.id for o in db.scalars(
        select(Organization).where(Organization.municipality_id == org.municipality_id))],
        year))

    lines = []
    for group in [*groups, *extra]:
        item = items.get(group.id)
        row = rows.get(group.id)
        if item is None and row is None:
            continue
        salary = item.salary if item else None
        price = salary if salary is not None else fallback.get(group.id)
        deviation = dec(row.deviation_fte) if row and row.deviation_fte is not None else None
        lines.append({
            "group_id": group.id, "group": group.name, "category": group.top_category,
            "positions": group.positions,
            "approved": _f(item.approved) if item else None,
            "occupied": _f(item.occupied) if item else None,
            "vacant": _f(item.vacant) if item else None,
            "salary": _f(salary), "salary_estimated": salary is None and price is not None,
            "payroll_approved": _f(annual(item.approved, salary)) if item else None,
            "payroll_occupied": _f(annual(item.occupied, salary)) if item else None,
            "required": _f(row.required_fte) if row else None,
            "deviation": _f(deviation),
            "deviation_cost": _f(annual(deviation, price)),
            "status": row.status if row else None,
        })
    by_category = {}
    for category in staffing_analysis.CATEGORIES:
        part = {gid: it for gid, it in items.items()
                if any(line["group_id"] == gid and line["category"] == category
                       for line in lines)}
        by_category[category] = totals_of(part).out()
    return {
        "organization_id": org.id, "organization": org.name, "year": year, "basis": basis,
        "schedule": None if schedule is None else {
            "status": schedule.status, "status_title": STATUSES.get(schedule.status),
            "approved_at": schedule.approved_at, "updated_at": schedule.updated_at,
            "comment": schedule.comment},
        "lines": lines, "totals": totals_of(items).out(), "by_category": by_category,
        "history": history(db, org.id, year),
    }


# --- списки и дашборд ----------------------------------------------------------------


def _last_change(versions: list, names: dict[int, str]) -> dict | None:
    if len(versions) < 2:
        return None
    return version_out(versions[-1], versions[-2], names)


def territory(db: Session, orgs: list[Organization], year: str) -> dict:
    """Строка на учреждение: штатка, занятость, ФОТ и последнее изменение."""
    ids = [o.id for o in orgs]
    schedules = _schedules(db, ids, year)
    versions = versions_of(db, ids, year)
    names = group_names(db)
    items, overall = [], Totals(payroll_approved=ZERO, payroll_occupied=ZERO)
    for org in orgs:
        schedule = schedules.get(org.id)
        total = totals_of(items_of(schedule))
        last = _last_change(versions.get(org.id, []), names)
        items.append({
            "organization_id": org.id, "organization": org.name, "org_type": org.org_type,
            "municipality": org.municipality.name,
            "status": schedule.status if schedule else None,
            "status_title": STATUSES.get(schedule.status) if schedule else "нет штатки",
            "updated_at": schedule.updated_at if schedule else None,
            **total.out(),
            "staffed_pct": (None if total.occupied is None or not total.approved
                            else round(float(total.occupied / total.approved * 100), 1)),
            "last_change": last,
        })
        if schedule is not None:
            overall.approved += total.approved
            overall.payroll_approved += total.payroll_approved or ZERO
            if total.occupied is not None and overall.occupied is not None:
                overall.occupied += total.occupied
                overall.payroll_occupied += total.payroll_occupied or ZERO
            overall.missing_salary += total.missing_salary
    return {"year": year, "items": items, "totals": overall.out()}


def dashboard(db: Session, orgs: list[Organization], year: str, basis: str) -> dict:
    ids = [o.id for o in orgs]
    staffing_analysis.ensure(db, year, ids)
    names = {o.id: o for o in orgs}
    schedules = _schedules(db, ids, year)
    fallback = average_salaries(schedules)
    items = {oid: items_of(s) for oid, s in schedules.items()}
    rows = staffing.current_rows(db, year, ids, basis=basis)
    groups = {g.id: g for g in db.scalars(select(PersonnelGroup)
                                          .order_by(PersonnelGroup.sort_order))}

    status = {c: dict.fromkeys(staffing_analysis.STATUS_TITLES, 0)
              for c in staffing_analysis.CATEGORIES}
    by_group: dict[int, dict] = {}
    by_org: dict[int, dict] = defaultdict(lambda: {"deficit": ZERO, "surplus": ZERO,
                                                   "deficit_cost": ZERO, "surplus_cost": ZERO})
    problem_orgs, no_data_orgs = set(), set()
    estimated = False
    for row in rows:
        if row.personnel_group_id is None:
            status[row.top_category][row.status] += 1
            if row.status == "no_data":
                no_data_orgs.add(row.organization_id)
            elif row.status != "normal":
                problem_orgs.add(row.organization_id)
            continue
        group = groups.get(row.personnel_group_id)
        if group is None:
            continue
        slot = by_group.setdefault(group.id, {
            "group_id": group.id, "group": group.name, "category": group.top_category,
            "required": ZERO, "fact": ZERO, "deficit": ZERO, "surplus": ZERO,
            "deficit_cost": ZERO, "surplus_cost": ZERO, "payroll": ZERO})
        if row.required_fte is not None:
            slot["required"] += dec(row.required_fte)
        if row.fact_fte is not None:
            slot["fact"] += dec(row.fact_fte)
        if row.status not in ("deficit", "surplus") or row.deviation_fte is None:
            continue
        item = items.get(row.organization_id, {}).get(group.id)
        salary = item.salary if item else None
        if salary is None:
            salary = fallback.get(group.id)
            estimated = estimated or salary is not None
        size = abs(dec(row.deviation_fte))
        cost = annual(size, salary) or ZERO
        kind = row.status if row.status == "deficit" else "surplus"
        slot[kind] += size
        slot[f"{kind}_cost"] += cost
        by_org[row.organization_id][kind] += size
        by_org[row.organization_id][f"{kind}_cost"] += cost

    totals = Totals(payroll_approved=ZERO, payroll_occupied=ZERO)
    for org_items in items.values():
        total = totals_of(org_items)
        totals.approved += total.approved
        totals.payroll_approved += total.payroll_approved or ZERO
        if total.occupied is not None and totals.occupied is not None:
            totals.occupied += total.occupied
            totals.payroll_occupied += total.payroll_occupied or ZERO
        totals.missing_salary += total.missing_salary
        for gid, item in org_items.items():
            if gid in by_group and item.salary is not None:
                by_group[gid]["payroll"] += annual(item.approved, item.salary)

    municipalities: dict[int, dict] = {}
    for org in orgs:
        slot = municipalities.setdefault(org.municipality_id, {
            "municipality_id": org.municipality_id, "municipality": org.municipality.name,
            "organizations": 0, "problems": 0, "no_data": 0, "deficit": ZERO, "surplus": ZERO,
            "deficit_cost": ZERO, "payroll": ZERO})
        slot["organizations"] += 1
        slot["problems"] += org.id in problem_orgs
        slot["no_data"] += org.id in no_data_orgs
        slot["deficit"] += by_org[org.id]["deficit"] if org.id in by_org else ZERO
        slot["surplus"] += by_org[org.id]["surplus"] if org.id in by_org else ZERO
        slot["deficit_cost"] += by_org[org.id]["deficit_cost"] if org.id in by_org else ZERO
        slot["payroll"] += totals_of(items.get(org.id, {})).payroll_approved or ZERO

    top = sorted(((oid, v) for oid, v in by_org.items() if v["deficit"] or v["surplus"]),
                 key=lambda pair: -(pair[1]["deficit_cost"] + pair[1]["surplus_cost"]))[:8]
    group_names_ = {g.id: g.name for g in groups.values()}
    versions = versions_of(db, ids, year)
    changes = []
    for oid, org_versions in versions.items():
        for i in range(1, len(org_versions)):
            out = version_out(org_versions[i], org_versions[i - 1], group_names_)
            if out["changes"]:
                changes.append({**out, "organization_id": oid,
                                "organization": names[oid].name})
    changes.sort(key=lambda c: c["created_at"], reverse=True)

    def money(d: dict) -> dict:
        return {k: (float(v) if isinstance(v, Decimal) else v) for k, v in d.items()}

    deficit = sum((g["deficit"] for g in by_group.values()), ZERO)
    surplus = sum((g["surplus"] for g in by_group.values()), ZERO)
    return {
        "year": year, "basis": basis, "organizations": len(orgs),
        "kpi": {
            "problems": len(problem_orgs), "no_data": len(no_data_orgs),
            "normal": len(orgs) - len(problem_orgs | no_data_orgs),
            "deficit_fte": float(deficit), "surplus_fte": float(surplus),
            "deficit_cost": float(sum((g["deficit_cost"] for g in by_group.values()), ZERO)),
            "surplus_cost": float(sum((g["surplus_cost"] for g in by_group.values()), ZERO)),
            "cost_estimated": estimated,
            **totals.out(),
        },
        "status": status,
        "by_group": [money(by_group[g]) for g in groups if g in by_group],
        "by_municipality": [money(m) for m in sorted(municipalities.values(),
                                                     key=lambda m: m["municipality"])],
        "top": [{"organization_id": oid, "organization": names[oid].name,
                 "municipality": names[oid].municipality.name, **money(v)} for oid, v in top],
        "changes": changes[:10],
    }


def deviation_cost(db: Session, row: StaffingAnalysisResult) -> Decimal | None:
    """Сколько в год стоит отклонение строки анализа (для текста заявки)."""
    schedules = _schedules(db, [row.organization_id], row.academic_year)
    items = items_of(schedules.get(row.organization_id))
    org = db.get(Organization, row.organization_id)
    fallback = average_salaries(_schedules(db, [o.id for o in db.scalars(
        select(Organization).where(Organization.municipality_id == org.municipality_id))],
        row.academic_year))
    if row.personnel_group_id is not None:
        targets = [row]
    else:
        targets = [r for r in staffing.current_rows(db, row.academic_year,
                                                     [row.organization_id],
                                                     category=row.top_category,
                                                     basis=row.basis)
                   if r.personnel_group_id is not None and r.status == row.status]
    total, known = ZERO, False
    for r in targets:
        if r.deviation_fte is None:
            continue
        item = items.get(r.personnel_group_id)
        salary = item.salary if item and item.salary is not None \
            else fallback.get(r.personnel_group_id)
        cost = annual(abs(dec(r.deviation_fte)), salary)
        if cost is not None:
            total += cost
            known = True
    return total if known else None
