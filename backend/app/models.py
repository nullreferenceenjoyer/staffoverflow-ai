from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
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


class OrgType(enum.StrEnum):
    school = "school"
    preschool = "preschool"
    complex = "complex"  # школа с дошкольными группами


class Category(enum.StrEnum):
    teaching = "teaching"
    admin = "admin"  # АУП
    support = "support"  # ВП
    medical = "medical"


class Level(enum.StrEnum):
    preschool = "preschool"
    primary = "primary"  # 1–4
    basic = "basic"  # 5–9
    secondary = "secondary"  # 10–11


class StudyForm(enum.StrEnum):
    full_time = "full_time"
    distance = "distance"
    home = "home"


class ProjectStatus(enum.StrEnum):
    draft = "draft"
    review = "review"
    approved = "approved"
    rejected = "rejected"
    implemented = "implemented"


class TaskStatus(enum.StrEnum):
    waiting = "waiting"  # ждёт завершения предыдущего шага
    todo = "todo"
    in_progress = "in_progress"
    done = "done"


Money = Numeric(14, 2)
Rate = Numeric(8, 2)


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

    municipality: Mapped[Municipality] = relationship(back_populates="organizations")
    buildings: Mapped[list[Building]] = relationship(cascade="all, delete-orphan")
    enrollments: Mapped[list[Enrollment]] = relationship(cascade="all, delete-orphan")
    positions: Mapped[list[StaffPosition]] = relationship(cascade="all, delete-orphan")


class Building(Base):
    __tablename__ = "buildings"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    area_sqm: Mapped[Decimal] = mapped_column(Numeric(10, 1))
    floors: Mapped[int] = mapped_column(default=1)
    year_built: Mapped[int | None]
    condition: Mapped[str] = mapped_column(String(32), default="satisfactory")


class Enrollment(Base):
    """Контингент: одна строка на учебный год, ступень и форму обучения."""

    __tablename__ = "enrollments"
    __table_args__ = (
        UniqueConstraint("organization_id", "academic_year", "level", "study_form"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    academic_year: Mapped[int]  # год начала: 2026 означает 2026/27
    level: Mapped[str] = mapped_column(_str_enum(Level))
    study_form: Mapped[str] = mapped_column(_str_enum(StudyForm), default=StudyForm.full_time)
    classes_count: Mapped[int] = mapped_column(default=0)  # для ДОУ — число групп
    students_count: Mapped[int] = mapped_column(default=0)
    special_needs_count: Mapped[int] = mapped_column(default=0)  # дети с ОВЗ


class StaffPosition(Base):
    """Строка фактического штатного расписания."""

    __tablename__ = "staff_positions"
    __table_args__ = (Index("ix_staff_org_function", "organization_id", "function_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    department: Mapped[str | None] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(_str_enum(Category))
    function_code: Mapped[str] = mapped_column(String(40))
    rate: Mapped[Decimal] = mapped_column(Rate)
    monthly_pay: Mapped[Decimal] = mapped_column(Money, default=0)  # начисления по строке
    # Хэш сотрудника; None — вакансия. Исходные ФИО в систему не попадают.
    employee_ref: Mapped[str | None] = mapped_column(String(32))
    weekly_hours: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    duties: Mapped[str | None] = mapped_column(Text)


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(400))
    doc_type: Mapped[str] = mapped_column(String(40), default="npa")
    source_ref: Mapped[str | None] = mapped_column(String(400))
    file_path: Mapped[str | None] = mapped_column(String(400))
    # Краткая справка, написанная своими словами, а не официальный текст документа
    is_summary: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    chunks: Mapped[list[KnowledgeChunk]] = relationship(
        cascade="all, delete-orphan", order_by="KnowledgeChunk.ordinal"
    )


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True
    )
    ordinal: Mapped[int]
    content: Mapped[str] = mapped_column(Text)
    # Размерность не фиксируем: она зависит от выбранного эмбеддера
    embedding: Mapped[list[float] | None] = mapped_column(Vector())


class Norm(Base):
    """Норматив численности или надбавка.

    Значение считается как base + per_unit * driver / unit_size, затем
    ограничивается min/max и округляется до шага rounding.
    """

    __tablename__ = "norms"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(60), unique=True)
    title: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(16), default="staff")  # staff | allowance
    function_code: Mapped[str] = mapped_column(String(40))
    org_types: Mapped[list[str]] = mapped_column(JSONB, default=list)
    driver: Mapped[str] = mapped_column(String(40))
    unit_size: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=1)
    per_unit: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    base: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    threshold: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    min_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    max_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    rounding: Mapped[Decimal] = mapped_column(Numeric(4, 2), default=Decimal("0.25"))
    # Доля экономии при передаче функции в общий центр/бригаду (0 — не централизуется)
    centralization_effect: Mapped[Decimal] = mapped_column(Numeric(4, 2), default=0)
    source_kind: Mapped[str] = mapped_column(String(16), default="assumption")
    legal_ref: Mapped[str | None] = mapped_column(String(500))
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="SET NULL")
    )
    is_active: Mapped[bool] = mapped_column(default=True)

    document: Mapped[KnowledgeDocument | None] = relationship()


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True)
    full_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(_str_enum(Role))
    municipality_id: Mapped[int | None] = mapped_column(ForeignKey("municipalities.id"))
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"))
    is_active: Mapped[bool] = mapped_column(default=True)
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    max_chat_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(24))  # normalization | centralization
    status: Mapped[str] = mapped_column(_str_enum(ProjectStatus), default=ProjectStatus.draft)
    municipality_id: Mapped[int] = mapped_column(ForeignKey("municipalities.id"), index=True)
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    summary: Mapped[str | None] = mapped_column(Text)
    rate_delta: Mapped[Decimal] = mapped_column(Rate, default=0)
    fot_effect_year: Mapped[Decimal] = mapped_column(Money, default=0)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    items: Mapped[list[ProjectItem]] = relationship(
        cascade="all, delete-orphan", order_by="ProjectItem.id"
    )
    documents: Mapped[list[GeneratedDocument]] = relationship(cascade="all, delete-orphan")
    municipality: Mapped[Municipality] = relationship()
    organization: Mapped[Organization | None] = relationship()


