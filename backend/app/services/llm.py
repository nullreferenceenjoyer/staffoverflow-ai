"""Клиент локальной языковой модели.

Работает с любым сервером, который понимает OpenAI-совместимый
/v1/chat/completions: llama.cpp (сервис llm в docker-compose), LM Studio, Ollama.
Модель нужна только для определения темы заявки. В тексте заявки бывают фамилии,
поэтому внешние сервисы не поддерживаются вовсе.
"""

from __future__ import annotations

import logging

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)


class LLMUnavailable(Exception):
    """Модель не настроена или не отвечает."""


def is_configured() -> bool:
    return bool(get_settings().llm_base_url)


def _payload(messages: list[dict], max_tokens: int | None) -> dict:
    settings = get_settings()
    payload = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": settings.llm_temperature,
        "max_tokens": max_tokens or settings.llm_max_tokens,
        "stream": False,
    }
    if settings.llm_disable_thinking:
        # llama.cpp понимает параметр шаблона, LM Studio — только «/no_think» в тексте
        payload["chat_template_kwargs"] = {"enable_thinking": False}
        if "qwen" in settings.llm_model.lower():
            payload["messages"] = _with_no_think(messages)
    return payload


def _with_no_think(messages: list[dict]) -> list[dict]:
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message["role"] == "user" and isinstance(message.get("content"), str):
            patched = dict(message, content=message["content"] + " /no_think")
            return messages[:index] + [patched] + messages[index + 1:]
    return messages


def strip_thinking(text: str) -> str:
    """Убирает блок <think>…</think>, если модель всё же рассуждает вслух."""
    stripped = text.strip()
    if stripped.startswith("<think>"):
        _, _, stripped = stripped.partition("</think>")
    return stripped.strip()


def complete(messages: list[dict], *, max_tokens: int | None = None) -> str:
    """Один запрос к модели. Бросает LLMUnavailable, если ответа нет."""
    settings = get_settings()
    if not settings.llm_base_url:
        raise LLMUnavailable("Локальная модель не подключена (LLM_BASE_URL пуст)")
    headers = {"Authorization": f"Bearer {settings.llm_api_key}"} if settings.llm_api_key else {}
    try:
        response = httpx.post(
            f"{settings.llm_base_url.rstrip('/')}/chat/completions",
            json=_payload(messages, max_tokens), headers=headers,
            # На CPU первый токен может идти десятки секунд, а соединение должно падать быстро
            timeout=httpx.Timeout(settings.llm_timeout_s, connect=5.0),
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"].get("content") or ""
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
        log.warning("LLM request failed: %s", exc)
        raise LLMUnavailable(f"Модель не ответила: {exc}") from exc
    text = strip_thinking(content)
    if not text:
        raise LLMUnavailable("Модель вернула пустой ответ")
    return text
