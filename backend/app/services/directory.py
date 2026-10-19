"""Справочники администратора: учреждения и пользователи, их импорт из Excel и шаблоны."""

from __future__ import annotations

import re
import secrets
import string
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Brigade, Building, Municipality, Organization, OrgType, Role, User
from app.security import hash_password
from app.services.spreadsheet import Column, normalize, number

ORG_ROLES = (Role.director, Role.executor, Role.employee)

ROLE_TITLES = {
    Role.admin: "Администратор",
    Role.regional_analyst: "Региональный аналитик",
    Role.municipal_specialist: "Специалист управления образования",
    Role.director: "Директор ОУ",
    Role.observer: "Наблюдатель",
    Role.executor: "Хозяйственная служба на точке",
    Role.brigade: "Выездная бригада",
    Role.employee: "Сотрудник ОУ",
}
ROLE_ALIASES = {
    Role.admin: ("администратор", "админ"),
    Role.regional_analyst: ("региональный аналитик", "аналитик"),
    Role.municipal_specialist: ("специалист", "специалист управления образования",
                                "управление образования", "специалист уо"),
    Role.director: ("директор", "директор оу", "заведующий", "руководитель"),
    Role.observer: ("наблюдатель",),
    Role.executor: ("хозяйственная служба", "хозяйственная служба на точке", "хозслужба",
                    "хозяйственная служба оу", "сотрудник хозслужбы", "завхоз", "исполнитель",
                    "рабочий"),
    Role.brigade: ("бригада", "выездная бригада", "участник бригады", "бригадир"),
    Role.employee: ("сотрудник", "сотрудник оу", "работник", "педагог", "учитель"),
}
ORG_TYPE_ALIASES = {
    OrgType.school: ("школа", "сош", "оош", "гимназия", "лицей"),
    OrgType.preschool: ("детский сад", "доу", "сад", "дошкольное"),
    OrgType.complex: ("комплекс", "образовательный комплекс"),
}

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

ORG_COLUMNS = [
    Column("name", "Название", ("наименование", "учреждение", "наименование учреждения",
                                "организация", "полное наименование"), required=True,
           note="Название учреждения, как оно будет видно в заявках. Например: СОШ № 5"),
    Column("municipality", "Муниципалитет", ("округ", "район", "муниципальное образование",
                                             "муниципальный округ", "городской округ"),
           note="Округ или район. Если такого ещё нет, он будет создан. Можно не заполнять, "
                "если при загрузке выбран муниципалитет по умолчанию"),
    Column("org_type", "Тип", ("тип учреждения", "вид"),
           note="Школа, детский сад или комплекс. Пусто — определится по названию"),
    Column("address", "Адрес", ("адрес учреждения", "юридический адрес", "фактический адрес")),
    Column("latitude", "Широта", ("lat", "latitude"),
           note="Десятичные градусы, например 55,7512. Нужны, чтобы подсказать ближайшую бригаду"),
    Column("longitude", "Долгота", ("lon", "lng", "longitude"),
           note="Десятичные градусы, например 37,6184"),
    Column("buildings", "Корпуса", ("здания", "корпус"),
           note="Названия корпусов через точку с запятой: Главный корпус; Корпус № 2. "
                "Пусто — будет один корпус «Основное здание»"),
    Column("code", "Код", ("внешний код", "код учреждения", "external_id", "инн"),
           note="Код во внешней системе. По нему учреждение узнаётся при повторной загрузке, "
                "даже если название поменялось"),
]

USER_COLUMNS = [
    Column("full_name", "ФИО", ("фамилия имя отчество", "сотрудник", "пользователь"),
           required=True, note="Например: Иванова А. П."),
    Column("email", "E-mail", ("email", "почта", "электронная почта", "логин", "e-mail"),
           required=True, note="Логин для входа. Если пользователь с таким e-mail уже есть, "
                               "он будет обновлён"),
    Column("role", "Роль", ("должность в системе",), required=True,
           note="Сотрудник, Хозяйственная служба, Выездная бригада, Директор, Специалист, "
                "Аналитик, Наблюдатель, Администратор"),
    Column("organization", "Учреждение", ("организация", "школа", "код учреждения"),
           note="Название или код учреждения. Нужно сотруднику, хозяйственной службе и директору"),
    Column("municipality", "Муниципалитет", ("округ", "район"),
           note="Нужен специалисту управления образования. Остальным помогает найти учреждение, "
                "если названия совпадают в разных округах"),
    Column("brigade", "Бригада", ("название бригады",),
           note="Нужна участнику выездной бригады. Бригада заводится в разделе «Бригады»"),
    Column("password", "Пароль", ("пароль для входа",),
           note="От 8 символов. Пусто — новому пользователю пароль будет создан, "
                "его покажут после загрузки; у существующих пароль не меняется"),
]


