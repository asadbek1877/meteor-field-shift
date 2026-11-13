"""Field Shift API.

Run from the repository root:
    uvicorn backend.main:app --reload
Then open http://localhost:8000 (site) or http://localhost:8000/docs (API).

Editing providers (POST/PATCH/DELETE /api/providers) needs the server to be
started with an ADMIN_TOKEN environment variable, sent as header X-Admin-Token.
"""
from __future__ import annotations

import os
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import (agro, climate, geo, landcover, nasa_client, observe, providers, regional, store, suitability, terrain,
               texts, usa, water, weekly)


def _load_env(path: Path) -> None:
    """KEY=value lines of the project's .env (API tokens). Values already in the environment win."""
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    except OSError:
        pass


_load_env(Path(__file__).parent.parent / ".env")

# If NASA is down, a cached point is used only when it is this close to the request.
FALLBACK_MAX_KM = float(os.getenv("FALLBACK_MAX_KM", "150"))

PRESETS = [
    {"id": "jizzakh", "name": {"en": "Jizzakh (steppe)", "uz": "Jizzax (dasht)"}, "lat": 40.1158, "lon": 67.8422},
    {"id": "tashkent", "name": {"en": "Tashkent (oasis)", "uz": "Toshkent (voha)"}, "lat": 41.2995, "lon": 69.2401},
    {"id": "kyzylkum", "name": {"en": "Kyzylkum (desert)", "uz": "Qizilqum (cho'l)"}, "lat": 42.0, "lon": 63.5},
]


@asynccontextmanager
async def lifespan(_: FastAPI):
    store.load_all()
    yield


app = FastAPI(title="Field Shift API", version="2.0", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=2000)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["*"])


def require_admin(x_admin_token: str | None = Header(default=None)):
    token = os.getenv("ADMIN_TOKEN")
    if not token:
        raise HTTPException(403, "Editing providers is off. Start the server with the ADMIN_TOKEN environment variable.")
    if not secrets.compare_digest(x_admin_token or "", token):
        raise HTTPException(401, "Wrong admin token.")


@app.get("/api/health")
def health():
    return {"status": "ok", "cached_points": len(store._memory)}


@app.get("/api/presets")
def presets():
    return PRESETS


@app.get("/api/options")
def options():
    """Everything the site needs to build its forms."""
    cfg = agro.CONFIG
    return {
        "crops": [{"id": c["id"], "name": c["name"], "legume": c["legume"]} for c in cfg["crops"]],
        "rotations": [{"id": r["id"], "name": r["name"], "years": r["years"]} for r in agro.ROTATIONS["rotations"]],
        "default_current": agro.ROTATIONS["default_current"],
        "soils": [{"id": k, "name": v["name"]} for k, v in cfg["soils"].items()],
        "irrigation": [{"id": k, "name": v["name"], "efficiency": v["efficiency"]} for k, v in cfg["irrigation"].items()],
        "weights": agro.DEFAULT_WEIGHTS,
        "periods": {"baseline": list(climate.BASELINE), "recent": list(climate.RECENT)},
        "presets": PRESETS,
    }


@app.get("/api/layers")
def layers():
    """Map layers of the enabled layer providers (no network check, for a fast first paint)."""
    return [{**layer, "provider": p["id"]} for p in providers.all_providers()
            if p["enabled"] and p["kind"] == "layers" for layer in providers.layers_of(p)]


@app.get("/api/places")
def search_places(
    q: str = Query(min_length=2, max_length=200),
    lang: str = Query(default="en", pattern="^(en|uz)$"),
    limit: int = Query(default=5, ge=1, le=8),
):
    """Find a country, region, town or village by name (OpenStreetMap Nominatim, Photon as backup).

    Each result has a centre (lat, lon), a bounding box [south, west, north, east] for
    fitting the map, and for areas a simplified outline (GeoJSON) to draw.
    """
    try:
        return {"results": geo.search(q, lang, limit)}
    except geo.GeoDown as exc:
        raise HTTPException(502, "Place search is temporarily unavailable.") from exc


# ---------- providers (site settings page) ----------

