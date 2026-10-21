"""Загрузка хозотдела и бригад, итог «сколько лишних», уборщики и удаление должности.

Расчёт загрузки проверяется без базы; API — на PostgreSQL, как test_api.py."""

from decimal import Decimal

from app.services import app_settings, workload

ADMIN = ("admin@example.ru", "admin")
DIRECTOR = "director@demo.ru"
MUNICIPAL = "municipal@demo.ru"
OBSERVER = "observer@demo.ru"


def unit(people_hours: list[float], work: float, travel: float = 0.0, kind="brigade"):
    people = [workload.Person(i, f"Мастер {i}", hours=h) for i, h in enumerate(people_hours)]
    item = workload.Unit("brigade-1", kind, 1, "Бригада", None, people)
    item.places[1] = workload.Place(1, "Школа", 5.0)
    item.work_hours, item.travel_hours = work, travel
    return item


SETTINGS = dict(app_settings.WORKLOAD_DEFAULTS)


def test_low_load_means_surplus_and_least_loaded_go_first():
    # 3 человека, за 90 дней 100 ч работы: нужен один, двое лишние
    result = unit([60, 10, 30], 100).calculate(SETTINGS, 90, Decimal(27500))
    assert result["needed"] == 1
    assert result["surplus"] == 2
    assert result["status"] == "surplus"
    assert result["load_pct"] < 10
    assert result["candidates"] == ["Мастер 1", "Мастер 2"]
    assert result["cost"] == 27500 * 12 * 2


def test_busy_brigade_is_overloaded_and_travel_counts():
    # 2 человека, 64 рабочих дня × 6 ч × 2 = 771 ч; работы и дороги — 900 ч
    result = unit([400, 400], 700, travel=200).calculate(SETTINGS, 90, None)
    assert result["status"] == "overload"
    assert result["load_pct"] > 100
    assert result["needed"] > 2
    assert result["surplus"] < 0
    assert result["candidates"] == [] and result["cost"] is None


def test_normal_load_keeps_everyone():
    # 2 человека, работы ровно на полторы ставки при загрузке 80 %
    hours = workload.workdays(90) * 6 * 0.8 * 1.5
    result = unit([hours / 2, hours / 2], hours).calculate(SETTINGS, 90, None)
    assert (result["needed"], result["surplus"], result["status"]) == (1.5, 0.5, "surplus")
    hours = workload.workdays(90) * 6 * 0.8 * 2
    result = unit([hours / 2, hours / 2], hours).calculate(SETTINGS, 90, None)
    assert (result["needed"], result["surplus"], result["status"]) == (2, 0, "normal")


def test_nobody_in_unit_is_not_a_surplus():
    result = unit([], 10).calculate(SETTINGS, 90, None)
    assert result["status"] == "no_people"
    assert result["surplus"] == 0


# --- API ------------------------------------------------------------------------------


def test_summary_shows_surplus_for_territory_and_director(client, login):
    data = client.get("/api/staffing/summary", headers=login(MUNICIPAL)).json()
    assert [b["key"] for b in data["buckets"]] == ["cleaning", "maintenance", "other"]
    head = data["headline"]
    assert head["total"] == round(head["cut"] + head["reduce_load"] + head["cut_vacant"]
                                  + head["brigade_cut"], 2)
    assert head["cost"] >= 0
    assert data["brigades"], "бригады округа видны специалисту"
    assert {r["code"] for r in data["rules"]} >= {"cut", "cut_vacant", "cut_by_load", "hire"}
    # Школы — от больших высвобождений к меньшим, у каждой — что сделать
    totals = [s["total"] for s in data["schools"]]
    assert totals == sorted(totals, reverse=True)
    assert all(s["main"] for s in data["schools"] if s["total"])

    own = client.get("/api/staffing/summary", headers=login(DIRECTOR)).json()
    assert own["organization"] is not None and own["organizations"] == 1
    assert own["headline"]["brigade_cut"] == 0
    cleaning = next(b for b in own["buckets"] if b["key"] == "cleaning")
    # В школе директора двое уборщиков заведены в системе
    assert cleaning["people"] == 2
    assert own["groups"] and own["actions"]
    # Каждое «сократить» называет должность и ставку
    for action in own["actions"]:
        if action["kind"].startswith("cut"):
            assert action["positions"] and all(p["position"] and p["fte"] > 0
                                               for p in action["positions"])

    hidden = client.get("/api/staffing/summary", headers=login(OBSERVER)).json()
    assert all(u["members"] == [] for u in hidden["brigades"])


def test_workload_finds_extra_person_on_site(client, login):
    data = client.get("/api/staffing/workload", headers=login(MUNICIPAL)).json()
    onsite = [u for u in data["units"] if u["kind"] == "onsite"]
    pair = next(u for u in onsite if u["people"] == 2)
    # Двое на точке, работы на одного — один лишний, первым в списке наименее загруженный
    assert pair["status"] == "surplus" and pair["surplus"] >= 1
    assert pair["candidates"] == [pair["members"][0]["name"]]
    brigade = next(u for u in data["units"] if u["kind"] == "brigade" and u["requests"])
    assert brigade["work_hours"] > 0
    assert brigade["organizations"]
    assert client.get("/api/staffing/workload", headers=login(OBSERVER)).status_code == 403


