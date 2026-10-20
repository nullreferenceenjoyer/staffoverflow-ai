"""Переходы статусов на краях: переназначение, этапы, закрытые заявки, события в реальном
времени. Нужен PostgreSQL, как и test_api.py."""

import json

import pytest

DIRECTOR = "director@demo.ru"
EXECUTOR = "executor@demo.ru"
MUNICIPAL = "municipal@demo.ru"
ADMIN = ("admin@example.ru", "admin")
# Свой заявитель: demo-сотрудника другие тесты переводят в другое учреждение
EMPLOYEE = "status.author@demo.ru"


@pytest.fixture(scope="module", autouse=True)
def author(client, login):
    org_id = client.get("/api/auth/me", headers=login(DIRECTOR)).json()["organization_id"]
    created = client.post("/api/users", headers=login(*ADMIN), json={
        "email": EMPLOYEE, "full_name": "Заявкина А. А.", "password": "demo12345",
        "role": "employee", "organization_id": org_id})
    assert created.status_code == 201, created.text


def new_request(client, login, title="Не закрывается дверца шкафа в кабинете 5") -> dict:
    """Заявка сотрудника, которую ведёт демо-исполнитель (executor@demo.ru).

    Хозслужб в учреждении может быть несколько (их добавляют другие тесты), поэтому
    исполнителя закрепляем явно, а не полагаемся на выбор наименее загруженного."""
    created = client.post("/api/requests", headers=login(EMPLOYEE), json={"title": title})
    assert created.status_code == 201, created.text
    request = created.json()
    executor = client.get("/api/auth/me", headers=login(EXECUTOR)).json()
    if request["assignee"] is None or request["assignee"]["id"] != executor["id"]:
        moved = client.patch(f"/api/requests/{request['id']}", headers=login(DIRECTOR),
                             json={"assignee_id": executor["id"]})
        assert moved.status_code == 200, moved.text
        request = moved.json()
    return request


def test_removed_assignee_returns_request_to_manager(client, login):
    director, executor = login(DIRECTOR), login(EXECUTOR)
    request = new_request(client, login)
    url = f"/api/requests/{request['id']}"
    taken = client.post(f"{url}/status", headers=executor, json={"status": "in_progress"}).json()
    assert taken["status"] == "in_progress"

    # Исполнителя сняли — делать заявку некому, и она не висит «в работе» без хозяина
    removed = client.patch(url, headers=director, json={"assignee_id": None}).json()
    assert (removed["status"], removed["assignee"]) == ("new", None)
    assert removed["my_turn"] == "Назначьте исполнителя"
    # Повторное снятие ничего не пишет в ленту
    again = client.patch(url, headers=director, json={"assignee_id": None}).json()
    assert len(again["events"]) == len(removed["events"])

    # Бывший исполнитель узнал, что заявка больше не его
    notes = client.get("/api/notifications", headers=executor).json()
    assert any(n["request_id"] == request["id"] and "больше не исполнитель" in n["text"]
               for n in notes)


def test_new_assignee_takes_request_into_work_himself(client, login):
    director, executor = login(DIRECTOR), login(EXECUTOR)
    me = client.get("/api/auth/me", headers=director).json()
    request = new_request(client, login)
    url = f"/api/requests/{request['id']}"
    client.post(f"{url}/status", headers=executor, json={"status": "in_progress"})

    moved = client.patch(url, headers=director, json={"assignee_id": me["id"]}).json()
    assert (moved["status"], moved["assignee"]["id"]) == ("assigned", me["id"])
    assert moved["my_turn"] == "Возьмите заявку в работу"


def test_done_and_closed_requests_are_not_edited(client, login):
    director, executor, employee = login(DIRECTOR), login(EXECUTOR), login(EMPLOYEE)
    request = new_request(client, login)
    url = f"/api/requests/{request['id']}"
    client.post(f"{url}/status", headers=executor, json={"status": "done", "comment": "Готово"})

    # Выполненную не переназначают: её принимают или возвращают
    assert client.patch(url, headers=director, json={"assignee_id": None}).status_code == 409
    returned = client.post(f"{url}/status", headers=employee,
                           json={"status": "in_progress", "comment": "Дверца снова открыта"})
    assert returned.json()["status"] == "in_progress"
    # Старый отчёт больше не выдаётся за итог работы
    assert returned.json()["resolution"] is None

    client.post(f"{url}/status", headers=executor, json={"status": "done", "comment": "Петли"})
    client.post(f"{url}/status", headers=employee, json={"status": "closed"})
    assert client.patch(url, headers=director, json={"kind": "urgent"}).status_code == 409
    assert client.patch(url, headers=director,
                        json={"due_at": "2030-01-01T10:00:00"}).status_code == 409


def test_deadline_without_timezone_and_in_the_past(client, login):
    director = login(DIRECTOR)
    request = new_request(client, login)
    url = f"/api/requests/{request['id']}"
    # Время без часового пояса принимается, а не роняет сервер сравнением сроков
    moved = client.patch(url, headers=director, json={"due_at": "2030-01-01T10:00:00"})
    assert moved.status_code == 200, moved.text
    assert moved.json()["due_at"].startswith("2030-01-01T10:00:00")
    assert client.patch(url, headers=director,
                        json={"due_at": "2001-01-01T10:00:00Z"}).status_code == 422


