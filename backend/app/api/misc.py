"""Обращения учреждений, чат с помощником, пользователи и журнал действий."""

import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import SessionLocal, get_db
from app.deps import Scope, audit, get_current_user, get_scope, require_roles
from app.models import AuditLog, IncomingRequest, Organization, Role, User
from app.schemas import (
    ChatRequest,
    RequestIn,
    RequestOut,
    RequestUpdate,
    UserCreate,
    UserOut,
    UserUpdate,
)
from app.security import hash_password
from app.services import assistant, llm, routing

router = APIRouter()


# --- обращения -----------------------------------------------------------------------


def _visible_requests(scope: Scope):
    query = select(IncomingRequest).order_by(IncomingRequest.created_at.desc())
    if scope.is_regional:
        return query
    ids = scope.organizations().with_only_columns(Organization.id)
    return query.where(IncomingRequest.organization_id.in_(ids))


def _request_out(item: IncomingRequest) -> dict:
    return {
        **RequestOut.model_validate(item).model_dump(),
        "organization": item.organization.name,
        "topic_title": routing.TOPICS.get(item.topic, routing.TOPICS["other"])[0],
    }


@router.get("/requests", tags=["requests"])
def list_requests(scope: Scope = Depends(get_scope)):
    return [_request_out(r) for r in scope.db.scalars(_visible_requests(scope).limit(300))]


@router.post("/requests", status_code=status.HTTP_201_CREATED, tags=["requests"])
def create_request(body: RequestIn, request: Request, scope: Scope = Depends(get_scope)):
    user = scope.user
    if user.role == Role.observer:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Наблюдатель не может создавать обращения")
    org_id = user.organization_id if user.role == Role.director else body.organization_id
    if org_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Укажите учреждение")
    org = scope.get_org(org_id)

    topic, role, classified_by = routing.classify(body.text)
    item = IncomingRequest(organization_id=org.id, author_id=user.id, text=body.text,
                           topic=topic, routed_role=role, classified_by=classified_by)
    scope.db.add(item)
    scope.db.flush()
    audit(scope.db, user, "request_created", entity="request", entity_id=item.id,
          details={"topic": topic, "routed_role": role, "by": classified_by}, request=request)
    scope.db.commit()
    return _request_out(item)


@router.patch("/requests/{request_id}", tags=["requests"])
def update_request(request_id: int, body: RequestUpdate, request: Request,
                   scope: Scope = Depends(get_scope)):
    user = scope.user
    item = scope.db.scalar(_visible_requests(scope).where(IncomingRequest.id == request_id))
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Обращение не найдено")
    # Отвечает тот, кому обращение направлено, либо администратор
    if user.role not in (item.routed_role, Role.admin):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Обращение адресовано другой роли")
    changes = body.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(item, key, value)
    audit(scope.db, user, "request_updated", entity="request", entity_id=item.id,
          details={k: str(v)[:200] for k, v in changes.items()}, request=request)
    scope.db.commit()
    return _request_out(item)


# --- помощник ------------------------------------------------------------------------


@router.get("/assistant/status", tags=["assistant"])
def assistant_status(_: User = Depends(get_current_user)):
    return llm.probe()


@router.post("/assistant/chat", tags=["assistant"])
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


# --- пользователи и аудит ------------------------------------------------------------


def _check_binding(role: Role, municipality_id: int | None, organization_id: int | None) -> None:
    if role == Role.municipal_specialist and municipality_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Специалисту нужно указать муниципалитет")
    if role == Role.director and organization_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Директору нужно указать учреждение")


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
