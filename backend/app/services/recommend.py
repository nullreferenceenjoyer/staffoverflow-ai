"""Что делать со ставками: сократить, убрать вакансии, добавить или сначала внести данные.

Решение принимается по группе должностей (норматив считается по группе), а сокращать
предлагается конкретные должности. Правила — те же, что в подсказке «Как считается»
в интерфейсе (RULES ниже); меняя одно, меняйте и другое.

    1. Занято больше нормы (сверх допуска)        -> сократить занятые ставки: люди лишние.
    2. По штатке больше, чем занято и чем нужно    -> убрать лишние вакансии: увольнять
                                                      никого не надо, освобождается бюджет.
    3. Хозотдел: по нормативу не хватает или норма,  -> сократить по загрузке, но только если
       а заявок мало (загрузка ниже нормы)              все сотрудники заведены в системе —
                                                      иначе их работа не видна.
    4. По нормативу лишние, а по заявкам хозотдел    -> не сокращать сверх того, что
       не успевает                                      позволяет загрузка.
    5. Не хватает по нормативу и загрузка нормальная -> сокращать нельзя, нужна ставка.
    6. Нет показателей, штатки или норматива          -> сначала внести данные.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import ROUND_FLOOR, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Organization, PersonnelGroup
from app.services import payroll, staffing, staffing_analysis, workload
from app.services.norms import CENT, ZERO, dec, num

QUARTER = Decimal("0.25")
BUCKETS = {
    "cleaning": "Уборщики",
    "maintenance": "Хозяйственный отдел",
    "other": "Остальной персонал",
}
GROUP_BUCKET = {"support_cleaning": "cleaning", workload.MAINTENANCE_GROUP: "maintenance"}


def bucket_of(group) -> str:
    """Уборщицы, хозотдел или остальной персонал — по коду группы или её подкатегории."""
    if group.code in GROUP_BUCKET:
        return GROUP_BUCKET[group.code]
    sub = getattr(group, "subcategory", None)
    return sub if sub in BUCKETS else "other"

RULES = [
    {"code": "cut", "title": "Занято больше нормы",
     "text": "Сократить разницу: по нормативу людей нужно меньше, чем работает. Это лишние "
             "занятые ставки — по ним нужно решение о сокращении."},
    {"code": "cut_vacant", "title": "В штатке больше ставок, чем занято и чем нужно",
     "text": "Убрать лишние вакантные ставки из штатки. Увольнять никого не нужно — "
             "освобождается заложенный в штатку фонд оплаты труда. Вакансии, которые "
             "нужны до нормы, остаются: их надо заполнить."},
    {"code": "reduce_load", "title": "Лишние ставки заняты совмещением",
     "text": "Сначала снимается совмещение и дополнительная нагрузка: люди остаются на "
             "своей одной ставке, увольнять никого не нужно. Сокращать людей приходится "
             "только то, что осталось после этого."},
    {"code": "cut_by_load", "title": "Хозотдел недогружен, хотя по нормативу не хватает",
     "text": "Норматив по площади считает худший случай. Если заявок за период мало, "
             "сотрудники простаивают — можно сократить по загрузке. Правило работает, только "
             "если все сотрудники хозотдела заведены в системе и вся работа идёт заявками."},
    {"code": "keep_by_load", "title": "По нормативу лишние, но хозотдел не успевает",
     "text": "Не сокращать больше, чем позволяет загрузка заявками: иначе работа встанет."},
    {"code": "hire", "title": "Не хватает по нормативу, загрузка нормальная",
     "text": "Сокращать нельзя: ставок меньше нормы. Нужна дополнительная ставка или "
             "заполнить вакансию."},
    {"code": "data", "title": "Не хватает данных",
     "text": "Без показателей (площадь, кабинеты, обучающиеся), утверждённой штатки или "
             "норматива система не пишет ни «лишние», ни «не хватает» — сначала внесите "
             "данные."},
    {"code": "tolerance", "title": "Допуск",
     "text": "Отклонение до 0,25 ставки или 5 % от нормы считается нормой: сокращать "
             "четверть ставки из-за округления не нужно."},
]


def _q(value: Decimal) -> Decimal:
    """Вниз до четверти ставки: сокращают целыми четвертями, а не сотыми."""
    return (value / QUARTER).quantize(Decimal(1), ROUND_FLOOR) * QUARTER


def _f(value) -> float | None:
    return None if value is None else float(value)


def _fte(value) -> str:
    value = Decimal(str(value))
    return f"{num(value)} ст."


def _allocate(lines: list[dict], amount: Decimal, kind: str) -> list[dict]:
    """Раскладывает сокращение по должностям группы: вакансии — где они есть, занятые
    ставки — с самой многочисленной должности."""
    if amount <= 0:
        return []
    if kind == "vacant":
        order = sorted((x for x in lines if x["vacant"] and x["vacant"] > 0),
                       key=lambda x: -x["vacant"])
        room = {id(x): Decimal(str(x["vacant"])) for x in order}
    elif kind == "load":
        order = sorted((x for x in lines if x.get("combined")), key=lambda x: -x["combined"])
        room = {id(x): Decimal(str(x["combined"])) for x in order}
    else:
        order = sorted((x for x in lines if (x["occupied"] if x["occupied"] is not None
                                             else x["approved"])),
                       key=lambda x: -(x["occupied"] if x["occupied"] is not None
                                       else x["approved"]))
        room = {id(x): Decimal(str(x["occupied"] if x["occupied"] is not None
                                   else x["approved"])) for x in order}
    out, left = [], amount
    for line in order:
        if left <= 0:
            break
        take = min(room[id(line)], left)
        if take <= 0:
            continue
        cost = (payroll.annual(take, dec(line["salary"])) if line["salary"] is not None
                else None)
        out.append({"line_id": line["line_id"], "position": line["position"],
                    "fte": float(take), "salary": line["salary"], "cost": _f(cost),
                    "kind": kind})
        left -= take
    return out


def _explain(row) -> list[str]:
    """Как получился норматив: «1 ставка на 1 000 м²: 12 000 м² → 12 = 12 ставок»."""
    if row is None:
        return []
    return [c.get("explain") or c.get("rule") for c in (row.coefficients_snapshot or [])
            if c.get("explain") or c.get("rule")]


def for_group(group: PersonnelGroup, lines: list[dict], occ_row, app_row,
              unit: dict | None, people: int | None, salary_fallback: Decimal | None,
              days: int, settings: dict) -> dict:
    """Решение по одной группе должностей одного учреждения."""
    row = occ_row or app_row
    bucket = bucket_of(group)
    approved = sum((Decimal(str(x["approved"] or 0)) for x in lines), ZERO)
    occ_values = [x["occupied"] for x in lines]
    occupied = (None if any(v is None for v in occ_values)
                else sum((Decimal(str(v)) for v in occ_values), ZERO))
    tracked = occupied is not None
    staff = occupied if tracked else approved
    required = dec(row.required_fte) if row and row.required_fte is not None else None
    salaries = [dec(x["salary"]) for x in lines if x["salary"] is not None]
    salary = (sum(salaries, ZERO) / len(salaries)) if salaries else salary_fallback

    why = _explain(row)
    rules: list[str] = []
    if tracked and occupied > approved:
        why.append(f"Проверьте данные: занято {_fte(occupied)} — больше, чем ставок по штатке "
                   f"({_fte(approved)})")
    odd = [x["position"] for x in lines if x["salary"] is not None and x["salary"] < 1000]
    if odd:
        why.append(f"Проверьте оклад: у «{odd[0]}» меньше 1 000 ₽ в месяц")
    reasons = list(row.missing_reasons or []) if row else ["норматив не настроен"]
    status_row = occ_row if (occ_row and occ_row.status != "no_data") or not app_row else app_row
    status = status_row.status if status_row else "no_data"
    if status_row is app_row and app_row is not None and not tracked:
        why.append("Занятость не ведётся — считаем по ставкам штатки")

    norm_cut = ZERO
    hire = ZERO
    if required is not None and status in ("surplus", "deficit", "normal"):
        dev = staff - required
        why.append(f"По нормативу нужно {_fte(required)}, "
                   f"{'занято' if tracked else 'по штатке'} {_fte(staff)}")
        if status == "surplus":
            norm_cut = dev.quantize(CENT)
        elif status == "deficit":
            hire = -dev

    # Загрузка заявками — только хозотдел учреждения
    load = None
    load_cut = None
    if bucket == "maintenance" and unit is not None and unit["people"] > 0:
        needed = Decimal(str(unit["needed"]))
        registered = unit["people"]
        load = {"people": registered, "needed": unit["needed"], "load_pct": unit["load_pct"],
                "requests": unit["requests"], "hours": unit["total_hours"],
                "capacity": unit["capacity_hours"], "days": days,
                "complete": registered + 0.25 >= float(staff)}
        why.append(f"За {days} дн. хозотдел закрыл {unit['requests']} заявок — "
                   f"{num(unit['total_hours'])} ч работы, загрузка "
                   f"{num(unit['load_pct'] or 0)} %. По норме загрузки "
                   f"({num(settings['hours_per_day'])} ч в день, "
                   f"{num(settings['target_load_pct'])} %) это работа на {_fte(needed)}")
        if load["complete"]:
            load_cut = _q(staff - needed) if staff > needed else ZERO
        else:
            why.append(f"В системе заведено {registered} сотрудников хозотдела из "
                       f"{num(staff)} ставок — загрузка видна не полностью, сокращать по "
                       "ней нельзя")

    cut = norm_cut
    if load_cut is not None:
        if load_cut > norm_cut and load_cut >= Decimal("0.5"):
            cut = load_cut
            rules.append("cut_by_load")
            hire = ZERO
            if norm_cut == 0 and required is not None and staff < required:
                why.append(f"По нормативу не хватает {_fte(required - staff)}, но работы "
                           f"заявками мало — можно сократить {_fte(cut)} по загрузке")
            else:
                why.append(f"По загрузке можно сократить {_fte(cut)}")
        elif norm_cut > 0 and load_cut < norm_cut:
            cut = load_cut
            rules.append("keep_by_load")
            why.append(f"По нормативу лишние {_fte(norm_cut)}, но заявок много — по "
                       f"загрузке можно сократить только {_fte(load_cut)}")
    # Лишние занятые ставки: сначала снимается совмещение (люди остаются на одной
    # ставке), увольнять приходится только остальное
    combined = sum((Decimal(str(x.get("combined") or 0)) for x in lines), ZERO)
    reduce_load = ZERO
    if cut > 0 and combined > 0 and "cut_by_load" not in rules:
        reduce_load = min(cut, combined)
        cut = (cut - reduce_load).quantize(CENT)
        rules.append("reduce_load")
        why.append(f"Из занятых {_fte(combined)} — совмещение и дополнительная нагрузка: "
                   f"уменьшить нагрузку на {_fte(reduce_load)} без увольнений")
        if cut > 0:
            why.append(f"Остальные {_fte(cut)} — это люди: сократить или не замещать, когда "
                       "уйдут сами")
    if cut > 0 and "cut_by_load" not in rules:
        rules.append("cut")

    # Вакансии сверх того, что нужно до нормы
    vacant = approved - occupied if tracked else ZERO
    cut_vacant = ZERO
    if tracked and vacant > 0:
        if required is not None and status != "no_data":
            keep = max(required - occupied, ZERO) if "cut_by_load" not in rules else ZERO
            cut_vacant = max(vacant - keep, ZERO).quantize(CENT)
            if cut_vacant > 0:
                rules.append("cut_vacant")
                why.append(f"Вакантно {_fte(vacant)}"
                           + (f", для нормы нужно заполнить {_fte(keep)}" if keep else "")
                           + f" — лишние вакансии {_fte(cut_vacant)}")
            elif keep > 0:
                why.append(f"Вакантно {_fte(vacant)} — их нужно заполнить до нормы")
    if hire > 0:
        rules.append("hire")
        why.append(f"Не хватает {_fte(hire)} — сокращать нельзя")
    if status in ("no_data", "warning") and not cut and not cut_vacant:
        rules.append("data")

    positions_cut = (_allocate(lines, cut, "people") + _allocate(lines, reduce_load, "load")
                     + _allocate(lines, cut_vacant, "vacant"))
    for item in positions_cut:
        if item["cost"] is None and salary is not None:
            item["cost"] = _f(payroll.annual(Decimal(str(item["fte"])), salary))

    def cost_of(kind: str) -> Decimal:
        return sum((Decimal(str(p["cost"] or 0)) for p in positions_cut if p["kind"] == kind),
                   ZERO)

    cost_people, cost_load, cost_vacant = cost_of("people"), cost_of("load"), cost_of("vacant")

    if cut > 0:
        verdict = "cut"
    elif reduce_load > 0:
        verdict = "reduce_load"
    elif cut_vacant > 0:
        verdict = "cut_vacant"
    elif hire > 0:
        verdict = "hire"
    elif status in ("no_data", "warning"):
        verdict = "data"
    else:
        verdict = "ok"
    return {
        "group_id": group.id, "group": group.name, "code": group.code, "bucket": bucket,
        "category": group.top_category, "required": _f(required), "approved": _f(approved),
        "occupied": _f(occupied), "vacant": _f(vacant) if tracked else None,
        "people": people, "status": status, "verdict": verdict, "rules": rules,
        "cut": _f(cut), "reduce_load": _f(reduce_load), "cut_vacant": _f(cut_vacant),
        "hire": _f(hire), "combined": _f(combined),
        "cost": _f(cost_people), "cost_load": _f(cost_load), "cost_vacant": _f(cost_vacant),
        "salary": _f(salary.quantize(Decimal(1)) if salary is not None else None),
        "positions_cut": positions_cut, "why": why,
        "reasons": reasons if verdict == "data" else [],
        "load": load, "lines": lines,
    }


def _lines(schedule, groups: dict[int, PersonnelGroup]) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = defaultdict(list)
    for line in schedule.lines if schedule else []:
        group = groups.get(line.personnel_group_id)
        approved = float(line.approved_fte or 0)
        occupied = None if line.occupied_fte is None else float(line.occupied_fte)
        out[line.personnel_group_id].append({
            "line_id": line.id, "position": staffing.position_name(line, group),
            "approved": approved, "occupied": occupied,
            "vacant": None if occupied is None else round(max(approved - occupied, 0), 2),
            "combined": _f(line.combined_fte),
            "salary": _f(line.salary_rub),
            "payroll": _f(payroll.annual(line.approved_fte, line.salary_rub)),
        })
    return out


def build(db: Session, orgs: list[Organization], year: str, days: int = 90,
          territory: bool = True) -> dict:
    """Решения по всем группам выбранных учреждений и загрузка бригад."""
    ids = [o.id for o in orgs]
    staffing_analysis.ensure(db, year, ids)
    groups = {g.id: g for g in db.scalars(select(PersonnelGroup)
                                          .order_by(PersonnelGroup.sort_order))}
    schedules = payroll._schedules(db, ids, year)
    fallback = payroll.average_salaries(schedules)
    rows: dict[tuple, object] = {}
    for row in staffing.current_rows(db, year, ids):
        if row.personnel_group_id is not None:
            rows[(row.organization_id, row.personnel_group_id, row.basis)] = row
    people = workload.people_by_org(db, ids)
    load = workload.analyze(db, orgs, days, territory=territory)
    onsite = {u["id"]: u for u in load["units"] if u["kind"] == "onsite"}
    settings = load["settings"]

    result = {}
    for org in orgs:
        lines = _lines(schedules.get(org.id), groups)
        present = {gid for (oid, gid, _b) in rows if oid == org.id} | set(lines)
        items = []
        for gid in [g for g in groups if g in present]:
            group = groups[gid]
            count = None
            if bucket_of(group) == "cleaning":
                count = people.get(org.id, {}).get("cleaner", 0)
            elif group.code == workload.MAINTENANCE_GROUP:
                count = people.get(org.id, {}).get("executor", 0)
            items.append(for_group(
                group, lines.get(gid, []), rows.get((org.id, gid, "occupied")),
                rows.get((org.id, gid, "approved")),
                onsite.get(org.id) if group.code == workload.MAINTENANCE_GROUP else None,
                count, fallback.get(gid), load["days"], settings))
        any_row = next((r for (oid, _g, _b), r in rows.items() if oid == org.id), None)
        total = payroll.totals_of(payroll.items_of(schedules.get(org.id)))
        cut = round(sum(i["cut"] for i in items), 2)
        reduce_load = round(sum(i["reduce_load"] for i in items), 2)
        cut_vacant = round(sum(i["cut_vacant"] for i in items), 2)
        cost = sum(i["cost"] for i in items)
        cost_load = sum(i["cost_load"] for i in items)
        cost_vacant = sum(i["cost_vacant"] for i in items)
        fot = float(total.payroll_approved or 0)
        result[org.id] = {
            "organization_id": org.id, "organization": org.name, "org_type": org.org_type,
            "municipality": org.municipality.name,
            "metrics": any_row.metrics_snapshot if any_row else {},
            "groups": items,
            "totals": {
                "cut": cut, "reduce_load": reduce_load, "cut_vacant": cut_vacant,
                "total": round(cut + reduce_load + cut_vacant, 2),
                "cost": cost, "cost_load": cost_load, "cost_vacant": cost_vacant,
                "total_cost": cost + cost_load + cost_vacant,
                "hire": sum(i["hire"] for i in items),
                "payroll": fot,
                "saving_pct": round((cost + cost_load + cost_vacant) / fot * 100, 1)
                if fot else None,
                "approved": float(total.approved), "occupied": _f(total.occupied),
                "data_missing": sum(1 for i in items if i["verdict"] == "data"),
            },
        }
    return {"orgs": result, "load": load, "rules": RULES}


def actions_of(org: dict) -> list[dict]:
    """Что сделать учреждению — по порядку экономии. Для директора это главный список."""
    out = []
    for g in org["groups"]:
        people_cut = [p for p in g["positions_cut"] if p["kind"] == "people"]
        load_cut = [p for p in g["positions_cut"] if p["kind"] == "load"]
        vacant_cut = [p for p in g["positions_cut"] if p["kind"] == "vacant"]
        if people_cut:
            out.append({"kind": "cut_by_load" if "cut_by_load" in g["rules"] else "cut",
                        "group": g["group"], "bucket": g["bucket"], "fte": g["cut"],
                        "cost": g["cost"], "positions": people_cut, "why": g["why"],
                        "rules": g["rules"]})
        if load_cut:
            out.append({"kind": "reduce_load", "group": g["group"], "bucket": g["bucket"],
                        "fte": g["reduce_load"], "cost": g["cost_load"], "positions": load_cut,
                        "why": g["why"], "rules": g["rules"]})
        if vacant_cut:
            out.append({"kind": "cut_vacant", "group": g["group"], "bucket": g["bucket"],
                        "fte": g["cut_vacant"], "cost": g["cost_vacant"],
                        "positions": vacant_cut, "why": g["why"], "rules": g["rules"]})
        if g["verdict"] == "hire":
            out.append({"kind": "hire", "group": g["group"], "bucket": g["bucket"],
                        "fte": g["hire"], "cost": None, "positions": [], "why": g["why"],
                        "rules": g["rules"]})
        if g["verdict"] == "data":
            out.append({"kind": "data", "group": g["group"], "bucket": g["bucket"],
                        "fte": None, "cost": None, "positions": [],
                        "why": g["reasons"] or g["why"], "rules": g["rules"]})
    order = {"cut": 0, "cut_by_load": 0, "reduce_load": 1, "cut_vacant": 1, "hire": 2,
             "data": 3}
    out.sort(key=lambda a: (order[a["kind"]], -(a["cost"] or 0), a["group"]))
    return out
