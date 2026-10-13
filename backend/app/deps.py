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

# Кто может менять данные учреждений и запускать расчёты
EDITORS = (Role.admin, Role.regional_analyst, Role.municipal_specialist, Role.director)
# Кто готовит проекты и ведёт задачи
PLANNERS = (Role.admin, Role.regional_analyst, Role.municipal_specialist)
# Кто утверждает проекты и правит нормативы
APPROVERS = (Role.admin, Role.regional_analyst)
# Кому доступны только заявки: штатные расписания и аналитика им не показываются
SERVICE_ROLES = (Role.executor, Role.employee)


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


def require_analytics_access(user: User = Depends(get_current_user)) -> User:
    if user.role in SERVICE_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Раздел недоступен для вашей роли")
    return user


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

    def org_ids(self, municipality_id: int | None = None) -> list[int] | None:
        """None означает «без ограничений» — так запросы не тянут список из тысячи id."""
        if self.is_regional and municipality_id is None:
            return None
        query = self.organizations().with_only_columns(Organization.id)
        if municipality_id is not None:
            query = query.where(Organization.municipality_id == municipality_id)
        return list(self.db.scalars(query))

    def get_org(self, org_id: int) -> Organization:
        org = self.db.scalar(self.organizations().where(Organization.id == org_id))
        if org is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Учреждение не найдено")
        return org

    def can_see_municipality(self, municipality_id: int | None) -> bool:
        if self.is_regional:
            return True
        if self.user.role == Role.municipal_specialist:
            return municipality_id == self.user.municipality_id
        return False

    def can_see_project(self, project) -> bool:
        if self.is_regional:
            return True
        if self.user.role == Role.municipal_specialist:
            return project.municipality_id == self.user.municipality_id
        # Директор видит проект, если он затрагивает его учреждение
        org_id = self.user.organization_id
        return project.organization_id == org_id or any(
            item.organization_id == org_id for item in project.items
        )


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
