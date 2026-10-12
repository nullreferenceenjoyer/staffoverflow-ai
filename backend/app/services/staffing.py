"""Расчёт нормативной численности и сравнение с фактом.

Модуль не знает про БД: на входе показатели учреждения, фактические ставки
по функциям и набор нормативов, на выходе — отчёт по учреждению.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

from app.models import Category, Level, StudyForm
from app.services.functions import BY_CODE, function_title

# Показатели учреждения, от которых могут зависеть нормативы
DRIVERS: dict[str, str] = {
    "students_total": "обучающихся",
    "students_school": "обучающихся 1–11 кл.",
    "students_preschool": "воспитанников",
    "students_distance": "обучающихся дистанционно",
    "students_home": "обучающихся на дому",
    "special_needs": "детей с ОВЗ",
    "classes_total": "классов",
    "classes_primary": "классов 1–4",
    "classes_basic": "классов 5–9",
    "classes_secondary": "классов 10–11",
    "groups_preschool": "дошкольных групп",
    "area_sqm": "м² площади",
    "buildings": "зданий",
    "floors": "этажей",
    "organization": "учреждение",
}


@dataclass(frozen=True)
class NormRule:
    code: str
    title: str
    function_code: str
    driver: str
    kind: str = "staff"
    org_types: tuple[str, ...] = ()
    unit_size: float = 1.0
    per_unit: float = 0.0
    base: float = 0.0
    threshold: float = 0.0
    min_value: float | None = None
    max_value: float | None = None
    rounding: float = 0.25
    centralization_effect: float = 0.0
    legal_ref: str | None = None

    @classmethod
    def from_model(cls, norm) -> NormRule:
        return cls(
            code=norm.code,
            title=norm.title,
            function_code=norm.function_code,
            driver=norm.driver,
            kind=norm.kind,
            org_types=tuple(norm.org_types or ()),
            unit_size=float(norm.unit_size),
            per_unit=float(norm.per_unit),
            base=float(norm.base),
            threshold=float(norm.threshold),
            min_value=None if norm.min_value is None else float(norm.min_value),
            max_value=None if norm.max_value is None else float(norm.max_value),
            rounding=float(norm.rounding),
            centralization_effect=float(norm.centralization_effect),
            legal_ref=norm.legal_ref,
        )


@dataclass
class NormValue:
    rule: NormRule
    raw: float  # до округления — нужен при объединении функции по нескольким ОУ
    value: float
    explanation: str


@dataclass
class ReportLine:
    function_code: str
    title: str
    category: str
    actual_rate: float = 0.0
    actual_pay: float = 0.0  # начисления в месяц
    vacant_rate: float = 0.0
    norm_rate: float | None = None  # None — норматив для функции не задан
    norm_raw: float = 0.0
    centralization_effect: float = 0.0
    explanations: list[str] = field(default_factory=list)

    @property
    def delta(self) -> float:
        """Факт минус норматив: плюс — избыток, минус — нехватка."""
        if self.norm_rate is None:
            return 0.0
        return round(self.actual_rate - self.norm_rate, 2)

    @property
    def pay_per_rate(self) -> float:
        return self.actual_pay / self.actual_rate if self.actual_rate else 0.0


@dataclass
class OrgReport:
    org_id: int
    name: str
    org_type: str
    municipality_id: int
    municipality: str
    metrics: dict[str, float]
    lines: list[ReportLine]
    allowances: list[NormValue]
    payroll_tax_rate: float = 0.302
    tolerance: float = 0.25

    @property
    def actual_total(self) -> float:
        return round(sum(line.actual_rate for line in self.lines), 2)

    @property
    def norm_total(self) -> float:
        # Функции без норматива берём по факту, иначе итог нельзя сравнивать с фактическим
        total = sum(
            line.actual_rate if line.norm_rate is None else line.norm_rate for line in self.lines
        )
        return round(total, 2)

    @property
    def surplus(self) -> float:
        return round(sum(line.delta for line in self.lines if line.delta > 0), 2)

    @property
    def shortage(self) -> float:
        return round(-sum(line.delta for line in self.lines if line.delta < 0), 2)

    @property
    def compliance(self) -> float:
        """Насколько факт совпадает с нормативом, 0–100 %."""
        norm = sum(line.norm_rate for line in self.lines if line.norm_rate is not None)
        if not norm:
            return 100.0
        deviation = sum(abs(line.delta) for line in self.lines)
        return round(max(0.0, 100.0 - deviation / norm * 100.0), 1)

    @property
    def fot_actual_year(self) -> float:
        monthly = sum(line.actual_pay for line in self.lines)
        return round(monthly * 12 * (1 + self.payroll_tax_rate))

    @property
    def saving_potential_year(self) -> float:
        monthly = sum(
            line.delta * line.pay_per_rate for line in self.lines if line.delta > self.tolerance
        )
        return round(monthly * 12 * (1 + self.payroll_tax_rate))

    def by_category(self) -> dict[str, dict[str, float]]:
        result: dict[str, dict[str, float]] = {
            c.value: {"actual": 0.0, "norm": 0.0, "surplus": 0.0, "shortage": 0.0}
            for c in Category
        }
        for line in self.lines:
            bucket = result[line.category]
            bucket["actual"] += line.actual_rate
            bucket["norm"] += line.actual_rate if line.norm_rate is None else line.norm_rate
            bucket["surplus"] += max(line.delta, 0)
            bucket["shortage"] += max(-line.delta, 0)
        return {c: {k: round(v, 2) for k, v in b.items()} for c, b in result.items()}


def ru(value: float) -> str:
    """Число для текста на русском: без хвостовых нулей и с десятичной запятой."""
    return f"{value:g}".replace(".", ",")


def round_to_step(value: float, step: float) -> float:
    if step <= 0:
        return round(value, 2)
    # Половина шага округляется вверх: 0.125 при шаге 0.25 даёт 0.25
    return round(math.floor(value / step + 0.5) * step, 2)


def collect_metrics(enrollments, buildings) -> dict[str, float]:
    """Сводит контингент последнего учебного года и здания в показатели для формул."""
    metrics = dict.fromkeys(DRIVERS, 0.0)
    metrics["organization"] = 1.0

    years = [e.academic_year for e in enrollments]
    if years:
        current = max(years)
        for row in enrollments:
            if row.academic_year != current:
                continue
            metrics["students_total"] += row.students_count
            metrics["special_needs"] += row.special_needs_count
            if row.level == Level.preschool:
                metrics["students_preschool"] += row.students_count
                metrics["groups_preschool"] += row.classes_count
            else:
                metrics["students_school"] += row.students_count
                metrics["classes_total"] += row.classes_count
                metrics[f"classes_{row.level}"] += row.classes_count
            if row.study_form == StudyForm.distance:
                metrics["students_distance"] += row.students_count
            elif row.study_form == StudyForm.home:
                metrics["students_home"] += row.students_count

    for building in buildings:
        metrics["area_sqm"] += float(building.area_sqm)
        metrics["buildings"] += 1
        metrics["floors"] += building.floors
    return metrics


def evaluate_rule(rule: NormRule, org_type: str, metrics: dict[str, float]) -> NormValue | None:
    """Считает один норматив; None — если он к учреждению не применяется."""
    if rule.org_types and org_type not in rule.org_types:
        return None
    driver_value = metrics.get(rule.driver, 0.0)
    if driver_value <= 0 or driver_value < rule.threshold:
        return None

    raw = rule.base + rule.per_unit * driver_value / rule.unit_size
    if rule.min_value is not None:
        raw = max(raw, rule.min_value)
    if rule.max_value is not None:
        raw = min(raw, rule.max_value)
    value = round_to_step(raw, rule.rounding)

    parts = []
    if rule.base:
        parts.append(ru(rule.base))
    if rule.per_unit:
        driver = DRIVERS.get(rule.driver, rule.driver)
        formula = f"{ru(rule.per_unit)} × {ru(driver_value)} {driver}"
        if rule.unit_size != 1:
            formula += f" / {ru(rule.unit_size)}"
        parts.append(formula)
    explanation = f"{rule.title}: {' + '.join(parts) or '0'} = {ru(value)}"
    return NormValue(rule=rule, raw=raw, value=value, explanation=explanation)


def build_report(
    *,
    org_id: int,
    name: str,
    org_type: str,
    municipality_id: int,
    municipality: str,
    metrics: dict[str, float],
    actual: list[dict],
    rules: list[NormRule],
    payroll_tax_rate: float = 0.302,
    tolerance: float = 0.25,
) -> OrgReport:
    """actual — строки вида {function_code, category, rate, pay, vacant_rate}."""
    lines: dict[str, ReportLine] = {}

    def line_for(code: str, category: str | None = None) -> ReportLine:
        if code not in lines:
            known = BY_CODE.get(code)
            lines[code] = ReportLine(
                function_code=code,
                title=function_title(code),
                category=category or (known.category.value if known else Category.support.value),
            )
        return lines[code]

    for row in actual:
        line = line_for(row["function_code"], row.get("category"))
        line.actual_rate += float(row["rate"])
        line.actual_pay += float(row.get("pay") or 0)
        line.vacant_rate += float(row.get("vacant_rate") or 0)

    allowances: list[NormValue] = []
    rules_by_function: dict[str, list[NormRule]] = defaultdict(list)
    for rule in rules:
        rules_by_function[rule.function_code].append(rule)

    for code, function_rules in rules_by_function.items():
        staff_values = []
        for rule in function_rules:
            result = evaluate_rule(rule, org_type, metrics)
            if result is None:
                continue
            if rule.kind == "allowance":
                allowances.append(result)
            else:
                staff_values.append(result)
        applicable = [
            r for r in function_rules
            if r.kind == "staff" and (not r.org_types or org_type in r.org_types)
        ]
        if not applicable or (not staff_values and code not in lines):
            continue
        # Норматив для этого типа ОУ есть, но дал ноль (например, не пройден порог
        # по контингенту) — тогда фактические ставки считаются избытком
        line = line_for(code)
        line.norm_rate = round(sum(v.value for v in staff_values), 2)
        line.norm_raw = sum(v.raw for v in staff_values)
        line.explanations = [v.explanation for v in staff_values]
        line.centralization_effect = max(
            (v.rule.centralization_effect for v in staff_values), default=0.0
        )

    for line in lines.values():
        line.actual_rate = round(line.actual_rate, 2)

    order = {c.value: i for i, c in enumerate(Category)}
    sorted_lines = sorted(
        lines.values(), key=lambda item: (order.get(item.category, 9), item.title)
    )
    return OrgReport(
        org_id=org_id,
        name=name,
        org_type=org_type,
        municipality_id=municipality_id,
        municipality=municipality,
        metrics=metrics,
        lines=sorted_lines,
        allowances=allowances,
        payroll_tax_rate=payroll_tax_rate,
        tolerance=tolerance,
    )
