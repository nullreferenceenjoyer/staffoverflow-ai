"""Сквозные проверки API: права доступа, импорт, жизненный цикл проекта и задач."""

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
    assert client.get("/api/dashboard").status_code == 401


def test_director_sees_only_own_organization(client, login):
    own = client.get("/api/organizations", headers=login(DIRECTOR)).json()
    everything = client.get("/api/organizations", headers=login(ANALYST)).json()
    assert len(own) == 1
    assert len(everything) == 8

    foreign = next(o for o in everything if o["id"] != own[0]["id"])
    response = client.get(f"/api/organizations/{foreign['id']}", headers=login(DIRECTOR))
    assert response.status_code == 404


def test_municipal_specialist_is_limited_to_municipality(client, login):
    organizations = client.get("/api/organizations", headers=login(MUNICIPAL)).json()
    assert organizations
    assert len({o["municipality_id"] for o in organizations}) == 1

    dashboard = client.get("/api/dashboard", headers=login(MUNICIPAL)).json()
    assert dashboard["organizations"] == len(organizations)


def test_observer_cannot_change_anything(client, login):
    headers = login(OBSERVER)
    org_id = client.get("/api/organizations", headers=headers).json()[0]["id"]

    assert client.post("/api/projects/generate", headers=headers,
                       json={"kind": "normalization", "organization_id": org_id}).status_code == 403
    assert client.post(f"/api/organizations/{org_id}/positions", headers=headers,
                       json={"title": "Учитель", "rate": 1}).status_code == 403
    assert client.get("/api/users", headers=headers).status_code == 403


def test_import_pseudonymizes_employees_and_recalculates(client, login):
    headers = login(MUNICIPAL)
    org = client.get("/api/organizations", headers=headers).json()[0]
    csv = (
        "Организация;Должность;Количество ставок;ФОТ;ФИО;Паспорт\n"
        f"{org['name']};Директор;1;120000;Иванов Иван Иванович;4510 123456\n"
        f"{org['name']};Уборщик служебных помещений;0,5;15000;;\n"
        "Чужая школа;Учитель;1;60000;Петров П. П.;\n"
    )
    response = client.post("/api/import/staffing", headers=headers,
                           files={"file": ("staff.csv", csv.encode("cp1251"), "text/csv")},
                           data={"replace": "true"})
    assert response.status_code == 200, response.text
    result = response.json()
    assert (result["imported"], result["skipped"]) == (2, 1)
    assert result["dropped_columns"] == ["паспорт"]

    positions = client.get(f"/api/organizations/{org['id']}/positions", headers=headers).json()
    assert len(positions) == 2
    director = next(p for p in positions if p["function_code"] == "director")
    assert director["employee_ref"] and "Иванов" not in director["employee_ref"]
    vacancy = next(p for p in positions if p["function_code"] == "cleaning")
    assert vacancy["employee_ref"] is None

    # После замены расписания в учреждении 1,5 ставки — отчёт должен это отражать
    report = client.get(f"/api/organizations/{org['id']}", headers=headers).json()
    assert report["actual"] == 1.5
    assert report["shortage"] > 0


def test_project_lifecycle(client, login):
    municipal, analyst = login(MUNICIPAL), login(ANALYST)
    municipality_id = client.get("/api/municipalities", headers=municipal).json()[0]["id"]

    response = client.post("/api/projects/generate", headers=municipal,
                           json={"kind": "centralization", "municipality_id": municipality_id})
    assert response.status_code == 201, response.text
    project = response.json()
    assert project["status"] == "draft"
    assert project["items"]
    url = f"/api/projects/{project['id']}"

    # Утверждать черновик нельзя, а специалист не может утверждать вообще
    assert client.post(f"{url}/status", headers=analyst,
                       json={"status": "approved"}).status_code == 409
    assert client.post(f"{url}/status", headers=municipal,
                       json={"status": "review"}).status_code == 200
    assert client.post(f"{url}/status", headers=municipal,
                       json={"status": "approved"}).status_code == 403
    approved = client.post(f"{url}/status", headers=analyst, json={"status": "approved"})
    assert approved.json()["status"] == "approved"
    assert approved.json()["decided_at"]

    # Модель в тестах не подключена, поэтому текст документа берётся из шаблона
    document = client.post(f"{url}/documents", headers=municipal, json={"kind": "order"}).json()
    assert document["written_by_llm"] is False
    file = client.get(f"/api/documents/{document['id']}/download", headers=municipal)
    assert file.status_code == 200
    assert file.content[:2] == b"PK"  # docx — это zip-архив


