"""Разъяснения по высвобождению: поток ответа модели и школы вне расчёта управления."""

import json
from contextlib import contextmanager

from app.services import llm, program_fill

MUNICIPAL = "municipal@demo.ru"


def test_school_outside_plan_is_staffed_by_norm():
    lines, classes = program_fill.school_in_norm(760, 3)
    assert classes == 30
    cleaners = lines["Уборщик служебных помещений"]
    # Уборщиков ровно столько, сколько нужно по классам, шагом 0,25 ставки
    assert cleaners * 3 >= classes and (cleaners - 0.25) * 3 < classes
    assert cleaners % 0.25 == 0
    assert lines["Директор"] == 1
    assert program_fill.school_in_norm(120, 3)[0]["Заведующий хозяйством"] == 0.5


def test_stream_skips_thinking(monkeypatch):
    pieces = ["<thi", "nk>считаю", "</think>", "\n\nПотому что", " вакансии."]

    class Response:
        def raise_for_status(self):
            pass

        def iter_lines(self):
            for piece in pieces:
                yield "data: " + json.dumps({"choices": [{"delta": {"content": piece}}]})
            yield "data: [DONE]"

    @contextmanager
    def fake_stream(*args, **kwargs):
        assert kwargs["json"]["stream"] is True
        yield Response()

    monkeypatch.setattr(llm.get_settings(), "llm_base_url", "http://model:8080/v1")
    monkeypatch.setattr(llm.httpx, "stream", fake_stream)
    assert "".join(llm.stream([{"role": "user", "content": "?"}])) == "Потому что вакансии."


def test_explain_without_model_says_so(client, login, monkeypatch):
    monkeypatch.setattr(llm.get_settings(), "llm_base_url", "")
    response = client.post("/api/program/explain", headers=login(MUNICIPAL),
                           json={"question": "Почему сокращают ставки?"})
    assert response.status_code == 503
