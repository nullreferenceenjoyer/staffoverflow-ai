"""Программа оптимизации штатных расписаний — факт по документам управления.

Источник — файл seed/program.local.json (в git не попадает: в нём ФИО уволенных):
итоги программы, высвобождение по 25 школам, расчёт по должностям и уволенные по
приказам. Данные загружаются один раз; дальше уволенных ведут в интерфейсе.

Если база демонстрационная (сгенерированные школы «OU-…»), реальные школы заменяют
демо-школы: пользователи и бригады переходят на реальные школы, демо-заявки и
демо-штатки удаляются. Ничего, чего нет в документах, не придумывается.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.models import (
    Dismissal,
    Municipality,
    Organization,
    ProgramPosition,
    ProgramSchool,
    User,
    brigade_organizations,
)
from app.services import app_settings

log = logging.getLogger(__name__)
KEY = "program"
BASIS_TITLES = {"own": "По собственному желанию", "layoff": "Сокращение штата"}


def _d(value) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _date(value) -> date | None:
    return date.fromisoformat(value) if value else None


def dismissed_by_org(db: Session) -> dict[int, dict[str, float]]:
    """Сколько ставок ушло по собственному желанию и по сокращению — без фамилий."""
    out: dict[int, dict[str, float]] = {}
    for item in db.scalars(select(Dismissal)):
        slot = out.setdefault(item.organization_id, {"own": 0.0, "layoff": 0.0, "people": 0})
        slot[item.basis] = slot.get(item.basis, 0.0) + float(item.fte)
        slot["people"] += 1
    return out


def _same(a: str, b: str) -> bool:
    def norm(text: str) -> str:
        return " ".join(text.lower().replace("ё", "е").split())

    return norm(a) == norm(b)


def _close(a: str, b: str) -> bool:
    a, b = a.lower().replace("ё", "е"), b.lower().replace("ё", "е")
    return a in b or b in a


def find_line(db: Session, item: Dismissal, year: str):
    """Строка штатки, где работал уволенный: та же должность в его школе. Сначала точное
    совпадение названия, потом частичное («Уборщик» ↔ «Уборщик служебных помещений»)."""
    from app.models import StaffingLine, StaffingSchedule  # noqa: PLC0415

    lines = list(db.scalars(
        select(StaffingLine).join(StaffingSchedule)
        .where(StaffingSchedule.organization_id == item.organization_id,
               StaffingSchedule.academic_year == year)))
    for match in (_same, _close):
        found = [x for x in lines if x.position and match(x.position, item.position)
                 and float(x.occupied_fte if x.occupied_fte is not None else x.approved_fte) > 0]
        if found:
            return max(found, key=lambda x: x.occupied_fte or x.approved_fte or 0)
    return None


def _changed(db: Session, line, user, comment: str) -> None:
    """После правки строки: версия штатки и пересчёт анализа школы."""
    from app.models import StaffingSchedule  # noqa: PLC0415
    from app.services import payroll, staffing_analysis  # noqa: PLC0415

    schedule = db.get(StaffingSchedule, line.schedule_id)
    db.flush()
    payroll.snapshot(db, schedule, user, "dismissal", comment)
    staffing_analysis.recalculate(db, schedule.academic_year, [schedule.organization_id])


def apply_dismissal(db: Session, item: Dismissal, user, year: str) -> bool:
    """Учитывает увольнение в штатке: «занято» в строке должности уменьшается на ставку
    уволенного, ставка становится вакантной. False — подходящей строки нет."""
    if item.applied_fte is not None:
        return True
    line = find_line(db, item, year)
    if line is None:
        return False
    occupied = line.occupied_fte if line.occupied_fte is not None else line.approved_fte
    take = min(item.fte, occupied)
    line.occupied_fte = occupied - take
    # Совмещение — часть занятых ставок: больше занятого его не бывает
    combined_cut = Decimal(0)
    if line.combined_fte is not None and line.combined_fte > line.occupied_fte:
        combined_cut = line.combined_fte - line.occupied_fte
        line.combined_fte = line.occupied_fte or None
    item.line_id = line.id
    item.applied_fte = take
    item.applied_combined = combined_cut or None
    _changed(db, line, user, f"Увольнение: {item.position}, −{take} ст.")
    return True


def revert_dismissal(db: Session, item: Dismissal, user) -> None:
    """Отменяет учёт увольнения в штатке: ставка снова занята."""
    if item.applied_fte is None:
        return
    line = item.line
    if line is not None:
        line.occupied_fte = (line.occupied_fte or Decimal(0)) + item.applied_fte
        if item.applied_combined:
            line.combined_fte = (line.combined_fte or Decimal(0)) + item.applied_combined
        _changed(db, line, user, f"Отмена увольнения: {item.position}, +{item.applied_fte} ст.")
    item.line_id = None
    item.applied_fte = None
    item.applied_combined = None


def summary(db: Session) -> dict | None:
    from app.models import AppSetting  # noqa: PLC0415

    stored = db.get(AppSetting, KEY)
    return dict(stored.value) if stored is not None and stored.value else None


def load(db: Session, path: Path) -> bool:
    """Загружает программу из файла, если её ещё нет. True — что-то загрузили."""
    if not path.exists() or summary(db) is not None:
        return False
    data = json.loads(path.read_text(encoding="utf-8"))
    municipality = db.scalar(select(Municipality).where(Municipality.name == data["okrug"]))
    if municipality is None:
        municipality = Municipality(name=data["okrug"])
        db.add(municipality)
        db.flush()

    schools: dict[str, Organization] = {}
    for item in data["schools"]:
        org = db.scalar(select(Organization).where(Organization.external_id == item["code"]))
        if org is None:
            org = Organization(name=item["name"], external_id=item["code"],
                               municipality_id=municipality.id,
                               org_type=item.get("type", "school"), buildings=[])
            from app.models import Building  # noqa: PLC0415

            org.buildings.append(Building(name="Основное здание"))
            db.add(org)
        schools[item["code"]] = org
    db.flush()
    _replace_demo_schools(db, data, schools)

    for order, item in enumerate(data["schools"], start=1):
        db.add(ProgramSchool(
            organization_id=schools[item["code"]].id, sort_order=order,
            total=_d(item["total"]), vacancies=_d(item["vacancies"]),
            load_reduction=_d(item["load"]), resignations=_d(item["own"]),
            layoffs=_d(item["layoff"]), hours=item["hours"], staff_units=item["units"],
            orders_note=item.get("orders")))
    for order, row in enumerate(data["positions"], start=1):
        category, name, before, cut, after, local, local_eco, regional, regional_eco = row
        db.add(ProgramPosition(
            sort_order=order, category=category, name=name, before_fte=_d(before),
            cut_fte=_d(cut), after_fte=_d(after), local_cut=_d(local),
            local_economy_month=_d(local_eco), regional_cut=_d(regional),
            regional_economy_month=_d(regional_eco)))
    for item in data["dismissals"]:
        db.add(Dismissal(
            organization_id=schools[item["school"]].id, full_name=item["name"],
            position=item["position"], fte=_d(item["fte"]), basis=item["basis"],
            article=item.get("article"), order_number=item.get("order"),
            order_date=_date(item.get("order_date")),
            dismissed_on=_date(item.get("dismissed_on")),
            notified_on=_date(item.get("notified_on")), note=item.get("note"),
            source=item.get("source")))
    from app.models import AppSetting  # noqa: PLC0415

    db.add(AppSetting(key=KEY, value={**data["program"], "version": data.get("version")}))
    db.flush()
    log.info("Program loaded: %d schools, %d dismissals", len(schools), len(data["dismissals"]))
    return True


def _replace_demo_schools(db: Session, data: dict, schools: dict[str, Organization]) -> None:
    """Демо-школы «OU-…» уступают место реальным: пользователи и бригады переходят на
    реальные школы (школа демо-директора — на школу с пометкой director), остальное
    демо удаляется."""
    demo = list(db.scalars(select(Organization).where(Organization.external_id.like("OU-%"))
                           .order_by(Organization.id)))
    if not demo:
        return
    director = db.scalar(select(User).where(User.email == "director@demo.ru"))
    first = next((s["code"] for s in data["schools"] if s.get("director")),
                 data["schools"][0]["code"])
    others = [schools[s["code"]] for s in data["schools"] if s["code"] != first]
    target: dict[int, Organization] = {}
    if director and director.organization_id:
        target[director.organization_id] = schools[first]
    rest = iter(others)
    for org in demo:
        if org.id not in target:
            target[org.id] = next(rest, schools[first])
    for old, new in target.items():
        db.execute(update(User).where(User.organization_id == old)
                   .values(organization_id=new.id))
    links = db.execute(select(brigade_organizations)).all()
    keep = {(b, target[o].id if o in target else o) for b, o in links}
    db.execute(delete(brigade_organizations))
    if keep:
        db.execute(brigade_organizations.insert(),
                   [{"brigade_id": b, "organization_id": o} for b, o in sorted(keep)])
    db.execute(delete(Organization).where(Organization.id.in_([o.id for o in demo])))
    db.flush()
    log.info("Demo schools replaced with %d real schools", len(schools))


def load_from_settings(db: Session) -> bool:
    from app.config import get_settings  # noqa: PLC0415

    path = Path(get_settings().seed_dir) / "program.local.json"
    loaded = load(db, path)
    filled = fill(db, path)
    return loaded or filled


FILL_KEY = "program_fill"


def _sync_dismissals(db: Session, data: dict, orgs: dict[str, Organization]) -> None:
    """Приказы по школам расчёта — ровно те, что в документах: недостающие возвращаются
    (в штатке не учтены — расчёт показывает состояние до них), посторонние убираются."""
    wanted = {(orgs[d["school"]].id, d["name"], d.get("order")): d for d in data["dismissals"]}
    ids = [o.id for o in orgs.values()]
    have = set()
    for item in db.scalars(select(Dismissal).where(Dismissal.organization_id.in_(ids))):
        key = (item.organization_id, item.full_name, item.order_number)
        if key in wanted:
            have.add(key)
        else:
            db.delete(item)
    for key, d in wanted.items():
        if key in have:
            continue
        db.add(Dismissal(
            organization_id=key[0], full_name=d["name"], position=d["position"],
            fte=_d(d["fte"]), basis=d["basis"], article=d.get("article"),
            order_number=d.get("order"), order_date=_date(d.get("order_date")),
            dismissed_on=_date(d.get("dismissed_on")), notified_on=_date(d.get("notified_on")),
            note=d.get("note"), source=d.get("source")))
    db.flush()


def _okrug(db: Session, data: dict) -> Municipality:
    municipality = db.scalar(select(Municipality).where(Municipality.name == data["okrug"]))
    if municipality is None:
        municipality = Municipality(name=data["okrug"])
        db.add(municipality)
        db.flush()
    return municipality


def _extra_schools(db: Session, data: dict) -> dict[str, Organization]:
    """Школы округа, которых нет в расчёте управления (fill.extra_schools)."""
    from app.models import Building  # noqa: PLC0415

    out: dict[str, Organization] = {}
    items = data["fill"].get("extra_schools", [])
    if not items:
        return out
    municipality = _okrug(db, data)
    for item in items:
        org = db.scalar(select(Organization).where(Organization.external_id == item["code"]))
        if org is None:
            org = Organization(name=item["name"], external_id=item["code"],
                               municipality_id=municipality.id, buildings=[])
            org.buildings.append(Building(name="Основное здание"))
            db.add(org)
        org.name = item["name"]
        org.org_type = item.get("type", "school")
        org.latitude, org.longitude = _d(item["lat"]), _d(item["lon"])
        out[item["code"]] = org
    db.flush()
    return out


WORKERS = ["Антонов В. С.", "Борисов Д. И.", "Васильев К. Н.", "Голубев А. П.",
           "Давыдов С. М.", "Ершов Н. В.", "Зайцев П. А.", "Ильин Р. Д.", "Карпов Е. Л.",
           "Лебедев М. Ю.", "Миронов Г. С.", "Никитин О. В.", "Орлов Т. А.", "Павлов Ю. Б.",
           "Романов И. Г.", "Соколов В. Е.", "Титов А. К.", "Уваров Л. Н.", "Фролов С. Д.",
           "Хохлов П. И.", "Цветков Д. А.", "Чернов Б. В.", "Шилов Н. С.", "Щукин В. Р.",
           "Яковлев А. М."]


def _executors(db: Session, orgs: list[Organization], rng) -> dict[int, list[int]]:
    """Рабочие хозотдела по школам. Где в системе никого нет, заводится один рабочий —
    иначе все заявки школы висели бы «без исполнителя»."""
    from app.models import Role  # noqa: PLC0415
    from app.security import hash_password  # noqa: PLC0415

    out: dict[int, list[int]] = {}
    ids = [o.id for o in orgs]
    for user in db.scalars(select(User).where(User.role == Role.executor, User.is_active,
                                              User.organization_id.in_(ids))):
        out.setdefault(user.organization_id, []).append(user.id)
    password = None
    names = iter(rng.sample(WORKERS, len(WORKERS)) * 2)
    for org in orgs:
        if org.id in out:
            continue
        email = f"worker-{org.external_id.lower()}@demo.ru"
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            password = password or hash_password("demo12345")
            user = User(email=email, full_name=next(names), role=Role.executor,
                        organization_id=org.id, password_hash=password)
            db.add(user)
            db.flush()
        out[org.id] = [user.id]
    return out


def _brigades(db: Session, data: dict) -> dict:
    """Бригады управления из fill.brigades: заводит недостающие и их сотрудников.
    Бригады без людей, которых нет в списке, убираются — в демо их заводили для проб."""
    from app.models import Brigade, Role  # noqa: PLC0415
    from app.security import hash_password  # noqa: PLC0415

    conf = data["fill"].get("brigades", {})
    if not conf:
        return {}
    municipality = _okrug(db, data)
    existing = {b.name: b for b in db.scalars(select(Brigade))}
    for name, brigade in existing.items():
        if name not in conf and not brigade.members:
            db.delete(brigade)
    out = {}
    password = None
    taken = set(db.scalars(select(User.email).where(User.email.like("brigade%@demo.ru"))))
    number = 0
    for name, item in conf.items():
        brigade = existing.get(name)
        if brigade is None:
            brigade = Brigade(name=name, topics=[])
            db.add(brigade)
        brigade.municipality_id = municipality.id
        brigade.latitude, brigade.longitude = _d(item["base"][0]), _d(item["base"][1])
        brigade.base_address = item.get("address") or brigade.base_address
        brigade.is_active = True
        if item.get("all"):
            brigade.topics = ["electrical", "it"]
        db.flush()
        if not brigade.members:
            for full_name in item.get("members", []):
                number += 1
                while f"brigade{number}@demo.ru" in taken:
                    number += 1
                password = password or hash_password("demo12345")
                db.add(User(email=f"brigade{number}@demo.ru", full_name=full_name,
                            role=Role.brigade, brigade_id=brigade.id, password_hash=password))
                taken.add(f"brigade{number}@demo.ru")
            db.flush()
            db.refresh(brigade)
        out[brigade] = item
    return out


def fill(db: Session, path: Path) -> bool:
    """Заполняет школы штаткой «до», нормативом «после», показателями и заявками
    по расчёту управления (см. program_fill.py). Один раз на версию файла."""
    import random  # noqa: PLC0415
    from datetime import UTC, datetime, timedelta  # noqa: PLC0415

    from sqlalchemy import insert  # noqa: PLC0415

    from app.models import (  # noqa: PLC0415
        AppSetting,
        IncomingRequest,
        InstitutionMetrics,
        NormativeCoefficient,
        NormativeDocument,
        PersonnelGroup,
        StaffingLine,
        StaffingSchedule,
    )
    from app.services import (  # noqa: PLC0415
        payroll,
        program_fill,
        staffing_analysis,
        workload,
    )
    from app.services.staffing import get_schedule  # noqa: PLC0415

    if not path.exists():
        return False
    data = json.loads(path.read_text(encoding="utf-8"))
    if "fill" not in data:
        return False
    # fill-4: приказы об увольнении сверяются с документами (тестовые правки убираются)
    version = f"{data.get('version')}-fill-4"
    marker = db.get(AppSetting, FILL_KEY)
    if marker is not None and (marker.value or {}).get("version") == version:
        return False
    plan = program_fill.build(data)
    year = staffing_analysis.current_year()
    start, end = staffing_analysis.period(year)
    orgs = {o.external_id: o for o in db.scalars(select(Organization).where(
        Organization.external_id.in_([s["code"] for s in data["schools"]])))}
    if len(orgs) != len(data["schools"]):
        return False

    # Должности расчёта — группы нормирования: норматив задан по каждой должности
    known = {g.code: g for g in db.scalars(select(PersonnelGroup))}
    groups: dict[str, PersonnelGroup] = {}
    for order, (category, name, *_rest) in enumerate(plan["positions"], start=1):
        code = f"dmt_{order:02d}"
        group = known.get(code) or PersonnelGroup(code=code)
        group.name = name
        group.top_category = "aup" if name in plan["aup"] else "support"
        group.subcategory = plan["buckets"].get(name, "other")
        group.positions = name
        group.institution_types = []
        group.is_active = True
        group.sort_order = order
        db.add(group)
        groups[name] = group
    for code, group in known.items():
        if not code.startswith("dmt_"):
            group.is_active = False
    db.flush()

    extra = _extra_schools(db, data)

    # Прежние штатки, показатели и нормативы школ заменяются заполнением
    ids = [o.id for o in [*orgs.values(), *extra.values()]]
    db.execute(update(Dismissal).where(Dismissal.organization_id.in_(ids))
               .values(line_id=None, applied_fte=None, applied_combined=None))
    _sync_dismissals(db, data, orgs)
    db.execute(delete(StaffingSchedule).where(StaffingSchedule.organization_id.in_(ids)))
    db.execute(delete(InstitutionMetrics).where(InstitutionMetrics.organization_id.in_(ids)))
    db.execute(delete(NormativeCoefficient).where(
        NormativeCoefficient.scope_level == "organization",
        NormativeCoefficient.scope_id.in_(ids)))
    db.execute(delete(IncomingRequest).where(IncomingRequest.organization_id.in_(ids),
                                             IncomingRequest.classified_by == "fill"))
    head = data["program"]
    # Реквизиты расчёта — из файла: номер, дата и кто выпустил
    doc = head.get("document") or {}
    number = doc.get("number") or "РАСЧЁТ-УО"
    document = db.scalar(select(NormativeDocument).where(NormativeDocument.number == number))
    if document is None:
        document = NormativeDocument(
            title="Целевая штатка школ после оптимизации (расчёт управления образования)",
            doc_type="расчёт", number=number,
            issued_at=_date(doc.get("date")) or _date(head.get("state_date")) or start,
            effective_from=start,
            issuer=doc.get("issuer") or f"Управление образования ({data['okrug']})",
            scope_level="organization", status="active", source_ref=head.get("passport"))
        db.add(document)
        db.flush()

    by_school: dict[str, dict[str, dict]] = {}
    for (code, name), cell in plan["cells"].items():
        by_school.setdefault(code, {})[name] = cell
    rng = random.Random(2026)
    settings = app_settings.workload(db)
    # Сколько часов заявок одна ставка берёт за 90 дней: заявки — только часть её времени
    rate_hours = workload.workdays(90) * settings["hours_per_day"] \
        * settings["target_load_pct"] / 100 * settings["requests_share_pct"] / 100
    now = datetime.now(UTC)
    titles: dict[str, list[str]] = {
        "furniture": ["Починить парту в кабинете", "Отремонтировать дверцу шкафа",
                      "Собрать шкафчики в раздевалке"],
        "plumbing": ["Течёт кран в туалете", "Засор раковины в столовой",
                     "Не греет батарея в классе"],
        "electrical": ["Не горят лампы в коридоре", "Заменить розетку в кабинете",
                       "Заменить выключатель"],
        "repair": ["Не закрывается замок двери", "Заменить разбитое стекло",
                   "Покрасить стену после протечки"],
        "supplies": ["Заменить расходные материалы", "Получить и расставить инвентарь"],
    }
    rkorz = "Рабочий по комплексному обслуживанию и ремонту зданий"
    requests: list[dict] = []
    executors = _executors(db, [*orgs.values(), *extra.values()], rng)

    def request(org: Organization, topic: str, hours: float, **extra) -> dict:
        created = now - timedelta(days=rng.uniform(0.2, 88), hours=rng.uniform(0, 8))
        urgent = rng.random() < 0.12
        days = 1 if urgent else extra.pop("days", 5)
        extra.pop("days", None)
        item = {
            "organization_id": org.id,
            "building_id": org.buildings[0].id if org.buildings else None,
            "title": rng.choice(titles[topic]), "text": "Заявка хозотделу школы",
            "kind": "urgent" if urgent else "planned", "topic": topic,
            "routed_role": "executor", "classified_by": "fill", "effort_hours": _d(hours),
            "complexity": "simple", "effort_by": "rules", "created_at": created,
            "brigade_id": None, "assignee_id": None,
            **program_fill.life(created, now, rng, days)}
        item.update(extra)
        if item["status"] != "new" and item["brigade_id"] is None and executors.get(org.id):
            item["assignee_id"] = rng.choice(executors[org.id])
        return item

    def own_requests(org: Organization, rk_after: float) -> None:
        """Заявки своему хозотделу за 90 дней: работы ровно на целевые ставки рабочих."""
        if not rk_after:
            return
        for value in program_fill.requests_plan(rk_after * rate_hours - 0.5, rng):
            requests.append(request(org, rng.choice(list(titles)), value))

    fill_schools = data["fill"]["schools"]
    for school in data["schools"]:
        org = orgs[school["code"]]
        students, lat, lon = fill_schools[school["code"]]
        org.latitude, org.longitude = _d(lat), _d(lon)
        cells = by_school.get(school["code"], {})
        schedule = get_schedule(db, org, year)
        schedule.status = "approved"
        schedule.approved_at = now
        schedule.comment = "Штатка до оптимизации (на 15.06.2026) — заполнено по расчёту УО"
        for name, cell in cells.items():
            schedule.lines.append(StaffingLine(
                personnel_group_id=groups[name].id, position=name,
                approved_fte=_d(cell["approved"]), occupied_fte=_d(cell["occupied"]),
                combined_fte=_d(cell["combined"]) if cell["combined"] else None,
                salary_rub=_d(plan["salary"][name])))
            db.add(NormativeCoefficient(
                document=document, personnel_group_id=groups[name].id,
                institution_type="all", scope_level="organization", scope_id=org.id,
                metric="none", fte_per_unit=_d(cell["after"]), rounding_mode="nearest",
                tolerance_abs=Decimal(0), tolerance_pct=Decimal(0), priority=0,
                effective_from=start, is_mandatory=True,
                comment="Целевая штатка «после» по расчёту управления"))
        # Показатели: площадь подобрана так, чтобы расчёт уборщиц дал целевую штатку
        cleaners = cells.get("Уборщик служебных помещений", {})
        norm = app_settings.cleaning(db)
        classes = max(round(students / 25), 1)
        target = cleaners.get("after", 0)
        if target:
            classes = min(classes, int(target * norm["classes_per_rate"]))
        helpers = cells.get("Помощник воспитателя", {}).get("after", 0)
        db.add(InstitutionMetrics(
            organization_id=org.id, academic_year=year, period_start=start, period_end=end,
            students_count=students, classes_count=classes,
            groups_count=round(helpers) or None,
            total_area_m2=_d(round(target * norm["area_per_rate"], 1)) if target else None,
            rooms_count=classes + 10,
            cleaners_fte=_d(cleaners.get("approved")),
            maintenance_fte=_d(cells.get(rkorz, {}).get("approved")),
            source="import", confirmed_at=now))
        own_requests(org, cells.get(rkorz, {}).get("after", 0))

    # Школы вне расчёта управления: штатка ровно по нормативу, высвобождать нечего
    norm = app_settings.cleaning(db)
    for conf in data["fill"].get("extra_schools", []):
        org = extra[conf["code"]]
        lines, classes = program_fill.school_in_norm(conf["students"], norm["classes_per_rate"])
        schedule = get_schedule(db, org, year)
        schedule.status = "approved"
        schedule.approved_at = now
        schedule.comment = "Штатка на 15.06.2026 — в пределах норматива"
        for name, value in lines.items():
            schedule.lines.append(StaffingLine(
                personnel_group_id=groups[name].id, position=name, approved_fte=_d(value),
                occupied_fte=_d(value), salary_rub=_d(plan["salary"][name])))
            db.add(NormativeCoefficient(
                document=document, personnel_group_id=groups[name].id,
                institution_type="all", scope_level="organization", scope_id=org.id,
                metric="none", fte_per_unit=_d(value), rounding_mode="nearest",
                tolerance_abs=Decimal(0), tolerance_pct=Decimal(0), priority=0,
                effective_from=start, is_mandatory=True,
                comment="Целевая штатка совпадает с действующей"))
        cleaners = lines["Уборщик служебных помещений"]
        db.add(InstitutionMetrics(
            organization_id=org.id, academic_year=year, period_start=start, period_end=end,
            students_count=conf["students"], classes_count=classes,
            total_area_m2=_d(round(cleaners * norm["area_per_rate"], 1)),
            rooms_count=classes + 8, cleaners_fte=_d(cleaners),
            maintenance_fte=_d(lines[rkorz]), source="import", confirmed_at=now))
        own_requests(org, lines[rkorz])
    db.flush()

    # Бригады управления: база и школы по расположению, люди и выезды на сложные работы
    everyone = [*orgs.values(), *extra.values()]
    for brigade, conf in _brigades(db, data).items():
        chosen = [o for o in everyone
                  if conf.get("all") or ("north_of" in conf and o.latitude >= conf["north_of"])
                  or ("south_of" in conf and o.latitude < conf["south_of"])]
        brigade.organizations = sorted(chosen, key=lambda o: o.name)
        members = [u.id for u in brigade.members]
        wide = bool(conf.get("all"))  # бригада на весь округ — выезжает реже
        for org in chosen:
            # Выезд бригады — работа на день-три: заменить участок трубы, перекрыть пол
            for _ in range(rng.randint(0, 1) if wide else rng.randint(1, 3)):
                topic = "electrical" if wide else rng.choice(["plumbing", "repair", "furniture"])
                item = request(
                    org, topic, rng.choice([4, 6, 8] if wide else [12, 16, 20, 24]), days=10,
                    text="Сложная работа — выезд бригады", routed_role="brigade",
                    complexity="complex", brigade_id=brigade.id)
                if item["status"] != "new" and members:
                    item["assignee_id"] = rng.choice(members)
                requests.append(item)
    for chunk in range(0, len(requests), 2000):
        db.execute(insert(IncomingRequest), requests[chunk:chunk + 2000])
    db.flush()
    staffing_analysis.recalculate(db, year, ids)
    for school in db.scalars(select(StaffingSchedule).where(
            StaffingSchedule.organization_id.in_(ids), StaffingSchedule.academic_year == year)):
        payroll.snapshot(db, school, None, "import")
    if marker is None:
        db.add(AppSetting(key=FILL_KEY, value={"version": version}))
    else:
        marker.value = {"version": version}
    db.flush()
    log.info("Schools filled: %d staffing lines, %d requests", len(plan["cells"]), len(requests))
    return True


# --- выдача --------------------------------------------------------------------------


def _f(value) -> float | None:
    return None if value is None else float(value)


def dismissal_out(item: Dismissal) -> dict:
    return {
        "id": item.id, "organization_id": item.organization_id,
        "organization": item.organization.name, "full_name": item.full_name,
        "position": item.position, "fte": _f(item.fte), "basis": item.basis,
        "basis_title": BASIS_TITLES.get(item.basis, item.basis), "article": item.article,
        "order_number": item.order_number, "order_date": item.order_date,
        "dismissed_on": item.dismissed_on, "notified_on": item.notified_on,
        "note": item.note, "source": item.source,
        # Учтено ли в штатке: какая должность и на сколько стало меньше «занято»
        "applied_fte": _f(item.applied_fte),
        "applied_position": item.line.position if item.applied_fte is not None and item.line
        else None,
    }


def school_out(row: ProgramSchool, dismissed: list[dict]) -> dict:
    fte = sum(d["fte"] for d in dismissed)
    return {
        "organization_id": row.organization_id, "organization": row.organization.name,
        "total": _f(row.total), "vacancies": _f(row.vacancies),
        "load_reduction": _f(row.load_reduction), "resignations": _f(row.resignations),
        "layoffs": _f(row.layoffs), "dismissed_fte": _f(row.resignations + row.layoffs),
        "hours": row.hours, "staff_units": row.staff_units, "orders": row.orders_note,
        "dismissals": dismissed, "people": len(dismissed),
        # Ставки уволенных из приказов сходятся с расчётом управления?
        "matches": abs(fte - float(row.resignations + row.layoffs)) < 0.01,
    }


def overview(db: Session, org_ids: list[int] | None) -> dict:
    """Итог программы. org_ids — школы, которые видит пользователь (None — все)."""
    head = summary(db)
    rows = list(db.scalars(select(ProgramSchool).order_by(ProgramSchool.sort_order)))
    people = list(db.scalars(select(Dismissal).order_by(Dismissal.dismissed_on,
                                                        Dismissal.id)))
    by_org: dict[int, list[dict]] = {}
    for item in people:
        by_org.setdefault(item.organization_id, []).append(dismissal_out(item))
    schools = [school_out(r, by_org.get(r.organization_id, [])) for r in rows
               if org_ids is None or r.organization_id in org_ids]
    positions = list(db.scalars(select(ProgramPosition).order_by(ProgramPosition.sort_order)))
    return {
        "program": head, "schools": schools,
        "all_schools": len(rows),
        "dismissed_total": {
            "people": len(people), "fte": sum(_f(p.fte) for p in people),
            "own": sum(_f(p.fte) for p in people if p.basis == "own"),
            "layoff": sum(_f(p.fte) for p in people if p.basis == "layoff"),
        },
        "positions_cut": [{"name": p.name, "category": p.category, "cut": _f(p.cut_fte),
                           "before": _f(p.before_fte), "after": _f(p.after_fte)}
                          for p in positions if p.cut_fte][:8],
    }


def positions(db: Session) -> dict:
    rows = list(db.scalars(select(ProgramPosition).order_by(ProgramPosition.sort_order)))
    categories: dict[str, dict] = {}
    for p in rows:
        slot = categories.setdefault(p.category, {
            "category": p.category, "before": 0.0, "cut": 0.0, "after": 0.0,
            "economy_month": 0.0, "items": []})
        economy = float(p.local_economy_month or 0) + float(p.regional_economy_month or 0)
        slot["items"].append({
            "id": p.id, "name": p.name, "before": _f(p.before_fte), "cut": _f(p.cut_fte),
            "after": _f(p.after_fte), "local_cut": _f(p.local_cut),
            "local_economy_month": _f(p.local_economy_month),
            "regional_cut": _f(p.regional_cut),
            "regional_economy_month": _f(p.regional_economy_month),
            "economy_month": economy,
            "cut_pct": round(float(p.cut_fte) / float(p.before_fte) * 100, 1)
            if p.before_fte else None,
        })
        slot["before"] += float(p.before_fte)
        slot["cut"] += float(p.cut_fte)
        slot["after"] += float(p.after_fte)
        slot["economy_month"] += economy
    return {"program": summary(db), "categories": list(categories.values())}


def cleaning_norm(db: Session) -> dict:
    return app_settings.cleaning(db)
