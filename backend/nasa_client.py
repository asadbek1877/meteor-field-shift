"""NASA POWER client.

fetch_daily   main path: daily data from 1991 to yesterday, 4 parallel requests (about 3 s)
fetch_monthly fallback: one small monthly request, expanded to the same daily shape

Docs: https://power.larc.nasa.gov/docs/services/api/temporal/
Both return the same structure, so the analysis code has a single input format:
    {"lat", "lon", "elevation", "resolution": "daily"|"monthly", "start": "1991-01-01",
     "fetched_at", "sources", "api_version", "params": {name: [value or None per day]}}
"""
from __future__ import annotations

import calendar
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import httpx

BASE = "https://power.larc.nasa.gov/api/temporal"
START = date(1991, 1, 1)
TIMEOUT_S = float(os.getenv("POWER_TIMEOUT", "8"))

# T2M, T2M_MAX, T2M_MIN  air temperature at 2 m: daily mean, maximum, minimum (C)
# PRECTOTCORR            precipitation (mm/day)
# RH2M                   relative humidity at 2 m (%)
# WS2M                   wind speed at 2 m (m/s)
# ALLSKY_SFC_SW_DWN      solar radiation at the surface (MJ/m2/day)
# GWETROOT               root zone soil wetness, fraction 0..1 (model, not a satellite measurement)
PARAMS = ["T2M", "T2M_MAX", "T2M_MIN", "PRECTOTCORR", "RH2M", "WS2M", "ALLSKY_SFC_SW_DWN", "GWETROOT"]
_MONTHLY = ["T2M", "T2M_RANGE", "PRECTOTCORR", "RH2M", "WS2M", "ALLSKY_SFC_SW_DWN", "GWETROOT"]

_client = httpx.Client(timeout=TIMEOUT_S, headers={"User-Agent": "field-shift-app"})


class PowerError(Exception):
    """NASA POWER is unreachable, too slow, or returned something unusable."""


def _get(kind: str, lat: float, lon: float, params: list[str], start: str, end: str) -> dict:
    query = {"parameters": ",".join(params), "community": "AG", "latitude": lat,
             "longitude": lon, "start": start, "end": end, "format": "JSON"}
    url = f"{BASE}/{kind}/point"
    try:
        try:
            resp = _client.get(url, params=query)
        except httpx.ConnectError:
            resp = _client.get(url, params=query)  # one retry for a network blip
        resp.raise_for_status()
        body = resp.json()
        body["properties"]["parameter"]  # must exist
        return body
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise PowerError(f"{type(exc).__name__}: {exc}") from exc


def _meta(body: dict, lat: float, lon: float, resolution: str) -> dict:
    header = body.get("header", {})
    coords = body.get("geometry", {}).get("coordinates", [])
    return {
        "lat": lat,
        "lon": lon,
        "elevation": coords[2] if len(coords) > 2 and coords[2] is not None else 0.0,
        "resolution": resolution,
        "start": START.isoformat(),
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "api_version": header.get("api", {}).get("version"),
        "sources": header.get("sources", []),
    }


def fetch_daily(lat: float, lon: float, today: date | None = None) -> dict:
    end = (today or date.today()) - timedelta(days=1)
    total = (end - START).days + 1
    step = total // 4 + 1
    ranges = []
    for k in range(4):
        a = START + timedelta(days=k * step)
        b = min(end, a + timedelta(days=step - 1))
        if a <= end:
            ranges.append((a, b))
    with ThreadPoolExecutor(max_workers=4) as pool:
        bodies = list(pool.map(
            lambda r: _get("daily", lat, lon, PARAMS, r[0].strftime("%Y%m%d"), r[1].strftime("%Y%m%d")),
            ranges))

    fill = bodies[0].get("header", {}).get("fill_value", -999.0)
    params = {name: [None] * total for name in PARAMS}
    for body in bodies:
        for name in PARAMS:
            series = params[name]
            for key, value in (body["properties"]["parameter"].get(name) or {}).items():
                if value is None or value == fill:
                    continue
                idx = (date(int(key[:4]), int(key[4:6]), int(key[6:8])) - START).days
                if 0 <= idx < total:
                    series[idx] = value
    if not any(v is not None for v in params["T2M"]):
        raise PowerError("no temperature data for this point")
    sources = sorted({s for b in bodies for s in b.get("header", {}).get("sources", [])})
    return {**_meta(bodies[-1], lat, lon, "daily"), "sources": sources, "params": params}


def fetch_monthly(lat: float, lon: float, today: date | None = None) -> dict:
    """Fallback. Every day of a month gets the monthly mean, so day-level indicators are approximate."""
    end_year = (today or date.today()).year - 1
    body = _get("monthly", lat, lon, _MONTHLY, str(START.year), str(end_year))
    raw = body["properties"]["parameter"]
    fill = body.get("header", {}).get("fill_value", -999.0)
    params = {name: [] for name in PARAMS}

    def value(name, key):
        v = (raw.get(name) or {}).get(key)
        return None if v is None or v == fill else v

    for year in range(START.year, end_year + 1):
        for month in range(1, 13):
            key = f"{year}{month:02d}"
            days = calendar.monthrange(year, month)[1]
            t, rng = value("T2M", key), value("T2M_RANGE", key)
            row = {
                "T2M": t,
                "T2M_MAX": t + rng / 2 if t is not None and rng is not None else None,
                "T2M_MIN": t - rng / 2 if t is not None and rng is not None else None,
                "PRECTOTCORR": value("PRECTOTCORR", key),
                "RH2M": value("RH2M", key),
                "WS2M": value("WS2M", key),
                "ALLSKY_SFC_SW_DWN": value("ALLSKY_SFC_SW_DWN", key),
                "GWETROOT": value("GWETROOT", key),
            }
            for name in PARAMS:
                params[name].extend([row[name]] * days)
    if not any(v is not None for v in params["T2M"]):
        raise PowerError("no temperature data for this point")
    return {**_meta(body, lat, lon, "monthly"), "params": params}
