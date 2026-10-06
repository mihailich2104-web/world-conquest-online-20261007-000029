"""Готовит src/data/provinces.geojson (Natural Earth 110m Admin 0 Countries).

Работает только на стандартной библиотеке. Если файл уже существует — ничего не делает
(принудительно перезагрузить: `python tools/prepare_map.py --force`).
"""
from __future__ import annotations

import json
import logging
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from config import PROVINCES_PATH  # noqa: E402

URLS = [
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_admin_0_countries.geojson",
    "https://naturalearth.s3.amazonaws.com/110m_cultural/ne_110m_admin_0_countries.geojson",
]
log = logging.getLogger("prepare_map")


def download() -> dict:
    """Скачивает GeoJSON, пробуя зеркала по очереди."""
    last: Exception | None = None
    for url in URLS:
        try:
            log.info("Загрузка %s", url)
            req = urllib.request.Request(url, headers={"User-Agent": "world-conquest/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as exc:  # сеть/формат: пробуем следующее зеркало
            last = exc
            log.warning("Не удалось: %s", exc)
    raise RuntimeError(f"Natural Earth недоступен: {last}")


def main() -> None:
    """Формирует упрощённый GeoJSON с полями iso, name, continent."""
    logging.basicConfig(level=logging.INFO)
    if PROVINCES_PATH.exists() and "--force" not in sys.argv:
        log.info("%s уже есть — пропускаю", PROVINCES_PATH)
        return
    try:
        src = download()
    except Exception:
        log.exception("Не удалось получить данные Natural Earth")
        raise SystemExit(1)
    feats = []
    for f in src["features"]:
        p = f["properties"]
        props = {k.upper(): v for k, v in p.items()}
        iso = props.get("ISO_A3")
        if iso in (None, "-99"):
            iso = props.get("ADM0_A3") or props.get("ISO_A3_EH")
        if not f.get("geometry") or not iso:
            continue
        feats.append({"type": "Feature",
                      "properties": {"iso": iso, "name": props.get("NAME"),
                                     "continent": props.get("CONTINENT")},
                      "geometry": f["geometry"]})
    PROVINCES_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROVINCES_PATH.write_text(json.dumps({"type": "FeatureCollection", "features": feats},
                                         ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log.info("Сохранено %d стран → %s", len(feats), PROVINCES_PATH)


if __name__ == "__main__":
    main()
