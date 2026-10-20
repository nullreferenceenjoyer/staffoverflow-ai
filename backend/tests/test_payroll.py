"""ФОТ по штатке, история изменений и сводка для дашборда."""

ANALYST = "analyst@demo.ru"
DIRECTOR = "director@demo.ru"
OBSERVER = "observer@demo.ru"


def _year(client, headers):
    return client.get("/api/staffing/meta", headers=headers).json()["current_year"]


def _director_org(client, login):
    return client.get("/api/auth/me", headers=login(DIRECTOR)).json()["organization_id"]


def test_director_sees_payroll_and_cut_of_cleaning(client, login):
    headers = login(DIRECTOR)
    org_id = _director_org(client, login)
    data = client.get(f"/api/staffing/institutions/{org_id}/schedule", headers=headers).json()
    cleaning = next(line for line in data["lines"] if line["group"] == "Уборка помещений")
    # 10 ставок × 22 500 ₽ × 12
    assert (cleaning["approved"], cleaning["salary"]) == (10.0, 22500.0)
    assert cleaning["payroll_approved"] == 2_700_000
    # Норматив 12 ставок, занято 9,5: дефицит 2,5 ставки стоит 2,5 × 22 500 × 12
    assert cleaning["deviation"] == -2.5 and cleaning["deviation_cost"] == -675_000
    assert data["totals"]["payroll_approved"] > 0

    # В октябре сократили ставку уборщика: в истории видно, как изменился ФОТ
    last = data["history"][0]
    assert last["approved_delta"] == -1 and last["payroll_delta"] == -270_000
    assert last["changes"][0]["group"] == "Уборка помещений"
    assert data["history"][-1]["first"] is True


def test_saving_schedule_makes_version_only_when_something_changed(client, login):
    analyst = login(ANALYST)
    year = _year(client, analyst)
    org_id = _director_org(client, login)
    other = next(i for i in client.get("/api/staffing/schedules", headers=analyst).json()["items"]
                 if i["organization_id"] != org_id and i["status"] == "approved")
    url = f"/api/staffing/institutions/{other['organization_id']}"
    data = client.get(f"{url}/data", headers=analyst, params={"year": year}).json()
    lines = [line for line in data["lines"] if line["approved"] is not None]
    body = {"year": year, "status": "approved",
            **{k: data["metrics"][k] for k in ("students_count", "classes_count",
                                                "groups_count", "total_area_m2")},
            "lines": [{"group_id": line["id"], "approved_fte": line["approved"],
                       "occupied_fte": line["occupied"], "salary_rub": line["salary"]}
                      for line in lines]}
    before = len(client.get(f"{url}/schedule", headers=analyst).json()["history"])
    assert client.put(f"{url}/data", headers=analyst, json=body).status_code == 200
    assert len(client.get(f"{url}/schedule", headers=analyst).json()["history"]) == before

    # Сократили одну ставку первой группы
    cut = body["lines"][0]
    body["lines"][0] = {**cut, "approved_fte": cut["approved_fte"] - 1,
                        "occupied_fte": None if cut["occupied_fte"] is None
                        else max(cut["occupied_fte"] - 1, 0)}
    assert client.put(f"{url}/data", headers=analyst, json=body).status_code == 200
    history = client.get(f"{url}/schedule", headers=analyst).json()["history"]
    assert len(history) == before + 1
    assert history[0]["approved_delta"] == -1
    assert history[0]["payroll_delta"] == -cut["salary_rub"] * 12
    assert history[0]["source"] == "manual" and history[0]["author"]


def test_dashboard_counts_money(client, login):
    body = client.get("/api/staffing/dashboard", headers=login(ANALYST)).json()
    kpi = body["kpi"]
    assert body["organizations"] >= kpi["problems"] + kpi["no_data"]
    assert kpi["payroll_approved"] > 0 and kpi["deficit_fte"] > 0 and kpi["deficit_cost"] > 0
    assert len(body["by_municipality"]) >= 2
    assert body["by_group"] and body["changes"]
    assert all(c["changes"] for c in body["changes"])
    # Наблюдатель видит сводку, но не штатку отдельного учреждения
    observer = login(OBSERVER)
    assert client.get("/api/staffing/dashboard", headers=observer).status_code == 200
    org_id = body["top"][0]["organization_id"]
    assert client.get(f"/api/staffing/institutions/{org_id}/schedule",
                      headers=observer).status_code == 403


def test_request_text_has_payroll_estimate(client, login):
    headers = login(DIRECTOR)
    draft = client.get("/api/staffing/request-draft", headers=headers, params={
        "organization_id": _director_org(client, login), "year": _year(client, headers),
        "category": "support"}).json()
    assert "Оценка ФОТ отклонения" in draft["text"]
