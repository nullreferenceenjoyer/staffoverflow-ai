"""Оценка трудоёмкости: от неё зависит, кому достанется заявка и какой будет срок."""

import pytest

from app.services import effort, geo
from app.services.spreadsheet import Column, TableError, read_table


@pytest.mark.parametrize(
    ("topic", "text", "complexity"),
    [
        ("furniture", "Отремонтировать дверцу шкафа", "simple"),
        ("electrical", "Перегорела лампочка в коридоре", "simple"),
        ("repair", "Не закрывается замок в кабинете 15", "simple"),
        ("plumbing", "Заменить трубы отопления в спортзале", "complex"),
        ("electrical", "Заменить проводку в кабинете информатики", "complex"),
        ("repair", "Покрасить стены во всех кабинетах второго этажа", "major"),
    ],
)
def test_complexity_by_text(topic, text, complexity):
    assert effort.estimate(topic, text).complexity == complexity


def test_quantity_makes_work_longer():
    one = effort.estimate("furniture", "Собрать шкафчик в раздевалке").hours
    six = effort.estimate("furniture", "Собрать 6 шкафчиков в раздевалке").hours
    assert six > one * 2


def test_area_is_counted_in_square_meters():
    small = effort.estimate("repair", "Положить линолеум, 10 м2").hours
    large = effort.estimate("repair", "Положить линолеум, 80 м2").hours
    assert large - small == pytest.approx(7, abs=0.5)


def test_non_field_topics_have_no_estimate():
    estimate = effort.estimate("norms", "На основании чего считается норматив?")
    assert estimate.hours is None and estimate.complexity == "simple"


def test_model_hours_are_used_when_plausible():
    assert effort.estimate("furniture", "Шкаф", model_hours=12).by == "llm"
    assert effort.estimate("furniture", "Шкаф", model_hours=9000).by == "rules"


def test_long_work_gets_extra_days():
    assert effort.extra_days(2) == 0
    assert effort.extra_days(12) == 1
    assert effort.extra_days(30) == 4


def test_distance_between_points():
    # От Красной площади до Воробьёвых гор около 6,3 км по прямой
    assert geo.distance_km(55.7539, 37.6208, 55.7105, 37.5530) == pytest.approx(6.4, abs=0.3)


COLUMNS = [Column("name", "Название", ("наименование",), required=True),
           Column("code", "Код")]


def test_csv_headers_are_matched_loosely():
    content = "НАИМЕНОВАНИЕ ;код\nСОШ № 5;OU-5\n;\nДетский сад № 2;\n".encode("cp1251")
    rows = read_table(content, "orgs.csv", COLUMNS)
    assert rows == [(2, {"name": "СОШ № 5", "code": "OU-5"}),
                    (4, {"name": "Детский сад № 2", "code": ""})]


def test_missing_required_column():
    with pytest.raises(TableError, match="Название"):
        read_table("Код\nOU-1\n".encode(), "orgs.csv", COLUMNS)