def test_workflow_opens_next_step_after_completion(client, login):
    headers = login(ANALYST)
    template = client.get("/api/workflow/templates", headers=headers).json()[0]
    tasks = client.post(f"/api/workflow/templates/{template['id']}/start", headers=headers,
                        json={}).json()
    assert [t["status"] for t in tasks[:2]] == ["todo", "waiting"]
    assert tasks[0]["due_date"] < tasks[1]["due_date"]

    client.patch(f"/api/tasks/{tasks[0]['id']}", headers=headers, json={"status": "done"})
    current = {t["id"]: t for t in client.get("/api/tasks", headers=headers).json()}
    assert current[tasks[0]["id"]]["status"] == "done"
    assert current[tasks[1]["id"]]["status"] == "todo"


def test_norm_change_affects_reports_and_is_audited(client, login):
    analyst = login(ANALYST)
    before = client.get("/api/dashboard", headers=analyst).json()["norm_total"]

    norms = client.get("/api/norms", headers=analyst).json()
    security = next(n for n in norms if n["code"] == "security")
    changed = {**security, "per_unit": security["per_unit"] + 1}
    response = client.put(f"/api/norms/{security['id']}", headers=analyst, json=changed)
    assert response.status_code == 200, response.text

    after = client.get("/api/dashboard", headers=analyst).json()["norm_total"]
    assert after > before

    assert client.put(f"/api/norms/{security['id']}", headers=login(MUNICIPAL),
                      json=security).status_code == 403

    admin = login("admin@example.ru", "admin")
    log = client.get("/api/audit", headers=admin, params={"limit": 50}).json()
    entry = next(row for row in log if row["action"] == "norm_updated")
    assert set(entry["details"]) == {"per_unit"}


def test_knowledge_search_finds_relevant_document(client, login):
    hits = client.get("/api/knowledge/search", headers=login(OBSERVER),
                      params={"q": "сколько логопедов положено на детей с ОВЗ"}).json()
    assert "ОВЗ" in hits[0]["title"]
    assert any(norm["code"] == "speech_therapist_ovz" for norm in hits[0]["norms"])


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


def test_employee_sees_only_own_requests_and_no_staffing(client, login):
    employee = login(EMPLOYEE)
    own = client.get("/api/requests", headers=employee).json()
    assert own and all(r["is_author"] for r in own)
    everything = client.get("/api/requests", headers=login(ANALYST)).json()
    assert len(everything) > len(own)

    foreign = next(r for r in everything if not any(r["id"] == o["id"] for o in own))
    assert client.get(f"/api/requests/{foreign['id']}", headers=employee).status_code == 404

    # Штатные расписания и аналитика сотруднику не показываются
    for path in ("/api/dashboard", "/api/organizations", "/api/analytics/workload"):
        assert client.get(path, headers=employee).status_code == 403
    assert client.post("/api/assistant/chat", headers=employee,
                       json={"question": "Где избыток АУП?"}).status_code == 403
    # …но справочники для формы заявки доступны, и учреждение в них только своё
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


