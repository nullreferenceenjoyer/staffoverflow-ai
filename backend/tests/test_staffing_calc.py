"""Расчёт нормативной численности без базы: нормативы, допуск, статусы, нехватка данных."""

from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace as NS

from app.services import norms, staffing_analysis

MOMENT = date(2026, 10, 20)
ORG = NS(id=1, org_type="school", municipality_id=10)
DEPUTIES = NS(id=1, name="Заместители директора", top_category="aup", is_active=True,
              institution_types=[])
CLERICAL = NS(id=2, name="Делопроизводство", top_category="aup", is_active=True,
              institution_types=[])
ACCOUNTING = NS(id=3, name="Бухгалтерия", top_category="aup", is_active=True,
                institution_types=[])
OTHER = NS(id=4, name="Прочее АУП", top_category="aup", is_active=True, institution_types=[])
CLEANING = NS(id=5, name="Уборка помещений", top_category="support", is_active=True,
              institution_types=[])
GROUPS = [DEPUTIES, CLERICAL, ACCOUNTING, OTHER, CLEANING]


def coef(id, group, metric, fte, unit=None, **kw):
    values = dict(
        id=id, personnel_group_id=group.id, document_id=None, document=None,
        institution_type="all", scope_level="region", scope_id=None, metric=metric,
        unit_size=None if unit is None else D(str(unit)), fte_per_unit=D(str(fte)),
        min_fte=None, max_fte=None, applies_from=None, applies_to=None,
        rounding_step=D("0.25"), rounding_mode="up", tolerance_abs=None, tolerance_pct=None,
        priority=0, effective_from=None, effective_to=None, is_mandatory=True)
    for key, value in kw.items():
        values[key] = D(str(value)) if isinstance(value, int | float) and key not in (
            "priority", "scope_id") else value
    return NS(**values)


# Нормативы из примера ТЗ (раздел 15)
EXAMPLE = [
    coef(1, DEPUTIES, "classes_count", 1, 12),
    coef(2, CLERICAL, "students_count", 1, 300),
    coef(3, ACCOUNTING, "students_count", 1, applies_to=800),
    coef(4, ACCOUNTING, "students_count", 1.25, applies_from=801),
]


def metrics(**kw):
    values = {"students_count": 840, "classes_count": 34, "groups_count": None,
              "total_area_m2": D(12000), "confirmed_at": None}
    values.update(kw)
    return NS(**values)


def schedule(lines, status="approved"):
    return NS(status=status, approved_at=None, lines=[
        NS(personnel_group_id=group.id, approved_fte=D(str(a)),
           occupied_fte=None if o is None else D(str(o))) for group, a, o in lines])


EXAMPLE_LINES = [(DEPUTIES, 3.5, 3.5), (CLERICAL, 2, 2), (ACCOUNTING, 1, 0.5)]


def run(coefficients=EXAMPLE, lines=EXAMPLE_LINES, status="approved", m=None):
    rows = staffing_analysis.analyze(
        ORG, GROUPS, coefficients, None if lines is None else schedule(lines, status),
        m or metrics(), "2026/2027", MOMENT)
    return {(r.basis, r.category, r.group_name): r for r in rows}


def test_example_from_spec():
    rows = run()
    deputies = rows[("occupied", "aup", "Заместители директора")]
    # 34 / 12 = 2,83 -> вверх до 0,25 = 3,0; занято 3,5 — сверх норматива на 0,5
    assert (deputies.required, deputies.fact, deputies.deviation) == (D("3.00"), D("3.5"),
                                                                        D("0.50"))
    assert deputies.status == "surplus"
    clerical = rows[("occupied", "aup", "Делопроизводство")]
    assert (clerical.required, clerical.deviation, clerical.status) == (D("3.00"), D("-1.00"),
                                                                        "deficit")
    accounting = rows[("occupied", "aup", "Бухгалтерия")]
    assert (accounting.required, accounting.deviation) == (D("1.25"), D("-0.75"))
    total = rows[("occupied", "aup", None)]
    assert (total.required, total.fact, total.deviation, total.status) == (
        D("7.25"), D("6.0"), D("-1.25"), "deficit")
    assert total.severity == "high"
    # По штатке бухгалтерия укомплектована на 1,0 из 1,25
    assert rows[("approved", "aup", "Бухгалтерия")].deviation == D("-0.25")


def test_explanation_is_human_readable():
    part = norms.compute(EXAMPLE[0], {"classes_count": 34})
    assert part.snapshot["explain"] == ("1 ставка на 12 классов: 34 класса → 2,83, "
                                        "округление до 0,25 вверх = 3 ставки")
    assert norms.describe(EXAMPLE[3]) == "1,25 ставки при числе обучающихся от 801"
    capped = coef(5, DEPUTIES, "classes_count", 1, 12, min_fte=1, max_fte=4)
    assert norms.describe(capped) == "1 ставка на 12 классов, не меньше 1, не больше 4"


