"""Фоновый процесс: напоминания о сроках, автозакрытие заявок и боты в мессенджерах.

Вынесен из API, чтобы веб-сервер можно было запускать в несколько экземпляров,
не получая дублей уведомлений. Запуск: python -m app.worker
"""

import logging
import time

import httpx

from app.bot.handler import create_bots
from app.config import get_settings
from app.db import SessionLocal
from app.services import helpdesk, workflow

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("worker")


def check_deadlines() -> None:
    with SessionLocal() as db:
        created = workflow.remind_about_deadlines(db)
        requests = helpdesk.run_automation(db)
        db.commit()
    if created:
        log.info("Created %d deadline notifications", len(created))
    if any(requests.values()):
        log.info("Requests: %d reminders, %d closed automatically", requests["reminded"],
                 requests["closed"])


def main() -> None:
    settings = get_settings()
    bots = create_bots()
    interval = settings.deadline_check_interval_min * 60
    next_check = 0.0
    log.info("Worker started, bots: %s", ", ".join(b.transport.name for b in bots) or "none")

    while True:
        if time.monotonic() >= next_check:
            try:
                check_deadlines()
            except Exception:
                log.exception("Deadline check failed")
            next_check = time.monotonic() + interval

        if not bots:
            time.sleep(30)
            continue
        for bot in bots:
            try:
                bot.deliver_notifications()
                bot.poll_once()  # сам ждёт до 25 секунд, отдельная пауза не нужна
            except httpx.HTTPError as exc:
                log.warning("%s is unreachable: %s", bot.transport.name, exc)
                time.sleep(30)


if __name__ == "__main__":
    main()
