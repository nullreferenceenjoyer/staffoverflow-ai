from __future__ import annotations

from datetime import datetime

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
