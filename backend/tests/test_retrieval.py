"""Разбор вопроса помощнику: что в нём распознаётся без модели."""

from types import SimpleNamespace

import pytest

from app.services.assistant import normalize
from app.services.retrieval import (
    INTENTS,
    Block,
    Plan,
    detect_category,
    detect_municipality,
    detect_organizations,
    table,
)

REPORTS = [
    SimpleNamespace(name="СОШ № 5 (Заречный м.о.)", org_type="school",
                    municipality="Заречный м.о."),
    SimpleNamespace(name="Детский сад № 5 «Радуга» (г.о. Дубна)", org_type="preschool",
                    municipality="г.о. Дубна"),
    SimpleNamespace(name="Образовательный комплекс № 51 (Заречный м.о.)", org_type="complex",
                    municipality="Заречный м.о."),
]


def intents(question: str) -> set[str]:
    import re

    return {name for name, pattern in INTENTS.items() if re.search(pattern, normalize(question))}


@pytest.mark.parametrize(
    ("question", "category"),
    [
        ("Где самый большой избыток АУП?", "admin"),
        ("сколько лишних бухгалтеров", "admin"),
        ("Что с уборщиками и охраной?", "support"),
        ("нехватка учителей", "teaching"),
        ("Какие учреждения хуже всего?", None),
    ],
)
def test_category(question, category):
    assert detect_category(normalize(question)) == category


@pytest.mark.parametrize(
    ("question", "municipality"),
    [
        ("отклонения в Заречном округе", "Заречный м.о."),
        ("что по Дубне", "г.о. Дубна"),
        ("покажи избыток по области", None),
    ],
)
def test_municipality_is_matched_by_word_stem(question, municipality):
    assert detect_municipality(normalize(question), REPORTS) == municipality


def test_organization_by_number_and_kind():
    found = detect_organizations(normalize("Что по школе № 5?"), REPORTS)
    assert [r.name for r in found] == ["СОШ № 5 (Заречный м.о.)"]

    found = detect_organizations(normalize("детский сад 5, какие отклонения"), REPORTS)
    assert [r.org_type for r in found] == ["preschool"]


def test_plain_numbers_are_not_organizations():
    # Год и проценты не должны приниматься за номер учреждения
    assert detect_organizations(normalize("сократить на 10 % до конца 2026 года"), REPORTS) == []
    # …но номер после них всё равно находится
    found = detect_organizations(normalize("в 2026 году по комплексу № 51"), REPORTS)
    assert [r.org_type for r in found] == ["complex"]


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Сколько ставок высвободит централизация бухгалтерии?", "centralization"),
        ("Можно ли объединить уборщиков в бригаду?", "centralization"),
        ("На основании чего считается норматив по логопедам?", "knowledge"),
        ("Какие задачи просрочены?", "work"),
        ("Сколько вакансий можно сократить без увольнений?", "vacancies"),
        ("Как идём к цели паспорта проекта?", "program"),
        ("Где не хватает педагогов?", "shortage"),
    ],
)
def test_intents(question, expected):
    assert expected in intents(question)


def test_table_formats_numbers_in_russian():
    text = table(["Учреждение", "Факт"], [["СОШ № 1", 12.5], ["Сад | 2", None]])
    assert text.splitlines()[2] == "| СОШ № 1 | 12,5 |"
    assert text.splitlines()[3] == "| Сад / 2 | — |"


def test_context_respects_budget():
    plan = Plan(summary="Итоги", blocks=[Block(f"Блок {i}", "строка\n" * 400) for i in range(5)])
    context = plan.context()
    assert context.startswith("Итоги")
    assert len(context) < 5600
    assert "Блок 0" in context and "Блок 4" not in context
