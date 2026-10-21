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
    cleaner = "cleaner"  # уборщик учреждения: получает заявки по уборке своего учреждения


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


# --- нормативная численность ----------------------------------------------------------
# Только агрегаты: ставки по группам должностей, показатели учреждения и нормативы.
# Сотрудников, ФИО и окладов здесь нет.


class StaffCategory(enum.StrEnum):
    aup = "aup"  # административно-управленческий персонал
    support = "support"  # учебно-вспомогательный и обслуживающий персонал


class ScheduleStatus(enum.StrEnum):
    draft = "draft"
    approved = "approved"
    archived = "archived"


class AnalysisStatus(enum.StrEnum):
    deficit = "deficit"  # не хватает ставок
    surplus = "surplus"  # сверх норматива
    normal = "normal"  # в пределах допуска
    no_data = "no_data"  # не хватает данных для расчёта
    warning = "warning"  # норматив не настроен или отклонения по группам гасят друг друга


class PersonnelGroup(Base):
    """Группа нормирования: «Делопроизводство», «Уборка помещений» и т. п."""

    __tablename__ = "personnel_groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(60), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    top_category: Mapped[str] = mapped_column(_str_enum(StaffCategory, 16))
    subcategory: Mapped[str | None] = mapped_column(String(40))
    # Типы учреждений, для которых группа имеет смысл. Пусто — для всех
    institution_types: Mapped[list[str]] = mapped_column(JSONB, default=list)
    # Примеры должностей — подсказка, что относить к группе
    positions: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(default=True)
    sort_order: Mapped[int] = mapped_column(default=0)


class NormativeDocument(Base):
    """Документ-основание норматива. Хранятся только реквизиты, без файла."""

    __tablename__ = "normative_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(500))
    doc_type: Mapped[str] = mapped_column(String(40))  # закон, приказ, постановление, локальный акт
    number: Mapped[str | None] = mapped_column(String(60))
    issued_at: Mapped[date | None] = mapped_column(Date)
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    issuer: Mapped[str | None] = mapped_column(String(300))
    scope_level: Mapped[str] = mapped_column(String(16), default="region")
    # active | superseded | archived
    status: Mapped[str] = mapped_column(String(16), default="active")
    source_ref: Mapped[str | None] = mapped_column(String(500))


class NormativeCoefficient(Base):
    """Норматив: сколько ставок группы положено на единицу показателя учреждения.

    Ставки = показатель / unit_size * fte_per_unit, затем округление, минимум и максимум.
    Без unit_size — фиксированные fte_per_unit ставок. applies_from/applies_to ограничивают
    норматив значениями показателя: «1,25 ставки при числе учащихся от 801».
    """

    __tablename__ = "normative_coefficients"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("normative_documents.id", ondelete="RESTRICT"), index=True
    )
    personnel_group_id: Mapped[int] = mapped_column(
        ForeignKey("personnel_groups.id", ondelete="CASCADE"), index=True
    )
    institution_type: Mapped[str] = mapped_column(String(16), default="all")
    # region — весь регион, municipality / organization — местный норматив для scope_id
    scope_level: Mapped[str] = mapped_column(String(16), default="region")
    scope_id: Mapped[int | None]
    metric: Mapped[str] = mapped_column(String(32))
    unit_size: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    fte_per_unit: Mapped[Decimal] = mapped_column(Numeric(7, 2))
    min_fte: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    max_fte: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    applies_from: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    applies_to: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    rounding_step: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    rounding_mode: Mapped[str] = mapped_column(String(8), default="up")  # up | down | nearest
    tolerance_abs: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    tolerance_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    priority: Mapped[int] = mapped_column(default=0)
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    is_mandatory: Mapped[bool] = mapped_column(default=True)
    comment: Mapped[str | None] = mapped_column(String(500))

    document: Mapped[NormativeDocument | None] = relationship()
    group: Mapped[PersonnelGroup] = relationship()