@dataclass
class ImportResult:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[dict] = field(default_factory=list)
    created_municipalities: list[str] = field(default_factory=list)
    passwords: list[dict] = field(default_factory=list)

    def fail(self, row: int, message: str) -> None:
        self.skipped += 1
        self.errors.append({"row": row, "message": message})

    def as_dict(self) -> dict:
        return {
            "created": self.created, "updated": self.updated, "skipped": self.skipped,
            "errors": self.errors[:200], "created_municipalities": self.created_municipalities,
            "passwords": self.passwords,
        }


def parse_role(value: str) -> Role | None:
    key = normalize(value)
    for role in Role:
        if key == role.value or key == normalize(ROLE_TITLES[role]) or key in ROLE_ALIASES[role]:
            return role
    return None


def guess_org_type(value: str, name: str) -> OrgType:
    for text in (normalize(value), normalize(name)):
        for org_type, aliases in ORG_TYPE_ALIASES.items():
            if text == org_type.value or any(a in text for a in aliases):
                return org_type
    return OrgType.school


def generate_password() -> str:
    alphabet = string.ascii_letters + string.digits
    while True:
        password = "".join(secrets.choice(alphabet) for _ in range(10))
        if any(c.isdigit() for c in password) and any(c.isalpha() for c in password):
            return password


class Municipalities:
    """Муниципалитеты по названию; недостающие создаются по ходу импорта."""

    def __init__(self, db: Session, result: ImportResult | None = None):
        self.db = db
        self.result = result
        self.by_name = {normalize(m.name): m for m in db.scalars(select(Municipality))}

    def find(self, name: str) -> Municipality | None:
        return self.by_name.get(normalize(name))

    def get_or_create(self, name: str) -> Municipality:
        found = self.find(name)
        if found is not None:
            return found
        municipality = Municipality(name=" ".join(name.split()))
        self.db.add(municipality)
        self.db.flush()
        self.by_name[normalize(name)] = municipality
        if self.result is not None:
            self.result.created_municipalities.append(municipality.name)
        return municipality


def set_buildings(org: Organization, names: list[str]) -> None:
    """Добавляет корпуса, которых ещё нет. Существующие не удаляются: на них ссылаются заявки."""
    known = {normalize(b.name) for b in org.buildings}
    for name in names:
        if name and normalize(name) not in known:
            org.buildings.append(Building(name=name, address=org.address))
            known.add(normalize(name))
    if not org.buildings:
        org.buildings.append(Building(name="Основное здание", address=org.address))


def import_organizations(db: Session, rows: list[tuple[int, dict]],
                         default_municipality_name: str = "") -> ImportResult:
    """Учреждения из таблицы. Муниципалитет по умолчанию — для строк, где он не указан."""
    result = ImportResult()
    municipalities = Municipalities(db, result)
    default_municipality = (municipalities.get_or_create(default_municipality_name)
                            if normalize(default_municipality_name) else None)
    orgs = list(db.scalars(select(Organization).options(selectinload(Organization.buildings))))
    by_code = {o.external_id: o for o in orgs if o.external_id}
    by_name: dict[tuple[str, int], Organization] = {
        (normalize(o.name), o.municipality_id): o for o in orgs}

    for row, values in rows:
        name = " ".join(values.get("name", "").split())
        if len(name) < 2:
            result.fail(row, "Не заполнено название")
            continue
        try:
            latitude = number(values.get("latitude", ""))
            longitude = number(values.get("longitude", ""))
        except ValueError:
            result.fail(row, "Широта и долгота должны быть числами, например 55,7512")
            continue
        if (latitude is not None and not -90 <= latitude <= 90) or (
                longitude is not None and not -180 <= longitude <= 180):
            result.fail(row, "Координаты вне допустимого диапазона")
            continue

        municipality = None
        if values.get("municipality"):
            municipality = municipalities.get_or_create(values["municipality"])
        code = values.get("code") or None
        org = by_code.get(code) if code else None
        if org is None:
            target = municipality or default_municipality
            if target is not None:
                org = by_name.get((normalize(name), target.id))
            else:
                same = [o for (n, _), o in by_name.items() if n == normalize(name)]
                if len(same) == 1:
                    org = same[0]
                elif len(same) > 1:
                    result.fail(row, "Учреждений с таким названием несколько — "
                                     "укажите муниципалитет или код")
                    continue
        if org is None:
            municipality = municipality or default_municipality
            if municipality is None:
                result.fail(row, "Не указан муниципалитет: заполните колонку или выберите "
                                 "муниципалитет по умолчанию")
                continue
            if code and code in by_code:
                result.fail(row, f"Код {code} уже занят другим учреждением")
                continue
            org = Organization(name=name, municipality=municipality,
                               org_type=guess_org_type(values.get("org_type", ""), name),
                               address=values.get("address") or None, external_id=code,
                               latitude=latitude, longitude=longitude)
            org.buildings = []
            db.add(org)
            result.created += 1
        else:
            # Пустые ячейки не затирают то, что уже введено
            org.name = name
            if municipality is not None:
                org.municipality = municipality
            if values.get("org_type"):
                org.org_type = guess_org_type(values["org_type"], name)
            if values.get("address"):
                org.address = values["address"]
            if latitude is not None:
                org.latitude = latitude
            if longitude is not None:
                org.longitude = longitude
            if code and not org.external_id:
                org.external_id = code
            result.updated += 1
        buildings = [b.strip() for b in re.split(r"[;\n]", values.get("buildings", ""))]
        set_buildings(org, [b for b in buildings if b])
        db.flush()
        if org.external_id:
            by_code[org.external_id] = org
        by_name[(normalize(org.name), org.municipality_id)] = org
    return result


