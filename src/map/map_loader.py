"""Загрузка карты: GeoJSON (чистый json), граф соседей, запасная карта."""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any, Iterator

from config import NON_PLAYABLE, PROVINCES_PATH
from .province import Province, Ring

log = logging.getLogger(__name__)
CELL = 0.4  # размер ячейки (градусы) для поиска общих границ


def _polys_from_geojson_geom(geom: dict[str, Any]) -> list[Ring]:
    """Внешние кольца полигонов из GeoJSON-геометрии."""
    if geom["type"] == "Polygon":
        return [[(p[0], p[1]) for p in geom["coordinates"][0]]]
    if geom["type"] == "MultiPolygon":
        return [[(p[0], p[1]) for p in poly[0]] for poly in geom["coordinates"]]
    return []


def _iter_features(path: Path) -> Iterator[tuple[dict[str, Any], list[Ring]]]:
    """Читает признаки GeoJSON напрямую через json (GeoPandas не нужен)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    for f in data["features"]:
        yield f["properties"], _polys_from_geojson_geom(f["geometry"])


def load_provinces(path: Path = PROVINCES_PATH) -> list[Province]:
    """Загружает провинции из provinces.geojson (без Антарктики и т.п.)."""
    provs: dict[str, Province] = {}
    for props, rings in _iter_features(path):
        iso = str(props["iso"])
        if iso in NON_PLAYABLE or not rings:
            continue
        if iso in provs:                      # дубликаты ISO — объединяем геометрию
            provs[iso].polygons.extend(rings)
        else:
            provs[iso] = Province(iso, str(props["name"]), str(props.get("continent", "")), rings)
    return [p.finalize() for p in provs.values()]


def build_adjacency(provs: list[Province]) -> dict[str, list[str]]:
    """Соседи = провинции, чьи вершины лежат в соседних ячейках сетки (общая граница)."""
    cells: dict[tuple[int, int], set[str]] = {}
    for p in provs:
        for ring in p.polygons:
            for lon, lat in ring:
                cells.setdefault((int(math.floor(lon / CELL)), int(math.floor(lat / CELL))), set()).add(p.iso)
    adj: dict[str, set[str]] = {p.iso: set() for p in provs}
    for p in provs:
        for ring in p.polygons:
            for lon, lat in ring:
                cx, cy = int(math.floor(lon / CELL)), int(math.floor(lat / CELL))
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        adj[p.iso] |= cells.get((cx + dx, cy + dy), set())
        adj[p.iso].discard(p.iso)
    return {k: sorted(v) for k, v in adj.items()}


def build_fallback(countries: list[dict[str, Any]]) -> list[Province]:
    """Запасная карта-сетка: используется, если provinces.geojson не создан."""
    cols = 16
    rows = math.ceil(len(countries) / cols)
    w, h = 360.0 / cols, 140.0 / rows
    out = []
    for i, c in enumerate(countries):
        x0, y1 = -180 + (i % cols) * w, 80 - (i // cols) * h
        ring: Ring = [(x0, y1), (x0 + w, y1), (x0 + w, y1 - h), (x0, y1 - h), (x0, y1)]
        out.append(Province(c["iso"], c["name"], c.get("continent", ""), [ring]).finalize())
    log.warning("provinces.geojson не найден — использую запасную карту-сетку "
                "(запустите tools/prepare_map.py)")
    return out


def load_world(countries: list[dict[str, Any]]) -> tuple[list[Province], dict[str, list[str]], bool]:
    """Возвращает (провинции, смежность, is_fallback)."""
    try:
        provs = load_provinces()
        if not provs:
            raise ValueError("пустая карта")
        fallback = False
    except (OSError, ValueError, KeyError):
        log.exception("Не удалось загрузить карту")
        provs, fallback = build_fallback(countries), True
    return provs, build_adjacency(provs), fallback
