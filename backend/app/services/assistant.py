"""Помощник по штатке: отвечает на вопросы о нормативах, анализе и кадровых заявках.

Модель сама ничего не считает и в базу не ходит. Перед каждым ответом собирается
справка из того, что пользователь и так видит в разделе: итоги анализа по его
территории или по одному учреждению, применённые нормативы с расчётом, показатели
и кадровые заявки. Справка и последние реплики разговора уходят в локальную модель.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.deps import Scope
from app.models import (
    AssistantChat,
    AssistantMessage,
    IncomingRequest,
    InstitutionMetrics,
    Municipality,
    NormativeCoefficient,
    Organization,
    PersonnelGroup,
    Role,
    StaffingSchedule,
)
from app.services import helpdesk, llm, norms, payroll, routing, staffing, staffing_analysis
from app.services.directory import ROLE_TITLES
from app.services.staffing_analysis import CATEGORY_TITLES, STATUS_TITLES

HISTORY = 8  # сколько последних реплик разговора отдавать модели
TOP_ORGS = 12  # учреждений с самыми большими отклонениями в справке по территории
MAX_NORMS = 40
MAX_REQUESTS = 12
REQUEST_STATUS = {
    "new": "новая", "assigned": "назначена", "in_progress": "в работе",
    "on_hold": "ждёт ответа", "done": "выполнена", "closed": "закрыта",
    "rejected": "отклонена",
}
SCHEDULE_STATUS = {"approved": "утверждена", "draft": "черновик", "archived": "в архиве"}

RULES = """Ты помощник в разделе «Нормативная численность» системы заявок школ и детских садов.
Отвечаешь по-русски, коротко и простыми словами, без канцелярита. Опирайся только на справку
ниже. Если в справке нужных цифр нет, так и скажи и подскажи, где их посмотреть или кто их вносит.
Ничего не выдумывай: ни нормативов, ни цифр, ни документов.

Как устроен расчёт:
- Норматив — сколько ставок положено группе должностей. Он считается из показателя
  учреждения: «1 ставка на 300 обучающихся» при 840 обучающихся даёт 2,8, после
  округления вверх до 0,25 — 3 ставки. Бывают пороги («1,25 ставки при числе обучающихся
  от 801»), минимум и максимум. Нормативы вносит региональный аналитик, местные —
  специалист управления образования; у каждого есть документ-основание.
- Факт берётся из штатного расписания учреждения на учебный год: «утверждено» — сколько
  ставок в штатке, «занято» — сколько из них фактически занято. Это итоги по группам
  (ставки и средний оклад), без ФИО. Вносит их директор в «Проверить данные» или специалист
  и аналитик загрузкой из Excel. Показатели (обучающиеся, классы, группы, площадь) — там же.
- Отклонение = факт − норматив. Минус — дефицит, плюс — сверх норматива, в пределах
  допуска (обычно 0,25 ставки или 5 %) — норма. Анализ «по занятости» сравнивает норматив
  с занятыми ставками, «по штатке» — с утверждёнными.
- «Нет данных» — когда не указан показатель, нет утверждённой штатки или не ведётся
  занятость. «Требует проверки» — норматив для группы не настроен или отклонения по
  группам компенсируют друг друга.
- Пересчёт идёт сам после любой правки штатки, показателей или нормативов и раз в сутки.
- Из анализа создаётся заявка: дефицит — «Дополнительные ставки» (АУП — специалисту
  управления, вспомогательный персонал — директору), излишек — «Сокращение и
  реорганизация» (крупный — региональному аналитику), нет данных — «Исправление данных»,
  вопрос — «Вопрос по нормативам» региональному аналитику.
- ФОТ (фонд оплаты труда) считается так: средний оклад за ставку × ставки × 12, без
  надбавок и начислений. «ФОТ по штатке» — за все утверждённые ставки, «ФОТ занятых» —
  за занятые, разница — сколько приходится на вакансии. Оклады — итог по группе, не по людям.
- Каждое изменение штатки сохраняется версией. В справке есть история: что поменялось
  по группам и на сколько изменился ФОТ в год.
