import pytest

from app.services.staffing import NormRule, build_report, evaluate_rule, round_to_step

METRICS = {
    "students_total": 620.0,
    "classes_primary": 10.0,
    "special_needs": 14.0,
    "area_sqm": 4200.0,
    "buildings": 1.0,
    "organization": 1.0,
}


def rule(**kwargs) -> NormRule:
    defaults = {"code": "x", "title": "Норматив", "function_code": "cleaning", "driver": "area_sqm"}
    return NormRule(**{**defaults, **kwargs})


@pytest.mark.parametrize(
    ("value", "step", "expected"),
    [(13.89, 0.25, 14.0), (0.125, 0.25, 0.25), (0.12, 0.25, 0.0), (2.4, 0.5, 2.5), (7.3, 1, 7.0)],
)
def test_round_to_step(value, step, expected):
    assert round_to_step(value, step) == expected


def test_per_unit_formula():
    # 1 ставка на 600 м² при 4200 м² — ровно 7 ставок
    result = evaluate_rule(rule(per_unit=1, unit_size=600), "school", METRICS)
    assert result.value == 7.0
    assert "4200" in result.explanation


def test_hours_based_teacher_norm():
    # 10 классов × 25 ч / 18 ч на ставку = 13,89 → 14,0 при шаге 0,25
    teacher = rule(function_code="teacher", driver="classes_primary", per_unit=25, unit_size=18)
    assert evaluate_rule(teacher, "school", METRICS).value == 14.0


def test_base_and_limits():
    accounting = rule(driver="students_total", base=1, per_unit=1, unit_size=500, max_value=2)
    result = evaluate_rule(accounting, "school", METRICS)
    assert result.raw == 2  # 1 + 620/500 = 2,24, но не больше максимума
    assert result.value == 2.0


def test_rule_is_skipped_for_other_org_type():
    preschool_only = rule(per_unit=1, unit_size=600, org_types=("preschool",))
    assert evaluate_rule(preschool_only, "school", METRICS) is None


def test_rule_is_skipped_below_threshold():
    speech = rule(driver="special_needs", per_unit=1, unit_size=12, threshold=20)
    assert evaluate_rule(speech, "school", METRICS) is None


def make_report(actual, rules):
    return build_report(
        org_id=1, name="СОШ № 1", org_type="school", municipality_id=1, municipality="г.о. Тест",
        metrics=METRICS, actual=actual, rules=rules, payroll_tax_rate=0.3, tolerance=0.25,
    )


def test_report_compares_actual_with_norm():
    report = make_report(
        actual=[
            {"function_code": "cleaning", "category": "support", "rate": 9, "pay": 270_000},
            {"function_code": "accounting", "category": "admin", "rate": 1, "pay": 60_000},
        ],
        rules=[
            rule(per_unit=1, unit_size=600),
            rule(code="acc", function_code="accounting", driver="students_total", base=1,
                 per_unit=1, unit_size=500),
        ],
    )
    lines = {line.function_code: line for line in report.lines}
    assert lines["cleaning"].delta == 2.0
    assert lines["accounting"].delta == -1.25
    assert report.surplus == 2.0
    assert report.shortage == 1.25
    # 2 лишние ставки × 30 000 ₽ × 12 мес. × 1,3
    assert report.saving_potential_year == 936_000


def test_function_without_norm_is_not_a_deviation():
    report = make_report(
        actual=[{"function_code": "additional_education", "category": "teaching", "rate": 3,
                 "pay": 150_000}],
        rules=[rule(per_unit=1, unit_size=600)],
    )
    line = next(x for x in report.lines if x.function_code == "additional_education")
    assert line.norm_rate is None
    assert line.delta == 0
    # В нормативный итог такая функция входит по факту, иначе итоги нельзя сравнивать
    assert report.norm_total == 3 + 7


def test_missing_function_becomes_shortage():
    report = make_report(actual=[], rules=[rule(per_unit=1, unit_size=600)])
    assert report.shortage == 7.0
    assert report.compliance == 0.0


def test_allowance_does_not_affect_headcount():
    allowance = rule(code="a", function_code="teacher", driver="classes_primary", per_unit=5000,
                     rounding=0, kind="allowance")
    report = make_report(actual=[], rules=[allowance])
    assert report.lines == []
    assert report.allowances[0].value == 50_000
