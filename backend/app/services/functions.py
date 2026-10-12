"""Справочник трудовых функций.

Должности в выгрузках называются как угодно («зам. дир. по УВР», «уборщ. служ. пом.»),
поэтому расчёты ведутся не по названию, а по коду функции. Код подбирается
по ключевым словам при импорте и при необходимости правится вручную.
"""

from dataclasses import dataclass

from app.models import Category


@dataclass(frozen=True)
class StaffFunction:
    code: str
    title: str
    category: Category
    keywords: tuple[str, ...]


# Порядок важен: более специфичные функции стоят раньше общих
# («заместитель директора» и «заведующий хозяйством» должны сработать раньше, чем «директор»).
FUNCTIONS: tuple[StaffFunction, ...] = (
    StaffFunction("deputy_director", "Заместитель директора", Category.admin,
                  ("заместитель", "зам.", "зам ")),
    StaffFunction("facility_manager", "Заведующий хозяйством", Category.admin,
                  ("завхоз", "заведующий хозяйством", "хозяйственн")),
    StaffFunction("librarian", "Педагог-библиотекарь", Category.teaching,
                  ("библиотек",)),
    StaffFunction("director", "Директор (заведующий)", Category.admin,
                  ("директор", "заведующ")),
    StaffFunction("accounting", "Бухгалтерия и экономика", Category.admin,
                  ("бухгалтер", "экономист")),
    StaffFunction("hr", "Кадровое делопроизводство", Category.admin,
                  ("кадр", "персонал")),
    StaffFunction("procurement", "Закупки", Category.admin,
                  ("закуп", "контрактн")),
    StaffFunction("it", "ИТ-сопровождение", Category.admin,
                  ("системный администратор", "программист", "инженер-электроник")),
    StaffFunction("clerk", "Делопроизводство", Category.admin,
                  ("секретар", "делопроизвод", "документовед")),
    StaffFunction("speech_therapist", "Учитель-логопед", Category.teaching,
                  ("логопед",)),
    StaffFunction("defectologist", "Учитель-дефектолог", Category.teaching,
                  ("дефектолог",)),
    StaffFunction("psychologist", "Педагог-психолог", Category.teaching,
                  ("психолог",)),
    StaffFunction("social_pedagogue", "Социальный педагог", Category.teaching,
                  ("социальный педагог",)),
    StaffFunction("tutor", "Тьютор", Category.teaching,
                  ("тьютор", "ассистент")),
    StaffFunction("assistant_educator", "Помощник воспитателя", Category.support,
                  ("помощник воспитателя", "младший воспитатель")),
    StaffFunction("educator", "Воспитатель", Category.teaching,
                  ("воспитатель",)),
    StaffFunction("additional_education", "Педагог дополнительного образования",
                  Category.teaching, ("дополнительного образования", "педагог-организатор")),
    StaffFunction("teacher", "Учитель", Category.teaching,
                  ("учитель", "преподаватель")),
    StaffFunction("nurse", "Медицинский работник", Category.medical,
                  ("медицинск", "медсестра", "врач", "фельдшер")),
    StaffFunction("cleaning", "Уборка помещений", Category.support,
                  ("уборщ",)),
    StaffFunction("security", "Охрана и вахта", Category.support,
                  ("сторож", "вахт", "охран")),
    StaffFunction("maintenance", "Обслуживание зданий", Category.support,
                  ("рабочий по комплексному", "обслуживанию здани", "электрик", "сантехник",
                   "слесарь", "плотник")),
    StaffFunction("janitor", "Уборка территории", Category.support,
                  ("дворник",)),
    StaffFunction("cloakroom", "Гардероб", Category.support,
                  ("гардероб",)),
    StaffFunction("kitchen", "Пищеблок", Category.support,
                  ("повар", "кухонн", "буфет")),
    StaffFunction("lab_assistant", "Лаборант", Category.support,
                  ("лаборант",)),
    StaffFunction("other", "Прочие должности", Category.support, ()),
)

BY_CODE: dict[str, StaffFunction] = {f.code: f for f in FUNCTIONS}

CATEGORY_TITLES: dict[str, str] = {
    Category.teaching: "Педагогический персонал",
    Category.admin: "АУП",
    Category.support: "Вспомогательный персонал",
    Category.medical: "Медицинский персонал",
}


def classify_title(title: str) -> StaffFunction:
    """Определяет функцию по названию должности; если ничего не подошло — «прочие»."""
    normalized = title.lower().replace("ё", "е")
    for function in FUNCTIONS:
        if any(keyword in normalized for keyword in function.keywords):
            return function
    return BY_CODE["other"]


def function_title(code: str) -> str:
    function = BY_CODE.get(code)
    return function.title if function else code