def _public(p: dict, status: dict | None = None) -> dict:
    return {
        "id": p["id"], "name": p["name"], "kind": p["kind"], "builtin": p.get("builtin", False),
        "nasa": p.get("nasa", False), "enabled": p["enabled"], "feeds": p["feeds"],
        "description": p.get("description", ""), "docs": p.get("docs", ""),
        "status": status or {"status": "disabled" if not p["enabled"] else "unknown", "ms": None, "message": None},
    }


@app.get("/api/providers")
def list_providers(refresh: bool = False):
    """All providers with a live check of the enabled ones."""
    items = providers.all_providers()
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {p["id"]: pool.submit(providers.check, p, refresh) for p in items if p["enabled"]}
    return {
        "editable": bool(os.getenv("ADMIN_TOKEN")),
        "items": [_public(p, futures[p["id"]].result() if p["id"] in futures else None) for p in items],
    }


class NewProvider(BaseModel):
    id: str
    name: str
    kind: str  # "layers" or "json"
    url_template: str
    description: str = ""
    docs: str = ""
    nasa: bool = False


class ProviderPatch(BaseModel):
    enabled: bool


@app.post("/api/providers", dependencies=[Depends(require_admin)])
def add_provider(body: NewProvider):
    try:
        return _public(providers.add_custom(body.model_dump()))
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@app.patch("/api/providers/{provider_id}", dependencies=[Depends(require_admin)])
def patch_provider(provider_id: str, body: ProviderPatch):
    try:
        return _public(providers.set_enabled(provider_id, body.enabled))
    except KeyError:
        raise HTTPException(404, "unknown provider")


@app.delete("/api/providers/{provider_id}", dependencies=[Depends(require_admin)])
def delete_provider(provider_id: str):
    try:
        providers.remove_custom(provider_id)
    except KeyError:
        raise HTTPException(404, "unknown provider")
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return {"removed": provider_id}


# ---------- analysis ----------

def _load_series(lat: float, lon: float):
    """-> (data or None, source, fallback info or None, error text or None)

    Order: saved data of this point, live daily data, live monthly data, nearest saved point.
    """
    data = store.get(lat, lon)
    if data is not None:
        return data, "cache", None, None
    try:
        data = nasa_client.fetch_daily(lat, lon)
        store.put(data)
        return data, "live", None, None
    except nasa_client.PowerError as exc:
        error = str(exc)
    try:
        return nasa_client.fetch_monthly(lat, lon), "monthly", None, error
    except nasa_client.PowerError:
        pass
    near = store.nearest(lat, lon)
    if near is not None and near[1] <= FALLBACK_MAX_KM:
        saved, dist = near
        return saved, "fallback", {"distance_km": round(dist), "lat": saved["lat"], "lon": saved["lon"]}, error
    return None, "failed", None, error


def _week_plan(plan: dict, week_job, ensemble_job, irrigation: str, lat: float, lon: float = 0.0):
    """This week's advice for the region's main crops; None when the forecast did not arrive."""
    try:
        weather = week_job.result()
    except water.WeatherDown:
        return None
    obs = observe.get(lat, lon)          # ready NASA observations; the others start loading now
    return weekly.analyze(plan, weather, ensemble_job.result(), agro.CONFIG["irrigation"][irrigation]["efficiency"],
                          date.today(), lat, obs)


def _try(job):
    """Result of a provider call, or the error text."""
    if job is None:
        return None, None
    try:
        return job.result(), None
    except providers.ProviderDown as exc:
        return None, str(exc)


