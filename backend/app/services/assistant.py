"""ИИ-помощник: отвечает на вопросы по данным системы.

Локальная модель на процессоре выдаёт 5–10 токенов в секунду, поэтому гонять её
по кругу «вызови инструмент — прочитай — вызови ещё» слишком долго. Ответ строится
в два шага:

  1. Разбор вопроса обычным кодом (retrieval.py): по словам в вопросе выбираются
     нужные выборки из базы — рейтинг учреждений, отчёт по школе, сценарий
     централизации и т. п. Они сразу уходят пользователю готовыми таблицами.
  2. Модель получает те же таблицы и пишет к ним короткий вывод.

Так пользователь видит цифры из базы через секунду, а модель не может «не заметить»
данные: они уже лежат у неё в контексте. Вызов инструментов оставлен запасным
путём — для вопросов, которые разбор не распознал.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import Scope
from app.models import Category, Municipality, Project, Task, TaskStatus
from app.services import analytics, centralization, llm, rag
from app.services.staffing import DRIVERS, OrgReport

log = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 2
MAX_TOOL_RESULT_CHARS = 3500
HISTORY_MESSAGES = 4
# Вывод к таблицам, а не пересказ: при 6 токенах в секунду это около минуты
ANSWER_MAX_TOKENS = 380

SYSTEM_PROMPT = """Ты — аналитик системы оптимизации штатных расписаний образовательных \
учреждений региона. Отвечаешь руководителям и специалистам управления образования.

В сообщении пользователя перед вопросом идёт блок «Данные из базы». Это актуальная выборка \
из системы, подобранная под вопрос.

Правила:
- Все цифры бери только из блока «Данные из базы» или из результатов инструментов. Если \
нужных данных там нет — скажи об этом прямо, не придумывай.
- Таблицы из блока пользователь уже видит над твоим ответом. Не переписывай их. Дай вывод: \
прямой ответ на вопрос с главными числами и названиями, затем что с этим можно сделать. \
Объём — 3–6 предложений или короткий список.
- Ставки — это штатные единицы, а не люди. Данные обезличены, ФИО в системе нет. На вопросы \
вида «кого уволить» объясняй, по каким функциям факт расходится с нормативом и какие есть \
варианты (вакансии, перераспределение, централизация); кадровое решение остаётся за \
руководителем.
- «Избыток» — превышение факта над расчётным нормативом, «нехватка» — наоборот.
- Не складывай и не пересчитывай числа сам: итоги уже посчитаны — они в первой строке \
блока и в строке «Итого». Бери готовые.
- Инструменты вызывай, только если приложенных данных для ответа не хватает. В ответе \
названия инструментов не упоминай.
- Отвечай по-русски. Числа приводи с единицами: ставки, ₽, %."""

ROLE_TITLES = {
    "admin": "администратор системы",
    "regional_analyst": "региональный аналитик",
    "municipal_specialist": "специалист управления образования",
    "director": "директор ОУ",
    "observer": "наблюдатель",
}


def _tool(name: str, description: str, properties: dict | None = None,
          required: list[str] | None = None) -> dict:
    return {"type": "function", "function": {
        "name": name,
        "description": description,
        "parameters": {"type": "object", "properties": properties or {},
                       "required": required or []},
    }}


_MUNICIPALITY = {"type": "string", "description": "Название муниципалитета или его часть"}
_CATEGORY = {"type": "string", "enum": [c.value for c in Category],
             "description": "teaching — педагоги, admin — АУП, support — вспомогательный "
                            "персонал, medical — медработники"}

TOOLS = [
    _tool("organizations", "Список учреждений с показателями для рейтингов и поиска. Если "
          "вопрос про одну категорию персонала, передай category.",
          {"municipality": _MUNICIPALITY,
           "search": {"type": "string", "description": "Часть названия учреждения"},
           "category": _CATEGORY,
           "sort": {"type": "string", "enum": ["surplus", "shortage", "compliance", "saving"]},
           "limit": {"type": "integer"}}),
    _tool("organization_report", "Отчёт по одному учреждению: контингент, факт и норматив "
          "по каждой функции, формулы расчёта.",
          {"organization": {"type": "string", "description": "Название или его часть"}},
          ["organization"]),
    _tool("deviations", "Крупнейшие отклонения факта от норматива по парам «учреждение — "
          "функция».",
          {"category": _CATEGORY, "municipality": _MUNICIPALITY,
           "limit": {"type": "integer"}}),
    _tool("centralization", "Сценарий централизации АУП и вспомогательного персонала.",
          {"municipality": _MUNICIPALITY}),
    _tool("knowledge_search", "Поиск по базе нормативных документов.",
          {"query": {"type": "string"}}, ["query"]),
]


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

    def call(self, name: str, arguments: dict) -> dict:
        handler = getattr(self, name, None) if name in _TOOL_NAMES else None
        if handler is None:
            return {"error": f"Инструмент {name} не существует"}
        try:
            return handler(**arguments)
        except TypeError as exc:
            return {"error": f"Неверные аргументы: {exc}"}

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

    def knowledge_search(self, query: str) -> dict:
        return {"results": [
            {"title": r["title"], "source": r["source_ref"], "text": r["content"],
             "is_official_text": not r["is_summary"]}
            for r in rag.search(self.db, query, limit=3)
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


_TOOL_NAMES = {tool["function"]["name"] for tool in TOOLS}


def scope_description(scope: Scope) -> str:
    user = scope.user
    if scope.is_regional:
        return "весь регион"
    if user.municipality_id and user.role == "municipal_specialist":
        municipality = scope.db.get(Municipality, user.municipality_id)
        return f"муниципалитет «{municipality.name}»"
    org = scope.db.scalar(scope.organizations())
    return f"учреждение «{org.name}»" if org else "нет доступных учреждений"


def _compact(value: dict) -> str:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    if len(text) > MAX_TOOL_RESULT_CHARS:
        text = text[:MAX_TOOL_RESULT_CHARS] + "… (результат обрезан, уточните запрос)"
    return text


def build_messages(scope: Scope, question: str, history: list[dict], context: str) -> list[dict]:
    """Системная подсказка неизменна, а данные идут в последнем сообщении: так сервер
    модели переиспользует кэш промпта между вопросами и не пересчитывает его заново."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for item in history[-HISTORY_MESSAGES:]:
        if item.get("role") in ("user", "assistant") and item.get("content"):
            messages.append({"role": item["role"], "content": str(item["content"])[:700]})
    user = scope.user
    messages.append({"role": "user", "content": (
        f"Данные из базы на {date.today():%d.%m.%Y}. Пользователь: {user.full_name}, "
        f"{ROLE_TITLES.get(user.role, user.role)}; ему доступны: {scope_description(scope)}.\n\n"
        f"{context}\n\nВопрос: {question}"
    )})
    return messages


