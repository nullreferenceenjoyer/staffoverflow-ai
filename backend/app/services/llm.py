"""Клиент языковой модели.

Работает с любым сервером, который понимает OpenAI-совместимый
/v1/chat/completions: llama.cpp (сервис llm в docker-compose), LM Studio, Ollama.

Правило маршрутизации одно: всё, что может содержать персональные данные или
строки штатного расписания, уходит только в локальную модель. Облачная
используется лишь для обезличенных сводных текстов и только если её включили.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)


class LLMUnavailable(Exception):
    """Модель не настроена или не отвечает."""


class LLMRejectedRequest(LLMUnavailable):
    """Сервер ответил 4xx — обычно модель не поддерживает tools."""


@dataclass(frozen=True)
class Endpoint:
    base_url: str
    model: str
    api_key: str
    is_local: bool


def pick_endpoint(*, sensitive: bool) -> Endpoint:
    settings = get_settings()
    if not sensitive and settings.cloud_llm_enabled and settings.cloud_llm_base_url:
        return Endpoint(settings.cloud_llm_base_url.rstrip("/"), settings.cloud_llm_model,
                        settings.cloud_llm_api_key, is_local=False)
    if not settings.llm_base_url:
        raise LLMUnavailable("Локальная модель не подключена (LLM_BASE_URL пуст)")
    return Endpoint(settings.llm_base_url.rstrip("/"), settings.llm_model,
                    settings.llm_api_key, is_local=True)


def is_configured() -> bool:
    return bool(get_settings().llm_base_url)


def probe() -> dict:
    """Проверяет, отвечает ли локальная модель. Нужен интерфейсу, чтобы сразу
    показать, что помощник недоступен, а не ждать таймаута на первом вопросе."""
    settings = get_settings()
    if not settings.llm_base_url:
        return {"configured": False, "online": False, "model": None}
    try:
        response = httpx.get(f"{settings.llm_base_url.rstrip('/')}/models", timeout=3,
                             headers=_headers(pick_endpoint(sensitive=True)))
        response.raise_for_status()
        online = True
    except httpx.HTTPError:
        online = False
    return {"configured": True, "online": online, "model": settings.llm_model}


def _payload(endpoint: Endpoint, messages: list[dict], *, tools: list[dict] | None,
             max_tokens: int | None, stream: bool) -> dict:
    settings = get_settings()
    payload = {
        "model": endpoint.model,
        "messages": messages,
        "temperature": settings.llm_temperature,
        "max_tokens": max_tokens or settings.llm_max_tokens,
        "stream": stream,
    }
    if tools:
        payload["tools"] = tools
    if endpoint.is_local and settings.llm_disable_thinking:
        # llama.cpp понимает параметр шаблона, LM Studio — только «/no_think» в тексте
        payload["chat_template_kwargs"] = {"enable_thinking": False}
        if "qwen" in endpoint.model.lower():
            payload["messages"] = _with_no_think(messages)
    return payload


def _with_no_think(messages: list[dict]) -> list[dict]:
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message["role"] == "user" and isinstance(message.get("content"), str):
            patched = dict(message, content=message["content"] + " /no_think")
            return messages[:index] + [patched] + messages[index + 1:]
    return messages


def _headers(endpoint: Endpoint) -> dict:
    return {"Authorization": f"Bearer {endpoint.api_key}"} if endpoint.api_key else {}


def _timeout() -> httpx.Timeout:
    # На CPU первый токен может идти десятки секунд, а соединение должно падать быстро
    return httpx.Timeout(get_settings().llm_timeout_s, connect=5.0)


class ThinkFilter:
    """Вырезает из потока блок <think>…</think>, если модель всё же рассуждает вслух."""

    OPEN, CLOSE = "<think>", "</think>"

    def __init__(self) -> None:
        self._buffer = ""
        self._inside = False
        self._started = False

    def feed(self, text: str) -> str:
        if self._started and not self._inside:
            return text
        self._buffer += text
        if not self._started:
            stripped = self._buffer.lstrip()
            if self.OPEN.startswith(stripped[: len(self.OPEN)]) and len(stripped) < len(self.OPEN):
                return ""  # пока непонятно, начинается ли ответ с <think>
            self._started = True
            self._inside = stripped.startswith(self.OPEN)
            if not self._inside:
                out, self._buffer = self._buffer, ""
                return out
        if self.CLOSE in self._buffer:
            out = self._buffer.split(self.CLOSE, 1)[1].lstrip()
            self._buffer, self._inside = "", False
            return out
        return ""


def strip_thinking(text: str) -> str:
    return ThinkFilter().feed(text).strip()


def complete(messages: list[dict], *, sensitive: bool = True, max_tokens: int | None = None) -> str:
    """Один запрос без стриминга. Бросает LLMUnavailable, если ответа нет."""
    endpoint = pick_endpoint(sensitive=sensitive)
    payload = _payload(endpoint, messages, tools=None, max_tokens=max_tokens, stream=False)
    try:
        response = httpx.post(f"{endpoint.base_url}/chat/completions", json=payload,
                              headers=_headers(endpoint), timeout=_timeout())
        response.raise_for_status()
        content = response.json()["choices"][0]["message"].get("content") or ""
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
        log.warning("LLM request failed: %s", exc)
        raise LLMUnavailable(f"Модель не ответила: {exc}") from exc
    text = strip_thinking(content)
    if not text:
        raise LLMUnavailable("Модель вернула пустой ответ")
    return text


def stream_chat(messages: list[dict], *, tools: list[dict] | None = None,
                sensitive: bool = True, max_tokens: int | None = None) -> Iterator[dict]:
    """Стримит ответ модели.

    Отдаёт события {"type": "delta", "text": ...} по мере генерации и в конце,
    если модель запросила инструменты, одно {"type": "tool_calls", "calls": [...]}.
    """
    endpoint = pick_endpoint(sensitive=sensitive)
    payload = _payload(endpoint, messages, tools=tools, max_tokens=max_tokens, stream=True)
    calls: dict[int, dict] = {}
    think_filter = ThinkFilter()

    try:
        with httpx.stream("POST", f"{endpoint.base_url}/chat/completions", json=payload,
                          headers=_headers(endpoint), timeout=_timeout()) as response:
            if 400 <= response.status_code < 500:
                response.read()
                raise LLMRejectedRequest(response.text[:300])
            response.raise_for_status()
            for line in response.iter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    choice = json.loads(data)["choices"][0]
                except (ValueError, KeyError, IndexError):
                    continue
                delta = choice.get("delta") or {}
                for call in delta.get("tool_calls") or []:
                    slot = calls.setdefault(call.get("index", 0),
                                            {"id": "", "name": "", "arguments": ""})
                    slot["id"] = call.get("id") or slot["id"]
                    function = call.get("function") or {}
                    slot["name"] = function.get("name") or slot["name"]
                    slot["arguments"] += function.get("arguments") or ""
                if delta.get("content"):
                    text = think_filter.feed(delta["content"])
                    if text:
                        yield {"type": "delta", "text": text}
    except httpx.HTTPError as exc:
        log.warning("LLM stream failed: %s", exc)
        raise LLMUnavailable(f"Модель недоступна: {exc}") from exc

    if calls:
        yield {"type": "tool_calls", "calls": [calls[i] for i in sorted(calls)]}
