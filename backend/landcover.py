"""What covers the ground at a point, seen from space: water, buildings, ice, crops... (10 m, worldwide).

Source: Impact Observatory / Microsoft / Esri "Sentinel-2 10m Land Use/Land Cover" time series
(2017-2025), read through its public ArcGIS ImageServer (getSamples). One request samples the point
and two rings around it (about 30 m and 100 m), so a decision does not hang on one 10 m pixel and the
app can tell "inside a lake" from "on the shore".

This replaces guessing from map labels for the cases that matter most: OpenStreetMap reverse geocoding
returns the NEAREST labelled object, so a point in the middle of a reservoir or in a hospital yard can
come back as "a road nearby". The satellite pixel has no such problem.

Classes (Impact Observatory legend):
  1 water   2 trees   4 flooded vegetation   5 crops   7 built area   8 bare ground
  9 snow/ice   10 clouds   11 rangeland
A point the service has no pixel for is reported as "nodata": that is open sea (the land cover is mapped
over land and inland water). When none of the points has a pixel the service answers HTTP 400; that is
also "nodata". Whether "nodata" means sea is decided together with OpenStreetMap (no address there).
"""
from __future__ import annotations

import json
import math
import threading
import time

import httpx

URL = ("https://ic.imagery1.arcgis.com/arcgis/rest/services/"
       "Sentinel2_10m_LandCover/ImageServer/getSamples")
TIMEOUT_S = 6
CACHE_TTL_S = 7 * 24 * 3600
CLASSES = {1: "water", 2: "trees", 4: "flooded_vegetation", 5: "crops", 7: "built", 8: "bare",
           9: "snow_ice", 10: "clouds", 11: "rangeland"}
RINGS_M = (30, 100)
RING_POINTS = 8

_client = httpx.Client(timeout=TIMEOUT_S, headers={"User-Agent": "field-shift-app"})
_cache: dict[tuple, tuple[float, dict | None]] = {}
_lock = threading.Lock()


class LandCoverDown(Exception):
    pass


def _points(lat: float, lon: float) -> list[tuple[float, float]]:
    """The point, then RING_POINTS points on each ring (lon, lat)."""
    pts = [(lon, lat)]
    m_lat = 111_320.0
    m_lon = max(1.0, 111_320.0 * math.cos(math.radians(lat)))
    for r in RINGS_M:
        for k in range(RING_POINTS):
            a = 2 * math.pi * k / RING_POINTS
            pts.append((lon + r * math.sin(a) / m_lon, lat + r * math.cos(a) / m_lat))
    return pts


def sample(lat: float, lon: float) -> dict:
    """-> {"center": class name or "nodata", "near": {class: count} (30 m ring), "around": {class: count} (100 m),
           "source": ...}. Raises LandCoverDown when the service does not answer."""
    key = (round(lat, 5), round(lon, 5))
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < CACHE_TTL_S:
            return hit[1]
    pts = _points(lat, lon)
    geometry = {"points": [[round(x, 7), round(y, 7)] for x, y in pts], "spatialReference": {"wkid": 4326}}
    try:
        r = _client.post(URL, data={"geometry": json.dumps(geometry), "geometryType": "esriGeometryMultipoint",
                                    "returnFirstValueOnly": "true", "f": "json"})
        r.raise_for_status()
        body = r.json()
        values: dict[int, str] = {}
        if "error" in body:
            err = body["error"]
            if not (isinstance(err, dict) and err.get("code") == 400 and "input" in str(err.get("message", "")).lower()):
                raise ValueError(str(err)[:80])
            body = {"samples": []}   # no point has a pixel: open sea
        for s in body.get("samples", []):
            try:
                values[int(s["locationId"])] = CLASSES.get(int(float(s["value"])), "unknown")
            except (KeyError, TypeError, ValueError):
                continue
    except (httpx.HTTPError, ValueError) as exc:
        raise LandCoverDown(f"land cover: {type(exc).__name__}") from exc

    def ring(i0: int) -> dict:
        counts: dict[str, int] = {}
        for i in range(i0, i0 + RING_POINTS):
            name = values.get(i, "nodata")
            counts[name] = counts.get(name, 0) + 1
        return counts

    result = {
        "center": values.get(0, "nodata"),
        "near": ring(1),
        "around": ring(1 + RING_POINTS),
        "source": "Sentinel-2 10 m land cover (Impact Observatory, Microsoft, Esri)",
    }
    with _lock:
        if len(_cache) > 5000:
            _cache.clear()
        _cache[key] = (time.time(), result)
    return result
