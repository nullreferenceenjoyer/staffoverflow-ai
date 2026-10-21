"""Разъяснения по высвобождению ставок: почему, откуда цифра, как и что дальше с людьми.

Модель отвечает по короткой справке — только то, что относится к вопросу: итог по
округу, разбивка по школе и должности, порядок высвобождения и общие нормы ТК РФ.
Справка маленькая специально: на локальной модели каждый лишний абзац — секунды до
первого слова. Уже уволенные в справку не попадают — расчёт показывает, что нужно
высвободить, а не историю увольнений.
"""

from __future__ import annotations

import time
from threading import Lock

from sqlalchemy.orm import Session

from app.models import Organization
from app.services import norms, program, summary

HISTORY = 6
CACHE_SECONDS = 60
MAX_TOKENS = 450
MAX_SCHOOLS = 10
MAX_POSITIONS = 10

RULES = """Ты объясняешь сотруднику школы или управления образования, почему в штатке
высвобождаются ставки. Пиши по-русски, просто и коротко: до 6–8 предложений или короткий
список. На вопрос о должности или человеке отвечай по схеме: «Почему» — «Откуда это берётся» —
«Как это делается» — «Что дальше с сотрудником». Опирайся только на справку, не выдумывай
цифр, фамилий и документов; если нужного нет — так и скажи. Называй, из каких частей
складывается высвобождение; если сокращать занятые ставки не нужно — скажи, что людей
не увольняют. Это расчёт на будущее: пиши «нужно высвободить», «предстоит», а не
«сократили» или «уволены». Итоговые цифры по округу называй, только если о них спросили.
Не путай: высвобождают ставки там, где их больше норматива, а не там, где людей не хватает.

Порядок высвобождения:
1. Вакансии — ставки никем не заняты и по нормативу не нужны; их исключают из штатки
   приказом, людей это не касается.
2. Совмещение — сотрудник работает больше чем на ставку; он остаётся на основной ставке,
   снимается доплата (работодатель предупреждает письменно за 3 рабочих дня, ст. 60.2 ТК РФ).
3. Сокращение занятых ставок — только остаток; решение принимает руководитель.

При сокращении (ТК РФ, детали — в кадровой службе): уведомление под подпись за 2 месяца
(ст. 180), предложение всех подходящих вакансий в той же местности (ст. 81, 180),
преимущественное право остаться (ст. 179), выходное пособие и сохранение среднего
заработка на время трудоустройства, обычно до двух месяцев (ст. 178).
Куда перейти: на вакансию в своей или другой школе округа; вспомогательный персонал —
в обслуживающие бригады образовательных комплексов."""


def _n(value) -> str:
    return norms.num(value)


def _parts(vacant: float, load: float, cut: float) -> str:
    """Из чего складывается цифра — словами, чтобы модель не перепутала части."""
    people = (f"сократить занятые ставки {_n(cut)} — это люди" if cut
              else "сокращать занятые ставки не нужно — людей не увольняют")
    return (f"вакансии {_n(vacant)} — людей не касается; снять совмещение {_n(load)} — "
            f"люди остаются на своей ставке; {people}")


def _headline(data: dict, plan: dict | None) -> list[str]:
    h = data["headline"]
    units = (plan or {}).get("staff_units") or round(h["cut"])
    lines = [
        f"Высвободить всего {_n(h['total'])} ставки в {h['schools_with_cut']} школах: "
        f"убрать вакансии — {_n(h['cut_vacant'])}, снять совмещение — {_n(h['reduce_load'])}, "
        f"сократить занятые ставки — {_n(h['cut'])} (это {units} штатных единиц).",
    ]
    if h["cost"]:
        lines.append(f"Экономия фонда оплаты труда — около {_n(round(h['cost'] / 1e6, 1))} млн ₽ "
                     f"в год" + (f" ({_n(h['saving_pct'])} % ФОТ)." if h["saving_pct"] else "."))
    if plan and plan.get("basis"):
        lines.append(f"Основание расчёта: {plan['basis']}.")
    return lines


def _school(data: dict, position: str | None) -> list[str]:
    lines = []
    for g in data["groups"]:
        if position and position.lower() not in g["group"].lower():
            continue
        total = (g["cut_vacant"] or 0) + (g["reduce_load"] or 0) + (g["cut"] or 0)
        if not total and not position:
            continue
        text = (f"- {g['group']}: по штатке {_n(g['approved'])}, занято {_n(g['occupied'])}, "
                f"по нормативу нужно {_n(g['required'])}")
        if total:
            text += (f"; высвободить {_n(total)}: "
                     f"{_parts(g['cut_vacant'] or 0, g['reduce_load'] or 0, g['cut'] or 0)}")
        else:
            text += "; лишних ставок нет"
        why = [w for w in g["why"] if "уволен" not in w.lower() and "ушл" not in w.lower()]
        if why:
            text += f". Расчёт: {'; '.join(why[:3])}"
        lines.append(text)
        if len(lines) >= MAX_POSITIONS:
            break
    return lines


def _territory(data: dict, position: str | None) -> list[str]:
    lines = []
    # Вопрос про должность: список школ только удлинил бы справку
    for s in [] if position else data["schools"][:MAX_SCHOOLS]:
        if not lines:
            lines.append("Где больше всего:")
        if not s["total"]:
            break
        lines.append(f"- {s['organization']}: {_n(s['total'])} — "
                     f"{_parts(s['cut_vacant'], s['reduce_load'], s['cut'])}")
    positions = data["positions"]
    if position:
        positions = [p for p in positions if position.lower() in p["position"].lower()]
    lines.append("По должностям:")
    for p in positions[:MAX_POSITIONS]:
        lines.append(f"- {p['position']}: было {_n(p['approved'])}, станет {_n(p['after'])}, "
                     f"высвободить {_n(p['total'])}: "
                     f"{_parts(p['cut_vacant'], p['reduce_load'], p['cut'])}")
    return lines


_cache: dict[tuple, tuple[float, str]] = {}
_lock = Lock()


def context(db: Session, orgs: list[Organization], org: Organization | None,
            position: str | None, year: str) -> str:
    """Справка для модели. Одна и та же минуту: тогда и сервер модели берёт её из своего
    кеша, а не читает заново — ответ начинается быстрее."""
    key = (tuple(sorted(o.id for o in orgs)), org.id if org else None, position or "", year)
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_SECONDS:
            return hit[1]
    text = _context(db, orgs, org, position, year)
    with _lock:
        _cache[key] = (now, text)
        for stale in [k for k, (t, _) in _cache.items() if now - t > CACHE_SECONDS]:
            del _cache[stale]
    return text


def _context(db: Session, orgs: list[Organization], org: Organization | None,
             position: str | None, year: str) -> str:
    plan = program.summary(db)
    territory = org is None
    data = summary.build(db, [org] if org else orgs, year, 90, territory=territory)
    parts = [*_headline(data, plan if territory else None), ""]
    if org is not None:
        parts.append(f"Школа «{org.name}»:")
        parts += _school(data, position) or ["- по этой школе высвобождать нечего"]
    else:
        parts += _territory(data, position)
    return "\n".join(parts)


def messages(db: Session, orgs: list[Organization], org: Organization | None,
             question: str, position: str | None, history: list[dict], year: str) -> list[dict]:
    out = [{"role": "system",
            "content": f"{RULES}\n\nСправка:\n{context(db, orgs, org, position, year)}"}]
    for item in history[-HISTORY:]:
        if item.get("role") in ("user", "assistant") and item.get("content"):
            out.append({"role": item["role"], "content": str(item["content"])[:2000]})
    out.append({"role": "user", "content": question})
    return out
