"""Сквозные проверки API: права доступа, импорт, жизненный цикл проекта и задач."""

ANALYST = "analyst@demo.ru"
MUNICIPAL = "municipal@demo.ru"
DIRECTOR = "director@demo.ru"
OBSERVER = "observer@demo.ru"


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

    # Директор не адресат обращения и закрыть его не может
    assert client.patch(f"/api/requests/{body['id']}", headers=login(DIRECTOR),
                        json={"status": "closed"}).status_code == 403


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
