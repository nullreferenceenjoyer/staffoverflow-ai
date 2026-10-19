"""Тема заявки и обращение к модели — то, что проверяется без сервера модели."""

import pytest

from app.services import llm, routing
from app.services.llm import _with_no_think, strip_thinking


def test_think_block_is_removed():
    assert strip_thinking("<think>считаю варианты</think>\n\nОтвет: 5") == "Ответ: 5"


def test_plain_answer_passes_through():
    assert strip_thinking('  {"topic": "it"} ') == '{"topic": "it"}'


def test_no_think_is_added_to_last_user_message_only():
    messages = [
        {"role": "user", "content": "первый"},
        {"role": "assistant", "content": "ответ"},
        {"role": "user", "content": "второй"},
    ]
    patched = _with_no_think(messages)
    assert [m["content"] for m in patched] == ["первый", "ответ", "второй /no_think"]
    assert messages[2]["content"] == "второй"  # исходный список не меняется


def test_model_is_required(monkeypatch):
    monkeypatch.setattr(llm.get_settings(), "llm_base_url", "")
    with pytest.raises(llm.LLMUnavailable):
        llm.complete([{"role": "user", "content": "тест"}])


@pytest.mark.parametrize(
    ("text", "topic"),
    [
        ("Просим выделить ставку логопеда, не хватает специалистов", "staff_increase"),
        ("Планируем реорганизацию и сокращение двух ставок", "staff_reduction"),
        ("На основании чего рассчитан норматив по уборщикам?", "norms"),
        ("Не могу войти в систему, пароль не подходит", "technical"),
        ("Поздравляем с праздником", "other"),
        ("Починить мебель: в кабинете 12 сломалась парта", "furniture"),
        ("Течёт кран в туалете на втором этаже", "plumbing"),
        ("Не горят лампы в коридоре, искрит розетка", "electrical"),
        ("Не печатает принтер в учительской", "it"),
        ("Убрать снег у запасного выхода", "cleaning"),
    ],
)
def test_request_topic_by_rules(text, topic):
    assert routing.classify_by_rules(text) == topic


def test_classify_falls_back_to_rules_without_llm(monkeypatch):
    monkeypatch.setattr(llm.get_settings(), "llm_base_url", "")
    found = routing.classify("Нужна ставка психолога, не хватает людей")
    assert (found.topic, found.role, found.by) == (
        "staff_increase", "municipal_specialist", "rules")
    assert found.hours is None
