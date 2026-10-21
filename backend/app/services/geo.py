"""Расстояния между учреждениями и базами бригад.

Считается по прямой: дорог и рек система не знает, поэтому это подсказка
для закрепления школ, а не маршрут.
"""

from __future__ import annotations

import math


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Расстояние по поверхности Земли (формула гаверсинусов)."""
    radius = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def point(obj) -> tuple[float, float] | None:
    """Координаты объекта с полями latitude/longitude или None, если их нет."""
    if obj.latitude is None or obj.longitude is None:
        return None
    return float(obj.latitude), float(obj.longitude)


def km_between(a, b) -> float | None:
    """Расстояние между двумя объектами с координатами; None — у кого-то их нет."""
    here, there = point(a), point(b)
    if here is None or there is None:
        return None
    return distance_km(*here, *there)
