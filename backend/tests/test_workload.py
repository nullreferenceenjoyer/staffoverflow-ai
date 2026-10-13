"""Загрузка персонала по площадкам: группировка корпусов и расчёт объёма работы."""

from app.services.staffing import NormRule
from app.services.workload import (
    SiteBuilding,
    StaffRow,
    address_key,
    analyze,
    attribute_students,
    distance_m,
    group_sites,
)

CLEANING = NormRule("cleaning", "Уборка: 1 ставка на 600 м²", "cleaning", "area_sqm",
                    per_unit=1, unit_size=600, min_value=1)
CLERK = NormRule("clerk", "Делопроизводство", "clerk", "students_total", base=0.5,
                 per_unit=0.5, unit_size=400, max_value=2)
SECURITY = NormRule("security", "Охрана: 2,5 на здание", "security", "buildings", per_unit=2.5,
                    rounding=0.5)
TEACHER = NormRule("teacher", "Учителя", "teacher", "classes_total", per_unit=1.5)


def building(id_, org=1, area=300.0, lat=55.75, lon=37.6, **extra) -> SiteBuilding:
    return SiteBuilding(id=id_, org_id=org, org_name=f"СОШ № {org}", org_type="school",
                        municipality_id=1, municipality="Заречный г.о.", name=f"Корпус {id_}",
                        area=area, lat=lat, lon=lon, **extra)


def staff(building_id, code="cleaning", rate=1.0, org=1, **extra) -> StaffRow:
    return StaffRow(org_id=org, building_id=building_id, function_code=code, category="support",
                    rate=rate, pay=30000 * rate, people=1, **extra)


def metrics(**values) -> dict:
    return {"students_total": 0.0, "area_sqm": 0.0, "buildings": 0.0, **values}


def test_distance_between_buildings():
    # 0,001° широты — около 111 метров
    gap = distance_m(building(1), building(2, lat=55.751))
    assert 105 < gap < 117


def test_neighbours_form_one_site_and_far_building_stays_alone():
    near = [building(1), building(2, lat=55.7512)]
    far = building(3, lat=55.80)
    sites = group_sites([*near, far], radius_m=300)
    assert sorted(len(site) for site in sites) == [1, 2]
    # При нулевом радиусе рядом не стоит никто
    assert len(group_sites([*near, far], radius_m=0)) == 3


def test_buildings_in_different_municipalities_are_never_merged():
    other = building(2)
    other.municipality_id = 2
    assert len(group_sites([building(1), other], radius_m=300)) == 2


def test_same_house_is_one_site_even_without_coordinates():
    first = building(1, lat=None, lon=None, address="г.о. Лесной, ул. Школьная, д. 5")
    second = building(2, lat=None, lon=None, address="Лесной г.о., Школьная ул., 5, корп. 2")
    third = building(3, lat=None, lon=None, address="г.о. Лесной, ул. Школьная, д. 7")
    assert address_key(first.address) == address_key(second.address)
    assert sorted(len(s) for s in group_sites([first, second, third], 300)) == [1, 2]


def test_address_without_house_number_is_not_a_key():
    assert address_key("г.о. Лесной, ул. Школьная") is None


def test_students_follow_occupancy_then_capacity_then_area():
    pair = [building(1, capacity=300, occupancy=90), building(2, capacity=100, occupancy=10)]
    attribute_students(pair, 200)
    assert [round(b.students) for b in pair] == [180, 20]

    pair = [building(1, capacity=300), building(2, capacity=100)]
    attribute_students(pair, 200)
    assert [round(b.students) for b in pair] == [150, 50]

    pair = [building(1, area=900), building(2, area=300, capacity=100)]
    attribute_students(pair, 200)
    assert [round(b.students) for b in pair] == [150, 50]


def test_three_cleaners_in_adjacent_buildings_doing_the_work_of_one():
    """Тот самый случай из постановки: работы на одного, а занято трое."""
    buildings = [building(1, area=300), building(2, area=240, lat=55.7507)]
    rows = [staff(1), staff(2), staff(2, vacant_rate=1.0)]
    rows[2].people = 0
    report = analyze(buildings, rows, {1: metrics(area_sqm=540, buildings=2)}, [CLEANING])

    assert report["totals"]["sites"] == 1
    cleaning = report["sites"][0]["functions"][0]
    assert cleaning["actual"] == 3
    assert cleaning["volume"] == 0.9  # 540 м² при норме 600 м² на ставку
    assert cleaning["required"] == 1
    assert cleaning["load_pct"] == 30
    assert cleaning["excess"] == 2
    assert cleaning["verdict"] == "duplicate"
    assert "справится один" in cleaning["recommendation"]
    assert "1 ст. — вакансии" in cleaning["recommendation"]
    assert report["totals"]["vacant_in_excess"] == 1
    assert report["totals"]["saving_year"] == round(2 * 30000 * 12 * 1.302)


