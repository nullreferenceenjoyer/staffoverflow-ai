"""Прогноз контингента и потребности в педагогах по линейному тренду.

Данных по каждому ОУ мало (обычно 3–5 лет), поэтому сложные модели здесь
бессмысленны: обычная регрессия по годам даёт понятный и проверяемый результат.
"""

from __future__ import annotations

from collections import defaultdict

from app.models import Level
from app.services.staffing import NormRule, collect_metrics, evaluate_rule

HORIZON_YEARS = 3


def linear_trend(points: list[tuple[int, float]]) -> tuple[float, float]:
    """МНК по точкам (год, значение). Возвращает (наклон, свободный член)."""
    n = len(points)
    if n == 0:
        return 0.0, 0.0
    if n == 1:
        return 0.0, points[0][1]
    mean_x = sum(x for x, _ in points) / n
    mean_y = sum(y for _, y in points) / n
    variance = sum((x - mean_x) ** 2 for x, _ in points)
    if variance == 0:
        return 0.0, mean_y
    slope = sum((x - mean_x) * (y - mean_y) for x, y in points) / variance
    return slope, mean_y - slope * mean_x


class _ProjectedRow:
    """Строка контингента будущего года в том же виде, что и Enrollment."""

    def __init__(self, year, level, students, classes, special):
        self.academic_year = year
        self.level = level
        self.study_form = "full_time"
        self.students_count = students
        self.classes_count = classes
        self.special_needs_count = special


def forecast_organization(org_type: str, enrollments, buildings, rules: list[NormRule]) -> dict:
    by_level: dict[str, dict[int, dict[str, float]]] = defaultdict(
        lambda: defaultdict(lambda: {"students": 0.0, "classes": 0.0, "special": 0.0})
    )
    for row in enrollments:
        bucket = by_level[row.level][row.academic_year]
        bucket["students"] += row.students_count
        bucket["classes"] += row.classes_count
        bucket["special"] += row.special_needs_count

    years = sorted({row.academic_year for row in enrollments})
    if not years:
        return {"history": [], "forecast": []}
    last_year = years[-1]

    teaching_rules = [r for r in rules if r.kind == "staff"]

    def teaching_need(rows) -> float:
        metrics = collect_metrics(rows, buildings)
        total = 0.0
        for rule in teaching_rules:
            if rule.function_code not in ("teacher", "educator"):
                continue
            value = evaluate_rule(rule, org_type, metrics)
            total += value.value if value else 0.0
        return round(total, 2)

    history = []
    for year in years:
        rows = [r for r in enrollments if r.academic_year == year]
        history.append({
            "year": year,
            "students": sum(r.students_count for r in rows),
            "teaching_norm": teaching_need(rows),
        })

    forecast = []
    for step in range(1, HORIZON_YEARS + 1):
        year = last_year + step
        rows = []
        for level in Level:
            series = by_level.get(level.value)
            if not series:
                continue
            slope, intercept = linear_trend([(y, v["students"]) for y, v in series.items()])
            students = max(round(slope * year + intercept), 0)
            latest = series[max(series)]
            # Наполняемость класса и долю детей с ОВЗ считаем такими же, как сейчас
            per_class = latest["students"] / latest["classes"] if latest["classes"] else 25
            special_share = latest["special"] / latest["students"] if latest["students"] else 0
            classes = -(-students // per_class) if students else 0
            rows.append(_ProjectedRow(year, level.value, students, int(classes),
                                      round(students * special_share)))
        forecast.append({
            "year": year,
            "students": sum(r.students_count for r in rows),
            "teaching_norm": teaching_need(rows),
        })
    return {"history": history, "forecast": forecast}
