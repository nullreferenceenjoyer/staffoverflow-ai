from app.services.centralization import build_scenario
from app.services.staffing import NormRule, build_report

ACCOUNTING = NormRule(code="acc", title="Бухгалтерия", function_code="accounting",
                      driver="students_total", base=1, per_unit=1, unit_size=500,
                      centralization_effect=0.4)
DIRECTOR = NormRule(code="dir", title="Директор", function_code="director",
                    driver="organization", per_unit=1, rounding=1)


def small_school(org_id: int, accountants: float):
    return build_report(
        org_id=org_id, name=f"Школа {org_id}", org_type="school", municipality_id=1,
        municipality="г.о. Тест",
        metrics={"students_total": 200.0, "organization": 1.0},
        actual=[
            {"function_code": "accounting", "category": "admin", "rate": accountants,
             "pay": accountants * 60_000},
            {"function_code": "director", "category": "admin", "rate": 1, "pay": 120_000},
        ],
        rules=[ACCOUNTING, DIRECTOR], payroll_tax_rate=0.3,
    )


def test_pooled_need_is_lower_than_sum_of_schools():
    scenario = build_scenario([small_school(i, 2) for i in range(1, 5)])
    accounting = scenario["functions"][0]

    assert accounting["actual"] == 8
    assert accounting["norm"] == 6  # 1,4 → 1,5 в каждой из четырёх школ
    # (4 × 1,4) × (1 − 0,4) = 3,36 → 3,5 при шаге 0,5
    assert accounting["centralized"] == 3.5
    assert accounting["released"] == 4.5
    assert scenario["saving_year"] == round(4.5 * 60_000 * 12 * 1.3)


def test_non_centralizable_functions_stay_in_every_stage():
    scenario = build_scenario([small_school(i, 2) for i in range(1, 5)])
    admin = next(s for s in scenario["stages"] if s["category"] == "admin")
    # 4 директора остаются на местах на всех этапах
    assert admin == {"category": "admin", "actual": 12, "norm": 10, "centralized": 7.5}


def test_center_keeps_at_least_one_rate():
    scenario = build_scenario([small_school(1, 1)])
    assert scenario["functions"][0]["centralized"] == 1.0
    assert scenario["released_total"] == 0


def test_empty_scope():
    scenario = build_scenario([])
    assert scenario["functions"] == []
    assert scenario["saving_year"] == 0
