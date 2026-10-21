"""Уборщики: норматив по кабинетам или площади, сколько есть и сколько на одного человека.

Уборщиков оценивают по нормативу (кабинеты или м² на ставку), а не по заявкам: уборка —
ежедневная работа, заявками приходит только разовая. Поэтому заявки уборщиков показаны
для сведения, а решение «сократить» — по правилам recommend.py.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import IncomingRequest, Organization, RequestStatus, Role, User
from app.services import app_settings, recommend

GROUP = "support_cleaning"


def _per(value, fte) -> float | None:
    if value is None or not fte:
        return None
    return round(float(value) / float(fte), 1)


def build(db: Session, orgs: list[Organization], year: str, days: int,
          territory: bool) -> dict:
    data = recommend.build(db, orgs, year, days, territory=territory)
    since = datetime.now(UTC) - timedelta(days=days)
    ids = [o.id for o in orgs]
    cleaners = list(db.scalars(select(User).where(User.role == Role.cleaner, User.is_active,
                                                  User.organization_id.in_(ids))
                               .order_by(User.full_name))) if ids else []
    default_hours = app_settings.workload(db)["default_hours"]
    work: dict[int, list[float]] = defaultdict(lambda: [0, 0.0])
    if cleaners:
        for request in db.scalars(select(IncomingRequest).where(
                IncomingRequest.assignee_id.in_([c.id for c in cleaners]),
                IncomingRequest.created_at >= since,
                IncomingRequest.status != RequestStatus.rejected)):
            slot = work[request.assignee_id]
            slot[0] += 1
            slot[1] += float(request.effort_hours) if request.effort_hours is not None \
                else default_hours
    by_org: dict[int, list[dict]] = defaultdict(list)
    for c in cleaners:
        count, hours = work.get(c.id, (0, 0.0))
        by_org[c.organization_id].append({"id": c.id, "name": c.full_name,
                                          "requests": count, "hours": round(hours, 1)})

    items = []
    totals = {"required": 0.0, "approved": 0.0, "occupied": 0.0, "cut": 0.0,
              "cut_vacant": 0.0, "cost": 0.0, "hire": 0.0, "people": 0, "rooms": 0,
              "area": 0.0, "schools": 0, "schools_cut": 0, "schools_hire": 0,
              "schools_data": 0}
    for org in data["orgs"].values():
        group = next((g for g in org["groups"] if g["code"] == GROUP), None)
        metrics = org["metrics"] or {}
        rooms, area = metrics.get("rooms_count"), metrics.get("total_area_m2")
        staff = None
        if group:
            staff = group["occupied"] if group["occupied"] is not None else group["approved"]
        people = by_org.get(org["organization_id"], [])
        item = {
            "organization_id": org["organization_id"], "organization": org["organization"],
            "municipality": org["municipality"], "rooms": rooms, "area": area,
            "group": group, "cleaners": people,
            "rooms_per_fte": _per(rooms, staff), "area_per_fte": _per(area, staff),
            "rooms_per_required": _per(rooms, group["required"]) if group else None,
            "area_per_required": _per(area, group["required"]) if group else None,
        }
        items.append(item)
        totals["schools"] += 1
        totals["people"] += len(people)
        totals["rooms"] += rooms or 0
        totals["area"] += area or 0
        if group:
            for key in ("required", "approved", "occupied", "cut", "cut_vacant", "cost",
                        "hire"):
                totals[key] += group[key] or 0
            totals["cost"] += group["cost_vacant"] or 0
            totals["schools_cut"] += bool(group["cut"] or group["cut_vacant"])
            totals["schools_hire"] += group["verdict"] == "hire"
            totals["schools_data"] += group["verdict"] == "data"
    items.sort(key=lambda i: (-((i["group"] or {}).get("cut") or 0)
                              - ((i["group"] or {}).get("cut_vacant") or 0),
                              i["organization"]))
    totals["rooms_per_fte"] = _per(totals["rooms"], totals["occupied"])
    totals["area_per_fte"] = _per(totals["area"], totals["occupied"])
    return {"year": year, "days": days, "items": items, "totals": totals,
            "rules": data["rules"]}
