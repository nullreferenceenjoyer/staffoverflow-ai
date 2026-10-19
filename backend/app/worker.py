"""Фоновый процесс: напоминания о сроках заявок и автозакрытие выполненных.

Вынесен из API, чтобы веб-сервер можно было запускать в несколько экземпляров,
не получая дублей уведомлений. Запуск: python -m app.worker
"""

import logging
import time

from app.config import get_settings
from app.db import SessionLocal
from app.services import helpdesk

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("worker")


def check_deadlines() -> None:
    with SessionLocal() as db:
        result = helpdesk.run_automation(db)
        db.commit()
    if any(result.values()):
        log.info("Requests: %d reminders, %d closed automatically", result["reminded"],
                 result["closed"])


def main() -> None:
    interval = get_settings().deadline_check_interval_min * 60
    log.info("Worker started, checking deadlines every %d min", interval // 60)
    while True:
        try:
            check_deadlines()
        except Exception:
            log.exception("Deadline check failed")
        time.sleep(interval)


if __name__ == "__main__":
    main()
