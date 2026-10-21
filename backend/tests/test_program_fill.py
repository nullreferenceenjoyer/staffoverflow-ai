"""Заполнение школ по расчёту управления: итоги по школам и должностям сходятся,
а анализ штатки даёт вакансии, нагрузку и сокращение людей ровно как в расчёте."""

from decimal import Decimal as D
from types import SimpleNamespace as NS

from app.services import app_settings, program_fill, recommend

DATA = {
    "program": {"total": 10.0, "vacancies": 4.0, "taxes_pct": 30.2,
                "payroll_base_year": 0},
    "schools": [
        {"code": "A", "total": 6.0, "vacancies": 3.0, "load": 2.0, "own": 1.0, "layoff": 0},
        {"code": "B", "total": 4.0, "vacancies": 1.0, "load": 1.5, "own": 0, "layoff": 1.5},
    ],
    "positions": [
        ["Иные", "Уборщик служебных помещений", 30, 5, 25, None, None, 5, 186000],
        ["Иные", "Дворник", 20, 3.5, 16.5, 3.5, 120000, None, None],
        ["Иные", "Грузчик", 6, 1.5, 4.5, 1.5, 54000, None, None],
    ],
    "fill": {
        "schools": {"A": [900, 56.3, 37.5], "B": [600, 56.2, 37.4]},
        "every_school": {"Уборщик служебных помещений": 4},
        "left": [["A", "Уборщик служебных помещений", 1, "own"],
                 ["B", "Грузчик", 1.5, "layoff"]],
    },
}


def test_allocation_keeps_school_and_position_totals():
    plan = program_fill.build(DATA)
    cells = plan["cells"]
    for school in DATA["schools"]:
        mine = [c for (code, _), c in cells.items() if code == school["code"]]
        assert round(sum(c["vacancy"] + c["load"] + c["people"] for c in mine), 2) \
            == school["total"]
        assert round(sum(c["vacancy"] for c in mine), 2) == school["vacancies"]
        assert round(sum(c["own"] for c in mine), 2) == school["own"]
    for _cat, name, before, cut, after, *_ in DATA["positions"]:
        mine = [c for (_, n), c in cells.items() if n == name]
        assert round(sum(c["approved"] for c in mine), 2) == before
        assert round(sum(c["after"] for c in mine), 2) == after
        assert round(sum(c["vacancy"] + c["load"] + c["people"] for c in mine), 2) == cut
    # Оклад восстанавливается из экономии: 186 000 ₽ в месяц на 5 ставок с налогами
    assert plan["salary"]["Уборщик служебных помещений"] == round(186000 / 5 / 1.302, 2)


def test_analysis_of_filled_schedule_gives_three_kinds():
    plan = program_fill.build(DATA)
    group = NS(id=1, name="Уборщик служебных помещений", code="dmt_01",
               top_category="support", subcategory="cleaning")
    cell = plan["cells"][("A", "Уборщик служебных помещений")]
    line = {"line_id": 1, "position": group.name, "approved": cell["approved"],
            "occupied": cell["occupied"], "combined": cell["combined"],
            "vacant": round(cell["approved"] - cell["occupied"], 2), "salary": 28000,
            "payroll": None}
    row = NS(required_fte=D(str(cell["after"])), status="surplus", missing_reasons=[],
             coefficients_snapshot=[])
    result = recommend.for_group(group, [line], row, row, None, None, None, 90,
                                 dict(app_settings.WORKLOAD_DEFAULTS))
    assert result["bucket"] == "cleaning"
    assert result["cut_vacant"] == cell["vacancy"]
    assert result["reduce_load"] == cell["load"]
    assert result["cut"] == cell["people"]
    kinds = {p["kind"] for p in result["positions_cut"]}
    assert kinds >= {"people"}


def test_requests_add_up_to_hours():
    import random

    values = program_fill.requests_plan(123.4, random.Random(1))
    assert round(sum(values), 1) == 123.4
    assert all(v >= 1.0 for v in values)