class StaffingSchedule(Base):
    """Штатное расписание учреждения на учебный год — только итоги по группам."""

    __tablename__ = "staffing_schedules"
    __table_args__ = (Index("ux_staffing_schedule", "organization_id", "academic_year",
                            unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    academic_year: Mapped[str] = mapped_column(String(9))  # 2026/2027
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(_str_enum(ScheduleStatus, 16), default=ScheduleStatus.draft)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("normative_documents.id", ondelete="SET NULL")
    )
    comment: Mapped[str | None] = mapped_column(String(500))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    lines: Mapped[list[StaffingLine]] = relationship(
        cascade="all, delete-orphan", order_by="StaffingLine.id"
    )


class StaffingLine(Base):
    """Строка штатки — должность: утверждённые и занятые ставки, оклад. Должность входит
    в группу нормирования (уборщик и гардеробщик — «Уборка помещений»): норматив считается
    по группе, а сокращать и добавлять можно конкретные должности."""

    __tablename__ = "staffing_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_id: Mapped[int] = mapped_column(
        ForeignKey("staffing_schedules.id", ondelete="CASCADE"), index=True
    )
    personnel_group_id: Mapped[int] = mapped_column(
        ForeignKey("personnel_groups.id", ondelete="RESTRICT")
    )
    building_id: Mapped[int | None] = mapped_column(
        ForeignKey("buildings.id", ondelete="SET NULL")
    )
    # Название должности. Пусто — строка завели итогом по группе (старые данные, загрузка
    # без колонки «Должность»): показывается первая типовая должность группы
    position: Mapped[str | None] = mapped_column(String(200))
    approved_fte: Mapped[Decimal] = mapped_column(Numeric(7, 2), default=0)
    # Пусто — занятость не ведётся, анализ «по занятости» для группы невозможен
    occupied_fte: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    # Из занятых — совмещение и дополнительная нагрузка: эти ставки снимаются уменьшением
    # нагрузки, без увольнения
    combined_fte: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    # Средний оклад за одну ставку группы, ₽ в месяц. Итог по группе, не по людям
    salary_rub: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    comment: Mapped[str | None] = mapped_column(String(500))


class StaffingScheduleVersion(Base):
    """Снимок штатки после каждого изменения: по нему видно, как менялись ставки и ФОТ."""

    __tablename__ = "staffing_schedule_versions"
    __table_args__ = (Index("ix_schedule_versions_org_year", "organization_id", "academic_year"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_id: Mapped[int] = mapped_column(
        ForeignKey("staffing_schedules.id", ondelete="CASCADE"), index=True
    )
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    academic_year: Mapped[str] = mapped_column(String(9))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    source: Mapped[str] = mapped_column(String(16))  # manual | import | demo
    status: Mapped[str] = mapped_column(String(16))
    comment: Mapped[str | None] = mapped_column(String(500))
    # [{group_id, approved, occupied, salary}]
    lines: Mapped[list[dict]] = mapped_column(JSONB, default=list)
    approved_fte: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    occupied_fte: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    payroll_approved: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    payroll_occupied: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))

    author: Mapped[User | None] = relationship()


