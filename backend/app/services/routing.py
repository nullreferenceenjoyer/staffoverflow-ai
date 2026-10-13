"""Классификация заявок: тема, кому направить и сколько времени на исполнение."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from app.models import Role
from app.services import llm

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Topic:
    title: str
    role: Role  # кому заявка уходит по умолчанию
    keywords: tuple[str, ...]  # для разбора без модели
    days: int = 5  # срок плановой заявки, календарных дней
    # Функция штатного расписания, которая выполняет такие заявки. По ней заявки
    # попадают в анализ загрузки хозяйственной службы.
    function_code: str | None = None


TOPICS: dict[str, Topic] = {
    "furniture": Topic("Мебель и инвентарь", Role.executor,
                       ("мебел", "парт", "стул", "шкаф", "стол", "полк", "дверц", "доск",
                        "скамь", "кроват", "тумб"), 7, "maintenance"),
    "plumbing": Topic("Сантехника и отопление", Role.executor,
                      ("кран", "течет", "течь", "протечк", "унитаз", "раковин", "батаре",
                       "отоплен", "канализац", "засор", "труб", "смесител"), 3, "maintenance"),
    "electrical": Topic("Электрика и освещение", Role.executor,
                        ("ламп", "свет", "розетк", "выключател", "электри", "проводк",
                         "щиток", "искрит"), 3, "maintenance"),
    "repair": Topic("Ремонт помещений", Role.executor,
                    ("покрас", "штукатур", "линолеум", "окн", "стекл", "замок", "двер",
                     "потол", "ремонт", "плитк"), 14, "maintenance"),
    "cleaning": Topic("Уборка и территория", Role.executor,
                      ("уборк", "убрать", "мусор", "грязь", "снег", "налед", "территор",
                       "вывоз"), 2, "cleaning"),
    "it": Topic("Компьютеры и связь", Role.executor,
                ("компьютер", "ноутбук", "принтер", "проектор", "интернет", "wi-fi", "вайфай",
                 "картридж", "монитор", "не печатает", "электронн журнал"), 3, "it"),
    "supplies": Topic("Снабжение и расходные материалы", Role.executor,
                      ("закупить", "приобрести", "канцеляр", "бумаг", "моющ", "расходн",
                       "закончил"), 10, "facility_manager"),
    "safety": Topic("Безопасность и доступ", Role.director,
                    ("пропуск", "турникет", "видеонаблюд", "камер", "тревожн", "огнетушител",
                     "пожарн", "ключ", "эваку"), 3, "security"),
    "staff_increase": Topic("Дополнительные ставки", Role.municipal_specialist,
                            ("нужна ставк", "дополнительн", "не хватает", "нехватк",
                             "ввести ставк", "выделить ставк", "увеличить штат"), 14),
    "staff_reduction": Topic("Сокращение и реорганизация", Role.regional_analyst,
                             ("сокращ", "оптимизац", "реорганизац", "объедин", "централизац"),
                             14),
    "norms": Topic("Вопрос по нормативам", Role.regional_analyst,
                   ("норматив", "норма ", "формул", "как рассчит", "на основании чего",
                    "приказ"), 7),
    "data_fix": Topic("Исправление данных", Role.municipal_specialist,
                      ("ошибк в данных", "неверн", "исправ", "неправильно указ",
                       "не совпадает", "уточнить контингент"), 5),
    "technical": Topic("Работа системы", Role.admin,
                       ("не могу войти", "пароль", "доступ", "не открывается",
                        "не загружается", "ошибка системы"), 2),
    "other": Topic("Прочее", Role.municipal_specialist, (), 7),
}

_PROMPT = """Определи тему заявки от сотрудника образовательного учреждения. Темы:
{topics}

Ответь одним JSON-объектом вида {{"topic": "<код темы>"}} без пояснений.

Заявка: {text}"""


def classify_by_rules(text: str) -> str:
    normalized = text.lower().replace("ё", "е")
    scores = {
        code: sum(keyword in normalized for keyword in topic.keywords)
        for code, topic in TOPICS.items()
    }
    best = max(scores, key=scores.get)
    return best if scores[best] else "other"


def classify(text: str) -> tuple[str, Role, str]:
    """Возвращает (тема, роль адресата, чем классифицировано: llm | rules)."""
    topics = "\n".join(f"- {code}: {topic.title}" for code, topic in TOPICS.items())
    try:
        # Текст заявки свободный и может содержать ФИО — только локальная модель
        reply = llm.complete(
            [{"role": "user", "content": _PROMPT.format(topics=topics, text=text[:1500])}],
            sensitive=True, max_tokens=40,
        )
        match = re.search(r"\{.*?\}", reply, re.S)
        topic = json.loads(match.group(0)).get("topic") if match else None
        if topic in TOPICS:
            return topic, TOPICS[topic].role, "llm"
        log.info("LLM returned unknown topic %r, using rules", reply[:80])
    except (llm.LLMUnavailable, ValueError):
        pass
    topic = classify_by_rules(text)
    return topic, TOPICS[topic].role, "rules"