def test_small_deviation_within_tolerance_is_normal():
    rows = run(coefficients=[coef(1, DEPUTIES, "none", 4)], lines=[(DEPUTIES, 4.2, 4.2)])
    row = rows[("occupied", "aup", "Заместители директора")]
    assert (row.deviation, row.status, row.severity) == (D("0.20"), "normal", None)
    rows = run(coefficients=[coef(1, DEPUTIES, "none", 4)], lines=[(DEPUTIES, 5, 5)])
    assert rows[("occupied", "aup", "Заместители директора")].status == "surplus"


def test_min_max_and_rounding():
    capped = coef(1, DEPUTIES, "classes_count", 1, 12, min_fte=1, max_fte=2)
    assert norms.compute(capped, {"classes_count": 34}).fte == D("2.00")
    assert norms.compute(capped, {"classes_count": 3}).fte == D("1.00")
    down = coef(2, CLERICAL, "students_count", 1, 300, rounding_mode="down")
    assert norms.compute(down, {"students_count": 840}).fte == D("2.75")
    exact = coef(3, CLERICAL, "students_count", 1, 300)
    # 900 / 300 = 3 ровно — округление вверх не должно дать 3,25
    assert norms.compute(exact, {"students_count": 900}).fte == D("3.00")


def test_no_schedule_means_no_data_not_deficit():
    total = run(lines=None)[("occupied", "aup", None)]
    assert total.status == "no_data"
    assert total.reasons == ["нет штатного расписания на 2026/2027"]
    assert total.deviation is None


def test_draft_schedule_is_not_used():
    total = run(status="draft")[("approved", "aup", None)]
    assert total.status == "no_data"
    assert "не утверждено" in total.reasons[0]


def test_missing_metric_is_reported():
    rows = run(coefficients=[*EXAMPLE, coef(5, CLEANING, "total_area_m2", 1, 1000)],
               lines=[*EXAMPLE_LINES, (CLEANING, 10, 9)], m=metrics(total_area_m2=None))
    total = rows[("approved", "support", None)]
    assert total.status == "no_data"
    assert total.reasons == ["не указано: общая площадь помещений (Уборка помещений)"]
    # АУП от площади не зависит и считается
    assert rows[("approved", "aup", None)].status == "deficit"


def test_unknown_occupancy_gives_no_data_only_for_occupied_basis():
    rows = run(lines=[(DEPUTIES, 3, None), (CLERICAL, 3, 3), (ACCOUNTING, 1.25, 1.25)])
    assert rows[("occupied", "aup", "Заместители директора")].reasons == [
        "нет данных о занятых ставках"]
    assert rows[("occupied", "aup", None)].status == "no_data"
    assert rows[("approved", "aup", None)].status == "normal"


def test_group_without_norm_needs_attention():
    rows = run(lines=[(DEPUTIES, 3, 3), (CLERICAL, 3, 3), (ACCOUNTING, 1.25, 1.25),
                      (OTHER, 1, 1)])
    assert rows[("occupied", "aup", "Прочее АУП")].reasons == ["норматив не настроен"]
    total = rows[("occupied", "aup", None)]
    # Остальные группы в норме, но ставки без норматива нужно проверить
    assert total.status == "warning"
    assert total.reasons == ["норматив не настроен: Прочее АУП"]


def test_compensating_deviations_are_flagged():
    rows = run(lines=[(DEPUTIES, 4, 4), (CLERICAL, 2, 2), (ACCOUNTING, 1.25, 1.25)])
    total = rows[("occupied", "aup", None)]
    assert total.deviation == D("0.00")
    assert total.status == "warning"
    assert total.reasons[0] == "отклонения по группам компенсируют друг друга"


def test_most_specific_norm_wins():
    regional = coef(1, CLERICAL, "students_count", 1, 300)
    for_schools = coef(2, CLERICAL, "none", 2, institution_type="school")
    local = coef(3, CLERICAL, "none", 1.5, scope_level="organization", scope_id=ORG.id)
    other_org = coef(4, CLERICAL, "none", 9, scope_level="organization", scope_id=99)
    m = {"students_count": 840}
    assert norms.select([regional], ORG, CLERICAL.id, MOMENT, m) == [regional]
    assert norms.select([regional, for_schools], ORG, CLERICAL.id, MOMENT, m) == [for_schools]
    assert norms.select([regional, for_schools, local, other_org], ORG, CLERICAL.id, MOMENT,
                        m) == [local]


def test_norm_outside_its_dates_or_document_is_ignored():
    expired = coef(1, CLERICAL, "none", 1, effective_to=date(2026, 8, 31))
    future = coef(2, CLERICAL, "none", 1, effective_from=date(2027, 1, 1))
    archived = coef(3, CLERICAL, "none", 1, document=NS(status="archived"))
    assert norms.select([expired, future, archived], ORG, CLERICAL.id, MOMENT, {}) == []


def test_academic_year():
    assert staffing_analysis.current_year(date(2026, 10, 20)) == "2026/2027"
    assert staffing_analysis.current_year(date(2027, 5, 1)) == "2026/2027"
    assert staffing_analysis.period("2026/2027") == (date(2026, 9, 1), date(2027, 8, 31))
    assert staffing_analysis.analysis_date("2025/2026", date(2026, 10, 20)) == date(2026, 8, 31)
