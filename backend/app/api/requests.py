"""Заявки сотрудников и учреждений: приём, назначение, переписка, сводка."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import selectinload

from app.deps import Scope, audit, get_scope
from app.models import Building, IncomingRequest, Organization, RequestKind, Role, User
from app.schemas import RequestComment, RequestIn, RequestStatusChange, RequestUpdate
from app.services import helpdesk, routing

router = APIRouter(tags=["requests"])


def _query(scope: Scope):
    return helpdesk.visible(scope).options(
        selectinload(IncomingRequest.organization), selectinload(IncomingRequest.building),
        selectinload(IncomingRequest.author), selectinload(IncomingRequest.assignee),
        selectinload(IncomingRequest.events),
    )


def _person(user: User | None) -> dict | None:
    return None if user is None else {"id": user.id, "name": user.full_name, "role": user.role}


def _actions(item: IncomingRequest, user: User) -> list[str]:
    allowed: tuple[str, ...] = ()
    if helpdesk.can_manage(user, item):
        allowed += helpdesk.WORK_TRANSITIONS.get(item.status, ())
    if item.author_id == user.id:
        allowed += helpdesk.AUTHOR_TRANSITIONS.get(item.status, ())
    return list(dict.fromkeys(allowed))


def _out(item: IncomingRequest, user: User, detailed: bool = False) -> dict:
    topic = routing.TOPICS.get(item.topic, routing.TOPICS["other"])
    result = {
        "id": item.id,
        "title": item.title,
        "text": item.text,
        "kind": item.kind,
        "topic": item.topic,
        "topic_title": topic.title,
        "status": item.status,
        "organization_id": item.organization_id,
        "organization": item.organization.name,
        "building_id": item.building_id,
        "building": item.building.name if item.building else None,
        "location": item.location,
        "author": _person(item.author),
        "assignee": _person(item.assignee),
        "routed_role": item.routed_role,
        "classified_by": item.classified_by,
        "created_at": item.created_at,
        "due_at": item.due_at,
        "started_at": item.started_at,
        "resolved_at": item.resolved_at,
        "closed_at": item.closed_at,
        "overdue": helpdesk.is_overdue(item),
        "resolution": item.resolution,
        "comments": sum(1 for e in item.events if e.kind == "comment"),
        "can_manage": helpdesk.can_manage(user, item),
        "is_author": item.author_id == user.id,
        "actions": _actions(item, user),
    }
    if detailed:
        result["events"] = [
            {"id": e.id, "kind": e.kind, "text": e.text, "created_at": e.created_at,
             "author": e.author.full_name if e.author else None}
            for e in item.events
        ]
    return result


def _get(request_id: int, scope: Scope) -> IncomingRequest:
    item = scope.db.scalar(_query(scope).where(IncomingRequest.id == request_id))
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Заявка не найдена")
    return item


def _assignable(scope: Scope, item: IncomingRequest) -> dict[int, User]:
    """Назначить можно любого, кто по роли вправе вести заявки этого учреждения."""
    people = {}
    for role in (Role.executor, Role.director, Role.municipal_specialist, item.routed_role):
        for candidate in helpdesk.candidates(scope.db, item, role):
            people[candidate.id] = candidate
    return people


def _forbid_observer(user: User) -> None:
    if user.role == Role.observer:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Наблюдатель не может менять заявки")


@router.get("/requests/meta")
def meta(scope: Scope = Depends(get_scope)):
    """Справочники для формы: темы со сроками и учреждения с корпусами."""
    organizations = scope.db.scalars(
        scope.organizations().options(selectinload(Organization.buildings)).limit(500)
    ).all()
    return {
        "topics": [
            {"code": code, "title": topic.title, "days": topic.days, "role": topic.role}
            for code, topic in routing.TOPICS.items()
        ],
        "kinds": [
            {"code": kind.value, "title": helpdesk.KIND_TITLES[kind],
             "hours": helpdesk.KIND_HOURS.get(kind)}
            for kind in RequestKind
        ],
        "statuses": [{"code": s.value, "title": t} for s, t in helpdesk.STATUS_TITLES.items()],
        "organizations": [
            {"id": org.id, "name": org.name,
             "buildings": [{"id": b.id, "name": b.name} for b in org.buildings]}
            for org in sorted(organizations, key=lambda o: o.name)
        ],
    }


@router.get("/requests")
def list_requests(scope: Scope = Depends(get_scope)):
    query = _query(scope).order_by(IncomingRequest.created_at.desc()).limit(1000)
    return [_out(item, scope.user) for item in scope.db.scalars(query)]


@router.get("/requests/stats")
def request_stats(days: int = 30, scope: Scope = Depends(get_scope)):
    items = scope.db.scalars(_query(scope)).all()
    return helpdesk.stats(list(items), days=max(7, min(days, 180)))


@router.post("/requests", status_code=status.HTTP_201_CREATED)
def create_request(body: RequestIn, request: Request, scope: Scope = Depends(get_scope)):
    user = scope.user
    _forbid_observer(user)
    org_id = user.organization_id or body.organization_id
    if org_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Укажите учреждение")
    org = scope.get_org(org_id)
    building = None
    if body.building_id is not None:
        building = scope.db.get(Building, body.building_id)
        if building is None or building.organization_id != org.id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "Корпус не относится к учреждению")
    if body.topic is not None and body.topic not in routing.TOPICS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Неизвестная тема")

    item = helpdesk.create(
        scope.db, user, org, title=body.title or body.text[:120], text=body.text or body.title,
        kind=body.kind, topic=body.topic, building=building, location=body.location,
    )
    audit(scope.db, user, "request_created", entity="request", entity_id=item.id,
          details={"topic": item.topic, "kind": item.kind, "assignee_id": item.assignee_id,
                   "by": item.classified_by}, request=request)
    scope.db.commit()
    return _out(item, user, detailed=True)


@router.get("/requests/{request_id}")
def get_request(request_id: int, scope: Scope = Depends(get_scope)):
    item = _get(request_id, scope)
    result = _out(item, scope.user, detailed=True)
    if result["can_manage"]:
        people = [_person(u) for u in _assignable(scope, item).values()]
        result["assignable"] = sorted(people, key=lambda p: p["name"])
    return result


@router.patch("/requests/{request_id}")
def update_request(request_id: int, body: RequestUpdate, request: Request,
                   scope: Scope = Depends(get_scope)):
    user = scope.user
    item = _get(request_id, scope)
    if not helpdesk.can_manage(user, item):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Заявку ведёт другой сотрудник")
    changes = body.model_dump(exclude_unset=True)
    try:
        if "topic" in changes or "kind" in changes:
            topic = changes.get("topic") or item.topic
            if topic not in routing.TOPICS:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Неизвестная тема")
            item.topic = topic
            item.kind = changes.get("kind") or item.kind
            item.classified_by = "manual"
            # Срок пересчитываем от создания, если его не задают явно этим же запросом
            if "due_at" not in changes:
                helpdesk.set_deadline(
                    item, user, helpdesk.deadline(item.kind, item.topic, item.created_at))
        if changes.get("due_at") is not None:
            helpdesk.set_deadline(item, user, changes["due_at"])
        if "assignee_id" in changes:
            assignee = None
            if changes["assignee_id"] is not None:
                assignee = _assignable(scope, item).get(changes["assignee_id"])
                if assignee is None:
                    raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                        "Исполнитель не найден")
            helpdesk.assign(scope.db, item, user, assignee)
    except helpdesk.Forbidden as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    audit(scope.db, user, "request_updated", entity="request", entity_id=item.id,
          details=body.model_dump(exclude_unset=True, mode="json"), request=request)
    scope.db.commit()
    return _out(item, user, detailed=True)


@router.post("/requests/{request_id}/status")
def change_status(request_id: int, body: RequestStatusChange, request: Request,
                  scope: Scope = Depends(get_scope)):
    user = scope.user
    _forbid_observer(user)
    item = _get(request_id, scope)
    try:
        helpdesk.change_status(scope.db, item, user, body.status, body.comment)
    except helpdesk.Forbidden as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    audit(scope.db, user, "request_status", entity="request", entity_id=item.id,
          details={"status": body.status}, request=request)
    scope.db.commit()
    return _out(item, user, detailed=True)


@router.post("/requests/{request_id}/comments", status_code=status.HTTP_201_CREATED)
def add_comment(request_id: int, body: RequestComment, scope: Scope = Depends(get_scope)):
    user = scope.user
    _forbid_observer(user)
    item = _get(request_id, scope)
    try:
        helpdesk.add_comment(scope.db, item, user, body.text.strip(), body.needs_reply)
    except helpdesk.Forbidden as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    scope.db.commit()
    return _out(item, user, detailed=True)
