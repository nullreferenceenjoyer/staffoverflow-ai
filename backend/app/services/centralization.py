"""Сценарий централизации АУП и вспомогательного персонала (раздел 5 ТЗ).

Идея расчёта: для функций, которые можно вынести в общий центр или бригаду,
потребность считается не по каждому учреждению отдельно, а по группе целиком.
Экономия получается из двух источников:
  1) пропадает округление вверх и минимальные ставки в каждом маленьком ОУ;
  2) срабатывает эффект масштаба, заданный в нормативе (centralization_effect).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from app.models import Category
from app.services.staffing import OrgReport, round_to_step

CENTER_NAMES = {
    "accounting": "Единый расчётный центр",
    "hr": "Центр кадрового обеспечения",
    "procurement": "Центр закупок",
    "it": "Служба ИТ-сопровождения",
    "clerk": "Центр документооборота",
    "cleaning": "Бригада клининга",
    "security": "Единая служба охраны",
    "maintenance": "Бригада технического обслуживания",
    "janitor": "Бригада благоустройства",
}


@dataclass
class CentralizedFunction:
    function_code: str
    title: str
    category: str
    center: str
    organizations: int  # сколько ОУ сейчас держат функцию у себя
    actual: float
    norm: float
    centralized: float
    pay_per_rate: float
    vacant: float
    members: list[dict]

    @property
    def released(self) -> float:
        """Сколько ставок высвобождается относительно факта."""
        return round(max(self.actual - self.centralized, 0), 2)


def build_scenario(reports: list[OrgReport]) -> dict:
    grouped: dict[str, list[tuple[OrgReport, object]]] = defaultdict(list)
    for report in reports:
        for line in report.lines:
            if line.centralization_effect > 0 and line.category in (
                Category.admin, Category.support
            ):
                grouped[line.function_code].append((report, line))

    functions: list[CentralizedFunction] = []
    for code, pairs in grouped.items():
        lines = [line for _, line in pairs]
        actual = sum(line.actual_rate for line in lines)
        pay = sum(line.actual_pay for line in lines)
        effect = max(line.centralization_effect for line in lines)
        raw = sum(line.norm_raw for line in lines)
        # Центр не может быть меньше одной ставки, иначе функцию некому выполнять
        centralized = max(round_to_step(raw * (1 - effect), 0.5), 1.0) if raw else 0.0
        functions.append(
            CentralizedFunction(
                function_code=code,
                title=lines[0].title,
                category=lines[0].category,
                center=CENTER_NAMES.get(code, "Сервисный центр"),
                organizations=sum(1 for line in lines if line.actual_rate > 0),
                actual=round(actual, 2),
                norm=round(sum(line.norm_rate or 0 for line in lines), 2),
                centralized=centralized,
                pay_per_rate=pay / actual if actual else 0.0,
                vacant=round(sum(line.vacant_rate for line in lines), 2),
                members=[
                    {"organization_id": report.org_id, "organization": report.name,
                     "actual": line.actual_rate, "norm": line.norm_rate}
                    for report, line in pairs
                ],
            )
        )
    functions.sort(key=lambda f: f.released, reverse=True)

    tax = reports[0].payroll_tax_rate if reports else 0.0
    saving = sum(f.released * f.pay_per_rate for f in functions) * 12 * (1 + tax)

    # Три точки для графика: как сейчас → по нормативам в каждом ОУ → общая служба.
    # Функции, которые не централизуются, на всех этапах берутся по нормативу.
    stages = []
    for category in (Category.admin, Category.support):
        actual = norm = centralized = 0.0
        for report in reports:
            for line in report.lines:
                if line.category != category:
                    continue
                line_norm = line.actual_rate if line.norm_rate is None else line.norm_rate
                actual += line.actual_rate
                norm += line_norm
                if line.function_code not in grouped:
                    centralized += line_norm
        centralized += sum(f.centralized for f in functions if f.category == category)
        stages.append({
            "category": category.value,
            "actual": round(actual, 2),
            "norm": round(norm, 2),
            "centralized": round(centralized, 2),
        })

    return {
        "organizations": len(reports),
        "functions": [
            {
                "function_code": f.function_code,
                "title": f.title,
                "category": f.category,
                "center": f.center,
                "organizations": f.organizations,
                "actual": f.actual,
                "norm": f.norm,
                "centralized": f.centralized,
                "released": f.released,
                "vacant": f.vacant,
                "saving_year": round(f.released * f.pay_per_rate * 12 * (1 + tax)),
                "members": f.members,
            }
            for f in functions
        ],
        "stages": stages,
        "released_total": round(sum(f.released for f in functions), 2),
        "saving_year": round(saving),
    }
