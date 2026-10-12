"""Бот руководителя: команды и ответы, общие для всех мессенджеров.

Пользователь привязывается по идентификатору чата: бот сообщает его незнакомому
собеседнику, а администратор вписывает в карточку пользователя.

Команды:
  /summary     — сводка по доступным данным
  /goal        — где проект относительно цели паспорта
  /deviations  — крупнейшие отклонения
  /projects    — проекты на согласовании с кнопками решения
  любой текст  — вопрос ИИ-помощнику
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.deps import APPROVERS, Scope, audit
from app.models import Notification, Project, ProjectStatus, User
from app.services import analytics, assistant
from app.services import program as program_service
from app.services.staffing import ru

from .transports import Incoming, MaxTransport, TelegramTransport, Transport

log = logging.getLogger(__name__)

HELP = ("/summary — сводка\n/goal — цель проекта\n/deviations — отклонения\n"
        "/projects — проекты на согласовании\nИли просто задайте вопрос текстом.")


def _money(value: float) -> str:
    return f"{ru(round(value / 1_000_000, 1))} млн ₽"


class Bot:
    def __init__(self, transport: Transport):
        self.transport = transport

    def poll_once(self) -> None:
        for incoming in self.transport.poll():
            try:
                with SessionLocal() as db:
                    self._handle(db, incoming)
            except Exception:
                log.exception("Failed to handle %s update", self.transport.name)

    def deliver_notifications(self) -> None:
        """Рассылает уведомления о сроках тем, у кого привязан чат этого мессенджера."""
        chat_column = getattr(User, self.transport.user_field)
        sent_column = getattr(Notification, f"sent_to_{self.transport.name}")
        with SessionLocal() as db:
            rows = db.execute(
                select(Notification, chat_column)
                .join(User, User.id == Notification.user_id)
                .where(sent_column.is_(False), chat_column.is_not(None))
                .limit(50)
            ).all()
            for notification, chat_id in rows:
                self.transport.send(chat_id, "⏰ " + notification.text)
                setattr(notification, f"sent_to_{self.transport.name}", True)
            db.commit()

    def _handle(self, db: Session, incoming: Incoming) -> None:
        send = self.transport.send
        chat_id = incoming.chat_id
        chat_column = getattr(User, self.transport.user_field)
        user = db.scalar(select(User).where(chat_column == chat_id, User.is_active))
        if user is None:
            send(chat_id, "Этот чат не привязан к учётной записи. Передайте администратору "
                          f"системы идентификатор чата: {chat_id}")
            return
        scope = Scope(user, db)

        if incoming.callback_data is not None:
            if incoming.callback_id:
                self.transport.ack(incoming.callback_id)
            self._decide(scope, chat_id, incoming.callback_data)
            return

        text = incoming.text
        if not text:
            send(chat_id, "Пока понимаю только текстовые сообщения.")
        elif text.startswith(("/start", "/help")):
            send(chat_id, f"Здравствуйте, {user.full_name}.\n{HELP}")
        elif text.startswith("/summary"):
            send(chat_id, self._summary(scope))
        elif text.startswith("/goal"):
            send(chat_id, self._goal(scope))
        elif text.startswith("/deviations"):
            send(chat_id, self._deviations(scope))
        elif text.startswith("/projects"):
            self._projects(scope, chat_id)
        else:
            self.transport.typing(chat_id)
            send(chat_id, assistant.answer(scope, text))

    def _summary(self, scope: Scope) -> str:
        s = analytics.summarize(analytics.load_reports(scope.db, scope.org_ids()))
        return (
            f"Учреждений: {s['organizations']}, обучающихся: {s['students']}\n"
            f"Факт: {ru(s['actual_total'])} ст., норматив: {ru(s['norm_total'])} ст.\n"
            f"Избыток: {ru(s['surplus'])} ст., нехватка: {ru(s['shortage'])} ст.\n"
            f"Соответствие нормативам: {ru(s['compliance'])} %\n"
            f"Потенциал экономии ФОТ: {_money(s['saving_potential_year'])} в год"
        )

    def _goal(self, scope: Scope) -> str:
        program = program_service.find_visible(scope.db, scope)
        if program is None:
            return "Паспорт проекта не заведён."
        board = program_service.scoreboard(
            program, program_service.program_reports(scope.db, program)
        )
        lines = [
            f"Цель: −{ru(board['target_pct'])} % ФОТ АУП и ВП к {program.end_date:%d.%m.%Y}",
            f"Достигнуто: {ru(board['done_pct'])} % ({_money(board['done_saving_year'])})",
            f"Осталось дней: {board['days_left']}",
        ]
        for item in board["categories"]:
            title = "АУП" if item["category"] == "admin" else "ВП"
            lines.append(f"{title}: сокращено {ru(item['done_rates'])} из "
                         f"{ru(item['plan_rates'])} ст.")
        return "\n".join(lines)

    def _deviations(self, scope: Scope) -> str:
        reports = analytics.load_reports(scope.db, scope.org_ids())
        rows = analytics.top_deviations(reports, limit=10)
        if not rows:
            return "Существенных отклонений нет."
        return "Крупнейшие отклонения:\n" + "\n".join(
            f"• {r['organization']} — {r['title']}: {'+' if r['delta'] > 0 else ''}"
            f"{ru(r['delta'])} ст." for r in rows
        )

    def _projects(self, scope: Scope, chat_id: int) -> None:
        projects = [
            p for p in scope.db.scalars(
                select(Project).where(Project.status == ProjectStatus.review)
            ) if scope.can_see_project(p)
        ]
        if not projects:
            self.transport.send(chat_id, "Проектов на согласовании нет.")
            return
        can_approve = scope.user.role in APPROVERS
        for project in projects[:10]:
            text = (f"{project.title}\nИзменение: {ru(float(project.rate_delta))} ст., "
                    f"ФОТ: {_money(float(project.fot_effect_year))} в год")
            buttons = [("✅ Утвердить", f"approve:{project.id}"),
                       ("↩️ Отклонить", f"reject:{project.id}")] if can_approve else None
            self.transport.send(chat_id, text, buttons)

    def _decide(self, scope: Scope, chat_id: int, data: str) -> None:
        action, _, raw_id = data.partition(":")
        if action not in ("approve", "reject") or not raw_id.isdigit():
            return
        if scope.user.role not in APPROVERS:
            self.transport.send(chat_id, "Недостаточно прав для утверждения.")
            return
        project = scope.db.get(Project, int(raw_id))
        if project is None or project.status != ProjectStatus.review:
            self.transport.send(chat_id, "Проект уже рассмотрен или не найден.")
            return
        project.status = ProjectStatus.approved if action == "approve" else ProjectStatus.rejected
        project.decided_by_id = scope.user.id
        project.decided_at = datetime.now(UTC)
        audit(scope.db, scope.user, "project_status_changed", entity="project",
              entity_id=project.id, details={"to": project.status, "via": self.transport.name})
        scope.db.commit()
        verdict = "утверждён" if action == "approve" else "отклонён"
        self.transport.send(chat_id, f"Проект «{project.title}» {verdict}.")


def create_bots() -> list[Bot]:
    settings = get_settings()
    bots = []
    if settings.max_bot_token:
        bots.append(Bot(MaxTransport(settings.max_bot_token, settings.max_api_url)))
    if settings.telegram_bot_token:
        bots.append(Bot(TelegramTransport(settings.telegram_bot_token)))
    return bots
