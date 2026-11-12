"""Place search and land cover of a point, from OpenStreetMap.

search()      place name -> places with centre, bounding box and outline (Nominatim, Photon as backup)
land_cover()  point -> what OpenStreetMap says is exactly there: building, road, water, farmland...

Nominatim usage policy: at most 1 request per second, a real User-Agent, and no
search-as-you-type. The site therefore searches only when the user submits, and
this module spaces requests and caches results.
"""
from __future__ import annotations

import json
import math
import threading
import time
from pathlib import Path

import httpx

NOMINATIM = "https://nominatim.openstreetmap.org"
PHOTON = "https://photon.komoot.io/api/"
USER_AGENT = "TerraShift/1.0 (NASA Space Apps 2026 field analysis demo)"
TIMEOUT_S = 8
ROAD_BUFFER_M = 12  # a point this close to a building edge or road line counts as "on it"
URBAN_BUFFER_M = 60  # a town address with a building or road this close counts as built-up land

_client = httpx.Client(timeout=TIMEOUT_S, headers={"User-Agent": USER_AGENT})
_rate_lock = threading.Lock()
_last_call = 0.0
_search_cache: dict[tuple, list] = {}
_cover_cache: dict[tuple, dict] = {}


class GeoDown(Exception):
    pass


def _nominatim(path: str, params: dict) -> dict | list:
    """One Nominatim request, never faster than 1 per second across the server."""
    global _last_call
    with _rate_lock:
        wait = 1.05 - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()
    try:
        r = _client.get(f"{NOMINATIM}/{path}", params={**params, "format": "jsonv2"})
        r.raise_for_status()
        return r.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise GeoDown(f"Nominatim: {type(exc).__name__}") from exc


# ---------- search ----------

def _bbox(raw) -> list[float] | None:
    """Nominatim boundingbox [south, north, west, east] (strings) -> [south, west, north, east]."""
    try:
        s, n, w, e = (float(v) for v in raw)
        return [s, w, n, e]
    except (TypeError, ValueError):
        return None


def search(q: str, lang: str = "en", limit: int = 5) -> list[dict]:
    key = (q.strip().lower(), lang, limit)
    if key in _search_cache:
        return _search_cache[key]
    try:
        rows = _nominatim("search", {
            "q": q, "limit": limit, "accept-language": "uz,en" if lang == "uz" else "en",
            "polygon_geojson": 1, "polygon_threshold": 0.005,
        })
        places = [_from_nominatim(r) for r in rows if isinstance(r, dict)]
    except GeoDown:
        places = _photon(q, lang, limit)  # raises GeoDown if this one is down too
    places = [p for p in places if p]
    _search_cache[key] = places
    return places


