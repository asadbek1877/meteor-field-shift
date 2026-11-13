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
from pathlib import Path
from urllib.parse import urlparse

import httpx

CONFIG = Path(__file__).parent / "providers.json"
HEALTH_TTL_S = 120
DOWN_TTL_S = 600
TIMEOUT_S = 3.5
JSON_MAX_BYTES = 2_000_000

_GIBS = "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best"


def _gibs(layer_id: str, title: dict, matrix: str, group: str, ext: str = "png", dated: bool = True,
          lag_days: int = 1) -> dict:
    """A GIBS WMTS layer. `dated` layers accept a date in place of the second `default`
    (the site offers a date picker); `lag_days` is how far behind today the newest image usually is."""
    return {
        "id": layer_id,
        "title": title,
        "group": group,
        "url": f"{_GIBS}/{layer_id}/default/default/{matrix}/{{z}}/{{y}}/{{x}}.{ext}",
        "max_zoom": int(matrix.split("Level")[1]),
        "attribution": "NASA GIBS",
        "dated": dated,
        "lag_days": lag_days,
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
        "description": "Satellite map layers: true colour, vegetation, land temperature, precipitation, soil moisture, water storage",
        "layers": [
            _gibs("VIIRS_SNPP_CorrectedReflectance_TrueColor", {"en": "True colour (VIIRS SNPP)", "uz": "Haqiqiy rang (VIIRS SNPP)"}, "GoogleMapsCompatible_Level9", "imagery", ext="jpg", lag_days=1),
            _gibs("MODIS_Terra_L3_NDVI_16Day", {"en": "Vegetation NDVI (MODIS Terra)", "uz": "O'simlik yashilligi NDVI (MODIS Terra)"}, "GoogleMapsCompatible_Level9", "vegetation", lag_days=20),
            _gibs("MODIS_Terra_L3_Land_Surface_Temp_8Day_Day", {"en": "Land surface temperature (MODIS Terra)", "uz": "Yer sirti harorati (MODIS Terra)"}, "GoogleMapsCompatible_Level7", "heat", lag_days=10),
            _gibs("SMAP_L4_Analyzed_Root_Zone_Soil_Moisture", {"en": "Root-zone soil moisture (SMAP L4)", "uz": "Ildiz qatlami namligi (SMAP L4)"}, "GoogleMapsCompatible_Level6", "water", lag_days=4),
            _gibs("IMERG_Precipitation_Rate", {"en": "Precipitation (GPM IMERG)", "uz": "Yog'in (GPM IMERG)"}, "GoogleMapsCompatible_Level6", "water", lag_days=2),
            _gibs("GRACE_Tellus_Liquid_Water_Equivalent_Thickness_Mascon_CRI", {"en": "Water storage (GRACE)", "uz": "Suv zaxirasi (GRACE)"}, "GoogleMapsCompatible_Level6", "water", dated=False),
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
        resp = _client.get(url)
        resp.raise_for_status()
        if len(resp.content) > JSON_MAX_BYTES:
            raise ValueError("response too large")
        body = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        reason = type(exc).__name__
        _down_until[provider["id"]] = (time.time() + DOWN_TTL_S, reason)
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

_soil_cache: dict[tuple, dict] = {}


def soil(provider: dict, lat: float, lon: float) -> dict:
    """Topsoil (0-30 cm) texture, organic carbon and pH from SoilGrids."""
    key = (round(lat, 2), round(lon, 2))
    if key in _soil_cache:
        return _soil_cache[key]
    body = _fetch(provider, lat, lon)
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
    _soil_cache[key] = result
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
