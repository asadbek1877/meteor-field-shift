"""Registry of data providers (NASA APIs and others).

Built-in providers live in code. Providers added later from the site's settings
page are stored in backend/providers.json. Kinds:

  series    NASA POWER: numbers that feed the climate, crop and rotation analysis
  layers    map tiles (NASA GIBS or a custom tile URL with {z}/{x}/{y})
  soil      soil properties of the point (SoilGrids)
  forecast  weather forecast for the next days (Open-Meteo, not NASA)
  json      any JSON API called with {lat} and {lon}; returned as raw "extra" data

A provider that fails is skipped for 10 minutes, so one dead service cannot slow
down every request. A new "json" provider is shown as raw data: feeding it into
the analysis needs a small mapping in code, because every API has its own format.
"""
from __future__ import annotations

import ipaddress
import json
import re
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path
from urllib.parse import urlparse

import httpx

CONFIG = Path(__file__).parent / "providers.json"
HEALTH_TTL_S = 120
DOWN_TTL_S = 600
TIMEOUT_S = 3.5
JSON_MAX_BYTES = 2_000_000

_GIBS = "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best"


def _gibs(layer_id: str, title: dict, matrix: str, group: str) -> dict:
    return {
        "id": layer_id,
        "title": title,
        "group": group,
        "url": f"{_GIBS}/{layer_id}/default/default/{matrix}/{{z}}/{{y}}/{{x}}.png",
        "max_zoom": int(matrix.split("Level")[1]),
        "attribution": "NASA GIBS",
    }


# Layer ids, tile matrix sets and formats were read from the GIBS WMTS capabilities.
BUILTIN = [
    {
        "id": "nasa_power", "name": "NASA POWER", "kind": "series", "builtin": True, "nasa": True,
        "feeds": ["climate", "crops", "rotations"],
        "docs": "https://power.larc.nasa.gov/docs/",
        "description": "Daily temperature, precipitation, humidity, wind, solar radiation and soil wetness since 1991 (MERRA-2, GEOS-IT, CERES)",
    },
    {
        "id": "nasa_gibs", "name": "NASA GIBS", "kind": "layers", "builtin": True, "nasa": True,
        "feeds": ["map"],
        "docs": "https://nasa-gibs.github.io/gibs-api-docs/",
        "description": "Satellite map layers: vegetation (MODIS, VIIRS), land temperature, precipitation (GPM IMERG), soil moisture (SMAP, GLDAS), water storage (GRACE), terrain (SRTM)",
        "layers": [
            _gibs("MODIS_Terra_L3_NDVI_16Day", {"en": "Vegetation NDVI (MODIS Terra)", "uz": "O'simlik yashilligi NDVI (MODIS Terra)"}, "GoogleMapsCompatible_Level9", "vegetation"),
            _gibs("MODIS_Terra_L3_Land_Surface_Temp_8Day_Day", {"en": "Land surface temperature (MODIS Terra)", "uz": "Yer sirti harorati (MODIS Terra)"}, "GoogleMapsCompatible_Level7", "heat"),
            _gibs("IMERG_Precipitation_Rate", {"en": "Precipitation (GPM IMERG)", "uz": "Yog'in (GPM IMERG)"}, "GoogleMapsCompatible_Level6", "water"),
            _gibs("GRACE_Tellus_Liquid_Water_Equivalent_Thickness_Mascon_CRI", {"en": "Water storage (GRACE)", "uz": "Suv zaxirasi (GRACE)"}, "GoogleMapsCompatible_Level6", "water"),
            _gibs("SMAP_L4_Analyzed_Root_Zone_Soil_Moisture", {"en": "Root-zone soil moisture (SMAP L4)", "uz": "Ildiz qatlami tuproq namligi (SMAP L4)"}, "GoogleMapsCompatible_Level6", "water"),
            _gibs("SMAP_L3_Passive_Day_Soil_Moisture", {"en": "Surface soil moisture (SMAP L3)", "uz": "Yuza tuproq namligi (SMAP L3)"}, "GoogleMapsCompatible_Level6", "water"),
            _gibs("GLDAS_Underground_Soil_Moisture_Monthly", {"en": "Soil moisture, monthly (GLDAS)", "uz": "Tuproq namligi, oylik (GLDAS)"}, "GoogleMapsCompatible_Level6", "water"),
            _gibs("VIIRS_SNPP_NDVI_8Day", {"en": "Vegetation NDVI, 8-day (VIIRS)", "uz": "O'simlik yashilligi NDVI, 8 kunlik (VIIRS)"}, "GoogleMapsCompatible_Level8", "vegetation"),
            _gibs("MODIS_Terra_Land_Surface_Temp_Day", {"en": "Land surface temperature, daily (MODIS Terra)", "uz": "Yer sirti harorati, kunlik (MODIS Terra)"}, "GoogleMapsCompatible_Level7", "heat"),
            _gibs("SRTM_Color_Index", {"en": "Terrain height (SRTM)", "uz": "Relyef balandligi (SRTM)"}, "GoogleMapsCompatible_Level12", "terrain"),
        ],
    },
    {
        "id": "soilgrids", "name": "SoilGrids (ISRIC)", "kind": "soil", "builtin": True, "nasa": False,
        "feeds": ["soil", "rotations"],
        "docs": "https://www.isric.org/explore/soilgrids",
        "description": "Soil texture, organic carbon and pH at 250 m. Not a NASA dataset",
        "url_template": "https://rest.isric.org/soilgrids/v2.0/properties/query?lon={lon}&lat={lat}"
                        "&property=clay&property=sand&property=silt&property=soc&property=phh2o"
                        "&depth=0-5cm&depth=5-15cm&depth=15-30cm&value=mean",
    },
    {
        "id": "open_meteo", "name": "Open-Meteo", "kind": "forecast", "builtin": True, "nasa": False,
        "feeds": ["forecast"],
        "docs": "https://open-meteo.com/en/docs",
        "description": "16-day weather forecast: rain, evapotranspiration, temperature. Not a NASA dataset",
        "url_template": "https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
                        "&daily=precipitation_sum,et0_fao_evapotranspiration,temperature_2m_max,"
                        "temperature_2m_min,precipitation_probability_max&forecast_days=16&timezone=auto",
    },
]
_BUILTIN_IDS = {p["id"] for p in BUILTIN}

