from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, PlainSerializer

from app.models import Category, Level, OrgType, ProjectStatus, Role, StudyForm, TaskStatus

# В БД числа лежат в Decimal, а в JSON отдаём обычные числа, а не строки
Num = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]


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
    is_active: bool
    telegram_chat_id: int | None
    max_chat_id: int | None


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=200)
    password: str = Field(min_length=8, max_length=72)
    role: Role
    municipality_id: int | None = None
    organization_id: int | None = None
    telegram_chat_id: int | None = None
    max_chat_id: int | None = None


class UserUpdate(BaseModel):
    full_name: str | None = Field(None, min_length=2, max_length=200)
    password: str | None = Field(None, min_length=8, max_length=72)
    role: Role | None = None
    municipality_id: int | None = None
    organization_id: int | None = None
    is_active: bool | None = None
    telegram_chat_id: int | None = None
    max_chat_id: int | None = None


class MunicipalityOut(ORMModel):
    id: int
    name: str


class OrganizationIn(BaseModel):
    name: str = Field(min_length=2, max_length=300)
    municipality_id: int
    org_type: OrgType
    address: str | None = None
    external_id: str | None = None


class BuildingIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    area_sqm: Num = Field(gt=0)
    floors: int = Field(1, ge=1, le=30)
    year_built: int | None = Field(None, ge=1800, le=2100)
    condition: str = "satisfactory"


class BuildingOut(ORMModel, BuildingIn):
    id: int


class EnrollmentIn(BaseModel):
    academic_year: int = Field(ge=2000, le=2100)
    level: Level
    study_form: StudyForm = StudyForm.full_time
    classes_count: int = Field(0, ge=0)
    students_count: int = Field(0, ge=0)
    special_needs_count: int = Field(0, ge=0)


class EnrollmentOut(ORMModel, EnrollmentIn):
    id: int


class PositionIn(BaseModel):
    department: str | None = None
    title: str = Field(min_length=2, max_length=200)
    rate: Num = Field(gt=0, le=3)
    monthly_pay: Num = Field(0, ge=0)
    weekly_hours: Num | None = Field(None, ge=0, le=80)
    duties: str | None = None
    # Если не задано, функция определяется по названию должности
    function_code: str | None = None
    is_vacant: bool = False


class PositionOut(ORMModel):
    id: int
    department: str | None
    title: str
    category: Category
    function_code: str
    rate: Num
    monthly_pay: Num
    weekly_hours: Num | None
    duties: str | None
    employee_ref: str | None


class NormIn(BaseModel):
    code: str = Field(min_length=2, max_length=60, pattern=r"^[a-z0-9_]+$")
    title: str = Field(min_length=2, max_length=300)
    kind: str = Field("staff", pattern="^(staff|allowance)$")
    function_code: str
    org_types: list[OrgType] = []
    driver: str
    unit_size: Num = Field(1, gt=0)
    per_unit: Num = Decimal(0)
    base: Num = Decimal(0)
    threshold: Num = Field(Decimal(0), ge=0)
    min_value: Num | None = None
    max_value: Num | None = None
    rounding: Num = Field(Decimal("0.25"), ge=0)
    centralization_effect: Num = Field(Decimal(0), ge=0, lt=1)
    source_kind: str = Field("assumption", pattern="^(federal|regional|assumption)$")
    legal_ref: str | None = None
    document_id: int | None = None
    is_active: bool = True


class NormOut(ORMModel, NormIn):
    id: int


class ProjectItemOut(ORMModel):
    id: int
    organization_id: int | None
    organization_name: str
    function_code: str
    title: str
    category: Category
    current_rate: Num
    proposed_rate: Num
    fot_effect_year: Num
    vacant_rate: Num
    reason: str


class DocumentOut(ORMModel):
    id: int
    kind: str
    title: str
    narrative: str
    written_by_llm: bool
    created_at: datetime


class ProjectOut(ORMModel):
    id: int
    title: str
    kind: str
    status: ProjectStatus
    municipality_id: int
    organization_id: int | None
    summary: str | None
    rate_delta: Num
    fot_effect_year: Num
    created_at: datetime
    decided_at: datetime | None


class ProjectDetail(ProjectOut):
    items: list[ProjectItemOut]
    documents: list[DocumentOut]


class ProjectGenerate(BaseModel):
    kind: str = Field(pattern="^(normalization|centralization)$")
    organization_id: int | None = None
    municipality_id: int | None = None


class ProjectStatusChange(BaseModel):
    status: ProjectStatus


class DocumentGenerate(BaseModel):
    kind: str = Field(pattern="^(order|memo|justification)$")


class WorkflowStep(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    role: Role
    duration_days: int = Field(3, ge=1, le=180)


class WorkflowTemplateIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    description: str | None = None
    steps: list[WorkflowStep] = Field(min_length=1, max_length=30)


class WorkflowTemplateOut(ORMModel, WorkflowTemplateIn):
    id: int


class WorkflowStart(BaseModel):
    project_id: int | None = None
    municipality_id: int | None = None
    start_date: date | None = None


class TaskIn(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    assignee_role: Role
    assignee_id: int | None = None
    project_id: int | None = None
    municipality_id: int | None = None
    due_date: date | None = None


class TaskUpdate(BaseModel):
    status: TaskStatus | None = None
    assignee_id: int | None = None
    due_date: date | None = None


class TaskOut(ORMModel):
    id: int
    project_id: int | None
    run_id: str | None
    step_index: int
    title: str
    assignee_role: Role
    assignee_id: int | None
    municipality_id: int | None
    status: TaskStatus
    due_date: date | None
    completed_at: datetime | None


class NotificationOut(ORMModel):
    id: int
    text: str
    task_id: int | None
    created_at: datetime
    read_at: datetime | None


class RequestIn(BaseModel):
    text: str = Field(min_length=10, max_length=4000)
    organization_id: int | None = None


class RequestUpdate(BaseModel):
    status: str | None = Field(None, pattern="^(new|in_progress|closed)$")
    resolution: str | None = None
    routed_role: Role | None = None


class RequestOut(ORMModel):
    id: int
    organization_id: int
    text: str
    topic: str
    routed_role: Role
    classified_by: str
    status: str
    resolution: str | None
    created_at: datetime


class ChatMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    history: list[ChatMessage] = []
