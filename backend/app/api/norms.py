from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import APPROVERS, audit, get_current_user, require_roles
from app.models import Norm, User
from app.schemas import NormIn, NormOut
from app.services.functions import CATEGORY_TITLES, FUNCTIONS
from app.services.staffing import DRIVERS

router = APIRouter(prefix="/norms", tags=["norms"])


def _validate(body: NormIn) -> None:
    if body.driver not in DRIVERS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Неизвестный показатель")
    if not any(f.code == body.function_code for f in FUNCTIONS):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Неизвестная функция")


@router.get("", response_model=list[NormOut])
def list_norms(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.scalars(select(Norm).order_by(Norm.kind.desc(), Norm.function_code, Norm.code)).all()


@router.get("/meta")
def meta(_: User = Depends(get_current_user)):
    """Справочники для формы норматива и подписей в интерфейсе."""
    return {
        "drivers": [{"key": key, "title": title} for key, title in DRIVERS.items()],
        "functions": [
            {"code": f.code, "title": f.title, "category": f.category} for f in FUNCTIONS
        ],
        "categories": [{"key": key, "title": title} for key, title in CATEGORY_TITLES.items()],
    }


@router.post("", response_model=NormOut, status_code=status.HTTP_201_CREATED)
def create_norm(body: NormIn, request: Request, db: Session = Depends(get_db),
                user: User = Depends(require_roles(*APPROVERS))):
    _validate(body)
    norm = Norm(**body.model_dump())
    db.add(norm)
    try:
        db.flush()
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Норматив с таким кодом уже есть") from exc
    audit(db, user, "norm_created", entity="norm", entity_id=norm.id,
          details={"code": norm.code}, request=request)
    db.commit()
    return norm


@router.put("/{norm_id}", response_model=NormOut)
def update_norm(norm_id: int, body: NormIn, request: Request, db: Session = Depends(get_db),
                user: User = Depends(require_roles(*APPROVERS))):
    norm = db.get(Norm, norm_id)
    if norm is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Норматив не найден")
    _validate(body)
    before = NormOut.model_validate(norm).model_dump(mode="json")
    for key, value in body.model_dump().items():
        setattr(norm, key, value)
    try:
        db.flush()
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Норматив с таким кодом уже есть") from exc
    # Перечитываем из БД, чтобы сравнивать значения в одном виде (1 и 1.00 — не изменение).
    # В журнал идут только изменившиеся поля: по ним видно, кто и когда поменял формулу
    db.refresh(norm)
    after = NormOut.model_validate(norm).model_dump(mode="json")
    changed = {k: [before[k], v] for k, v in after.items() if before[k] != v}
    audit(db, user, "norm_updated", entity="norm", entity_id=norm.id, details=changed,
          request=request)
    db.commit()
    return norm


@router.delete("/{norm_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_norm(norm_id: int, request: Request, db: Session = Depends(get_db),
                user: User = Depends(require_roles(*APPROVERS))):
    norm = db.get(Norm, norm_id)
    if norm is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Норматив не найден")
    audit(db, user, "norm_deleted", entity="norm", entity_id=norm.id,
          details={"code": norm.code}, request=request)
    db.delete(norm)
    db.commit()
