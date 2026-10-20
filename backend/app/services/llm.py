"""Клиент локальной языковой модели.

Работает с любым сервером, который понимает OpenAI-совместимый
/v1/chat/completions: llama.cpp (сервис llm в docker-compose), LM Studio, Ollama.
Модель нужна только для определения темы заявки. В тексте заявки бывают фамилии,
поэтому внешние сервисы не поддерживаются вовсе.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)

NOT_CONFIGURED = "Локальная модель не подключена (LLM_BASE_URL пуст)"


class LLMUnavailable(Exception):
    """Модель не настроена или не отвечает."""


def is_configured() -> bool:
    return bool(get_settings().llm_base_url)


# --- состояние модели ------------------------------------------------------------------
# Последний известный результат: проверки по расписанию и обычные запросы к модели.
# Пока модель недоступна, классификация не ждёт таймаута, а сразу берёт ключевые слова.

_lock = threading.Lock()
_state: dict = {"available": None, "error": None, "checked_at": None, "since": None}
_listeners: list[Callable[[dict], None]] = []


def on_change(listener: Callable[[dict], None]) -> None:
    """Подписка на смену доступности модели: стала доступна или перестала отвечать."""
    _listeners.append(listener)


def status() -> dict:
    settings = get_settings()
    with _lock:
        state = dict(_state)
    if not settings.llm_base_url:
        state.update(available=False, error=NOT_CONFIGURED)
    return {"configured": bool(settings.llm_base_url), "model": settings.llm_model, **state}


def _record(available: bool, error: str | None = None) -> None:
    moment = datetime.now(UTC)
    with _lock:
        changed = _state["available"] is not available
        _state.update(available=available, error=error, checked_at=moment)
        if changed:
            _state["since"] = moment
    if changed:
        if available:
            log.info("LLM is available")
        else:
            log.warning("LLM is unavailable: %s", error)
        snapshot = status()
        for listener in list(_listeners):
            try:
                listener(snapshot)
            except Exception:
                log.exception("LLM status listener failed")


def should_try() -> bool:
    """Стоит ли обращаться к модели. После сбоя запросы не идут, пока проверка по
    расписанию не скажет, что модель снова отвечает (или пока не пройдёт интервал)."""
    settings = get_settings()
    if not settings.llm_base_url:
        return False
    with _lock:
        available, checked_at = _state["available"], _state["checked_at"]
    if available is not False or checked_at is None:
        return True
    return datetime.now(UTC) - checked_at > timedelta(seconds=settings.llm_check_interval_s)


def _model_listed(model: str, ids: list[str]) -> bool:
    # LM Studio отдаёт идентификаторы вида «qwen/qwen3-8b», а в настройке пишут «qwen3-8b»
    return any(model == i or i.endswith(f"/{model}") or model.endswith(f"/{i}") for i in ids)


def check() -> dict:
    """Проверяет, что сервер модели отвечает и нужная модель на нём есть."""
    settings = get_settings()
    if not settings.llm_base_url:
        _record(False, NOT_CONFIGURED)
        return status()
    headers = {"Authorization": f"Bearer {settings.llm_api_key}"} if settings.llm_api_key else {}
    try:
        response = httpx.get(f"{settings.llm_base_url.rstrip('/')}/models", headers=headers,
                             timeout=httpx.Timeout(10.0, connect=5.0))
        response.raise_for_status()
        data = response.json().get("data") or []
        ids = [str(m.get("id")) for m in data if isinstance(m, dict) and m.get("id")]
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        _record(False, f"Сервер модели не отвечает: {exc}")
        return status()
    model = settings.llm_model
    # «local» — значение по умолчанию: llama.cpp отвечает своей моделью на любое имя
    if ids and model and model != "local" and not _model_listed(model, ids):
        _record(False, f"Модель «{model}» не загружена на сервере, доступны: {', '.join(ids[:5])}")
    else:
        _record(True)
    return status()


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
        raise LLMUnavailable(NOT_CONFIGURED)
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
    except httpx.HTTPError as exc:
        log.warning("LLM request failed: %s", exc)
        _record(False, f"Модель не ответила: {exc}")
        raise LLMUnavailable(f"Модель не ответила: {exc}") from exc
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        # Сервер ответил, но не в формате OpenAI: модель работает, а разобрать ответ нельзя
        log.warning("LLM returned malformed response: %s", exc)
        raise LLMUnavailable(f"Модель вернула ответ в неожиданном формате: {exc}") from exc
    _record(True)
    text = strip_thinking(content)
    if not text:
        raise LLMUnavailable("Модель вернула пустой ответ")
    return text
