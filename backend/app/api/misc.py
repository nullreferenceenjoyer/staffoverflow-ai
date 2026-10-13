"""Чат с помощником, уведомления, пользователи и журнал действий."""

import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import SessionLocal, get_db
from app.deps import (
    SERVICE_ROLES,
    Scope,
    audit,
    get_current_user,
    get_scope,
    require_analytics_access,
    require_roles,
)
from app.models import AuditLog, Notification, Role, User
from app.schemas import ChatRequest, NotificationOut, UserCreate, UserOut, UserUpdate
from app.security import hash_password
from app.services import assistant, llm

router = APIRouter()


# --- помощник ------------------------------------------------------------------------


@router.get("/assistant/status", tags=["assistant"])
def assistant_status(_: User = Depends(get_current_user)):
    return llm.probe()


@router.post("/assistant/chat", tags=["assistant"],
             dependencies=[Depends(require_analytics_access)])
def chat(body: ChatRequest, request: Request, scope: Scope = Depends(get_scope)):
    """Ответ помощника потоком Server-Sent Events."""
    audit(scope.db, scope.user, "assistant_question", details={"question": body.question[:500]},
          request=request)
    scope.db.commit()
    history = [m.model_dump() for m in body.history]
    user_id = scope.user.id

    def events():
        # Сессия из зависимости закрывается раньше, чем заканчивается стрим,
        # поэтому на время генерации открываем отдельную
        with SessionLocal() as db:
            stream_scope = Scope(db.get(User, user_id), db)
            for event in assistant.run(stream_scope, body.question, history):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        yield 'data: {"type": "done"}\n\n'

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# --- уведомления ---------------------------------------------------------------------


@router.get("/notifications", response_model=list[NotificationOut], tags=["notifications"])
def list_notifications(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.scalars(
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc())
        .limit(50)
    ).all()


@router.post("/notifications/read", status_code=status.HTTP_204_NO_CONTENT,
             tags=["notifications"])
def mark_notifications_read(db: Session = Depends(get_db),
                            user: User = Depends(get_current_user)):
    db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
    )
    db.commit()


# --- пользователи и аудит ------------------------------------------------------------


def _check_binding(role: Role, municipality_id: int | None, organization_id: int | None) -> None:
    if role == Role.municipal_specialist and municipality_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Специалисту нужно указать муниципалитет")
    if role in (Role.director, *SERVICE_ROLES) and organization_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Для этой роли нужно указать учреждение")


@router.get("/users", response_model=list[UserOut], tags=["admin"])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_roles(Role.admin))):
    return db.scalars(select(User).order_by(User.full_name)).all()


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED,
             tags=["admin"])
def create_user(body: UserCreate, request: Request, db: Session = Depends(get_db),
                admin: User = Depends(require_roles(Role.admin))):
    _check_binding(body.role, body.municipality_id, body.organization_id)
    user = User(**body.model_dump(exclude={"password"}),
                password_hash=hash_password(body.password))
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Такой e-mail или Telegram ID уже используется") from exc
    audit(db, admin, "user_created", entity="user", entity_id=user.id,
          details={"email": user.email, "role": user.role}, request=request)
    db.commit()
    return user


@router.patch("/users/{user_id}", response_model=UserOut, tags=["admin"])
def update_user(user_id: int, body: UserUpdate, request: Request, db: Session = Depends(get_db),
                admin: User = Depends(require_roles(Role.admin))):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")
    changes = body.model_dump(exclude_unset=True)
    if user.id == admin.id and (changes.get("is_active") is False
                                or changes.get("role", Role.admin) != Role.admin):
        raise HTTPException(status.HTTP_409_CONFLICT, "Нельзя лишить прав самого себя")
    password = changes.pop("password", None)
    if password:
        user.password_hash = hash_password(password)
    for key, value in changes.items():
        setattr(user, key, value)
    _check_binding(Role(user.role), user.municipality_id, user.organization_id)
    audit(db, admin, "user_updated", entity="user", entity_id=user.id,
          details={"fields": sorted(changes) + (["password"] if password else [])},
          request=request)
    try:
        db.commit()
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Такой Telegram ID уже используется") from exc
    return user


@router.get("/audit", tags=["admin"])
def audit_log(limit: int = 200, offset: int = 0, db: Session = Depends(get_db),
              _: User = Depends(require_roles(Role.admin))):
    rows = db.scalars(
        select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 1000)).offset(offset)
    ).all()
    return [
        {"id": r.id, "created_at": r.created_at, "user_email": r.user_email, "action": r.action,
         "entity": r.entity, "entity_id": r.entity_id, "details": r.details, "ip": r.ip}
        for r in rows
    ]