def test_handover_to_brigade_resets_work_and_notifies_members(client, login):
    director, executor = login(DIRECTOR), login(EXECUTOR)
    request = new_request(client, login, "Починить стул в кабинете 7")
    url = f"/api/requests/{request['id']}"
    client.post(f"{url}/status", headers=executor, json={"status": "in_progress"})
    brigade = next(b for b in client.get(url, headers=director).json()["brigades"] if b["serves"])

    moved = client.patch(url, headers=director, json={"brigade_id": brigade["id"]}).json()
    assert (moved["status"], moved["assignee"], moved["brigade"]["id"]) == (
        "assigned", None, brigade["id"])

    # Директор берёт сам: бригада с заявки снимается, ответственный — он
    taken = client.post(f"{url}/status", headers=director, json={"status": "in_progress"}).json()
    assert taken["brigade"] is None
    assert taken["assignee"]["role"] == "director"


def test_stages_follow_the_parent_request(client, login):
    municipal, director = login(MUNICIPAL), login(DIRECTOR)
    body = client.post("/api/requests", headers=director, json={
        "title": "Покрасить стены во всех кабинетах второго этажа"}).json()
    url = f"/api/requests/{body['id']}"
    parent = client.post(f"{url}/split", headers=municipal, json={"stages": [
        {"title": "Подготовить стены", "hours": 8}, {"title": "Покрасить", "hours": 8}]}).json()
    first, second = (c["id"] for c in parent["children"])

    # Пока этапы не выполнены, общую заявку не отметить выполненной
    early = client.post(f"{url}/status", headers=municipal,
                        json={"status": "done", "comment": "всё"})
    assert early.status_code == 409
    assert "этапы" in early.json()["detail"]

    for stage in (first, second):
        client.post(f"/api/requests/{stage}/status", headers=municipal,
                    json={"status": "done", "comment": "Сделано"})
    assert client.get(url, headers=director).json()["status"] == "done"

    # Этап вернули — общая заявка снова в работе
    back = client.post(f"/api/requests/{second}/status", headers=municipal,
                       json={"status": "in_progress", "comment": "Пропущен угол"})
    assert back.status_code == 200, back.text
    assert client.get(url, headers=director).json()["status"] == "in_progress"

    # Отклонили общую — открытые этапы отклоняются вместе с ней
    rejected = client.post(f"{url}/status", headers=municipal,
                           json={"status": "rejected", "comment": "Перенесли на лето"}).json()
    assert rejected["status"] == "rejected"
    assert client.get(f"/api/requests/{second}", headers=municipal).json()["status"] == "rejected"
    assert client.get(f"/api/requests/{first}", headers=municipal).json()["status"] == "done"


def test_list_can_be_reloaded_by_ids(client, login):
    employee = login(EMPLOYEE)
    new_request(client, login)
    own = client.get("/api/requests", headers=employee).json()
    everything = client.get("/api/requests", headers=login(DIRECTOR)).json()
    foreign = next(r["id"] for r in everything if not any(o["id"] == r["id"] for o in own))
    picked = client.get("/api/requests", headers=employee,
                        params={"ids": f"{own[0]['id']},{foreign}"}).json()
    # Чужая заявка не вернётся, даже если спросить её номер
    assert [r["id"] for r in picked] == [own[0]["id"]]
    assert client.get("/api/requests", headers=employee,
                      params={"ids": "abc"}).status_code == 422


def test_change_is_announced_to_listeners_after_commit(client, login):
    import psycopg

    from app.config import get_settings
    from app.services import live

    dsn = get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(f"LISTEN {live.CHANNEL}")
        request = new_request(client, login)
        executor = client.get("/api/auth/me", headers=login(EXECUTOR)).json()
        payloads = [json.loads(n.payload) for n in conn.notifies(timeout=1)]
    assert payloads, "после создания заявки нет NOTIFY"
    changes = [r for p in payloads for r in p.get("requests", ()) if r["id"] == request["id"]]
    assert changes
    assert any(executor["id"] in r["people"] for r in changes)
    assert all(r["org"] == request["organization_id"] for r in changes)
    # Исполнителю ушло уведомление о назначении — его колокольчик тоже обновится
    assert any(executor["id"] in p.get("users", ()) for p in payloads)


def test_failed_change_is_not_announced(client, login):
    import psycopg

    from app.config import get_settings
    from app.services import live

    request = new_request(client, login)
    dsn = get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(f"LISTEN {live.CHANNEL}")
        # Отказ без причины: транзакция откатывается, и NOTIFY не уходит
        refused = client.post(f"/api/requests/{request['id']}/status", headers=login(EXECUTOR),
                              json={"status": "rejected"})
        assert refused.status_code == 409
        assert list(conn.notifies(timeout=0.5, stop_after=1)) == []


def test_model_status_details_are_for_admin_only(client, login):
    admin = client.get("/api/llm/status", headers=login(*ADMIN)).json()
    assert (admin["configured"], admin["available"]) == (False, False)
    assert "LLM_BASE_URL" in admin["error"]
    employee = client.get("/api/llm/status", headers=login(EMPLOYEE)).json()
    assert employee["available"] is False
    assert "error" not in employee
    assert client.post("/api/llm/check", headers=login(EMPLOYEE)).status_code == 403
    assert client.get("/api/events").status_code == 401


def test_admins_are_told_when_model_is_down(client, login):
    from app import worker
    from app.db import SessionLocal

    state = {"configured": True, "available": False, "error": "connection refused"}
    with SessionLocal() as db:
        assert worker.notify_admins(db, worker.llm_alert(state)) == 1
        db.commit()
        # Повтор того же предупреждения в течение суток не дублируется
        assert worker.notify_admins(db, worker.llm_alert(state)) == 0
    notes = client.get("/api/notifications", headers=login(*ADMIN)).json()
    assert any("connection refused" in n["text"] and n["request_id"] is None for n in notes)
