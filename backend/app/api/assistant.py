"""Помощник по штатке: разговоры с историей.

Каждый видит только свои разговоры. Справка для модели собирается в пределах
территории пользователя, поэтому чужих учреждений помощник «не знает».
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.deps import Scope, audit, get_scope
from app.models import AssistantChat, Role
from app.schemas import AssistantAskIn
from app.services import assistant, staffing
from app.services.staffing_analysis import current_year, period

router = APIRouter(prefix="/assistant", tags=["assistant"])
MAX_CHATS = 50


def viewer(scope: Scope = Depends(get_scope)) -> Scope:
    if not staffing.can_view(scope.user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Помощник недоступен для вашей роли")
    return scope


def _chat(scope: Scope, chat_id: int) -> AssistantChat:
    chat = scope.db.scalar(select(AssistantChat).where(
        AssistantChat.id == chat_id, AssistantChat.user_id == scope.user.id)
        .options(selectinload(AssistantChat.messages), selectinload(AssistantChat.organization)))
    if chat is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Разговор не найден")
    return chat


@router.get("/chats")
def chats(scope: Scope = Depends(viewer)):
    items = scope.db.scalars(select(AssistantChat).where(AssistantChat.user_id == scope.user.id)
                             .options(selectinload(AssistantChat.organization))
                             .order_by(AssistantChat.updated_at.desc()).limit(MAX_CHATS))
    return [assistant.chat_out(c) for c in items]


@router.get("/chats/{chat_id}")
def chat(chat_id: int, scope: Scope = Depends(viewer)):
    return assistant.chat_out(_chat(scope, chat_id), with_messages=True)


@router.delete("/chats/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_chat(chat_id: int, scope: Scope = Depends(viewer)):
    scope.db.delete(_chat(scope, chat_id))
    scope.db.commit()


@router.post("/ask")
def ask(body: AssistantAskIn, request: Request, scope: Scope = Depends(viewer)):
    """Вопрос помощнику. Без chat_id начинается новый разговор."""
    db, user = scope.db, scope.user
    question = body.question.strip()
    if body.chat_id is not None:
        item = _chat(scope, body.chat_id)
        if item.organization_id is not None:
            scope.get_org(item.organization_id)  # учреждение могли убрать из территории
    else:
        year = body.year or current_year()
        try:
            period(year)
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
        org = None
        if body.organization_id is not None:
            if user.role == Role.observer:
                raise HTTPException(status.HTTP_403_FORBIDDEN,
                                    "Наблюдателю доступна только сводка без деталей")
            org = scope.get_org(body.organization_id)
        elif user.role == Role.director and user.organization_id:
            # У директора одно учреждение — разговор всегда про него
            org = scope.get_org(user.organization_id)
        item = AssistantChat(user_id=user.id, title=assistant.title_from(question),
                             academic_year=year, organization=org, messages=[])
        db.add(item)

    try:
        reply = assistant.answer(scope, item, question)
    except assistant.AssistantUnavailable as exc:
        db.rollback()
        detail = (f"Помощник недоступен: {exc}" if user.role == Role.admin else
                  "Помощник сейчас недоступен: локальная модель не отвечает. "
                  "Попробуйте позже или сообщите администратору.")
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail) from exc

    assistant.add_exchange(item, question, reply)
    item.updated_at = datetime.now(UTC)
    db.flush()
    audit(db, user, "assistant_asked", entity="assistant_chat", entity_id=item.id,
          details={"year": item.academic_year, "organization_id": item.organization_id},
          request=request)
    db.commit()
    return assistant.chat_out(_chat(scope, item.id), with_messages=True)
