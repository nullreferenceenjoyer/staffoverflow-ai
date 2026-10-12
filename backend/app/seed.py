"""Начальное наполнение базы.

    python -m app.seed              # справочники + демо-данные, если база пустая
    python -m app.seed --orgs 1000  # синтетика нужного объёма для нагрузочной проверки

Демо-учреждения и штатные расписания генерируются случайно с фиксированным зерном,
поэтому при каждом запуске получаются одни и те же цифры. Реальных данных здесь нет.
Названия муниципалитетов и паспорт проекта берутся из профиля в папке seed/.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.models import (
    Building,
    DigitalTool,
    Enrollment,
    IncomingRequest,
    KnowledgeDocument,
    Milestone,
    Municipality,
    Norm,
    Organization,
    Program,
    ProjectStatus,
    Role,
    StaffPosition,
    Task,
    TaskStatus,
    User,
    WorkflowTemplate,
)
from app.security import hash_password
from app.seed_data import DIGITAL_TOOLS, KNOWLEDGE, NORMS, WORKFLOW_TEMPLATES
from app.services import analytics, rag, routing, workflow
from app.services import projects as project_service
from app.services.functions import BY_CODE
from app.services.importer import pseudonymize
from app.services.staffing import NormRule, collect_metrics, evaluate_rule

log = logging.getLogger("seed")

DEMO_PASSWORD = "demo12345"
CURRENT_YEAR = 2026
HISTORY_YEARS = 4

KINDERGARTEN_NAMES = ["Солнышко", "Радуга", "Теремок", "Берёзка", "Сказка", "Ромашка",
                      "Золотой ключик", "Журавлик"]

# функция -> (типовые названия должностей, оклад за ставку, подразделение)
POSITIONS = {
    "teacher": (["Учитель"], 68000, "Учебная часть"),
    "educator": (["Воспитатель"], 56000, "Дошкольное отделение"),
    "psychologist": (["Педагог-психолог"], 52000, "Служба сопровождения"),
    "speech_therapist": (["Учитель-логопед"], 54000, "Служба сопровождения"),
    "defectologist": (["Учитель-дефектолог"], 54000, "Служба сопровождения"),
    "social_pedagogue": (["Социальный педагог"], 48000, "Служба сопровождения"),
    "librarian": (["Педагог-библиотекарь"], 45000, "Библиотека"),
    "additional_education": (["Педагог дополнительного образования"], 50000, "Учебная часть"),
    "director": (["Директор"], 135000, "Администрация"),
    "deputy_director": (["Заместитель директора по УВР", "Заместитель директора по ВР",
                         "Заместитель директора по безопасности"], 98000, "Администрация"),
    "accounting": (["Главный бухгалтер", "Бухгалтер", "Экономист"], 62000, "Бухгалтерия"),
    "hr": (["Специалист по кадрам"], 52000, "Администрация"),
    "procurement": (["Контрактный управляющий"], 58000, "Администрация"),
    "it": (["Системный администратор"], 60000, "Администрация"),
    "clerk": (["Секретарь руководителя", "Делопроизводитель"], 42000, "Администрация"),
    "facility_manager": (["Заведующий хозяйством"], 50000, "Хозяйственная служба"),
    "cleaning": (["Уборщик служебных помещений"], 31000, "Хозяйственная служба"),
    "security": (["Сторож", "Вахтёр"], 30000, "Хозяйственная служба"),
    "maintenance": (["Рабочий по комплексному обслуживанию зданий"], 36000,
                    "Хозяйственная служба"),
    "janitor": (["Дворник"], 30000, "Хозяйственная служба"),
    "cloakroom": (["Гардеробщик"], 28000, "Хозяйственная служба"),
    "lab_assistant": (["Лаборант"], 32000, "Учебная часть"),
    "assistant_educator": (["Помощник воспитателя"], 34000, "Дошкольное отделение"),
    "kitchen": (["Повар", "Кухонный рабочий"], 38000, "Пищеблок"),
    "nurse": (["Медицинская сестра"], 46000, "Медицинский кабинет"),
}
DUTIES = {
    "accounting": "Начисление заработной платы, ведение бухгалтерского учёта, отчётность, "
                  "расчёты с поставщиками.",
    "hr": "Ведение кадрового делопроизводства, оформление приёма и увольнения, табель, "
          "воинский учёт.",
    "procurement": "Планирование закупок, подготовка документации, работа в ЕИС, "
                   "ведение контрактов.",
    "clerk": "Регистрация входящих и исходящих документов, подготовка приказов, приём "
             "посетителей, табель.",
    "it": "Обслуживание компьютерной техники и сети, сопровождение электронного журнала.",
}
HOURS_PER_RATE = analytics.HOURS_PER_RATE
REQUESTS = [
    "Просим выделить дополнительную ставку учителя-логопеда: в этом году в первые классы "
    "пришло 14 детей с заключениями ПМПК.",
    "В карточке учреждения неверно указана площадь второго корпуса, просим исправить данные.",
    "На основании чего рассчитывается норматив по уборщикам служебных помещений?",
]


def ensure_reference_data(db: Session) -> None:
    """Справочники, без которых система не работает. Создаются один раз."""
    settings = get_settings()
    if db.scalar(select(func.count()).select_from(User)) == 0:
        db.add(User(email=settings.admin_email, full_name="Администратор",
                    password_hash=hash_password(settings.admin_password), role=Role.admin))
        log.info("Created admin user %s", settings.admin_email)

    documents: dict[str, KnowledgeDocument] = {}
    if db.scalar(select(func.count()).select_from(KnowledgeDocument)) == 0:
        for key, item in KNOWLEDGE.items():
            document = KnowledgeDocument(title=item["title"], source_ref=item["source_ref"],
                                         doc_type=item.get("doc_type", "npa"), is_summary=True)
            rag.index_document(db, document, item["text"])
            documents[key] = document
        db.flush()

    if db.scalar(select(func.count()).select_from(Norm)) == 0:
        for item in NORMS:
            data = dict(item)
            document = documents.get(data.pop("doc") or "")
            db.add(Norm(**data, document_id=document.id if document else None))

    if db.scalar(select(func.count()).select_from(WorkflowTemplate)) == 0:
        db.add_all(WorkflowTemplate(**template) for template in WORKFLOW_TEMPLATES)

    if db.scalar(select(func.count()).select_from(DigitalTool)) == 0:
        db.add_all(
            DigitalTool(function_code=code, name=name, description=description)
            for code, name, description in DIGITAL_TOOLS
        )
    db.commit()


class DemoGenerator:
    def __init__(self, db: Session, rules: list[NormRule], seed: int = 42):
        self.db = db
        self.rules = [r for r in rules if r.kind == "staff"]
        self.rng = random.Random(seed)
        self._employee = 0

    def _employee_ref(self) -> str | None:
        if self.rng.random() < 0.07:
            return None  # вакансия
        self._employee += 1
        return pseudonymize(f"Демонстрационный сотрудник {self._employee}")

    def organization(self, municipality: Municipality, index: int,
                     mostly_complexes: bool = False) -> Organization:
        rng = self.rng
        roll = rng.random()
        if mostly_complexes and rng.random() < 0.75:
            roll = 0.9  # в пилотном округе школы и сады объединены в комплексы
        if roll < 0.55:
            org_type, name = "school", f"СОШ № {index}"
            school, preschool = rng.randint(180, 1300), 0
        elif roll < 0.85:
            org_type = "preschool"
            name = f"Детский сад № {index} «{rng.choice(KINDERGARTEN_NAMES)}»"
            school, preschool = 0, rng.randint(70, 320)
        else:
            org_type, name = "complex", f"Образовательный комплекс № {index}"
            school, preschool = rng.randint(500, 1500), rng.randint(80, 240)

        org = Organization(municipality_id=municipality.id, org_type=org_type,
                           name=f"{name} ({municipality.name})",
                           external_id=f"OU-{municipality.id:03d}-{index:04d}")
        org.enrollments = self._enrollments(school, preschool)
        org.buildings = self._buildings(school + preschool, org_type)
        org.positions = self._positions(org)
        return org

    def _enrollments(self, school: int, preschool: int) -> list[Enrollment]:
        rng = self.rng
        trend = rng.uniform(-0.04, 0.05)  # годовое изменение контингента
        special_share = rng.uniform(0.01, 0.05)
        distance_share = rng.choice([0, 0, 0, 0.02, 0.04])
        rows = []
        for offset in range(HISTORY_YEARS):
            year = CURRENT_YEAR - HISTORY_YEARS + 1 + offset
            factor = (1 + trend) ** (offset - HISTORY_YEARS + 1) * rng.uniform(0.98, 1.02)
            levels = [("primary", 0.42, 26), ("basic", 0.47, 25), ("secondary", 0.11, 22)]
            for level, share, class_size in levels:
                students = round(school * share * factor)
                if not students:
                    continue
                distance = round(students * distance_share) if level != "primary" else 0
                rows.append(Enrollment(
                    academic_year=year, level=level, study_form="full_time",
                    students_count=students - distance,
                    classes_count=max(1, round(students / class_size)),
                    special_needs_count=round(students * special_share)))
                if distance:
                    rows.append(Enrollment(
                        academic_year=year, level=level, study_form="distance",
                        students_count=distance, classes_count=0, special_needs_count=0))
            if preschool:
                students = round(preschool * factor)
                rows.append(Enrollment(
                    academic_year=year, level="preschool", study_form="full_time",
                    students_count=students,
                    classes_count=max(1, round(students / 22)),
                    special_needs_count=round(students * special_share)))
        return rows

    def _buildings(self, students: int, org_type: str) -> list[Building]:
        rng = self.rng
        count = 1 if students < 600 else rng.choice([1, 2, 2, 3])
        area_total = students * rng.uniform(7.5, 11.0)
        names = ["Главный корпус", "Корпус начальной школы", "Дошкольное отделение"]
        if org_type == "preschool":
            names = ["Основное здание", "Корпус № 2", "Корпус № 3"]
        return [
            Building(name=names[i], area_sqm=Decimal(round(area_total / count, 1)),
                     floors=rng.choice([2, 3, 3, 4]) if org_type != "preschool" else 2,
                     year_built=rng.randint(1962, 2021),
                     condition=rng.choice(["good", "satisfactory", "satisfactory", "poor"]))
            for i in range(count)
        ]

    def _positions(self, org: Organization) -> list[StaffPosition]:
        """Штат строится от норматива с отклонениями, чтобы аналитике было что находить."""
        rng = self.rng
        metrics = collect_metrics(org.enrollments, org.buildings)
        small = metrics["students_total"] < 400

        need: dict[str, float] = {}
        for rule in self.rules:
            value = evaluate_rule(rule, org.org_type, metrics)
            if value:
                need[rule.function_code] = need.get(rule.function_code, 0.0) + value.value
        if org.org_type != "preschool" and rng.random() < 0.6:
            need["additional_education"] = rng.choice([1, 1.5, 2, 3])

        positions: list[StaffPosition] = []
        for code, norm in need.items():
            category = BY_CODE[code].category
            if code == "director":
                factor = 1.0
            elif category == "teaching":
                factor = rng.uniform(0.9, 1.12)
            elif small:
                # В малых ОУ обеспечивающие функции обычно раздуты: «свой» бухгалтер, кадровик
                factor = rng.uniform(1.0, 1.7)
            else:
                factor = rng.uniform(0.85, 1.3)
            total = max(round(norm * factor * 4) / 4, 0.25)
            positions += self._split(code, total, org.org_type)
        return positions

    def _split(self, code: str, total: float, org_type: str) -> list[StaffPosition]:
        rng = self.rng
        titles, salary, department = POSITIONS[code]
        if code == "director" and org_type == "preschool":
            titles = ["Заведующий"]
        function = BY_CODE[code]
        rows = []
        remaining = total
        while remaining > 0:
            rate = min(remaining, rng.choice([1, 1, 1, 0.5]) if remaining >= 1 else remaining)
            remaining = round(remaining - rate, 2)
            title = titles[0] if code == "director" else rng.choice(titles)
            hours = None
            if code in HOURS_PER_RATE:
                load = rng.uniform(0.95, 1.25) if rng.random() > 0.12 else rng.uniform(0.5, 0.75)
                hours = Decimal(round(HOURS_PER_RATE[code] * rate * load, 1))
            # Иногда бухгалтер или кадровик числится в другом подразделении —
            # это и есть дублирование функций внутри учреждения
            place = department
            if code in ("accounting", "hr", "clerk") and rng.random() < 0.12:
                place = "Дошкольное отделение" if org_type == "complex" else "Хозяйственная служба"
            rows.append(StaffPosition(
                department=place, title=title, category=function.category.value,
                function_code=code, rate=Decimal(str(rate)),
                monthly_pay=Decimal(round(salary * rate * rng.uniform(0.9, 1.2), -2)),
                employee_ref=self._employee_ref(), weekly_hours=hours, duties=DUTIES.get(code),
            ))
        return rows


def load_profile(path: str | Path | None = None) -> dict:
    """Демо-профиль: муниципалитеты, паспорт проекта, дорожная карта.

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
    rules = analytics.load_rules(db)
    generator = DemoGenerator(db, rules)

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
        db.add(generator.organization(municipality, index, mostly_complexes=pilot))
        if index % 100 == 0:
            db.flush()
            log.info("Generated %d organizations", index)
    db.flush()

    first_municipality = municipalities[0]
    # Демо-директору достаётся школа: на ней видны все разделы, включая надбавки
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

    # Один проект с запущенным сценарием, чтобы разделы «Проекты» и «Задачи» не были пустыми
    author = users[Role.municipal_specialist]
    reports = analytics.load_reports(
        db, list(db.scalars(select(Organization.id).where(
            Organization.municipality_id == first_municipality.id)))
    )
    report = next(r for r in reports if r.org_id == first_org.id)
    project = project_service.normalization_project(report, author, {})
    if project is not None:
        project.status = ProjectStatus.review
        db.add(project)
        db.flush()
        template = db.scalar(select(WorkflowTemplate).order_by(WorkflowTemplate.id))
        tasks = workflow.start_run(db, template, project, first_municipality.id,
                                   start=date.today() - timedelta(days=9))
        _complete_first_steps(db, tasks, count=2)

    # Ответственные в мероприятиях не заполняются: их вписывают в интерфейсе
    passport = profile["program"]
    program = Program(
        municipality_id=first_municipality.id,
        **{**passport, "start_date": date.fromisoformat(passport["start_date"]),
           "end_date": date.fromisoformat(passport["end_date"])},
    )
    program.milestones = [
        Milestone(ordinal=number, title=item["title"],
                  start_date=date.fromisoformat(item["start_date"]),
                  end_date=date.fromisoformat(item["end_date"]))
        for number, item in enumerate(profile["milestones"], start=1)
    ]
    db.add(program)

    for text in REQUESTS:
        topic = routing.classify_by_rules(text)
        db.add(IncomingRequest(organization_id=first_org.id, author_id=users[Role.director].id,
                               text=text, topic=topic, routed_role=routing.TOPICS[topic][1],
                               classified_by="rules"))
    db.commit()
    log.info("Demo data ready: %d organizations, demo password is %s", org_count, DEMO_PASSWORD)


def _complete_first_steps(db: Session, tasks: list[Task], count: int) -> None:
    for task in tasks[:count]:
        workflow.set_status(db, task, TaskStatus.done)
        db.flush()
    if len(tasks) > count:
        tasks[count].status = TaskStatus.in_progress


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