_lock = threading.Lock()
_client = httpx.Client(timeout=TIMEOUT_S, headers={"User-Agent": "field-shift-app"})
_health: dict[str, tuple[float, dict]] = {}
_down_until: dict[str, tuple[float, str]] = {}


class ProviderDown(Exception):
    pass


# ---------- config ----------

def _read() -> dict:
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"enabled": {}, "custom": []}


def _write(cfg: dict) -> None:
    CONFIG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def all_providers() -> list[dict]:
    cfg = _read()
    return [{**p, "enabled": cfg.get("enabled", {}).get(p["id"], True)}
            for p in BUILTIN + cfg.get("custom", [])]


def get(provider_id: str) -> dict | None:
    return next((p for p in all_providers() if p["id"] == provider_id), None)


def set_enabled(provider_id: str, enabled: bool) -> dict:
    if get(provider_id) is None:
        raise KeyError(provider_id)
    with _lock:
        cfg = _read()
        cfg.setdefault("enabled", {})[provider_id] = enabled
        _write(cfg)
    _down_until.pop(provider_id, None)
    return get(provider_id)


def _check_url(url: str) -> None:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if parsed.scheme != "https" or not host:
        raise ValueError("url must start with https://")
    if host == "localhost" or host.endswith(".local"):
        raise ValueError("local addresses are not allowed")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
        raise ValueError("private addresses are not allowed")


def add_custom(spec: dict) -> dict:
    """Validate and store a new provider. Raises ValueError with a readable message."""
    pid = str(spec.get("id", ""))
    if not re.fullmatch(r"[a-z0-9_]{3,32}", pid):
        raise ValueError("id must be 3-32 characters: a-z, 0-9, _")
    if get(pid):
        raise ValueError("this id already exists")
    kind = spec.get("kind")
    url = str(spec.get("url_template", ""))
    if kind == "layers":
        if not all(t in url for t in ("{z}", "{x}", "{y}")):
            raise ValueError("a tile url needs {z}, {x} and {y}")
    elif kind == "json":
        if "{lat}" not in url or "{lon}" not in url:
            raise ValueError("a json url needs {lat} and {lon}")
    else:
        raise ValueError("kind must be 'layers' or 'json'")
    _check_url(url.replace("{", "").replace("}", ""))
    provider = {
        "id": pid,
        "name": str(spec.get("name") or pid)[:60],
        "kind": kind,
        "builtin": False,
        "nasa": bool(spec.get("nasa", False)),
        "feeds": ["map"] if kind == "layers" else ["extra"],
        "url_template": url,
        "description": str(spec.get("description", ""))[:200],
        "docs": str(spec.get("docs", ""))[:200],
    }
    with _lock:
        cfg = _read()
        cfg.setdefault("custom", []).append(provider)
        _write(cfg)
    return get(pid)


