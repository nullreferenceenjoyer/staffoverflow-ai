"""Итог анализа: сколько ставок можно высвободить, где и как.

Решения по должностям принимает recommend.py. Здесь они складываются в итог по трём
способам высвобождения:
  - убрать вакансии — ставки никто не занимает, увольнять никого не надо;
  - уменьшить нагрузку — снять совмещение и доплаты: люди остаются на своей ставке;
  - сократить занятые ставки — остальное.
Расчёт — по штатке как она есть. Увольнение, учтённое в штатке (раздел «Уволенные»),
уменьшает «занято»: ставка переходит из «сократить» в «убрать вакансии», общее число
высвобождаемых ставок не меняется.
Бригады управления в штатках школ не состоят: их лишние люди по загрузке идут в итог
управления отдельной строкой. Если загружен расчёт управления (программа), итог
сверяется с ним.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Organization
from app.services import program, recommend

KINDS = ("cut_vacant", "reduce_load", "cut")
COST = {"cut_vacant": "cost_vacant", "reduce_load": "cost_load", "cut": "cost"}
POSITION_KIND = {"vacant": "cut_vacant", "load": "reduce_load", "people": "cut"}


def _bucket(key: str) -> dict:
    return {"key": key, "title": recommend.BUCKETS[key], "required": 0.0, "approved": 0.0,
            "occupied": 0.0, "people": 0, "has_people": False, "hire": 0.0,
            **{k: 0.0 for k in KINDS}, **{COST[k]: 0.0 for k in KINDS},
            "total": 0.0, "total_cost": 0.0, "orgs_cut": 0}


def build(db: Session, orgs: list[Organization], year: str, days: int,
          territory: bool) -> dict:
    data = recommend.build(db, orgs, year, days, territory=territory)
    per_org = data["orgs"]
    load = data["load"]
    plan = program.summary(db)
    taxes = 1 + (float(plan.get("taxes_pct", 0)) / 100 if plan else 0)

    buckets = {key: _bucket(key) for key in recommend.BUCKETS}
    positions: dict[str, dict] = {}
    approved_by: dict[str, float] = {}
    schools = []
    for org in per_org.values():
        touched = set()
        for g in org["groups"]:
            slot = buckets[g["bucket"]]
            for key in ("required", "approved", "hire"):
                slot[key] += g[key] or 0
            slot["occupied"] += g["occupied"] or 0
            if g["people"] is not None:
                slot["people"] += g["people"]
                slot["has_people"] = True
            for kind in KINDS:
                slot[kind] += g[kind] or 0
                slot[COST[kind]] += g[COST[kind]] or 0
            if any(g[k] for k in KINDS):
                touched.add(g["bucket"])
            for p in g["positions_cut"]:
                item = positions.setdefault(p["position"], {
                    "position": p["position"], "bucket": g["bucket"], "category": g["category"],
                    "approved": 0.0, "required": 0.0, "schools": 0,
                    **{k: 0.0 for k in KINDS}, "cost": 0.0})
                item[POSITION_KIND[p["kind"]]] += p["fte"]
                item["cost"] += p["cost"] or 0
            for line in g["lines"]:
                approved_by[line["position"]] = approved_by.get(line["position"], 0.0) \
                    + line["approved"]
        for key in touched:
            buckets[key]["orgs_cut"] += 1
        t = org["totals"]
        actions = recommend.actions_of(org)
        schools.append({
            "organization_id": org["organization_id"], "organization": org["organization"],
            **{k: t[k] for k in KINDS}, "total": t["total"],
            "cost": t["total_cost"] * taxes, "payroll": t["payroll"] * taxes,
            "saving_pct": t["saving_pct"], "hire": t["hire"],
            "main": [{"kind": a["kind"], "group": a["group"], "fte": a["fte"]}
                     for a in actions if a["kind"] in ("cut", "reduce_load", "cut_vacant")][:3],
        })
    for slot in buckets.values():
        slot["total"] = sum(slot[k] for k in KINDS)
        slot["total_cost"] = sum(slot[COST[k]] for k in KINDS) * taxes
        for k in KINDS:
            slot[COST[k]] *= taxes
    for item in positions.values():
        item["approved"] = round(approved_by.get(item["position"], 0.0), 2)
        item["total"] = round(sum(item[k] for k in KINDS), 2)
        item["after"] = round(item["approved"] - item["total"], 2)
        item["cost"] *= taxes
        for k in KINDS:
            item[k] = round(item[k], 2)
    schools.sort(key=lambda s: (-s["total"], s["organization"]))

    onsite = [u for u in load["units"] if u["kind"] == "onsite"]
    brigades = [u for u in load["units"] if u["kind"] == "brigade"]
    brigade_cut = load["totals"]["brigade_surplus"] if territory and not plan else 0.0
    brigade_cost = (load["totals"]["brigade_cost"] or 0) if territory and not plan else 0
    totals = {k: round(sum(s[k] for s in schools), 2) for k in KINDS}
    total = round(sum(totals.values()), 2)
    cost = sum(s["cost"] for s in schools)
    payroll = sum(s["payroll"] for s in schools)
    base = float(plan["payroll_base_year"]) if plan and territory else payroll
    single = next(iter(per_org.values())) if len(per_org) == 1 and not territory else None
    hours_per_rate = int(plan.get("hours_per_rate", 1972)) if plan else 1972
    # Штатных единиц к сокращению: пока занятых ставок к сокращению столько же, сколько в
    # расчёте управления, берём его число единиц (1,75 ставки — это две единицы, а не одна);
    # после увольнений и правок штатки — по ставкам
    units = round(totals["cut"])
    if (plan and territory and plan.get("staff_units") is not None
            and abs(float(plan.get("dismissed_fte") or -1) - totals["cut"]) < 0.01):
        units = int(plan["staff_units"])
    return {
        "year": year, "days": load["days"], "periods": load["periods"],
        "organizations": len(orgs),
        "headline": {
            **totals, "total": round(total + brigade_cut, 2), "cost": cost + brigade_cost,
            "brigade_cut": brigade_cut, "brigade_cost": brigade_cost,
            "hours": round(total * hours_per_rate), "hours_per_rate": hours_per_rate,
            "payroll": payroll, "base": base,
            "saving_pct": round(cost / base * 100, 2) if base else None,
            "taxes_pct": round((taxes - 1) * 100, 1),
            "hire": round(sum(s["hire"] for s in schools), 2),
            "schools_with_cut": sum(1 for s in schools if s["total"]),
            "staff_units": units,
        },
        "plan": plan if territory or plan is None else {
            k: plan[k] for k in ("title", "basis", "state_date", "taxes_pct") if k in plan},
        "buckets": [buckets[k] for k in recommend.BUCKETS],
        "positions": sorted(positions.values(), key=lambda p: (-p["total"], p["position"])),
        "schools": schools,
        "actions": recommend.actions_of(single) if single else [],
        "groups": single["groups"] if single else [],
        "metrics": single["metrics"] if single else {},
        "totals": single["totals"] if single else None,
        "brigades": brigades,
        "onsite": onsite,
        "workload_settings": load["settings"],
        "rules": data["rules"],
    }