class InstitutionMetrics(Base):
    """Показатели учреждения, от которых считаются нормативы."""

    __tablename__ = "institution_metrics"
    __table_args__ = (Index("ux_institution_metrics", "organization_id", "academic_year",
                            unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    academic_year: Mapped[str] = mapped_column(String(9))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    students_count: Mapped[int | None]
    classes_count: Mapped[int | None]
    groups_count: Mapped[int | None]
    total_area_m2: Mapped[Decimal | None] = mapped_column(Numeric(10, 1))
    # Кабинеты и другие помещения, которые убирают: «1 уборщик на 30 кабинетов»
    rooms_count: Mapped[int | None]
    # Сколько ставок уборщиц и своего хозотдела в школе сейчас — для простых расчётов
    cleaners_fte: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    maintenance_fte: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    source: Mapped[str] = mapped_column(String(16), default="manual")  # manual | import | external
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StaffingAnalysisResult(Base):
    """Результат расчёта на дату. Строка без группы — итог по категории.

    Хранится вместе со снимком нормативов и показателей: заявка, связанная с расчётом,
    показывает ту картину, что была при её создании, даже если норматив потом поменяли.
    """

    __tablename__ = "staffing_analysis_results"
    __table_args__ = (Index("ix_staffing_results_current", "academic_year", "is_current",
                            "basis", "top_category"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    personnel_group_id: Mapped[int | None] = mapped_column(
        ForeignKey("personnel_groups.id", ondelete="SET NULL")
    )
    top_category: Mapped[str] = mapped_column(String(16))
    academic_year: Mapped[str] = mapped_column(String(9))
    period_date: Mapped[date] = mapped_column(Date)
    basis: Mapped[str] = mapped_column(String(16))  # approved | occupied
    required_fte: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    approved_fte: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    occupied_fte: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    fact_fte: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    deviation_fte: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    deviation_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 1))
    status: Mapped[str] = mapped_column(_str_enum(AnalysisStatus, 16))
    severity: Mapped[str | None] = mapped_column(String(8))  # low | medium | high
    missing_reasons: Mapped[list[str]] = mapped_column(JSONB, default=list)
    coefficients_snapshot: Mapped[list[dict]] = mapped_column(JSONB, default=list)
    metrics_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Последний расчёт. Прежние строки остаются, только если на них ссылаются заявки
    is_current: Mapped[bool] = mapped_column(default=True)

    group: Mapped[PersonnelGroup | None] = relationship()


class RequestStaffingLink(Base):
    """Связь заявки с результатом нормативного анализа."""

    __tablename__ = "request_staffing_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(
        ForeignKey("incoming_requests.id", ondelete="CASCADE"), index=True
    )
    analysis_result_id: Mapped[int] = mapped_column(
        ForeignKey("staffing_analysis_results.id", ondelete="CASCADE"), index=True
    )
    link_type: Mapped[str] = mapped_column(String(16))  # deficit | surplus | no_data | question
    created_by: Mapped[str] = mapped_column(String(8))  # system | user
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    result: Mapped[StaffingAnalysisResult] = relationship()


class AssistantChat(Base):
    """Разговор с помощником по штатке. Виден только своему автору."""

    __tablename__ = "assistant_chats"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    academic_year: Mapped[str] = mapped_column(String(9))
    # Разговор про одно учреждение. Пусто — про всю территорию пользователя
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    organization: Mapped[Organization | None] = relationship()
    messages: Mapped[list[AssistantMessage]] = relationship(
        cascade="all, delete-orphan", order_by="AssistantMessage.id"
    )


class AssistantMessage(Base):
    __tablename__ = "assistant_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(
        ForeignKey("assistant_chats.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# --- программа оптимизации штатных расписаний (факт по документам) ---------------------


class ProgramSchool(Base):
    """Сколько ставок высвободила школа и за счёт чего — из расчёта управления."""

    __tablename__ = "program_schools"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), unique=True
    )
    sort_order: Mapped[int] = mapped_column(default=0)
    total: Mapped[Decimal] = mapped_column(Numeric(9, 3), default=0)
    vacancies: Mapped[Decimal] = mapped_column(Numeric(9, 3), default=0)
    load_reduction: Mapped[Decimal] = mapped_column(Numeric(9, 3), default=0)
    resignations: Mapped[Decimal] = mapped_column(Numeric(9, 3), default=0)
    layoffs: Mapped[Decimal] = mapped_column(Numeric(9, 3), default=0)
    hours: Mapped[int] = mapped_column(default=0)
    staff_units: Mapped[int] = mapped_column(default=0)  # «шт. ед.» в паспорте
    orders_note: Mapped[str | None] = mapped_column(String(500))

    organization: Mapped[Organization] = relationship()


class ProgramPosition(Base):
    """Строка расчёта по должностям: было, сократили, стало и экономия в месяц."""

    __tablename__ = "program_positions"

    id: Mapped[int] = mapped_column(primary_key=True)
    sort_order: Mapped[int] = mapped_column(default=0)
    category: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(200))
    before_fte: Mapped[Decimal] = mapped_column(Numeric(10, 3), default=0)
    cut_fte: Mapped[Decimal] = mapped_column(Numeric(10, 3), default=0)
    after_fte: Mapped[Decimal] = mapped_column(Numeric(10, 3), default=0)
    local_cut: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    local_economy_month: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    regional_cut: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    regional_economy_month: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))


class Dismissal(Base):
    """Уволенный по программе сотрудник: кто, откуда, на основании какого приказа."""

    __tablename__ = "dismissals"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    full_name: Mapped[str] = mapped_column(String(200))
    position: Mapped[str] = mapped_column(String(300))
    fte: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=1)
    basis: Mapped[str] = mapped_column(String(16))  # own — по собственному, layoff — сокращение
    article: Mapped[str | None] = mapped_column(String(200))
    order_number: Mapped[str | None] = mapped_column(String(60))
    order_date: Mapped[date | None] = mapped_column(Date)
    dismissed_on: Mapped[date | None] = mapped_column(Date)
    notified_on: Mapped[date | None] = mapped_column(Date)  # уведомление о сокращении
    note: Mapped[str | None] = mapped_column(String(500))
    source: Mapped[str | None] = mapped_column(String(300))  # файл приказа
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Учтено в штатке: в какой строке и на сколько уменьшили «занято» (и совмещение).
    # Пусто — увольнение в штатке не учтено (например, загружено из документов «до»)
    line_id: Mapped[int | None] = mapped_column(
        ForeignKey("staffing_lines.id", ondelete="SET NULL")
    )
    applied_fte: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    applied_combined: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))

    organization: Mapped[Organization] = relationship()
    line: Mapped[StaffingLine | None] = relationship()


class AppSetting(Base):
    """Настройки, которые меняют в интерфейсе: например, нормы загрузки хозслужбы."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


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
