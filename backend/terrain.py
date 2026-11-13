"""Terrain of a field from NASA SRTM (30 m): height, slope, which way it faces, and what that means.

Source: NASA Shuttle Radar Topography Mission, SRTMGL1 (1 arc-second, about 30 m), read point-wise
through the public OpenTopoData API (dataset "srtm30m"; at most 1 request per second and 1000 a day,
so every answer is kept on disk). One request samples the point and its 8 neighbours 60 m away; slope
and aspect come from the 3x3 window (Horn's method). SRTM heights are whole metres with a few metres of
noise, so the 60 m spacing keeps a flat field from showing a false slope of several percent.

Slope classes follow the usual soil-conservation breakpoints (USDA NRCS / FAO):
  < 2 %    flat: little runoff, but watch drainage
  2-6 %    gentle: some erosion on bare soil -> keep residue, contour rows
  6-12 %   moderate: erosion likely on bare soil -> cover crops, perennials in the rotation
  12-20 %  strong: field crops only with terraces or strips
  > 20 %   steep: not for annual field crops (pasture, orchards on terraces)
"""
from __future__ import annotations

import json
import math
import threading
import time
from pathlib import Path

import httpx

URL = "https://api.opentopodata.org/v1/srtm30m"
STEP_M = 60.0
MIN_INTERVAL_S = 1.1
CACHE_FILE = Path(__file__).parent / "cache" / "terrain.json"
CLASSES = ((2, "flat"), (6, "gentle"), (12, "moderate"), (20, "strong"), (1e9, "steep"))

_client = httpx.Client(timeout=8, headers={"User-Agent": "field-shift-app"})
_cache: dict[str, dict] | None = None
_lock = threading.Lock()
_rate_lock = threading.Lock()
_last_call = 0.0


class TerrainDown(Exception):
    pass


def _grid(lat: float, lon: float) -> list[tuple[float, float]]:
    """3x3 points, row by row from the north-west, STEP_M apart."""
    dlat = STEP_M / 110_540
    dlon = STEP_M / (111_320 * max(0.01, math.cos(math.radians(lat))))
    return [(lat + r * dlat, lon + c * dlon) for r in (1, 0, -1) for c in (-1, 0, 1)]


def slope_aspect(z: list[float]) -> tuple[float, float]:
    """Horn (1981) on a 3x3 window (row-major from the north-west): slope in %, aspect in degrees from north."""
    a, b, c, d, _e, f, g, h, i = z
    dzdx = ((c + 2 * f + i) - (a + 2 * d + g)) / (8 * STEP_M)
    dzdy = ((g + 2 * h + i) - (a + 2 * b + c)) / (8 * STEP_M)   # positive: height rises to the south
    slope = 100 * math.hypot(dzdx, dzdy)
    aspect = (math.degrees(math.atan2(-dzdx, dzdy)) + 360) % 360 if slope > 0.1 else None
    return slope, aspect


def slope_class(slope_pct: float) -> str:
    return next(name for limit, name in CLASSES if slope_pct < limit)


def sample(lat: float, lon: float) -> dict:
    """-> {"elevation_m", "slope_pct", "slope_deg", "aspect_deg", "class", "relief_m", "source"}"""
    global _cache
    key = f"{round(lat, 4)}_{round(lon, 4)}"
    with _lock:
        if _cache is None:
            try:
                _cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                _cache = {}
        if key in _cache:
            return _cache[key]
    pts = _grid(lat, lon)
    global _last_call
    with _rate_lock:
        wait = MIN_INTERVAL_S - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()
    try:
        r = _client.get(URL, params={"locations": "|".join(f"{y:.6f},{x:.6f}" for y, x in pts)})
        r.raise_for_status()
        z = [p["elevation"] for p in r.json()["results"]]
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise TerrainDown(f"SRTM: {type(exc).__name__}") from exc
    if any(v is None for v in z):           # sea or a data hole
        result = {"elevation_m": z[4], "slope_pct": None, "slope_deg": None, "aspect_deg": None,
                  "class": None, "relief_m": None, "source": "NASA SRTM 30 m"}
    else:
        slope, aspect = slope_aspect(z)
        result = {"elevation_m": round(z[4], 1), "slope_pct": round(slope, 1),
                  "slope_deg": round(math.degrees(math.atan(slope / 100)), 1),
                  "aspect_deg": round(aspect) if aspect is not None else None,
                  "class": slope_class(slope), "relief_m": round(max(z) - min(z), 1), "source": "NASA SRTM 30 m"}
    with _lock:
        _cache[key] = result
        try:
            CACHE_FILE.parent.mkdir(exist_ok=True)
            CACHE_FILE.write_text(json.dumps(_cache), encoding="utf-8")
        except OSError:
            pass
    return result
