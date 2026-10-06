"""Провинция карты: геометрия страны в градусах и в мировых пикселях."""
from __future__ import annotations

from dataclasses import dataclass, field

from config import MAP_SCALE

Ring = list[tuple[float, float]]


def lonlat_to_world(lon: float, lat: float) -> tuple[float, float]:
    """Равнопромежуточная проекция: (lon, lat) → мировые пиксели."""
    return (lon + 180.0) * MAP_SCALE, (90.0 - lat) * MAP_SCALE


def world_to_lonlat(x: float, y: float) -> tuple[float, float]:
    """Обратная проекция: мировые пиксели → (lon, lat)."""
    return x / MAP_SCALE - 180.0, 90.0 - y / MAP_SCALE


def ring_area(ring: Ring) -> float:
    """Площадь кольца (формула шнурования), всегда ≥ 0."""
    s = 0.0
    for i in range(len(ring)):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % len(ring)]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def ring_centroid(ring: Ring) -> tuple[float, float]:
    """Центр масс кольца; для вырожденных колец — среднее вершин."""
    a = cx = cy = 0.0
    for i in range(len(ring)):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % len(ring)]
        cr = x1 * y2 - x2 * y1
        a += cr
        cx += (x1 + x2) * cr
        cy += (y1 + y2) * cr
    if abs(a) < 1e-12:
        n = len(ring)
        return sum(p[0] for p in ring) / n, sum(p[1] for p in ring) / n
    return cx / (3 * a), cy / (3 * a)


def point_in_ring(x: float, y: float, ring: Ring) -> bool:
    """Алгоритм луча: лежит ли точка внутри кольца."""
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi + 1e-18) + xi:
            inside = not inside
        j = i
    return inside


@dataclass
class Province:
    """Провинция = страна на карте 110m (мультиполигон без дыр)."""
    iso: str
    name: str
    continent: str
    polygons: list[Ring]
    wpolys: list[Ring] = field(default_factory=list)     # мировые пиксели
    bbox: tuple[float, float, float, float] = (0, 0, 0, 0)  # lon/lat
    wbbox: tuple[float, float, float, float] = (0, 0, 0, 0)  # мировые пиксели
    centroid: tuple[float, float] = (0.0, 0.0)               # lon/lat крупнейшей части
    area: float = 0.0

    def finalize(self) -> "Province":
        """Считает проекцию, рамки, центроид и площадь."""
        pts = [p for r in self.polygons for p in r]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        self.bbox = (min(xs), min(ys), max(xs), max(ys))
        self.wpolys = [[lonlat_to_world(lo, la) for lo, la in r] for r in self.polygons]
        wx, wy = [p[0] for r in self.wpolys for p in r], [p[1] for r in self.wpolys for p in r]
        self.wbbox = (min(wx), min(wy), max(wx), max(wy))
        biggest = max(self.polygons, key=ring_area)
        self.area = sum(ring_area(r) for r in self.polygons)
        self.centroid = ring_centroid(biggest)
        return self

    def contains(self, lon: float, lat: float) -> bool:
        """Попадает ли точка (lon, lat) в провинцию."""
        b = self.bbox
        if not (b[0] <= lon <= b[2] and b[1] <= lat <= b[3]):
            return False
        return any(point_in_ring(lon, lat, r) for r in self.polygons)

    @property
    def world_centroid(self) -> tuple[float, float]:
        """Центроид в мировых пикселях."""
        return lonlat_to_world(*self.centroid)