class ProjectItem(Base):
    __tablename__ = "project_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    organization_name: Mapped[str] = mapped_column(String(300))
    function_code: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(_str_enum(Category))
    current_rate: Mapped[Decimal] = mapped_column(Rate)
    proposed_rate: Mapped[Decimal] = mapped_column(Rate)
    fot_effect_year: Mapped[Decimal] = mapped_column(Money, default=0)
    # Какая часть сокращения приходится на вакансии, то есть не затрагивает работников
    vacant_rate: Mapped[Decimal] = mapped_column(Rate, default=0, server_default="0")
    reason: Mapped[str] = mapped_column(Text)


class GeneratedDocument(Base):
    __tablename__ = "generated_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(24))  # order | memo | justification
    title: Mapped[str] = mapped_column(String(300))
    narrative: Mapped[str] = mapped_column(Text)
    file_path: Mapped[str] = mapped_column(String(400))
    written_by_llm: Mapped[bool] = mapped_column(default=False)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Program(Base):
    """Паспорт проекта: цель по ФОТ АУП и ВП, план и исходная точка."""

    __tablename__ = "programs"

    id: Mapped[int] = mapped_column(primary_key=True)
    municipality_id: Mapped[int] = mapped_column(ForeignKey("municipalities.id"), unique=True)
    title: Mapped[str] = mapped_column(String(400))
    description: Mapped[str | None] = mapped_column(Text)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    target_fot_cut_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    # {"admin": {"rates": .., "dismissals": ..}, "support": {...}, "saving_year": ..,
    #  "hours_per_rate": 1972}
    plan: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Снимок ставок и ФОТ на старте проекта; от него считается достигнутое сокращение
    baseline: Mapped[dict | None] = mapped_column(JSONB)
    baseline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    municipality: Mapped[Municipality] = relationship()
    milestones: Mapped[list[Milestone]] = relationship(
        cascade="all, delete-orphan", order_by="Milestone.ordinal"
    )


class Milestone(Base):
    """Мероприятие дорожной карты паспорта."""

    __tablename__ = "milestones"

    id: Mapped[int] = mapped_column(primary_key=True)
    program_id: Mapped[int] = mapped_column(ForeignKey("programs.id", ondelete="CASCADE"))
    ordinal: Mapped[int]
    title: Mapped[str] = mapped_column(String(400))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    responsible: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(16), default="planned")  # planned|in_progress|done


class DigitalTool(Base):
    """Цифровой инструмент, который берёт на себя функцию при сокращении ставки АУП."""

    __tablename__ = "digital_tools"

    id: Mapped[int] = mapped_column(primary_key=True)
    function_code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    # Доля функционала ставки, которую закрывает инструмент; None — ещё не оценивали
    coverage_pct: Mapped[int | None]


class WorkflowTemplate(Base):
    __tablename__ = "workflow_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    # [{"title": str, "role": Role, "duration_days": int}, ...] в порядке выполнения
    steps: Mapped[list[dict]] = mapped_column(JSONB, default=list)


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (Index("ix_tasks_status_due", "status", "due_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    # Задачи одного запуска сценария; порядок внутри запуска задаёт step_index
    run_id: Mapped[str | None] = mapped_column(String(32), index=True)
    step_index: Mapped[int] = mapped_column(default=0)
    title: Mapped[str] = mapped_column(String(300))
    assignee_role: Mapped[str] = mapped_column(_str_enum(Role))
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # Нужна для разграничения доступа: задача видна тем же, кому виден муниципалитет
    municipality_id: Mapped[int | None] = mapped_column(ForeignKey("municipalities.id"))
    status: Mapped[str] = mapped_column(_str_enum(TaskStatus), default=TaskStatus.todo)
    duration_days: Mapped[int] = mapped_column(default=3)
    due_date: Mapped[date | None] = mapped_column(Date)
    last_reminder_on: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    project: Mapped[Project | None] = relationship()
    assignee: Mapped[User | None] = relationship()


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_to_telegram: Mapped[bool] = mapped_column(default=False)
    sent_to_max: Mapped[bool] = mapped_column(default=False, server_default="false")


class IncomingRequest(Base):
    """Обращение от ОУ («нужна ставка логопеда»), которое надо направить специалисту."""

    __tablename__ = "incoming_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    text: Mapped[str] = mapped_column(Text)
    topic: Mapped[str] = mapped_column(String(40))
    routed_role: Mapped[str] = mapped_column(_str_enum(Role))
    classified_by: Mapped[str] = mapped_column(String(8))  # llm | rules
    status: Mapped[str] = mapped_column(String(16), default="new")  # new | in_progress | closed
    resolution: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    organization: Mapped[Organization] = relationship()


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
