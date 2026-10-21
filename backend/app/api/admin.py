"""Администрирование: учёт учреждений, бригады с закреплёнными школами, импорт и шаблоны."""

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.deps import audit, require_roles
from app.models import (
    Brigade,
    Building,
    IncomingRequest,
    Municipality,
    Organization,
    Role,
    User,
)
from app.schemas import BrigadeIn, BrigadeSchools, OrganizationIn
from app.services import directory, effort, geo, helpdesk
from app.services.spreadsheet import TableError, build_template, read_table

router = APIRouter(prefix="/admin", tags=["admin"])
admin_only = require_roles(Role.admin)
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _coords(obj) -> dict:
    return {"latitude": float(obj.latitude) if obj.latitude is not None else None,
            "longitude": float(obj.longitude) if obj.longitude is not None else None}


# --- учреждения ----------------------------------------------------------------------


def _organization_out(org: Organization, users: int, requests: int,
                      brigades: list[Brigade]) -> dict:
    return {
        "id": org.id, "name": org.name, "org_type": org.org_type, "address": org.address,
        "external_id": org.external_id, "municipality_id": org.municipality_id,
        "municipality": org.municipality.name, **_coords(org),
        "buildings": [{"id": b.id, "name": b.name, "address": b.address} for b in org.buildings],
        "users": users, "requests": requests,
        "brigades": [{"id": b.id, "name": b.name} for b in brigades],
    }


def _organizations(db: Session, ids: list[int] | None = None) -> list[dict]:
    query = (select(Organization).order_by(Organization.name)
             .options(selectinload(Organization.buildings),
                      selectinload(Organization.municipality)))
    if ids is not None:
        query = query.where(Organization.id.in_(ids))
    orgs = list(db.scalars(query))
    users = dict(db.execute(select(User.organization_id, func.count())
                            .group_by(User.organization_id)).all())
    requests = dict(db.execute(select(IncomingRequest.organization_id, func.count())
                               .group_by(IncomingRequest.organization_id)).all())
    served: dict[int, list[Brigade]] = {}
    for brigade in db.scalars(select(Brigade).options(selectinload(Brigade.organizations))):
        for org in brigade.organizations:
            served.setdefault(org.id, []).append(brigade)
    return [_organization_out(o, users.get(o.id, 0), requests.get(o.id, 0),
                              served.get(o.id, [])) for o in orgs]


@router.get("/organizations")
def list_organizations(db: Session = Depends(get_db), _: User = Depends(admin_only)):
    return _organizations(db)


def _apply_organization(db: Session, org: Organization, body: OrganizationIn) -> None:
    municipality = directory.Municipalities(db).get_or_create(body.municipality)
    org.name = " ".join(body.name.split())
    org.municipality = municipality
    org.org_type = body.org_type
    org.address = body.address or None
    org.external_id = body.external_id or None
    org.latitude = body.latitude
    org.longitude = body.longitude
    keep = {b.id for b in body.buildings if b.id}
    for building in list(org.buildings):
        if building.id not in keep:
            # Заявки корпуса останутся, просто без указания корпуса
            org.buildings.remove(building)
    by_id = {b.id: b for b in org.buildings}
    for item in body.buildings:
        if item.id and item.id in by_id:
            by_id[item.id].name = item.name
            by_id[item.id].address = item.address or org.address
        elif not item.id:
            org.buildings.append(Building(name=item.name, address=item.address or org.address))
    if not org.buildings:
        org.buildings.append(Building(name="Основное здание", address=org.address))


@router.post("/organizations", status_code=status.HTTP_201_CREATED)
def create_organization(body: OrganizationIn, request: Request, db: Session = Depends(get_db),
                        admin: User = Depends(admin_only)):
    org = Organization(buildings=[])
    # В сессию — после заполнения: иначе автосохранение запишет учреждение без названия
    _apply_organization(db, org, body)
    db.add(org)
    try:
        db.flush()
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Такой код учреждения уже есть") from exc
    audit(db, admin, "organization_created", entity="organization", entity_id=org.id,
          details={"name": org.name}, request=request)
    db.commit()
    return _organizations(db, [org.id])[0]


@router.put("/organizations/{org_id}")
def update_organization(org_id: int, body: OrganizationIn, request: Request,
                        db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    org = db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Учреждение не найдено")
    _apply_organization(db, org, body)
    try:
        db.flush()
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Такой код учреждения уже есть") from exc
    audit(db, admin, "organization_updated", entity="organization", entity_id=org.id,
          details={"name": org.name}, request=request)
    db.commit()
    return _organizations(db, [org.id])[0]


@router.delete("/organizations/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_organization(org_id: int, request: Request, db: Session = Depends(get_db),
                        admin: User = Depends(admin_only)):
    org = db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Учреждение не найдено")
    users = db.scalar(select(func.count()).select_from(User)
                      .where(User.organization_id == org_id))
    requests = db.scalar(select(func.count()).select_from(IncomingRequest)
                         .where(IncomingRequest.organization_id == org_id))
    if users or requests:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"У учреждения есть пользователи ({users}) или заявки ({requests}) — "
                            "удалить его нельзя")
    audit(db, admin, "organization_deleted", entity="organization", entity_id=org_id,
          details={"name": org.name}, request=request)
    db.delete(org)
    db.commit()


