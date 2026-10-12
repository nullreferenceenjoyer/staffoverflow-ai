"""Транспорты бота: Telegram и MAX.

Оба работают через long polling, поэтому входящих подключений в контур не требуют.
Различия между мессенджерами спрятаны здесь; логика команд — в handler.py.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)

POLL_TIMEOUT_S = 25
Button = tuple[str, str]  # (подпись, данные для обратного вызова)


@dataclass
class Incoming:
    chat_id: int
    text: str = ""
    callback_data: str | None = None
    callback_id: str | None = None


class Transport:
    name: str
    # Поле пользователя, в котором хранится идентификатор чата этого мессенджера
    user_field: str

    def poll(self) -> list[Incoming]:
        raise NotImplementedError

    def send(self, chat_id: int, text: str, buttons: list[Button] | None = None) -> None:
        raise NotImplementedError

    def ack(self, callback_id: str) -> None:
        """Подтверждает нажатие кнопки, чтобы у пользователя пропал индикатор ожидания."""

    def typing(self, chat_id: int) -> None:
        """Показывает «печатает…», пока готовится ответ модели."""


class TelegramTransport(Transport):
    name = "telegram"
    user_field = "telegram_chat_id"

    def __init__(self, token: str):
        self._client = httpx.Client(
            base_url=f"https://api.telegram.org/bot{token}/",
            timeout=httpx.Timeout(POLL_TIMEOUT_S + 10, connect=10),
        )
        self._offset = 0

    def _call(self, method: str, **params) -> dict:
        response = self._client.post(method, json=params)
        response.raise_for_status()
        return response.json()

    def poll(self) -> list[Incoming]:
        updates = self._call("getUpdates", offset=self._offset, timeout=POLL_TIMEOUT_S)
        result = []
        for update in updates.get("result", []):
            self._offset = update["update_id"] + 1
            callback = update.get("callback_query")
            message = update.get("message") or (callback or {}).get("message")
            if not message:
                continue
            result.append(Incoming(
                chat_id=message["chat"]["id"],
                text=(message.get("text") or "").strip() if not callback else "",
                callback_data=callback.get("data") if callback else None,
                callback_id=callback.get("id") if callback else None,
            ))
        return result

    def send(self, chat_id: int, text: str, buttons: list[Button] | None = None) -> None:
        params: dict = {"chat_id": chat_id, "text": text[:4000]}  # лимит Telegram — 4096
        if buttons:
            params["reply_markup"] = {"inline_keyboard": [
                [{"text": label, "callback_data": data} for label, data in buttons]
            ]}
        try:
            self._call("sendMessage", **params)
        except httpx.HTTPError as exc:
            log.warning("Telegram send failed: %s", exc)

    def ack(self, callback_id: str) -> None:
        self._call("answerCallbackQuery", callback_query_id=callback_id)

    def typing(self, chat_id: int) -> None:
        self._call("sendChatAction", chat_id=chat_id, action="typing")


class MaxTransport(Transport):
    """Бот в мессенджере MAX (Bot API на platform-api.max.ru)."""

    name = "max"
    user_field = "max_chat_id"

    def __init__(self, token: str, base_url: str = "https://platform-api.max.ru"):
        self._client = httpx.Client(
            base_url=base_url,
            headers={"Authorization": token},
            timeout=httpx.Timeout(POLL_TIMEOUT_S + 10, connect=10),
        )
        self._marker: int | None = None

    def poll(self) -> list[Incoming]:
        params: dict = {"timeout": POLL_TIMEOUT_S, "types": "message_created,message_callback"}
        if self._marker is not None:
            params["marker"] = self._marker
        response = self._client.get("/updates", params=params)
        response.raise_for_status()
        payload = response.json()
        self._marker = payload.get("marker", self._marker)

        result = []
        for update in payload.get("updates", []):
            message = update.get("message") or {}
            chat_id = (message.get("recipient") or {}).get("chat_id")
            if chat_id is None:
                continue
            if update.get("update_type") == "message_callback":
                callback = update.get("callback") or {}
                result.append(Incoming(chat_id=chat_id, callback_data=callback.get("payload"),
                                       callback_id=callback.get("callback_id")))
            else:
                text = ((message.get("body") or {}).get("text") or "").strip()
                result.append(Incoming(chat_id=chat_id, text=text))
        return result

    def send(self, chat_id: int, text: str, buttons: list[Button] | None = None) -> None:
        body: dict = {"text": text[:4000]}
        if buttons:
            body["attachments"] = [{"type": "inline_keyboard", "payload": {"buttons": [
                [{"type": "callback", "text": label, "payload": data} for label, data in buttons]
            ]}}]
        try:
            self._client.post("/messages", params={"chat_id": chat_id},
                              json=body).raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("MAX send failed: %s", exc)

    def ack(self, callback_id: str) -> None:
        self._client.post("/answers", params={"callback_id": callback_id},
                          json={"notification": "Принято"})
