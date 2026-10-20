"""Нормативы: документы-основания и коэффициенты.

Региональные нормативы правят администратор и аналитик, местные (муниципалитета или
учреждения) — ещё и специалист управления своего муниципалитета. Директор видит только
нормативы, применимые к его учреждению. После любой правки анализ пересчитывается.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.staffing import viewer
from app.deps import Scope, audit
from app.models import (
    Municipality,
    NormativeCoefficient,
    NormativeDocument,
    Organization,
    PersonnelGroup,
    Role,
)
from app.schemas import NormCoefficientIn, NormDocumentIn
from app.services import staffing, staffing_analysis
from app.services.norms import dec

router = APIRouter(prefix="/norms", tags=["norms"])


def _norm_editor(scope: Scope) -> None:
    if scope.user.role not in staffing.NORM_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Нормативы правит аналитик или "
                                                       "специалист управления")


def _document_scope(scope: Scope, scope_level: str) -> None:
    if scope_level == "region" and scope.user.role not in (Role.admin, Role.regional_analyst):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Региональные документы заводит аналитик или администратор")


# --- документы -----------------------------------------------------------------------


def _documents(scope: Scope, ids: list[int] | None = None) -> list[dict]:
    query = select(NormativeDocument).order_by(NormativeDocument.status,
                                               NormativeDocument.issued_at.desc().nulls_last(),
                                               NormativeDocument.id)
    if ids is not None:
        query = query.where(NormativeDocument.id.in_(ids))
    used = dict(scope.db.execute(select(NormativeCoefficient.document_id, func.count())
                                 .group_by(NormativeCoefficient.document_id)).all())
    return [staffing.document_out(d, used.get(d.id, 0)) for d in scope.db.scalars(query)]


@router.get("/documents")
def list_documents(scope: Scope = Depends(viewer)):
    return _documents(scope)


def _apply_document(document: NormativeDocument, body: NormDocumentIn) -> None:
    for key, value in body.model_dump().items():
        if isinstance(value, str):
            value = value.strip() or None
        setattr(document, key, value)
    document.title = body.title.strip()
    document.doc_type = body.doc_type.strip()


@router.post("/documents", status_code=status.HTTP_201_CREATED)
def create_document(body: NormDocumentIn, request: Request, scope: Scope = Depends(viewer)):
    _norm_editor(scope)
    _document_scope(scope, body.scope_level)
    document = NormativeDocument()
    _apply_document(document, body)
    scope.db.add(document)
    scope.db.flush()
    audit(scope.db, scope.user, "norm_document_created", entity="normative_document",
          entity_id=document.id, details={"title": document.title, "number": document.number},
          request=request)
    scope.db.commit()
    return _documents(scope, [document.id])[0]


@router.put("/documents/{document_id}")
def update_document(document_id: int, body: NormDocumentIn, request: Request,
                    scope: Scope = Depends(viewer)):
    _norm_editor(scope)
    document = scope.db.get(NormativeDocument, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Документ не найден")
    _document_scope(scope, document.scope_level)
    _document_scope(scope, body.scope_level)
    status_changed = document.status != body.status
    _apply_document(document, body)
    scope.db.flush()
    if status_changed:
        # Документ перестал действовать — его нормативы больше не применяются
        staffing_analysis.recalculate_all(scope.db)
    audit(scope.db, scope.user, "norm_document_updated", entity="normative_document",
          entity_id=document.id, details={"title": document.title, "status": document.status},
          request=request)
    scope.db.commit()
    return _documents(scope, [document.id])[0]


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: int, request: Request, scope: Scope = Depends(viewer)):
    _norm_editor(scope)
    document = scope.db.get(NormativeDocument, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Документ не найден")
    _document_scope(scope, document.scope_level)
    used = scope.db.scalar(select(func.count()).select_from(NormativeCoefficient)
                           .where(NormativeCoefficient.document_id == document_id))
    if used:
        raise HTTPException(status.HTTP_409_CONFLICT, f"На документ ссылаются нормативы ({used}) — "
                                                      "переведите его в архив")
    audit(scope.db, scope.user, "norm_document_deleted", entity="normative_document",
          entity_id=document_id, details={"title": document.title}, request=request)
    scope.db.delete(document)
    scope.db.commit()


# --- коэффициенты --------------------------------------------------------------------


def _coefficient_query():
    return select(NormativeCoefficient).options(
        selectinload(NormativeCoefficient.document), selectinload(NormativeCoefficient.group))


def _visible(scope: Scope) -> list[NormativeCoefficient]:
    user, db = scope.user, scope.db
    own = db.get(Organization, user.organization_id) if user.organization_id else None
    orgs = ({o.id: o for o in db.scalars(scope.organizations())}
            if user.role == Role.municipal_specialist else {})
    coefficients = db.scalars(_coefficient_query())
    return [c for c in coefficients if staffing.visible_norm(user, c, orgs, own)]


def _scope_title(scope: Scope, coef: NormativeCoefficient) -> str | None:
    if coef.scope_level == "municipality":
        item = scope.db.get(Municipality, coef.scope_id)
    elif coef.scope_level == "organization":
        item = scope.db.get(Organization, coef.scope_id)
    else:
        return None
    return item.name if item else None


def _out(scope: Scope, coef: NormativeCoefficient) -> dict:
    return {**staffing.coefficient_out(coef), "scope_title": _scope_title(scope, coef),
            "can_edit": staffing.can_edit_norm(scope.db, scope.user, coef.scope_level,
                                               coef.scope_id)}


def _sort_key(item: dict, order: dict[int, int]):
    return (item["category"], order.get(item["group_id"], 0), item["institution_type"],
            item["applies_from"] or 0)


@router.get("/coefficients")
def list_coefficients(scope: Scope = Depends(viewer)):
    order = {g.id: g.sort_order for g in scope.db.scalars(select(PersonnelGroup))}
    items = [_out(scope, c) for c in _visible(scope)]
    return sorted(items, key=lambda i: _sort_key(i, order))


def _apply_coefficient(scope: Scope, coef: NormativeCoefficient, body: NormCoefficientIn) -> None:
    db = scope.db
    if not staffing.can_edit_norm(db, scope.user, body.scope_level, body.scope_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Вы можете править только местные "
                                                       "нормативы своего муниципалитета")
    if db.get(PersonnelGroup, body.group_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Группа не найдена")
    if body.document_id is not None and db.get(NormativeDocument, body.document_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Документ не найден")
    if body.scope_level == "municipality" and db.get(Municipality, body.scope_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Муниципалитет не найден")
    if body.scope_level == "organization" and db.get(Organization, body.scope_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Учреждение не найдено")
    data = body.model_dump()
    coef.personnel_group_id = data.pop("group_id")
    for key in ("unit_size", "fte_per_unit", "min_fte", "max_fte", "applies_from", "applies_to",
                "rounding_step", "tolerance_abs", "tolerance_pct"):
        data[key] = dec(data[key])
    data["comment"] = (data["comment"] or "").strip() or None
    for key, value in data.items():
        setattr(coef, key, value)


@router.post("/coefficients", status_code=status.HTTP_201_CREATED)
def create_coefficient(body: NormCoefficientIn, request: Request, scope: Scope = Depends(viewer)):
    _norm_editor(scope)
    coef = NormativeCoefficient()
    _apply_coefficient(scope, coef, body)
    scope.db.add(coef)
    scope.db.flush()
    staffing_analysis.recalculate_all(scope.db)
    audit(scope.db, scope.user, "norm_coefficient_created", entity="normative_coefficient",
          entity_id=coef.id, details=body.model_dump(mode="json"), request=request)
    scope.db.commit()
    return _out(scope, scope.db.scalar(_coefficient_query()
                                       .where(NormativeCoefficient.id == coef.id)))


def _get(scope: Scope, coef_id: int) -> NormativeCoefficient:
    coef = scope.db.scalar(_coefficient_query().where(NormativeCoefficient.id == coef_id))
    if coef is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Норматив не найден")
    if not staffing.can_edit_norm(scope.db, scope.user, coef.scope_level, coef.scope_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Этот норматив правит аналитик")
    return coef


@router.put("/coefficients/{coef_id}")
def update_coefficient(coef_id: int, body: NormCoefficientIn, request: Request,
                       scope: Scope = Depends(viewer)):
    _norm_editor(scope)
    coef = _get(scope, coef_id)
    before = staffing.coefficient_out(coef)["rule"]
    _apply_coefficient(scope, coef, body)
    scope.db.flush()
    staffing_analysis.recalculate_all(scope.db)
    audit(scope.db, scope.user, "norm_coefficient_updated", entity="normative_coefficient",
          entity_id=coef.id, details={"before": before, **body.model_dump(mode="json")},
          request=request)
    scope.db.commit()
    scope.db.refresh(coef)
    return _out(scope, coef)


@router.delete("/coefficients/{coef_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_coefficient(coef_id: int, request: Request, scope: Scope = Depends(viewer)):
    _norm_editor(scope)
    coef = _get(scope, coef_id)
    rule = staffing.coefficient_out(coef)
    scope.db.delete(coef)
    scope.db.flush()
    # Связанные с заявками результаты хранят снимок норматива, поэтому удалять безопасно
    staffing_analysis.recalculate_all(scope.db)
    audit(scope.db, scope.user, "norm_coefficient_deleted", entity="normative_coefficient",
          entity_id=coef_id, details={"group": rule["group"], "rule": rule["rule"]},
          request=request)
    scope.db.commit()
