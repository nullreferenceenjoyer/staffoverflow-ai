"""Оценка трудоёмкости хозяйственной заявки и что из неё следует.

Оценка грубая и нужна для одного решения: справится ли сотрудник на точке за пару
часов, или работу отдавать выездной бригаде и давать на неё больше времени. Часы
считаются от типовой работы по теме и уточняются по тексту: сколько предметов,
насколько масштабно, есть ли тяжёлые работы.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from app.config import get_settings
from app.models import Complexity

# Типовая работа одного мастера по теме, часов. Темы не из списка — не хозяйственные,
# их делают не руками, и трудоёмкость для них не считается
BASE_HOURS = {
    "furniture": 1.5,
    "plumbing": 2.0,
    "electrical": 1.5,
    "repair": 2.0,
    "cleaning": 1.5,
    "it": 1.0,
    "supplies": 1.0,
}

# Работа явно легче типовой
LIGHT = re.compile(r"лампочк|перегорел|картридж|подтянуть|смазать|закончил|заел|разболтал")

# Тяжёлые работы: сколько часов добавляют к типовой
HEAVY: list[tuple[re.Pattern, float]] = [
    (re.compile(r"замен\w* (\w+ )?(труб|батаре|радиатор|стояк)"), 6),
    (re.compile(r"проводк"), 6),
    (re.compile(r"демонтаж"), 4),
    (re.compile(r"(?<!де)монтаж"), 3),
    (re.compile(r"штукатур"), 4),
    (re.compile(r"покрас\w* (\w+ )?стен"), 4),
    (re.compile(r"линолеум|плитк|напольн|паркет"), 6),
    (re.compile(r"кровл|крыш"), 8),
    (re.compile(r"фасад"), 8),
    (re.compile(r"сварк|сварив"), 4),
    (re.compile(r"прорвал|затопил|залил"), 4),
    (re.compile(r"капитальн"), 16),
    (re.compile(r"ремонт (\w+ )?(кабинет|класс|помещени|зал|коридор|санузл|туалет)"), 12),
    (re.compile(r"забор|ограждени"), 6),
]

# Работа по всему зданию или этажу, а не в одном месте
SCALE = re.compile(
    r"во всех|всех кабинет|все кабинет|весь этаж|всего этажа|всем этаже|по всему|всё здание"
    r"|все здание|всей территори|по всей|каждом кабинет|каждом класс"
)

# «6 шкафчиков», «12 парт», «40 м²»
QUANTITY = re.compile(
    r"(\d{1,4})\s*(м2|м²|кв\.? ?м|шт|штук|парт|стул|шкаф|окон|окн|светильник|ламп|кабинет"
    r"|класс|батаре|радиатор|розет|кран|раковин|унитаз|двер|компьютер|ноутбук|принтер)"
)


@dataclass(frozen=True)
class Estimate:
    hours: float | None
    complexity: Complexity
    by: str | None  # llm | rules | manual
    reasons: tuple[str, ...] = ()


def is_field(topic: str) -> bool:
    """Хозяйственная тема: работу делают руками на месте, сотрудник или бригада."""
    return topic in BASE_HOURS


def complexity_of(hours: float | None) -> Complexity:
    settings = get_settings()
    if hours is None or hours <= settings.effort_brigade_hours:
        return Complexity.simple
    if hours <= settings.effort_major_hours:
        return Complexity.complex
    return Complexity.major


def _round(hours: float) -> float:
    return min(max(round(hours * 2) / 2, 0.5), 500.0)


def by_rules(topic: str, text: str) -> tuple[float, tuple[str, ...]]:
    normalized = text.lower().replace("ё", "е")
    hours = BASE_HOURS[topic]
    reasons = [f"типовая работа по теме — {hours:g} ч"]
    if LIGHT.search(normalized):
        hours *= 0.5
        reasons.append("мелкая работа")
    for pattern, extra in HEAVY:
        match = pattern.search(normalized)
        if match:
            hours += extra
            reasons.append(f"«{match.group(0)}» +{extra:g} ч")
    for number, unit in QUANTITY.findall(normalized):
        count = int(number)
        if unit.startswith(("м", "кв")):
            # Покраска, плитка, уборка — порядка 10 м² в час
            hours += count / 10
            reasons.append(f"{count} м²")
        elif 1 < count <= 200:
            hours *= 1 + 0.35 * (min(count, 50) - 1)
            reasons.append(f"{count} шт.")
        break
    if SCALE.search(normalized):
        hours *= 3
        reasons.append("по всему этажу или зданию")
    return _round(hours), tuple(reasons)


def estimate(topic: str, text: str, model_hours: float | None = None) -> Estimate:
    """Оценка для новой заявки. Часы от модели берутся, если они правдоподобны."""
    if not is_field(topic):
        return Estimate(None, Complexity.simple, None)
    if model_hours is not None and 0.25 <= model_hours <= 500:
        hours = _round(model_hours)
        return Estimate(hours, complexity_of(hours), "llm", ("оценка модели",))
    hours, reasons = by_rules(topic, text)
    return Estimate(hours, complexity_of(hours), "rules", reasons)


def extra_days(hours: float | None) -> int:
    """На сколько дней продлить плановый срок: бригада работает около 6 часов в день."""
    if hours is None or complexity_of(hours) == Complexity.simple:
        return 0
    return max(math.ceil(hours / 6) - 1, 0)
