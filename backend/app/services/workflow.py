"""Сценарии работ: запуск цепочки задач по шаблону и контроль сроков."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Notification, Project, Role, Task, TaskStatus, User, WorkflowTemplate


def start_run(db: Session, template: WorkflowTemplate, project: Project | None,
              municipality_id: int | None, start: date | None = None) -> list[Task]:
    """Создаёт задачи по шагам шаблона. Сроки идут друг за другом: каждый следующий
    шаг отсчитывается от планового окончания предыдущего."""
    run_id = uuid.uuid4().hex
    due = start or date.today()
    tasks = []
    for index, step in enumerate(template.steps):
        due += timedelta(days=int(step.get("duration_days", 3)))
        title = step["title"]
        if project is not None:
            title = f"{title} — {project.title}"
        tasks.append(Task(
            project_id=project.id if project else None,
            run_id=run_id,
            step_index=index,
            title=title[:300],
            assignee_role=step.get("role", Role.municipal_specialist),
            municipality_id=municipality_id,
            status=TaskStatus.todo if index == 0 else TaskStatus.waiting,
            duration_days=int(step.get("duration_days", 3)),
            due_date=due,
        ))
    db.add_all(tasks)
    return tasks


def set_status(db: Session, task: Task, status: TaskStatus) -> None:
    task.status = status
    if status != TaskStatus.done:
        task.completed_at = None
        return
    task.completed_at = datetime.now(UTC)
    if task.run_id is None:
        return
    # Открываем следующий шаг цепочки
    following = db.scalar(
        select(Task)
        .where(Task.run_id == task.run_id, Task.step_index == task.step_index + 1)
    )
    if following is not None and following.status == TaskStatus.waiting:
        following.status = TaskStatus.todo


def recipients(db: Session, task: Task) -> list[User]:
    """Кому напоминать: назначенному исполнителю, а если его нет — всем с нужной ролью."""
    if task.assignee_id:
        user = db.get(User, task.assignee_id)
        return [user] if user and user.is_active else []
    query = select(User).where(User.role == task.assignee_role, User.is_active)
    if task.assignee_role == Role.municipal_specialist and task.municipality_id:
        query = query.where(User.municipality_id == task.municipality_id)
    if task.assignee_role == Role.director and task.project and task.project.organization_id:
        query = query.where(User.organization_id == task.project.organization_id)
    return list(db.scalars(query))


def remind_about_deadlines(db: Session, today: date | None = None) -> list[Notification]:
    """Создаёт уведомления по задачам, срок которых близко или уже прошёл.
    По одной задаче — не чаще раза в день."""
    today = today or date.today()
    horizon = today + timedelta(days=get_settings().deadline_warn_days)
    tasks = db.scalars(
        select(Task)
        .where(Task.status.in_((TaskStatus.todo, TaskStatus.in_progress)))
        .where(Task.due_date.is_not(None), Task.due_date <= horizon)
        .where((Task.last_reminder_on.is_(None)) | (Task.last_reminder_on < today))
    ).all()

    created = []
    for task in tasks:
        days_left = (task.due_date - today).days
        if days_left < 0:
            text = f"Просрочена задача «{task.title}»: срок был {task.due_date:%d.%m.%Y}"
        elif days_left == 0:
            text = f"Сегодня срок по задаче «{task.title}»"
        else:
            text = f"До срока по задаче «{task.title}» осталось дней: {days_left}"
        for user in recipients(db, task):
            notification = Notification(user_id=user.id, task_id=task.id, text=text)
            db.add(notification)
            created.append(notification)
        task.last_reminder_on = today
    return created
