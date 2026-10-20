"""Обновления заявок в реальном времени.

Как изменение доходит до браузера:
  1. Сессия SQLAlchemy запоминает, какие заявки и уведомления менялись в транзакции.
  2. Перед фиксацией транзакции в PostgreSQL уходит NOTIFY с их номерами. NOTIFY
     транзакционный: при откате он не отправится, при фиксации — придёт ровно один раз.
  3. Каждый процесс API слушает канал (LISTEN) и раздаёт событие открытым потокам
     /api/events — только тем пользователям, которых заявка касается.
  4. Браузер перечитывает изменившиеся заявки обычными запросами, с проверкой прав.

Так изменения из любого экземпляра API и из фонового worker видны всем сразу,
без отдельного брокера сообщений.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import chain

from sqlalchemy import event, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

log = logging.getLogger(__name__)

CHANNEL = "requests_live"
# В NOTIFY помещается до 8000 байт; если изменилось слишком много, просим перечитать всё
MAX_PAYLOAD = 7000
_PENDING = "live_pending"


# --- сбор изменений в сессии -----------------------------------------------------------


def _pending(session: Session) -> dict:
    return session.info.setdefault(_PENDING, {"requests": {}, "users": set()})


def _previous(obj, names: tuple[str, ...]) -> set:
    """Прежние значения полей: кому заявка принадлежала до изменения."""
    values = set()
    state = inspect(obj)
    for name in names:
        for value in state.attrs[name].history.deleted or ():
            values.add(getattr(value, "id", value))
    values.discard(None)
    return values


def _after_flush(session: Session, _context) -> None:
    pending = _pending(session)
    for obj in chain(session.new, session.dirty, session.deleted):
        table = getattr(obj, "__tablename__", None)
        if table == "incoming_requests" and obj.id is not None:
            before = pending["requests"].setdefault(
                obj.id, {"people": set(), "brigades": set(), "roles": set()})
            # Прежний исполнитель тоже должен узнать, что заявка ушла от него
            before["people"] |= _previous(obj, ("assignee", "assignee_id"))
            before["brigades"] |= _previous(obj, ("brigade", "brigade_id"))
            before["roles"] |= _previous(obj, ("routed_role",))
        elif table == "request_events" and obj.request_id is not None:
            pending["requests"].setdefault(
                obj.request_id, {"people": set(), "brigades": set(), "roles": set()})
        elif table == "notifications":
            pending["users"].add(obj.user_id)
            if obj.request_id is not None:
                pending["requests"].setdefault(
                    obj.request_id, {"people": set(), "brigades": set(), "roles": set()})


_INFO_SQL = text("""
    SELECT r.id, r.organization_id, o.municipality_id, r.author_id, r.assignee_id,
           r.brigade_id, r.routed_role
    FROM incoming_requests r JOIN organizations o ON o.id = r.organization_id
    WHERE r.id = ANY(:ids)
""")


def _before_commit(session: Session) -> None:
    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        return
    # before_commit вызывается до финального flush — сбрасываем сами, чтобы ничего не упустить
    session.flush()
    pending = session.info.pop(_PENDING, None)
    if not pending or not (pending["requests"] or pending["users"]):
        return
    payload: dict = {"users": sorted(pending["users"])}
    ids = sorted(pending["requests"])
    if len(ids) > 200:
        payload = {"all": True}
    elif ids:
        rows = session.execute(_INFO_SQL, {"ids": ids}).all()
        payload["requests"] = [
            {
                "id": row.id, "org": row.organization_id, "mun": row.municipality_id,
                "people": sorted({row.author_id, row.assignee_id,
                                  *pending["requests"][row.id]["people"]} - {None}),
                "brigades": sorted({row.brigade_id,
                                    *pending["requests"][row.id]["brigades"]} - {None}),
                "roles": sorted({row.routed_role, *pending["requests"][row.id]["roles"]}),
            }
            for row in rows
        ]
    message = json.dumps(payload, separators=(",", ":"))
    if len(message.encode()) > MAX_PAYLOAD:
        message = json.dumps({"all": True})
    session.execute(text("SELECT pg_notify(:channel, :payload)"),
                    {"channel": CHANNEL, "payload": message})


def _forget(session: Session, *_args) -> None:
    session.info.pop(_PENDING, None)


def install(factory: sessionmaker) -> None:
    """Подключает сбор изменений ко всем сессиям фабрики."""
    event.listen(factory, "after_flush", _after_flush)
    event.listen(factory, "before_commit", _before_commit)
    event.listen(factory, "after_rollback", _forget)


# --- раздача событий подписчикам -------------------------------------------------------


@dataclass(frozen=True)
class Viewer:
    """Снимок пользователя на момент подключения: по нему решается, что ему показывать."""

    id: int
    role: str
    organization_id: int | None
    municipality_id: int | None
    brigade_id: int | None


@dataclass(eq=False)
class Subscriber:
    viewer: Viewer
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=100))

    def send(self, message: dict) -> None:
        try:
            self.queue.put_nowait(message)
        except asyncio.QueueFull:
            # Клиент не успевает читать: выбрасываем очередь и просим перечитать всё
            while not self.queue.empty():
                self.queue.get_nowait()
            self.queue.put_nowait({"type": "requests", "all": True})


class Hub:
    """Слушает канал PostgreSQL и раздаёт события открытым потокам этого процесса."""

    def __init__(self, concerns: Callable[[Viewer, dict], bool]):
        self.concerns = concerns
        self.subscribers: set[Subscriber] = set()
        self.connected = False
        self._loop: asyncio.AbstractEventLoop | None = None

    def subscribe(self, viewer: Viewer) -> Subscriber:
        subscriber = Subscriber(viewer)
        self.subscribers.add(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: Subscriber) -> None:
        self.subscribers.discard(subscriber)

    def broadcast(self, message: dict) -> None:
        for subscriber in list(self.subscribers):
            subscriber.send(message)

    def broadcast_threadsafe(self, message: dict) -> None:
        """Для вызова из потоков пула, где работают синхронные обработчики."""
        if self._loop is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self.broadcast, message)

    def dispatch(self, payload: str) -> None:
        try:
            data = json.loads(payload)
        except ValueError:
            log.warning("Malformed live payload: %.100s", payload)
            return
        if data.get("all"):
            self.broadcast({"type": "requests", "all": True})
            self.broadcast({"type": "notifications"})
            return
        users = set(data.get("users", ()))
        infos = data.get("requests", ())
        for subscriber in list(self.subscribers):
            ids = [info["id"] for info in infos if self.concerns(subscriber.viewer, info)]
            if ids:
                subscriber.send({"type": "requests", "ids": ids})
            if subscriber.viewer.id in users:
                subscriber.send({"type": "notifications"})

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        import psycopg  # только здесь: юнит-тестам и worker асинхронный драйвер не нужен

        url = make_url(get_settings().database_url).set(drivername="postgresql")
        dsn = url.render_as_string(hide_password=False)
        failed = False
        while True:
            try:
                async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
                    await conn.execute(f"LISTEN {CHANNEL}")
                    self.connected = True
                    if failed:
                        # Пока связи не было, события могли потеряться
                        log.info("Live updates restored")
                        self.broadcast({"type": "requests", "all": True})
                        self.broadcast({"type": "notifications"})
                    failed = False
                    async for note in conn.notifies():
                        self.dispatch(note.payload)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if not failed:
                    log.warning("Live updates listener failed, retrying: %s", exc)
                failed = True
            self.connected = False
            await asyncio.sleep(5)
