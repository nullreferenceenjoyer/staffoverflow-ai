"""Справочник групп нормирования и демо-данные раздела «Нормативная численность».

Группы — справочник: создаются при каждом запуске, если их нет. Нормативы, штатки
и показатели — только для демо: коэффициенты условные, их настраивает аналитик.
"""

from __future__ import annotations

import random
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    InstitutionMetrics,
    NormativeCoefficient,
    NormativeDocument,
    Organization,
    PersonnelGroup,
    ScheduleStatus,
    StaffingLine,
    StaffingSchedule,
    StaffingScheduleVersion,
)
from app.services import norms, payroll, staffing_analysis

# (код, название, категория, подкатегория, типы учреждений, примеры должностей)
GROUPS = [
    ("aup_management", "Руководство", "aup", "management", [], "Директор, заведующий"),
    ("aup_deputies", "Заместители директора", "aup", "management", [],
     "Заместитель директора, заместитель заведующего"),
    ("aup_accounting", "Бухгалтерия и финансово-экономическая служба", "aup", "specialists", [],
     "Главный бухгалтер, бухгалтер, экономист"),
    ("aup_clerical", "Делопроизводство", "aup", "clerical", [],
     "Секретарь, делопроизводитель, архивист"),
    ("aup_household", "Хозяйственная часть", "aup", "specialists", [],
     "Заведующий хозяйством, начальник хозяйственной части"),
    ("aup_other", "Прочее АУП", "aup", "other", [],
     "Диспетчер, специалист по кадрам, специалист по охране труда"),
    ("support_edu", "Учебно-вспомогательные специалисты", "support", "educational_support", [],
     "Педагог-психолог, учитель-логопед, социальный педагог, библиотекарь"),
    ("support_assistants", "Помощники воспитателя", "support", "educational_support",
     ["preschool", "complex"], "Помощник воспитателя, младший воспитатель"),
    ("support_cleaning", "Уборка помещений", "support", "service", [],
     "Уборщик служебных помещений, гардеробщик"),
    ("support_security", "Охрана", "support", "service", [], "Сторож, вахтёр, охранник"),
    ("support_kitchen", "Пищеблок", "support", "service", [], "Повар, кухонный рабочий"),
    ("support_maintenance", "Техническое обслуживание", "support", "service", [],
     "Рабочий по обслуживанию здания, электрик, слесарь-сантехник, дворник"),
]


def ensure_groups(db: Session) -> None:
    """Добавляет недостающие группы. Существующие не трогает: их могли переименовать."""
    known = set(db.scalars(select(PersonnelGroup.code)))
    for order, (code, name, category, sub, types, positions) in enumerate(GROUPS, start=1):
        if code not in known:
            db.add(PersonnelGroup(code=code, name=name, top_category=category, subcategory=sub,
                                  institution_types=types, positions=positions,
                                  is_active=True, sort_order=order * 10))
    db.flush()


D = Decimal

# (группа, тип учреждения, показатель, на сколько единиц, ставок, мин, макс, от, до, шаг, документ)
DEMO_NORMS = [
    ("aup_management", "all", "none", None, "1", None, None, None, None, None, "main"),
    ("aup_deputies", "all", "classes_count", "12", "1", "1", "5", None, None, "0.25", "main"),
    ("aup_deputies", "preschool", "groups_count", "6", "0.5", "0.5", "2", None, None, "0.25",
     "main"),
    ("aup_accounting", "all", "students_count", None, "1", None, None, None, "800", None, "main"),
    ("aup_accounting", "all", "students_count", None, "1.25", None, None, "801", None, None,
     "main"),
    ("aup_accounting", "preschool", "none", None, "0.5", None, None, None, None, None, "main"),
    ("aup_clerical", "all", "students_count", "300", "1", None, None, None, None, "0.25", "main"),
    ("aup_clerical", "preschool", "none", None, "0.5", None, None, None, None, None, "main"),
    ("aup_household", "all", "none", None, "1", None, None, None, None, None, "main"),
    ("support_edu", "all", "students_count", "250", "1", "1", None, None, None, "0.5", "main"),
    ("support_edu", "preschool", "groups_count", "4", "0.5", "0.5", None, None, None, "0.25",
     "main"),
    ("support_assistants", "all", "groups_count", "1", "1", None, None, None, None, None, "main"),
    ("support_cleaning", "all", "total_area_m2", "1000", "1", None, None, None, None, "0.25",
     "law"),
    ("support_security", "all", "none", None, "2", None, None, None, None, None, "main"),
    ("support_kitchen", "all", "students_count", "250", "1", "1", None, None, None, "0.5", "main"),
    ("support_maintenance", "all", "total_area_m2", "3000", "1", "1", None, None, None, "0.5",
     "main"),
]