def remove_custom(provider_id: str) -> None:
    if provider_id in _BUILTIN_IDS:
        raise ValueError("built-in providers can be switched off but not removed")
    with _lock:
        cfg = _read()
        before = len(cfg.get("custom", []))
        cfg["custom"] = [p for p in cfg.get("custom", []) if p["id"] != provider_id]
        if len(cfg["custom"]) == before:
            raise KeyError(provider_id)
        _write(cfg)


# ---------- calls ----------

def layers_of(provider: dict) -> list[dict]:
    if provider["kind"] != "layers":
        return []
    if provider.get("layers"):
        return provider["layers"]
    return [{
        "id": provider["id"], "title": {"en": provider["name"], "uz": provider["name"]}, "group": "custom",
        "url": provider["url_template"].replace("{time}", "default"),
        "max_zoom": 8, "attribution": provider["name"],
    }]


def _fetch(provider: dict, lat: float, lon: float):
    """GET the provider's JSON for a point, remembering failures for 10 minutes."""
    down = _down_until.get(provider["id"])
    if down and time.time() < down[0]:
        raise ProviderDown(f"{down[1]} (skipped, retry in {int(down[0] - time.time())} s)")
    url = provider["url_template"].replace("{lat}", str(lat)).replace("{lon}", str(lon))
    try:
        # SoilGrids often needs about 10 s; it is fetched in the background (see soil()), so it may take longer
        resp = _client.get(url, timeout=SOIL_TIMEOUT_S if provider.get("kind") == "soil" else TIMEOUT_S)
        resp.raise_for_status()
        if len(resp.content) > JSON_MAX_BYTES:
            raise ValueError("response too large")
        body = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        reason = type(exc).__name__
        # soil is fetched in the background and costs the request nothing, so it may be retried sooner
        ttl = SOIL_DOWN_TTL_S if provider.get("kind") == "soil" else DOWN_TTL_S
        _down_until[provider["id"]] = (time.time() + ttl, reason)
        raise ProviderDown(reason) from exc
    _down_until.pop(provider["id"], None)
    return body


def fetch_json(provider: dict, lat: float, lon: float):
    return _fetch(provider, lat, lon)


def check(provider: dict, force: bool = False) -> dict:
    """Is a provider reachable right now? Cached for 2 minutes."""
    now = time.time()
    hit = _health.get(provider["id"])
    if hit and not force and now - hit[0] < HEALTH_TTL_S:
        return hit[1]
    if force:
        _down_until.pop(provider["id"], None)
    started = time.perf_counter()
    try:
        if provider["kind"] == "layers":
            url = layers_of(provider)[0]["url"].replace("{z}", "2").replace("{y}", "1").replace("{x}", "1")
            resp = _client.get(url)
            if resp.status_code != 200:
                raise ProviderDown(f"HTTP {resp.status_code}")
        elif provider["kind"] == "series":
            from . import nasa_client
            resp = nasa_client._client.get(
                f"{nasa_client.BASE}/daily/point",
                params={"parameters": "T2M", "community": "AG", "latitude": 41.3, "longitude": 69.2,
                        "start": "20240101", "end": "20240102", "format": "JSON"})
            if resp.status_code != 200:
                raise ProviderDown(f"HTTP {resp.status_code}")
        else:
            _fetch(provider, 41.3, 69.2)
        result = {"status": "ok", "ms": round((time.perf_counter() - started) * 1000), "message": None}
    except (httpx.HTTPError, ProviderDown) as exc:
        result = {"status": "down", "ms": None, "message": str(exc) or type(exc).__name__}
    _health[provider["id"]] = (now, result)
    return result


# ---------- soil ----------

SOIL_TIMEOUT_S = 25
SOIL_DOWN_TTL_S = 120
SOIL_WAIT_S = 3.5          # a request waits this long; the fetch itself goes on in the background
SOIL_CACHE_FILE = Path(__file__).parent / "cache" / "soil.json"
_soil_cache: dict[tuple, dict] = {}
_soil_jobs: dict[tuple, Future] = {}
_soil_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="soil")
_soil_disk_loaded = False


def _soil_from_disk() -> None:
    """Soil does not change, so every answer is kept on disk and survives restarts."""
    global _soil_disk_loaded
    if _soil_disk_loaded:
        return
    _soil_disk_loaded = True
    try:
        for key, value in json.loads(SOIL_CACHE_FILE.read_text(encoding="utf-8")).items():
            lat, lon = key.split("_")
            _soil_cache.setdefault((float(lat), float(lon)), value)
    except (OSError, ValueError):
        pass