# --- бригады -------------------------------------------------------------------------


def _brigade_out(brigade: Brigade, load: int) -> dict:
    base = geo.point(brigade)
    organizations = []
    for org in brigade.organizations:
        here = geo.point(org)
        distance = round(geo.distance_km(*base, *here), 1) if base and here else None
        organizations.append({"id": org.id, "name": org.name, "distance_km": distance})
    return {
        "id": brigade.id, "name": brigade.name, "municipality_id": brigade.municipality_id,
        "municipality": brigade.municipality.name if brigade.municipality else None,
        "base_address": brigade.base_address, **_coords(brigade), "topics": brigade.topics,
        "is_active": brigade.is_active,
        "members": [{"id": m.id, "name": m.full_name, "email": m.email, "is_active": m.is_active}
                    for m in brigade.members],
        "organizations": organizations, "active_requests": load,
    }


def _brigade_query():
    return select(Brigade).order_by(Brigade.name).options(
        selectinload(Brigade.members), selectinload(Brigade.organizations),
        selectinload(Brigade.municipality))


def _brigades(db: Session, ids: list[int] | None = None) -> list[dict]:
    query = _brigade_query()
    if ids is not None:
        query = query.where(Brigade.id.in_(ids))
    brigades = list(db.scalars(query))
    load = helpdesk.brigade_load(db, [b.id for b in brigades])
    return [_brigade_out(b, load.get(b.id, 0)) for b in brigades]


@router.get("/brigades")
def list_brigades(db: Session = Depends(get_db), _: User = Depends(admin_only)):
    return _brigades(db)


