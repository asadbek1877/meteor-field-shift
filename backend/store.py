"""Cache of NASA POWER responses: memory first, then gzip files in backend/cache/.

Files in backend/cache/ are committed to git, so the demo works even when
NASA POWER is down. Only raw NASA data is stored; analysis is always recomputed.
"""
from __future__ import annotations

import gzip
import json
import math
from pathlib import Path

CACHE_DIR = Path(__file__).parent / "cache"
_memory: dict[str, dict] = {}


def _key(lat: float, lon: float) -> str:
    # 0.1 degree is about 10 km; the NASA grid cell is about 50 km wide.
    return f"{round(lat, 1):.1f}_{round(lon, 1):.1f}"


def load_all() -> int:
    """Read every cached file into memory. Called once at startup."""
    CACHE_DIR.mkdir(exist_ok=True)
    for path in CACHE_DIR.glob("*.json.gz"):
        try:
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data.get("params", {}).get("T2M"), list):
                _memory[path.name.removesuffix(".json.gz")] = data
        except (OSError, ValueError, EOFError):
            continue
    return len(_memory)


def get(lat: float, lon: float) -> dict | None:
    return _memory.get(_key(lat, lon))


def put(data: dict) -> None:
    key = _key(data["lat"], data["lon"])
    _memory[key] = data
    try:
        CACHE_DIR.mkdir(exist_ok=True)
        with gzip.open(CACHE_DIR / f"{key}.json.gz", "wt", encoding="utf-8") as fh:
            json.dump(data, fh, separators=(",", ":"))
    except OSError:
        pass  # read-only disk on some hosts: memory cache still works


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance (haversine)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def nearest(lat: float, lon: float) -> tuple[dict, float] | None:
    """Closest cached point and its distance in km."""
    best = None
    for data in _memory.values():
        d = distance_km(lat, lon, data["lat"], data["lon"])
        if best is None or d < best[1]:
            best = (data, d)
    return best
