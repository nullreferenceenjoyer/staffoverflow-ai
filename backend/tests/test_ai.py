"""Части ИИ-слоя, которые можно проверить без модели."""

import pytest

from app.services import llm, routing
from app.services.assistant import foreign_references
from app.services.forecast import linear_trend
from app.services.llm import ThinkFilter, _with_no_think
from app.services.rag import CHUNK_SIZE, hashing_embedding, split_into_chunks


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def feed_all(parts: list[str]) -> str:
    think_filter = ThinkFilter()
    return "".join(think_filter.feed(part) for part in parts)


def test_think_block_is_removed_from_stream():
    assert feed_all(["<thi", "nk>считаю", " варианты</th", "ink>\n\nОтвет: 5"]) == "Ответ: 5"


def test_plain_answer_passes_through():
    assert feed_all(["Да", ", избыток ", "есть"]) == "Да, избыток есть"


def test_answer_starting_with_angle_bracket():
    assert feed_all(["<b>", "важно</b>"]) == "<b>важно</b>"


def test_no_think_is_added_to_last_user_message_only():
    messages = [
        {"role": "user", "content": "первый"},
        {"role": "assistant", "content": "ответ"},
        {"role": "user", "content": "второй"},
    ]
    patched = _with_no_think(messages)
    assert [m["content"] for m in patched] == ["первый", "ответ", "второй /no_think"]
    assert messages[2]["content"] == "второй"  # исходный список не меняется


def test_sensitive_requests_never_go_to_cloud(monkeypatch):
    settings = llm.get_settings()
    monkeypatch.setattr(settings, "cloud_llm_enabled", True)
    monkeypatch.setattr(settings, "cloud_llm_base_url", "https://cloud.example/v1")
    monkeypatch.setattr(settings, "llm_base_url", "http://llm:8080/v1")

    assert llm.pick_endpoint(sensitive=True).is_local
    assert not llm.pick_endpoint(sensitive=False).is_local


def test_local_model_is_required_for_sensitive_requests(monkeypatch):
    settings = llm.get_settings()
    monkeypatch.setattr(settings, "cloud_llm_enabled", True)
    monkeypatch.setattr(settings, "cloud_llm_base_url", "https://cloud.example/v1")
    monkeypatch.setattr(settings, "llm_base_url", "")

    with pytest.raises(llm.LLMUnavailable):
        llm.pick_endpoint(sensitive=True)


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
    topic, role, classified_by = routing.classify("Нужна ставка психолога, не хватает людей")
    assert (topic, role, classified_by) == ("staff_increase", "municipal_specialist", "rules")


def test_chunks_respect_size_and_keep_text():
    text = "\n\n".join(f"Абзац {i}. " + "слово " * 60 for i in range(12))
    chunks = split_into_chunks(text)
    assert len(chunks) > 1
    assert all(len(chunk) <= CHUNK_SIZE + 200 for chunk in chunks)
    assert "Абзац 0." in chunks[0] and "Абзац 11." in chunks[-1]


def test_hashing_embedding_tolerates_word_forms():
    query = hashing_embedding("сколько логопедов на детей с ОВЗ")
    relevant = hashing_embedding("Учитель-логопед: одна штатная единица на 12 обучающихся с ОВЗ")
    unrelated = hashing_embedding("Уборка территории и вывоз снега в зимний период")
    assert cosine(query, relevant) > cosine(query, unrelated) + 0.1


def test_linear_trend():
    slope, intercept = linear_trend([(2023, 500), (2024, 520), (2025, 540)])
    assert round(slope) == 20
    assert round(slope * 2026 + intercept) == 560


def test_trend_with_single_point_is_flat():
    assert linear_trend([(2025, 300)]) == (0.0, 300)


CONTEXT = ("Из базы знаний. Учитель-логопед: одна штатная единица на 6–12 обучающихся с ОВЗ — "
           "Приказ Минпросвещения России от 22.03.2021 № 115. Учреждение: СОШ № 5.")


def test_answer_within_context_raises_no_warning():
    answer = ("По приказу Минпросвещения № 115 на 12 детей с ОВЗ положена одна ставка логопеда. "
              "В СОШ № 5 их 14, значит нужно 1,25 ставки.")
    assert foreign_references(answer, CONTEXT) == []


@pytest.mark.parametrize(
    ("answer", "fragment"),
    [
        ("Это следует из приказа Минобрнауки № 1601 о норме часов.", "№ 1601"),
        ("Согласно статье 333 Трудового кодекса, норма не превышает 36 часов.", "Трудового"),
        ("Требования к уборке установлены СанПиН 2.4.3648-20.", "СанПиН"),
        ("Подробнее см. https://minobr.example/norms и 273-ФЗ.", "https://"),
    ],
)
def test_references_outside_context_are_reported(answer, fragment):
    found = foreign_references(answer, CONTEXT)
    assert any(fragment in item for item in found)
