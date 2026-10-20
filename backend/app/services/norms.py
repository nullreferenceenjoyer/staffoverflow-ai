"""Нормативы: какие применяются к учреждению и сколько ставок дают.

Норматив — это «1 ставка на 300 обучающихся» или «1,25 ставки при числе обучающихся
от 801». Расчёт одного норматива:

    ставки = показатель / unit_size * fte_per_unit     (без unit_size — fte_per_unit)
    -> округление по rounding_step (вверх, вниз или математически)
    -> не меньше min_fte и не больше max_fte

Если к группе подходит несколько нормативов, берутся самые точные: местный норматив
учреждения важнее муниципального, муниципальный — регионального, норматив для типа
учреждения — общего «для всех», при равенстве — с большим priority. Отобранные
нормативы складываются.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal

METRICS: dict[str, str] = {
    "students_count": "Обучающиеся / воспитанники",
    "classes_count": "Классы",
    "groups_count": "Группы",
    "total_area_m2": "Площадь, м²",
    "none": "Без показателя",
}
# Как показатель звучит в фразе «не указано …» — для причины «нет данных»
METRIC_MISSING: dict[str, str] = {
    "students_count": "число обучающихся",
    "classes_count": "число классов",
    "groups_count": "число групп",
    "total_area_m2": "общая площадь помещений",
}
# В условии норматива: «1,25 ставки при числе обучающихся от 801»
METRIC_CONDITION: dict[str, str] = {
    "students_count": "числе обучающихся",
    "classes_count": "числе классов",
    "groups_count": "числе групп",
    "total_area_m2": "площади (м²)",
}
INSTITUTION_TYPES: dict[str, str] = {
    "all": "Все учреждения",
    "school": "Школы",
    "preschool": "Детские сады",
    "complex": "Образовательные комплексы",
}
SCOPE_LEVELS: dict[str, str] = {
    "region": "Регион",
    "municipality": "Муниципалитет",
    "organization": "Учреждение",
}
SCOPE_RANK = {"region": 0, "municipality": 1, "organization": 2}
ROUNDING_MODES: dict[str, str] = {"up": "вверх", "down": "вниз", "nearest": "математически"}
DOC_TYPES = ("закон", "постановление", "приказ", "распоряжение", "методические рекомендации",
             "локальный акт")
DOC_STATUSES: dict[str, str] = {
    "active": "Действует", "superseded": "Заменён", "archived": "В архиве",
}

ZERO = Decimal("0")
CENT = Decimal("0.01")


def dec(value) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def plural(n: Decimal | int | float, one: str, few: str, many: str) -> str:
    value = Decimal(str(n))
    if value != value.to_integral_value():
        return few  # 1,25 ставки, 2,5 класса
    n = abs(int(value))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def num(value: Decimal | int | float | None) -> str:
    """Число по-русски: 1,25; 12; 1 000."""
    if value is None:
        return "—"
    value = Decimal(str(value)).quantize(CENT).normalize()
    if value == value.to_integral_value():
        text = f"{int(value):,}".replace(",", " ")
    else:
        text = f"{value:f}".replace(".", ",")
    return text


def fte_text(value: Decimal | int | float) -> str:
    return f"{num(value)} {plural(value, 'ставка', 'ставки', 'ставок')}"


def _unit_text(metric: str, size: Decimal) -> str:
    """«на 12 классов», «на 300 обучающихся», «на 1 000 м²»."""
    words = {
        "students_count": ("обучающегося", "обучающихся", "обучающихся"),
        "classes_count": ("класс", "класса", "классов"),
        "groups_count": ("группу", "группы", "групп"),
    }
    if metric == "total_area_m2":
        return f"на {num(size)} м²"
    return f"на {num(size)} {plural(size, *words[metric])}"


def metric_value_text(metric: str, value) -> str:
    """«34 класса», «840 обучающихся», «12 000 м²»."""
    words = {
        "students_count": ("обучающийся", "обучающихся", "обучающихся"),
        "classes_count": ("класс", "класса", "классов"),
        "groups_count": ("группа", "группы", "групп"),
    }
    if metric == "total_area_m2":
        return f"{num(value)} м²"
    return f"{num(value)} {plural(value, *words[metric])}"


def describe(coef) -> str:
    """Норматив человеческими словами: «1 ставка на 12 классов, не меньше 1»."""
    base = fte_text(coef.fte_per_unit)
    if coef.unit_size and coef.metric != "none":
        base += " " + _unit_text(coef.metric, dec(coef.unit_size))
    condition = []
    if coef.metric != "none" and (coef.applies_from is not None or coef.applies_to is not None):
        title = METRIC_CONDITION.get(coef.metric, coef.metric)
        if coef.applies_from is not None and coef.applies_to is not None:
            condition.append(f"при {title} от {num(coef.applies_from)} до {num(coef.applies_to)}")
        elif coef.applies_from is not None:
            condition.append(f"при {title} от {num(coef.applies_from)}")
        else:
            condition.append(f"при {title} до {num(coef.applies_to)}")
    limits = []
    if coef.min_fte is not None:
        limits.append(f"не меньше {num(coef.min_fte)}")
    if coef.max_fte is not None:
        limits.append(f"не больше {num(coef.max_fte)}")
    return ", ".join([" ".join([base, *condition]), *limits])


def round_fte(value: Decimal, step: Decimal | None, mode: str) -> Decimal:
    if not step:
        return value.quantize(CENT, ROUND_HALF_UP)
    rounding = {"up": ROUND_CEILING, "down": ROUND_FLOOR}.get(mode, ROUND_HALF_UP)
    return ((value / step).quantize(Decimal(1), rounding) * step).quantize(CENT)


def active_on(coef, moment: date) -> bool:
    if coef.effective_from is not None and moment < coef.effective_from:
        return False
    if coef.effective_to is not None and moment > coef.effective_to:
        return False
    document = getattr(coef, "document", None)
    return document is None or document.status == "active"


def scope_matches(coef, org) -> bool:
    if coef.scope_level == "organization":
        return coef.scope_id == org.id
    if coef.scope_level == "municipality":
        return coef.scope_id == org.municipality_id
    return True


def condition_met(coef, metrics: dict) -> bool | None:
    """Подходит ли норматив по значению показателя. None — показатель не указан."""
    if coef.metric == "none" or (coef.applies_from is None and coef.applies_to is None):
        return True
    value = metrics.get(coef.metric)
    if value is None:
        return None
    value = dec(value)
    if coef.applies_from is not None and value < dec(coef.applies_from):
        return False
    return not (coef.applies_to is not None and value > dec(coef.applies_to))


def select(coefficients: list, org, group_id: int, moment: date, metrics: dict) -> list:
    """Нормативы, которые применяются к группе учреждения на дату (см. описание модуля)."""
    candidates = [
        c for c in coefficients
        if c.personnel_group_id == group_id
        and c.institution_type in ("all", org.org_type)
        and active_on(c, moment) and scope_matches(c, org)
        and condition_met(c, metrics) is not False
    ]
    if not candidates:
        return []

    def rank(c):
        return (SCOPE_RANK.get(c.scope_level, 0), c.institution_type != "all", c.priority or 0)

    best = max(rank(c) for c in candidates)
    return [c for c in candidates if rank(c) == best]


@dataclass
class Part:
    """Сколько ставок дал один норматив и как это получилось."""

    fte: Decimal | None
    missing: str | None  # чего не хватило для расчёта
    snapshot: dict


def compute(coef, metrics: dict) -> Part:
    snapshot = {
        "id": coef.id, "rule": describe(coef), "metric": coef.metric,
        "document_id": coef.document_id,
        "document": document_title(coef.document) if getattr(coef, "document", None) else None,
        "is_mandatory": coef.is_mandatory,
    }
    value = None
    if coef.metric != "none":
        value = metrics.get(coef.metric)
        needs_value = bool(coef.unit_size) or condition_met(coef, metrics) is None
        if value is None and needs_value:
            missing = f"не указано: {METRIC_MISSING.get(coef.metric, coef.metric)}"
            return Part(None, missing, {**snapshot, "missing": missing})
    if coef.unit_size and value is not None:
        raw = dec(value) / dec(coef.unit_size) * dec(coef.fte_per_unit)
    else:
        raw = dec(coef.fte_per_unit)
    result = round_fte(raw, dec(coef.rounding_step), coef.rounding_mode)
    if coef.min_fte is not None:
        result = max(result, dec(coef.min_fte))
    if coef.max_fte is not None:
        result = min(result, dec(coef.max_fte))
    result = result.quantize(CENT)

    steps = []
    if coef.unit_size and value is not None:
        steps.append(f"{metric_value_text(coef.metric, value)} → {num(raw.quantize(CENT))}")
        if coef.rounding_step:
            steps.append(f"округление до {num(coef.rounding_step)} "
                         f"{ROUNDING_MODES.get(coef.rounding_mode, '')}".strip())
    elif value is not None and coef.metric != "none":
        steps.append(metric_value_text(coef.metric, value))
    explain = f"{describe(coef)}"
    if steps:
        explain += f": {', '.join(steps)}"
    explain += f" = {fte_text(result)}"
    return Part(result, None, {**snapshot, "value": None if value is None else float(value),
                               "fte": float(result), "explain": explain})


def tolerance(coefs: list, required: Decimal, default_abs: float, default_pct: float) -> Decimal:
    """Отклонение в пределах допуска — это норма, а не «излишек 0,01 ставки»."""
    best = ZERO
    for coef in coefs or [None]:
        tol_abs = dec(coef.tolerance_abs) if coef and coef.tolerance_abs is not None \
            else dec(default_abs)
        tol_pct = dec(coef.tolerance_pct) if coef and coef.tolerance_pct is not None \
            else dec(default_pct)
        best = max(best, tol_abs, required * tol_pct / 100)
    return best


def document_title(document) -> str:
    """«приказ № 123 от 01.09.2026»."""
    parts = [document.doc_type]
    if document.number:
        parts.append(f"№ {document.number}")
    if document.issued_at:
        parts.append(f"от {document.issued_at:%d.%m.%Y}")
    text = " ".join(parts)
    return f"{text} «{document.title}»" if document.title else text