def test_workload_report_finds_idle_staff_on_sites(client, login):
    report = client.get("/api/analytics/workload", headers=login(ANALYST)).json()
    totals = report["totals"]
    assert totals["buildings"] >= totals["sites"] > 0
    assert totals["shared_sites"] > 0
    assert totals["unassigned_rate"] == 0  # в демо-данных все ставки привязаны к корпусам
    assert totals["excess"] > 0

    finding = next(f for f in report["findings"] if f["verdict"] == "duplicate")
    assert finding["actual"] - finding["required"] == finding["excess"]
    assert "можно сократить" in finding["recommendation"]

    # Чем меньше радиус, тем меньше корпусов считаются соседними
    apart = client.get("/api/analytics/workload", headers=login(ANALYST),
                       params={"radius": 0}).json()
    assert apart["totals"]["shared_sites"] == 0
    assert apart["totals"]["sites"] == totals["buildings"]

    own = client.get("/api/analytics/workload", headers=login(DIRECTOR)).json()
    assert {b["organization_id"] for s in own["sites"] for b in s["buildings"]} == {
        client.get("/api/organizations", headers=login(DIRECTOR)).json()[0]["id"]}


def test_workload_project_is_generated_from_findings(client, login):
    municipal = login(MUNICIPAL)
    municipality_id = client.get("/api/municipalities", headers=municipal).json()[0]["id"]
    response = client.post("/api/projects/generate", headers=municipal,
                           json={"kind": "workload", "municipality_id": municipality_id})
    assert response.status_code == 201, response.text
    project = response.json()
    assert project["rate_delta"] < 0
    assert project["fot_effect_year"] < 0
    assert all(item["proposed_rate"] < item["current_rate"] for item in project["items"])


def test_rgis_import_updates_buildings_by_object_code(client, login):
    headers = login(MUNICIPAL)
    org = client.get("/api/organizations", headers=headers).json()[0]
    existing = client.get(f"/api/organizations/{org['id']}", headers=headers).json()["buildings"]
    code = existing[0]["rgis_id"]
    csv = (
        "Правообладатель;Наименование объекта;Код объекта РГИС;Адрес;Широта;Долгота;"
        "Общая площадь;Этажность;Проектная мощность;Собственник\n"
        f"{org['name']};Главный корпус;{code};г. Заречный, ул. Новая, д. 1;55,7512;37,6184;"
        ";;640;Администрация\n"
        f"{org['name']};Мастерские;RGIS-NEW-1;г. Заречный, ул. Новая, д. 1, стр. 2;55,7514;"
        "37,6189;412,5;1;;Администрация\n"
        f"{org['name']};Склад;;без адреса;;;;;;\n"
    )
    response = client.post("/api/import/buildings", headers=headers,
                           files={"file": ("rgis.csv", csv.encode("cp1251"), "text/csv")})
    assert response.status_code == 200, response.text
    result = response.json()
    assert (result["imported"], result["skipped"]) == (2, 1)
    assert result["dropped_columns"] == ["собственник"]

    buildings = client.get(f"/api/organizations/{org['id']}", headers=headers).json()["buildings"]
    assert len(buildings) == len(existing) + 1
    main = next(b for b in buildings if b["rgis_id"] == code)
    assert (main["capacity"], main["latitude"]) == (640, 55.7512)
    assert main["area_sqm"] == existing[0]["area_sqm"]  # пустая ячейка площадь не затёрла
    workshop = next(b for b in buildings if b["rgis_id"] == "RGIS-NEW-1")
    assert workshop["area_sqm"] == 412.5


def chat_events(client, headers, question: str) -> list[dict]:
    import json

    response = client.post("/api/assistant/chat", headers=headers, json={"question": question})
    assert response.status_code == 200
    return [json.loads(line[5:]) for line in response.text.splitlines() if line.startswith("data:")]


def test_assistant_shows_database_data_even_without_model(client, login):
    events = chat_events(client, login(ANALYST), "Где самый большой избыток АУП?")
    blocks = [e for e in events if e["type"] == "data"]
    assert "АУП" in blocks[0]["title"]
    assert "| Учреждение |" in blocks[0]["markdown"]
    # Модель в тестах не подключена: об этом сообщается, но данные уже отданы
    assert any(e["type"] == "error" for e in events)


