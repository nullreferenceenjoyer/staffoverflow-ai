"""Заявки: назначение исполнителя, сроки, переходы статусов и сводка для дашборда.

Кому достаётся хозяйственная заявка, зависит от её трудоёмкости:
  простая (до 4 ч)      -> сотрудник хозслужбы на точке, если его нет — бригада
  сложная или крупная   -> выездная бригада, которая обслуживает учреждение
  аварийная             -> сначала тот, кто на месте: он быстрее локализует аварию
Крупную работу (больше 16 ч) руководитель может разбить на этапы.

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
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.deps import Scope
from app.models import (
    Brigade,
    Building,
    Complexity,
    IncomingRequest,
    Notification,
    Organization,
    RequestEvent,
    RequestKind,
    RequestStatus,
    Role,
    User,
    brigade_organizations,
)
from app.services import effort, routing

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
COMPLEXITY_TITLES = {
    Complexity.simple: "простая", Complexity.complex: "сложная", Complexity.major: "крупная",
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
# Что может сам заявитель: отозвать открытую заявку, принять работу или вернуть её
AUTHOR_TRANSITIONS: dict[str, tuple[str, ...]] = {
    **{status: (S.rejected,) for status in ACTIVE},
    S.done: (S.closed, S.in_progress),
}

# Если у адресата по теме нет учётной записи, заявка поднимается выше
FALLBACK_ROLES = {
    Role.executor: (Role.executor, Role.director, Role.municipal_specialist),
    Role.director: (Role.director, Role.municipal_specialist),
}


class Forbidden(Exception):
    """Действие недоступно этому пользователю или в этом статусе."""


def now() -> datetime:
    return datetime.now(UTC)


def when(moment: datetime) -> str:
    """Дата и время для текста уведомления — в часовом поясе учреждений, а не в UTC."""
    try:
        zone = ZoneInfo(get_settings().timezone)
    except (ZoneInfoNotFoundError, ValueError):
        zone = UTC
    return f"{moment.astimezone(zone):%d.%m.%Y %H:%M}"


def deadline(kind: str, topic: str, start: datetime, hours: float | None = None) -> datetime:
    if kind in KIND_HOURS:
        return start + timedelta(hours=KIND_HOURS[kind])
    # Большую работу за типовой срок не сделать: добавляем дни по объёму
    return start + timedelta(days=routing.TOPICS[topic].days + effort.extra_days(hours))


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
    mine = [IncomingRequest.assignee_id == user.id, IncomingRequest.author_id == user.id]
    if user.role == Role.brigade and user.brigade_id is not None:
        # Бригада видит всё, что ей направлено, по всем закреплённым учреждениям
        mine.append(IncomingRequest.brigade_id == user.brigade_id)
    return query.where(or_(*mine))


def concerns(viewer, info: dict) -> bool:
    """Касается ли изменение заявки пользователя — для обновлений в реальном времени.

    Те же правила, что в visible(), но по сведениям из события: учреждение, округ,
    участники (заявитель, исполнитель — нынешний и прежний), бригады и адресаты.
    Меняя visible(), поменяйте и эту функцию.
    """
    if viewer.role in (Role.admin, Role.regional_analyst, Role.observer):
        return True
    if viewer.role == Role.municipal_specialist:
        return info["mun"] == viewer.municipality_id
    if viewer.role == Role.director:
        return info["org"] == viewer.organization_id
    mine = viewer.id in info["people"]
    if viewer.role == Role.executor:
        return info["org"] == viewer.organization_id and (mine or Role.executor in info["roles"])
    if viewer.role == Role.brigade and viewer.brigade_id is not None:
        return mine or viewer.brigade_id in info["brigades"]
    return mine


def can_manage(user: User, request: IncomingRequest) -> bool:
    """Вести заявку: назначать, менять срок, переводить по статусам."""
    if user.role == Role.observer:
        return False
    if user.role in (Role.admin, Role.regional_analyst) or request.assignee_id == user.id:
        return True
    if user.role == Role.municipal_specialist:
        return request.organization.municipality_id == user.municipality_id
    if user.role == Role.brigade:
        return request.brigade_id is not None and request.brigade_id == user.brigade_id
    if user.role in (Role.director, Role.executor):
        # Внутри учреждения решаются только хозяйственные заявки; то, что ушло
        # в управление образования, директор сам себе закрыть не может
        same_org = request.organization_id == user.organization_id
        mine = ((Role.executor,) if user.role == Role.executor
                else (Role.executor, Role.director, Role.brigade))
        return same_org and request.routed_role in mine
    return False


def my_turn(user: User, request: IncomingRequest) -> str | None:
    """Что сейчас должен сделать именно этот пользователь, или None, если ход не за ним.

    Отсюда берутся счётчик «ждут вас» в меню и подсказка в карточке заявки.
    """
    if request.author_id == user.id:
        if request.status == S.on_hold:
            return "Ответьте на вопрос исполнителя"
        if request.status == S.done:
            return "Проверьте работу и примите её"
    if (request.status == S.assigned and request.assignee_id is None
            and request.brigade_id is not None and request.brigade_id == user.brigade_id):
        return "Возьмите заявку в работу — она направлена вашей бригаде"
    if request.assignee_id == user.id:
        if request.status == S.assigned:
            return "Возьмите заявку в работу"
        if request.status == S.in_progress:
            return "Выполните и напишите отчёт"
    # Открытая заявка, которую никто не делает (не нашёлся исполнитель, его сняли,
    # бригаду расформировали), не должна теряться: ход за руководителем
    if (request.status in (S.new, S.assigned, S.in_progress) and request.assignee_id is None
            and request.brigade_id is None and can_manage(user, request)):
        return "Назначьте исполнителя"
    return None


def candidates(db: Session, request: IncomingRequest, role: str) -> list[User]:
    """Кто с этой ролью может взять заявку — с учётом учреждения и территории."""
    query = select(User).where(User.role == role, User.is_active)
    if role in (Role.executor, Role.director):
        query = query.where(User.organization_id == request.organization_id)
    elif role == Role.municipal_specialist:
        query = query.where(User.municipality_id == request.organization.municipality_id)
    return list(db.scalars(query.order_by(User.id)))


def least_loaded(db: Session, users: list[User]) -> User | None:
    if not users:
        return None
    load = dict(db.execute(
        select(IncomingRequest.assignee_id, func.count())
        .where(IncomingRequest.assignee_id.in_([u.id for u in users]),
               IncomingRequest.status.in_(ACTIVE))
        .group_by(IncomingRequest.assignee_id)
    ).all())
    return min(users, key=lambda u: (load.get(u.id, 0), u.id))


def brigades_for(db: Session, request: IncomingRequest) -> list[Brigade]:
    """Бригады, за которыми закреплено учреждение и которые берут эту тему."""
    brigades = db.scalars(
        select(Brigade)
        .join(brigade_organizations, brigade_organizations.c.brigade_id == Brigade.id)
        .where(brigade_organizations.c.organization_id == request.organization_id,
               Brigade.is_active)
        .order_by(Brigade.id)
    )
    return [b for b in brigades
            if (not b.topics or request.topic in b.topics) and any(m.is_active for m in b.members)]


def brigade_load(db: Session, brigade_ids: list[int]) -> dict[int, int]:
    return dict(db.execute(
        select(IncomingRequest.brigade_id, func.count())
        .where(IncomingRequest.brigade_id.in_(brigade_ids), IncomingRequest.status.in_(ACTIVE))
        .group_by(IncomingRequest.brigade_id)
    ).all())


def pick_brigade(db: Session, request: IncomingRequest) -> Brigade | None:
    """Наименее загруженная бригада: открытых заявок на одного участника."""
    brigades = brigades_for(db, request)
    if not brigades:
        return None
    load = brigade_load(db, [b.id for b in brigades])
    return min(brigades, key=lambda b: (
        load.get(b.id, 0) / max(sum(m.is_active for m in b.members), 1), b.id))


def route(db: Session, request: IncomingRequest) -> tuple[User | None, Brigade | None, str]:
    """Кому отдать заявку: (исполнитель, бригада, почему). Меняет routed_role."""
    if effort.is_field(request.topic) and request.routed_role == Role.executor:
        heavy = request.complexity != Complexity.simple
        emergency = request.kind == RequestKind.emergency
        # Аварию первым локализует тот, кто на месте, даже если работа большая
        order = ("brigade", Role.executor) if heavy and not emergency else (Role.executor,
                                                                            "brigade")
        for option in (*order, Role.director, Role.municipal_specialist):
            if option == "brigade":
                brigade = pick_brigade(db, request)
                if brigade is not None:
                    request.routed_role = Role.brigade
                    why = ("работа сложная" if heavy and not emergency
                           else "в учреждении нет сотрудника хозслужбы")
                    return None, brigade, why
                continue
            user = least_loaded(db, candidates(db, request, option))
            if user is not None:
                request.routed_role = option
                if option == Role.executor:
                    why = ("авария: первым едет тот, кто на месте" if heavy and emergency
                           else "сотрудник на точке" if not heavy
                           else "бригады для учреждения нет")
                else:
                    why = "в учреждении некому выполнить"
                return user, None, why
        return None, None, ""
    for role in FALLBACK_ROLES.get(request.routed_role, (request.routed_role,)):
        user = least_loaded(db, candidates(db, request, role))
        if user is not None:
            request.routed_role = role
            return user, None, ""
    return None, None, ""


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


def workers(request: IncomingRequest) -> list[User]:
    """Кто сейчас делает заявку: исполнитель, а пока его нет — вся бригада."""
    if request.assignee is not None:
        return [request.assignee]
    if request.brigade is not None:
        return [m for m in request.brigade.members if m.is_active]
    return []


# Роли, на которые переходит заявка вместе с исполнителем
WORKER_ROLES = (Role.executor, Role.director, Role.brigade, Role.municipal_specialist,
                Role.regional_analyst, Role.admin)


def _give(request: IncomingRequest, user: User) -> None:
    """Отдаёт заявку человеку. Участник бригады ведёт её от имени бригады,
    остальные — сами по себе, и бригада с заявки снимается."""
    request.assignee = user
    request.brigade = user.brigade if user.role == Role.brigade else None
    if user.role in WORKER_ROLES:
        request.routed_role = user.role


def create(db: Session, author: User, organization: Organization, *, title: str, text: str,
           kind: str = RequestKind.planned, topic: str | None = None,
           building: Building | None = None, location: str | None = None,
           created_at: datetime | None = None, parent: IncomingRequest | None = None,
           effort_hours: float | None = None, role: Role | None = None) -> IncomingRequest:
    """Создаёт и распределяет заявку. role — адресат вместо того, что задан темой
    (заявки из нормативного анализа направляются по своим правилам)."""
    created_at = created_at or now()
    model_hours = None
    if topic in routing.TOPICS:
        role, classified_by = role or routing.TOPICS[topic].role, "manual"
    else:
        found = routing.classify(f"{title}. {text}")
        topic, role, classified_by, model_hours = found.topic, found.role, found.by, found.hours
    if effort_hours is not None and effort.is_field(topic):
        estimate = effort.Estimate(effort_hours, effort.complexity_of(effort_hours), "manual")
    else:
        estimate = effort.estimate(topic, f"{title}. {text}", model_hours)
    request = IncomingRequest(
        organization=organization, building=building, location=location, author=author,
        title=title, text=text, kind=kind, topic=topic, routed_role=role,
        classified_by=classified_by, status=S.new, created_at=created_at, parent=parent,
        effort_hours=estimate.hours, complexity=estimate.complexity, effort_by=estimate.by,
        due_at=deadline(kind, topic, created_at, estimate.hours),
    )
    db.add(request)
    db.flush()
    log(request, author, "status", "Заявка создана", created_at)
    if estimate.hours is not None:
        why = f": {', '.join(estimate.reasons)}" if estimate.reasons else ""
        log(request, None, "effort", f"Оценка трудоёмкости — около {estimate.hours:g} ч, "
            f"{COMPLEXITY_TITLES[estimate.complexity]}{why}", created_at)

    assignee, brigade, why = route(db, request)
    due = f"срок {when(request.due_at)}"
    if brigade is not None:
        request.brigade = brigade
        request.status = S.assigned
        db.flush()
        log(request, None, "assignee",
            f"Направлена бригаде «{brigade.name}» ({why})", created_at)
        notify(db, request, list(brigade.members), f"направлена вашей бригаде, {due}",
               skip=author)
    elif assignee is not None:
        request.assignee = assignee
        request.status = S.assigned
        db.flush()
        reason = f" ({why})" if why else ""
        log(request, None, "assignee",
            f"Исполнитель назначен автоматически: {assignee.full_name}{reason}", created_at)
        notify(db, request, [assignee], f"назначена вам, {due}", skip=author)
    if estimate.complexity == Complexity.major and parent is None:
        # Крупную работу видит руководство: её стоит спланировать или разбить на этапы
        managers = [*candidates(db, request, Role.director),
                    *candidates(db, request, Role.municipal_specialist)]
        notify(db, request, managers, f"крупная работа, около {estimate.hours:g} ч — "
               "проверьте срок и при необходимости разбейте на этапы", skip=author)
    return request


def assign(db: Session, request: IncomingRequest, actor: User, assignee: User | None,
           brigade: Brigade | None = None) -> None:
    """Назначает исполнителя или бригаду.

    Новый исполнитель сам берёт заявку в работу, поэтому заявка «в работе» после
    передачи снова становится «назначенной». Если исполнителя сняли и делать заявку
    некому, она возвращается в «новые» — к руководителю, который назначит другого.
    """
    if request.status in FINAL:
        raise Forbidden("Заявка уже закрыта")
    if request.status == S.done:
        raise Forbidden("Работа уже выполнена — её нужно принять или вернуть на доработку")
    moment = now()
    previous = request.assignee
    if brigade is not None:
        if request.brigade_id == brigade.id and request.assignee_id is None:
            return
        # Передать бригаде: возьмёт любой её участник
        request.brigade = brigade
        request.assignee = None
        request.routed_role = Role.brigade
        db.flush()
        log(request, actor, "assignee", f"Передана бригаде «{brigade.name}»", moment)
        if request.status in (S.new, S.in_progress):
            _set_status(request, S.assigned, moment)
        notify(db, request, [m for m in brigade.members if m.is_active],
               "передана вашей бригаде", skip=actor)
        notify(db, request, [previous], f"передана бригаде «{brigade.name}»", skip=actor)
        return
    if assignee is None:
        if previous is None:
            return
        request.assignee = None
        db.flush()
        log(request, actor, "assignee", "Исполнитель снят", moment)
        if request.status in (S.assigned, S.in_progress):
            _set_status(request, S.assigned if request.brigade_id else S.new, moment)
        notify(db, request, [previous], "вы больше не исполнитель", skip=actor)
        return
    if request.assignee_id == assignee.id:
        return
    _give(request, assignee)
    db.flush()
    log(request, actor, "assignee", f"Исполнитель: {assignee.full_name}", moment)
    if request.status in (S.new, S.in_progress):
        _set_status(request, S.assigned, moment)
    notify(db, request, [assignee], f"назначена вам, срок {when(request.due_at)}"
           if request.due_at else "назначена вам", skip=actor)
    notify(db, request, [previous], f"передана другому исполнителю: {assignee.full_name}",
           skip=actor)


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
    # Заявитель может отозвать свою заявку без объяснений, остальным нужна причина
    withdrawn = status == S.rejected and is_author and request.status in ACTIVE
    if (status == S.on_hold or (status == S.rejected and not withdrawn)) and not comment:
        raise Forbidden("Напишите причину — заявитель должен понимать, что происходит")
    if status == S.in_progress and request.status == S.done and not comment:
        raise Forbidden("Напишите, что именно не сделано")
    unfinished = [c for c in request.children if c.status in ACTIVE]
    if status in (S.done, S.closed) and unfinished:
        raise Forbidden(f"Сначала нужно выполнить этапы: не готово {len(unfinished)} "
                        f"из {len(request.children)}")

    returned = request.status == S.done and status == S.in_progress
    previous = request.status
    if manager and request.assignee is None and status in (S.in_progress, S.on_hold, S.done):
        # Кто взялся, тот и исполнитель
        _give(request, actor)
        log(request, actor, "assignee", f"Исполнитель: {actor.full_name}", moment)
    _set_status(request, status, moment)
    if status == S.done:
        request.resolution = comment or request.resolution
    elif returned:
        # Прежний отчёт остаётся в ленте, но в карточке уже не выдаётся за итог
        request.resolution = None
    if status == S.rejected:
        # Отклонили общую заявку — этапы делать больше незачем
        for child in unfinished:
            _set_status(child, S.rejected, moment)
            log(child, actor, "status", "Отклонена вместе с общей заявкой", moment)
            notify(db, child, workers(child), "отклонена вместе с общей заявкой", skip=actor)
    _sync_parent(db, request, moment)
    if returned:
        title = "Возвращена в работу"
    elif withdrawn:
        title = "Отозвана заявителем"
    elif previous == S.on_hold and status == S.in_progress:
        title = "Работа продолжена"
    else:
        title = STATUS_TITLES[status]
    log(request, actor, "status", f"{title}. {comment}" if comment else title, moment)
    notify(db, request, [request.author, *workers(request)],
           title.lower() + (f" — {comment[:200]}" if comment else ""), skip=actor)


def _sync_parent(db: Session, request: IncomingRequest, moment: datetime) -> None:
    """Крупная заявка выполнена, когда выполнены все её этапы; если этап вернули
    на доработку, общая заявка тоже возвращается в работу."""
    parent = request.parent
    if parent is None:
        return
    stages = parent.children
    finished = (S.done, S.closed, S.rejected)
    complete = (all(c.status in finished for c in stages)
                and any(c.status != S.rejected for c in stages))
    if complete and parent.status in ACTIVE:
        _set_status(parent, S.done, moment)
        parent.resolution = parent.resolution or "Все этапы выполнены"
        log(parent, None, "status", "Выполнена: закрыты все этапы", moment)
        notify(db, parent, [parent.author], "все этапы выполнены, проверьте и примите работу")
    elif not complete and parent.status == S.done:
        _set_status(parent, S.in_progress, moment)
        parent.resolution = None
        log(parent, None, "status", f"Возвращена в работу: этап «{request.title}» не выполнен",
            moment)
        notify(db, parent, [parent.author, *workers(parent)],
               f"этап «{request.title}» вернули на доработку")


def split(db: Session, request: IncomingRequest, actor: User,
          stages: list[tuple[str, float | None]]) -> list[IncomingRequest]:
    """Разбивает крупную работу на этапы. Каждый этап — отдельная заявка со своим
    исполнителем и сроком; общая закрывается, когда выполнены все."""
    if not can_manage(actor, request):
        raise Forbidden("Разбить заявку может только тот, кто её ведёт")
    if request.status not in ACTIVE:
        raise Forbidden("Разбить можно только открытую заявку")
    if request.parent_id is not None:
        raise Forbidden("Этап нельзя разбить ещё раз")
    if request.children:
        raise Forbidden("Заявка уже разбита на этапы")
    moment = now()
    children = [
        create(db, actor, request.organization, title=title,
               text=f"Этап заявки № {request.id} «{request.title}». {request.text}",
               kind=request.kind, topic=request.topic, building=request.building,
               location=request.location, parent=request, effort_hours=hours)
        for title, hours in stages
    ]
    if request.status in (S.new, S.assigned):
        _set_status(request, S.in_progress, moment)
    log(request, actor, "status", f"Разбита на этапы: {len(children)}. Заявка будет выполнена, "
        "когда закроют все этапы", moment)
    return children


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
    notify(db, request, [request.author, *workers(request)],
           f"{actor.full_name}: {text[:200]}", skip=actor)


def set_deadline(request: IncomingRequest, actor: User, due_at: datetime) -> None:
    if request.due_at == due_at:
        return
    request.due_at = due_at
    request.last_reminder_on = None
    log(request, actor, "deadline", f"Срок изменён: до {when(due_at)}")


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
            text = f"срок истёк {when(request.due_at)}"
            # О просрочке узнаёт и руководитель учреждения
            recipients = [request.assignee, *candidates(db, request, Role.director)]
        else:
            text = f"срок истекает {when(request.due_at)}"
            recipients = [request.assignee]
        if request.assignee is None and request.brigade is not None:
            recipients += [m for m in request.brigade.members if m.is_active]
        elif request.assignee is None and request.routed_role != Role.brigade:
            # Бригаду могли расформировать — тогда не рассылаем всем бригадам региона
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

        title = routing.TOPICS.get(r.topic, routing.TOPICS["other"]).title
        topic = topics.setdefault(r.topic, {
            "topic": r.topic, "title": title, "total": 0, "active": 0,
            "overdue": 0, "hours": []})
        topic["total"] += 1
        topic["active"] += active
        topic["overdue"] += late

        if active or r.assignee_id is not None:
            # Не взятая заявка бригады числится за бригадой, а не за «не назначен»
            key = r.assignee_id or (f"brigade-{r.brigade_id}" if r.brigade_id else None)
            if r.assignee:
                name = r.assignee.full_name
            elif r.brigade:
                name = f"Бригада «{r.brigade.name}»"
            else:
                name = "Не назначен"
            person = people.setdefault(key, {
                "id": r.assignee_id, "key": str(key), "name": name,
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
        "unassigned": sum(1 for r in requests if r.status in ACTIVE and r.assignee_id is None
                          and r.brigade_id is None),
        "complex": sum(1 for r in requests if r.status in ACTIVE
                       and r.complexity != Complexity.simple),
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

