"""Нормативная численность через API: права, анализ, данные, нормативы и заявки."""

ADMIN = ("admin@example.ru", "admin")
ANALYST = "analyst@demo.ru"
MUNICIPAL = "municipal@demo.ru"
DIRECTOR = "director@demo.ru"
OBSERVER = "observer@demo.ru"
EXECUTOR = "executor@demo.ru"
EMPLOYEE = "employee@demo.ru"


def _year(client, headers):
    return client.get("/api/staffing/meta", headers=headers).json()["current_year"]


def _director_org(client, login):
    return client.get("/api/auth/me", headers=login(DIRECTOR)).json()["organization_id"]


def test_section_is_hidden_from_employee_and_service_staff(client, login):
    for email in (EMPLOYEE, EXECUTOR):
        headers = login(email)
        assert client.get("/api/staffing/meta", headers=headers).status_code == 403
        assert client.get("/api/staffing/analysis", headers=headers).status_code == 403
        assert client.get("/api/norms/coefficients", headers=headers).status_code == 403


def test_observer_sees_summary_without_details(client, login):
    headers = login(OBSERVER)
    analysis = client.get("/api/staffing/analysis", headers=headers)
    assert analysis.status_code == 200
    org_id = analysis.json()["items"][0]["organization_id"]
    assert client.get(f"/api/staffing/institutions/{org_id}/analysis",
                      headers=headers).status_code == 403
    meta = client.get("/api/staffing/meta", headers=headers).json()
    assert meta["permissions"]["details"] is False


def test_director_sees_own_school_with_example_from_spec(client, login):
    headers = login(DIRECTOR)
    org_id = _director_org(client, login)
    items = client.get("/api/staffing/analysis", headers=headers).json()["items"]
    assert [i["organization_id"] for i in items] == [org_id]

    detail = client.get(f"/api/staffing/institutions/{org_id}/analysis", headers=headers).json()
    aup = detail["analysis"]["aup"]["occupied"]
    total = aup["total"]
    # Школа из примера ТЗ: 840 обучающихся, 34 класса
    assert (total["deviation"], total["status"]) == (-1.25, "deficit")
    by_group = {g["group"]: g for g in aup["groups"]}
    assert by_group["Заместители директора"]["deviation"] == 0.5
    assert by_group["Делопроизводство"]["deviation"] == -1.0
    assert by_group["Бухгалтерия и финансово-экономическая служба"]["required"] == 1.25
    assert by_group["Делопроизводство"]["coefficients"][0]["explain"].startswith(
        "1 ставка на 300 обучающихся")
    assert detail["documents"]

    other = next(i for i in client.get("/api/staffing/analysis",
                                       headers=login(ANALYST)).json()["items"]
                 if i["organization_id"] != org_id)
    assert client.get(f"/api/staffing/institutions/{other['organization_id']}/analysis",
                      headers=headers).status_code == 404


def test_analyst_sees_region_and_problems_come_first(client, login):
    body = client.get("/api/staffing/analysis", headers=login(ANALYST)).json()
    items = body["items"]
    # Каждое учреждение в таблице, даже то, по которому данных ещё нет
    assert len(items) == len(client.get("/api/organizations", headers=login(*ADMIN)).json())
    assert sum(body["summary"].values()) == len(items)
    assert body["summary"]["no_data"] >= 1
    ranks = [{"deficit": 0, "surplus": 0, "warning": 0, "no_data": 1, "normal": 2}[i["status"]]
             for i in items]
    assert ranks == sorted(ranks)
    missing = next(i for i in items if i["status"] == "no_data")
    assert missing["reasons"]

    municipal = client.get("/api/staffing/analysis", headers=login(MUNICIPAL)).json()["items"]
    assert 0 < len(municipal) < len(items)
    assert len({i["municipality_id"] for i in municipal}) == 1


def test_request_from_analysis_keeps_snapshot_when_norm_changes(client, login):
    director, analyst = login(DIRECTOR), login(ANALYST)
    org_id = _director_org(client, login)
    year = _year(client, director)
    query = {"organization_id": org_id, "year": year, "category": "aup", "basis": "occupied"}
    draft = client.get("/api/staffing/request-draft", headers=director, params=query).json()
    # Дефицит АУП — дополнительные ставки, решает управление образования
    assert (draft["topic"], draft["routed_role"]) == ("staff_increase", "municipal_specialist")
    assert "дефицит 1,25 ставки" in draft["text"]
    assert "Делопроизводство −1,00" in draft["text"]

    created = client.post("/api/staffing/requests", headers=director, json=query)
    assert created.status_code == 201, created.text
    request_id = created.json()["request_id"]
    card = client.get(f"/api/requests/{request_id}", headers=director).json()
    assert card["topic"] == "staff_increase"
    assert card["routed_role"] == "municipal_specialist"
    assert card["staffing"][0]["deviation"] == -1.25
    assert card["staffing"][0]["link_type"] == "deficit"

    # Местный норматив для школы: делопроизводство теперь 2 ставки
    group = next(g for g in client.get("/api/staffing/meta", headers=analyst).json()["groups"]
                 if g["code"] == "aup_clerical")
    norm = client.post("/api/norms/coefficients", headers=analyst, json={
        "group_id": group["id"], "scope_level": "organization", "scope_id": org_id,
        "metric": "none", "fte_per_unit": 2, "rounding_step": 0.25})
    assert norm.status_code == 201, norm.text
    try:
        detail = client.get(f"/api/staffing/institutions/{org_id}/analysis",
                            headers=director).json()
        assert detail["analysis"]["aup"]["occupied"]["total"]["deviation"] == -0.25
        # Заявка показывает картину на момент создания
        card = client.get(f"/api/requests/{request_id}", headers=director).json()
        assert card["staffing"][0]["deviation"] == -1.25
        assert card["staffing"][0]["is_current"] is False
    finally:
        assert client.delete(f"/api/norms/coefficients/{norm.json()['id']}",
                             headers=analyst).status_code == 204
    detail = client.get(f"/api/staffing/institutions/{org_id}/analysis", headers=director).json()
    assert detail["analysis"]["aup"]["occupied"]["total"]["deviation"] == -1.25


