"""Зависимости FastAPI: текущий пользователь, проверка ролей и область видимости данных."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AuditLog, Organization, Role, User
from app.security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

# Роли, которые работают в пределах одного учреждения
ORG_ROLES = (Role.director, Role.executor, Role.employee)


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    user_id = decode_access_token(token)
    user = db.get(User, user_id) if user_id else None
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется вход в систему",
                            headers={"WWW-Authenticate": "Bearer"})
    return user


def require_roles(*roles: Role) -> Callable[..., User]:
    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостаточно прав")
        return user

    return checker


class Scope:
    """Какие учреждения видит пользователь.

    Регион (админ, аналитик, наблюдатель) видит всё, специалист управления
    образования — свой муниципалитет, директор — только своё учреждение.
    """

    def __init__(self, user: User, db: Session):
        self.user = user
        self.db = db

    @property
    def is_regional(self) -> bool:
        return self.user.role in (Role.admin, Role.regional_analyst, Role.observer)

    def organizations(self):
        query = select(Organization)
        if self.is_regional:
            return query
        if self.user.role == Role.municipal_specialist:
            return query.where(Organization.municipality_id == self.user.municipality_id)
        return query.where(Organization.id == self.user.organization_id)

    def get_org(self, org_id: int) -> Organization:
        org = self.db.scalar(self.organizations().where(Organization.id == org_id))
        if org is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Учреждение не найдено")
        return org


def get_scope(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Scope:
    return Scope(user, db)


def audit(db: Session, user: User | None, action: str, *, entity: str | None = None,
          entity_id: int | str | None = None, details: dict | None = None,
          request: Request | None = None) -> None:
    """Добавляет запись в журнал; фиксируется вместе с основной транзакцией."""
    db.add(AuditLog(
        user_id=user.id if user else None,
        user_email=user.email if user else None,
        action=action,
        entity=entity,
        entity_id=None if entity_id is None else str(entity_id),
        details=details,
        ip=request.client.host if request and request.client else None,
    ))