def _d(value: str | None) -> Decimal | None:
    return None if value is None else D(value)


def seed_norms(db: Session, year: str) -> None:
    start, end = staffing_analysis.period(year)
    main = NormativeDocument(
        title="Нормативы численности АУП и вспомогательного персонала (демо, условные)",
        doc_type="приказ", number="123", issued_at=start, effective_from=start,
        effective_to=end, issuer="Управление образования (демо)", scope_level="region",
        status="active", source_ref="Демо-данные: коэффициенты условные, задайте свои")
    law = NormativeDocument(
        title="Нормы обслуживания помещений (демо, условные)", doc_type="закон", number="45",
        issued_at=date(start.year - 1, 12, 20), effective_from=date(start.year, 1, 1),
        issuer="Региональное законодательное собрание (демо)", scope_level="region",
        status="active")
    db.add_all([main, law])
    db.flush()
    documents = {"main": main, "law": law}
    groups = {g.code: g for g in db.scalars(select(PersonnelGroup))}
    for (code, kind, metric, unit, fte, low, high, since, until, step, doc) in DEMO_NORMS:
        document = documents[doc]
        db.add(NormativeCoefficient(
            document=document, personnel_group_id=groups[code].id, institution_type=kind,
            scope_level="region", metric=metric, unit_size=_d(unit), fte_per_unit=D(fte),
            min_fte=_d(low), max_fte=_d(high), applies_from=_d(since), applies_to=_d(until),
            rounding_step=_d(step), rounding_mode="up", priority=0,
            effective_from=document.effective_from, effective_to=document.effective_to,
            is_mandatory=True))
    db.flush()


def _metrics(rng: random.Random, org: Organization) -> dict:
    if org.org_type == "preschool":
        groups = rng.randint(6, 14)
        return {"students_count": groups * rng.randint(18, 24), "classes_count": None,
                "groups_count": groups, "total_area_m2": D(groups * rng.randint(130, 170))}
    students = rng.randint(380, 1150)
    groups = rng.randint(3, 8) if org.org_type == "complex" else None
    area = students * rng.randint(9, 13) + (groups or 0) * 150
    return {"students_count": students + (groups or 0) * 20,
            "classes_count": max(round(students / 25), 11), "groups_count": groups,
            "total_area_m2": D(area)}


# Сколько групп учреждения расходятся с нормативом и насколько. Большинство — в норме
# или с одной-двумя проблемными группами, как в жизни
OFF_GROUPS = (0, 0, 0, 1, 1, 1, 2, 2, 3)
OFFSETS = [D(x) for x in ("-1", "-0.75", "-0.5", "0.5", "0.75", "1", "1.5")]
# Вакансии: занято меньше утверждённого
VACANCY = [D(x) for x in ("0",) * 10 + ("0.25", "0.5", "1")]

# Пример из ТЗ: школа демо-директора
EXAMPLE_METRICS = {"students_count": 840, "classes_count": 34, "groups_count": None,
                   "total_area_m2": D(12000)}
EXAMPLE_LINES = {
    "aup_management": ("1", "1"), "aup_deputies": ("3.5", "3.5"), "aup_clerical": ("2", "2"),
    "aup_accounting": ("1", "0.5"), "aup_household": ("1", "1"),
    "support_edu": ("3.5", "3"), "support_cleaning": ("10", "9.5"), "support_security": ("2", "2"),
    "support_kitchen": ("4", "4"), "support_maintenance": ("4", "4"),
}


