"""Заявка по результату нормативного анализа: тема, кому направить и текст.

  дефицит АУП                 -> «Дополнительные ставки», специалист управления
  дефицит вспомогательного    -> «Дополнительные ставки», директор (если заявку
                                 пишет сам директор — специалист управления)
  излишек небольшой           -> «Сокращение и реорганизация», специалист управления
  излишек крупный             -> «Сокращение и реорганизация», региональный аналитик
  нет данных                  -> «Исправление данных»: директору, а если пишет
                                 директор — специалисту управления
  требует проверки / вопрос   -> «Вопрос по нормативам», региональный аналитик

Система не пишет «уволить» или «лишний сотрудник» — только «проверить излишек ставки».
"""

from __future__ import annotations

from decimal import Decimal

from app.models import AnalysisStatus, Role

A = AnalysisStatus


def plan(status: str, category: str, severity: str | None, author_role: str) -> tuple[str, Role]:
    if status == A.deficit:
        role = Role.municipal_specialist if category == "aup" else Role.director
        if role == Role.director and author_role == Role.director:
            role = Role.municipal_specialist
        return "staff_increase", role
    if status == A.surplus:
        return "staff_reduction", (Role.regional_analyst if severity == "high"
                                   else Role.municipal_specialist)
    if status == A.no_data:
        return "data_fix", (Role.municipal_specialist if author_role == Role.director
                            else Role.director)
    return "norms", Role.regional_analyst


def link_type(status: str) -> str:
    return {A.deficit: "deficit", A.surplus: "surplus", A.no_data: "no_data"}.get(
        status, "question")


def fte(value: Decimal | float | None) -> str:
    if value is None:
        return "—"
    return f"{abs(Decimal(str(value))):.2f}".replace(".", ",") + " ставки"


def signed(value: Decimal | float | None) -> str:
    if value is None:
        return "—"
    value = Decimal(str(value))
    sign = "+" if value > 0 else "−" if value < 0 else ""
    return f"{sign}{abs(value):.2f}".replace(".", ",")


def compose(*, org_name: str, year: str, category_title: str, basis: str, status: str,
            group_name: str | None, required, approved, occupied, deviation,
            reasons: list[str], groups: list[tuple[str, float | None]],
            documents: list[str], cost: str | None = None) -> tuple[str, str]:
    """Заголовок и текст заявки по шаблону."""
    subject = f"по группе «{group_name}»" if group_name else f"по категории «{category_title}»"
    fact_label = "Занято" if basis == "occupied" else "Утверждено по штатке"
    fact = occupied if basis == "occupied" else approved
    basis_line = "" if not documents else f"Основание: {'; '.join(documents)}."
    numbers = [f"Норматив: {fte(required)}.", f"{fact_label}: {fte(fact)}."]
    if cost:
        numbers.append(f"Оценка ФОТ отклонения: {cost} в год (оклад × ставки × 12).")
    by_groups = ""
    if not group_name and groups:
        by_groups = "По группам: " + "; ".join(f"{name} {signed(dev)}" for name, dev in groups) \
            + "."

    if status == A.deficit:
        title = f"Дефицит {fte(deviation)} {subject}: {org_name}"
        lines = [f"По результатам нормативного анализа выявлен дефицит {fte(deviation)} "
                 f"{subject} в учреждении «{org_name}» на {year} учебный год.", *numbers,
                 by_groups, basis_line,
                 "Прошу рассмотреть вопрос о дополнительной ставке или уточнении "
                 "штатного расписания."]
    elif status == A.surplus:
        title = f"Сверх норматива {fte(deviation)} {subject}: {org_name}"
        lines = [f"По результатам нормативного анализа выявлен излишек {fte(deviation)} "
                 f"{subject} в учреждении «{org_name}» на {year} учебный год.", *numbers,
                 by_groups, basis_line,
                 "Прошу проверить корректность штатного расписания и фактической занятости."]
    elif status == A.no_data:
        title = f"Нет данных для нормативного анализа: {org_name}"
        missing = "; ".join(reasons) or "данные неполные"
        lines = [f"Для нормативного анализа ({category_title}) в учреждении «{org_name}» "
                 f"отсутствуют данные: {missing}.", f"Период: {year}.",
                 "Прошу внести корректные данные для расчёта нормативной численности."]
    else:
        title = f"Вопрос по нормативу {subject}: {org_name}"
        detail = "; ".join(reasons)
        lines = [f"Прошу пояснить применение норматива {subject} в учреждении «{org_name}» "
                 f"на {year} учебный год." + (f" Результат анализа: {detail}." if detail else ""),
                 *numbers, by_groups, basis_line]
    return title[:200], "\n".join(line for line in lines if line)
