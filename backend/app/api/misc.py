"""Уведомления, пользователи, справочники учреждений и журнал действий."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import ORG_ROLES, audit, get_current_user, require_roles
from app.models import AuditLog, Brigade, Municipality, Notification, Organization, Role, User
from app.schemas import (
    MunicipalityOut,
    NotificationOut,
    OrganizationOut,
    UserCreate,
    UserOut,
    UserUpdate,
)
from app.security import hash_password

router = APIRouter()


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


def _check_binding(role: Role, municipality_id: int | None, organization_id: int | None,
                   brigade_id: int | None = None) -> None:
    if role == Role.brigade and brigade_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Участнику выездной бригады нужно указать бригаду")
    if role == Role.municipal_specialist and municipality_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Специалисту нужно указать муниципалитет")
    if role in ORG_ROLES and organization_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Для этой роли нужно указать учреждение")


@router.get("/municipalities", response_model=list[MunicipalityOut], tags=["admin"])
def list_municipalities(db: Session = Depends(get_db),
                        _: User = Depends(require_roles(Role.admin))):
    return db.scalars(select(Municipality).order_by(Municipality.name)).all()


@router.get("/organizations", response_model=list[OrganizationOut], tags=["admin"])
def list_organizations(db: Session = Depends(get_db),
                       _: User = Depends(require_roles(Role.admin))):
    return db.scalars(select(Organization).order_by(Organization.name)).all()


def _check_references(db: Session, municipality_id: int | None,
                      organization_id: int | None, brigade_id: int | None = None) -> None:
    if brigade_id is not None and db.get(Brigade, brigade_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Бригада не найдена")
    if municipality_id is not None and db.get(Municipality, municipality_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Муниципалитет не найден")
    if organization_id is not None and db.get(Organization, organization_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Учреждение не найдено")


@router.get("/users", response_model=list[UserOut], tags=["admin"])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_roles(Role.admin))):
    return db.scalars(select(User).order_by(User.full_name)).all()


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED,
             tags=["admin"])
def create_user(body: UserCreate, request: Request, db: Session = Depends(get_db),
                admin: User = Depends(require_roles(Role.admin))):
    _check_binding(body.role, body.municipality_id, body.organization_id, body.brigade_id)
    _check_references(db, body.municipality_id, body.organization_id, body.brigade_id)
    data = body.model_dump(exclude={"password"})
    if body.role != Role.brigade:
        data["brigade_id"] = None
    user = User(**data, password_hash=hash_password(body.password))
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Такой e-mail уже используется") from exc
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
    if user.role != Role.brigade:
        user.brigade_id = None
    _check_binding(Role(user.role), user.municipality_id, user.organization_id, user.brigade_id)
    _check_references(db, user.municipality_id, user.organization_id, user.brigade_id)
    audit(db, admin, "user_updated", entity="user", entity_id=user.id,
          details={"fields": sorted(changes) + (["password"] if password else [])},
          request=request)
    db.commit()
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
