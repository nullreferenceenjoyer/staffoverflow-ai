"""Правила «что делать со ставками» без базы: каждое правило подсказки — отдельный случай."""

from decimal import Decimal as D
from types import SimpleNamespace as NS

from app.services import app_settings, recommend

CLEANING = NS(id=5, name="Уборка помещений", code="support_cleaning", top_category="support")
MAINTENANCE = NS(id=6, name="Техническое обслуживание", code="support_maintenance",
                 top_category="support")
SETTINGS = dict(app_settings.WORKLOAD_DEFAULTS)


def line(position, approved, occupied, salary=22500, line_id=None):
    return {"line_id": line_id or hash(position) % 1000, "position": position,
            "approved": approved, "occupied": occupied,
            "vacant": None if occupied is None else max(approved - occupied, 0),
            "salary": salary, "payroll": None}


def row(required, status):
    return NS(required_fte=D(str(required)), status=status, missing_reasons=[],
              coefficients_snapshot=[{"explain": "1 ставка на 1 000 м²"}])


def unit(people, needed, requests=3, hours=10.0):
    return {"people": people, "needed": needed, "load_pct": 5.0, "requests": requests,
            "total_hours": hours, "capacity_hours": 700.0}


def decide(group, lines, status, required, load=None):
    return recommend.for_group(group, lines, row(required, status), row(required, status),
                               load, None, D(22500), 90, SETTINGS)


def test_occupied_over_norm_cuts_people_and_extra_vacancies():
    # Нужно 12, по штатке 14, занято 13: 1 занятая лишняя и 1 вакансия лишняя
    result = decide(CLEANING, [line("Уборщик служебных помещений", 13, 12),
                               line("Гардеробщик", 1, 1)], "surplus", 12)
    assert (result["cut"], result["cut_vacant"], result["verdict"]) == (1, 1, "cut")
    people = [p for p in result["positions_cut"] if p["kind"] == "people"]
    assert people == [{"line_id": people[0]["line_id"], "position": "Уборщик служебных помещений",
                       "fte": 1.0, "salary": 22500, "cost": 270000.0, "kind": "people"}]
    assert {"cut", "cut_vacant"} <= set(result["rules"])


def test_deficit_keeps_vacancies_needed_for_norm():
    result = decide(CLEANING, [line("Уборщик служебных помещений", 5, 4)], "deficit", 5)
    assert (result["cut"], result["cut_vacant"], result["hire"]) == (0, 0, 1)
    assert result["verdict"] == "hire"


def test_underloaded_maintenance_is_cut_despite_norm_deficit():
    # По площади нужно 4, занято 2 — дефицит, но заявок на одного: второй лишний
    result = decide(MAINTENANCE, [line("Рабочий", 2, 2)], "deficit", 4, unit(2, 1.0))
    assert (result["cut"], result["hire"], result["verdict"]) == (1, 0, "cut")
    assert "cut_by_load" in result["rules"]
    assert any("не хватает" in w and "по загрузке" in w for w in result["why"])


def test_load_is_ignored_when_staff_is_not_registered():
    # Ставок 3, а в системе один сотрудник — его загрузка не говорит обо всём хозотделе
    result = decide(MAINTENANCE, [line("Рабочий", 3, 3)], "deficit", 4, unit(1, 1.0))
    assert (result["cut"], result["hire"]) == (0, 1)
    assert result["load"]["complete"] is False


def test_busy_maintenance_is_not_cut_below_load():
    # По норме лишний один, но работы на троих — не сокращаем
    result = decide(MAINTENANCE, [line("Рабочий", 3, 3)], "surplus", 2, unit(3, 3.0))
    assert result["cut"] == 0
    assert "keep_by_load" in result["rules"]


def test_no_data_asks_to_fill_in():
    missing = NS(required_fte=None, status="no_data", missing_reasons=["не указано: число кабинетов"],
                 coefficients_snapshot=[])
    result = recommend.for_group(CLEANING, [line("Уборщик", 3, 3)], missing, missing, None,
                                 None, None, 90, SETTINGS)
    assert result["verdict"] == "data"
    assert result["reasons"] == ["не указано: число кабинетов"]
