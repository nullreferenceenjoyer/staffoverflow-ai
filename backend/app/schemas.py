from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.models import OrgType, RequestKind, RequestStatus, Role


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(ORMModel):
    id: int
    email: str
    full_name: str
    role: Role
    municipality_id: int | None
    organization_id: int | None
    brigade_id: int | None
    is_active: bool


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=200)
    password: str = Field(min_length=8, max_length=72)
    role: Role
    municipality_id: int | None = None
    organization_id: int | None = None
    brigade_id: int | None = None


class UserUpdate(BaseModel):
    full_name: str | None = Field(None, min_length=2, max_length=200)
    password: str | None = Field(None, min_length=8, max_length=72)
    role: Role | None = None
    municipality_id: int | None = None
    organization_id: int | None = None
    brigade_id: int | None = None
    is_active: bool | None = None


class MunicipalityOut(ORMModel):
    id: int
    name: str


class OrganizationOut(ORMModel):
    id: int
    name: str
    municipality_id: int


class BuildingItem(BaseModel):
    id: int | None = None  # пусто — новый корпус
    name: str = Field(min_length=1, max_length=200)
    address: str | None = Field(None, max_length=300)


class OrganizationIn(BaseModel):
    name: str = Field(min_length=2, max_length=300)
    # Название муниципалитета: если такого нет, он будет создан
    municipality: str = Field(min_length=2, max_length=200)
    org_type: OrgType = OrgType.school
    address: str | None = Field(None, max_length=300)
    external_id: str | None = Field(None, max_length=64)
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    buildings: list[BuildingItem] = Field(default_factory=list, max_length=30)


class BrigadeIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    municipality_id: int | None = None
    base_address: str | None = Field(None, max_length=300)
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    # Темы, которые берёт бригада. Пусто — все хозяйственные
    topics: list[str] = Field(default_factory=list)
    is_active: bool = True
    member_ids: list[int] = Field(default_factory=list)


class BrigadeSchools(BaseModel):
    organization_ids: list[int] = Field(default_factory=list, max_length=2000)


class NotificationOut(ORMModel):
    id: int
    text: str
    request_id: int | None
    created_at: datetime
    read_at: datetime | None


class RequestIn(BaseModel):
    title: str = Field("", max_length=200)
    text: str = Field("", max_length=4000)
    kind: RequestKind = RequestKind.planned
    # Не задана — тему определит система по тексту
    topic: str | None = None
    organization_id: int | None = None
    building_id: int | None = None
    location: str | None = Field(None, max_length=200)

    @model_validator(mode="after")
    def _has_content(self):
        self.title, self.text = self.title.strip(), self.text.strip()
        if len(self.title or self.text) < 5:
            raise ValueError("Опишите, что нужно сделать")
        return self


class RequestUpdate(BaseModel):
    assignee_id: int | None = None
    # Передать бригаде: заявку возьмёт любой её участник
    brigade_id: int | None = None
    due_at: datetime | None = None
    kind: RequestKind | None = None
    topic: str | None = None
    effort_hours: float | None = Field(None, ge=0.5, le=500)