def import_users(db: Session, rows: list[tuple[int, dict]], actor: User) -> ImportResult:
    result = ImportResult()
    municipalities = Municipalities(db)
    orgs = list(db.scalars(select(Organization)))
    brigades = {normalize(b.name): b for b in db.scalars(select(Brigade))}
    users = {u.email.lower(): u for u in db.scalars(select(User))}

    def find_org(value: str, municipality: Municipality | None) -> Organization | str:
        exact = [o for o in orgs if o.external_id and o.external_id == value.strip()]
        if exact:
            return exact[0]
        same = [o for o in orgs if normalize(o.name) == normalize(value)
                and (municipality is None or o.municipality_id == municipality.id)]
        if not same:
            return f"Учреждение «{value}» не найдено"
        if len(same) > 1:
            return f"Учреждений «{value}» несколько — укажите муниципалитет"
        return same[0]

    for row, values in rows:
        full_name = " ".join(values.get("full_name", "").split())
        email = values.get("email", "").strip().lower()
        if len(full_name) < 2:
            result.fail(row, "Не заполнено ФИО")
            continue
        if not EMAIL.match(email):
            result.fail(row, f"Некорректный e-mail «{values.get('email', '')}»")
            continue
        role = parse_role(values.get("role", ""))
        if role is None:
            result.fail(row, f"Неизвестная роль «{values.get('role', '')}»")
            continue
        password = values.get("password", "")
        if password and len(password) < 8:
            result.fail(row, "Пароль короче 8 символов")
            continue

        municipality = None
        if values.get("municipality"):
            municipality = municipalities.find(values["municipality"])
            if municipality is None:
                result.fail(row, f"Муниципалитет «{values['municipality']}» не найден")
                continue
        organization = None
        if role in ORG_ROLES:
            if not values.get("organization"):
                result.fail(row, "Для этой роли нужно указать учреждение")
                continue
            found = find_org(values["organization"], municipality)
            if isinstance(found, str):
                result.fail(row, found)
                continue
            organization = found
        brigade = None
        if role == Role.brigade:
            brigade = brigades.get(normalize(values.get("brigade", "")))
            if brigade is None:
                result.fail(row, "Для участника бригады укажите существующую бригаду")
                continue
        if role == Role.municipal_specialist and municipality is None:
            result.fail(row, "Специалисту нужно указать муниципалитет")
            continue

        user = users.get(email)
        if user is not None and user.id == actor.id:
            result.fail(row, "Свою учётную запись через импорт не меняют")
            continue
        if user is None:
            user = User(email=email, full_name=full_name, role=role, is_active=True)
            if not password:
                password = generate_password()
                result.passwords.append({"email": email, "full_name": full_name,
                                         "password": password})
            user.password_hash = hash_password(password)
            db.add(user)
            users[email] = user
            result.created += 1
        else:
            user.full_name = full_name
            user.role = role
            if password:
                user.password_hash = hash_password(password)
            result.updated += 1
        user.organization_id = organization.id if organization else None
        user.municipality_id = (municipality.id if role == Role.municipal_specialist
                                and municipality else None)
        user.brigade_id = brigade.id if brigade else None
        db.flush()
    return result


ORG_EXAMPLES = [
    ["СОШ № 5", "Северный м.о.", "Школа", "г. Северный, ул. Школьная, д. 5", "55,7512",
     "37,6184", "Главный корпус; Корпус начальной школы", "OU-005"],
    ["Детский сад № 12 «Солнышко»", "Северный м.о.", "Детский сад",
     "г. Северный, ул. Садовая, д. 12", "", "", "", ""],
]
USER_EXAMPLES = [
    ["Иванова А. П.", "ivanova@school5.ru", "Сотрудник", "СОШ № 5", "Северный м.о.", "", ""],
    ["Петров С. В.", "petrov@school5.ru", "Хозяйственная служба", "СОШ № 5", "", "", ""],
    ["Сидоров К. Л.", "sidorov@brigada.ru", "Выездная бригада", "", "", "Бригада № 1",
     "Brigada2026"],
    ["Кузнецова Е. М.", "kuznetsova@uo.ru", "Специалист", "", "Северный м.о.", "", ""],
]
ORG_HELP = [
    "Повторная загрузка того же файла не создаёт дублей: учреждение узнаётся по коду, "
    "а без кода — по названию в пределах муниципалитета.",
    "Пустые ячейки не затирают уже введённые данные.",
]
USER_HELP = [
    "Пользователь узнаётся по e-mail: повторная загрузка обновит ФИО, роль и привязку.",
    "Пароли, созданные системой, показываются один раз — сразу после загрузки.",
]