def seed_staffing_demo(db: Session, first_org_id: int | None = None) -> None:
    """Показатели и штатки на текущий учебный год, с отклонениями и пробелами в данных."""
    rng = random.Random(7)
    year = staffing_analysis.current_year()
    start, end = staffing_analysis.period(year)
    moment = staffing_analysis.analysis_date(year)
    ensure_groups(db)
    seed_norms(db, year)
    groups = list(db.scalars(select(PersonnelGroup).order_by(PersonnelGroup.sort_order)))
    by_code = {g.code: g for g in groups}
    coefficients = list(db.scalars(select(NormativeCoefficient)
                                   .options(selectinload(NormativeCoefficient.document))))
    orgs = list(db.scalars(select(Organization).order_by(Organization.id)))
    approved_at = datetime(start.year, 9, 1, 9, tzinfo=UTC)

    for index, org in enumerate(orgs):
        example = org.id == first_org_id
        values = EXAMPLE_METRICS if example else _metrics(rng, org)
        # Каждое седьмое учреждение не указало площадь — анализ скажет, чего не хватает
        if not example and index % 7 == 3:
            values = {**values, "total_area_m2": None}
        db.add(InstitutionMetrics(organization_id=org.id, academic_year=year, period_start=start,
                                  period_end=end, source="import", confirmed_at=approved_at,
                                  **values))
        if not example and index % 11 == 5:
            continue  # штатку ещё не загрузили
        status = (ScheduleStatus.draft if not example and index % 13 == 8
                  else ScheduleStatus.approved)
        schedule = StaffingSchedule(organization_id=org.id, academic_year=year,
                                    period_start=start, period_end=end, status=status,
                                    approved_at=approved_at if status == "approved" else None)
        tracks_occupancy = example or index % 9 != 4  # кое-где занятость не ведут
        lines = []
        if example:
            for code, (approved, occupied) in EXAMPLE_LINES.items():
                lines.append(StaffingLine(personnel_group_id=by_code[code].id,
                                          approved_fte=D(approved), occupied_fte=D(occupied)))
        else:
            required: dict[int, Decimal] = {}
            for group in groups:
                if not staffing_analysis.group_applies(group, org):
                    continue
                selected = norms.select(coefficients, org, group.id, moment, values)
                parts = [norms.compute(c, values) for c in selected]
                if parts:
                    required[group.id] = sum((p.fte or D(0) for p in parts), D(0))
            off = set(rng.sample(sorted(required), min(rng.choice(OFF_GROUPS), len(required))))
            for group_id, fte in required.items():
                approved = max(fte + (rng.choice(OFFSETS) if group_id in off else D(0)), D(0))
                occupied = max(approved - rng.choice(VACANCY), D(0))
                lines.append(StaffingLine(personnel_group_id=group_id, approved_fte=approved,
                                          occupied_fte=occupied if tracks_occupancy else None))
            if index % 10 == 6:
                # Ставки по группе без норматива: анализ попросит его настроить
                lines.append(StaffingLine(personnel_group_id=by_code["aup_other"].id,
                                          approved_fte=D("0.5"), occupied_fte=D("0.5")))
        schedule.lines = lines
        db.add(schedule)
    db.flush()
    seed_payroll(db, first_org_id)
    staffing_analysis.recalculate(db, year)


