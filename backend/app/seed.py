"""Начальное наполнение базы.

    python -m app.seed              # администратор + демо-данные, если база пустая
    python -m app.seed --orgs 1000  # синтетика нужного объёма для нагрузочной проверки

Демо-учреждения, корпуса, бригады и заявки генерируются случайно с фиксированным зерном,
поэтому при каждом запуске получается одно и то же. Реальных данных здесь нет.
Названия муниципалитетов берутся из профиля в папке seed/.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.models import (
    Brigade,
    Building,
    Complexity,
    Municipality,
    Organization,
    RequestStatus,
    Role,
    User,
)
from app.security import hash_password
from app.services import helpdesk

log = logging.getLogger("seed")

DEMO_PASSWORD = "demo12345"

KINDERGARTEN_NAMES = ["Солнышко", "Радуга", "Теремок", "Берёзка", "Сказка", "Ромашка",
                      "Золотой ключик", "Журавлик"]
STREETS = ["Школьная", "Садовая", "Центральная", "Молодёжная", "Лесная", "Советская",
           "Новая", "Первомайская", "Заводская", "Спортивная", "Парковая", "Мира"]

# (заголовок, подробности, тема, срочность)
REQUESTS = [
    ("Заменить трубы отопления в спортзале", "Две секции не греют, трубы проржавели.",
     "plumbing", "planned"),
    ("Покрасить стены во всех кабинетах второго этажа", "Перед началом учебного года.",
     "repair", "planned"),
    ("Заменить проводку в кабинете информатики", "Розетки греются, автомат выбивает.",
     "electrical", "urgent"),
    ("Положить линолеум в рекреации", "Покрытие протёрлось, около 60 м2.", "repair", "planned"),
    ("Починить парту в кабинете 12", "Сломалась ножка у парты в третьем ряду, качается.",
     "furniture", "planned"),
    ("Отремонтировать дверцу шкафа", "В учительской отвалилась дверца книжного шкафа.",
     "furniture", "planned"),
    ("Заменить два стула в кабинете 21", "Треснули сиденья, пользоваться нельзя.",
     "furniture", "planned"),
    ("Собрать новые шкафчики в раздевалке", "Привезли шесть шкафчиков, лежат в коробках.",
     "furniture", "planned"),
    ("Течёт кран в туалете на втором этаже", "Вода капает постоянно, раковина не перекрывается.",
     "plumbing", "urgent"),
    ("Прорвало трубу в подвале", "Вода идёт на пол рядом с электрощитовой.",
     "plumbing", "emergency"),
    ("Холодные батареи в спортзале", "После запуска отопления две секции не греют.",
     "plumbing", "urgent"),
    ("Не горят лампы в коридоре", "На первом этаже у столовой перегорели четыре светильника.",
     "electrical", "planned"),
    ("Искрит розетка в кабинете информатики", "Розетка у окна искрит при включении.",
     "electrical", "emergency"),
    ("Заменить выключатель в кабинете 7", "Выключатель западает, свет включается через раз.",
     "electrical", "planned"),
    ("Покрасить стену в раздевалке", "После протечки осталось пятно, нужна покраска.",
     "repair", "planned"),
    ("Заменить разбитое стекло", "Трещина в окне лестничного пролёта между 2 и 3 этажом.",
     "repair", "urgent"),
    ("Не закрывается замок в кабинете 15", "Ключ проворачивается, кабинет не запирается.",
     "repair", "planned"),
    ("Убрать снег у запасного выхода", "Запасный выход со стороны двора завален снегом.",
     "cleaning", "urgent"),
    ("Вывезти мусор после субботника", "У хозяйственного блока лежат мешки с листвой.",
     "cleaning", "planned"),
    ("Не печатает принтер в учительской", "Принтер захватывает бумагу и останавливается.",
     "it", "planned"),
    ("Нет интернета в кабинете 30", "С утра не открывается электронный журнал.",
     "it", "urgent"),
    ("Настроить проектор в актовом зале", "Изображение смещено, нужна настройка к пятнице.",
     "it", "planned"),
    ("Закупить бумагу и картриджи", "Запас бумаги на неделю, картриджи закончились.",
     "supplies", "planned"),
    ("Закончились моющие средства", "На пищеблоке осталось на два дня.", "supplies", "planned"),
    ("Не работает турникет на входе", "Турникет не считывает пропуска с утра.",
     "safety", "urgent"),
    ("Проверить огнетушители на третьем этаже", "Истекает срок перезарядки.",
     "safety", "planned"),
    ("Нужна дополнительная ставка учителя-логопеда",
     "В этом году в первые классы пришло 14 детей с заключениями ПМПК.",
     "staff_increase", "planned"),
    ("Неверно указана площадь второго корпуса", "Просим исправить данные в карточке учреждения.",
     "data_fix", "planned"),
    ("На основании чего считается норматив по уборщикам?",
     "Прошу пояснить, откуда взята норма 600 м² на ставку.", "norms", "planned"),
]
RESOLUTIONS = {
    "furniture": "Отремонтировано, можно пользоваться.",
    "plumbing": "Неисправность устранена, течи нет.",
    "electrical": "Заменено, проверено под нагрузкой.",
    "repair": "Работы выполнены.",
    "cleaning": "Убрано.",
    "it": "Настроено, работает.",
    "supplies": "Выдано со склада, остальное включено в заявку на закупку.",
    "safety": "Проверено, замечаний нет.",
}


def ensure_reference_data(db: Session) -> None:
    """Без администратора в систему не войти. Создаётся один раз."""
    settings = get_settings()
    if db.scalar(select(func.count()).select_from(User)) == 0:
        db.add(User(email=settings.admin_email, full_name="Администратор",
                    password_hash=hash_password(settings.admin_password), role=Role.admin))
        log.info("Created admin user %s", settings.admin_email)
    db.commit()


def center(municipality: Municipality) -> tuple[float, float]:
    """Условная точка муниципалитета на карте области."""
    return (55.2 + (municipality.id * 37 % 100) / 100 * 1.4,
            36.6 + (municipality.id * 53 % 100) / 100 * 2.2)


def demo_organization(rng: random.Random, municipality: Municipality, index: int,
                      mostly_complexes: bool = False) -> Organization:
    roll = rng.random()
    if mostly_complexes and rng.random() < 0.75:
        roll = 0.9  # в пилотном округе школы и сады объединены в комплексы
    if roll < 0.55:
        org_type, name = "school", f"СОШ № {index}"
        names = ["Главный корпус", "Корпус начальной школы", "Спортивный корпус"]
    elif roll < 0.85:
        org_type = "preschool"
        name = f"Детский сад № {index} «{rng.choice(KINDERGARTEN_NAMES)}»"
        names = ["Основное здание", "Корпус № 2", "Корпус № 3"]
    else:
        org_type, name = "complex", f"Образовательный комплекс № {index}"
        names = ["Главный корпус", "Корпус начальной школы", "Дошкольное отделение"]

    street, house = rng.choice(STREETS), rng.randint(1, 60)
    address = f"{municipality.name}, ул. {street}, д. {house}"
    count = rng.choice([1, 1, 2, 2, 3])
    buildings = [
        Building(name=names[i], address=address if i == 0 else f"{address}, корп. {i + 1}")
        for i in range(count)
    ]
    # Учреждения разбросаны в радиусе 10–12 км от центра округа
    lat, lon = center(municipality)
    return Organization(municipality_id=municipality.id, org_type=org_type,
                        name=f"{name} ({municipality.name})", address=address,
                        external_id=f"OU-{municipality.id:03d}-{index:04d}",
                        latitude=round(lat + rng.uniform(-0.1, 0.1), 6),
                        longitude=round(lon + rng.uniform(-0.17, 0.17), 6),
                        buildings=buildings)


def seed_brigades(db: Session, municipalities: list[Municipality], password_hash: str) -> None:
    """Две общие бригады в пилотном округе — северная и южная, школы закреплены за
    ближайшей; бригада электриков на весь округ; по одной бригаде в остальных."""
    pilot = municipalities[0]
    lat, lon = center(pilot)
    north = Brigade(name="Бригада «Север»", municipality=pilot, latitude=round(lat + 0.06, 6),
                    longitude=lon, base_address=f"{pilot.name}, ул. Заводская, д. 3", topics=[])
    south = Brigade(name="Бригада «Юг»", municipality=pilot, latitude=round(lat - 0.06, 6),
                    longitude=lon, base_address=f"{pilot.name}, ул. Лесная, д. 18", topics=[])
    electric = Brigade(name="Электрики округа", municipality=pilot, latitude=lat, longitude=lon,
                       base_address=f"{pilot.name}, ул. Центральная, д. 1",
                       topics=["electrical", "it"])
    brigades = [north, south, electric]
    for municipality in municipalities[1:]:
        m_lat, m_lon = center(municipality)
        brigades.append(Brigade(name=f"Выездная бригада ({municipality.name})",
                                municipality=municipality, latitude=m_lat, longitude=m_lon,
                                topics=[]))
    db.add_all(brigades)
    db.flush()

    orgs = list(db.scalars(select(Organization)))
    for org in orgs:
        if org.municipality_id == pilot.id:
            nearest = north if float(org.latitude) >= lat else south
            nearest.organizations.append(org)
            electric.organizations.append(org)
        else:
            local = next(b for b in brigades[3:] if b.municipality_id == org.municipality_id)
            local.organizations.append(org)

    people = [(north, "Ковалёв И. Д."), (north, "Жуков А. С."), (south, "Носов П. Е."),
              (south, "Егоров В. М."), (electric, "Лапин С. Г.")]
    people += [(b, f"Монтажник {i} (бригада округа)") for i, b in enumerate(brigades[3:], 1)]
    for number, (brigade, name) in enumerate(people, start=1):
        db.add(User(email=f"brigade{number}@demo.ru", full_name=name, role=Role.brigade,
                    brigade=brigade, password_hash=password_hash))
    db.flush()


def load_profile(path: str | Path | None = None) -> dict:
    """Демо-профиль: названия муниципалитетов.

    Без явного пути берётся seed/local.json, если он есть, иначе seed/demo.json.
    """
    settings = get_settings()
    path = path or settings.seed_file
    if not path:
        folder = Path(settings.seed_dir)
        local = folder / "local.json"
        path = local if local.exists() else folder / "demo.json"
    log.info("Demo profile: %s", path)
    return json.loads(Path(path).read_text(encoding="utf-8"))


def seed_demo(db: Session, org_count: int, profile: dict | None = None) -> None:
    profile = profile or load_profile()
    rng = random.Random(42)

    names = profile["municipalities"]
    municipality_count = min(len(names), max(4, org_count // 6))
    municipalities = [Municipality(name=name) for name in names[:municipality_count]]
    db.add_all(municipalities)
    db.flush()

    for index in range(1, org_count + 1):
        # Половина учреждений — в пилотном округе, остальные поровну между прочими
        pilot = index % 2 == 1
        others = municipalities[1:]
        municipality = municipalities[0] if pilot else others[(index // 2 - 1) % len(others)]
        db.add(demo_organization(rng, municipality, index, mostly_complexes=pilot))
        if index % 100 == 0:
            db.flush()
            log.info("Generated %d organizations", index)
    db.flush()

    first_municipality = municipalities[0]
    # Демо-директору достаётся школа
    first_org = db.scalar(
        select(Organization)
        .where(Organization.municipality_id == first_municipality.id)
        .order_by((Organization.org_type != "school"), Organization.id)
    )
    password_hash = hash_password(DEMO_PASSWORD)
    users = {
        Role.regional_analyst: User(email="analyst@demo.ru", full_name="Соколова А. В.",
                                    role=Role.regional_analyst),
        Role.municipal_specialist: User(email="municipal@demo.ru",
                                        full_name="Кузнецов Д. С.",
                                        role=Role.municipal_specialist,
                                        municipality_id=first_municipality.id),
        Role.director: User(email="director@demo.ru", full_name="Морозова Е. Н.",
                            role=Role.director, organization_id=first_org.id),
        Role.observer: User(email="observer@demo.ru", full_name="Орлов П. А.",
                            role=Role.observer),
    }
    for user in users.values():
        user.password_hash = password_hash
    db.add_all(users.values())
    db.flush()
    seed_brigades(db, municipalities, password_hash)

    pilot_orgs = db.scalars(
        select(Organization)
        .where(Organization.municipality_id == first_municipality.id)
        .order_by((Organization.id != first_org.id), Organization.id)
    ).all()
    seed_requests(db, rng, pilot_orgs, users, password_hash)
    db.commit()
    log.info("Demo data ready: %d organizations, demo password is %s", org_count, DEMO_PASSWORD)


def seed_requests(db: Session, rng: random.Random, organizations: list[Organization],
                  users: dict[Role, User], password_hash: str) -> None:
    """Заявки за последний месяц в разных статусах, чтобы дашборд и доска не были пустыми."""
    first_org = organizations[0]
    employee = User(email="employee@demo.ru", full_name="Лебедева О. И.", role=Role.employee,
                    organization_id=first_org.id, password_hash=password_hash)
    names = ["Гришин В. П.", "Тарасов Н. А.", "Белова И. С.", "Фомин Г. Р."]
    for number, (org, name) in enumerate(zip(organizations, names, strict=False), start=1):
        email = "executor@demo.ru" if number == 1 else f"executor{number}@demo.ru"
        db.add(User(email=email, full_name=name, role=Role.executor, organization_id=org.id,
                    password_hash=password_hash))
    db.add(employee)
    db.flush()

    S = RequestStatus
    outcomes = [S.closed] * 9 + [S.done] * 2 + [S.in_progress] * 4 + [S.assigned] * 3 + [
        S.on_hold, S.rejected]
    moment = datetime.now(UTC)
    for index in range(46):
        title, text, topic, kind = REQUESTS[index % len(REQUESTS)]
        # Половина заявок — в учреждении демо-директора, остальные по соседям
        org = first_org if index % 2 == 0 else rng.choice(organizations[1:6] or organizations)
        author = users[Role.municipal_specialist]
        if org.id == first_org.id:
            author = employee if index % 4 else users[Role.director]
        outcome = rng.choice(outcomes)
        # Незакрытые заявки — свежие, иначе полдоски окажется просроченной
        age = 27 * 24 if outcome in (S.closed, S.rejected) else 6 * 24
        created = moment - timedelta(hours=rng.uniform(3, age))
        request = helpdesk.create(
            db, author, org, title=title, text=text, kind=kind, topic=topic,
            building=rng.choice(org.buildings), location=None, created_at=created,
        )
        request.classified_by = "rules"
        # Заявку бригады берёт первый её участник
        worker = request.assignee or (request.brigade.members[0]
                                      if request.brigade and request.brigade.members else None)
        if worker is None or outcome == S.assigned:
            continue

        limit = (moment - created).total_seconds() / 3600
        allowed = (request.due_at - created).total_seconds() / 3600
        # Примерно каждая пятая заявка выполняется с опозданием
        spent = allowed * (rng.uniform(1.1, 1.8) if rng.random() < 0.2 else rng.uniform(0.2, 0.9))
        spent = min(spent, limit * 0.9)
        started = created + timedelta(hours=min(rng.uniform(0.5, 20), spent * 0.4))
        finished = created + timedelta(hours=spent)
        if outcome == S.rejected:
            helpdesk.change_status(db, request, worker, S.rejected,
                                   "Дубль: такая заявка уже в работе.", at=started)
            continue
        helpdesk.change_status(db, request, worker, S.in_progress, at=started)
        if outcome == S.on_hold:
            helpdesk.change_status(db, request, worker, S.on_hold,
                                   "Уточните, пожалуйста, номер кабинета.", at=finished)
        elif outcome in (S.done, S.closed):
            helpdesk.change_status(db, request, worker, S.done,
                                   RESOLUTIONS.get(topic, "Вопрос решён."), at=finished)
            if outcome == S.closed:
                confirmed = finished + timedelta(hours=rng.uniform(1, 30))
                helpdesk.change_status(db, request, author, S.closed,
                                       at=min(confirmed, moment))

    # Одна крупная работа разбита на этапы, чтобы было видно, как это выглядит
    major = db.scalar(select(helpdesk.IncomingRequest).where(
        helpdesk.IncomingRequest.complexity == Complexity.major,
        helpdesk.IncomingRequest.status.in_(helpdesk.ACTIVE),
        helpdesk.IncomingRequest.parent_id.is_(None)).order_by(helpdesk.IncomingRequest.id))
    if major is not None:
        helpdesk.split(db, major, users[Role.municipal_specialist], [
            ("Подготовить стены: снять старую краску, зашпаклевать", 8),
            ("Покрасить кабинеты с 21 по 25", 6),
            ("Покрасить кабинеты с 26 по 30", 6),
        ])


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--orgs", type=int, default=36, help="сколько учреждений сгенерировать")
    args = parser.parse_args()

    with SessionLocal() as db:
        ensure_reference_data(db)
        if not get_settings().seed_demo_data:
            return
        if db.scalar(select(func.count()).select_from(Organization)):
            log.info("Organizations already exist, demo data skipped")
            return
        seed_demo(db, args.orgs)


if __name__ == "__main__":
    main()
