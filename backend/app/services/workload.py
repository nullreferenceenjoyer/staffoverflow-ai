"""Загрузка хозяйственного отдела и бригад: сколько людей нужно на тот объём работы,
который реально приходит заявками.

Считается по хозяйственным заявкам за период (по умолчанию 90 дней):

    работа    = Σ трудоёмкости заявок (у заявки без оценки — default_hours); у хозотдела
                школы заявки — только часть времени (requests_share_pct), поэтому
                работа = часы заявок ÷ эта доля
    дорога    = только у бригады: каждый выезд (учреждение × день) — путь от базы
                туда и обратно, 2 × км / скорость
    ёмкость   = люди × рабочие дни периода × часов в день
    загрузка  = (работа + дорога) / ёмкость
    нужно     = (работа + дорога) / (рабочие дни × часов в день × нормальная загрузка),
                вверх до 0,5 ставки, но не меньше min_people
    лишние    = люди − нужно

Если лишние есть, первыми в списке на сокращение стоят наименее загруженные люди —
это подсказка руководителю, решение принимает он.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Brigade,
    IncomingRequest,
    Organization,
    PersonnelGroup,
    RequestStatus,
    Role,
    StaffingLine,
    User,
)
from app.services import app_settings, effort, geo

PERIODS = (30, 90, 180, 365)
MAINTENANCE_GROUP = "support_maintenance"


def workdays(days: int) -> float:
    return days * 5 / 7


def round_up_half(value: float) -> float:
    # Хвост меньше 0,01 ставки — погрешность часов, а не повод добавлять полчеловека
    return math.ceil(round(value * 2 - 0.02, 6)) / 2


@dataclass
class Person:
    id: int
    name: str
    hours: float = 0.0
    requests: int = 0

    def out(self) -> dict:
        return {"id": self.id, "name": self.name, "hours": round(self.hours, 1),
                "requests": self.requests}


@dataclass
class Place:
    id: int
    name: str
    distance_km: float | None = None
    requests: int = 0
    hours: float = 0.0
    trips: set = field(default_factory=set)


@dataclass
class Unit:
    """Бригада управления или хозяйственный отдел одного учреждения."""

    key: str
    kind: str  # brigade | onsite
    id: int
    name: str
    municipality: str | None
    people: list[Person]
    places: dict[int, Place] = field(default_factory=dict)
    requests: int = 0
    work_hours: float = 0.0
    travel_hours: float = 0.0
    distance_unknown: bool = False

    def calculate(self, settings: dict, days: int, salary: Decimal | None) -> dict:
        count = len(self.people)
        hours_day = settings["hours_per_day"]
        target = settings["target_load_pct"] / 100
        share = settings["requests_share_pct"] / 100 if self.kind == "onsite" else 1.0
        work = self.work_hours / share if share else self.work_hours
        total = work + self.travel_hours
        capacity = count * workdays(days) * hours_day
        load = round(total / capacity * 100, 1) if capacity else None
        needed = round_up_half(total / (workdays(days) * hours_day * target)) if total else 0.0
        needed = max(needed, settings["min_people"] if (self.places or total) else 0.0)
        surplus = round(count - needed, 1) if count else 0.0
        if not count:
            status = "no_people"
        elif surplus >= 0.5:
            status = "surplus"
        elif load is not None and load > 100:
            status = "overload"
        else:
            status = "normal"
        people = sorted(self.people, key=lambda p: (p.hours, p.requests, p.name))
        # Кого сократить первым: наименее загруженных, по числу целых лишних людей
        candidates = [p.name for p in people[:int(surplus)]] if surplus >= 1 else []
        cost = (float(salary) * 12 * surplus if salary is not None and surplus > 0 else None)
        months = days / 30
        places = sorted(self.places.values(), key=lambda p: (-p.requests, p.name))
        return {
            "key": self.key, "kind": self.kind, "id": self.id, "name": self.name,
            "municipality": self.municipality, "people": count,
            "members": [p.out() for p in people],
            "organizations": [{
                "id": p.id, "name": p.name, "requests": p.requests,
                "hours": round(p.hours, 1), "trips": len(p.trips),
                "distance_km": None if p.distance_km is None else round(p.distance_km, 1),
                "per_month": round(p.requests / months, 1) if months else None,
            } for p in places],
            "requests": self.requests, "work_hours": round(self.work_hours, 1),
            "routine_hours": round(work - self.work_hours, 1),
            "travel_hours": round(self.travel_hours, 1), "total_hours": round(total, 1),
            "capacity_hours": round(capacity, 1), "load_pct": load, "needed": needed,
            "surplus": surplus, "status": status, "candidates": candidates,
            "distance_unknown": self.distance_unknown,
            "cost": None if cost is None else round(cost), "cost_estimated": True,
        }


def maintenance_salary(db: Session) -> Decimal | None:
    """Средний оклад ставки хозяйственного отдела по всем штаткам — цена лишнего человека."""
    value = db.scalar(select(func.avg(StaffingLine.salary_rub))
                      .join(PersonnelGroup, PersonnelGroup.id == StaffingLine.personnel_group_id)
                      .where(PersonnelGroup.code == MAINTENANCE_GROUP,
                             StaffingLine.salary_rub.is_not(None)))
    return None if value is None else Decimal(value).quantize(Decimal(1))


def _brigades(db: Session, orgs: list[Organization], territory: bool) -> list[Brigade]:
    """Бригады, которые касаются выбранных учреждений: обслуживают хотя бы одно из них
    или (для управления) работают в том же муниципалитете."""
    ids = {o.id for o in orgs}
    municipalities = {o.municipality_id for o in orgs}
    brigades = db.scalars(select(Brigade).where(Brigade.is_active).order_by(Brigade.name)
                          .options(selectinload(Brigade.members),
                                   selectinload(Brigade.organizations),
                                   selectinload(Brigade.municipality)))
    return [b for b in brigades
            if any(o.id in ids for o in b.organizations)
            or (territory and (b.municipality_id in municipalities
                               or (b.municipality_id is None and not b.organizations)))]


def _requests(db: Session, since: datetime) -> list[IncomingRequest]:
    items = list(db.scalars(
        select(IncomingRequest)
        .where(IncomingRequest.created_at >= since,
               IncomingRequest.status != RequestStatus.rejected,
               IncomingRequest.topic.in_(list(effort.BASE_HOURS)))
        .options(selectinload(IncomingRequest.organization))))
    # Крупная работа, разбитая на этапы, считается по этапам, а не дважды
    parents = {r.parent_id for r in items if r.parent_id is not None}
    return [r for r in items if r.id not in parents]


def analyze(db: Session, orgs: list[Organization], days: int = 90, *,
            territory: bool = True, moment: datetime | None = None) -> dict:
    """Загрузка бригад и хозотделов учреждений, которые касаются выбранных учреждений.

    territory — смотрит управление (бригады своего округа видны, даже если ни одной
    выбранной школы не обслуживают); директору — только то, что работает у него."""
    days = days if days in PERIODS else 90
    settings = app_settings.workload(db)
    moment = moment or datetime.now(UTC)
    since = moment - timedelta(days=days)
    org_ids = {o.id for o in orgs}
    salary = maintenance_salary(db)
    speed = settings["travel_speed_kmh"]
    default_hours = settings["default_hours"]

    units: list[Unit] = []
    by_brigade: dict[int, Unit] = {}
    by_member: dict[int, tuple[Unit, Person]] = {}
    for brigade in _brigades(db, orgs, territory):
        people = [Person(m.id, m.full_name) for m in brigade.members if m.is_active]
        unit = Unit(f"brigade-{brigade.id}", "brigade", brigade.id, brigade.name,
                    brigade.municipality.name if brigade.municipality else None, people)
        for org in brigade.organizations:
            unit.places[org.id] = Place(org.id, org.name, geo.km_between(brigade, org))
        units.append(unit)
        by_brigade[brigade.id] = unit
        for person in people:
            by_member[person.id] = (unit, person)

    executors = db.scalars(select(User).where(User.role == Role.executor, User.is_active,
                                              User.organization_id.in_(org_ids))
                           .order_by(User.full_name)) if org_ids else []
    by_org: dict[int, Unit] = {}
    names = {o.id: o for o in orgs}
    for user in executors:
        unit = by_org.get(user.organization_id)
        if unit is None:
            org = names[user.organization_id]
            unit = Unit(f"org-{org.id}", "onsite", org.id, org.name,
                        org.municipality.name if org.municipality else None, [])
            unit.places[org.id] = Place(org.id, org.name, 0.0)
            by_org[org.id] = unit
            units.append(unit)
        person = Person(user.id, user.full_name)
        unit.people.append(person)
        by_member[person.id] = (unit, person)

    brigade_of = {b.id: b for b in db.scalars(select(Brigade))} if by_brigade else {}
    for request in _requests(db, since):
        unit = person = None
        if request.assignee_id in by_member:
            unit, person = by_member[request.assignee_id]
        elif request.brigade_id in by_brigade:
            unit = by_brigade[request.brigade_id]
        if unit is None:
            continue
        hours = float(request.effort_hours) if request.effort_hours is not None \
            else default_hours
        unit.requests += 1
        unit.work_hours += hours
        if person is not None:
            person.hours += hours
            person.requests += 1
        place = unit.places.get(request.organization_id)
        if place is None:
            # Работа в учреждении, которое за бригадой не закреплено (передали вручную)
            km = (geo.km_between(brigade_of[unit.id], request.organization)
                  if unit.kind == "brigade" and unit.id in brigade_of else 0.0)
            place = unit.places[request.organization_id] = Place(
                request.organization_id, request.organization.name, km)
        place.requests += 1
        place.hours += hours
        if unit.kind == "brigade":
            started = request.started_at or request.created_at
            trip = started.date()
            if trip not in place.trips:
                place.trips.add(trip)
                if place.distance_km is None:
                    unit.distance_unknown = True
                else:
                    unit.travel_hours += 2 * place.distance_km / speed

    out = [u.calculate(settings, days, salary) for u in units]
    out.sort(key=lambda u: (-max(u["surplus"], 0), u["load_pct"] if u["load_pct"] is not None
                            else 1e9, u["name"]))
    surplus = [u for u in out if u["status"] == "surplus"]
    totals = {
        "units": len(out), "people": sum(u["people"] for u in out),
        "needed": sum(u["needed"] for u in out),
        "surplus": round(sum(u["surplus"] for u in surplus), 1),
        "surplus_units": len(surplus),
        "overloaded": sum(1 for u in out if u["status"] == "overload"),
        "cost": round(sum(u["cost"] or 0 for u in surplus)) if salary is not None else None,
        "requests": sum(u["requests"] for u in out),
        "hours": round(sum(u["total_hours"] for u in out), 1),
    }
    for kind in ("brigade", "onsite"):
        part = [u for u in surplus if u["kind"] == kind]
        totals[f"{kind}_surplus"] = round(sum(u["surplus"] for u in part), 1)
        totals[f"{kind}_cost"] = (round(sum(u["cost"] or 0 for u in part))
                                  if salary is not None else None)
    return {"days": days, "periods": list(PERIODS), "settings": settings,
            "salary": None if salary is None else float(salary),
            "units": out, "totals": totals,
            "since": since.isoformat(), "calculated_at": moment.isoformat()}


def people_by_org(db: Session, org_ids: list[int]) -> dict[int, dict[str, int]]:
    """Сколько уборщиков и сотрудников хозотдела заведено в системе по учреждениям."""
    if not org_ids:
        return {}
    rows = db.execute(select(User.organization_id, User.role, func.count())
                      .where(User.organization_id.in_(org_ids), User.is_active,
                             User.role.in_((Role.cleaner, Role.executor)))
                      .group_by(User.organization_id, User.role)).all()
    result: dict[int, dict[str, int]] = defaultdict(lambda: {"cleaner": 0, "executor": 0})
    for org_id, role, count in rows:
        result[org_id][role] = count
    return result
