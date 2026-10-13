"""ИИ-помощник: отвечает на вопросы только по данным системы.

Источников у помощника два: таблицы базы данных и документы, загруженные в базу
знаний. Ничего другого модель не видит и ссылаться ей больше не на что:

  1. Вопрос разбирает обычный код (retrieval.py): по словам в нём выбираются выборки
     из базы и фрагменты документов. Они сразу уходят пользователю готовыми блоками
     с указанием источника.
  2. Модель получает те же блоки и пишет к ним короткий вывод. Инструментов у неё
     нет, в сеть она не ходит.
  3. Если под вопрос ничего не нашлось, модель не вызывается вовсе — пользователь
     получает прямой ответ, что таких данных в системе нет.
  4. Готовый ответ проверяется: если в нём упомянут приказ, закон или ссылка,
     которых не было в переданных данных, пользователь видит предупреждение.

Заодно это быстро: локальная модель на процессоре выдаёт 5–10 токенов в секунду,
и гонять её по кругу «вызови инструмент — прочитай» было бы слишком долго.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import Scope
from app.models import Municipality, Project, Task, TaskStatus
from app.services import analytics, centralization, helpdesk, llm, rag
from app.services.staffing import DRIVERS, OrgReport

log = logging.getLogger(__name__)

HISTORY_MESSAGES = 4
# Вывод к таблицам, а не пересказ: при 6 токенах в секунду это около минуты
ANSWER_MAX_TOKENS = 380

SYSTEM_PROMPT = """Ты — аналитик системы оптимизации штатных расписаний образовательных \
учреждений. Отвечаешь руководителям и специалистам управления образования.

В сообщении пользователя перед вопросом идёт блок «Данные системы»: выборки из базы данных \
и фрагменты документов из базы знаний. Это единственный источник, которым тебе разрешено \
пользоваться.