def test_assistant_names_its_sources(client, login):
    events = chat_events(client, login(ANALYST),
                         "Сколько логопедов положено на детей с ОВЗ и на основании чего?")
    sources = next(e for e in events if e["type"] == "sources")["items"]
    document = next(s for s in sources if s["kind"] == "document")
    assert "ОВЗ" in document["title"]
    assert "115" in document["ref"]
    assert all(e.get("source") for e in events if e["type"] == "data")


def test_assistant_refuses_questions_outside_the_system(client, login):
    events = chat_events(client, login(ANALYST), "Посоветуй хороший фильм на вечер")
    assert not [e for e in events if e["type"] == "data"]
    assert "нет данных" in events[0]["text"]
    assert next(e for e in events if e["type"] == "sources")["items"] == []
    # До модели дело не дошло, поэтому и ошибки о её недоступности нет
    assert not [e for e in events if e["type"] == "error"]


def test_assistant_answers_about_workload_and_requests(client, login):
    events = chat_events(client, login(ANALYST),
                         "Где персонал простаивает в соседних корпусах?")
    block = next(e for e in events if e["type"] == "data")
    assert "по площадкам" in block["title"]
    assert "РГИС" in block["source"]

    events = chat_events(client, login(ANALYST), "Сколько заявок просрочено?")
    assert any(e["type"] == "data" and e["title"] == "Заявки" for e in events)


def test_assistant_respects_access_scope(client, login):
    own = client.get("/api/organizations", headers=login(DIRECTOR)).json()[0]
    foreign = next(o for o in client.get("/api/organizations", headers=login(ANALYST)).json()
                   if o["municipality_id"] != own["municipality_id"])
    number = foreign["name"].split("№ ")[1].split()[0]

    events = chat_events(client, login(DIRECTOR), f"Что по учреждению № {number}?")
    text = " ".join(e.get("markdown", "") + e.get("title", "") for e in events)
    assert foreign["name"] not in text


def test_program_scoreboard_tracks_progress_from_baseline(client, login):
    municipal = login(MUNICIPAL)
    program = client.get("/api/program", headers=municipal).json()
    assert program["scoreboard"]["target_pct"] == 10
    assert program["scoreboard"]["baseline_fixed"] is False
    assert len(program["milestones"]) == 5

    assert client.post("/api/program/baseline", headers=municipal).status_code == 200

    # Убираем одну ставку вспомогательного персонала — она должна появиться в «сокращено»
    org = client.get("/api/organizations", headers=municipal).json()[-1]
    positions = client.get(f"/api/organizations/{org['id']}/positions", headers=municipal).json()
    victim = next(p for p in positions if p["category"] == "support" and p["rate"] == 1)
    client.delete(f"/api/positions/{victim['id']}", headers=municipal)

    board = client.get("/api/program", headers=municipal).json()["scoreboard"]
    support = next(c for c in board["categories"] if c["category"] == "support")
    assert board["baseline_fixed"] is True
    assert support["done_rates"] == 1
    assert support["done_hours"] == 1972
    assert board["done_saving_year"] > 0

    # Наблюдатель паспорт видит, но менять исходную точку не может
    assert client.get("/api/program", headers=login(OBSERVER)).status_code == 200
    assert client.post("/api/program/baseline", headers=login(OBSERVER)).status_code == 403


def test_digital_tool_coverage_is_editable(client, login):
    tools = client.get("/api/digital-tools", headers=login(OBSERVER)).json()
    assert all(tool["coverage_pct"] is None for tool in tools)

    response = client.put("/api/digital-tools/clerk", headers=login(MUNICIPAL),
                          json={"name": "Маршрутизация документов", "coverage_pct": 85})
    assert response.status_code == 200
    clerk = next(t for t in client.get("/api/digital-tools", headers=login(OBSERVER)).json()
                 if t["function_code"] == "clerk")
    assert clerk["coverage_pct"] == 85