@app.get("/api/analyze")
def analyze(
    lat: float = Query(..., ge=-90, le=90, description="Latitude"),
    lon: float = Query(..., ge=-180, le=180, description="Longitude"),
    lang: str = Query("en", pattern="^(en|uz)$", description="Language of texts"),
    soil: str = Query("auto", pattern="^(auto|light|medium|heavy)$", description="Soil type; auto = SoilGrids"),
    irrigation: str = Query("furrow", pattern="^(furrow|sprinkler|drip)$", description="Irrigation method"),
    current: str | None = Query(None, description="Id of the farmer's current rotation"),
    custom: str | None = Query(None, description="Own rotation, e.g. cotton|winter_wheat+mung_bean|alfalfa"),
    w_water: float = Query(agro.DEFAULT_WEIGHTS["water"], ge=0, le=100),
    w_income: float = Query(agro.DEFAULT_WEIGHTS["income"], ge=0, le=100),
    w_soil: float = Query(agro.DEFAULT_WEIGHTS["soil"], ge=0, le=100),
    w_risk: float = Query(agro.DEFAULT_WEIGHTS["risk"], ge=0, le=100),
):
    """Full analysis of one field using every provider that works right now.

    The request does not fail because a provider is down. Instead:
    - `providers` lists each provider with its status
    - `warnings` has a readable message for everything that did not work
    - `coverage` says which parts were done: full, approx or skipped
    - parts that could not be computed are null
    """
    started = time.perf_counter()
    lat, lon = round(lat, 4), round(lon, 4)
    msg = texts.WARN[lang]
    try:
        custom_years = agro.parse_custom(custom)
    except ValueError as exc:
        raise HTTPException(422, str(exc))

    items = providers.all_providers()
    by_kind = lambda kind: [p for p in items if p["kind"] == kind]  # noqa: E731
    on = lambda p: p["enabled"]  # noqa: E731
    power = by_kind("series")[0]
    soil_p = next(iter(by_kind("soil")), None)
    fc_p = next(iter(by_kind("forecast")), None)

    with ThreadPoolExecutor(max_workers=8) as pool:
        series_job = pool.submit(_load_series, lat, lon) if on(power) else None
        soil_job = pool.submit(providers.soil, soil_p, lat, lon) if soil_p and on(soil_p) else None
        fc_job = pool.submit(providers.forecast, fc_p, lat, lon) if fc_p and on(fc_p) else None
        layer_jobs = {p["id"]: pool.submit(providers.check, p) for p in by_kind("layers") if on(p)}
        json_jobs = {p["id"]: pool.submit(providers.fetch_json, p, lat, lon) for p in by_kind("json") if on(p)}
        cover_job = pool.submit(geo.land_cover, lat, lon, lang)
        elevation_job = pool.submit(geo.elevation, lat, lon)
        sat_job = pool.submit(landcover.sample, lat, lon)
        terrain_job = pool.submit(terrain.sample, lat, lon)
        # US fields: USDA CDL rotation history, SSURGO soil, NASS county yields (offline country check first)
        us_job = pool.submit(usa.detail, lat, lon) if geo.country_at(lat, lon) == "US" else None
        week_job = pool.submit(water.fetch, lat, lon, 1)          # this week's weather, for the weekly advice
        ensemble_job = pool.submit(water.fetch_ensemble, lat, lon)

    warnings, statuses, extra, map_layers = [], [], {}, []

    def warn(provider, severity, text):
        warnings.append({"provider": provider, "severity": severity, "text": text})

    def status(p, state, message=None):
        statuses.append({"id": p["id"], "name": p["name"], "nasa": p.get("nasa", False),
                         "status": state, "message": message})

    # NASA POWER
    data, source, fallback, error = None, "disabled", None, None
    if series_job:
        data, source, fallback, error = series_job.result()
    if source == "disabled":
        warn("nasa_power", "warning", msg["disabled"].format(name=power["name"]))
    elif source == "failed":
        warn("nasa_power", "critical", msg["power_failed"])
    elif source == "fallback":
        warn("nasa_power", "warning", msg["power_fallback"].format(km=fallback["distance_km"]))
    elif source == "monthly":
        warn("nasa_power", "warning", msg["power_monthly"])
    status(power, source, error)

    # soil
    soil_info, soil_error = _try(soil_job)
    us = us_job.result() if us_job else None
    if us and us.get("soil") and soil == "auto":
        soil_info, soil_error = us["soil"], None   # SSURGO is the official US soil survey: better than 250 m SoilGrids
    soil_class = soil if soil != "auto" else (soil_info or {}).get("class", "medium")
    soil_name = agro.CONFIG["soils"][soil_class]["name"][lang]
    # water-holding numbers: from the measured texture when the soil is "auto" and SoilGrids answered
    soil_water = agro.soil_water(soil_class, soil_info if soil == "auto" else None)
    if soil_p:
        if not on(soil_p):
            status(soil_p, "disabled")
        elif soil_info:
            status(soil_p, "ok")
        else:
            status(soil_p, "failed", soil_error)
            if soil == "auto":
                warn(soil_p["id"], "warning", msg["soil_down"].format(name=soil_p["name"], soil=soil_name))

    # forecast
    forecast, fc_error = _try(fc_job)
    if fc_p:
        if not on(fc_p):
            status(fc_p, "disabled")
        elif forecast:
            status(fc_p, "ok")
        else:
            status(fc_p, "failed", fc_error)
            warn(fc_p["id"], "info", msg["forecast_down"].format(name=fc_p["name"]))

    # map layers and custom json providers
    for p in by_kind("layers") + by_kind("json"):
        if not on(p):
            status(p, "disabled")
        elif p["kind"] == "layers":
            result = layer_jobs[p["id"]].result()
            status(p, result["status"], result["message"])
            if result["status"] == "ok":
                map_layers += [{**layer, "provider": p["id"]} for layer in providers.layers_of(p)]
            else:
                warn(p["id"], "warning", msg["layer_down"].format(name=p["name"]))
        else:
            value, err = _try(json_jobs[p["id"]])
            if err is None:
                extra[p["id"]] = value
                status(p, "ok")
            else:
                status(p, "failed", err)
                warn(p["id"], "warning", msg["json_failed"].format(name=p["name"]))

    # analysis with whatever arrived
    # land cover: is the point a field at all, or a building, road, water...?
    try:
        cover = cover_job.result()
    except geo.GeoDown:
        cover = None
    try:  # 10 m satellite land cover: water, buildings, ice... seen from space
        sat = sat_job.result()
    except landcover.LandCoverDown:
        sat = None
    try:  # NASA SRTM: height and slope of the field
        relief = terrain_job.result()
    except terrain.TerrainDown:
        relief = None
    # field height: NASA SRTM, else Copernicus DEM (Open-Meteo)
    point_elevation = (relief["elevation_m"] if relief and relief.get("elevation_m") is not None
                       else elevation_job.result())

    result = {"periods": None, "climate": None, "crops": None, "rotations": None, "now": None, "advice": None,
              "region": None, "week_plan": None}
    suit = suitability.judge(cover, None, False, sat, relief)
    if data:
        # NASA POWER temperatures are for the mean height of a ~50 km cell: move them to the field's height
        days = climate.prepare(data, point_elevation)
        if days.correction_c[1]:
            warn("nasa_power", "info", msg["elevation"].format(
                grid=round(days.grid_elevation), point=round(days.elevation), d=days.correction_c[0]))
        no_soil = data.get("resolution") == "daily" and not any(v is not None for v in days.soil[-400:])
        suit = suitability.judge(cover, suitability.climate_facts(days), no_soil, sat, relief)
        clim = climate.analyze(days)
    if suit["status"] == "unsuitable" and data:
        # No crop advice for a roof, a road or the sea: keep only the climate of the place.
        result.update({
            "periods": {"baseline": list(climate.BASELINE), "recent": list(climate.RECENT)},
            "climate": clim,
            "advice": [a for a in texts.advice(lang, clim, [], {"items": []}, {}) if a["group"] == "climate"],
        })
    elif data:
        # What this country grows, what of it works at this point, and rotations built from that.
        iso = (cover or {}).get("country_code") or geo.country_at(lat, lon)  # offline borders if OSM is down
        plan = regional.plan(days, iso, soil_class, irrigation, soil_water["awc_mm_per_m"], us)
        field = plan["field"]
        crops = field.crops(plan["show"]) if plan["show"] else []
        rot = field.rotations(current, custom_years,
                              {"water": w_water, "income": w_income, "soil": w_soil, "risk": w_risk},
                              plan["candidates"], plan["default_current"])
        if not rot["items"]:
            rot = None
        for it in (rot or {}).get("items", []):
            for c in it["conflicts"]:
                warn("rotation", "warning", msg["conflict"].format(
                    name=it["name"][lang], a=agro.CROPS[c["first"]]["name"][lang],
                    b=agro.CROPS[c["second"]]["name"][lang], days=c["overlap_days"]))
        recent, look = climate.recent_conditions(days), climate.outlook(days)
        if forecast and forecast["et0_7d_mm"] is not None:
            week_basis = {"source": "forecast", "et0_7d_mm": forecast["et0_7d_mm"], "rain_7d_mm": forecast["rain_7d_mm"]}
        elif look:
            week_basis = {"source": "climatology", "et0_7d_mm": look["et0_7d_mm"]["p50"], "rain_7d_mm": look["rain_7d_mm"]["p50"]}
        else:
            week_basis = None
        now = {
            "recent": recent, "outlook": look, "forecast": forecast, "week_basis": week_basis,
            "week": field.week(week_basis["et0_7d_mm"], week_basis["rain_7d_mm"], date.today(), plan["show"])
            if week_basis and plan["show"] else [],
        }
        result = {
            "periods": {"baseline": list(climate.BASELINE), "recent": list(climate.RECENT)},
            "climate": clim, "crops": crops, "rotations": rot, "now": now,
            "advice": texts.advice(lang, clim, crops, rot or {"items": []}, now),
            "region": texts.region(lang, plan["profile"]),
            "week_plan": _week_plan(plan, week_job, ensemble_job, irrigation, lat, lon),
        }

    quality = {"live": "full", "cache": "full", "monthly": "approx", "fallback": "approx"}.get(source, "skipped")
    datasets = []
    if data:
        datasets.append({"name": "NASA POWER", "detail": f"Daily API {data.get('api_version') or ''}".strip(),
                         "sources": data.get("sources", []), "parameters": nasa_client.PARAMS,
                         "resolution": "0.5 x 0.625 degree (meteorology), 1 degree (solar)",
                         "url": "https://power.larc.nasa.gov/", "nasa": True})
    if map_layers:
        datasets.append({"name": "NASA GIBS", "detail": "WMTS map layers",
                         "sources": sorted({l["id"] for l in map_layers if l["provider"] == "nasa_gibs"}),
                         "url": "https://earthdata.nasa.gov/gibs", "nasa": True})
    if soil_info:
        datasets.append({"name": "SoilGrids 2.0", "detail": "ISRIC, 250 m", "sources": [],
                         "url": "https://soilgrids.org/", "nasa": False})
    region_info = result.get("region") or {}
    if region_info.get("local"):
        datasets.append({"name": "MapSPAM 2020 (IFPRI)", "detail": "harvested area of 46 crops, ~10 km grid, by province",
                         "sources": [region_info["local"]["region"]], "url": "https://doi.org/10.7910/DVN/SWPENT", "nasa": False})
    if region_info.get("country"):
        datasets.append({"name": "FAOSTAT (FAO)", "detail": "national yield and producer price",
                         "sources": [region_info["country"]["name"]], "url": "https://www.fao.org/faostat/", "nasa": False})
    if us:
        if us.get("cdl"):
            datasets.append({"name": "USDA NASS Cropland Data Layer (30 m)", "detail": "crop grown on this field every year since 2008",
                             "sources": [f"{r['year']}: {r['name']}" for r in us["cdl"][-3:]], "nasa": False,
                             "url": "https://nassgeodata.gmu.edu/CropScape/"})
        if us.get("soil"):
            datasets.append({"name": "USDA NRCS SSURGO", "detail": "soil of the field: texture, water capacity, drainage, erodibility",
                             "sources": [us["soil"].get("component") or ""], "nasa": False,
                             "url": "https://websoilsurvey.nrcs.usda.gov/app/"})
        if us.get("yields"):
            datasets.append({"name": "USDA NASS QuickStats", "detail": "county yields of the last 5 survey years",
                             "sources": [(us.get("county") or {}).get("county", "")], "nasa": False,
                             "url": "https://quickstats.nass.usda.gov/"})
    if relief is not None:
        datasets.append({"name": "NASA SRTM (30 m)", "detail": "height, slope and aspect of the field",
                         "sources": ["SRTMGL1 via OpenTopoData"], "nasa": True,
                         "url": "https://www.earthdata.nasa.gov/data/instruments/srtm"})
    if sat is not None:
        datasets.append({"name": "Sentinel-2 10 m Land Cover (Impact Observatory, Microsoft, Esri)",
                         "detail": "what covers the ground at the point and 100 m around: water, built-up, ice, crops",
                         "sources": [sat["center"]], "url": "https://livingatlas.arcgis.com/landcover/", "nasa": False})
    if cover is not None:
        datasets.append({"name": "OpenStreetMap (Nominatim)", "detail": "land cover at the point: building, road, water, farmland",
                         "sources": [cover["osm"]] if cover.get("osm") else [],
                         "url": "https://nominatim.openstreetmap.org/", "nasa": False})
    if forecast:
        datasets.append({"name": "Open-Meteo", "detail": "weather forecast", "sources": [],
                         "url": "https://open-meteo.com/", "nasa": False})
    return {
        "location": {"lat": lat, "lon": lon},
        "source": source,
        "fallback": fallback,
        "data_fetched_at": data["fetched_at"] if data else None,
        "coverage": {
            "climate": quality, "crops": quality, "rotations": quality,
            "soil": "measured" if soil_info else "chosen" if soil != "auto" else "default",
            "forecast": "forecast" if forecast else "climatology" if data and data.get("resolution") == "daily" else "none",
            "map_layers": "available" if map_layers else "unavailable",
            "extra": sorted(extra),
        },
        "providers": statuses,
        "warnings": warnings,
        "datasets": datasets,
        "map_layers": map_layers,
        "soil": {"class": soil_class, "name": agro.CONFIG["soils"][soil_class]["name"],
                 "awc_mm_per_m": soil_water["awc_mm_per_m"], "water": soil_water, "details": soil_info},
        "extra": extra,
        "suitability": texts.suitability(lang, suit),
        **result,
        "disclaimer": texts.DISCLAIMER[lang],
        "timing_ms": round((time.perf_counter() - started) * 1000),
    }


