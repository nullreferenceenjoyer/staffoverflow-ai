"""Сквозные проверки API: вход, права доступа, заявки и администрирование."""

ANALYST = "analyst@demo.ru"
MUNICIPAL = "municipal@demo.ru"
DIRECTOR = "director@demo.ru"
OBSERVER = "observer@demo.ru"
EXECUTOR = "executor@demo.ru"
EMPLOYEE = "employee@demo.ru"


def test_wrong_password_is_rejected(client):
    response = client.post("/api/auth/login", data={"username": ANALYST, "password": "nope"})
    assert response.status_code == 401


def test_anonymous_request_is_rejected(client):
    assert client.get("/api/requests").status_code == 401


def test_request_is_routed_by_topic(client, login):
    response = client.post("/api/requests", headers=login(DIRECTOR),
                           json={"text": "Не хватает уборщиков, нужна ставка"})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["routed_role"] == "municipal_specialist"
    assert body["classified_by"] == "rules"
    # Исполнитель нашёлся сразу, поэтому заявка не «новая», а уже «назначена»
    assert body["status"] == "assigned"
    assert body["assignee"]["role"] == "municipal_specialist"

    # Директор не ведёт эту заявку: отчитаться за неё не может, только отозвать как автор
    assert body["actions"] == ["rejected"]
    assert client.post(f"/api/requests/{body['id']}/status", headers=login(DIRECTOR),
                       json={"status": "done", "comment": "сами справились"}).status_code == 409


def test_furniture_request_goes_through_all_statuses(client, login):
    employee, executor = login(EMPLOYEE), login(EXECUTOR)
    created = client.post("/api/requests", headers=employee, json={
        "title": "Починить мебель в кабинете 14", "text": "У шкафа отвалилась дверца",
        "location": "каб. 14"})
    assert created.status_code == 201, created.text
    request = created.json()
    url = f"/api/requests/{request['id']}"
    assert (request["topic"], request["kind"], request["status"]) == (
        "furniture", "planned", "assigned")
    # Плановая заявка на мебель — неделя, исполнитель — хозяйственная служба учреждения
    assert request["assignee"]["role"] == "executor"
    assert request["due_at"][:10] > request["created_at"][:10]
    # Пока работа не сделана, заявитель может только отозвать заявку, и ход не за ним
    assert request["actions"] == ["rejected"]
    assert request["my_turn"] is None
    assert client.get(url, headers=executor).json()["my_turn"] == "Возьмите заявку в работу"

    # Вопрос исполнителя ставит заявку на паузу, ответ заявителя возвращает в работу
    paused = client.post(f"{url}/comments", headers=executor,
                         json={"text": "Какой именно шкаф?", "needs_reply": True}).json()
    assert paused["status"] == "on_hold"
    resumed = client.post(f"{url}/comments", headers=employee,
                          json={"text": "Книжный, у окна"}).json()
    assert resumed["status"] == "in_progress"
    assert resumed["due_at"] >= request["due_at"]

    # Отчитаться без права нельзя, вернуть без объяснения — тоже
    assert client.post(f"{url}/status", headers=employee,
                       json={"status": "done"}).status_code == 409
    done = client.post(f"{url}/status", headers=executor,
                       json={"status": "done", "comment": "Петли заменены"}).json()
    assert (done["status"], done["resolution"]) == ("done", "Петли заменены")
    assert client.get(url, headers=employee).json()["my_turn"] == "Проверьте работу и примите её"
    assert client.post(f"{url}/status", headers=employee,
                       json={"status": "in_progress"}).status_code == 409
    closed = client.post(f"{url}/status", headers=employee, json={"status": "closed"}).json()
    assert closed["status"] == "closed"
    assert closed["closed_at"]

    kinds = [event["kind"] for event in closed["events"]]
    assert kinds.count("comment") == 2
    assert "assignee" in kinds
    # В закрытую заявку писать уже нельзя
    assert client.post(f"{url}/comments", headers=employee,
                       json={"text": "спасибо"}).status_code == 409

    # Исполнителю пришло уведомление о назначении, заявителю — о выполнении
    notes = client.get("/api/notifications", headers=employee).json()
    assert any(n["request_id"] == request["id"] and "выполнена" in n["text"] for n in notes)


def test_author_can_withdraw_request_without_reason(client, login):
    employee, executor = login(EMPLOYEE), login(EXECUTOR)
    request = client.post("/api/requests", headers=employee,
                          json={"title": "Не работает розетка в кабинете 3"}).json()
    url = f"/api/requests/{request['id']}"
    # Исполнитель без причины отклонить не может, а заявитель отзывает свою молча
    assert client.post(f"{url}/status", headers=executor,
                       json={"status": "rejected"}).status_code == 409
    withdrawn = client.post(f"{url}/status", headers=employee,
                            json={"status": "rejected"}).json()
    assert withdrawn["status"] == "rejected"
    assert withdrawn["events"][-1]["text"] == "Отозвана заявителем"
    assert withdrawn["actions"] == []


