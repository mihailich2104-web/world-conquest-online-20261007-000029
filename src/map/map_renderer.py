"""Рендер карты: кэш мировой поверхности + векторная отрисовка при приближении."""
from __future__ import annotations

import logging
import math
from typing import Optional

import pygame

from config import IDEOLOGY_COLORS, SETTINGS
from core.game_state import GameState
from .camera import WORLD_H, WORLD_W, Camera
from .province import Province, world_to_lonlat

log = logging.getLogger(__name__)
OCEAN = (22, 42, 72)
BORDER = (20, 24, 32)
VECTOR_ZOOM = 2.0        # выше этого масштаба рисуем полигоны напрямую (чётче)


def lighten(c: tuple[int, int, int], k: float = 0.35) -> tuple[int, int, int]:
    """Осветляет цвет на долю k."""
    return tuple(int(v + (255 - v) * k) for v in c)  # type: ignore[return-value]


class MapRenderer:
    """Рисует провинции, подсветку, подписи; определяет провинцию под курсором."""

    def __init__(self, provinces: list[Province], camera: Camera, font: pygame.font.Font) -> None:
        self.provs = provinces
        self.by_iso = {p.iso: p for p in provinces}
        self.cam = camera
        self.font = font
        self.world = pygame.Surface((int(WORLD_W), int(WORLD_H)))
        self._label_cache: dict[tuple[str, int], pygame.Surface] = {}
        self._badge_cache: dict[tuple[str, tuple[int, int, int], bool], pygame.Surface] = {}
        self.pulse = 0.0
        self.backdrop: Optional[pygame.Surface] = None

    # ---------- цвета ----------
    def color_of(self, iso: str, state: GameState) -> tuple[int, int, int]:
        """Цвет провинции: цвет владельца или цвет его идеологии."""
        owner = state.countries.get(state.owner.get(iso, iso))
        if owner is None:
            return (90, 90, 90)
        if SETTINGS.map_mode == "ideology":
            return IDEOLOGY_COLORS.get(owner.ideology, (150, 150, 150))
        return owner.color

    # ---------- кэш ----------
    def rebuild(self, state: GameState) -> None:
        """Перерисовывает кэш мировой поверхности (при смене владельцев/режима)."""
        self.world.fill(OCEAN)
        for p in self.provs:
            col = self.color_of(p.iso, state)
            for ring in p.wpolys:
                if len(ring) >= 3:
                    pygame.draw.polygon(self.world, col, ring)
                    pygame.draw.polygon(self.world, BORDER, ring, 1)
        state.map_dirty = False

    # ---------- рисование ----------
    def draw(self, screen: pygame.Surface, state: GameState, hover: Optional[str],
             selected: Optional[str], extra: tuple[str, ...] = ()) -> None:
        """Рисует карту в окно. extra — дополнительно подсвеченные провинции (туториал)."""
        if state.map_dirty:
            self.rebuild(state)
        cam = self.cam
        screen.fill(OCEAN)
        vx, vy, vw, vh = cam.view_rect()
        if cam.zoom < VECTOR_ZOOM:
            src = pygame.Rect(int(max(vx, 0)), int(max(vy, 0)), 0, 0)
            src.w = int(min(vx + vw, WORLD_W)) - src.x + 1
            src.h = int(min(vy + vh, WORLD_H)) - src.y + 1
            src.clamp_ip(self.world.get_rect())
            if src.w > 0 and src.h > 0:
                sub = self.world.subsurface(src)
                size = (max(1, int(src.w * cam.zoom)), max(1, int(src.h * cam.zoom)))
                screen.blit(pygame.transform.scale(sub, size), cam.world_to_screen(src.x, src.y))
        else:
            for p in self.provs:
                if self._visible(p):
                    col = self.color_of(p.iso, state)
                    for pts in self._screen_rings(p):
                        pygame.draw.polygon(screen, col, pts)
                        pygame.draw.polygon(screen, BORDER, pts, 1)
        for iso in extra:
            self._outline(screen, iso, (255, 215, 0), 3)
        if hover and hover in self.by_iso:
            self._fill_hover(screen, hover, state)
        if selected and selected in self.by_iso:
            self._outline(screen, selected, (255, 255, 255), 2)
        self._labels(screen, state)

    def _visible(self, p: Province) -> bool:
        """Пересекается ли рамка провинции с видимой областью."""
        vx, vy, vw, vh = self.cam.view_rect()
        b = p.wbbox
        return not (b[2] < vx or b[0] > vx + vw or b[3] < vy or b[1] > vy + vh)

    def _screen_rings(self, p: Province) -> list[list[tuple[float, float]]]:
        """Кольца провинции в экранных координатах (только крупные на экране)."""
        z, ox, oy = self.cam.zoom, self.cam.x, self.cam.y
        out = []
        for ring in p.wpolys:
            if len(ring) < 3:
                continue
            xs = [pt[0] for pt in ring]
            if (max(xs) - min(xs)) * z < 1.0:
                continue
            out.append([((x - ox) * z, (y - oy) * z) for x, y in ring])
        return out

    def _outline(self, screen: pygame.Surface, iso: str, color: tuple[int, int, int], w: int) -> None:
        """Контур провинции."""
        p = self.by_iso.get(iso)
        if p and self._visible(p):
            for pts in self._screen_rings(p):
                pygame.draw.polygon(screen, color, pts, w)

    def _fill_hover(self, screen: pygame.Surface, iso: str, state: GameState) -> None:
        """Подсветка наведения: светлая заливка."""
        p = self.by_iso[iso]
        if self._visible(p):
            col = lighten(self.color_of(iso, state))
            for pts in self._screen_rings(p):
                pygame.draw.polygon(screen, col, pts)
                pygame.draw.polygon(screen, (255, 255, 255), pts, 1)

    def _labels(self, screen: pygame.Surface, state: GameState) -> None:
        """Подписи стран, если они помещаются в рамку провинции на экране."""
        z = self.cam.zoom
        if z < 1.2:
            return
        for p in self.provs:
            if not self._visible(p):
                continue
            name = state.countries[state.owner[p.iso]].name if p.iso in state.owner else p.name
            key = (name, 0)
            surf = self._label_cache.get(key)
            if surf is None:
                surf = self.font.render(name, True, (15, 15, 15))
                self._label_cache[key] = surf
            if (p.wbbox[2] - p.wbbox[0]) * z < surf.get_width() + 6:
                continue
            sx, sy = self.cam.world_to_screen(*p.world_centroid)
            screen.blit(surf, (sx - surf.get_width() / 2, sy - surf.get_height() / 2))

    def draw_marker(self, screen: pygame.Surface, iso: str, dt: float) -> None:
        """Пульсирующий маркер в центре страны (для туториала/игрока)."""
        p = self.by_iso.get(iso)
        if not p:
            return
        self.pulse += dt * 4
        sx, sy = self.cam.world_to_screen(*p.world_centroid)
        r = 8 + 4 * math.sin(self.pulse)
        pygame.draw.circle(screen, (255, 215, 0), (int(sx), int(sy)), int(r), 3)
        pygame.draw.circle(screen, (255, 60, 60), (int(sx), int(sy)), 3)

    # ---------- армии, войны, фон меню ----------
    def _badge(self, text: str, color: tuple[int, int, int], war: bool) -> pygame.Surface:
        """Плашка армии: тёмный фон, рамка цвета страны (красная — в войне)."""
        key = (text, color, war)
        surf = self._badge_cache.get(key)
        if surf is None:
            t = self.font.render(text, True, (236, 238, 242))
            surf = pygame.Surface((t.get_width() + 10, t.get_height() + 4), pygame.SRCALPHA)
            surf.fill((18, 21, 26, 215))
            pygame.draw.rect(surf, (200, 70, 70) if war else color, surf.get_rect(), 2)
            surf.blit(t, (5, 2))
            self._badge_cache[key] = surf
        return surf

    def draw_overlays(self, screen: pygame.Surface, state: GameState, mine: Optional[str]) -> None:
        """Войны (линия фронта между главными противниками) и армии стран."""
        cam = self.cam
        for w in state.wars:
            a, d = self.by_iso.get(w.main_attacker), self.by_iso.get(w.main_defender)
            if a is None or d is None:
                continue
            ax, ay = cam.world_to_screen(*a.world_centroid)
            dx, dy = cam.world_to_screen(*d.world_centroid)
            pygame.draw.line(screen, (176, 64, 64), (ax, ay), (dx, dy), 2)
            f = (w.score + 100.0) / 200.0                       # положение фронта: 0 — у атакующего, 1 — у защитника
            fx, fy = ax + (dx - ax) * f, ay + (dy - ay) * f
            pygame.draw.circle(screen, (24, 26, 30), (int(fx), int(fy)), 8)
            pygame.draw.circle(screen, (226, 96, 96), (int(fx), int(fy)), 6)
            pygame.draw.circle(screen, (236, 238, 242), (int(fx), int(fy)), 8, 1)
        z = cam.zoom
        for c in state.countries.values():
            if not c.alive or c.army <= 0:
                continue
            p = self.by_iso.get(c.iso)
            if p is None or not self._visible(p):
                continue
            at_war = bool(c.at_war_with)
            if z < 1.3 and not at_war and c.iso != mine:
                continue
            sx, sy = cam.world_to_screen(*p.world_centroid)
            b = self._badge(str(c.army), c.color, at_war)
            screen.blit(b, (sx - b.get_width() / 2, sy + 6))

    def make_backdrop(self, size: tuple[int, int]) -> None:
        """Готовит затемнённый фон главного меню из мировой поверхности (один раз)."""
        w, h = size
        bw = int(h * (self.world.get_width() / self.world.get_height()))
        surf = pygame.transform.smoothscale(self.world, (max(bw, w), h))
        shade = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
        shade.fill((8, 10, 14, 150))
        surf.blit(shade, (0, 0))
        self.backdrop = surf

    def draw_backdrop(self, screen: pygame.Surface, t: float) -> None:
        """Рисует фон меню с медленным горизонтальным дрейфом."""
        if self.backdrop is None:
            screen.fill((16, 20, 28))
            return
        bw, w = self.backdrop.get_width(), screen.get_width()
        span = max(0, bw - w)
        off = int((math.sin(t * 0.05) * 0.5 + 0.5) * span)
        screen.blit(self.backdrop, (-off, 0))

    # ---------- выбор ----------
    def province_at(self, pos: tuple[int, int]) -> Optional[str]:
        """ISO провинции под экранной точкой (None — океан)."""
        wx, wy = self.cam.screen_to_world(*pos)
        lon, lat = world_to_lonlat(wx, wy)
        best: Optional[Province] = None
        for p in self.provs:
            if p.contains(lon, lat) and (best is None or p.area < best.area):
                best = p
        return best.iso if best else None
