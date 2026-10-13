"""Загрузка АУП и вспомогательного персонала по площадкам.

Обычный расчёт (staffing.py) сравнивает факт с нормативом внутри одного учреждения.
Здесь единица анализа другая — площадка: корпуса, которые стоят рядом, даже если они
числятся за разными учреждениями. Для каждой функции считается объём работы в ставках
и сравнивается с тем, сколько ставок на площадке занято. Если три человека в соседних
корпусах делают работу, с которой справится один, это видно сразу.

Объём работы берётся из тех же нормативов, но без минимумов и округлений: именно они
и дают «ставку на каждое здание», которая потом простаивает. Объём учреждения делится
между его корпусами по тому показателю, от которого зависит норматив: площадь — по
площади, контингент — по наполняемости или проектной мощности из РГИС.

Модуль не ходит в базу, данные готовит analytics.load_sites.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field

from app.models import Category
from app.services.functions import BY_CODE, function_title
from app.services.staffing import NormRule, ru

DEFAULT_RADIUS_M = 300
# Меньше этого расхождения в ставках рекомендацию не даём
MIN_EXCESS = 0.5
# Загрузка выше — работа есть, даже если ставок чуть больше расчётного
FULL_LOAD = 0.8
STEP = 0.25
# Здание заполнено меньше чем на столько от проектной мощности — отдельное замечание
LOW_OCCUPANCY = 0.5

CONTINGENT_DRIVERS = {"students_total", "students_school", "students_preschool",
                      "students_distance", "students_home", "special_needs", "classes_total",
                      "classes_primary", "classes_basic", "classes_secondary",
                      "groups_preschool"}
CATEGORIES = (Category.admin.value, Category.support.value)
# Руководство у каждого юридического лица своё: директора и заместителей соседних
# учреждений в общий объём не складываем, даже если здания стоят через забор
ORG_BOUND = ("director", "deputy_director")


@dataclass
class SiteBuilding:
    id: int
    org_id: int
    org_name: str
    org_type: str
    municipality_id: int
    municipality: str
    name: str
    area: float
    floors: int = 1
    address: str | None = None
    lat: float | None = None
    lon: float | None = None
    capacity: int | None = None
    occupancy: int | None = None
    students: float = 0.0  # сколько обучающихся приходится на корпус, считается ниже

    @property
    def located(self) -> bool:
        return self.lat is not None and self.lon is not None


@dataclass
class StaffRow:
    """Ставки одной функции в одном корпусе."""

    org_id: int
    building_id: int | None
    function_code: str
    category: str
    rate: float
    pay: float = 0.0
    vacant_rate: float = 0.0
    people: int = 0


@dataclass
class FunctionLoad:
    function_code: str
    title: str
    category: str
    actual: float = 0.0
    pay: float = 0.0
    vacant: float = 0.0
    people: int = 0
    volume: float = 0.0
    requests: int = 0
    organization: str | None = None  # заполняется для функций из ORG_BOUND
    by_building: dict[int, dict[str, float]] = field(default_factory=dict)

    @property
    def required(self) -> float:
        """Сколько ставок нужно площадке: объём, округлённый вверх до четверти."""
        if self.volume <= 0:
            return 0.0
        return round(math.ceil(self.volume / STEP - 1e-9) * STEP, 2)

    @property
    def load(self) -> float | None:
        return self.volume / self.actual if self.actual else None

    @property
    def excess(self) -> float:
        return round(self.actual - self.required, 2)

    @property
    def staffed_buildings(self) -> int:
        return sum(1 for b in self.by_building.values() if b["actual"] > 0)

    @property
    def verdict(self) -> str:
        if self.actual and self.excess >= MIN_EXCESS and (self.load or 0) < FULL_LOAD:
            return "duplicate" if self.staffed_buildings > 1 else "idle"
        if -self.excess >= MIN_EXCESS:
            return "overload"
        return "ok"


def distance_m(a: SiteBuilding, b: SiteBuilding) -> float | None:
    """Расстояние по прямой между корпусами, метры."""
    if not (a.located and b.located):
        return None
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    dlat = lat2 - lat1
    dlon = math.radians(b.lon - a.lon)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(h))


_ADDRESS_NOISE = re.compile(r"\b(?:корп(?:ус)?|стр(?:оение)?|лит(?:ера)?|к)\.?\s*[\dа-я]+\b")


def address_key(address: str | None) -> str | None:
    """«ул. Ленина, д. 5, корп. 2» и «Ленина ул., 5» должны совпасть: корпуса
    и строения одного дома стоят на одном участке."""
    if not address:
        return None
    text = address.lower().replace("ё", "е")
    text = _ADDRESS_NOISE.sub(" ", text)
    words = re.findall(r"[а-яa-z]{3,}|\d+[а-я]?", text)
    words = [w for w in words if w not in ("улица", "дом", "город", "область", "обл")]
    # Без номера дома адрес слишком общий, чтобы по нему объединять
    if not any(w[0].isdigit() for w in words):
        return None
    return " ".join(sorted(words))


def group_sites(buildings: list[SiteBuilding], radius_m: float) -> list[list[SiteBuilding]]:
    """Объединяет корпуса в площадки: рядом по координатам или по одному адресу."""
    parent = {b.id: b.id for b in buildings}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    by_municipality: dict[int, list[SiteBuilding]] = defaultdict(list)
    for building in buildings:
        by_municipality[building.municipality_id].append(building)

    for group in by_municipality.values():
        keys = {b.id: address_key(b.address) for b in group}
        for i, first in enumerate(group):
            for second in group[i + 1:]:
                gap = distance_m(first, second)
                same_address = keys[first.id] is not None and keys[first.id] == keys[second.id]
                if (gap is not None and gap <= radius_m) or (gap is None and same_address):
                    parent[find(first.id)] = find(second.id)

    sites: dict[int, list[SiteBuilding]] = defaultdict(list)
    for building in buildings:
        sites[find(building.id)].append(building)
    return list(sites.values())


def attribute_students(buildings: list[SiteBuilding], students_total: float) -> None:
    """Раскладывает контингент учреждения по корпусам: по фактической наполняемости,
    если она известна для всех корпусов, иначе по проектной мощности, иначе по площади."""
    if not buildings:
        return
    for key in ("occupancy", "capacity", "area"):
        weights = [getattr(b, key) or 0 for b in buildings]
        if all(w > 0 for w in weights):
            break
    else:
        weights = [1.0] * len(buildings)
    total = sum(weights)
    for building, weight in zip(buildings, weights, strict=True):
        building.students = students_total * weight / total


def pure_volume(rule: NormRule, org_type: str, metrics: dict[str, float]) -> float:
    """Объём работы по нормативу в ставках — без минимума и округления."""
    if rule.kind != "staff" or (rule.org_types and org_type not in rule.org_types):
        return 0.0
    driver = metrics.get(rule.driver, 0.0)
    if driver <= 0 or driver < rule.threshold:
        return 0.0
    volume = rule.base + rule.per_unit * driver / rule.unit_size
    return min(volume, rule.max_value) if rule.max_value is not None else volume


def building_shares(rule: NormRule, buildings: list[SiteBuilding]) -> list[float]:
    """Какая доля объёма работы учреждения приходится на каждый корпус."""
    if rule.driver == "area_sqm":
        weights = [b.area for b in buildings]
    elif rule.driver == "floors":
        weights = [float(b.floors) for b in buildings]
    elif rule.driver == "buildings":
        weights = [1.0] * len(buildings)
    elif rule.driver in CONTINGENT_DRIVERS:
        weights = [b.students for b in buildings]
    else:
        # Норматив «на учреждение» (директор): работа числится за главным корпусом
        weights = [1.0] + [0.0] * (len(buildings) - 1)
    total = sum(weights)
    if total <= 0:
        return [1.0] + [0.0] * (len(buildings) - 1)
    return [w / total for w in weights]


def main_building(buildings: list[SiteBuilding]) -> SiteBuilding:
    return max(buildings, key=lambda b: (b.capacity or 0, b.area, -b.id))


def _site_name(buildings: list[SiteBuilding]) -> str:
    organizations = list(dict.fromkeys(b.org_name for b in buildings))
    if len(buildings) == 1:
        return f"{organizations[0]}, {buildings[0].name.lower()}"
    if len(organizations) == 1:
        return f"{organizations[0]}: корпусов рядом — {len(buildings)}"
    return " + ".join(organizations[:3]) + (" и др." if len(organizations) > 3 else "")


def _span(buildings: list[SiteBuilding]) -> float | None:
    gaps = [distance_m(a, b) for i, a in enumerate(buildings) for b in buildings[i + 1:]]
    gaps = [g for g in gaps if g is not None]
    return round(max(gaps)) if gaps else None


def _recommendation(load: FunctionLoad, span: float | None) -> str:
    title = load.title + (f" ({load.organization})" if load.organization else "")
    busy = f"{ru(load.actual)} ст."
    if load.people:
        busy += f" ({load.people} чел.)"
    percent = round((load.load or 0) * 100)
    if load.verdict == "overload":
        return (f"{title}: занято {busy}, объём работы — {ru(round(load.volume, 2))} ст. "
                f"Не хватает {ru(-load.excess)} ст. — сокращать здесь нельзя, сюда стоит "
                "перевести ставки с недозагруженных площадок.")

    where = "на площадке"
    if load.verdict == "duplicate":
        where = f"в {load.staffed_buildings} соседних корпусах"
        if span is not None:
            where += f" (до {round(span)} м друг от друга)"
    text = (f"{title}: {where} занято {busy}, а объём работы — "
            f"{ru(round(load.volume, 2))} ст., загрузка {percent} %. ")
    if load.required <= 1 and load.people > 1:
        text += "С таким объёмом справится один сотрудник. "
    text += f"Достаточно {ru(load.required)} ст., {ru(load.excess)} ст. можно сократить"
    vacant = min(load.vacant, load.excess)
    if vacant > 0:
        text += f"; из них {ru(round(vacant, 2))} ст. — вакансии, без увольнений"
    return text + "."


def analyze(
    buildings: list[SiteBuilding],
    staff: list[StaffRow],
    org_metrics: dict[int, dict[str, float]],
    rules: list[NormRule],
    *,
    radius_m: float = DEFAULT_RADIUS_M,
    payroll_tax_rate: float = 0.302,
    requests: dict[tuple[int, str], int] | None = None,
) -> dict:
    """Собирает отчёт по площадкам.

    org_metrics — показатели учреждений из staffing.collect_metrics;
    requests — число заявок за период по паре (корпус, функция), если есть.
    """
    requests = requests or {}
    by_org: dict[int, list[SiteBuilding]] = defaultdict(list)
    for building in buildings:
        by_org[building.org_id].append(building)
    for org_id, group in by_org.items():
        attribute_students(group, org_metrics.get(org_id, {}).get("students_total", 0.0))

    site_of: dict[int, int] = {}
    groups = group_sites(buildings, radius_m)
    for index, group in enumerate(groups):
        for building in group:
            site_of[building.id] = index
    loads: list[dict[str, FunctionLoad]] = [{} for _ in groups]

    def load_for(building: SiteBuilding, code: str, category: str | None = None) -> FunctionLoad:
        site = loads[site_of[building.id]]
        shared = code not in ORG_BOUND
        key = code if shared else f"{code}:{building.org_id}"
        if key not in site:
            known = BY_CODE.get(code)
            site[key] = FunctionLoad(
                function_code=code, title=function_title(code),
                category=category or (known.category.value if known else Category.support.value),
                organization=None if shared else building.org_name,
            )
        site[key].by_building.setdefault(building.id, {"actual": 0.0, "volume": 0.0})
        return site[key]

    relevant = [r for r in rules if r.kind == "staff" and r.function_code in BY_CODE
                and BY_CODE[r.function_code].category.value in CATEGORIES]
    for org_id, group in by_org.items():
        metrics = org_metrics.get(org_id, {})
        for rule in relevant:
            volume = pure_volume(rule, group[0].org_type, metrics)
            if volume <= 0:
                continue
            for building, share in zip(group, building_shares(rule, group), strict=True):
                if share <= 0:
                    continue
                load = load_for(building, rule.function_code)
                load.volume += volume * share
                load.by_building[building.id]["volume"] += volume * share

    unassigned = 0.0
    buildings_by_id = {b.id: b for b in buildings}
    for row in staff:
        if row.category not in CATEGORIES or row.org_id not in by_org:
            continue
        building = buildings_by_id.get(row.building_id or 0)
        if building is None or building.org_id != row.org_id:
            building = main_building(by_org[row.org_id])
            if len(by_org[row.org_id]) > 1:
                unassigned += row.rate
        load = load_for(building, row.function_code, row.category)
        load.actual += row.rate
        load.pay += row.pay
        load.vacant += row.vacant_rate
        load.people += row.people
        load.by_building[building.id]["actual"] += row.rate

    for (building_id, code), count in requests.items():
        building = buildings_by_id.get(building_id)
        if building is not None and code in loads[site_of[building.id]]:
            loads[site_of[building.id]][code].requests += count

    def saving(load: FunctionLoad) -> int:
        if load.verdict not in ("duplicate", "idle") or not load.actual:
            return 0
        return round(load.excess * load.pay / load.actual * 12 * (1 + payroll_tax_rate))

    sites = []
    findings = []
    functions_total: dict[str, dict] = {}
    for index, group in enumerate(groups):
        group.sort(key=lambda b: (b.org_name, b.id))
        span = _span(group)
        rows = []
        for load in sorted(loads[index].values(), key=lambda item: -item.excess):
            load.actual = round(load.actual, 2)
            row = {
                "function_code": load.function_code,
                "title": load.title,
                "organization": load.organization,
                "category": load.category,
                "actual": load.actual,
                "people": load.people,
                "vacant": round(load.vacant, 2),
                "volume": round(load.volume, 2),
                "required": load.required,
                "load_pct": None if load.load is None else round(load.load * 100),
                "excess": load.excess,
                "verdict": load.verdict,
                "saving_year": saving(load),
                "requests": load.requests,
                "by_building": [
                    {"building_id": b.id, "name": b.name,
                     "actual": round(load.by_building.get(b.id, {}).get("actual", 0.0), 2),
                     "volume": round(load.by_building.get(b.id, {}).get("volume", 0.0), 2)}
                    for b in group
                ],
                "recommendation": None,
            }
            if load.verdict != "ok":
                row["recommendation"] = _recommendation(load, span)
            rows.append(row)

            total = functions_total.setdefault(load.function_code, {
                "function_code": load.function_code, "title": load.title,
                "category": load.category, "actual": 0.0, "volume": 0.0, "required": 0.0,
                "excess": 0.0, "saving_year": 0, "sites": 0})
            total["actual"] += load.actual
            total["volume"] += load.volume
            total["required"] += load.required
            if load.verdict in ("duplicate", "idle"):
                total["excess"] += load.excess
                total["saving_year"] += row["saving_year"]
                total["sites"] += 1

        actual = sum(r["actual"] for r in rows)
        volume = sum(r["volume"] for r in rows)
        flagged = [r for r in rows if r["verdict"] in ("duplicate", "idle")]
        students = sum(b.students for b in group)
        capacity = sum(b.capacity or 0 for b in group) if all(b.capacity for b in group) else None
        site = {
            "id": min(b.id for b in group),
            "name": _site_name(group),
            "municipality_id": group[0].municipality_id,
            "municipality": group[0].municipality,
            "organizations": len({b.org_id for b in group}),
            "span_m": span,
            "students": round(students),
            "capacity": capacity,
            "occupancy_pct": round(students / capacity * 100) if capacity else None,
            "actual": round(actual, 2),
            "volume": round(volume, 2),
            "load_pct": round(volume / actual * 100) if actual else None,
            "excess": round(sum(r["excess"] for r in flagged), 2),
            "vacant_in_excess": round(sum(min(r["vacant"], r["excess"]) for r in flagged), 2),
            "saving_year": sum(r["saving_year"] for r in flagged),
            "buildings": [
                {"id": b.id, "organization_id": b.org_id, "organization": b.org_name,
                 "name": b.name, "address": b.address, "lat": b.lat, "lon": b.lon,
                 "area": b.area, "floors": b.floors, "capacity": b.capacity,
                 "students": round(b.students),
                 "occupancy_pct": round(b.students / b.capacity * 100) if b.capacity else None}
                for b in group
            ],
            "functions": rows,
        }
        sites.append(site)
        for row in rows:
            if row["verdict"] != "ok":
                findings.append({
                    "site_id": site["id"], "site": site["name"],
                    "municipality": site["municipality"],
                    **{k: row[k] for k in ("function_code", "title", "organization",
                                           "category", "actual",
                                           "people", "vacant", "volume", "required",
                                           "load_pct", "excess", "verdict", "saving_year",
                                           "recommendation")},
                })
        if capacity and students / capacity < LOW_OCCUPANCY:
            findings.append({
                "site_id": site["id"], "site": site["name"],
                "municipality": site["municipality"], "function_code": None,
                "title": "Заполненность зданий", "organization": None, "category": None,
                "actual": site["actual"],
                "people": 0, "vacant": 0.0, "volume": site["volume"], "required": None,
                "load_pct": site["occupancy_pct"], "excess": 0.0, "verdict": "underused",
                "saving_year": 0,
                "recommendation": (
                    f"Проектная мощность по РГИС — {capacity} мест, занимается "
                    f"{round(students)} ({site['occupancy_pct']} %). Здания содержатся на "
                    f"полную мощность: АУП и вспомогательного персонала {ru(site['actual'])} "
                    "ст. Стоит рассмотреть перевод контингента из соседних переполненных "
                    "корпусов или консервацию части площадей."),
            })

    sites.sort(key=lambda s: (-s["saving_year"], -s["excess"], s["name"]))
    order = {"duplicate": 0, "idle": 1, "underused": 2, "overload": 3}
    findings.sort(key=lambda f: (order[f["verdict"]], -f["saving_year"], f["excess"]))

    by_function = []
    for total in functions_total.values():
        actual = total["actual"]
        by_function.append({
            **total,
            "actual": round(actual, 2),
            "volume": round(total["volume"], 2),
            "required": round(total["required"], 2),
            "excess": round(total["excess"], 2),
            "load_pct": round(total["volume"] / actual * 100) if actual else None,
        })
    by_function.sort(key=lambda f: (-f["excess"], f["title"]))

    actual = sum(s["actual"] for s in sites)
    volume = sum(s["volume"] for s in sites)
    return {
        "radius_m": radius_m,
        "totals": {
            "sites": len(sites),
            "shared_sites": sum(1 for s in sites if len(s["buildings"]) > 1),
            "buildings": len(buildings),
            "without_location": sum(1 for b in buildings if not b.located and not b.address),
            "unassigned_rate": round(unassigned, 2),
            "actual": round(actual, 2),
            "volume": round(volume, 2),
            "load_pct": round(volume / actual * 100) if actual else None,
            "excess": round(sum(s["excess"] for s in sites), 2),
            "vacant_in_excess": round(sum(s["vacant_in_excess"] for s in sites), 2),
            "saving_year": sum(s["saving_year"] for s in sites),
            "flagged_sites": sum(1 for s in sites if s["excess"] > 0),
        },
        "by_function": by_function,
        "findings": findings,
        "sites": sites,
    }
