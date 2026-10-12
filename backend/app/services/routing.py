"""Классификация обращений от учреждений и выбор, кому их направить."""

from __future__ import annotations

import json
import logging
import re

from app.models import Role
from app.services import llm

log = logging.getLogger(__name__)

# тема -> (название, кому направить, ключевые слова для разбора без модели)
TOPICS: dict[str, tuple[str, Role, tuple[str, ...]]] = {
    "staff_increase": ("Дополнительные ставки", Role.municipal_specialist,
                       ("нужна ставк", "дополнительн", "не хватает", "нехватк", "ввести ставк",
                        "выделить ставк", "увеличить штат")),
    "staff_reduction": ("Сокращение и реорганизация", Role.regional_analyst,
                        ("сокращ", "оптимизац", "реорганизац", "объедин", "централизац")),
    "norms": ("Вопрос по нормативам", Role.regional_analyst,
              ("норматив", "норма ", "формул", "как рассчит", "на основании чего", "приказ")),
    "data_fix": ("Исправление данных", Role.municipal_specialist,
                 ("ошибк в данных", "неверн", "исправ", "неправильно указ", "не совпадает",
                  "уточнить контингент")),
    "technical": ("Работа системы", Role.admin,
                  ("не могу войти", "пароль", "доступ", "не открывается", "не загружается",
                   "ошибка системы")),
    "other": ("Прочее", Role.municipal_specialist, ()),
}

_PROMPT = """Определи тему обращения от образовательного учреждения. Темы:
{topics}

Ответь одним JSON-объектом вида {{"topic": "<код темы>"}} без пояснений.

Обращение: {text}"""


def classify_by_rules(text: str) -> str:
    normalized = text.lower().replace("ё", "е")
    scores = {
        code: sum(keyword in normalized for keyword in keywords)
        for code, (_, _, keywords) in TOPICS.items()
    }
    best = max(scores, key=scores.get)
    return best if scores[best] else "other"


def classify(text: str) -> tuple[str, Role, str]:
    """Возвращает (тема, роль адресата, чем классифицировано: llm | rules)."""
    topics = "\n".join(f"- {code}: {title}" for code, (title, _, _) in TOPICS.items())
    try:
        # Текст обращения свободный и может содержать ФИО — только локальная модель
        reply = llm.complete(
            [{"role": "user", "content": _PROMPT.format(topics=topics, text=text[:1500])}],
            sensitive=True, max_tokens=40,
        )
        match = re.search(r"\{.*?\}", reply, re.S)
        topic = json.loads(match.group(0)).get("topic") if match else None
        if topic in TOPICS:
            return topic, TOPICS[topic][1], "llm"
        log.info("LLM returned unknown topic %r, using rules", reply[:80])
    except (llm.LLMUnavailable, ValueError):
        pass
    topic = classify_by_rules(text)
    return topic, TOPICS[topic][1], "rules"