def test_same_staff_in_distant_buildings_is_not_duplication():
    buildings = [building(1, area=300), building(2, area=240, lat=55.80)]
    rows = [staff(1), staff(2)]
    report = analyze(buildings, rows, {1: metrics(area_sqm=540, buildings=2)}, [CLEANING])
    assert report["totals"]["sites"] == 2
    # Каждый корпус сам по себе: работы на полставки при целой ставке — это недозагрузка,
    # но не дублирование, и объединить уборщиков через весь город не предлагается
    assert [f["verdict"] for f in report["findings"]] == ["idle", "idle"]
    assert all(f["required"] == 0.5 for f in report["findings"])


def test_neighbouring_organizations_share_fractional_load():
    buildings = [building(1, org=1), building(2, org=2, lat=55.7508)]
    rows = [staff(1, "clerk", 1.5, org=1), staff(2, "clerk", 1.0, org=2)]
    per_org = {1: metrics(students_total=240), 2: metrics(students_total=160)}
    report = analyze(buildings, rows, per_org, [CLERK])

    site = report["sites"][0]
    assert site["organizations"] == 2
    clerk = site["functions"][0]
    # 0,5 + 0,3 и 0,5 + 0,2 — вместе 1,5 ставки работы на 2,5 занятых
    assert (clerk["volume"], clerk["required"], clerk["excess"]) == (1.5, 1.5, 1.0)
    assert clerk["verdict"] == "duplicate"


def test_posts_per_building_are_not_reduced():
    buildings = [building(1), building(2, lat=55.7507)]
    rows = [staff(1, "security", 2.5), staff(2, "security", 2.5)]
    report = analyze(buildings, rows, {1: metrics(buildings=2)}, [SECURITY])
    assert report["sites"][0]["functions"][0]["verdict"] == "ok"
    assert report["totals"]["excess"] == 0


def test_shortage_is_reported_as_overload_not_as_saving():
    report = analyze([building(1, area=1800)], [staff(1)], {1: metrics(area_sqm=1800)},
                     [CLEANING])
    cleaning = report["sites"][0]["functions"][0]
    assert cleaning["verdict"] == "overload"
    assert cleaning["saving_year"] == 0
    assert report["totals"]["excess"] == 0


def test_teaching_staff_is_out_of_scope():
    rows = [StaffRow(org_id=1, building_id=1, function_code="teacher", category="teaching",
                     rate=20)]
    report = analyze([building(1)], rows, {1: metrics(classes_total=10)}, [TEACHER])
    assert report["sites"][0]["functions"] == []


def test_unassigned_positions_go_to_main_building_and_are_counted():
    buildings = [building(1, area=900, capacity=400), building(2, area=300, lat=55.80)]
    report = analyze(buildings, [staff(None, rate=2.0)],
                     {1: metrics(area_sqm=1200, buildings=2)}, [CLEANING])
    assert report["totals"]["unassigned_rate"] == 2
    main = next(s for s in report["sites"] if s["buildings"][0]["id"] == 1)
    assert main["functions"][0]["actual"] == 2


def test_half_empty_building_is_flagged():
    report = analyze([building(1, capacity=800, occupancy=300)], [staff(1)],
                     {1: metrics(students_total=300, area_sqm=300)}, [CLEANING])
    finding = next(f for f in report["findings"] if f["verdict"] == "underused")
    assert finding["load_pct"] == 38
    assert "800 мест" in finding["recommendation"]


def test_requests_are_attached_to_the_function_of_the_site():
    report = analyze([building(1)], [staff(1)], {1: metrics(area_sqm=300)}, [CLEANING],
                     requests={(1, "cleaning"): 7, (99, "cleaning"): 3})
    assert report["sites"][0]["functions"][0]["requests"] == 7


DEPUTY = NormRule("deputy", "Заместители", "deputy_director", "students_total", base=0.5,
                  per_unit=1, unit_size=300)


def test_management_of_neighbouring_organizations_is_not_pooled():
    buildings = [building(1, org=1), building(2, org=2, lat=55.7508)]
    rows = [StaffRow(org_id=org, building_id=org, function_code="deputy_director",
                     category="admin", rate=2.0, people=2) for org in (1, 2)]
    per_org = {1: metrics(students_total=450), 2: metrics(students_total=90)}
    report = analyze(buildings, rows, per_org, [DEPUTY])

    deputies = report["sites"][0]["functions"]
    # У каждого учреждения свои заместители: первое загружено полностью, второе — нет
    assert [(f["organization"], f["volume"], f["verdict"]) for f in deputies] == [
        ("СОШ № 2", 0.8, "idle"), ("СОШ № 1", 2.0, "ok")]
    assert "(СОШ № 2)" in deputies[0]["recommendation"]