def _apply_brigade(db: Session, brigade: Brigade, body: BrigadeIn) -> None:
    if body.municipality_id is not None and db.get(Municipality, body.municipality_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Муниципалитет не найден")
    unknown = sorted(set(body.topics) - set(effort.BASE_HOURS))
    if unknown:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Неизвестные темы: {', '.join(unknown)}")
    brigade.name = " ".join(body.name.split())
    brigade.municipality_id = body.municipality_id
    brigade.base_address = body.base_address or None
    brigade.latitude = body.latitude
    brigade.longitude = body.longitude
    brigade.topics = body.topics
    brigade.is_active = body.is_active
    members = list(db.scalars(select(User).where(User.id.in_(body.member_ids)))) \
        if body.member_ids else []
    wrong = [u.full_name for u in members if u.role != Role.brigade]
    if wrong:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Не участники бригад (группа «Хозяйственный отдел», в бригаде "
                            f"управления образования): {', '.join(wrong)}")
    for user in list(brigade.members):
        if user.id not in body.member_ids:
            user.brigade_id = None
    for user in members:
        user.brigade = brigade


@router.post("/brigades", status_code=status.HTTP_201_CREATED)
def create_brigade(body: BrigadeIn, request: Request, db: Session = Depends(get_db),
                   admin: User = Depends(admin_only)):
    brigade = Brigade(topics=[])
    _apply_brigade(db, brigade, body)
    db.add(brigade)
    try:
        db.flush()
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Бригада с таким названием уже есть") \
            from exc
    audit(db, admin, "brigade_created", entity="brigade", entity_id=brigade.id,
          details={"name": brigade.name}, request=request)
    db.commit()
    return _brigades(db, [brigade.id])[0]


@router.put("/brigades/{brigade_id}")
def update_brigade(brigade_id: int, body: BrigadeIn, request: Request,
                   db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    brigade = db.scalar(_brigade_query().where(Brigade.id == brigade_id))
    if brigade is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Бригада не найдена")
    _apply_brigade(db, brigade, body)
    try:
        db.flush()
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Бригада с таким названием уже есть") \
            from exc
    audit(db, admin, "brigade_updated", entity="brigade", entity_id=brigade.id,
          details={"name": brigade.name, "members": body.member_ids}, request=request)
    db.commit()
    return _brigades(db, [brigade.id])[0]


@router.put("/brigades/{brigade_id}/organizations")
def set_brigade_organizations(brigade_id: int, body: BrigadeSchools, request: Request,
                              db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    brigade = db.scalar(_brigade_query().where(Brigade.id == brigade_id))
    if brigade is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Бригада не найдена")
    orgs = list(db.scalars(select(Organization).where(
        Organization.id.in_(body.organization_ids)))) if body.organization_ids else []
    if len(orgs) != len(set(body.organization_ids)):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Часть учреждений не найдена")
    brigade.organizations = orgs
    audit(db, admin, "brigade_schools", entity="brigade", entity_id=brigade.id,
          details={"organizations": len(orgs)}, request=request)
    db.commit()
    return _brigades(db, [brigade.id])[0]


@router.get("/brigades/{brigade_id}/suggestions")
def brigade_suggestions(brigade_id: int, db: Session = Depends(get_db),
                        _: User = Depends(admin_only)):
    """Учреждения с расстоянием до базы бригады и отметкой, какая бригада к ним ближе."""
    brigade = db.scalar(_brigade_query().where(Brigade.id == brigade_id))
    if brigade is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Бригада не найдена")
    query = select(Organization).options(selectinload(Organization.municipality))
    if brigade.municipality_id is not None:
        query = query.where(Organization.municipality_id == brigade.municipality_id)
    others = [b for b in db.scalars(_brigade_query().where(Brigade.is_active))
              if geo.point(b) is not None]
    served: dict[int, list[str]] = {}
    for other in others:
        for org in other.organizations:
            if other.id != brigade.id:
                served.setdefault(org.id, []).append(other.name)
    assigned = {o.id for o in brigade.organizations}
    base = geo.point(brigade)
    items = []
    for org in db.scalars(query):
        here = geo.point(org)
        distance = nearest = None
        if here is not None:
            if base is not None:
                distance = round(geo.distance_km(*base, *here), 1)
            # Сравниваем только бригады с тем же набором работ: общую — с общими,
            # электриков — с электриками
            candidates = [(geo.distance_km(*geo.point(b), *here), b) for b in others
                          if b.municipality_id in (None, org.municipality_id)
                          and sorted(b.topics) == sorted(brigade.topics)]
            if candidates:
                nearest = min(candidates, key=lambda pair: pair[0])[1]
        items.append({
            "id": org.id, "name": org.name, "municipality": org.municipality.name,
            "distance_km": distance, "assigned": org.id in assigned,
            "nearest": {"id": nearest.id, "name": nearest.name} if nearest else None,
            "other_brigades": served.get(org.id, []),
        })
    items.sort(key=lambda i: (i["distance_km"] is None, i["distance_km"] or 0, i["name"]))
    return {"has_base": base is not None, "items": items}


@router.delete("/brigades/{brigade_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_brigade(brigade_id: int, request: Request, db: Session = Depends(get_db),
                   admin: User = Depends(admin_only)):
    brigade = db.get(Brigade, brigade_id)
    if brigade is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Бригада не найдена")
    if helpdesk.brigade_load(db, [brigade_id]).get(brigade_id):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "У бригады есть открытые заявки — сначала передайте их другим")
    audit(db, admin, "brigade_deleted", entity="brigade", entity_id=brigade_id,
          details={"name": brigade.name}, request=request)
    db.delete(brigade)
    db.commit()


# --- импорт и шаблоны ----------------------------------------------------------------


async def _read(file: UploadFile, columns) -> list[tuple[int, dict]]:
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Файл больше 10 МБ")
    try:
        return read_table(content, file.filename or "", columns)
    except TableError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.post("/import/organizations")
async def import_organizations(request: Request, file: UploadFile = File(...),
                               municipality: str = Form(""), db: Session = Depends(get_db),
                               admin: User = Depends(admin_only)):
    rows = await _read(file, directory.ORG_COLUMNS)
    result = directory.import_organizations(db, rows, municipality)
    audit(db, admin, "import_organizations", details={
        "file": file.filename, "created": result.created, "updated": result.updated,
        "skipped": result.skipped}, request=request)
    db.commit()
    return result.as_dict()


@router.post("/import/users")
async def import_users(request: Request, file: UploadFile = File(...),
                       db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    rows = await _read(file, directory.USER_COLUMNS)
    result = directory.import_users(db, rows, admin)
    # Пароли в журнал не пишем
    audit(db, admin, "import_users", details={
        "file": file.filename, "created": result.created, "updated": result.updated,
        "skipped": result.skipped}, request=request)
    db.commit()
    return result.as_dict()


TEMPLATES = {
    "organizations": ("Учреждения", directory.ORG_COLUMNS, directory.ORG_EXAMPLES,
                      directory.ORG_HELP),
    "users": ("Пользователи", directory.USER_COLUMNS, directory.USER_EXAMPLES,
              directory.USER_HELP),
}


@router.get("/templates/{kind}.xlsx")
def template(kind: str, _: User = Depends(admin_only)):
    if kind not in TEMPLATES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Нет такого шаблона")
    title, columns, examples, help_rows = TEMPLATES[kind]
    content = build_template(columns, examples, help_rows, title)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{kind}-template.xlsx"'},
    )
