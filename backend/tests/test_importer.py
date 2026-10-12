import pytest

from app.services.functions import classify_title
from app.services.importer import (
    STAFF_COLUMNS,
    ImportFormatError,
    ImportResult,
    _map_columns,
    _number,
    pseudonymize,
    read_table,
)


def test_reads_excel_style_csv():
    content = "Организация;Должность;Количество ставок\nСОШ № 1;Учитель;1,5\n".encode("cp1251")
    rows = read_table("staff.csv", content)
    assert rows == [{"организация": "СОШ № 1", "должность": "Учитель", "количество ставок": "1,5"}]


def test_reads_utf8_csv_with_commas_and_bom():
    content = "﻿organization,title,rate\nSchool,Teacher,1\n".encode()
    assert read_table("staff.csv", content)[0]["organization"] == "School"


def test_empty_file_is_rejected():
    with pytest.raises(ImportFormatError):
        read_table("staff.csv", "Организация;Должность\n".encode())


def test_personal_columns_are_dropped():
    result = ImportResult()
    header = ["организация", "должность", "ставка", "фио", "паспорт", "снилс"]
    mapping = _map_columns(header, STAFF_COLUMNS, ("organization", "title", "rate"), result)
    assert mapping["employee"] == "фио"
    assert result.dropped_columns == ["паспорт", "снилс"]


def test_missing_required_column():
    with pytest.raises(ImportFormatError, match="должность"):
        _map_columns(["организация", "ставка"], STAFF_COLUMNS,
                     ("organization", "title", "rate"), ImportResult())


def test_pseudonym_is_stable_and_hides_the_name():
    first = pseudonymize("Иванов  Иван Иванович")
    assert first == pseudonymize("иванов иван иванович")
    assert first != pseudonymize("Иванов Иван Петрович")
    assert "иванов" not in first.lower()
    assert len(first) == 32


@pytest.mark.parametrize(
    ("raw", "expected"), [("1,5", "1.5"), ("62 000", "62000"), ("0.25", "0.25")]
)
def test_number_parsing(raw, expected):
    assert str(_number(raw)) == expected


def test_bad_number():
    with pytest.raises(ValueError):
        _number("полторы")


@pytest.mark.parametrize(
    ("title", "code"),
    [
        ("Учитель начальных классов", "teacher"),
        ("Учитель-логопед", "speech_therapist"),
        ("Зам. директора по УВР", "deputy_director"),
        ("Заместитель директора по АХЧ", "deputy_director"),
        ("Директор", "director"),
        ("Заведующий", "director"),
        ("Заведующий хозяйством", "facility_manager"),
        ("Главный бухгалтер", "accounting"),
        ("Специалист по кадрам", "hr"),
        ("Уборщик служебных помещений", "cleaning"),
        ("Помощник воспитателя", "assistant_educator"),
        ("Воспитатель ГПД", "educator"),
        ("Педагог-библиотекарь", "librarian"),
        ("Рабочий по комплексному обслуживанию и ремонту зданий", "maintenance"),
        ("Оператор котельной", "other"),
    ],
)
def test_classify_title(title, code):
    assert classify_title(title).code == code
