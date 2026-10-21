"""Заполнение школ данными по расчёту управления образования.

В расчёте управления есть итоги по школам (сколько ставок высвобождено и за счёт чего)
и итоги по должностям по всему округу (было, сократили, стало, экономия). Штатки каждой
школы по должностям в документах нет — она восстанавливается так, чтобы сходились оба
итога:

  1. «Стало» по должности раскладывается по школам пропорционально размеру школы
     (шагом 0,25 ставки, минимум — директор, рабочий и уборщики в каждой школе).
  2. «Сократили» по должности раскладывается по школам методом пропорционального
     выравнивания: суммы по школе равны итогу школы, суммы по должности — итогу должности.
     Ушедшие сотрудники ставятся в свою школу и должность.
  3. Сокращение в клетке делится на вакансии и нагрузку в той же пропорции, что у школы.

Из этого собирается штатка «до» (по штатке = стало + сократили, занято = по штатке −
вакансии, совмещение = нагрузка) и норматив — целевая штатка «после». Анализ системы
по этой штатке даёт ровно те цифры, что в расчёте управления.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict


def r2(value: float) -> float:
    return round(value + 1e-9, 2)


def hamilton(total: float, weights: dict[str, float], step: float = 0.25,
             minimum: float = 0.0) -> dict[str, float]:
    """Делит total по ключам пропорционально весам шагом step (метод наибольших остатков).
    Остаток меньше шага добавляется самому большому, чтобы сумма сошлась до сотых."""
    keys = list(weights)
    base = minimum if minimum * len(keys) <= total else 0.0
    rest = total - base * len(keys)
    weight = sum(weights.values()) or 1.0
    units = int(round(rest / step, 6) // 1)
    quotas = {k: rest * weights[k] / weight / step for k in keys}
    counts = {k: int(quotas[k]) for k in keys}
    left = units - sum(counts.values())
    for k in sorted(keys, key=lambda k: -(quotas[k] - counts[k]))[:max(left, 0)]:
        counts[k] += 1
    out = {k: base + counts[k] * step for k in keys}
    remainder = r2(total - sum(out.values()))
    if remainder:
        biggest = max(keys, key=lambda k: weights[k])
        out[biggest] += remainder
    return {k: r2(v) for k, v in out.items()}


def ipf(rows: dict, cols: dict, base: dict, iterations: int = 400) -> dict:
    """Пропорциональное выравнивание: матрица с заданными суммами строк и столбцов,
    похожая на исходные веса."""
    x = dict(base)
    by_row: dict = defaultdict(list)
    by_col: dict = defaultdict(list)
    for key in x:
        by_row[key[0]].append(key)
        by_col[key[1]].append(key)
    for _ in range(iterations):
        for groups, targets in ((by_row, rows), (by_col, cols)):
            for name, keys in groups.items():
                current = sum(x[k] for k in keys)
                if current > 0:
                    factor = targets.get(name, 0.0) / current
                    for k in keys:
                        x[k] *= factor
    return x


def to_total(values: dict, total: float) -> dict:
    """Округление до сотых так, чтобы сумма была ровно total (наибольшие остатки)."""
    return hamilton(total, {k: max(v, 0.0) for k, v in values.items()}, step=0.01)


def round_matrix(x: dict, rows: dict, cols: dict, step: float = 0.25) -> dict:
    """Округление с сохранением сумм строк и столбцов: в строке — шагом step (сокращают
    четвертями ставки), остаток до сотых и расхождения по столбцам гасятся через самый
    большой столбец."""
    out: dict = {}
    for row, target in rows.items():
        cells = {k: v for k, v in x.items() if k[0] == row}
        if cells:
            out.update(hamilton(target, cells, step=step))
    # Должности, которым не хватило, забирают у должностей с излишком в той же школе:
    # перенос внутри строки не меняет итог школы
    for _ in range(10_000):
        error = {c: r2(t - sum(v for k, v in out.items() if k[1] == c)) for c, t in cols.items()}
        need = [c for c, e in error.items() if e > 0]
        extra = [c for c, e in error.items() if e < 0]
        if not need or not extra:
            break
        moved = False
        for p in need:
            for q in extra:
                rows_both = [k[0] for k in out if k[1] == q and out[k] > 0 and (k[0], p) in out]
                if not rows_both:
                    continue
                row = max(rows_both, key=lambda r: out[(r, q)])
                amount = r2(min(error[p], -error[q], out[(row, q)]))
                if amount <= 0:
                    continue
                out[(row, q)] = r2(out[(row, q)] - amount)
                out[(row, p)] = r2(out[(row, p)] + amount)
                moved = True
                break
            if moved:
                break
        if not moved:
            break
    return out


def build(data: dict) -> dict:
    """Штатка «до» и «после» по школам и должностям. Возвращает
    {"cells": {(школа, должность): {...}}, "salary": {должность: оклад}, ...}."""
    fill = data["fill"]
    program = data["program"]
    schools = {s["code"]: s for s in data["schools"]}
    weights = {code: float(fill["schools"][code][0]) for code in schools}
    positions = [p for p in data["positions"] if p[0] != "Педагогические работники"]
    every = fill.get("every_school", {})

    after: dict[tuple[str, str], float] = {}
    exists: dict[tuple[str, str], float] = {}
    for _cat, name, before_total_, _cut, after_total, *_ in positions:
        minimum = float(every.get(name, 0))
        for code, value in hamilton(float(after_total), weights, minimum=minimum).items():
            after[(code, name)] = value
        # Где должность была до оптимизации — только там её и сокращали
        for code, value in hamilton(float(before_total_), weights, minimum=minimum).items():
            exists[(code, name)] = value

    fixed: dict[tuple[str, str], dict[str, float]] = defaultdict(lambda: {"own": 0.0,
                                                                          "layoff": 0.0})
    for code, name, fte, basis in fill["left"]:
        fixed[(code, name)][basis] += float(fte)

    # Итог — как в документах: 215,57 минус ушедшие. Школы и должности округляются до
    # сотых так, чтобы сумма сошлась ровно
    fixed_total = sum(v["own"] + v["layoff"] for v in fixed.values())
    grand = r2(float(program["total"]) - fixed_total)
    rows = to_total({code: float(s["total"]) - float(s["own"]) - float(s["layoff"])
                     for code, s in schools.items()}, grand)
    exact_cols = {}
    for _cat, name, _before, cut, *_ in positions:
        taken = sum(v["own"] + v["layoff"] for k, v in fixed.items() if k[1] == name)
        if float(cut) - taken > 0.0001:
            exact_cols[name] = float(cut) - taken
    cols = to_total(exact_cols, grand)
    before_total = {name: float(before) for _c, name, before, *_ in positions}
    base = {(code, name): exists[(code, name)] for code in schools for name in cols
            if exists.get((code, name), 0) > 0}
    residual = round_matrix(ipf(rows, cols, base), rows, cols)

    vacancies = to_total({code: float(s["vacancies"]) for code, s in schools.items()},
                         r2(float(program["vacancies"])))
    vacancies = {code: min(v, rows[code]) for code, v in vacancies.items()}
    cells = {}
    for code in schools:
        vacancy_total = vacancies[code]
        mine = {name: residual.get((code, name), 0.0) for name in cols}
        share = vacancy_total / rows[code] if rows[code] else 0.0
        vacancy = {n: r2(min(v * share, v)) for n, v in mine.items()}
        diff = r2(vacancy_total - sum(vacancy.values()))
        if diff and mine:
            biggest = max(mine, key=lambda n: mine[n] - vacancy[n] if diff > 0 else vacancy[n])
            vacancy[biggest] = r2(vacancy[biggest] + diff)
        for _cat, name, *_ in positions:
            gone = fixed.get((code, name), {"own": 0.0, "layoff": 0.0})
            cut = mine.get(name, 0.0)
            v = vacancy.get(name, 0.0)
            load = r2(cut - v)
            people = r2(gone["own"] + gone["layoff"])
            a = after.get((code, name), 0.0)
            approved = r2(a + cut + people)
            if approved <= 0:
                continue
            cells[(code, name)] = {
                "after": a, "approved": approved, "occupied": r2(approved - v),
                "combined": load, "vacancy": v, "load": load, "people": people,
                "own": gone["own"], "layoff": gone["layoff"],
            }

    taxes = 1 + float(program.get("taxes_pct", 0)) / 100
    salary: dict[str, float] = {}
    for _cat, name, _before, cut, _after, _l, local_eco, _r, regional_eco in positions:
        economy = float(local_eco or 0) + float(regional_eco or 0)
        if cut and economy:
            salary[name] = round(economy / float(cut) / taxes, 2)
    known = sum(before_total[n] * s for n, s in salary.items())
    unknown = sum(before_total[n] for n in before_total if n not in salary)
    monthly = float(program.get("payroll_base_year", 0)) / taxes / 12
    rest = round((monthly - known) / unknown, 2) if unknown and monthly > known else 30000.0
    for name in before_total:
        salary.setdefault(name, rest)
    return {"cells": cells, "salary": salary, "positions": positions,
            "buckets": fill.get("buckets", {}), "aup": set(fill.get("aup", [])),
            "rows": rows, "cols": cols}


def requests_plan(hours: float, rng: random.Random) -> list[float]:
    """Трудоёмкости заявок, которые в сумме дают hours (до десятых)."""
    choices = [1.5, 2.0, 2.0, 3.0, 3.0, 4.0, 4.0, 5.0, 6.0, 8.0]
    out: list[float] = []
    left = round(hours, 1)
    while left > 0:
        value = min(rng.choice(choices), left)
        if left - value < 1.0 and left - value > 0:
            value = left
        out.append(round(value, 1))
        left = round(left - value, 1)
    return out


def school_in_norm(students: int, classes_per_rate: float) -> tuple[dict[str, float], int]:
    """Штатка школы, которой нет в расчёте управления: ровно по нормативу, лишних ставок
    нет. Уборщики — по числу классов шагом 0,25 ставки."""
    classes = max(round(students / 25), 1)
    cleaners = math.ceil(classes / classes_per_rate / 0.25) * 0.25
    return {
        "Директор": 1.0,
        "Заместитель директора": float(max(1, math.ceil(students / 350))),
        "Заведующий хозяйством": 1.0 if students >= 200 else 0.5,
        "Рабочий по комплексному обслуживанию и ремонту зданий": 2.0 if students >= 500
        else 1.0,
        "Уборщик служебных помещений": cleaners,
        "Дворник": 1.0,
    }, classes


ACTIVE = ("new", "assigned", "in_progress", "in_progress", "on_hold")


def life(created, now, rng: random.Random, days_to_do: float) -> dict:
    """Статус и даты заявки: свежие частью ещё в работе (некоторые уже просрочены),
    старые закрыты, малая часть — с опозданием."""
    from datetime import timedelta  # noqa: PLC0415

    due = created + timedelta(days=days_to_do)
    if (now - created).days < 12 and rng.random() < 0.3:
        status = rng.choice(ACTIVE)
        working = status in ("in_progress", "on_hold")
        # Просрочена примерно каждая восьмая открытая, у остальных срок ещё не вышел
        if due < now and rng.random() > 0.12:
            due = now + timedelta(hours=rng.uniform(4, 72))
        return {"status": status, "due_at": due, "started_at": created if working else None,
                "hold_since": now - timedelta(hours=rng.uniform(2, 30))
                if status == "on_hold" else None,
                "resolved_at": None, "closed_at": None, "resolution": None}
    if rng.random() < 0.07:
        done = due + timedelta(hours=rng.uniform(3, 72))
    else:
        done = created + (due - created) * rng.uniform(0.1, 0.9)
    return {"status": "closed", "due_at": due, "started_at": created, "hold_since": None,
            "resolved_at": done, "closed_at": done, "resolution": "Выполнено"}