Правила:
- Используй только то, что написано в блоке «Данные системы». Собственные знания о законах, \
приказах, нормах, практике других регионов и любые сведения из интернета использовать нельзя.
- Не называй нормативные акты, документы, сайты и организации, которых нет в блоке. Номер \
и название документа можно привести, только если они дословно есть в блоке.
- Если данных для ответа в блоке нет или их не хватает — так и скажи: «В данных системы \
этого нет». Не достраивай ответ предположениями.
- Таблицы из блока пользователь уже видит над твоим ответом. Не переписывай их. Дай вывод: \
прямой ответ на вопрос с главными числами и названиями, затем что с этим можно сделать. \
Объём — 3–6 предложений или короткий список.
- Ставки — это штатные единицы, а не люди. Данные обезличены, ФИО в системе нет. На вопросы \
вида «кого уволить» объясняй, по каким функциям и на каких площадках персонал недозагружен \
и какие есть варианты (вакансии, перераспределение, объединение); кадровое решение остаётся \
за руководителем.
- «Избыток» — превышение факта над расчётным нормативом, «нехватка» — наоборот. «Загрузка» — \
объём работы, делённый на занятые ставки.
- Не складывай и не пересчитывай числа сам: итоги уже посчитаны — они в первой строке \
блока и в строке «Итого». Бери готовые.
- Отвечай по-русски. Числа приводи с единицами: ставки, ₽, %."""

NO_DATA = (
    "В базе системы и в загруженных документах нет данных для ответа на этот вопрос. "
    "Я отвечаю только по ним: штатные расписания и нормативы, загрузка персонала по "
    "площадкам, централизация, заявки, проекты и задачи, паспорт проекта, документы из "
    "базы знаний. Если нужного документа нет, его можно загрузить в разделе «База знаний»."
)

ROLE_TITLES = {
    "admin": "администратор системы",
    "regional_analyst": "региональный аналитик",
    "municipal_specialist": "специалист управления образования",
    "director": "директор ОУ",
    "observer": "наблюдатель",
}

# Упоминания внешних источников в ответе модели: реквизиты документов и ссылки
_DOCUMENT = re.compile(
    r"(?:приказ|постановлени|распоряжени|закон|письм|решени|указ)[а-я]*[^.\n№]{0,70}"
    r"№\s*([0-9][\w\-/.]*)", re.I)
_NAMED_ACT = re.compile(
    r"санпин[\s\d.\-/]*|гост\s*р?\s*[\d.\-]+|снип[\s\d.\-]*|трудов\w+ кодекс\w*|\bтк рф\b"
    r"|бюджетн\w+ кодекс\w*|\d+-фз\b|профстандарт\w*|единый квалификационный справочник"
    r"|\bекс\b", re.I)
_URL = re.compile(r"https?://\S+|\bwww\.\S+", re.I)


def foreign_references(answer: str, context: str) -> list[str]:
    """Ищет в ответе ссылки на источники, которых не было в переданных модели данных."""
    known = normalize(context)
    found = [m.group(0) for m in _URL.finditer(answer)]
    for match in _DOCUMENT.finditer(answer):
        number = match.group(1).rstrip(".,;)").lower()
        if f"№ {number}" not in known and f"№{number}" not in known:
            found.append(match.group(0).strip())
    for match in _NAMED_ACT.finditer(answer):
        name = " ".join(normalize(match.group(0)).split())
        # Сравниваем по началу названия: «трудового кодекса» и «трудовой кодекс» — одно и то же
        if name[:6] not in known:
            found.append(match.group(0).strip())
    return list(dict.fromkeys(found))


def normalize(text: str) -> str:
    return text.lower().replace("ё", "е")


class Toolbox:
    """Чтение данных в пределах области видимости пользователя."""

    def __init__(self, db: Session, scope: Scope):
        self.db = db
        self.scope = scope
        self._reports: list[OrgReport] | None = None

    @property
    def reports(self) -> list[OrgReport]:
        if self._reports is None:
            self._reports = analytics.load_reports(self.db, self.scope.org_ids())
        return self._reports

    def select(self, municipality: str | None) -> list[OrgReport]:
        if not municipality:
            return self.reports
        needle = normalize(municipality)
        exact = [r for r in self.reports if normalize(r.municipality) == needle]
        if exact:
            return exact
        # Модель часто пишет «район» вместо «г.о.» или «м.о.» — сравниваем по основе слова
        word = max(needle.replace(".", " ").split(), key=len)
        stem = word[: min(6, max(4, len(word) - 2))]
        return [r for r in self.reports if stem in normalize(r.municipality)]

    def overview(self, municipality: str | None = None) -> dict:
        return analytics.summarize(self.select(municipality))

    def organizations(self, municipality: str | None = None, search: str | None = None,
                      category: str | None = None, sort: str = "surplus",
                      limit: int = 10) -> dict:
        reports = self.select(municipality)
        if search:
            reports = [r for r in reports if normalize(search) in normalize(r.name)]

        rows = []
        for r in reports:
            row = {"id": r.org_id, "name": r.name, "municipality": r.municipality,
                   "students": int(r.metrics["students_total"])}
            if category in r.by_category():
                # Запрошена одна категория — отдаём цифры только по ней,
                # иначе модель подставляет общий избыток вместо избытка АУП
                row |= {"category": category, **r.by_category()[category]}
            else:
                row |= {"actual": r.actual_total, "norm": r.norm_total, "surplus": r.surplus,
                        "shortage": r.shortage}
            row |= {"compliance_pct": r.compliance,
                    "saving_potential_year_rub": r.saving_potential_year}
            rows.append(row)

        keys = {
            "surplus": lambda row: -row["surplus"],
            "shortage": lambda row: -row["shortage"],
            "compliance": lambda row: row["compliance_pct"],
            "saving": lambda row: -row["saving_potential_year_rub"],
        }
        rows.sort(key=keys.get(sort, keys["surplus"]))
        limit = max(1, min(int(limit or 10), 25))
        return {"total": len(rows), "organizations": rows[:limit]}

    def find_organizations(self, organization: str) -> list[OrgReport]:
        needle = normalize(organization)
        matches = [r for r in self.reports if needle in normalize(r.name)]
        exact = [r for r in matches if normalize(r.name) == needle]
        return exact or matches

    def organization_report(self, organization: str) -> dict:
        matches = self.find_organizations(organization)
        if not matches:
            return {"error": f"Учреждение «{organization}» не найдено среди доступных"}
        if len(matches) > 1:
            return {"error": "Найдено несколько учреждений, уточните название",
                    "candidates": [r.name for r in matches[:10]]}
        return self.report_details(matches[0])

    @staticmethod
    def report_details(report: OrgReport) -> dict:
        return {
            "id": report.org_id,
            "name": report.name,
            "municipality": report.municipality,
            "metrics": {DRIVERS[k]: v for k, v in report.metrics.items()
                        if v and k != "organization"},
            "actual": report.actual_total,
            "norm": report.norm_total,
            "surplus": report.surplus,
            "shortage": report.shortage,
            "compliance_pct": report.compliance,
            "fot_year_rub": report.fot_actual_year,
            "saving_potential_year_rub": report.saving_potential_year,
            "functions": [
                {"title": line.title, "category": line.category, "actual": line.actual_rate,
                 "norm": line.norm_rate, "delta": line.delta, "vacant": line.vacant_rate,
                 "formula": "; ".join(line.explanations)}
                for line in report.lines
            ],
        }

    def deviations(self, category: str | None = None, municipality: str | None = None,
                   limit: int = 10) -> dict:
        limit = max(1, min(int(limit or 10), 25))
        rows = analytics.top_deviations(self.select(municipality), category, limit)
        return {"deviations": rows}

    def centralization(self, municipality: str | None = None) -> dict:
        scenario = centralization.build_scenario(self.select(municipality))
        for function in scenario["functions"]:
            function.pop("members")
        return scenario

    def vacancies(self, municipality: str | None = None, category: str | None = None) -> dict:
        """Вакантные ставки по функциям: их можно сократить, никого не увольняя."""
        totals: dict[str, dict] = {}
        for report in self.select(municipality):
            for line in report.lines:
                if not line.vacant_rate or (category and line.category != category):
                    continue
                item = totals.setdefault(line.title, {
                    "title": line.title, "category": line.category, "vacant": 0.0,
                    "of_them_above_norm": 0.0, "organizations": 0})
                item["vacant"] += line.vacant_rate
                item["of_them_above_norm"] += max(min(line.vacant_rate, line.delta), 0)
                item["organizations"] += 1
        rows = sorted(totals.values(), key=lambda item: -item["vacant"])
        for row in rows:
            row["vacant"] = round(row["vacant"], 2)
            row["of_them_above_norm"] = round(row["of_them_above_norm"], 2)
        return {
            "vacancies": rows,
            "total": round(sum(r["vacant"] for r in rows), 2),
            "above_norm": round(sum(r["of_them_above_norm"] for r in rows), 2),
        }

    def workload(self, municipality: str | None = None) -> dict:
        org_ids = self.scope.org_ids()
        if municipality:
            org_ids = [r.org_id for r in self.select(municipality)]
        return analytics.load_sites(self.db, org_ids)

    def requests(self) -> dict:
        items = list(self.db.scalars(helpdesk.visible(self.scope)))
        late = sorted((r for r in items if helpdesk.is_overdue(r)), key=lambda r: r.due_at)
        return {
            **helpdesk.stats(items),
            "overdue_list": [
                {"id": r.id, "title": r.title, "organization": r.organization.name,
                 "assignee": r.assignee.full_name if r.assignee else None, "due": r.due_at}
                for r in late[:8]
            ],
        }

    def knowledge_search(self, query: str, min_score: float = 0.0) -> dict:
        return {"results": [
            {"document_id": r["document_id"], "title": r["title"], "source": r["source_ref"],
             "text": r["content"], "is_official_text": not r["is_summary"], "score": r["score"]}
            for r in rag.search(self.db, query, limit=3) if r["score"] >= min_score
        ]}

    def projects_and_tasks(self) -> dict:
        projects = [p for p in self.db.scalars(select(Project).order_by(Project.id.desc()))
                    if self.scope.can_see_project(p)][:15]
        tasks = self.db.scalars(
            select(Task).where(Task.status != TaskStatus.done).order_by(Task.due_date)
        ).all()
        today = date.today()
        return {
            "projects": [
                {"id": p.id, "title": p.title, "status": p.status,
                 "rate_delta": float(p.rate_delta),
                 "fot_effect_year_rub": float(p.fot_effect_year)}
                for p in projects
            ],
            "open_tasks": [
                {"title": t.title, "status": t.status, "due": t.due_date,
                 "overdue": bool(t.due_date and t.due_date < today)}
                for t in tasks if self.scope.can_see_municipality(t.municipality_id)
            ][:20],
        }


def scope_description(scope: Scope) -> str:
    user = scope.user
    if scope.is_regional:
        return "весь регион"
    if user.municipality_id and user.role == "municipal_specialist":
        municipality = scope.db.get(Municipality, user.municipality_id)
        return f"муниципалитет «{municipality.name}»"
    org = scope.db.scalar(scope.organizations())
    return f"учреждение «{org.name}»" if org else "нет доступных учреждений"


def build_messages(scope: Scope, question: str, history: list[dict], context: str) -> list[dict]:
    """Системная подсказка неизменна, а данные идут в последнем сообщении: так сервер
    модели переиспользует кэш промпта между вопросами и не пересчитывает его заново."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for item in history[-HISTORY_MESSAGES:]:
        if item.get("role") in ("user", "assistant") and item.get("content"):
            messages.append({"role": item["role"], "content": str(item["content"])[:700]})
    user = scope.user
    messages.append({"role": "user", "content": (
        f"Данные системы на {date.today():%d.%m.%Y}. Пользователь: {user.full_name}, "
        f"{ROLE_TITLES.get(user.role, user.role)}; ему доступны: {scope_description(scope)}.\n\n"
        f"{context}\n\nВопрос: {question}"
    )})
    return messages


