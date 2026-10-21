"""Программа оптимизации: уволенные, простые расчёты уборщиц и хозотдела.

Реальные данные (seed/program.local.json) в тестах не загружаются: они заменили бы
демо-школы общей тестовой базы. Проверяются расчёты и права."""

from app.services import simple

DIRECTOR = "director@demo.ru"
MUNICIPAL = "municipal@demo.ru"
OBSERVER = "observer@demo.ru"


def test_rounding_and_verdict():
    assert simple.up(14.011) == 14.02
    assert simple.up(15) == 15
    assert simple._verdict(17, 15) == ("surplus", 2)
    assert simple._verdict(15, 15) == ("normal", 0)
    assert simple._verdict(15.2, 15) == ("surplus", 0.2)
    assert simple._verdict(13, 15) == ("deficit", -2)
    assert simple._verdict(None, 15) == ("no_data", None)


def test_cleaning_is_classes_or_area_whichever_needs_more(client, login):
    headers = login(DIRECTOR)
    org = client.get("/api/auth/me", headers=headers).json()["organization_id"]
    year = client.get("/api/staffing/meta", headers=headers).json()["current_year"]
    norm = client.get("/api/program/cleaning", headers=headers).json()["norm"]
    # Классы и площадь — те, что уже есть у школы: от них считаются и другие нормативы
    metrics = client.get(f"/api/staffing/institutions/{org}/data", headers=headers,
                         params={"year": year}).json()["metrics"]
    classes, area = metrics["classes_count"], metrics["total_area_m2"]
    body = {"year": year, "classes_count": classes, "total_area_m2": area, "cleaners_fte": 17}
    saved = client.put(f"/api/program/cleaning/{org}", headers=headers, json=body)
    assert saved.status_code == 200, saved.text
    item = saved.json()
    assert item["by_classes"] == round(classes / norm["classes_per_rate"], 2)
    assert item["by_area"] == round(area / norm["area_per_rate"], 2)
    assert item["need"] == simple.up(max(item["by_classes"], item["by_area"]))
    assert item["diff"] == round(17 - item["need"], 2)
    assert item["status"] == ("surplus" if item["diff"] >= 0.01 else
                              "deficit" if item["diff"] <= -0.01 else "normal")
    # Директор видит только свою школу
    assert len(client.get("/api/program/cleaning", headers=headers).json()["items"]) == 1
    assert client.put("/api/program/cleaning-norm", headers=headers,
                      json={"classes_per_rate": 3, "area_per_rate": 600}).status_code == 403
    assert client.put(f"/api/program/cleaning/{org}", headers=login(OBSERVER),
                      json=body).status_code == 403


def test_maintenance_compares_own_staff_with_requests(client, login):
    headers = login(DIRECTOR)
    org = client.get("/api/auth/me", headers=headers).json()["organization_id"]
    year = client.get("/api/staffing/meta", headers=headers).json()["current_year"]
    assert client.put(f"/api/program/maintenance/{org}", headers=headers,
                      json={"year": year, "maintenance_fte": 4}).status_code == 200
    data = client.get("/api/program/maintenance", headers=headers).json()
    school = data["schools"][0]
    assert school["have"] == 4 and school["requests"] >= 1
    assert school["need"] >= data["settings"]["min_people"]
    assert school["diff"] == round(4 - school["need"], 2)
    territory = client.get("/api/program/maintenance", headers=login(MUNICIPAL)).json()
    assert territory["brigades"] and all(b["organizations"] is not None
                                         for b in territory["brigades"])


def test_dismissals_are_kept_by_education_department(client, login):
    org = client.get("/api/auth/me", headers=login(DIRECTOR)).json()["organization_id"]
    body = {"organization_id": org, "full_name": "Иванова Анна Петровна",
            "position": "Уборщик служебных помещений", "fte": 1, "basis": "own",
            "order_number": "1-к", "order_date": "2026-08-24", "dismissed_on": "2026-08-24"}
    assert client.post("/api/program/dismissals", headers=login(DIRECTOR),
                       json=body).status_code == 403
    created = client.post("/api/program/dismissals", headers=login(MUNICIPAL), json=body)
    assert created.status_code == 201, created.text
    item = created.json()
    assert item["basis_title"] == "По собственному желанию"
    own = client.get("/api/program/dismissals", headers=login(DIRECTOR)).json()
    assert [i["id"] for i in own["items"]] == [item["id"]] and not own["can_edit"]
    hidden = client.get("/api/program/dismissals", headers=login(OBSERVER)).json()
    assert all(i["full_name"] == "—" for i in hidden["items"])
    # В расчёте уборщиц фамилий уволенных нет: расчёт — по штатке до увольнений
    cleaning = client.get("/api/program/cleaning", headers=login(DIRECTOR)).json()
    assert "Иванова" not in str(cleaning)
    assert client.delete(f"/api/program/dismissals/{item['id']}",
                         headers=login(MUNICIPAL)).status_code == 204
    overview = client.get("/api/program/overview", headers=login(MUNICIPAL)).json()
    assert overview["program"] is None and overview["dismissed_total"]["people"] == 0


