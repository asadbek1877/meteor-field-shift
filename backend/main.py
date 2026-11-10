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
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import agro, climate, nasa_client, providers, store, texts

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
    soil_class = soil if soil != "auto" else (soil_info or {}).get("class", "medium")
    soil_name = agro.CONFIG["soils"][soil_class]["name"][lang]
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
    result = {"periods": None, "climate": None, "crops": None, "rotations": None, "now": None, "advice": None}
    if data:
        days = climate.prepare(data)
        if not any(v is not None for v in days.soil[-400:]):
            warn("nasa_power", "warning", msg["not_land"])  # no soil wetness: sea, lake or ice
        clim = climate.analyze(days)
        field = agro.Field(days, soil_class, irrigation)
        crops = field.crops()
        rot = field.rotations(current, custom_years,
                              {"water": w_water, "income": w_income, "soil": w_soil, "risk": w_risk})
        for it in rot["items"]:
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
            "week": field.week(week_basis["et0_7d_mm"], week_basis["rain_7d_mm"], date.today()) if week_basis else [],
        }
        result = {
            "periods": {"baseline": list(climate.BASELINE), "recent": list(climate.RECENT)},
            "climate": clim, "crops": crops, "rotations": rot, "now": now,
            "advice": texts.advice(lang, clim, crops, rot, now),
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
                 "awc_mm_per_m": agro.CONFIG["soils"][soil_class]["awc_mm_per_m"], "details": soil_info},
        "extra": extra,
        **result,
        "disclaimer": texts.DISCLAIMER[lang],
        "timing_ms": round((time.perf_counter() - started) * 1000),
    }


# Serve the website from the same server (one deploy, one link).
_frontend = Path(__file__).parent.parent / "frontend"
if _frontend.is_dir():
    app.mount("/", StaticFiles(directory=_frontend, html=True), name="frontend")
