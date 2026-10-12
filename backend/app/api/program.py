from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import PLANNERS, Scope, audit, get_current_user, get_scope, require_roles
from app.models import DigitalTool, Milestone, Program, User
from app.schemas import Num, ORMModel
from app.services import program as program_service
from app.services.functions import BY_CODE, function_title

router = APIRouter(tags=["program"])


class CategoryPlan(BaseModel):
    rates: float = Field(0, ge=0)
    dismissals: float = Field(0, ge=0)


class ProgramPlan(BaseModel):
    admin: CategoryPlan = CategoryPlan()
    support: CategoryPlan = CategoryPlan()
    saving_year: float = Field(0, ge=0)
    hours_per_rate: float = Field(program_service.DEFAULT_HOURS_PER_RATE, gt=0)


class ProgramIn(BaseModel):
    municipality_id: int
    title: str = Field(min_length=3, max_length=400)
    description: str | None = None
    start_date: date
    end_date: date
    target_fot_cut_pct: Num = Field(gt=0, le=100)
    plan: ProgramPlan = ProgramPlan()


class MilestoneIn(BaseModel):
    title: str = Field(min_length=3, max_length=400)
    start_date: date
    end_date: date
    responsible: str | None = Field(None, max_length=300)
    status: str = Field("planned", pattern="^(planned|in_progress|done)$")


class MilestoneOut(ORMModel, MilestoneIn):
    id: int
    ordinal: int


class DigitalToolIn(BaseModel):
    name: str = Field(min_length=2, max_length=300)
    description: str | None = None
    coverage_pct: int | None = Field(None, ge=0, le=100)


def _editable(scope: Scope, program: Program) -> None:
    if not scope.can_see_municipality(program.municipality_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Нет доступа к паспорту")


def _get(scope: Scope) -> Program:
    program = program_service.find_visible(scope.db, scope)
    if program is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Паспорт проекта не заведён")
    return program


@router.get("/program")
def get_program(scope: Scope = Depends(get_scope)):
    program = _get(scope)
    reports = program_service.program_reports(scope.db, program)
    return {
        "id": program.id,
        "municipality_id": program.municipality_id,
        "municipality": program.municipality.name,
        "title": program.title,
        "description": program.description,
        "start_date": program.start_date,
        "end_date": program.end_date,
        "target_fot_cut_pct": float(program.target_fot_cut_pct),
        "plan": ProgramPlan.model_validate(program.plan or {}),
        "scoreboard": program_service.scoreboard(program, reports),
        "milestones": [MilestoneOut.model_validate(m) for m in program.milestones],
    }


@router.put("/program")
def save_program(body: ProgramIn, request: Request,
                 user: User = Depends(require_roles(*PLANNERS)),
                 scope: Scope = Depends(get_scope)):
    """Создаёт паспорт муниципалитета или обновляет существующий."""
    if not scope.can_see_municipality(body.municipality_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Нет доступа к муниципалитету")
    if body.end_date <= body.start_date:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Срок завершения должен быть позже даты начала")
    db = scope.db
    program = db.scalar(select(Program).where(Program.municipality_id == body.municipality_id))
    if program is None:
        program = Program(municipality_id=body.municipality_id)
        db.add(program)
    for key, value in body.model_dump(exclude={"municipality_id"}).items():
        setattr(program, key, value)
    db.flush()
    audit(db, user, "program_saved", entity="program", entity_id=program.id, request=request)
    db.commit()
    return {"id": program.id}


@router.post("/program/baseline")
def fix_baseline(request: Request, user: User = Depends(require_roles(*PLANNERS)),
                 scope: Scope = Depends(get_scope)):
    """Запоминает текущие ставки и ФОТ как исходную точку проекта."""
    program = _get(scope)
    _editable(scope, program)
    program_service.fix_baseline(program, program_service.program_reports(scope.db, program))
    audit(scope.db, user, "program_baseline_fixed", entity="program", entity_id=program.id,
          details=program.baseline, request=request)
    scope.db.commit()
    return {"baseline_at": program.baseline_at}


@router.post("/program/milestones", response_model=MilestoneOut,
             status_code=status.HTTP_201_CREATED)
def add_milestone(body: MilestoneIn, request: Request,
                  user: User = Depends(require_roles(*PLANNERS)),
                  scope: Scope = Depends(get_scope)):
    program = _get(scope)
    _editable(scope, program)
    milestone = Milestone(program_id=program.id, ordinal=len(program.milestones) + 1,
                          **body.model_dump())
    scope.db.add(milestone)
    audit(scope.db, user, "milestone_added", entity="program", entity_id=program.id,
          request=request)
    scope.db.commit()
    return milestone


@router.put("/program/milestones/{milestone_id}", response_model=MilestoneOut)
def update_milestone(milestone_id: int, body: MilestoneIn, request: Request,
                     user: User = Depends(require_roles(*PLANNERS)),
                     scope: Scope = Depends(get_scope)):
    program = _get(scope)
    _editable(scope, program)
    milestone = next((m for m in program.milestones if m.id == milestone_id), None)
    if milestone is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Мероприятие не найдено")
    for key, value in body.model_dump().items():
        setattr(milestone, key, value)
    audit(scope.db, user, "milestone_updated", entity="milestone", entity_id=milestone.id,
          details={"status": body.status}, request=request)
    scope.db.commit()
    return milestone


@router.delete("/program/milestones/{milestone_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_milestone(milestone_id: int, request: Request,
                     user: User = Depends(require_roles(*PLANNERS)),
                     scope: Scope = Depends(get_scope)):
    program = _get(scope)
    _editable(scope, program)
    milestone = next((m for m in program.milestones if m.id == milestone_id), None)
    if milestone is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Мероприятие не найдено")
    scope.db.delete(milestone)
    audit(scope.db, user, "milestone_deleted", entity="program", entity_id=program.id,
          request=request)
    scope.db.commit()


# --- цифровые инструменты, замещающие функции АУП ------------------------------------


@router.get("/digital-tools")
def list_tools(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    tools = db.scalars(select(DigitalTool)).all()
    return sorted(
        ({"function_code": t.function_code, "function": function_title(t.function_code),
          "name": t.name, "description": t.description, "coverage_pct": t.coverage_pct}
         for t in tools),
        key=lambda item: item["function"],
    )


@router.put("/digital-tools/{function_code}")
def save_tool(function_code: str, body: DigitalToolIn, request: Request,
              db: Session = Depends(get_db), user: User = Depends(require_roles(*PLANNERS))):
    if function_code not in BY_CODE:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Неизвестная функция")
    tool = db.scalar(select(DigitalTool).where(DigitalTool.function_code == function_code))
    if tool is None:
        tool = DigitalTool(function_code=function_code)
        db.add(tool)
    for key, value in body.model_dump().items():
        setattr(tool, key, value)
    audit(db, user, "digital_tool_saved", entity="digital_tool", entity_id=function_code,
          details={"coverage_pct": body.coverage_pct}, request=request)
    db.commit()
    return {"function_code": function_code}