def test_requests_board_counts_only_household_requests(client, login):
    headers = login(MUNICIPAL)
    data = client.get("/api/program/requests", headers=headers, params={"days": 90}).json()
    assert data["days"] == 90
    assert sum(h["requests"] for h in data["handlers"]) == data["created"]
    assert data["hours"] == round(sum(h["hours"] for h in data["handlers"]), 1)
    assert all(t["topic"] in simple.effort.BASE_HOURS for t in data["by_topic"])
    cleaning = client.get("/api/program/requests", headers=headers,
                          params={"topic": "cleaning"}).json()
    assert {t["topic"] for t in cleaning["by_topic"]} <= {"cleaning"}
    # Наблюдатель видит цифры, но не фамилии исполнителей
    assert client.get("/api/program/requests",
                      headers=login(OBSERVER)).json()["by_assignee"] == []


def test_dismissal_frees_the_position_in_schedule(client, login):
    """Увольнение освобождает ставку: в штатке «занято» меньше, на «Итоге» она переходит
    из людей в вакансии, а всего «высвободить» не меняется. Удаление записи — всё назад."""
    org = client.get("/api/auth/me", headers=login(DIRECTOR)).json()["organization_id"]
    headers = login(MUNICIPAL)

    def schedule():
        return client.get(f"/api/staffing/institutions/{org}/schedule", headers=headers).json()

    def headline():
        return client.get("/api/staffing/summary", headers=headers).json()["headline"]

    before, total = schedule(), headline()["total"]
    position = next(p for line in before["lines"] for p in line["positions"]
                    if (p["occupied"] or 0) >= 1)
    created = client.post("/api/program/dismissals", headers=headers, json={
        "organization_id": org, "full_name": "Проверкин Пётр Петрович",
        "position": position["position"], "fte": 1, "basis": "layoff"})
    assert created.status_code == 201, created.text
    item = created.json()
    assert item["applied_fte"] == 1 and item["applied_position"] == position["position"]
    after = schedule()
    assert after["totals"]["occupied"] == round(before["totals"]["occupied"] - 1, 2)
    assert after["totals"]["approved"] == before["totals"]["approved"]
    assert headline()["total"] == total
    # «Вернуть» и «Учесть в штатке» — то же самое без удаления записи
    reverted = client.delete(f"/api/program/dismissals/{item['id']}/apply", headers=headers)
    assert reverted.json()["applied_fte"] is None
    assert schedule()["totals"]["occupied"] == before["totals"]["occupied"]
    assert client.post(f"/api/program/dismissals/{item['id']}/apply",
                       headers=headers).json()["applied_fte"] == 1
    assert client.delete(f"/api/program/dismissals/{item['id']}",
                         headers=headers).status_code == 204
    assert schedule()["totals"]["occupied"] == before["totals"]["occupied"]
    # Должности, которой нет в штатке, учесть нельзя — запись остаётся неучтённой
    odd = client.post("/api/program/dismissals", headers=headers, json={
        "organization_id": org, "full_name": "Проверкин Пётр Петрович",
        "position": "Астроном", "fte": 1, "basis": "own"}).json()
    assert odd["applied_fte"] is None
    assert client.post(f"/api/program/dismissals/{odd['id']}/apply",
                       headers=headers).status_code == 422
    client.delete(f"/api/program/dismissals/{odd['id']}", headers=headers)


def test_maintenance_detail_for_school_and_brigade(client, login):
    headers = login(MUNICIPAL)
    data = client.get("/api/program/maintenance", headers=headers).json()
    school = data["schools"][0]
    detail = client.get("/api/program/maintenance/detail", headers=headers,
                        params={"organization_id": school["organization_id"]}).json()
    assert detail["kind"] == "school" and detail["row"]["need"] == school["need"]
    assert detail["requests"]["count"] >= len(detail["requests"]["recent"])
    if data["brigades"]:
        brigade = data["brigades"][0]
        card = client.get("/api/program/maintenance/detail", headers=headers,
                          params={"brigade_id": brigade["id"]}).json()
        assert card["unit"]["people"] == brigade["people"]
        assert card["requests"]["count"] == brigade["requests"]
    assert client.get("/api/program/maintenance/detail", headers=headers,
                      params={"brigade_id": 999999}).status_code == 404
    # Наблюдатель видит цифры, но не фамилии
    hidden = client.get("/api/program/maintenance/detail", headers=login(OBSERVER),
                        params={"organization_id": school["organization_id"]}).json()
    assert all(p["name"] == "—" for p in hidden["people"])
