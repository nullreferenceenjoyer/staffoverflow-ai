"""Помощник по штатке: история разговоров, права и справка для модели."""

import pytest

from app.services import llm

ANALYST = "analyst@demo.ru"
DIRECTOR = "director@demo.ru"
OBSERVER = "observer@demo.ru"
EMPLOYEE = "employee@demo.ru"


@pytest.fixture
def model(monkeypatch):
    """Вместо модели — заглушка, которая запоминает, что ей прислали."""
    calls: list[list[dict]] = []

    def complete(messages, **_):
        calls.append(messages)
        return f"Ответ № {len(calls)}"

    monkeypatch.setattr(llm, "should_try", lambda: True)
    monkeypatch.setattr(llm, "complete", complete)
    return calls


def test_hidden_from_employee(client, login):
    headers = login(EMPLOYEE)
    assert client.get("/api/assistant/chats", headers=headers).status_code == 403
    assert client.post("/api/assistant/ask", json={"question": "Где дефицит?"},
                       headers=headers).status_code == 403


def test_director_chat_keeps_history(client, login, model):
    headers = login(DIRECTOR)
    first = client.post("/api/assistant/ask", json={"question": "Почему дефицит по АУП?"},
                        headers=headers)
    assert first.status_code == 200, first.text
    chat = first.json()
    # Разговор директора всегда про его учреждение
    assert chat["organization_id"] == client.get("/api/auth/me", headers=headers).json()[
        "organization_id"]
    assert [m["role"] for m in chat["messages"]] == ["user", "assistant"]
    system = model[0][0]["content"]
    assert "Делопроизводство" in system and "1 ставка на 300 обучающихся" in system
    # ФОТ и сокращение ставки уборщика из истории штатки
    assert "ФОТ по штатке" in system and "оклад 22 500 ₽/мес" in system
    assert "Уборка помещений: 11 → 10 ставок, ФОТ −270 000 ₽/год" in system

    second = client.post("/api/assistant/ask", json={"chat_id": chat["id"],
                                                     "question": "А что с бухгалтерией?"},
                         headers=headers).json()
    assert len(second["messages"]) == 4
    # Модель получила предыдущие реплики
    assert [m["content"] for m in model[1][1:]] == [
        "Почему дефицит по АУП?", "Ответ № 1", "А что с бухгалтерией?"]

    listed = client.get("/api/assistant/chats", headers=headers).json()
    assert listed[0]["id"] == chat["id"]
    # Чужой разговор не открыть
    assert client.get(f"/api/assistant/chats/{chat['id']}",
                      headers=login(ANALYST)).status_code == 404

    assert client.delete(f"/api/assistant/chats/{chat['id']}",
                         headers=headers).status_code == 204
    assert client.get(f"/api/assistant/chats/{chat['id']}", headers=headers).status_code == 404


def test_analyst_gets_region_summary(client, login, model):
    reply = client.post("/api/assistant/ask", json={"question": "Где не хватает данных?"},
                        headers=login(ANALYST))
    assert reply.status_code == 200
    assert reply.json()["organization_id"] is None
    system = model[0][0]["content"]
    assert "весь регион" in system and "Нет данных:" in system
    assert "Действующие нормативы:" in system
    assert "По муниципалитетам:" in system and "Последние изменения штаток:" in system


def test_observer_cannot_ask_about_institution(client, login, model):
    headers = login(OBSERVER)
    org_id = client.get("/api/staffing/analysis", headers=headers).json()["items"][0][
        "organization_id"]
    assert client.post("/api/assistant/ask", json={"question": "Что тут?",
                                                   "organization_id": org_id},
                       headers=headers).status_code == 403


def test_without_model_nothing_is_saved(client, login):
    headers = login(ANALYST)
    before = len(client.get("/api/assistant/chats", headers=headers).json())
    reply = client.post("/api/assistant/ask", json={"question": "Где дефицит?"},
                        headers=headers)
    assert reply.status_code == 503
    assert len(client.get("/api/assistant/chats", headers=headers).json()) == before