# Средний оклад за ставку по группе, ₽ в месяц (демо, условные)
SALARIES = {
    "aup_management": 78000, "aup_deputies": 62000, "aup_accounting": 46000,
    "aup_clerical": 32000, "aup_household": 39000, "aup_other": 35000,
    "support_edu": 41000, "support_assistants": 27000, "support_cleaning": 22500,
    "support_security": 24000, "support_kitchen": 30000, "support_maintenance": 27500,
}
# Как менялась штатка с начала года: (группа, сколько ставок было больше, повод)
CHANGES = [
    ("support_cleaning", D("1"), "Сокращение ставки уборщика после передачи уборки"),
    ("aup_clerical", D("0.5"), "Сокращение полставки делопроизводителя"),
    ("support_kitchen", D("-1"), "Добавлена ставка повара: открыта вторая смена"),
    ("aup_deputies", D("-0.5"), "Добавлены полставки заместителя по безопасности"),
    ("support_maintenance", D("1"), "Сокращение рабочего по обслуживанию здания"),
]


def seed_payroll(db: Session, example_org_id: int | None = None) -> None:
    """Демо-оклады в штатках и история изменений: часть учреждений за год что-то сократила
    или добавила, и в истории видно, как это сдвинуло ФОТ."""
    rng = random.Random(11)
    year = staffing_analysis.current_year()
    start, _ = staffing_analysis.period(year)
    groups = {g.id: g.code for g in db.scalars(select(PersonnelGroup))}
    schedules = list(db.scalars(select(StaffingSchedule)
                                .where(StaffingSchedule.academic_year == year)
                                .options(selectinload(StaffingSchedule.lines))
                                .order_by(StaffingSchedule.organization_id)))
    first = datetime(start.year, start.month, start.day, 9, tzinfo=UTC)
    for index, schedule in enumerate(schedules):
        example = schedule.organization_id == example_org_id
        for line in schedule.lines:
            base = SALARIES.get(groups.get(line.personnel_group_id, ""), 30000)
            factor = 1 if example else rng.uniform(0.9, 1.12)
            line.salary_rub = D(round(base * factor, -2))
        db.flush()
        current = payroll._lines_json(payroll.items_of(schedule))
        # У школы демо-директора в октябре сократили ставку уборщика
        change = CHANGES[0] if example else (CHANGES[index % len(CHANGES)]
                                             if index % 3 == 1 else None)
        by_code = {groups[line["group_id"]]: line for line in current}
        if change and change[0] in by_code:
            code, delta, comment = change
            before = [dict(line) for line in current]
            for line in before:
                if line["group_id"] == by_code[code]["group_id"]:
                    line["approved"] = max(float(D(str(line["approved"])) + delta), 0)
            _version(db, schedule, before, first, "Штатное расписание на учебный год")
            _version(db, schedule, current, first + timedelta(days=rng.randint(25, 45)),
                     comment)
        else:
            _version(db, schedule, current, first, "Штатное расписание на учебный год")
    db.flush()


def _version(db: Session, schedule: StaffingSchedule, lines: list[dict], moment: datetime,
             comment: str) -> None:
    total = payroll.Totals(payroll_approved=D(0), payroll_occupied=D(0))
    for line in lines:
        approved, salary = D(str(line["approved"])), D(str(line["salary"]))
        total.approved += approved
        total.payroll_approved += payroll.annual(approved, salary)
        if line["occupied"] is None or total.occupied is None:
            total.occupied = None
        else:
            occupied = min(D(str(line["occupied"])), approved) if approved else D(0)
            total.occupied += occupied
            total.payroll_occupied += payroll.annual(occupied, salary)
    db.add(StaffingScheduleVersion(
        schedule_id=schedule.id, organization_id=schedule.organization_id,
        academic_year=schedule.academic_year, created_at=moment, source="demo",
        status=schedule.status, comment=comment, lines=lines, approved_fte=total.approved,
        occupied_fte=total.occupied, payroll_approved=total.payroll_approved,
        payroll_occupied=None if total.occupied is None else total.payroll_occupied))


def seed_payroll_for_existing_demo(db: Session, example_org_id: int | None) -> bool:
    """Демо-база, созданная до появления окладов, получает их один раз."""
    if db.scalar(select(StaffingScheduleVersion.id).limit(1)) is not None:
        return False
    if db.scalar(select(StaffingLine.id).where(StaffingLine.salary_rub.is_not(None))
                 .limit(1)) is not None:
        return False
    seed_payroll(db, example_org_id)
    return True