def run(scope: Scope, question: str, history: list[dict] | None = None) -> Iterator[dict]:
    """Отдаёт события для интерфейса: data (блок данных с источником), sources (на что
    опирается ответ), delta (кусок текста модели), warning, error."""
    from app.services import retrieval  # импорт здесь: retrieval сам использует Toolbox

    history = history or []
    toolbox = Toolbox(scope.db, scope)
    plan = retrieval.build_plan(toolbox, question, history)
    if not plan.blocks:
        # Отвечать не по чему — модель не спрашиваем, чтобы она не взялась фантазировать
        yield {"type": "delta", "text": NO_DATA}
        yield {"type": "sources", "items": []}
        return
    for block in plan.blocks:
        yield {"type": "data", "title": block.title, "markdown": block.markdown,
               "source": block.source}
    yield {"type": "sources", "items": plan.sources()}

    context = plan.context()
    messages = build_messages(scope, question, history, context)
    text = ""
    try:
        for event in llm.stream_chat(messages, sensitive=True, max_tokens=ANSWER_MAX_TOKENS):
            if event["type"] == "delta":
                text += event["text"]
                yield event
    except llm.LLMUnavailable as exc:
        yield {"type": "error", "message": str(exc), "has_data": True}
        return

    foreign = foreign_references(text, context + " " + question)
    if foreign:
        log.info("Answer mentions sources outside the context: %s", foreign)
        yield {"type": "warning", "message": (
            "В выводе модели упомянуты источники, которых нет в базе знаний системы: "
            + "; ".join(foreign[:4]) + ". Эту часть ответа считайте неподтверждённой.")}
    if not text.strip():
        yield {"type": "error", "message": "Модель не дала ответа", "has_data": True}


def answer(scope: Scope, question: str) -> str:
    """Ответ целиком, без стриминга — для бота. Если модель недоступна,
    возвращает сами данные: это полезнее, чем сообщение об ошибке."""
    parts: list[str] = []
    data: list[str] = []
    for event in run(scope, question):
        if event["type"] == "delta":
            parts.append(event["text"])
        elif event["type"] == "data":
            data.append(f"{event['title']}\n{event['markdown']}")
        elif event["type"] == "warning":
            parts.append(f"\n\n⚠ {event['message']}")
        elif event["type"] == "error" and not parts:
            return "\n\n".join(data) or f"Не удалось получить ответ: {event['message']}"
    return "".join(parts).strip() or "\n\n".join(data) or "Модель не дала ответа."
