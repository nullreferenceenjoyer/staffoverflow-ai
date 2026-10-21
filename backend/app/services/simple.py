"""Простые расчёты по школе: уборщицы и хозотдел. Каждый — в одну строку арифметики.

Уборщицы:   нужно = большее из (классы ÷ классов на ставку, площадь ÷ м² на ставку),
            вверх до сотых ставки. Лишние = есть − нужно.
Хозотдел:   своя служба школы сравнивается с заявками школы, которые она сделала. Заявки —
            только часть её времени (остальное — плановые работы), поэтому:
            нужно = часы заявок ÷ (рабочие дни × часов в день × нормальная загрузка ×
            доля времени на заявки), вверх до сотых, не меньше минимума.
            Лишние = есть − нужно.
            Школа без своего хозотдела обслуживается бригадой управления — у бригады
            свой расчёт: заявки и дорога по всем закреплённым школам.
Разница меньше 0,01 ставки — норма.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Brigade,
    IncomingRequest,
    InstitutionMetrics,
    Organization,
    PersonnelGroup,
    RequestStatus,
    Role,
    StaffingLine,
    StaffingSchedule,
    User,
)
from app.services import app_settings, effort, helpdesk, routing, workload

TOLERANCE = 0.01


def up(value: float) -> float:
    """Вверх до сотых ставки."""
    return math.ceil(round(value * 100, 6)) / 100


def _f(value) -> float | None:
    return None if value is None else float(value)


def _metrics(db: Session, ids: list[int], year: str) -> dict[int, InstitutionMetrics]:
    if not ids:
        return {}
    return {m.organization_id: m for m in db.scalars(select(InstitutionMetrics).where(
        InstitutionMetrics.organization_id.in_(ids), InstitutionMetrics.academic_year == year))}


def _from_schedule(db: Session, ids: list[int], year: str, code: str,
                   bucket: str = "") -> dict[int, float]:
    """Ставки группы по штатке школы — если школа ведёт штатку по должностям."""
    if not ids:
        return {}
    rows = db.execute(
        select(StaffingSchedule.organization_id, StaffingLine.approved_fte,
               StaffingLine.occupied_fte)
        .join(StaffingLine, StaffingLine.schedule_id == StaffingSchedule.id)
        .join(PersonnelGroup, PersonnelGroup.id == StaffingLine.personnel_group_id)
        .where(StaffingSchedule.organization_id.in_(ids), StaffingSchedule.academic_year == year,
               (PersonnelGroup.code == code) | (PersonnelGroup.subcategory == bucket))).all()
    out: dict[int, float] = defaultdict(float)
    for org_id, approved, occupied in rows:
        out[org_id] += float(occupied if occupied is not None else approved or 0)
    return out


def _people(db: Session, ids: list[int], role: str) -> dict[int, list[str]]:
    out: dict[int, list[str]] = defaultdict(list)
    if ids:
        for user in db.scalars(select(User).where(User.role == role, User.is_active,
                                                  User.organization_id.in_(ids))
                               .order_by(User.full_name)):
            out[user.organization_id].append(user.full_name)
    return out


def _verdict(have: float | None, need: float | None) -> tuple[str, float | None]:
    if have is None or need is None:
        return "no_data", None
    diff = round(have - need, 2)
    if diff >= TOLERANCE:
        return "surplus", diff
    if diff <= -TOLERANCE:
        return "deficit", diff
    return "normal", diff


def cleaning(db: Session, orgs: list[Organization], year: str) -> dict:
    norm = app_settings.cleaning(db)
    ids = [o.id for o in orgs]
    metrics = _metrics(db, ids, year)
    schedule = _from_schedule(db, ids, year, "support_cleaning", "cleaning")
    people = _people(db, ids, Role.cleaner)
    items = []
    totals = {"schools": len(orgs), "filled": 0, "have": 0.0, "need": 0.0, "surplus": 0.0,
              "deficit": 0.0}
    for org in orgs:
        m = metrics.get(org.id)
        classes = m.classes_count if m else None
        area = _f(m.total_area_m2) if m else None
        have = _f(m.cleaners_fte) if m and m.cleaners_fte is not None else schedule.get(org.id)
        by_classes = classes / norm["classes_per_rate"] if classes else None
        by_area = area / norm["area_per_rate"] if area else None
        parts = [v for v in (by_classes, by_area) if v is not None]
        need = up(max(parts)) if parts else None
        status, diff = _verdict(have, need)
        missing = []
        if not classes and not area:
            missing.append("число классов или площадь")
        if have is None:
            missing.append("сколько ставок уборщиц сейчас")
        items.append({
            "organization_id": org.id, "organization": org.name, "classes": classes,
            "area": area, "have": have, "have_from": "input" if m and m.cleaners_fte is not None
            else ("schedule" if org.id in schedule else None),
            "by_classes": None if by_classes is None else round(by_classes, 2),
            "by_area": None if by_area is None else round(by_area, 2),
            "need": need, "diff": diff, "status": status, "missing": missing,
            "people": people.get(org.id, []),
        })
        if status != "no_data":
            totals["filled"] += 1
            totals["have"] += have
            totals["need"] += need
            totals["surplus"] += max(diff, 0) if status == "surplus" else 0
            totals["deficit"] += -diff if status == "deficit" else 0
    items.sort(key=lambda i: (i["status"] == "no_data", -(i["diff"] or 0), i["organization"]))
    return {"year": year, "norm": norm, "items": items, "totals": totals,
            "tolerance": TOLERANCE}


def maintenance(db: Session, orgs: list[Organization], year: str, days: int,
                territory: bool) -> dict:
    settings = app_settings.workload(db)
    days = days if days in workload.PERIODS else 90
    ids = [o.id for o in orgs]
    metrics = _metrics(db, ids, year)
    schedule = _from_schedule(db, ids, year, workload.MAINTENANCE_GROUP)
    staff = _people(db, ids, Role.executor)
    since = datetime.now(UTC) - timedelta(days=days)
    # Сколько часов работы за период — одна ставка при 100 % и при нормальной загрузке
    full_hours = workload.workdays(days) * settings["hours_per_day"]
    share = settings["requests_share_pct"] / 100
    # Сколько часов заявок одна ставка берёт за период при нормальной загрузке
    rate_hours = full_hours * settings["target_load_pct"] / 100 * share
    own: dict[int, list] = defaultdict(lambda: [0, 0.0])
    by_brigade: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    if ids:
        for r in db.scalars(select(IncomingRequest).where(
                IncomingRequest.organization_id.in_(ids), IncomingRequest.created_at >= since,
                IncomingRequest.status != RequestStatus.rejected,
                IncomingRequest.topic.in_(list(effort.BASE_HOURS)))):
            hours = float(r.effort_hours) if r.effort_hours is not None \
                else settings["default_hours"]
            if r.brigade_id is not None:
                by_brigade[r.organization_id][r.brigade_id] += 1
            else:
                own[r.organization_id][0] += 1
                own[r.organization_id][1] += hours
    brigades = list(db.scalars(select(Brigade).where(Brigade.is_active)
                               .options(selectinload(Brigade.organizations))))
    serves: dict[int, list[str]] = defaultdict(list)
    for b in brigades:
        for o in b.organizations:
            serves[o.id].append(b.name)

    schools = []
    for org in orgs:
        m = metrics.get(org.id)
        have = _f(m.maintenance_fte) if m and m.maintenance_fte is not None \
            else schedule.get(org.id)
        count, hours = own.get(org.id, (0, 0.0))
        has_own = bool(have) or bool(staff.get(org.id))
        need = None
        if has_own:
            need = max(up(hours / rate_hours) if hours else 0.0, settings["min_people"])
        status, diff = _verdict(have, need) if has_own else ("brigade", None)
        schools.append({
            "organization_id": org.id, "organization": org.name, "have": have,
            "people": staff.get(org.id, []), "requests": count, "hours": round(hours, 1),
            "need": need, "diff": diff, "status": status,
            "load_pct": round(hours / (have * full_hours * share) * 100, 1) if have else None,
            "brigades": serves.get(org.id, []),
            "brigade_requests": sum(by_brigade.get(org.id, {}).values()),
        })
    schools.sort(key=lambda s: (s["status"] in ("brigade", "no_data"), -(s["diff"] or 0),
                                s["organization"]))
    load = workload.analyze(db, orgs, days, territory=territory)
    units = [{k: u[k] for k in ("id", "name", "people", "members", "organizations", "requests",
                                "work_hours", "travel_hours", "total_hours", "load_pct",
                                "needed", "surplus", "status", "candidates",
                                "distance_unknown")}
             for u in load["units"] if u["kind"] == "brigade"]
    return {"days": days, "periods": list(workload.PERIODS), "settings": settings,
            "rate_hours": round(rate_hours), "full_hours": round(full_hours),
            "schools": schools, "brigades": units,
            "tolerance": TOLERANCE}


def requests_board(db: Session, orgs: list[Organization], days: int,
                   topics: list[str] | None = None) -> dict:
    """Сводка по хозяйственным заявкам школ: сколько пришло, как выполняются, кто делает.

    Общая часть — та же, что на дашборде заявок. Сверху — то, что нужно для расчёта
    хозотдела: сколько часов работы пришло и сколько ушло бригадам, а сколько своим.
    """
    days = days if days in workload.PERIODS else 90
    ids = [o.id for o in orgs]
    topics = [t for t in (topics or effort.BASE_HOURS) if t in effort.BASE_HOURS]
    since = helpdesk.now() - timedelta(days=days)
    items = list(db.scalars(
        select(IncomingRequest)
        .where(IncomingRequest.organization_id.in_(ids), IncomingRequest.topic.in_(topics),
               or_(IncomingRequest.status.in_(helpdesk.ACTIVE),
                   IncomingRequest.created_at >= since, IncomingRequest.resolved_at >= since))
        .options(selectinload(IncomingRequest.organization),
                 selectinload(IncomingRequest.assignee),
                 selectinload(IncomingRequest.brigade)))) if ids and topics else []
    data = helpdesk.stats(items, days=days)

    default = app_settings.workload(db)["default_hours"]
    fresh = [r for r in items if r.created_at >= since and r.status != RequestStatus.rejected]
    handlers = {key: {"key": key, "requests": 0, "active": 0, "hours": 0.0}
                for key in ("brigade", "own")}
    complexity = {c: 0 for c in helpdesk.COMPLEXITY_TITLES}
    for r in fresh:
        hours = float(r.effort_hours) if r.effort_hours is not None else default
        slot = handlers["brigade" if r.brigade_id is not None else "own"]
        slot["requests"] += 1
        slot["hours"] += hours
        complexity[r.complexity] = complexity.get(r.complexity, 0) + 1
    for r in items:
        if r.status in helpdesk.ACTIVE:
            handlers["brigade" if r.brigade_id is not None else "own"]["active"] += 1
    for slot in handlers.values():
        slot["hours"] = round(slot["hours"], 1)
    data.update({
        "created": len(fresh),
        "hours": round(sum(s["hours"] for s in handlers.values()), 1),
        "handlers": list(handlers.values()),
        "by_complexity": [{"complexity": str(c), "title": helpdesk.COMPLEXITY_TITLES[c],
                           "count": n} for c, n in complexity.items()],
        "periods": list(workload.PERIODS),
    })
    return data


def _requests_summary(items: list[IncomingRequest], default_hours: float, limit: int = 15) -> dict:
    """Короткая сводка по заявкам для карточки: сколько, часы, темы, последние."""
    moment = helpdesk.now()
    topics: dict[str, dict] = {}
    resolved = in_time = 0
    for r in items:
        hours = float(r.effort_hours) if r.effort_hours is not None else default_hours
        title = routing.TOPICS.get(r.topic, routing.TOPICS["other"]).title
        slot = topics.setdefault(r.topic, {"topic": r.topic, "title": title, "count": 0,
                                           "hours": 0.0})
        slot["count"] += 1
        slot["hours"] += hours
        if r.resolved_at is not None:
            resolved += 1
            in_time += r.due_at is None or r.resolved_at <= r.due_at
    recent = sorted(items, key=lambda r: r.created_at, reverse=True)[:limit]
    return {
        "count": len(items),
        "hours": round(sum(float(r.effort_hours) if r.effort_hours is not None
                           else default_hours for r in items), 1),
        "active": sum(1 for r in items if r.status in helpdesk.ACTIVE),
        "overdue": sum(1 for r in items if helpdesk.is_overdue(r, moment)),
        "in_time_pct": round(in_time / resolved * 100) if resolved else None,
        "by_topic": sorted(({**t, "hours": round(t["hours"], 1)} for t in topics.values()),
                           key=lambda t: -t["hours"]),
        "recent": [{
            "id": r.id, "title": r.title, "organization": r.organization.name,
            "status": r.status, "status_title": helpdesk.STATUS_TITLES.get(r.status, r.status),
            "kind": r.kind, "hours": float(r.effort_hours) if r.effort_hours is not None
            else default_hours, "created_at": r.created_at, "due_at": r.due_at,
            "assignee": r.assignee.full_name if r.assignee else None,
            "overdue": helpdesk.is_overdue(r, moment),
        } for r in recent],
    }


def _period_requests(db: Session, since, *where) -> list[IncomingRequest]:
    return list(db.scalars(
        select(IncomingRequest)
        .where(IncomingRequest.created_at >= since,
               IncomingRequest.status != RequestStatus.rejected,
               IncomingRequest.topic.in_(list(effort.BASE_HOURS)), *where)
        .options(selectinload(IncomingRequest.organization),
                 selectinload(IncomingRequest.assignee))))


def brigade_detail(db: Session, orgs: list[Organization], brigade_id: int, days: int,
                   territory: bool) -> dict | None:
    """Бригада подробно: люди и их часы, школы и выезды, заявки, как получилась загрузка."""
    days = days if days in workload.PERIODS else 90
    load = workload.analyze(db, orgs, days, territory=territory)
    unit = next((u for u in load["units"] if u["kind"] == "brigade" and u["id"] == brigade_id),
                None)
    if unit is None:
        return None
    brigade = db.get(Brigade, brigade_id)
    settings = load["settings"]
    since = datetime.now(UTC) - timedelta(days=days)
    items = _period_requests(db, since, IncomingRequest.brigade_id == brigade_id)
    return {
        "kind": "brigade", "days": days, "settings": settings,
        "name": brigade.name, "base_address": brigade.base_address,
        "unit": unit, "requests": _requests_summary(items, settings["default_hours"]),
        "workdays": round(workload.workdays(days), 1),
    }


def school_detail(db: Session, org: Organization, year: str, days: int) -> dict:
    """Свой хозотдел школы подробно: кто работает, заявки, как получилось «нужно»."""
    data = maintenance(db, [org], year, days, territory=False)
    row = data["schools"][0]
    settings = data["settings"]
    since = datetime.now(UTC) - timedelta(days=data["days"])
    items = _period_requests(db, since, IncomingRequest.organization_id == org.id,
                             IncomingRequest.brigade_id.is_(None))
    people: dict[str, dict] = {}
    for r in items:
        name = r.assignee.full_name if r.assignee else "Без исполнителя"
        slot = people.setdefault(name, {"name": name, "requests": 0, "hours": 0.0})
        slot["requests"] += 1
        slot["hours"] += float(r.effort_hours) if r.effort_hours is not None \
            else settings["default_hours"]
    for name in row["people"]:
        people.setdefault(name, {"name": name, "requests": 0, "hours": 0.0})
    brigade_items = _period_requests(db, since, IncomingRequest.organization_id == org.id,
                                     IncomingRequest.brigade_id.is_not(None))
    return {
        "kind": "school", "days": data["days"], "settings": settings,
        "name": org.name, "row": row, "rate_hours": data["rate_hours"],
        "full_hours": data["full_hours"],
        "people": sorted(({**p, "hours": round(p["hours"], 1)} for p in people.values()),
                         key=lambda p: -p["hours"]),
        "requests": _requests_summary(items, settings["default_hours"]),
        "brigade_requests": _requests_summary(brigade_items, settings["default_hours"], 5),
    }