def _soil_to_disk() -> None:
    try:
        SOIL_CACHE_FILE.parent.mkdir(exist_ok=True)
        SOIL_CACHE_FILE.write_text(json.dumps({f"{k[0]}_{k[1]}": v for k, v in _soil_cache.items()},
                                              ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def soil(provider: dict, lat: float, lon: float) -> dict:
    """Topsoil (0-30 cm) texture, organic carbon and pH from SoilGrids.

    SoilGrids is slow (often 10 s). The request waits SOIL_WAIT_S; if the answer is not there yet the
    fetch continues in the background and is cached, so the next analysis of the place has the soil.
    """
    key = (round(lat, 2), round(lon, 2))
    with _lock:
        _soil_from_disk()
        if key in _soil_cache:
            return _soil_cache[key]
        job = _soil_jobs.get(key)
        if job is None:
            job = _soil_jobs[key] = _soil_pool.submit(_soil_fetch, provider, lat, lon, key)
    try:
        return job.result(timeout=SOIL_WAIT_S)
    except FutureTimeout:
        raise ProviderDown("slow answer, still loading: the next analysis of this place will have the soil") from None


def _soil_fetch(provider: dict, lat: float, lon: float, key: tuple) -> dict:
    try:
        result = _soil_parse(_fetch(provider, lat, lon))
        with _lock:
            _soil_cache[key] = result
            _soil_to_disk()
        return result
    finally:
        with _lock:
            _soil_jobs.pop(key, None)


def _soil_parse(body) -> dict:
    values = {}
    try:
        for layer in body.get("properties", {}).get("layers", []):
            factor = layer.get("unit_measure", {}).get("d_factor") or 1
            means = [d["values"].get("mean") for d in layer.get("depths", [])]
            means = [m for m in means if m is not None]
            if means:
                values[layer["name"]] = sum(means) / len(means) / factor
    except (AttributeError, KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise ProviderDown(f"unexpected response ({type(exc).__name__})") from exc
    if "clay" not in values or "sand" not in values:
        raise ProviderDown("no soil data for this point")
    clay, sand = values["clay"], values["sand"]  # percent
    soil_class = "light" if sand >= 65 else "heavy" if clay >= 35 else "medium"
    result = {
        "class": soil_class,
        "clay_pct": round(clay, 1), "sand_pct": round(sand, 1),
        "silt_pct": round(values.get("silt", 100 - clay - sand), 1),
        "organic_carbon_g_kg": round(values["soc"], 1) if "soc" in values else None,
        "ph": round(values["phh2o"], 1) if "phh2o" in values else None,
        "depth_cm": "0-30", "source": "SoilGrids 2.0 (ISRIC), 250 m",
    }
    return result


# ---------- forecast ----------

def forecast(provider: dict, lat: float, lon: float) -> dict:
    """Daily forecast normalised to a small structure."""
    body = _fetch(provider, lat, lon)
    try:
        return _forecast_days(provider, body)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ProviderDown(f"unexpected response ({type(exc).__name__})") from exc


def _forecast_days(provider: dict, body) -> dict:
    daily = body.get("daily") or {}
    times = daily.get("time") or []
    if not times:
        raise ProviderDown("empty forecast")

    def col(name):
        values = daily.get(name) or []
        return [values[i] if i < len(values) else None for i in range(len(times))]

    rain, et0 = col("precipitation_sum"), col("et0_fao_evapotranspiration")
    tmax, tmin, prob = col("temperature_2m_max"), col("temperature_2m_min"), col("precipitation_probability_max")
    days = [{"date": times[i], "rain_mm": rain[i], "et0_mm": et0[i], "t_max": tmax[i], "t_min": tmin[i],
             "rain_probability": prob[i]} for i in range(len(times)) if rain[i] is not None or tmax[i] is not None]
    week = days[:7]
    next_rain = next((d for d in days if (d["rain_mm"] or 0) >= 1.0), None)
    return {
        "source": provider["name"],
        "days": days,
        "rain_7d_mm": round(sum(d["rain_mm"] or 0 for d in week), 1),
        "et0_7d_mm": round(sum(d["et0_mm"] or 0 for d in week), 1) if all(d["et0_mm"] is not None for d in week) else None,
        "next_rain_date": next_rain["date"] if next_rain else None,
        "next_rain_mm": next_rain["rain_mm"] if next_rain else None,
        "horizon_days": len(days),
    }
