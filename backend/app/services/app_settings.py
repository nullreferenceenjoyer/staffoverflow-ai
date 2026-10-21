"""Настройки, которые меняют в интерфейсе. Пока одна группа — нормы загрузки хозслужбы."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import AppSetting

WORKLOAD_KEY = "workload"

# Нормы загрузки хозяйственного отдела и бригад. Условные — их настраивает управление
WORKLOAD_DEFAULTS: dict[str, float] = {
    # Сколько часов в день один сотрудник реально работает руками (без обеда, оформления)
    "hours_per_day": 6.0,
    # Нормальная загрузка: ниже — люди простаивают, выше — не успевают
    "target_load_pct": 80.0,
    # Средняя скорость в дороге, км/ч: из неё и расстояния — время на выезд
    "travel_speed_kmh": 30.0,
    # Сколько часов считать за заявку без оценки трудоёмкости
    "default_hours": 1.5,
    # Сколько человек оставить в бригаде или учреждении, даже если заявок почти нет
    "min_people": 1.0,
    # Какая часть времени хозотдела школы уходит на заявки. Остальное — плановые обходы,
    # сезонные и регламентные работы, их заявками не оформляют. У бригад — только заявки
    "requests_share_pct": 25.0,
}

WORKLOAD_TITLES: dict[str, str] = {
    "hours_per_day": "Рабочих часов в день на человека",
    "target_load_pct": "Нормальная загрузка, %",
    "travel_speed_kmh": "Скорость в дороге, км/ч",
    "default_hours": "Часов на заявку без оценки",
    "min_people": "Минимум людей в бригаде или учреждении",
    "requests_share_pct": "Доля времени хозотдела школы на заявки, %",
}


CLEANING_KEY = "cleaning"
# Норма уборщиц: на сколько классов и на сколько м² одна ставка. Условные — их задаёт
# управление образования. Нужно ставок = большее из «по классам» и «по площади»:
# убрать надо и все классы, и всю площадь
CLEANING_DEFAULTS: dict[str, float] = {"classes_per_rate": 3.0, "area_per_rate": 600.0}


def cleaning(db: Session) -> dict[str, float]:
    stored = db.get(AppSetting, CLEANING_KEY)
    values = dict(CLEANING_DEFAULTS)
    for key, value in ((stored.value or {}) if stored else {}).items():
        if key in values and isinstance(value, int | float) and value > 0:
            values[key] = float(value)
    return values


def save_cleaning(db: Session, values: dict[str, float]) -> dict[str, float]:
    stored = db.get(AppSetting, CLEANING_KEY)
    clean = {k: float(values[k]) for k in CLEANING_DEFAULTS if k in values}
    if stored is None:
        db.add(AppSetting(key=CLEANING_KEY, value=clean))
    else:
        stored.value = {**(stored.value or {}), **clean}
    db.flush()
    return cleaning(db)


def workload(db: Session) -> dict[str, float]:
    stored = db.get(AppSetting, WORKLOAD_KEY)
    values = dict(WORKLOAD_DEFAULTS)
    if stored is not None:
        for key, value in (stored.value or {}).items():
            if key in values and isinstance(value, int | float):
                values[key] = float(value)
    return values


def save_workload(db: Session, values: dict[str, float]) -> dict[str, float]:
    stored = db.get(AppSetting, WORKLOAD_KEY)
    clean = {key: float(values[key]) for key in WORKLOAD_DEFAULTS if key in values}
    if stored is None:
        db.add(AppSetting(key=WORKLOAD_KEY, value=clean))
    else:
        stored.value = {**(stored.value or {}), **clean}
    db.flush()
    return workload(db)
