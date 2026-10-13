"""Формирование проектов штатных расписаний из результатов анализа."""

from __future__ import annotations

from decimal import Decimal

from app.models import Category, Project, ProjectItem, User
from app.services.centralization import build_scenario
from app.services.staffing import OrgReport, ru


def _effect(delta_rate: float, pay_per_rate: float, tax: float) -> Decimal:
    """Годовое изменение ФОТ: минус — экономия, плюс — дополнительные расходы."""
    return Decimal(round(delta_rate * pay_per_rate * 12 * (1 + tax)))


def _finalize(project: Project) -> Project:
    project.rate_delta = sum((i.proposed_rate - i.current_rate for i in project.items), Decimal(0))
    project.fot_effect_year = sum((i.fot_effect_year for i in project.items), Decimal(0))
    return project


def normalization_project(report: OrgReport, author: User, fallback_pay: dict[str, float]):
    """Проект приведения штатного расписания одного ОУ к нормативу.

    fallback_pay — средняя стоимость ставки по категории: нужна, чтобы оценить
    затраты на должности, которых в учреждении сейчас нет совсем.
    """
    items = []
    for line in report.lines:
        if line.norm_rate is None or abs(line.delta) <= report.tolerance:
            continue
        pay = line.pay_per_rate or fallback_pay.get(line.category, 0.0)
        formula = "; ".join(line.explanations) or "норматив для учреждения этого типа равен нулю"
        if line.delta > 0:
            reason = f"Факт {ru(line.actual_rate)} ст. превышает норматив {ru(line.norm_rate)} ст. "
            if line.vacant_rate:
                reason += (f"Из них {ru(min(line.vacant_rate, line.delta))} ст. вакантны — "
                           "их можно исключить без высвобождения работников. ")
        else:
            reason = f"Факт {ru(line.actual_rate)} ст. ниже норматива {ru(line.norm_rate)} ст. "
        items.append(ProjectItem(
            organization_id=report.org_id,
            organization_name=report.name,
            function_code=line.function_code,
            title=line.title,
            category=line.category,
            current_rate=Decimal(str(line.actual_rate)),
            proposed_rate=Decimal(str(line.norm_rate)),
            fot_effect_year=_effect(-line.delta, pay, report.payroll_tax_rate),
            vacant_rate=Decimal(str(max(min(line.vacant_rate, line.delta), 0))),
            reason=reason + f"Расчёт: {formula}.",
        ))
    if not items:
        return None
    return _finalize(Project(
        title=f"Приведение штатного расписания к нормативу: {report.name}",
        kind="normalization",
        municipality_id=report.municipality_id,
        organization_id=report.org_id,
        created_by_id=author.id,
        items=items,
        summary=(f"Факт {ru(report.actual_total)} ст., норматив {ru(report.norm_total)} ст. "
                 f"Избыток {ru(report.surplus)} ст., нехватка {ru(report.shortage)} ст."),
    ))


def centralization_project(reports: list[OrgReport], author: User):
    """Проект передачи функций АУП и ВП в общие центры для группы учреждений."""
    if not reports:
        return None
    scenario = build_scenario(reports)
    tax = reports[0].payroll_tax_rate
    items = []
    for function in scenario["functions"]:
        if function["released"] <= 0:
            continue
        pay = function["saving_year"] / function["released"] / 12 / (1 + tax)
        kind = "АУП" if function["category"] == Category.admin else "вспомогательного персонала"
        items.append(ProjectItem(
            organization_id=None,
            organization_name=f"{function['center']} ({function['organizations']} ОУ)",
            function_code=function["function_code"],
            title=function["title"],
            category=function["category"],
            current_rate=Decimal(str(function["actual"])),
            proposed_rate=Decimal(str(function["centralized"])),
            fot_effect_year=_effect(-function["released"], pay, tax),
            vacant_rate=Decimal(str(min(function["vacant"], function["released"]))),
            reason=(f"Функция {kind} сейчас ведётся отдельно в {function['organizations']} "
                    f"учреждениях: {ru(function['actual'])} ст. при нормативе "
                    f"{ru(function['norm'])} ст. При объединении в «{function['center']}» "
                    f"достаточно {ru(function['centralized'])} ст."),
        ))
    if not items:
        return None
    municipality = reports[0].municipality
    return _finalize(Project(
        title=f"Централизация функций АУП и ВП: {municipality}",
        kind="centralization",
        municipality_id=reports[0].municipality_id,
        created_by_id=author.id,
        items=items,
        summary=(f"Учреждений в периметре: {len(reports)}. Высвобождается "
                 f"{ru(scenario['released_total'])} ст."),
    ))


def workload_project(report: dict, municipality_id: int, municipality: str, author: User):
    """Проект по итогам анализа загрузки: сокращение ставок на площадках, где персонал
    недозагружен. report — результат workload.analyze по одному муниципалитету."""
    organizations = {
        site["id"]: site["buildings"][0]["organization_id"]
        for site in report["sites"] if site["organizations"] == 1
    }
    items = [
        ProjectItem(
            organization_id=organizations.get(finding["site_id"]),
            organization_name=finding["site"][:300],
            function_code=finding["function_code"],
            title=finding["title"],
            category=finding["category"],
            current_rate=Decimal(str(finding["actual"])),
            proposed_rate=Decimal(str(finding["required"])),
            fot_effect_year=Decimal(-finding["saving_year"]),
            vacant_rate=Decimal(str(round(min(finding["vacant"], finding["excess"]), 2))),
            reason=finding["recommendation"],
        )
        for finding in report["findings"] if finding["verdict"] in ("duplicate", "idle")
    ]
    if not items:
        return None
    totals = report["totals"]
    return _finalize(Project(
        title=f"Выравнивание загрузки АУП и ВП по площадкам: {municipality}",
        kind="workload",
        municipality_id=municipality_id,
        created_by_id=author.id,
        items=items,
        summary=(f"Площадок: {totals['sites']}, из них с недозагрузкой — "
                 f"{totals['flagged_sites']}. Занято {ru(totals['actual'])} ст. при объёме "
                 f"работы {ru(totals['volume'])} ст.; сокращается {ru(totals['excess'])} ст., "
                 f"из них {ru(totals['vacant_in_excess'])} ст. — вакансии."),
    ))
