from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Table,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Role(enum.StrEnum):
    admin = "admin"
    regional_analyst = "regional_analyst"
    municipal_specialist = "municipal_specialist"
    director = "director"
    observer = "observer"
    executor = "executor"  # хозяйственная служба на точке: работает в одном учреждении
    brigade = "brigade"  # участник выездной бригады: ездит по закреплённым учреждениям
    employee = "employee"  # сотрудник учреждения: подаёт заявки и видит только свои


class OrgType(enum.StrEnum):
    school = "school"
    preschool = "preschool"
    complex = "complex"  # школа с дошкольными группами


class RequestStatus(enum.StrEnum):
    new = "new"  # исполнитель не найден, ждёт распределения
    assigned = "assigned"
    in_progress = "in_progress"
    on_hold = "on_hold"  # исполнитель ждёт ответа заявителя, срок не идёт
    done = "done"  # выполнена, ждёт подтверждения заявителя
    closed = "closed"
    rejected = "rejected"


class Complexity(enum.StrEnum):
    simple = "simple"  # справится сотрудник на точке
    complex = "complex"  # нужна бригада и больше времени
    major = "major"  # крупная работа: бригада, предупреждение руководителю, можно разбить на этапы


class RequestKind(enum.StrEnum):
    planned = "planned"
    urgent = "urgent"
    emergency = "emergency"


def _str_enum(enum_cls: type[enum.Enum], length: int = 32) -> String:
    # Значения перечислений храним строками: добавить новое значение можно без миграции типа
    return String(length)


class Municipality(Base):
    __tablename__ = "municipalities"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)

    organizations: Mapped[list[Organization]] = relationship(back_populates="municipality")


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(primary_key=True)
    municipality_id: Mapped[int] = mapped_column(ForeignKey("municipalities.id"), index=True)
    name: Mapped[str] = mapped_column(String(300))
    org_type: Mapped[str] = mapped_column(_str_enum(OrgType))
    address: Mapped[str | None] = mapped_column(String(300))
    # Код во внешней системе (ГИС, ЕФИС, 1С) — по нему сопоставляются выгрузки
    external_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    # Координаты нужны, чтобы подсказать, какой бригаде учреждение ближе
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))

    municipality: Mapped[Municipality] = relationship(back_populates="organizations")
    buildings: Mapped[list[Building]] = relationship(
        cascade="all, delete-orphan", order_by="Building.id"
    )


class Building(Base):
    """Корпус учреждения: к нему привязываются заявки."""

    __tablename__ = "buildings"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    address: Mapped[str | None] = mapped_column(String(300))


# Какие учреждения обслуживает бригада. Одно учреждение может быть у нескольких
# бригад, если у них разные специализации (сантехники, электрики)
brigade_organizations = Table(
    "brigade_organizations",
    Base.metadata,
    Column("brigade_id", ForeignKey("brigades.id", ondelete="CASCADE"), primary_key=True),
    Column("organization_id", ForeignKey("organizations.id", ondelete="CASCADE"),
           primary_key=True),
)


class Brigade(Base):
    """Выездная бригада: группа сотрудников, которая ездит по закреплённым учреждениям."""

    __tablename__ = "brigades"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    # Округ, в котором работает бригада. Пусто — по всему региону
    municipality_id: Mapped[int | None] = mapped_column(ForeignKey("municipalities.id"))
    base_address: Mapped[str | None] = mapped_column(String(300))
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    # Темы заявок, которые бригада берёт. Пустой список — все хозяйственные
    topics: Mapped[list[str]] = mapped_column(JSONB, default=list)
    is_active: Mapped[bool] = mapped_column(default=True)

    municipality: Mapped[Municipality | None] = relationship()
    members: Mapped[list[User]] = relationship(back_populates="brigade", order_by="User.id")
    organizations: Mapped[list[Organization]] = relationship(
        secondary=brigade_organizations, order_by="Organization.name"
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True)
    full_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(_str_enum(Role))
    municipality_id: Mapped[int | None] = mapped_column(ForeignKey("municipalities.id"))
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"))
    brigade_id: Mapped[int | None] = mapped_column(
        ForeignKey("brigades.id", ondelete="SET NULL"), index=True
    )
    is_active: Mapped[bool] = mapped_column(default=True)

    brigade: Mapped[Brigade | None] = relationship(back_populates="members")


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text)
    request_id: Mapped[int | None] = mapped_column(
        ForeignKey("incoming_requests.id", ondelete="CASCADE")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IncomingRequest(Base):
    """Заявка: от «починить мебель в кабинете» до «нужна ставка логопеда»."""

    __tablename__ = "incoming_requests"
    __table_args__ = (Index("ix_requests_status_due", "status", "due_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    building_id: Mapped[int | None] = mapped_column(
        ForeignKey("buildings.id", ondelete="SET NULL")
    )
    location: Mapped[str | None] = mapped_column(String(200))  # кабинет, этаж
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(_str_enum(RequestKind), default=RequestKind.planned)
    topic: Mapped[str] = mapped_column(String(40))
    routed_role: Mapped[str] = mapped_column(_str_enum(Role))
    assignee_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    # Заявка бригады: пока её не взял конкретный участник, assignee пуст
    brigade_id: Mapped[int | None] = mapped_column(
        ForeignKey("brigades.id", ondelete="SET NULL"), index=True
    )
    classified_by: Mapped[str] = mapped_column(String(8))  # llm | rules | manual
    # Оценка трудоёмкости в часах работы и что из неё следует
    effort_hours: Mapped[Decimal | None] = mapped_column(Numeric(6, 1))
    complexity: Mapped[str] = mapped_column(
        _str_enum(Complexity), default=Complexity.simple, server_default="simple"
    )
    effort_by: Mapped[str | None] = mapped_column(String(8))  # llm | rules | manual
    # Этап крупной заявки: родитель закрывается, когда выполнены все этапы
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("incoming_requests.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(_str_enum(RequestStatus), default=RequestStatus.new)
    resolution: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Когда заявку поставили на паузу: при возобновлении срок сдвигается на время ожидания
    hold_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_reminder_on: Mapped[date | None] = mapped_column(Date)

    organization: Mapped[Organization] = relationship()
    building: Mapped[Building | None] = relationship()
    author: Mapped[User | None] = relationship(foreign_keys=[author_id])
    assignee: Mapped[User | None] = relationship(foreign_keys=[assignee_id])
    brigade: Mapped[Brigade | None] = relationship()
    parent: Mapped[IncomingRequest | None] = relationship(
        remote_side=[id], back_populates="children"
    )
    children: Mapped[list[IncomingRequest]] = relationship(
        back_populates="parent", order_by="IncomingRequest.id"
    )
    events: Mapped[list[RequestEvent]] = relationship(
        cascade="all, delete-orphan", order_by="RequestEvent.id"
    )


class RequestEvent(Base):
    """Лента заявки: комментарии людей и записи о том, что изменилось."""

    __tablename__ = "request_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(
        ForeignKey("incoming_requests.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(16))  # comment | status | assignee | deadline
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    author: Mapped[User | None] = relationship()


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    user_id: Mapped[int | None]
    user_email: Mapped[str | None] = mapped_column(String(200))
    action: Mapped[str] = mapped_column(String(60))
    entity: Mapped[str | None] = mapped_column(String(60))
    entity_id: Mapped[str | None] = mapped_column(String(60))
    details: Mapped[dict | None] = mapped_column(JSONB)
    ip: Mapped[str | None] = mapped_column(String(64))