def run(scope: Scope, question: str, history: list[dict] | None = None) -> Iterator[dict]:
    """Отдаёт события для интерфейса: data (таблица из базы), delta (кусок текста
    модели), tool (модель запросила что-то сама), error."""
    from app.services import retrieval  # импорт здесь: retrieval сам использует Toolbox

    history = history or []
    toolbox = Toolbox(scope.db, scope)
    plan = retrieval.build_plan(toolbox, question, history)
    for block in plan.blocks:
        yield {"type": "data", "title": block.title, "markdown": block.markdown}

    messages = build_messages(scope, question, history, plan.context())
    # Если разбор понял вопрос, данных достаточно и второй круг не нужен
    tools: list[dict] | None = None if plan.recognized else TOOLS

    for round_no in range(MAX_TOOL_ROUNDS + 1):
        round_tools = tools if round_no < MAX_TOOL_ROUNDS else None
        calls: list[dict] = []
        text = ""
        try:
            for event in llm.stream_chat(messages, tools=round_tools, sensitive=True,
                                         max_tokens=ANSWER_MAX_TOKENS):
                if event["type"] == "delta":
                    text += event["text"]
                    yield event
                else:
                    calls = event["calls"]
        except llm.LLMRejectedRequest as exc:
            if tools is None:
                yield {"type": "error", "message": str(exc)}
                return
            log.info("LLM rejected tools, answering from prefetched data: %s", exc)
            tools = None
            continue
        except llm.LLMUnavailable as exc:
            yield {"type": "error", "message": str(exc), "has_data": bool(plan.blocks)}
            return

        if not calls:
            return

        messages.append({
            "role": "assistant",
            "content": text or None,
            "tool_calls": [
                {"id": c["id"] or f"call_{i}", "type": "function",
                 "function": {"name": c["name"], "arguments": c["arguments"] or "{}"}}
                for i, c in enumerate(calls)
            ],
        })
        for i, call in enumerate(calls):
            try:
                arguments = json.loads(call["arguments"] or "{}")
            except ValueError:
                arguments = {}
            yield {"type": "tool", "name": call["name"], "arguments": arguments}
            result = toolbox.call(call["name"], arguments if isinstance(arguments, dict) else {})
            messages.append({"role": "tool", "tool_call_id": call["id"] or f"call_{i}",
                             "content": _compact(result)})

    yield {"type": "error", "message": "Модель не смогла сформулировать ответ, уточните вопрос"}


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
        elif event["type"] == "error" and not parts:
            return "\n\n".join(data) or f"Не удалось получить ответ: {event['message']}"
    return "".join(parts).strip() or "\n\n".join(data) or "Модель не дала ответа."