- Если спрашивают «что будет, если сократить или добавить N ставок» в группе: возьми
  строку ЭТОЙ группы в разделе «Оклады и ФОТ по группам». ФОТ изменится на N × «одна
  ставка стоит». Норматив не меняется (он зависит от показателей учреждения), а меняется
  отклонение: новое отклонение = текущее отклонение − N при сокращении и + N при
  добавлении; минус — дефицит, плюс — сверх норматива, около нуля — норма. Назови
  оклад группы, новый ФОТ группы и новое отклонение. Если оклада группы нет, так и скажи.
Не советуй увольнять людей: излишек ставки — повод проверить штатку и занятость, а не решение."""


class AssistantUnavailable(Exception):
    pass


def num(value) -> str:
    return norms.num(value)


def signed(value) -> str:
    if value is None:
        return "—"
    sign = "+" if value > 0 else "−" if value < 0 else ""
    return f"{sign}{num(abs(value))}"


# --- справка ---------------------------------------------------------------------------


def _org_name(org: Organization) -> str:
    """В демо-данных муниципалитет уже есть в названии — не повторяем его."""
    if org.municipality.name in org.name:
        return org.name
    return f"{org.name}, {org.municipality.name}"


def _who(scope: Scope, org: Organization | None) -> str:
    user = scope.user
    role = ROLE_TITLES.get(user.role, user.role)
    if org is not None:
        where = f"учреждение «{_org_name(org)}»"
    elif scope.is_regional:
        where = "весь регион"
    elif user.role == Role.municipal_specialist and user.municipality_id:
        municipality = scope.db.get(Municipality, user.municipality_id)
        where = municipality.name if municipality else "свой муниципалитет"
    else:
        where = "своё учреждение"
    return f"Пользователь: {role}. Разговор про: {where.rstrip('.')}."


def _metrics_line(metrics: dict) -> str:
    parts = []
    for key in staffing_analysis.METRIC_FIELDS:
        value = metrics.get(key)
        title = norms.METRICS[key].lower()
        parts.append(f"{title} — {'не указано' if value is None else num(value)}")
    return "; ".join(parts)


def _group_line(occupied: dict, approved: dict | None) -> str:
    """Одна группа: норматив с расчётом, штатка, занятость и что получилось."""
    name = occupied["group"]
    head = f"- {name}: норматив {num(occupied['required'])}"
    # У норматива без показателя расчёт вырождается в «1 ставка = 1 ставка»
    rules = [c["explain"] if ":" in (c.get("explain") or "") else c.get("rule")
             for c in occupied["coefficients"]]
    if rules:
        head += f" ({'; '.join(r for r in rules if r)})"
    head += f"; по штатке {num(occupied['approved'])}, занято {num(occupied['occupied'])}"
    status = STATUS_TITLES[occupied["status"]].lower()
    if occupied["deviation"] is not None:
        head += f"; по занятости {signed(occupied['deviation'])} — {status}"
    else:
        head += f"; по занятости — {status}"
    if approved and approved["status"] != occupied["status"]:
        head += (f"; по штатке {signed(approved['deviation'])} — "
                 f"{STATUS_TITLES[approved['status']].lower()}")
    if occupied["reasons"]:
        head += f" ({'; '.join(occupied['reasons'])})"
    return head


def _institution(db: Session, org: Organization, year: str) -> list[str]:
    staffing_analysis.ensure(db, year, [org.id])
    rows = [staffing.result_out(r) for r in staffing.current_rows(db, year, [org.id])]
    schedule = db.scalar(select(StaffingSchedule).where(
        StaffingSchedule.organization_id == org.id, StaffingSchedule.academic_year == year))
    metrics = db.scalar(select(InstitutionMetrics).where(
        InstitutionMetrics.organization_id == org.id, InstitutionMetrics.academic_year == year))
    values = {k: getattr(metrics, k) if metrics else None
              for k in staffing_analysis.METRIC_FIELDS}

    lines = [f"Учреждение «{_org_name(org)}», учебный год {year}."]
    lines.append(f"Показатели: {_metrics_line(values)}"
                 + (f" (источник: {metrics.source})." if metrics else "."))
    if schedule is None:
        lines.append("Штатного расписания на этот год нет.")
    else:
        state = SCHEDULE_STATUS.get(schedule.status, schedule.status)
        lines.append(f"Штатное расписание: {state}.")

    by_key = {(r["category"], r["basis"], r["group_id"]): r for r in rows}
    for category, title in CATEGORY_TITLES.items():
        total = by_key.get((category, "occupied", None))
        if total is None:
            continue
        lines.append("")
        line = (f"{title}: норматив {num(total['required'])}, по штатке "
                f"{num(total['approved'])}, занято {num(total['occupied'])}, "
                f"итог по занятости — {STATUS_TITLES[total['status']].lower()}")
        if total["deviation"] is not None:
            line += f" ({signed(total['deviation'])})"
        approved_total = by_key.get((category, "approved", None))
        if approved_total and approved_total["status"] != total["status"]:
            line += f", по штатке — {STATUS_TITLES[approved_total['status']].lower()}"
        if total["reasons"]:
            line += f". Причины: {'; '.join(total['reasons'])}"
        lines.append(line + ".")
        for row in rows:
            if row["category"] == category and row["basis"] == "occupied" and row["group_id"]:
                lines.append(_group_line(row, by_key.get((category, "approved", row["group_id"]))))
    documents = staffing.documents_of(rows)
    if documents:
        lines.append("")
        lines.append(f"Документы-основания: {'; '.join(documents)}.")
    lines += ["", *_institution_payroll(db, org, year)]
    return lines


def _institution_payroll(db: Session, org: Organization, year: str) -> list[str]:
    data = payroll.institution(db, org, year, "occupied")
    total = data["totals"]
    if not data["lines"]:
        return ["ФОТ: штатки нет, считать не из чего."]
    lines = [f"ФОТ по штатке {payroll.rub(total['payroll_approved'])} в год, занятых ставок — "
             f"{payroll.rub(total['payroll_occupied'])}, на вакансии приходится "
             f"{payroll.rub(total['vacant_payroll'])}."]
    if total["missing_salary"]:
        lines.append(f"Оклад не указан у групп: {total['missing_salary']}.")
    lines.append("Оклады и ФОТ по группам:")
    for line in data["lines"]:
        if line["approved"] is None:
            continue
        one = payroll.annual(1, line["salary"])
        text = (f"- {line['group']}: оклад {payroll.rub(line['salary'])}/мес, одна ставка "
                f"стоит {payroll.rub(one)}/год; по штатке {num(line['approved'])}, занято "
                f"{num(line['occupied'])}, ФОТ {payroll.rub(line['payroll_approved'])}/год; "
                f"норматив {num(line['required'])}, отклонение {signed(line['deviation'])}")
        if line["deviation"] and line["deviation_cost"] is not None:
            what = "закрыть дефицит" if line["deviation"] < 0 else "излишек"
            text += f" ({what}: {payroll.rub(abs(line['deviation_cost']))}/год)"
        lines.append(text)
    history = data["history"]
    if history:
        lines.append("История изменений штатки (новые сверху):")
        for version in history[:6]:
            when = f"{version['created_at']:%d.%m.%Y}"
            who = f", {version['author']}" if version["author"] else ""
            if version["first"]:
                lines.append(f"- {when}: исходная штатка, {num(version['approved'])} ставок, "
                             f"ФОТ {payroll.rub(version['payroll_approved'])}/год{who}")
                continue
            changes = ("; ".join(payroll.change_text(c) for c in version["changes"])
                       or "изменился статус")
            lines.append(f"- {when}{who}: {changes}. Итого ставок "
                         f"{signed(version['approved_delta'])}, ФОТ "
                         f"{payroll.signed_rub(version['payroll_delta'])}/год"
                         + (f" («{version['comment']}»)" if version["comment"] else ""))
    return lines


def _territory(db: Session, orgs: list[Organization], year: str) -> list[str]:
    ids = [o.id for o in orgs]
    staffing_analysis.ensure(db, year, ids)
    names = {o.id: o for o in orgs}
    rows = staffing.current_rows(db, year, ids, basis="occupied")
    lines = [f"Учебный год {year}, учреждений: {len(orgs)}. Анализ по занятости."]
    for category, title in CATEGORY_TITLES.items():
        totals = [r for r in rows if r.top_category == category and r.personnel_group_id is None]
        counts = dict.fromkeys(STATUS_TITLES, 0)
        for r in totals:
            counts[r.status] += 1
        summary = ", ".join(f"{STATUS_TITLES[s].lower()} — {n}" for s, n in counts.items() if n)
        lines.append("")
        lines.append(f"{title}: {summary or 'расчёта нет'}.")

        problems: dict[int, list[str]] = {}
        for r in rows:
            if (r.top_category == category and r.personnel_group_id is not None
                    and r.status in ("deficit", "surplus") and r.deviation_fte is not None):
                problems.setdefault(r.organization_id, []).append(
                    f"{r.group.name if r.group else '?'} {signed(r.deviation_fte)}")
        off = sorted((r for r in totals if r.status in ("deficit", "surplus", "warning")),
                     key=lambda r: -abs(r.deviation_fte or 0))
        for r in off[:TOP_ORGS]:
            org = names[r.organization_id]
            text = (f"- {_org_name(org)}: "
                    f"{STATUS_TITLES[r.status].lower()}, норматив {num(r.required_fte)}, "
                    f"занято {num(r.occupied_fte)}, отклонение {signed(r.deviation_fte)}")
            if problems.get(org.id):
                text += f"; по группам: {', '.join(problems[org.id][:4])}"
            lines.append(text)
        if len(off) > TOP_ORGS:
            lines.append(f"- и ещё {len(off) - TOP_ORGS} с отклонениями")
        lacking = [r for r in totals if r.status == "no_data"]
        if lacking:
            lines.append("Нет данных:")
            for r in lacking[:TOP_ORGS]:
                lines.append(f"- {names[r.organization_id].name}: "
                             f"{'; '.join(r.missing_reasons or ['данные неполные'])}")
            if len(lacking) > TOP_ORGS:
                lines.append(f"- и ещё {len(lacking) - TOP_ORGS}")
    lines += ["", *_territory_payroll(db, orgs, year)]
    return lines


def _territory_payroll(db: Session, orgs: list[Organization], year: str) -> list[str]:
    data = payroll.dashboard(db, orgs, year, "occupied")
    kpi = data["kpi"]
    lines = [f"ФОТ по штаткам {payroll.rub(kpi['payroll_approved'])} в год, занятых ставок — "
             f"{payroll.rub(kpi['payroll_occupied'])}. Дефицит {num(kpi['deficit_fte'])} ставок, "
             f"закрыть его стоит {payroll.rub(kpi['deficit_cost'])}/год; сверх норматива "
             f"{num(kpi['surplus_fte'])} ставок на {payroll.rub(kpi['surplus_cost'])}/год."]
    if kpi["cost_estimated"]:
        lines.append("Где оклада группы нет, взят средний оклад группы по территории.")
    if len(data["by_municipality"]) > 1:
        lines.append("По муниципалитетам:")
        for m in data["by_municipality"]:
            lines.append(f"- {m['municipality']}: учреждений {m['organizations']}, с "
                         f"отклонениями {m['problems']}, дефицит {num(m['deficit'])} ставок "
                         f"({payroll.rub(m['deficit_cost'])}/год), ФОТ "
                         f"{payroll.rub(m['payroll'])}/год")
    if data["changes"]:
        lines.append("Последние изменения штаток:")
        for change in data["changes"]:
            items = "; ".join(payroll.change_text(c) for c in change["changes"])
            lines.append(f"- {change['created_at']:%d.%m.%Y}, {change['organization']}: {items}. "
                         f"ФОТ {payroll.signed_rub(change['payroll_delta'])}/год")
    return lines


def _norms(db: Session, scope: Scope, org: Organization | None) -> list[str]:
    coefs = list(db.scalars(select(NormativeCoefficient).options(
        selectinload(NormativeCoefficient.document),
        selectinload(NormativeCoefficient.group))))
    scope_orgs = {o.id: o for o in db.scalars(scope.organizations())}
    groups = {g.id: g for g in db.scalars(select(PersonnelGroup))}
    lines = []
    for coef in sorted(coefs, key=lambda c: (groups[c.personnel_group_id].sort_order, c.id)):
        if org is not None and not norms.scope_matches(coef, org):
            continue
        if not staffing.visible_norm(scope.user, coef, scope_orgs, org):
            continue
        if staffing.coefficient_out(coef)["state"] != "active":
            continue
        kind = norms.INSTITUTION_TYPES.get(coef.institution_type, coef.institution_type).lower()
        where = norms.SCOPE_LEVELS.get(coef.scope_level, coef.scope_level).lower()
        line = f"- {groups[coef.personnel_group_id].name} ({kind}, {where}): {norms.describe(coef)}"
        if coef.document is not None:
            document = coef.document
            line += f"; основание — {document.doc_type}" + (
                f" № {document.number}" if document.number else "")
        lines.append(line)
        if len(lines) >= MAX_NORMS:
            lines.append("- и другие, полный список на вкладке «Нормативы»")
            break
    return ["Действующие нормативы:", *lines] if lines else ["Действующих нормативов нет."]


def _requests(db: Session, scope: Scope, org: Organization | None) -> list[str]:
    query = (helpdesk.visible(scope)
             .where(IncomingRequest.topic.in_(staffing.STAFFING_TOPICS),
                    IncomingRequest.parent_id.is_(None))
             .options(selectinload(IncomingRequest.organization))
             .order_by(IncomingRequest.created_at.desc()).limit(MAX_REQUESTS))
    if org is not None:
        query = query.where(IncomingRequest.organization_id == org.id)
    items = list(db.scalars(query))
    if not items:
        return ["Кадровых заявок нет."]
    lines = ["Последние кадровые заявки:"]
    for r in items:
        topic = routing.TOPICS[r.topic].title if r.topic in routing.TOPICS else r.topic
        lines.append(f"- № {r.id} «{r.title}» — {topic}, {REQUEST_STATUS.get(r.status, r.status)}, "
                     f"{r.organization.name}, {r.created_at:%d.%m.%Y}")
    return lines


def build_context(scope: Scope, year: str, org: Organization | None) -> str:
    db = scope.db
    parts = [_who(scope, org), ""]
    if org is not None:
        parts += _institution(db, org, year)
    else:
        orgs = list(db.scalars(scope.organizations()
                               .options(selectinload(Organization.municipality))))
        parts += _territory(db, orgs, year)
    parts += ["", *_norms(db, scope, org), "", *_requests(db, scope, org)]
    return "\n".join(parts)


# --- разговор --------------------------------------------------------------------------


def chat_out(chat: AssistantChat, with_messages: bool = False) -> dict:
    result = {
        "id": chat.id, "title": chat.title, "year": chat.academic_year,
        "organization_id": chat.organization_id,
        "organization": chat.organization.name if chat.organization else None,
        "created_at": chat.created_at, "updated_at": chat.updated_at,
    }
    if with_messages:
        result["messages"] = [{"id": m.id, "role": m.role, "content": m.content,
                               "created_at": m.created_at} for m in chat.messages]
    return result


def title_from(question: str) -> str:
    text = " ".join(question.split())
    return text if len(text) <= 80 else text[:77].rstrip() + "…"


def answer(scope: Scope, chat: AssistantChat, question: str) -> str:
    """Ответ модели на вопрос с учётом справки и истории разговора."""
    if not llm.should_try():
        raise AssistantUnavailable(llm.status().get("error") or "Модель недоступна")
    context = build_context(scope, chat.academic_year, chat.organization)
    messages = [{"role": "system", "content": f"{RULES}\n\nСправка на сейчас:\n{context}"}]
    for message in chat.messages[-HISTORY:]:
        messages.append({"role": message.role, "content": message.content})
    messages.append({"role": "user", "content": question})
    try:
        return llm.complete(messages)
    except llm.LLMUnavailable as exc:
        raise AssistantUnavailable(str(exc)) from exc


def add_exchange(chat: AssistantChat, question: str, reply: str) -> None:
    chat.messages.append(AssistantMessage(role="user", content=question))
    chat.messages.append(AssistantMessage(role="assistant", content=reply))
