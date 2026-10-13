"""Паспорт проекта: табло цели и дорожная карта.

Цель паспорта — сократить ФОТ административно-управленческого и вспомогательного
персонала на заданный процент к сроку. Здесь считается, где проект находится
относительно цели: что было на старте (исходная точка), что сейчас, сколько ещё
можно снять по расчёту системы и как это соотносится с планом из паспорта.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.deps import Scope
from app.models import Category, Organization, Program
from app.services import analytics
from app.services.centralization import build_scenario
from app.services.staffing import OrgReport, ru

TRACKED = (Category.admin, Category.support)
DEFAULT_HOURS_PER_RATE = 1972  # часов в год на ставку при 40-часовой неделе


def program_reports(db: Session, program: Program) -> list[OrgReport]:
    org_ids = list(db.scalars(
        select(Organization.id).where(Organization.municipality_id == program.municipality_id)
    ))
    return analytics.load_reports(db, org_ids)


def snapshot(reports: list[OrgReport]) -> dict:
    """Ставки и месячные начисления АУП и ВП — то, что фиксируется как исходная точка."""
    result = {c.value: {"rate": 0.0, "pay": 0.0, "vacant": 0.0} for c in TRACKED}
    for report in reports:
        for line in report.lines:
            if line.category in result:
                bucket = result[line.category]
                bucket["rate"] += line.actual_rate
                bucket["pay"] += line.actual_pay
                bucket["vacant"] += line.vacant_rate
    return {c: {k: round(v, 2) for k, v in b.items()} for c, b in result.items()}


def fix_baseline(program: Program, reports: list[OrgReport]) -> None:
    program.baseline = snapshot(reports)
    program.baseline_at = datetime.now(UTC)


def scoreboard(program: Program, reports: list[OrgReport]) -> dict:
    tax = get_settings().payroll_tax_rate
    hours = float(program.plan.get("hours_per_rate") or DEFAULT_HOURS_PER_RATE)
    current = snapshot(reports)
    # Пока исходная точка не зафиксирована, сравнивать не с чем: считаем, что старт — сегодня
    baseline = program.baseline or current

    def fot_year(pay: float) -> float:
        return round(pay * 12 * (1 + tax))

    categories = []
    for category in TRACKED:
        key = category.value
        surplus = vacant_surplus = saving = 0.0
        for report in reports:
            for line in report.lines:
                if line.category != key or line.delta <= report.tolerance:
                    continue
                surplus += line.delta
                vacant_surplus += min(line.vacant_rate, line.delta)
                saving += line.delta * line.pay_per_rate
        plan = program.plan.get(key) or {}
        plan_rates = float(plan.get("rates") or 0)
        done = round(baseline[key]["rate"] - current[key]["rate"], 2)
        categories.append({
            "category": key,
            "baseline_rate": baseline[key]["rate"],
            "current_rate": current[key]["rate"],
            "baseline_fot_year": fot_year(baseline[key]["pay"]),
            "current_fot_year": fot_year(current[key]["pay"]),
            "done_rates": done,
            "plan_rates": plan_rates,
            "plan_dismissals": float(plan.get("dismissals") or 0),
            "plan_hours": round(plan_rates * hours),
            "done_hours": round(done * hours),
            # Что показывает расчёт по текущим данным: избыток сверх норматива
            "potential_rates": round(surplus, 2),
            "potential_vacant": round(vacant_surplus, 2),
            "potential_saving_year": fot_year(saving),
        })

    baseline_fot = sum(c["baseline_fot_year"] for c in categories)
    current_fot = sum(c["current_fot_year"] for c in categories)
    target_pct = float(program.target_fot_cut_pct)
    scenario = build_scenario(reports)
    today = date.today()
    return {
        "baseline_fixed": program.baseline is not None,
        "baseline_at": program.baseline_at,
        "baseline_fot_year": baseline_fot,
        "current_fot_year": current_fot,
        "target_pct": target_pct,
        "target_saving_year": round(baseline_fot * target_pct / 100),
        "done_saving_year": baseline_fot - current_fot,
        "done_pct": round((baseline_fot - current_fot) / baseline_fot * 100, 2)
        if baseline_fot else 0.0,
        "plan_saving_year": float(program.plan.get("saving_year") or 0),
        "potential_saving_year": sum(c["potential_saving_year"] for c in categories),
        "potential_pct": round(
            sum(c["potential_saving_year"] for c in categories) / current_fot * 100, 2
        ) if current_fot else 0.0,
        "centralization_saving_year": scenario["saving_year"],
        "centralization_released": scenario["released_total"],
        "hours_per_rate": hours,
        "days_left": (program.end_date - today).days,
        "organizations": len(reports),
        "categories": categories,
    }


def can_view(scope: Scope, program: Program) -> bool:
    if scope.can_see_municipality(program.municipality_id):
        return True
    # Директор видит паспорт своего муниципалитета, но только на чтение
    org = scope.db.scalar(scope.organizations())
    return org is not None and org.municipality_id == program.municipality_id


def find_visible(db: Session, scope: Scope) -> Program | None:
    for program in db.scalars(select(Program).order_by(Program.id)):
        if can_view(scope, program):
            return program
    return None


def assistant_block(db: Session, scope: Scope):
    """Сводка по паспорту для помощника."""
    from app.services.retrieval import Block, money, table

    program = find_visible(db, scope)
    if program is None:
        return None
    board = scoreboard(program, program_reports(db, program))
    rows = [
        [("АУП" if c["category"] == "admin" else "ВП"), c["baseline_rate"], c["current_rate"],
         c["plan_rates"], c["done_rates"], c["potential_rates"], c["potential_vacant"]]
        for c in board["categories"]
    ]
    milestones = "; ".join(
        f"{m.ordinal}. {m.title[:60]} — до {m.end_date:%d.%m.%Y}, {m.status}"
        for m in program.milestones
    )
    head = (
        f"Цель: сократить ФОТ АУП и ВП на {ru(board['target_pct'])} % к "
        f"{program.end_date:%d.%m.%Y} (осталось дней: {board['days_left']}). ФОТ на старте "
        f"{money(board['baseline_fot_year'])}, сейчас {money(board['current_fot_year'])}, "
        f"достигнуто {ru(board['done_pct'])} %. План экономии по паспорту "
        f"{money(board['plan_saving_year'])}, расчётный потенциал по нормативам "
        f"{money(board['potential_saving_year'])} ({ru(board['potential_pct'])} %), "
        f"по сценарию централизации {money(board['centralization_saving_year'])}."
    )
    body = table(["Категория", "Ставок на старте", "Сейчас", "План сокращения", "Сокращено",
                  "Избыток по расчёту", "из него вакансии"], rows)
    return Block(f"Паспорт проекта: {program.municipality.name}",
                 f"{head}\n\n{body}\n\nДорожная карта: {milestones}",
                 source="База данных системы: паспорт проекта")