# ---------- soil water forecast for one field ----------

@app.get("/api/water")
def water_forecast(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    crop: str = Query(..., description="Crop id from /api/options"),
    area_ha: float = Query(1.0, gt=0, le=100_000, description="Field area in hectares"),
    sow: date | None = Query(None, description="Sowing date; default: the computed sowing date of this point"),
    last_irrigation: date | None = Query(None, description="Last irrigation or soaking rain; makes the start exact"),
    soil: str = Query("auto", pattern="^(auto|light|medium|heavy)$"),
    irrigation: str = Query("furrow", pattern="^(furrow|sprinkler|drip)$"),
):
    """When the soil of this field dries out for the crop, and how much water it then needs.

    Daily FAO-56 root-zone balance over the last irrigation and the 16-day forecast; the evaporation
    (ET0, Penman-Monteith) is driven by sunshine, temperature, humidity and wind.
    """
    if crop not in agro.CROPS:
        raise HTTPException(422, "unknown crop")
    today = date.today()
    if last_irrigation and not (today - timedelta(days=water.MAX_PAST_DAYS) <= last_irrigation <= today):
        raise HTTPException(422, f"last_irrigation must be within the last {water.MAX_PAST_DAYS} days")
    lat, lon = round(lat, 4), round(lon, 4)
    crop_def = agro.CROPS[crop]
    data, _source, _fb, _err = _load_series(lat, lon)
    if data:  # sowing date and season length of THIS point
        crop_def = agro.localize(climate.prepare(data, geo.elevation(lat, lon)), crop_def)
    soil_class, measured = soil, None
    if soil == "auto":
        soil_p = next((p for p in providers.all_providers() if p["kind"] == "soil" and p["enabled"]), None)
        try:
            measured = providers.soil(soil_p, lat, lon) if soil_p else None
        except providers.ProviderDown:
            measured = None
        soil_class = (measured or {}).get("class", "medium")
    efficiency = agro.CONFIG["irrigation"][irrigation]["efficiency"]
    obs = observe.get(lat, lon)          # NASA observations that are ready (the rest load in the background)
    try:
        return water.plan(lat, lon, crop_def, agro.soil_water(soil_class, measured), efficiency, area_ha,
                          sow, last_irrigation, today, obs)
    except water.WeatherDown as exc:
        raise HTTPException(502, "Weather forecast is temporarily unavailable.") from exc


# ---------- NASA observations at the field ----------

@app.get("/api/observations")
def observations(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180)):
    """What NASA satellites measured at the point: SMAP soil moisture, GPM IMERG rain, GLDAS soil water
    anomaly, MODIS and HLS vegetation (NDVI), ECOSTRESS surface temperature and evapotranspiration,
    and OpenET in the western US. Products that are still loading say {"status": "loading"}:
    ask again in a few seconds."""
    products = observe.get(lat, lon)
    pending = [p for p, v in products.items() if v.get("status") == "loading"]
    return {"products": products, "pending": pending, "complete": not pending}


# Serve the website from the same server (one deploy, one link).
_frontend = Path(__file__).parent.parent / "frontend"
if _frontend.is_dir():
    app.mount("/", StaticFiles(directory=_frontend, html=True), name="frontend")