def _from_nominatim(r: dict) -> dict | None:
    try:
        lat, lon = float(r["lat"]), float(r["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    name = r.get("name") or r.get("display_name", "").split(",")[0]
    context = ", ".join(part.strip() for part in r.get("display_name", "").split(",")[1:] if part.strip())
    geometry = r.get("geojson") if isinstance(r.get("geojson"), dict) else None
    return {
        "name": name, "context": context, "label": r.get("display_name") or name,
        "lat": lat, "lon": lon, "bbox": _bbox(r.get("boundingbox")),
        "kind": r.get("addresstype") or r.get("type"), "rank": r.get("place_rank"),
        # points carry no outline worth drawing
        "outline": geometry if geometry and geometry.get("type") in ("Polygon", "MultiPolygon") else None,
    }


def _photon(q: str, lang: str, limit: int) -> list[dict]:
    try:
        r = _client.get(PHOTON, params={"q": q, "limit": limit, "lang": "en" if lang == "en" else "default"})
        r.raise_for_status()
        features = r.json().get("features", [])
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        raise GeoDown(f"Photon: {type(exc).__name__}") from exc
    out = []
    for f in features:
        p, coords = f.get("properties") or {}, (f.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        name = p.get("name") or p.get("city") or p.get("state") or p.get("country") or ""
        context = ", ".join(dict.fromkeys(v for v in (p.get("city"), p.get("state"), p.get("country")) if v and v != name))
        ext = p.get("extent")  # [west, north, east, south]
        out.append({
            "name": name, "context": context, "label": ", ".join(x for x in (name, context) if x),
            "lat": float(coords[1]), "lon": float(coords[0]),
            "bbox": [ext[3], ext[0], ext[1], ext[2]] if isinstance(ext, list) and len(ext) == 4 else None,
            "kind": p.get("type"), "rank": None, "outline": None,
        })
    return out


# ---------- land cover ----------

# OpenStreetMap category/type -> what the land is. Checked in this order: type first, then category.
_COVER_BY_TYPE = {
    "glacier": "glacier", "bare_rock": "rock", "scree": "rock", "rock": "rock", "cliff": "rock",
    "sand": "sand", "dune": "sand", "beach": "sand",
    "water": "water", "lake": "water", "pond": "water", "reservoir": "water", "river": "water",
    "riverbank": "water", "canal": "water", "basin": "water", "bay": "sea", "strait": "sea", "sea": "sea",
    "coastline": "sea", "wetland": "wetland", "marsh": "wetland", "swamp": "wetland",
    "residential": "urban", "commercial": "urban", "industrial": "urban", "retail": "urban",
    "construction": "urban", "garages": "urban", "railway": "transport", "cemetery": "urban",
    "military": "urban", "landfill": "urban", "quarry": "urban", "brownfield": "urban",
    "aerodrome": "transport", "runway": "transport", "taxiway": "transport", "apron": "transport",
    "park": "park", "pitch": "park", "stadium": "park", "playground": "park", "golf_course": "park",
    "sports_centre": "park", "track": "park",
    "farmland": "farmland", "farmyard": "farmland", "orchard": "farmland", "vineyard": "farmland",
    "meadow": "farmland", "allotments": "farmland", "greenhouse_horticulture": "farmland",
    "plant_nursery": "farmland", "grassland": "grassland", "scrub": "grassland", "heath": "grassland",
    "forest": "forest", "wood": "forest",
}
_COVER_BY_CATEGORY = {
    "building": "building", "amenity": "building", "shop": "building", "office": "building",
    "tourism": "building", "craft": "building", "healthcare": "building", "historic": "building",
    "man_made": "building", "highway": "road", "railway": "transport", "aeroway": "transport",
    "waterway": "water", "water": "water",
}


def _cover_kind(category: str, kind: str) -> str | None:
    if category in ("boundary", "place"):
        return None  # an administrative area says nothing about the ground
    return _COVER_BY_TYPE.get(kind) or _COVER_BY_CATEGORY.get(category)


def _xy(lat0: float, lon: float, lat: float) -> tuple[float, float]:
    """Metres on a local flat projection around lat0."""
    return lon * 111_320 * math.cos(math.radians(lat0)), lat * 110_540


def _in_ring(x: float, y: float, ring) -> bool:
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _seg_dist(p, a, b) -> float:
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def where(geometry: dict | None, lat: float, lon: float) -> tuple[bool | None, float | None]:
    """-> (point is inside the area, distance in metres to the outline/line/point); None when unknown."""
    if not isinstance(geometry, dict):
        return None, None
    gtype, coords = geometry.get("type"), geometry.get("coordinates")
    try:
        proj = lambda c: _xy(lat, c[0], c[1])  # noqa: E731
        p = proj((lon, lat))
        if gtype in ("Polygon", "MultiPolygon"):
            polygons = [coords] if gtype == "Polygon" else coords
            edges = []
            for rings in polygons:
                outer = [proj(c) for c in rings[0]]
                holes = [[proj(c) for c in h] for h in rings[1:]]
                if _in_ring(*p, outer) and not any(_in_ring(*p, h) for h in holes):
                    return True, 0.0
                edges += [ring for ring in [outer, *holes]]
            return False, min(_seg_dist(p, a, b) for ring in edges for a, b in zip(ring, ring[1:]))
        if gtype in ("LineString", "MultiLineString"):
            lines = [coords] if gtype == "LineString" else coords
            pts = [[proj(c) for c in line] for line in lines]
            return None, min(_seg_dist(p, a, b) for line in pts for a, b in zip(line, line[1:]))
        if gtype == "Point":
            return None, math.dist(p, proj(coords))
    except (TypeError, IndexError, ValueError, ZeroDivisionError):
        pass
    return None, None


def land_cover(lat: float, lon: float, lang: str = "en") -> dict:
    """What OpenStreetMap has exactly at the point.

    -> {"kind": building|road|water|sea|urban|farmland|... or None, "osm": "category=type",
        "name", "place" (readable address), "country_code", "found": False when OSM has no address here}
    Raises GeoDown when the service does not answer.
    """
    key = (round(lat, 4), round(lon, 4), lang)
    if key in _cover_cache:
        return _cover_cache[key]
    body = _nominatim("reverse", {
        "lat": lat, "lon": lon, "zoom": 18, "accept-language": "uz,en" if lang == "uz" else "en",
        "polygon_geojson": 1, "polygon_threshold": 0.00001,
    })
    if not isinstance(body, dict):
        raise GeoDown("Nominatim: unexpected response")
    if body.get("error"):  # "Unable to geocode": no address at all, typically open sea
        result = {"kind": None, "osm": None, "name": None, "place": None, "country_code": None, "found": False}
    else:
        category, kind = body.get("category") or "", body.get("type") or ""
        cover = _cover_kind(category, kind)
        inside, dist = where(body.get("geojson"), lat, lon)
        address = body.get("address") or {}
        # Nominatim answers with the NEAREST object, so it only counts if the point is really on it.
        on_it = inside is True or (dist is not None and dist <= ROAD_BUFFER_M)
        land = cover if cover and on_it else None
        in_town = bool(address.get("city") or address.get("town")) and any(
            address.get(k) for k in ("house_number", "neighbourhood", "suburb", "quarter", "residential"))
        near = dist is not None and dist <= URBAN_BUFFER_M
        if land is None and in_town and near and cover in ("building", "road", "transport", "urban"):
            land = "urban"  # between houses, yards and streets of a town
        result = {
            "kind": land,
            "osm": f"{category}={kind}" if category else None,
            "name": body.get("name") or None,
            "place": body.get("display_name"),
            "country_code": address.get("country_code"),
            "found": True,
        }
    if len(_cover_cache) > 5000:
        _cover_cache.clear()
    _cover_cache[key] = result
    return result


# ---------- country of a point, offline ----------

_COUNTRIES_FILE = Path(__file__).parent / "data" / "countries.json"
_countries: list | None = None


def country_at(lat: float, lon: float) -> str | None:
    """ISO 3166 alpha-2 code of the country that contains the point (Natural Earth 1:50m), or None at sea.

    Works without network, so the regional crop plan does not depend on OpenStreetMap answering.
    """
    global _countries
    if _countries is None:
        try:
            _countries = json.loads(_COUNTRIES_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _countries = []
    # The point itself, then a ring about 10 km around it: simplified borders cut off some coasts.
    for dlat, dlon in [(0, 0)] + [(dy * 0.1, dx * 0.1) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dy or dx]:
        y, x = lat + dlat, lon + dlon
        for c in _countries:
            s, w, n, e = c["bbox"]
            if not (s <= y <= n and w <= x <= e):
                continue
            for rings in c["polygons"]:
                if _in_ring(x, y, rings[0]) and not any(_in_ring(x, y, h) for h in rings[1:]):
                    return c["iso"]
    return None
