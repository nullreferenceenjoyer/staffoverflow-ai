"""Подбор данных под вопрос без участия модели.

Вопрос разбирается по ключевым словам: какой муниципалитет, какое учреждение,
какая категория персонала и что именно хотят узнать. По результату собираются
блоки — готовые таблицы в Markdown. Один и тот же текст показывается пользователю
и кладётся в контекст модели, так что расхождений между ними быть не может.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from app.services.assistant import Toolbox, normalize
from app.services.functions import CATEGORY_TITLES
from app.services.staffing import OrgReport, ru

# Сколько текста отдаём модели: при контексте 8K должно остаться место под историю и ответ
CONTEXT_BUDGET_CHARS = 5200
ROWS = 8

CATEGORY_PATTERNS = {
    "admin": r"\bауп\b|административ|управленч|бухгалт|кадров|секретар|делопроизв|закуп",
    "support": r"\bвп\b|\bувп\b|вспомогат|обслуживающ|уборщ|уборк|охран|сторож|дворник|техничк",
    "teaching": r"педагог|учител|воспитател|логопед|психолог|дефектолог",
    "medical": r"медицин|медсест|медработ",
}
INTENTS = {
    "centralization": r"централиз|бригад|объедин|расчетн\w* центр|аутсорс|сервисн\w* центр",
    "knowledge": r"приказ|постановлен|на основании|положен[оа]?\b|закон|методик|формул"
                 r"|как (?:счита|рассчит)|по какому нормативу|нормативн\w* (?:акт|документ)",
    "work": r"проект|задач|срок|просроч|согласован|утвержд",
    "vacancies": r"ваканс|вакант|свободн\w* ставк|без увольнен",
    "shortage": r"нехват|не хватает|дефицит|недостат|недоукомплект",
    "compliance": r"соответств|хуже всего|лучше всего|рейтинг",
    "saving": r"эконом|\bфот\b|сэконом|деньг|бюджет|высвобод",
    "territories": r"округ|муниципал|район|территор",
    "program": r"паспорт|цел[ьи] проекта|план\w* высвобожд|дорожн\w* карт",
}
ORG_KINDS = {
    "preschool": r"сад\w*|доу|детск\w+ сад\w*",
    "complex": r"комплекс\w*",
    "school": r"сош|школ\w*|лице\w*|гимнази\w*",
}
FOLLOW_UP = r"\b(?:них|ним|этом|этой|этих|там|него|нему|ней|подробнее|а по|тоже|еще)\b"


@dataclass
class Block:
    title: str
    markdown: str


@dataclass
class Plan:
    blocks: list[Block] = field(default_factory=list)
    summary: str = ""  # одна строка итогов — в контекст модели, пользователю не показывается
    recognized: bool = False  # удалось ли понять, о чём вопрос

    def context(self) -> str:
        parts = [self.summary]
        used = len(self.summary)
        for block in self.blocks:
            text = f"### {block.title}\n{block.markdown}"
            if used + len(text) > CONTEXT_BUDGET_CHARS:
                text = text[: max(CONTEXT_BUDGET_CHARS - used, 0)]
                if len(text) < 200:
                    break
            parts.append(text)
            used += len(text)
        return "\n\n".join(parts)


def table(headers: list[str], rows: list[list]) -> str:
    def cell(value) -> str:
        if value is None:
            return "—"
        if isinstance(value, float):
            return ru(round(value, 2))
        return str(value).replace("|", "/")

    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(cell(v) for v in row) + " |" for row in rows]
    return "\n".join(lines)


def money(value: float) -> str:
    if abs(value) >= 1_000_000:
        return f"{ru(round(value / 1_000_000, 1))} млн ₽"
    return f"{ru(round(value / 1000))} тыс. ₽"


def signed(value: float) -> str:
    return ("+" if value > 0 else "") + ru(round(value, 2))


def detect_category(text: str) -> str | None:
    for category, pattern in CATEGORY_PATTERNS.items():
        if re.search(pattern, text):
            return category
    return None


def stem(word: str) -> str:
    """Грубая основа слова: «заречный» → «заречн», «дубна» → «дубн».
    Этого хватает, чтобы узнать название в любом падеже."""
    return word[: min(6, max(4, len(word) - 2))]


def detect_municipality(text: str, reports: list[OrgReport]) -> str | None:
    for name in sorted({r.municipality for r in reports}):
        words = [w for w in re.split(r"[\s.]+", normalize(name)) if len(w) > 3]
        if any(stem(word) in text for word in words):
            return name
    return None


def detect_organizations(text: str, reports: list[OrgReport]) -> list[OrgReport]:
    kinds = "|".join(ORG_KINDS.values())
    pattern = rf"(?:({kinds})\s*)?(?:№|номер)?\s*(\d{{1,4}})\b"
    # Число считается номером учреждения, только если рядом «школа», «сад» или знак №
    match = next((m for m in re.finditer(pattern, text) if m.group(1) or "№" in m.group(0)), None)
    if match is None:
        return []
    number, kind_word = match.group(2), match.group(1)
    found = [r for r in reports if re.search(rf"№\s*{number}\b", r.name)]
    if kind_word:
        for org_type, pattern in ORG_KINDS.items():
            if re.fullmatch(pattern, kind_word):
                found = [r for r in found if r.org_type == org_type] or found
    return found


def _organization_block(toolbox: Toolbox, report: OrgReport) -> Block:
    details = toolbox.report_details(report)
    functions = [f for f in details["functions"] if f["norm"] is not None]
    functions.sort(key=lambda f: -abs(f["delta"]))
    rows = [[f["title"], f["actual"], f["norm"], signed(f["delta"]), f["vacant"] or ""]
            for f in functions[:12]]
    metrics = ", ".join(f"{ru(v)} {k}" for k, v in list(details["metrics"].items())[:6])
    head = (
        f"Показатели: {metrics}. Факт {ru(details['actual'])} ст., норматив "
        f"{ru(details['norm'])} ст., избыток {ru(details['surplus'])} ст., нехватка "
        f"{ru(details['shortage'])} ст., соответствие {ru(details['compliance_pct'])} %, "
        f"потенциал экономии {money(details['saving_potential_year_rub'])} в год."
    )
    body = table(["Функция", "Факт", "Норматив", "Отклонение", "Вакансии"], rows)
    return Block(report.name, f"{head}\n\n{body}")


def _ranking_block(toolbox: Toolbox, municipality, category, sort: str) -> Block | None:
    data = toolbox.organizations(municipality=municipality, category=category, sort=sort,
                                 limit=ROWS)
    if not data["organizations"]:
        return None
    titles = {"surplus": "с наибольшим избытком", "shortage": "с наибольшей нехваткой",
              "compliance": "с наименьшим соответствием нормативам",
              "saving": "с наибольшим потенциалом экономии"}
    scope = f" ({CATEGORY_TITLES[category]})" if category else ""
    rows = [[o["name"], o["actual"], o["norm"], o["surplus"], o["shortage"],
             f"{ru(o['compliance_pct'])} %", money(o["saving_potential_year_rub"])]
            for o in data["organizations"]]
    headers = ["Учреждение", "Факт", "Норматив", "Избыток", "Нехватка", "Соответствие",
               "Экономия в год"]
    top = data["organizations"][0]
    leader = {
        "surplus": f"избыток {ru(top['surplus'])} ст.",
        "shortage": f"нехватка {ru(top['shortage'])} ст.",
        "compliance": f"соответствие {ru(top['compliance_pct'])} %",
        "saving": f"экономия {money(top['saving_potential_year_rub'])} в год",
    }[sort]
    head = f"Первое в списке: {top['name']} — {leader}."
    return Block(f"Учреждения {titles[sort]}{scope}, всего {data['total']}",
                 f"{head}\n\n{table(headers, rows)}")


def _deviations_block(toolbox: Toolbox, municipality, category) -> Block | None:
    rows = toolbox.deviations(category=category, municipality=municipality, limit=ROWS)
    if not rows["deviations"]:
        return None
    body = table(
        ["Учреждение", "Функция", "Факт", "Норматив", "Отклонение", "ФОТ в год"],
        [[d["organization"], d["title"], d["actual"], d["norm"], signed(d["delta"]),
          money(d["fot_effect_year"])] for d in rows["deviations"]],
    )
    return Block("Крупнейшие отклонения от норматива", body)


def _centralization_block(toolbox: Toolbox, municipality) -> Block | None:
    scenario = toolbox.centralization(municipality=municipality)
    if not scenario["functions"]:
        return None
    body = table(
        ["Функция", "Центр", "ОУ", "Сейчас", "Норматив", "В центре", "Высвобождается",
         "Экономия в год"],
        [[f["title"], f["center"], f["organizations"], f["actual"], f["norm"], f["centralized"],
          f["released"], money(f["saving_year"])] for f in scenario["functions"]],
    )
    head = (f"Учреждений: {scenario['organizations']}. Всего высвобождается "
            f"{ru(scenario['released_total'])} ст., экономия {money(scenario['saving_year'])} "
            "в год.")
    where = f": {municipality}" if municipality else ""
    return Block(f"Сценарий централизации АУП и ВП{where}", f"{head}\n\n{body}")


def _vacancies_block(toolbox: Toolbox, municipality, category) -> Block | None:
    data = toolbox.vacancies(municipality=municipality, category=category)
    if not data["vacancies"]:
        return None
    body = table(
        ["Функция", "Вакантно, ст.", "из них сверх норматива", "Учреждений"],
        [[v["title"], v["vacant"], v["of_them_above_norm"], v["organizations"]]
         for v in data["vacancies"][:12]]
        + [["Итого", data["total"], data["above_norm"], ""]],
    )
    what = f" ({CATEGORY_TITLES[category]})" if category else ""
    head = (f"Всего вакантно{what}: {ru(data['total'])} ст. Из них сверх норматива — "
            f"{ru(data['above_norm'])} ст.: столько можно сократить, никого не увольняя.")
    return Block(f"Вакантные ставки{what}", f"{head}\n\n{body}")


def _territories_block(toolbox: Toolbox) -> Block | None:
    rows = toolbox.overview()["municipalities"]
    if len(rows) < 2:
        return None
    body = table(
        ["Муниципалитет", "ОУ", "Факт", "Норматив", "Избыток", "Нехватка", "Экономия в год"],
        [[m["name"], m["organizations"], m["actual"], m["norm"], m["surplus"], m["shortage"],
          money(m["saving"])] for m in rows],
    )
    return Block("Показатели по муниципалитетам", body)


def _knowledge_block(toolbox: Toolbox, question: str) -> Block | None:
    results = toolbox.knowledge_search(question)["results"]
    if not results:
        return None
    # Маленькая модель легко путает соседние нормы в одном абзаце («логопед на 12 детей,
    # психолог на 20»), поэтому предложения со словами из вопроса выносим наверх отдельно
    stems = {stem(word) for word in re.findall(r"[а-я]{6,}", normalize(question))}
    quotes: list[str] = []
    parts = []
    for item in results[:2]:
        kind = "" if item["is_official_text"] else " (краткая справка)"
        parts.append(f"**{item['title']}**{kind}, {item['source']}\n\n{item['text'][:700]}")
        for sentence in re.split(r"(?<=[.!?])\s+", item["text"]):
            if any(s in normalize(sentence) for s in stems) and sentence not in quotes:
                quotes.append(f"«{sentence.strip()}» — {item['source']}")
    head = ""
    if quotes:
        head = "Ближе всего к вопросу:\n" + "\n".join(f"- {q}" for q in quotes[:4]) + "\n\n"
    return Block("Из базы знаний", head + "\n\n".join(parts))


def _work_block(toolbox: Toolbox) -> Block | None:
    data = toolbox.projects_and_tasks()
    parts = []
    if data["projects"]:
        parts.append(table(
            ["Проект", "Статус", "Ставки", "ФОТ в год"],
            [[p["title"], p["status"], signed(p["rate_delta"]), money(p["fot_effect_year_rub"])]
             for p in data["projects"][:6]],
        ))
    if data["open_tasks"]:
        parts.append(table(
            ["Задача", "Статус", "Срок", "Просрочена"],
            [[t["title"][:90], t["status"],
              t["due"].strftime("%d.%m.%Y") if isinstance(t["due"], date) else "—",
              "да" if t["overdue"] else ""] for t in data["open_tasks"][:8]],
        ))
    return Block("Проекты и открытые задачи", "\n\n".join(parts)) if parts else None


def _summary_line(toolbox: Toolbox, municipality: str | None) -> str:
    s = toolbox.overview(municipality)
    categories = "; ".join(
        f"{c['title']}: факт {ru(c['actual'])}, норматив {ru(c['norm'])}, избыток "
        f"{ru(c['surplus'])}, нехватка {ru(c['shortage'])}" for c in s["categories"]
    )
    where = municipality or "все доступные учреждения"
    return (
        f"Итоги ({where}): учреждений {s['organizations']}, обучающихся {s['students']}, "
        f"факт {ru(s['actual_total'])} ст., норматив {ru(s['norm_total'])} ст., избыток "
        f"{ru(s['surplus'])} ст., нехватка {ru(s['shortage'])} ст., соответствие "
        f"{ru(s['compliance'])} %, ФОТ {money(s['fot_actual_year'])} в год, потенциал экономии "
        f"{money(s['saving_potential_year'])} в год. По категориям (ставки): {categories}."
    )


def build_plan(toolbox: Toolbox, question: str, history: list[dict]) -> Plan:
    text = normalize(question)
    # «А по ним подробнее?» без прошлого вопроса не разобрать
    if len(text) < 30 or re.search(FOLLOW_UP, text):
        previous = [m["content"] for m in history if m.get("role") == "user"][-1:]
        text = normalize(" ".join(previous)) + " " + text

    reports = toolbox.reports
    municipality = detect_municipality(text, reports)
    category = detect_category(text)
    intents = {name for name, pattern in INTENTS.items() if re.search(pattern, text)}
    scoped = toolbox.select(municipality) if municipality else reports
    organizations = detect_organizations(text, scoped)

    plan = Plan(summary=_summary_line(toolbox, municipality))
    blocks: list[Block | None] = []

    if "program" in intents:
        from app.services import program  # модуль тянет модели проекта, нужен не всегда

        blocks.append(program.assistant_block(toolbox.db, toolbox.scope))
    for report in organizations[:2]:
        blocks.append(_organization_block(toolbox, report))
    if "centralization" in intents:
        blocks.append(_centralization_block(toolbox, municipality))
    if "vacancies" in intents:
        blocks.append(_vacancies_block(toolbox, municipality, category))
    if "knowledge" in intents:
        blocks.append(_knowledge_block(toolbox, question))
    if "work" in intents:
        blocks.append(_work_block(toolbox))
    if "territories" in intents and not municipality and not organizations:
        blocks.append(_territories_block(toolbox))

    # Рейтинг и отклонения — ответ по умолчанию и на всё, что касается избытка и нехватки
    specific = organizations or intents & {"centralization", "knowledge", "work", "program",
                                           "vacancies"}
    if not specific or intents & {"shortage", "compliance"}:
        sort = next((s for s in ("shortage", "compliance", "saving") if s in intents), "surplus")
        if len(scoped) > 1:
            blocks.append(_ranking_block(toolbox, municipality, category, sort))
        blocks.append(_deviations_block(toolbox, municipality, category))

    plan.blocks = [block for block in blocks if block is not None]
    plan.recognized = bool(organizations or intents or category or municipality)
    return plan