def test_workload_settings_are_edited_by_education_department(client, login):
    body = {"hours_per_day": 6, "target_load_pct": 75, "travel_speed_kmh": 30,
            "default_hours": 1.5, "min_people": 1}
    assert client.put("/api/staffing/workload/settings", headers=login(DIRECTOR),
                      json=body).status_code == 403
    saved = client.put("/api/staffing/workload/settings", headers=login(MUNICIPAL), json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["target_load_pct"] == 75
    data = client.get("/api/staffing/workload", headers=login(MUNICIPAL)).json()
    assert data["settings"]["target_load_pct"] == 75
    client.put("/api/staffing/workload/settings", headers=login(MUNICIPAL),
               json={**body, "target_load_pct": 80})


def test_cleaning_goes_to_cleaner_of_the_school(client, login):
    body = client.post("/api/requests", headers=login(DIRECTOR),
                       json={"title": "Убрать мусор и грязь в коридоре второго этажа"}).json()
    assert body["topic"] == "cleaning"
    assert body["assignee"]["role"] == "cleaner"


def test_positions_are_added_changed_and_removed(client, login):
    headers = login(DIRECTOR)
    org = client.get("/api/auth/me", headers=headers).json()["organization_id"]
    url = f"/api/staffing/institutions/{org}"
    schedule = client.get(f"{url}/schedule", headers=headers).json()
    cleaning = next(line for line in schedule["lines"] if line["group"] == "Уборка помещений")
    # Штатка по должностям: уборщик и гардеробщик — в группе «Уборка помещений»
    assert {p["position"] for p in cleaning["positions"]} >= {"Уборщик служебных помещений",
                                                             "Гардеробщик"}
    year = schedule["year"]
    body = {"year": year, "group_id": cleaning["group_id"], "position": "Мойщик окон",
            "approved_fte": 0.5, "occupied_fte": 0.5, "salary_rub": 21000}
    added = client.post(f"{url}/positions", headers=headers, json=body)
    assert added.status_code == 201, added.text
    line = next(line for line in added.json()["lines"] if line["group_id"] == body["group_id"])
    new = next(p for p in line["positions"] if p["position"] == "Мойщик окон")
    assert line["approved"] == cleaning["approved"] + 0.5
    assert client.post(f"{url}/positions", headers=headers, json=body).status_code == 409
    assert client.post(f"{url}/positions", headers=headers,
                       json={**body, "position": "Ещё", "occupied_fte": 2}).status_code == 422

    changed = client.put(f"{url}/positions/{new['line_id']}", headers=headers,
                         json={**body, "approved_fte": 1, "occupied_fte": 0.5}).json()
    line = next(line for line in changed["lines"] if line["group_id"] == body["group_id"])
    assert next(p for p in line["positions"] if p["line_id"] == new["line_id"])["vacant"] == 0.5
    assert changed["history"][0]["comment"] == "Изменена должность: Мойщик окон"

    removed = client.delete(f"{url}/positions/{new['line_id']}", headers=headers,
                            params={"year": year})
    assert removed.status_code == 200, removed.text
    line = next(line for line in removed.json()["lines"] if line["group_id"] == body["group_id"])
    assert line["approved"] == cleaning["approved"]
    assert client.delete(f"{url}/positions/{new['line_id']}", headers=headers,
                         params={"year": year}).status_code == 404
    assert client.post(f"{url}/positions", headers=login(OBSERVER), json=body).status_code == 403


def test_cleaning_tab_counts_rooms_per_cleaner(client, login):
    data = client.get("/api/staffing/cleaning", headers=login(DIRECTOR)).json()
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["rooms"] == 52 and item["group"]["required"] is not None
    assert item["rooms_per_fte"] == round(52 / item["group"]["occupied"], 1)
    assert {c["name"] for c in item["cleaners"]} == {"Петрова Н. В.", "Сазонова Л. М."}
    territory = client.get("/api/staffing/cleaning", headers=login(MUNICIPAL)).json()
    assert territory["totals"]["schools"] == len(territory["items"]) > 1
    assert client.get("/api/staffing/cleaning", headers=login(OBSERVER)).status_code == 403


def test_position_is_removed_from_schedule(client, login):
    headers = login(*ADMIN)
    director_org = client.get("/api/auth/me", headers=login(DIRECTOR)).json()["organization_id"]
    items = client.get("/api/staffing/schedules", headers=headers).json()["items"]
    org = next(i for i in items if i["status"] and i["organization_id"] != director_org)
    url = f"/api/staffing/institutions/{org['organization_id']}"
    schedule = client.get(f"{url}/schedule", headers=headers).json()
    line = next(line for line in schedule["lines"] if line["approved"])

    assert client.delete(f"{url}/lines/{line['group_id']}",
                         headers=login(OBSERVER)).status_code == 403
    response = client.delete(f"{url}/lines/{line['group_id']}", headers=headers)
    assert response.status_code == 200, response.text
    after = response.json()
    assert not any(row["group_id"] == line["group_id"] and row["approved"]
                   for row in after["lines"])
    assert after["history"][0]["comment"].startswith("Удалена должность")
    assert client.delete(f"{url}/lines/{line['group_id']}", headers=headers).status_code == 404