class RequestStage(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    hours: float | None = Field(None, ge=0.5, le=500)


class RequestSplit(BaseModel):
    stages: list[RequestStage] = Field(min_length=2, max_length=12)


class RequestStatusChange(BaseModel):
    status: RequestStatus
    comment: str | None = Field(None, max_length=4000)


class RequestComment(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    # Вопрос заявителю: заявка встаёт на паузу до его ответа
    needs_reply: bool = False


# --- нормативная численность ---------------------------------------------------------

Category = Literal["aup", "support"]
Basis = Literal["occupied", "approved"]


class StaffingLineIn(BaseModel):
    group_id: int
    approved_fte: float | None = Field(None, ge=0, le=500)
    occupied_fte: float | None = Field(None, ge=0, le=500)
    # Средний оклад за ставку, ₽ в месяц
    salary_rub: float | None = Field(None, gt=0, le=10_000_000)


class StaffingDataIn(BaseModel):
    """Штатка, занятость и показатели учреждения за учебный год — одним сохранением."""

    year: str = Field(pattern=r"^\d{4}/\d{4}$")
    students_count: int | None = Field(None, ge=0, le=100_000)
    classes_count: int | None = Field(None, ge=0, le=2_000)
    groups_count: int | None = Field(None, ge=0, le=2_000)
    total_area_m2: float | None = Field(None, ge=0, le=1_000_000)
    lines: list[StaffingLineIn] = Field(default_factory=list, max_length=100)
    status: Literal["draft", "approved"] = "draft"
    comment: str | None = Field(None, max_length=500)


class RecalculateIn(BaseModel):
    year: str = Field(pattern=r"^\d{4}/\d{4}$")
    organization_id: int | None = None


class StaffingRequestIn(BaseModel):
    organization_id: int
    year: str = Field(pattern=r"^\d{4}/\d{4}$")
    category: Category
    basis: Basis = "occupied"
    group_id: int | None = None
    # Пусто — текст по шаблону; заполненные — то, что человек поправил в предпросмотре
    title: str | None = Field(None, max_length=200)
    text: str | None = Field(None, max_length=4000)


class NormDocumentIn(BaseModel):
    title: str = Field(min_length=3, max_length=500)
    doc_type: str = Field(min_length=2, max_length=40)
    number: str | None = Field(None, max_length=60)
    issued_at: date | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    issuer: str | None = Field(None, max_length=300)
    scope_level: Literal["region", "municipality", "organization"] = "region"
    status: Literal["active", "superseded", "archived"] = "active"
    source_ref: str | None = Field(None, max_length=500)

    @model_validator(mode="after")
    def _dates(self):
        if self.effective_from and self.effective_to and self.effective_from > self.effective_to:
            raise ValueError("«Действует с» позже, чем «Действует до»")
        return self


class NormCoefficientIn(BaseModel):
    group_id: int
    document_id: int | None = None
    institution_type: Literal["all", "school", "preschool", "complex"] = "all"
    scope_level: Literal["region", "municipality", "organization"] = "region"
    scope_id: int | None = None
    metric: Literal["students_count", "classes_count", "groups_count", "total_area_m2", "none"]
    unit_size: float | None = Field(None, gt=0, le=1_000_000)
    fte_per_unit: float = Field(ge=0, le=500)
    min_fte: float | None = Field(None, ge=0, le=500)
    max_fte: float | None = Field(None, ge=0, le=500)
    applies_from: float | None = Field(None, ge=0)
    applies_to: float | None = Field(None, ge=0)
    rounding_step: float | None = Field(None, gt=0, le=10)
    rounding_mode: Literal["up", "down", "nearest"] = "up"
    tolerance_abs: float | None = Field(None, ge=0, le=50)
    tolerance_pct: float | None = Field(None, ge=0, le=100)
    priority: int = Field(0, ge=-100, le=100)
    effective_from: date | None = None
    effective_to: date | None = None
    is_mandatory: bool = True
    comment: str | None = Field(None, max_length=500)

    @model_validator(mode="after")
    def _consistent(self):
        if self.metric == "none" and (self.unit_size or self.applies_from is not None
                                      or self.applies_to is not None):
            raise ValueError("Без показателя нельзя задать «на сколько единиц» и диапазон")
        if (self.min_fte is not None and self.max_fte is not None
                and self.min_fte > self.max_fte):
            raise ValueError("Минимум ставок больше максимума")
        if (self.applies_from is not None and self.applies_to is not None
                and self.applies_from > self.applies_to):
            raise ValueError("Диапазон показателя задан наоборот")
        if self.effective_from and self.effective_to and self.effective_from > self.effective_to:
            raise ValueError("«Действует с» позже, чем «Действует до»")
        if self.scope_level == "region":
            self.scope_id = None
        elif self.scope_id is None:
            raise ValueError("Для местного норматива укажите муниципалитет или учреждение")
        return self


class AssistantAskIn(BaseModel):
    # Пусто — новый разговор: про учреждение organization_id или про всю территорию
    chat_id: int | None = None
    year: str | None = Field(None, pattern=r"^\d{4}/\d{4}$")
    organization_id: int | None = None
    question: str = Field(min_length=2, max_length=2000)
