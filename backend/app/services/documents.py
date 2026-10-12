"""Генерация документов по проекту: приказ, служебная записка, обоснование.

Структура документа и таблица изменений собираются из данных проекта кодом —
цифры в документ попадают без участия модели. LLM пишет только связный
вводный текст; если модель недоступна, подставляется шаблонный.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt

from app.config import get_settings
from app.models import GeneratedDocument, Project, User
from app.services import llm
from app.services.staffing import ru

log = logging.getLogger(__name__)

KINDS = {
    "order": "Проект приказа",
    "memo": "Служебная записка",
    "justification": "Обоснование изменений штатного расписания",
}

_INSTRUCTIONS = {
    "order": "Напиши преамбулу приказа об изменении штатного расписания: 2–3 предложения "
             "о цели и основаниях. Без слова «ПРИКАЗЫВАЮ» и без перечисления пунктов.",
    "memo": "Напиши текст служебной записки руководителю: суть предлагаемых изменений, "
            "ожидаемый эффект и что требуется от адресата. 2 абзаца.",
    "justification": "Напиши обоснование для комиссии: почему изменения нужны, на чём основан "
                     "расчёт, какие есть риски и как их снизить. 3 абзаца.",
}


def _money(value) -> str:
    return f"{float(value):,.0f}".replace(",", " ") + " ₽"


def _facts(project: Project) -> str:
    lines = [f"Проект: {project.title}.", project.summary or ""]
    for item in project.items[:25]:
        lines.append(
            f"- {item.organization_name}, {item.title}: было {ru(float(item.current_rate))} ст., "
            f"предлагается {ru(float(item.proposed_rate))} ст., изменение ФОТ за год "
            f"{_money(item.fot_effect_year)}."
        )
    lines.append(f"Итого изменение ставок: {ru(float(project.rate_delta))}, "
                 f"ФОТ за год: {_money(project.fot_effect_year)}.")
    return "\n".join(filter(None, lines))


def _template_narrative(project: Project, kind: str) -> str:
    staff = "сокращение" if project.rate_delta < 0 else "увеличение"
    fot = "сокращение" if project.fot_effect_year < 0 else "увеличение"
    base = (
        f"По результатам сопоставления фактического штатного расписания с расчётными "
        f"нормативами подготовлены предложения по {len(project.items)} позициям. "
        f"Итоговое {staff} численности — {ru(float(abs(project.rate_delta)))} ст., ожидаемое {fot} "
        f"фонда оплаты труда — {_money(abs(project.fot_effect_year))} в год."
    )
    if kind == "order":
        return ("В целях приведения штатной численности в соответствие с нормативами и "
                "повышения эффективности расходования фонда оплаты труда. " + base)
    if kind == "memo":
        return base + (" Прошу рассмотреть предложения и согласовать их вынесение "
                       "на утверждение.")
    return base + (" Расчёт выполнен по действующим в системе нормативам; формулы приведены "
                   "в таблице по каждой позиции. Изменения рекомендуется проводить поэтапно, "
                   "начиная с вакантных ставок.")


def write_narrative(project: Project, kind: str) -> tuple[str, bool]:
    """Возвращает текст и признак, что его написала модель."""
    messages = [
        {"role": "system", "content":
            "Ты готовишь официальные документы органа управления образованием. Пиши "
            "деловым стилем, без Markdown и заголовков. Используй только цифры из данных, "
            "не упоминай конкретных людей."},
        {"role": "user", "content": f"{_INSTRUCTIONS[kind]}\n\nДанные:\n{_facts(project)}"},
    ]
    try:
        # В данных только учреждения и ставки, персональных сведений нет,
        # поэтому запрос можно отдать облачной модели, если она разрешена
        return llm.complete(messages, sensitive=False, max_tokens=600), True
    except llm.LLMUnavailable as exc:
        log.info("Narrative falls back to template: %s", exc)
        return _template_narrative(project, kind), False


def _add_items_table(document, project: Project) -> None:
    table = document.add_table(rows=1, cols=6)
    table.style = "Table Grid"
    headers = ("Учреждение / центр", "Функция", "Было, ст.", "Станет, ст.",
               "ФОТ за год", "Обоснование")
    for cell, text in zip(table.rows[0].cells, headers, strict=True):
        cell.text = text
        cell.paragraphs[0].runs[0].bold = True
    for item in project.items:
        row = table.add_row().cells
        values = (item.organization_name, item.title, ru(float(item.current_rate)),
                  ru(float(item.proposed_rate)), _money(item.fot_effect_year), item.reason)
        for cell, text in zip(row, values, strict=True):
            cell.text = text
    for row in table.rows:
        for cell in row.cells:
            for paragraph in cell.paragraphs:
                for run in paragraph.runs:
                    run.font.size = Pt(9)


def render_docx(project: Project, kind: str, narrative: str, path: Path) -> None:
    document = Document()
    document.styles["Normal"].font.name = "Times New Roman"
    document.styles["Normal"].font.size = Pt(12)

    mark = document.add_paragraph("ПРОЕКТ")
    mark.alignment = WD_ALIGN_PARAGRAPH.RIGHT

    if kind == "order":
        heading = document.add_paragraph()
        heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
        heading.add_run("ПРИКАЗ").bold = True
        document.add_paragraph(f"от «___» __________ {date.today().year} г.  № ____")
        document.add_paragraph().add_run("О внесении изменений в штатное расписание").bold = True
        for paragraph in narrative.split("\n"):
            if paragraph.strip():
                document.add_paragraph(paragraph.strip())
        document.add_paragraph("ПРИКАЗЫВАЮ:")
        document.add_paragraph("1. Внести в штатное расписание изменения согласно приложению.")
        document.add_paragraph("2. Руководителям учреждений провести предусмотренные трудовым "
                               "законодательством процедуры и уведомить работников в "
                               "установленные сроки.")
        document.add_paragraph("3. Контроль за исполнением приказа оставляю за собой.")
        document.add_paragraph("\nРуководитель ____________________ / ____________________")
        document.add_page_break()
        document.add_paragraph("Приложение. Изменения штатного расписания").runs[0].bold = True
    else:
        heading = document.add_paragraph()
        heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
        heading.add_run(KINDS[kind].upper()).bold = True
        document.add_paragraph(project.title).alignment = WD_ALIGN_PARAGRAPH.CENTER
        for paragraph in narrative.split("\n"):
            if paragraph.strip():
                document.add_paragraph(paragraph.strip())

    _add_items_table(document, project)
    document.add_paragraph(
        f"\nИтого: изменение численности {ru(float(project.rate_delta))} ст., "
        f"изменение ФОТ {_money(project.fot_effect_year)} в год (с начислениями)."
    )
    note = document.add_paragraph(
        "Документ сформирован автоматически по данным системы и требует проверки "
        "ответственным специалистом."
    )
    note.runs[0].italic = True
    note.runs[0].font.size = Pt(9)

    path.parent.mkdir(parents=True, exist_ok=True)
    document.save(path)


def generate(project: Project, kind: str, author: User) -> GeneratedDocument:
    narrative, by_llm = write_narrative(project, kind)
    relative = Path("documents") / f"{project.id}-{kind}-{uuid.uuid4().hex[:8]}.docx"
    render_docx(project, kind, narrative, Path(get_settings().storage_dir) / relative)
    return GeneratedDocument(
        project_id=project.id,
        kind=kind,
        title=f"{KINDS[kind]}: {project.title}",
        narrative=narrative,
        file_path=relative.as_posix(),
        written_by_llm=by_llm,
        created_by_id=author.id,
    )
