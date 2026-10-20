"""Обновления в реальном времени и присмотр за моделью — то, что проверяется без базы."""

import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.services import helpdesk, live, llm

ORG, OTHER_ORG, MUN = 1, 2, 10


def info(**changes) -> dict:
    base = {"id": 7, "org": ORG, "mun": MUN, "people": [100, 101], "brigades": [],
            "roles": ["executor"]}
    return {**base, **changes}


def viewer(role: str, user_id: int = 1, org: int | None = ORG, mun: int | None = MUN,
           brigade: int | None = None) -> live.Viewer:
    return live.Viewer(user_id, role, org, mun, brigade)


@pytest.mark.parametrize(("who", "event", "expected"), [
    (viewer("observer", org=None, mun=None), info(org=OTHER_ORG, mun=99), True),
    (viewer("municipal_specialist", org=None), info(org=OTHER_ORG), True),
    (viewer("municipal_specialist", org=None, mun=99), info(), False),
    (viewer("director"), info(), True),
    (viewer("director", org=OTHER_ORG), info(), False),
    # Хозслужба видит хозяйственные заявки своего учреждения…
    (viewer("executor"), info(), True),
    # …но не то, что ушло в управление образования, если она к заявке не причастна
    (viewer("executor"), info(roles=["municipal_specialist"]), False),
    # Прежний исполнитель узнаёт, что заявку у него забрали
    (viewer("executor", user_id=101), info(roles=["municipal_specialist"]), True),
    (viewer("employee", user_id=100), info(), True),
    (viewer("employee", user_id=5), info(), False),
    (viewer("brigade", user_id=5, brigade=3), info(brigades=[3]), True),
    (viewer("brigade", user_id=5, brigade=3), info(brigades=[4]), False),
])
def test_change_reaches_only_those_who_see_the_request(who, event, expected):
    assert helpdesk.concerns(who, event) is expected


def test_hub_sends_request_ids_and_notifications_to_the_right_people():
    async def scenario():
        hub = live.Hub(helpdesk.concerns)
        author = hub.subscribe(viewer("employee", user_id=100))
        stranger = hub.subscribe(viewer("employee", user_id=5))
        change = {"id": 7, "org": 1, "mun": 10, "people": [100], "brigades": [], "roles": []}
        hub.dispatch(json.dumps({"users": [100], "requests": [change]}))
        assert author.queue.get_nowait() == {"type": "requests", "ids": [7]}
        assert author.queue.get_nowait() == {"type": "notifications"}
        assert stranger.queue.empty()

        hub.dispatch('{"all": true}')
        assert stranger.queue.get_nowait() == {"type": "requests", "all": True}
        assert stranger.queue.get_nowait() == {"type": "notifications"}

        # Кто не успевает читать, получает просьбу перечитать всё вместо сотни событий
        for _ in range(101):
            stranger.send({"type": "llm"})
        assert stranger.queue.qsize() == 1
        assert stranger.queue.get_nowait() == {"type": "requests", "all": True}

        while not author.queue.empty():
            author.queue.get_nowait()
        hub.unsubscribe(author)
        hub.dispatch('{"all": true}')
        assert author.queue.empty()

    asyncio.run(scenario())


@pytest.fixture
def model(monkeypatch):
    """Настроенная модель с чистым состоянием."""
    settings = llm.get_settings()
    monkeypatch.setattr(settings, "llm_base_url", "http://model:8080/v1")
    monkeypatch.setattr(settings, "llm_model", "qwen3-8b")
    monkeypatch.setattr(llm, "_state", {"available": None, "error": None, "checked_at": None,
                                        "since": None})
    monkeypatch.setattr(llm, "_listeners", [])
    return settings


def fake_get(status: int = 200, ids: tuple[str, ...] = ("qwen/qwen3-8b",), fail: bool = False):
    def get(url, **_kwargs):
        if fail:
            raise httpx.ConnectError("connection refused")
        return httpx.Response(status, json={"data": [{"id": i} for i in ids]},
                              request=httpx.Request("GET", url))
    return get


def test_not_configured_model_is_reported(monkeypatch):
    monkeypatch.setattr(llm.get_settings(), "llm_base_url", "")
    state = llm.check()
    assert (state["configured"], state["available"]) == (False, False)
    assert "LLM_BASE_URL" in state["error"]
    assert not llm.should_try()


def test_model_check_finds_server_and_model(model, monkeypatch):
    monkeypatch.setattr(llm.httpx, "get", fake_get())
    assert llm.check()["available"] is True

    monkeypatch.setattr(llm.httpx, "get", fake_get(ids=("llama-3",)))
    state = llm.check()
    assert state["available"] is False
    assert "qwen3-8b" in state["error"] and "llama-3" in state["error"]

    monkeypatch.setattr(llm.httpx, "get", fake_get(fail=True))
    assert "не отвечает" in llm.check()["error"]


def test_after_failure_requests_skip_model_until_it_recovers(model, monkeypatch):
    changes = []
    llm.on_change(changes.append)

    def broken(*_args, **_kwargs):
        raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr(llm.httpx, "post", broken)
    with pytest.raises(llm.LLMUnavailable):
        llm.complete([{"role": "user", "content": "тест"}])
    assert [c["available"] for c in changes] == [False]

    # Следующая заявка не ждёт таймаута — тема сразу по ключевым словам
    asked = []
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: asked.append(1))
    found = helpdesk.routing.classify("Течёт кран в туалете")
    assert (found.topic, found.by) == ("plumbing", "rules")
    assert not asked

    # Прошёл интервал проверки — модель снова пробуем
    llm._state["checked_at"] = datetime.now(UTC) - timedelta(seconds=model.llm_check_interval_s + 1)
    assert llm.should_try()

    monkeypatch.setattr(llm.httpx, "get", fake_get())
    llm.check()
    assert [c["available"] for c in changes] == [False, True]
    assert llm.should_try()


def test_deadline_is_written_in_local_time(monkeypatch):
    monkeypatch.setattr(helpdesk.get_settings(), "timezone", "Europe/Moscow")
    assert helpdesk.when(datetime(2026, 10, 20, 9, 0, tzinfo=UTC)) == "20.10.2026 12:00"
    monkeypatch.setattr(helpdesk.get_settings(), "timezone", "Nowhere/Unknown")
    assert helpdesk.when(datetime(2026, 10, 20, 9, 0, tzinfo=UTC)) == "20.10.2026 09:00"
