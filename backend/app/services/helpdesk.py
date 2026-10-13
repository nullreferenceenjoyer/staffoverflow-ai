"""Заявки: назначение исполнителя, сроки, переходы статусов и сводка для дашборда.

Статус человек почти не выставляет руками — он следует из действий:
  создали и нашёлся исполнитель      -> «назначена»
  исполнитель ответил или взял        -> «в работе»
  исполнитель задал вопрос заявителю  -> «ждёт ответа» (срок на это время не идёт)
  заявитель ответил                   -> снова «в работе», срок сдвигается
  исполнитель отчитался               -> «выполнена»
  заявитель подтвердил или молчит N дней -> «закрыта»
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.deps import Scope
from app.models import (
    Building,
    IncomingRequest,
    Notification,
    Organization,
    RequestEvent,
    RequestKind,
    RequestStatus,
    Role,
    User,
)
from app.services import routing

S = RequestStatus
ACTIVE = (S.new, S.assigned, S.in_progress, S.on_hold)
FINAL = (S.closed, S.rejected)

STATUS_TITLES = {
    S.new: "Новая", S.assigned: "Назначена", S.in_progress: "В работе",
    S.on_hold: "Ждёт ответа", S.done: "Выполнена", S.closed: "Закрыта",
    S.rejected: "Отклонена",
}
KIND_TITLES = {
    RequestKind.planned: "Плановая", RequestKind.urgent: "Срочная",
    RequestKind.emergency: "Аварийная",
}
# На срочную и аварийную срок один для всех тем, на плановую — из справочника тем
KIND_HOURS = {RequestKind.urgent: 24, RequestKind.emergency: 4}

# Куда заявку может перевести тот, кто её ведёт
WORK_TRANSITIONS: dict[str, tuple[str, ...]] = {
    S.new: (S.in_progress, S.rejected),
    S.assigned: (S.in_progress, S.on_hold, S.done, S.rejected),
    S.in_progress: (S.on_hold, S.done, S.rejected),
    S.on_hold: (S.in_progress, S.done, S.rejected),
    S.done: (S.in_progress, S.closed),
}
# Что может сам заявитель: принять работу или вернуть её
AUTHOR_TRANSITIONS: dict[str, tuple[str, ...]] = {S.done: (S.closed, S.in_progress)}

# Если у адресата по теме нет учётной записи, заявка поднимается выше
FALLBACK_ROLES = {
    Role.executor: (Role.executor, Role.director, Role.municipal_specialist),
    Role.director: (Role.director, Role.municipal_specialist),
}


class Forbidden(Exception):
    """Действие недоступно этому пользователю или в этом статусе."""


def now() -> datetime:
    return datetime.now(UTC)


def deadline(kind: str, topic: str, start: datetime) -> datetime:
    if kind in KIND_HOURS:
        return start + timedelta(hours=KIND_HOURS[kind])
    return start + timedelta(days=routing.TOPICS[topic].days)


def is_overdue(request: IncomingRequest, moment: datetime | None = None) -> bool:
    # На паузе срок не идёт, поэтому «ждёт ответа» просроченной не считается
    return (request.status in (S.new, S.assigned, S.in_progress)
            and request.due_at is not None and request.due_at < (moment or now()))


def visible(scope: Scope):
    """Запрос на заявки, которые пользователь вправе видеть."""
    user = scope.user
    query = select(IncomingRequest)
    if scope.is_regional:
        return query
    if user.role == Role.municipal_specialist:
        ids = select(Organization.id).where(Organization.municipality_id == user.municipality_id)
        return query.where(IncomingRequest.organization_id.in_(ids))
    if user.role == Role.director:
        return query.where(IncomingRequest.organization_id == user.organization_id)
    if user.role == Role.executor:
        return query.where(
            IncomingRequest.organization_id == user.organization_id,
            (IncomingRequest.routed_role == Role.executor)
            | (IncomingRequest.assignee_id == user.id)
            | (IncomingRequest.author_id == user.id),
        )
    return query.where(IncomingRequest.author_id == user.id)


def can_manage(user: User, request: IncomingRequest) -> bool:
    """Вести заявку: назначать, менять срок, переводить по статусам."""
    if user.role == Role.observer:
        return False
    if user.role in (Role.admin, Role.regional_analyst) or request.assignee_id == user.id:
        return True
    if user.role == Role.municipal_specialist:
        return request.organization.municipality_id == user.municipality_id
    if user.role in (Role.director, Role.executor):
        # Внутри учреждения решаются только хозяйственные заявки; то, что ушло
        # в управление образования, директор сам себе закрыть не может
        same_org = request.organization_id == user.organization_id
        mine = (Role.executor,) if user.role == Role.executor else (Role.executor, Role.director)
        return same_org and request.routed_role in mine
    return False


def candidates(db: Session, request: IncomingRequest, role: str) -> list[User]:
    """Кто с этой ролью может взять заявку — с учётом учреждения и территории."""
    query = select(User).where(User.role == role, User.is_active)
    if role in (Role.executor, Role.director):
        query = query.where(User.organization_id == request.organization_id)
    elif role == Role.municipal_specialist:
        query = query.where(User.municipality_id == request.organization.municipality_id)
    return list(db.scalars(query.order_by(User.id)))


def pick_assignee(db: Session, request: IncomingRequest) -> User | None:
    """Выбирает наименее загруженного из подходящих. Возвращает None, если некому."""
    for role in FALLBACK_ROLES.get(request.routed_role, (request.routed_role,)):
        users = candidates(db, request, role)
        if not users:
            continue
        load = dict(db.execute(
            select(IncomingRequest.assignee_id, func.count())
            .where(IncomingRequest.assignee_id.in_([u.id for u in users]),
                   IncomingRequest.status.in_(ACTIVE))
            .group_by(IncomingRequest.assignee_id)
        ).all())
        request.routed_role = role
        return min(users, key=lambda u: (load.get(u.id, 0), u.id))
    return None


def log(request: IncomingRequest, author: User | None, kind: str, text: str,
        at: datetime | None = None) -> RequestEvent:
    event = RequestEvent(author_id=author.id if author else None, kind=kind, text=text)
    if at is not None:
        event.created_at = at
    request.events.append(event)
    return event


def notify(db: Session, request: IncomingRequest, users: list[User | None], text: str,
           skip: User | None = None) -> None:
    seen = set()
    for user in users:
        if user is None or user.id in seen or (skip is not None and user.id == skip.id):
            continue
        seen.add(user.id)
        db.add(Notification(user_id=user.id, request_id=request.id,
                            text=f"Заявка № {request.id} «{request.title}»: {text}"))


def create(db: Session, author: User, organization: Organization, *, title: str, text: str,
           kind: str = RequestKind.planned, topic: str | None = None,
           building: Building | None = None, location: str | None = None,
           created_at: datetime | None = None) -> IncomingRequest:
    created_at = created_at or now()
    if topic in routing.TOPICS:
        role, classified_by = routing.TOPICS[topic].role, "manual"
    else:
        topic, role, classified_by = routing.classify(f"{title}. {text}")
    request = IncomingRequest(
        organization=organization, building=building, location=location, author=author,
        title=title, text=text, kind=kind, topic=topic, routed_role=role,
        classified_by=classified_by, status=S.new, created_at=created_at,
        due_at=deadline(kind, topic, created_at),
    )
    db.add(request)
    db.flush()
    log(request, author, "status", "Заявка создана", created_at)

    assignee = pick_assignee(db, request)
    if assignee is not None:
        request.assignee = assignee
        request.status = S.assigned
        db.flush()
        log(request, None, "assignee",
            f"Исполнитель назначен автоматически: {assignee.full_name}", created_at)
        notify(db, request, [assignee], "назначена вам, срок "
               f"{request.due_at:%d.%m.%Y %H:%M}", skip=author)
    return request


def assign(db: Session, request: IncomingRequest, actor: User, assignee: User | None) -> None:
    if request.status in FINAL:
        raise Forbidden("Заявка уже закрыта")
    request.assignee = assignee
    db.flush()
    if assignee is None:
        log(request, actor, "assignee", "Исполнитель снят")
        if request.status == S.assigned:
            request.status = S.new
        return
    log(request, actor, "assignee", f"Исполнитель: {assignee.full_name}")
    if request.status == S.new:
        request.status = S.assigned
    notify(db, request, [assignee], "назначена вам", skip=actor)


def _resume(request: IncomingRequest, moment: datetime) -> None:
    if request.hold_since is not None and request.due_at is not None:
        request.due_at += moment - request.hold_since
    request.hold_since = None


def _set_status(request: IncomingRequest, status: str, moment: datetime) -> None:
    previous = request.status
    request.status = status
    if previous == S.on_hold:
        _resume(request, moment)
    if status == S.in_progress:
        request.started_at = request.started_at or moment
        request.resolved_at = None
    elif status == S.on_hold:
        request.hold_since = moment
    elif status == S.done:
        request.resolved_at = moment
    elif status in FINAL:
        request.closed_at = moment
        request.resolved_at = request.resolved_at or moment


def change_status(db: Session, request: IncomingRequest, actor: User, status: str,
                  comment: str | None = None, at: datetime | None = None) -> None:
    moment = at or now()
    manager = can_manage(actor, request)
    is_author = request.author_id == actor.id
    allowed: tuple[str, ...] = ()
    if manager:
        allowed += WORK_TRANSITIONS.get(request.status, ())
    if is_author:
        allowed += AUTHOR_TRANSITIONS.get(request.status, ())
    if status not in allowed:
        raise Forbidden(f"Из статуса «{STATUS_TITLES[request.status]}» нельзя перевести "
                        f"в «{STATUS_TITLES[status]}»")
    comment = (comment or "").strip()
    if status in (S.rejected, S.on_hold) and not comment:
        raise Forbidden("Напишите причину — заявитель должен понимать, что происходит")
    if status == S.in_progress and request.status == S.done and not comment:
        raise Forbidden("Напишите, что именно не сделано")

    returned = request.status == S.done and status == S.in_progress
    if manager and request.assignee is None and status in (S.in_progress, S.done):
        # Кто взялся, тот и исполнитель
        request.assignee = actor
        log(request, actor, "assignee", f"Исполнитель: {actor.full_name}", moment)
    _set_status(request, status, moment)
    if status == S.done:
        request.resolution = comment or request.resolution
    title = "Возвращена в работу" if returned else STATUS_TITLES[status]
    log(request, actor, "status", f"{title}. {comment}" if comment else title, moment)
    notify(db, request, [request.author, request.assignee],
           title.lower() + (f" — {comment[:200]}" if comment else ""), skip=actor)


def add_comment(db: Session, request: IncomingRequest, actor: User, text: str,
                needs_reply: bool = False) -> None:
    """Комментарий двигает статус сам: ответ исполнителя — «в работе»,
    вопрос к заявителю — «ждёт ответа», ответ заявителя — обратно «в работе»."""
    if request.status in FINAL:
        raise Forbidden("Заявка закрыта, комментарии не принимаются")
    moment = now()
    log(request, actor, "comment", text, moment)
    is_assignee = request.assignee_id == actor.id
    if is_assignee and needs_reply and request.status in (S.assigned, S.in_progress):
        _set_status(request, S.on_hold, moment)
        log(request, None, "status", "Ждёт ответа заявителя, срок приостановлен", moment)
    elif is_assignee and request.status == S.assigned:
        _set_status(request, S.in_progress, moment)
        log(request, None, "status", "В работе", moment)
    elif request.author_id == actor.id and request.status == S.on_hold:
        _set_status(request, S.in_progress, moment)
        log(request, None, "status", "Заявитель ответил, работа продолжена", moment)
    notify(db, request, [request.author, request.assignee],
           f"{actor.full_name}: {text[:200]}", skip=actor)


def set_deadline(request: IncomingRequest, actor: User, due_at: datetime) -> None:
    request.due_at = due_at
    request.last_reminder_on = None
    log(request, actor, "deadline", f"Срок изменён: до {due_at:%d.%m.%Y %H:%M}")


def run_automation(db: Session, moment: datetime | None = None) -> dict[str, int]:
    """Фоновая обработка: напоминания о сроках и закрытие принятых по умолчанию заявок."""
    moment = moment or now()
    settings = get_settings()
    today = moment.date()
    result = {"reminded": 0, "closed": 0}

    stale = moment - timedelta(days=settings.request_autoclose_days)
    for request in db.scalars(select(IncomingRequest).where(
            IncomingRequest.status == S.done, IncomingRequest.resolved_at < stale)):
        _set_status(request, S.closed, moment)
        log(request, None, "status", "Закрыта автоматически: заявитель не возразил "
            f"в течение {settings.request_autoclose_days} дн.", moment)
        notify(db, request, [request.author], "закрыта автоматически")
        result["closed"] += 1

    horizon = moment + timedelta(hours=settings.request_warn_hours)
    for request in db.scalars(select(IncomingRequest).where(
            IncomingRequest.status.in_((S.new, S.assigned, S.in_progress)),
            IncomingRequest.due_at <= horizon,
            (IncomingRequest.last_reminder_on.is_(None))
            | (IncomingRequest.last_reminder_on < today))):
        if request.due_at < moment:
            text = f"срок истёк {request.due_at:%d.%m.%Y %H:%M}"
            # О просрочке узнаёт и руководитель учреждения
            recipients = [request.assignee, *candidates(db, request, Role.director)]
        else:
            text = f"срок истекает {request.due_at:%d.%m.%Y %H:%M}"
            recipients = [request.assignee]
        if request.assignee is None:
            recipients += candidates(db, request, request.routed_role)
        notify(db, request, recipients, text)
        request.last_reminder_on = today
        result["reminded"] += 1
    return result


def _hours(start: datetime, end: datetime) -> float:
    return (end - start).total_seconds() / 3600


def stats(requests: list[IncomingRequest], moment: datetime | None = None, days: int = 30) -> dict:
    """Сводка для дашборда заявок."""
    moment = moment or now()
    since = moment - timedelta(days=days)
    by_status = dict.fromkeys((s.value for s in S), 0)
    topics: dict[str, dict] = {}
    people: dict[int | None, dict] = {}
    organizations: dict[int, dict] = {}
    flow: dict[date, dict] = {
        (since + timedelta(days=i + 1)).date(): {"created": 0, "closed": 0} for i in range(days)
    }
    resolve_hours: list[float] = []
    in_time = resolved = overdue = 0

    for r in requests:
        by_status[r.status] += 1
        late = is_overdue(r, moment)
        overdue += late
        active = r.status in ACTIVE

        topic = topics.setdefault(r.topic, {
            "topic": r.topic, "title": routing.TOPICS[r.topic].title, "total": 0, "active": 0,
            "overdue": 0, "hours": []})
        topic["total"] += 1
        topic["active"] += active
        topic["overdue"] += late

        if active or r.assignee_id is not None:
            person = people.setdefault(r.assignee_id, {
                "id": r.assignee_id,
                "name": r.assignee.full_name if r.assignee else "Не назначен",
                "active": 0, "overdue": 0, "done": 0})
            person["active"] += active
            person["overdue"] += late
            person["done"] += r.status in (S.done, S.closed)

        org = organizations.setdefault(r.organization_id, {
            "id": r.organization_id, "name": r.organization.name, "total": 0, "active": 0,
            "overdue": 0})
        org["total"] += 1
        org["active"] += active
        org["overdue"] += late

        if r.created_at.date() in flow:
            flow[r.created_at.date()]["created"] += 1
        if r.resolved_at is not None and r.status != S.rejected:
            if r.resolved_at.date() in flow:
                flow[r.resolved_at.date()]["closed"] += 1
            if r.resolved_at >= since:
                hours = _hours(r.created_at, r.resolved_at)
                resolve_hours.append(hours)
                topic["hours"].append(hours)
                resolved += 1
                in_time += r.due_at is None or r.resolved_at <= r.due_at

    for topic in topics.values():
        hours = topic.pop("hours")
        topic["avg_hours"] = round(sum(hours) / len(hours), 1) if hours else None

    return {
        "days": days,
        "total": len(requests),
        "active": sum(by_status[s] for s in ACTIVE),
        "unassigned": sum(1 for r in requests if r.status in ACTIVE and r.assignee_id is None),
        "overdue": overdue,
        "waiting_confirmation": by_status[S.done],
        "resolved": resolved,
        "in_time_pct": round(in_time / resolved * 100) if resolved else None,
        "avg_hours": round(sum(resolve_hours) / len(resolve_hours), 1) if resolve_hours else None,
        "by_status": [{"status": s.value, "title": STATUS_TITLES[s], "count": by_status[s]}
                      for s in S],
        "by_kind": [
            {"kind": k.value, "title": KIND_TITLES[k],
             "count": sum(1 for r in requests if r.kind == k and r.status in ACTIVE)}
            for k in RequestKind
        ],
        "by_topic": sorted(topics.values(), key=lambda t: -t["total"]),
        "by_assignee": sorted(people.values(), key=lambda p: (-p["active"], p["name"]))[:12],
        "by_organization": sorted(organizations.values(), key=lambda o: -o["total"])[:8],
        "flow": [{"date": day.isoformat(), **values} for day, values in flow.items()],
    }