def test_emergency_request_gets_short_deadline(client, login):
    from datetime import datetime

    body = client.post("/api/requests", headers=login(EMPLOYEE), json={
        "title": "Прорвало трубу в подвале", "kind": "emergency"}).json()
    assert body["topic"] == "plumbing"
    spent = datetime.fromisoformat(body["due_at"]) - datetime.fromisoformat(body["created_at"])
    assert spent.total_seconds() == 4 * 3600


def test_employee_sees_only_own_requests(client, login):
    employee = login(EMPLOYEE)
    own = client.get("/api/requests", headers=employee).json()
    assert own and all(r["is_author"] for r in own)
    everything = client.get("/api/requests", headers=login(ANALYST)).json()
    assert len(everything) > len(own)

    foreign = next(r for r in everything if not any(r["id"] == o["id"] for o in own))
    assert client.get(f"/api/requests/{foreign['id']}", headers=employee).status_code == 404

    # Справочники для формы заявки доступны, и учреждение в них только своё
    meta = client.get("/api/requests/meta", headers=employee).json()
    assert len(meta["organizations"]) == 1
    assert meta["organizations"][0]["buildings"]


def test_request_can_be_reassigned_only_to_someone_from_the_organization(client, login):
    director = login(DIRECTOR)
    request = client.post("/api/requests", headers=login(EMPLOYEE),
                          json={"title": "Не горит лампа в коридоре"}).json()
    details = client.get(f"/api/requests/{request['id']}", headers=director).json()
    assert details["can_manage"]
    me = client.get("/api/auth/me", headers=director).json()
    assert me["id"] in {p["id"] for p in details["assignable"]}

    moved = client.patch(f"/api/requests/{request['id']}", headers=director,
                         json={"assignee_id": me["id"]}).json()
    assert moved["assignee"]["id"] == me["id"]
    observer = client.get("/api/auth/me", headers=login(OBSERVER)).json()
    assert client.patch(f"/api/requests/{request['id']}", headers=director,
                        json={"assignee_id": observer["id"]}).status_code == 422


def test_request_stats_for_dashboard(client, login):
    stats = client.get("/api/requests/stats", headers=login(ANALYST)).json()
    assert stats["total"] == sum(item["count"] for item in stats["by_status"])
    assert stats["active"] > 0
    assert len(stats["flow"]) == 30
    assert stats["by_topic"][0]["total"] >= stats["by_topic"][-1]["total"]
    assert 0 <= stats["in_time_pct"] <= 100
    assert stats["my_turn"] >= 0


def test_observer_cannot_change_anything(client, login):
    headers = login(OBSERVER)
    assert client.post("/api/requests", headers=headers,
                       json={"title": "Починить парту"}).status_code == 403
    assert client.get("/api/users", headers=headers).status_code == 403


def test_director_sees_requests_of_own_organization_only(client, login):
    director = login(DIRECTOR)
    me = client.get("/api/auth/me", headers=director).json()
    requests = client.get("/api/requests", headers=director).json()
    assert requests
    assert {r["organization_id"] for r in requests} == {me["organization_id"]}
    meta = client.get("/api/requests/meta", headers=director).json()
    assert [o["id"] for o in meta["organizations"]] == [me["organization_id"]]


def test_admin_binds_user_to_organization(client, login):
    admin = login("admin@example.ru", "admin")
    organizations = client.get("/api/organizations", headers=admin).json()
    assert len(organizations) == 8
    # Справочник учреждений нужен только администратору
    assert client.get("/api/organizations", headers=login(DIRECTOR)).status_code == 403

    org = organizations[-1]
    body = {"email": "new.executor@demo.ru", "full_name": "Новиков С. А.",
            "password": "secret123", "role": "executor"}
    # Без учреждения хозяйственную службу не завести
    assert client.post("/api/users", headers=admin, json=body).status_code == 422
    assert client.post("/api/users", headers=admin,
                       json={**body, "organization_id": 999_999}).status_code == 422
    created = client.post("/api/users", headers=admin, json={**body, "organization_id": org["id"]})
    assert created.status_code == 201, created.text
    user = created.json()
    assert user["organization_id"] == org["id"]

    other = organizations[0]
    moved = client.patch(f"/api/users/{user['id']}", headers=admin,
                         json={"organization_id": other["id"]})
    assert moved.json()["organization_id"] == other["id"]

    # После переноса исполнитель работает уже с другим учреждением
    executor = login("new.executor@demo.ru", "secret123")
    meta = client.get("/api/requests/meta", headers=executor).json()
    assert meta["organizations"][0]["id"] == other["id"]