def test_surplus_request_never_says_dismiss(client, login):
    director = login(DIRECTOR)
    org_id = _director_org(client, login)
    meta = client.get("/api/staffing/meta", headers=director).json()
    group = next(g for g in meta["groups"] if g["code"] == "aup_deputies")
    draft = client.get("/api/staffing/request-draft", headers=director, params={
        "organization_id": org_id, "year": meta["current_year"], "category": "aup",
        "basis": "occupied", "group_id": group["id"]}).json()
    assert draft["topic"] == "staff_reduction"
    assert "излишек 0,50 ставки" in draft["text"]
    assert "уволить" not in draft["text"].lower()


def test_staffing_request_is_linked_by_text(client, login):
    director = login(DIRECTOR)
    created = client.post("/api/requests", headers=director, json={
        "title": "Нужна ставка уборщика служебных помещений",
        "text": "Не хватает уборщиков на новое крыло"}).json()
    assert created["topic"] == "staff_increase"
    card = client.get(f"/api/requests/{created['id']}", headers=director).json()
    assert card["staffing"][0]["group"] == "Уборка помещений"
    assert card["staffing"][0]["created_by"] == "system"
    # Сотрудник учреждения блок анализа не видит, даже в своей заявке
    own = client.post("/api/requests", headers=login(EMPLOYEE), json={
        "title": "Нужна ставка уборщика"}).json()
    assert client.get(f"/api/requests/{own['id']}", headers=login(EMPLOYEE)).json()[
        "staffing"] == []


def test_data_editing_is_scoped_and_recalculates(client, login):
    analyst, director = login(ANALYST), login(DIRECTOR)
    org_id = _director_org(client, login)
    year = _year(client, analyst)
    other = next(i for i in client.get("/api/staffing/analysis", headers=analyst).json()["items"]
                 if i["organization_id"] != org_id)["organization_id"]
    url = f"/api/staffing/institutions/{other}/data"
    # Директор чужого учреждения данные не видит и не меняет
    assert client.get(url, headers=director, params={"year": year}).status_code == 404
    assert client.get(url, headers=login(OBSERVER), params={"year": year}).status_code == 403

    data = client.get(url, headers=analyst, params={"year": year}).json()
    body = {"year": year, "status": "draft",
            **{k: data["metrics"][k] for k in ("students_count", "classes_count",
                                                "groups_count", "total_area_m2")},
            "lines": [{"group_id": line["id"], "approved_fte": line["approved"],
                       "occupied_fte": line["occupied"]}
                      for line in data["lines"] if line["approved"] is not None]}
    saved = client.put(url, headers=analyst, json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["schedule"]["status"] == "draft"
    row = next(i for i in client.get("/api/staffing/analysis", headers=analyst,
                                     params={"basis": "approved"}).json()["items"]
               if i["organization_id"] == other)
    assert row["status"] == "no_data"
    assert "не утверждено" in row["reasons"][0]

    assert client.put(url, headers=analyst, json={**body, "status": "approved"}).status_code == 200
    audit = client.get("/api/audit", headers=login(*ADMIN)).json()
    assert any(a["action"] == "staffing_schedule_approved" for a in audit)


def test_specialist_cannot_change_regional_norms(client, login):
    headers = login(MUNICIPAL)
    group = client.get("/api/staffing/meta", headers=headers).json()["groups"][0]
    response = client.post("/api/norms/coefficients", headers=headers, json={
        "group_id": group["id"], "metric": "none", "fte_per_unit": 1})
    assert response.status_code == 403
    assert client.get("/api/norms/coefficients", headers=login(DIRECTOR)).status_code == 200


def test_import_lines_reports_errors_by_row(client, login):
    analyst = login(ANALYST)
    year = _year(client, analyst)
    # Школа демо-директора: те же 1 / 1 ставки хозчасти, пример из ТЗ не меняется
    org = client.get("/api/staffing/analysis", headers=login(DIRECTOR)).json()["items"][0][
        "organization"]
    csv = (f"Код учреждения;Учебный год;Группа;Утверждено ставок;Занято ставок\n"
           f"{org};{year};aup_household;1;1\n"
           f"{org};{year};несуществующая;1;1\n"
           f"Нет такой школы;{year};aup_household;1;1\n")
    response = client.post("/api/staffing/import/lines", headers=analyst,
                           files={"file": ("lines.csv", csv.encode("utf-8"), "text/csv")})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["created"] + result["updated"] == 1
    assert [e["row"] for e in result["errors"]] == [3, 4]
    assert client.get("/api/staffing/templates/lines.xlsx", headers=analyst).status_code == 200
