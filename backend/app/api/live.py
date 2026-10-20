"""Поток событий для интерфейса и состояние локальной модели."""

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from app.db import SessionLocal
from app.deps import get_current_user, oauth2_scheme, require_roles
from app.models import Role, User
from app.security import decode_access_token
from app.services import helpdesk, live, llm

router = APIRouter()
hub = live.Hub(helpdesk.concerns)

# Пустая строка раз в 20 секунд: прокси не закрывает молчащее соединение,
# а браузер быстрее замечает, что связь пропала
KEEPALIVE_S = 20


def _viewer(token: str) -> live.Viewer:
    # Сессию закрываем сразу: поток живёт часами, и держать на нём соединение с базой незачем
    with SessionLocal() as db:
        user_id = decode_access_token(token)
        user = db.get(User, user_id) if user_id else None
        if user is None or not user.is_active:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется вход в систему",
                                headers={"WWW-Authenticate": "Bearer"})
        return live.Viewer(user.id, user.role, user.organization_id, user.municipality_id,
                           user.brigade_id)


def _sse(kind: str, data: dict) -> str:
    return f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


@router.get("/events", tags=["live"])
async def events(request: Request, token: str = Depends(oauth2_scheme)):
    """Server-Sent Events: какие заявки изменились, пришли ли уведомления, что с моделью.

    Содержимое заявок в поток не попадает — интерфейс перечитывает их обычными
    запросами, где проверяются права.
    """
    viewer = await run_in_threadpool(_viewer, token)

    async def stream():
        subscriber = hub.subscribe(viewer)
        try:
            yield "retry: 3000\n\n"
            yield _sse("hello", {"live": hub.connected})
            while True:
                try:
                    message = await asyncio.wait_for(subscriber.queue.get(), KEEPALIVE_S)
                except TimeoutError:
                    if await request.is_disconnected():
                        break
                    yield ": ping\n\n"
                    continue
                yield _sse(message["type"], message)
        finally:
            hub.unsubscribe(subscriber)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        # nginx не должен копить поток в буфере
        "X-Accel-Buffering": "no",
    })


def _public(state: dict, user: User) -> dict:
    """Подробности сбоя (адрес сервера, текст ошибки) видит только администратор."""
    result = {
        "configured": state["configured"],
        "available": state["available"],
        "checked_at": state["checked_at"],
        "since": state["since"],
    }
    if user.role == Role.admin:
        result.update(model=state["model"], error=state["error"])
    return result


@router.get("/llm/status", tags=["service"])
def llm_status(user: User = Depends(get_current_user)):
    return _public(llm.status(), user)


@router.post("/llm/check", tags=["service"])
def llm_check(user: User = Depends(require_roles(Role.admin))):
    """Проверить модель сейчас, не дожидаясь проверки по расписанию."""
    return _public(llm.check(), user)
