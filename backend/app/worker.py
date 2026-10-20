"""Фоновый процесс: напоминания о сроках заявок, автозакрытие выполненных
и присмотр за локальной моделью.

Вынесен из API, чтобы веб-сервер можно было запускать в несколько экземпляров,
не получая дублей уведомлений. Запуск: python -m app.worker
"""

import logging
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.models import Notification, Role, User
from app.services import helpdesk, llm, staffing_analysis

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("worker")

STAFFING_EVERY_S = 24 * 3600

# Одинаковое предупреждение о модели администратор получает не чаще раза в сутки,
# даже если worker перезапускали
LLM_ALERT_REPEAT = timedelta(hours=24)


def check_deadlines() -> None:
    with SessionLocal() as db:
        result = helpdesk.run_automation(db)
        db.commit()
    if any(result.values()):
        log.info("Requests: %d reminders, %d closed automatically", result["reminded"],
                 result["closed"])


def recalculate_staffing() -> None:
    """Нормативы действуют с даты и до даты, поэтому картина меняется и без правок:
    раз в сутки пересчитываем анализ нормативной численности."""
    with SessionLocal() as db:
        years = staffing_analysis.recalculate_all(db)
        db.commit()
    log.info("Staffing analysis recalculated for %d academic years", years)


def llm_alert(state: dict) -> str:
    if not state["configured"]:
        return ("Языковая модель не подключена: тема новых заявок определяется по ключевым "
                "словам. Чтобы включить модель, задайте LLM_BASE_URL в .env (см. README).")
    if state["available"]:
        return "Языковая модель снова отвечает: тема новых заявок определяется моделью."
    return (f"Языковая модель не работает — {state['error']}. Пока её не починят, тема новых "
            "заявок определяется по ключевым словам: проверяйте её в карточке заявки.")


def notify_admins(db: Session, text: str, moment: datetime | None = None) -> int:
    moment = moment or datetime.now(UTC)
    admins = db.scalars(select(User).where(User.role == Role.admin, User.is_active)).all()
    sent = 0
    for admin in admins:
        repeated = db.scalar(select(Notification.id).where(
            Notification.user_id == admin.id, Notification.text == text,
            Notification.created_at > moment - LLM_ALERT_REPEAT).limit(1))
        if repeated is None:
            db.add(Notification(user_id=admin.id, text=text))
            sent += 1
    return sent


class LLMWatch:
    """Следит за моделью и сообщает администраторам, когда она пропала или вернулась."""

    def __init__(self):
        self.known: bool | None = None  # что было при прошлой проверке

    def tick(self) -> None:
        state = llm.check()
        available = bool(state["available"])
        # При старте сообщаем только о проблеме, «всё работает» — только после сбоя
        if available == self.known or (self.known is None and available):
            self.known = available
            return
        self.known = available
        with SessionLocal() as db:
            if notify_admins(db, llm_alert(state)):
                log.info("Admins notified: LLM %s", "available" if available else "unavailable")
            db.commit()


def main() -> None:
    settings = get_settings()
    deadlines_every = settings.deadline_check_interval_min * 60
    llm_every = max(settings.llm_check_interval_s, 10)
    log.info("Worker started, checking deadlines every %d min, LLM every %d s",
             deadlines_every // 60, llm_every)
    watch = LLMWatch()
    next_deadlines = next_llm = 0.0
    # Первый пересчёт — через час после старта: при запуске API анализ уже досчитывается сам
    next_staffing = time.monotonic() + 3600
    while True:
        moment = time.monotonic()
        if moment >= next_staffing:
            next_staffing = moment + STAFFING_EVERY_S
            try:
                recalculate_staffing()
            except Exception:
                log.exception("Staffing recalculation failed")
        if moment >= next_deadlines:
            next_deadlines = moment + deadlines_every
            try:
                check_deadlines()
            except Exception:
                log.exception("Deadline check failed")
        if moment >= next_llm:
            next_llm = moment + llm_every
            try:
                watch.tick()
            except Exception:
                log.exception("LLM check failed")
        time.sleep(max(min(next_deadlines, next_llm, next_staffing) - time.monotonic(), 1))


if __name__ == "__main__":
    main()
