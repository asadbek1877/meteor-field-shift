"""What NASA satellites have measured at the field: soil moisture, rain, vegetation, heat, evaporation.

Products (all read point-wise with the Earthdata token, see earthdata.py):
  smap      SMAP L4 (SPL4SMGP, 9 km): root-zone and surface soil moisture, surface temperature; last 30 days
  imerg     GPM IMERG Late daily (0.1 deg): observed rain of the last 60 days, heavy-rain days
  gldas     GLDAS Noah monthly (0.25 deg): soil moisture 0-100 cm and evaporation of the latest month,
            ranked against the same month since 2000 -> drought / wet anomaly
  modis     MODIS Terra MOD13Q1 (250 m, 16 days): NDVI of the last 3 years -> crop vigour by season
  hls       Harmonized Landsat Sentinel-2 vegetation indices (30 m): cloud-free NDVI of the last 60 days
  ecostress ECOSTRESS (70 m): land surface temperature and actual daily evapotranspiration, last 120 days
  openet    OpenET ensemble actual ET (western US, API key)
  gaez      FAO GAEZ v4 crop suitability index, 1981-2010 climate (global)
  prism     PRISM 4 km annual rain and temperature of the last 10 years (US)
  nwis      USGS stream gauge and groundwater well nearest to the field (US)
  cocorahs  CoCoRaHS volunteer rain gauges within 30 km (US)

The products take 5-40 s each, so they are fetched in the background and cached on disk; the API
returns what is ready and the page asks again until everything has arrived.
"""
from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import httpx

from . import earthdata as ed
from .physics import percentile

CACHE_DIR = Path(__file__).parent / "cache" / "obs"
TTL_S = {"smap": 6 * 3600, "imerg": 6 * 3600, "gldas": 7 * 86400, "modis": 3 * 86400, "hls": 12 * 3600,
         "ecostress": 12 * 3600, "openet": 30 * 86400, "gaez": 365 * 86400, "prism": 30 * 86400,
         "nwis": 6 * 3600, "cocorahs": 6 * 3600}
PRODUCTS = ("smap", "imerg", "gldas", "modis", "hls", "ecostress", "openet", "gaez", "prism", "nwis", "cocorahs")
NEEDS_TOKEN = {"smap", "imerg", "gldas", "modis", "hls", "ecostress"}
HEAVY_RAIN_MM = 20.0

_pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix="obs")
_reads = ThreadPoolExecutor(max_workers=8, thread_name_prefix="obs-read")
_jobs: dict[tuple, object] = {}
_lock = threading.Lock()


def _key(lat: float, lon: float) -> tuple[float, float]:
    return round(lat, 3), round(lon, 3)


def _path(product: str, lat: float, lon: float) -> Path:
    return CACHE_DIR / f"{product}_{lat:.3f}_{lon:.3f}.json"


def _load(product: str, lat: float, lon: float) -> dict | None:
    try:
        body = json.loads(_path(product, lat, lon).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if time.time() - body.get("_saved", 0) > TTL_S[product]:
        return None
    return body


def _save(product: str, lat: float, lon: float, body: dict) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _path(product, lat, lon).write_text(json.dumps({**body, "_saved": time.time()}), encoding="utf-8")
    except OSError:
        pass


def _parallel(fn, items) -> list:
    return list(_reads.map(fn, items))


def _num(x):
    try:
        v = float(x.ravel()[0]) if hasattr(x, "ravel") else float(x)
    except (TypeError, ValueError, IndexError):
        return None
    return None if v != v or abs(v) > 1e20 else v


# ---------- products ----------

def smap(lat: float, lon: float, today: date) -> dict:
    row, col = ed.ease2_9km(lat, lon)
    found = ed.granules("SPL4SMGP", today - timedelta(days=31), today)
    daily: dict[str, dict] = {}
    for g in found:                                   # one granule a day: the one closest to 12 UTC
        if g["opendap"] and (g["date"] not in daily or abs(int(g["time"][:2] or 0) - 12) < abs(int(daily[g["date"]]["time"][:2] or 0) - 12)):
            daily[g["date"]] = g

    def read(g):
        try:
            v = ed.dap(g["opendap"], f"/Geophysical_Data/sm_rootzone[{row}][{col}];/Geophysical_Data/sm_surface[{row}][{col}];"
                                     f"/Geophysical_Data/surface_temp[{row}][{col}]")
        except ed.EarthdataDown:
            return None
        get = lambda name: next((_num(a) for k, a in v.items() if k.endswith(name)), None)  # noqa: E731
        root, surf, temp = get("sm_rootzone"), get("sm_surface"), get("surface_temp")
        if root is None or root < 0:
            return None
        return {"date": g["date"], "rootzone": round(root, 3), "surface": round(surf, 3) if surf is not None else None,
                "surface_temp_c": round(temp - 273.15, 1) if temp and temp > 0 else None}
    series = sorted([r for r in _parallel(read, list(daily.values())) if r], key=lambda r: r["date"])
    if not series:
        return {"status": "empty"}
    last, first = series[-1], series[0]
    return {"status": "ok", "series": series, "latest": last,
            "change_30d": round(last["rootzone"] - first["rootzone"], 3),
            "grid": "9 km", "source": "NASA SMAP L4 (SPL4SMGP v8)"}


def imerg(lat: float, lon: float, today: date) -> dict:
    j, i = ed.imerg_index(lat, lon)
    found = [g for g in ed.granules("GPM_3IMERGDL", today - timedelta(days=60), today) if g["opendap"]]

    def read(g):
        try:
            v = ed.dap(g["opendap"], f"/precipitation[0][{j}][{i}]")
        except ed.EarthdataDown:
            return None
        p = next((_num(a) for k, a in v.items() if k.endswith("precipitation")), None)
        return {"date": g["date"], "rain_mm": round(p, 1)} if p is not None and p >= 0 else None
    series = sorted([r for r in _parallel(read, found) if r], key=lambda r: r["date"])
    if not series:
        return {"status": "empty"}
    rain = [r["rain_mm"] for r in series]
    last30 = [r["rain_mm"] for r in series if r["date"] >= (today - timedelta(days=30)).isoformat()]
    wet = max(series, key=lambda r: r["rain_mm"])
    return {"status": "ok", "series": series, "total_60d_mm": round(sum(rain), 1), "total_30d_mm": round(sum(last30), 1),
            "rain_days": sum(1 for x in rain if x >= 1), "heavy_days": sum(1 for x in rain if x >= HEAVY_RAIN_MM),
            "wettest": wet, "days_since_rain": next((k for k, r in enumerate(reversed(series)) if r["rain_mm"] >= 1), len(series)),
            "source": "NASA GPM IMERG Late daily (V07)"}


def gldas(lat: float, lon: float, today: date) -> dict:
    i, j = ed.gldas_index(lat, lon)
    found = [g for g in ed.granules("GLDAS_NOAH025_M", date(2000, 1, 1), today, limit=2000, version="2.1") if g["opendap"]]
    if not found:
        return {"status": "empty"}
    latest = found[-1]
    month = latest["date"][5:7]
    same = [g for g in found if g["date"][5:7] == month]

    def read(g):
        try:
            v = ed.dap(g["opendap"], f"/SoilMoi0_10cm_inst[0][{i}][{j}];/SoilMoi10_40cm_inst[0][{i}][{j}];"
                                     f"/SoilMoi40_100cm_inst[0][{i}][{j}];/Evap_tavg[0][{i}][{j}];/Rainf_f_tavg[0][{i}][{j}]")
        except ed.EarthdataDown:
            return None
        get = lambda name: next((_num(a) for k, a in v.items() if k.endswith(name)), None)  # noqa: E731
        parts = [get("SoilMoi0_10cm_inst"), get("SoilMoi10_40cm_inst"), get("SoilMoi40_100cm_inst")]
        if any(p is None or p < 0 for p in parts):
            return None
        secs = 86400 * ed.days_in_month(ed.parse_day(g["date"]))
        evap, rain = get("Evap_tavg"), get("Rainf_f_tavg")
        return {"date": g["date"][:7], "soil_mm_0_100": round(sum(parts), 1),       # kg/m2 = mm of water
                "evap_mm": round(evap * secs, 1) if evap is not None else None,
                "rain_mm": round(rain * secs, 1) if rain is not None else None}
    rows = sorted([r for r in _parallel(read, same) if r], key=lambda r: r["date"])
    if not rows:
        return {"status": "empty"}
    now = rows[-1]
    history = [r["soil_mm_0_100"] for r in rows[:-1]]
    rank = round(100 * sum(1 for x in history if x < now["soil_mm_0_100"]) / len(history)) if history else None
    return {"status": "ok", "latest": now, "same_month": rows, "percentile": rank,
            "normal_mm": round(percentile(history, 50), 1) if history else None,
            "class": None if rank is None else "very_dry" if rank <= 10 else "dry" if rank <= 30 else
            "wet" if rank >= 70 else "normal",
            "source": "NASA GLDAS-2.1 Noah, monthly 0.25°"}


def modis(lat: float, lon: float, today: date) -> dict:
    tile, row, col = ed.modis_sin(lat, lon)
    found = [g for g in ed.granules("MOD13Q1", today - timedelta(days=3 * 365 + 20), today, lat, lon) if g["opendap"]]
    base = "/MODIS_Grid_16DAY_250m_500m_VI/Data_Fields/"

    def read(g):
        try:
            v = ed.dap(g["opendap"], f"{base}_250m_16_days_NDVI[{row}][{col}];{base}_250m_16_days_pixel_reliability[{row}][{col}]")
        except ed.EarthdataDown:
            return None
        ndvi = next((_num(a) for k, a in v.items() if k.endswith("_NDVI")), None)
        rel = next((_num(a) for k, a in v.items() if k.endswith("reliability")), None)
        if ndvi is None or ndvi <= -3000 or (rel is not None and rel not in (0, 1)):
            return None                                # fill value, cloud, snow
        return {"date": g["date"], "ndvi": round(ndvi * 0.0001, 3)}
    series = sorted([r for r in _parallel(read, found) if r], key=lambda r: r["date"])
    if not series:
        return {"status": "empty"}
    peaks = {}
    for r in series:
        y = r["date"][:4]
        if r["ndvi"] > peaks.get(y, {"ndvi": -1})["ndvi"]:
            peaks[y] = r
    last = series[-1]
    doy = ed.parse_day(last["date"]).timetuple().tm_yday
    same = [r["ndvi"] for r in series[:-1] if abs(ed.parse_day(r["date"]).timetuple().tm_yday - doy) <= 8]
    return {"status": "ok", "series": series, "latest": last, "peaks": peaks, "tile": tile,
            "same_time_before": round(sum(same) / len(same), 3) if same else None,
            "source": "NASA MODIS Terra MOD13Q1 v061, 250 m"}


FMASK_BAD = 0b00111110     # bits 1-5: cloud, adjacent cloud, shadow, snow/ice, water


def hls(lat: float, lon: float, today: date) -> dict:
    found = (ed.granules("HLSS30_VI", today - timedelta(days=60), today, lat, lon) +
             ed.granules("HLSL30_VI", today - timedelta(days=60), today, lat, lon))
    found = sorted(found, key=lambda g: g["date"])[-14:]

    def read(g):
        ndvi_url = next((u for u in g["files"] if u.endswith("NDVI.tif")), None)
        mask_url = next((u for u in g["files"] if u.endswith("Fmask.tif")), None)
        if not ndvi_url or not mask_url:
            return None
        try:
            mask = ed.cog_point(mask_url, lat, lon)
            if mask is None or int(mask) & FMASK_BAD:
                return {"date": g["date"], "ndvi": None, "clear": False}
            ndvi = ed.cog_point(ndvi_url, lat, lon)
        except ed.EarthdataDown:
            return None
        if ndvi is None or not -1 <= ndvi <= 1:
            return {"date": g["date"], "ndvi": None, "clear": False}
        return {"date": g["date"], "ndvi": round(ndvi, 3), "clear": True,
                "sensor": "Sentinel-2" if ".S30." in g["id"] else "Landsat"}
    rows = sorted([r for r in _parallel(read, found) if r], key=lambda r: r["date"])
    clear = [r for r in rows if r["clear"]]
    if not clear:
        return {"status": "empty" if not rows else "cloudy", "scenes": len(rows)}
    last = clear[-1]
    state = "green" if last["ndvi"] >= 0.5 else "growing" if last["ndvi"] >= 0.3 else "sparse" if last["ndvi"] >= 0.15 else "bare"
    return {"status": "ok", "series": clear, "latest": last, "state": state, "scenes": len(rows),
            "source": "NASA HLS v2.0 vegetation indices (Landsat 8/9 + Sentinel-2), 30 m"}


def ecostress(lat: float, lon: float, today: date) -> dict:
    start = today - timedelta(days=120)
    def latest_unique(found, n):                       # one scene per date and overpass (versions repeat)
        seen = {}
        for g in sorted(found, key=lambda g: (g["date"], g["time"])):
            seen[(g["date"], g["time"][:5])] = g
        return list(seen.values())[-n:]
    lst = latest_unique(ed.granules("ECO_L2T_LSTE", start, today, lat, lon), 10)
    jet = latest_unique(ed.granules("ECO_L3T_JET", start, today, lat, lon), 12)

    def read_lst(g):
        u = next((x for x in g["files"] if x.endswith("_LST.tif")), None)
        c = next((x for x in g["files"] if x.endswith("_cloud.tif")), None)
        try:
            if c and (ed.cog_point(c, lat, lon) or 0) >= 1:
                return None
            v = ed.cog_point(u, lat, lon) if u else None
        except ed.EarthdataDown:
            return None
        return {"date": g["date"], "time_utc": g["time"][:5], "lst_c": round(v - 273.15, 1)} if v and v > 200 else None

    def read_et(g):
        u = next((x for x in g["files"] if x.endswith("_ETdaily.tif")), None)
        c = next((x for x in g["files"] if x.endswith("_cloud.tif")), None)
        try:
            if c and (ed.cog_point(c, lat, lon) or 0) >= 1:
                return None
            v = ed.cog_point(u, lat, lon) if u else None
        except ed.EarthdataDown:
            return None
        return {"date": g["date"], "et_mm": round(v, 2)} if v is not None and 0 <= v < 30 else None
    lst_rows = sorted([r for r in _parallel(read_lst, lst) if r], key=lambda r: r["date"])
    et_rows = sorted([r for r in _parallel(read_et, jet) if r], key=lambda r: r["date"])
    if not lst_rows and not et_rows:
        return {"status": "empty"}
    return {"status": "ok", "lst": lst_rows, "et": et_rows,
            "hottest": max(lst_rows, key=lambda r: r["lst_c"]) if lst_rows else None,
            "et_mean_mm": round(sum(r["et_mm"] for r in et_rows) / len(et_rows), 2) if et_rows else None,
            "source": "NASA ECOSTRESS L2T LSTE v3 and L3T JET, 70 m"}


OPENET_STATES = {"AZ", "CA", "CO", "ID", "KS", "MT", "NE", "NV", "NM", "ND", "OK", "OR", "SD", "TX", "UT", "WA", "WY"}


def openet(lat: float, lon: float, today: date) -> dict:
    """OpenET ensemble actual ET, monthly, last full growing season (western US; 100 requests a month)."""
    key = os.environ.get("OPENET_API_KEY")
    if not key:
        return {"status": "unavailable"}
    from . import usa
    where = usa.county(lat, lon)
    if not where or where["state"] not in OPENET_STATES:
        return {"status": "unavailable"}
    year = today.year if today.month >= 11 else today.year - 1
    body = {"date_range": [f"{year}-01-01", f"{year}-12-31"], "interval": "monthly", "geometry": [lon, lat],
            "model": "Ensemble", "variable": "ET", "reference_et": "gridMET", "units": "mm", "file_format": "JSON"}
    try:
        r = httpx.post("https://openet-api.org/raster/timeseries/point", json=body,
                       headers={"Authorization": key}, timeout=60)
        r.raise_for_status()
        rows = [{"month": x["time"][:7], "et_mm": x["et"]} for x in r.json() if x.get("et") is not None]
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return {"status": "failed"}
    return {"status": "ok" if rows else "empty", "monthly": rows, "year": year,
            "total_mm": round(sum(x["et_mm"] for x in rows), 0), "source": "OpenET Ensemble (Landsat-based), 30 m"}


# ---------- FAO GAEZ v4: crop suitability (global) ----------

GAEZ = "https://gaez-services.fao.org/server/rest/services/res05/ImageServer"
GAEZ_CROP = {   # library crop -> GAEZ crop name
    "winter_wheat": "Wheat", "spring_wheat": "Wheat", "cotton": "Cotton", "maize": "Maize", "rice": "Wetland rice",
    "soybean": "Soybean", "barley": "Barley", "potato": "White potato", "sunflower": "Sunflower",
    "rapeseed": "Rapeseed", "groundnut": "Groundnut", "dry_bean": "Phaseolus bean", "chickpea": "Chickpea",
    "sorghum": "Sorghum", "millet": "Pearl millet", "sugar_beet": "Sugarbeet", "tomato": "Tomato", "onion": "Onion",
    "alfalfa": "Alfalfa",
}
_gaez_ids: dict | None = None


def _gaez_catalog() -> dict:
    """(GAEZ crop, water supply) -> raster id of the suitability index, 1981-2010 climate, high inputs.

    Irrigated rasters are named by method for many crops (gravity, sprinkler, drip); they all count as
    "irrigated" and the best one is used."""
    global _gaez_ids
    if _gaez_ids is None:
        r = httpx.get(GAEZ + "/query", timeout=40, params={
            "where": "variable like 'Suitability index  range%current cropland%' and year='1981-2010' "
                     "and input_level='High' and water_supply in ('Irrigation','Gravity Irrigation',"
                     "'Sprinkler Irrigation','Drip Irrigation','Rainfed')",
            "outFields": "objectid,crop,water_supply", "returnGeometry": "false", "f": "json"})
        r.raise_for_status()
        _gaez_ids = {(f["attributes"]["crop"], f["attributes"]["water_supply"]): f["attributes"]["objectid"]
                     for f in r.json().get("features", [])}
    return _gaez_ids


def gaez(lat: float, lon: float, today: date) -> dict:
    try:
        ids = _gaez_catalog()
    except (httpx.HTTPError, ValueError) as exc:
        return {"status": "failed", "error": f"GAEZ: {type(exc).__name__}"}
    geom = json.dumps({"x": lon, "y": lat, "spatialReference": {"wkid": 4326}})

    def read(item):
        (crop, water), rid = item
        try:
            r = httpx.get(GAEZ + "/getSamples", timeout=30, params={
                "geometry": geom, "geometryType": "esriGeometryPoint", "returnFirstValueOnly": "true", "f": "json",
                "mosaicRule": json.dumps({"mosaicMethod": "esriMosaicLockRaster", "lockRasterIds": [rid]})})
            v = float(r.json()["samples"][0]["value"])
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
            return None
        return (crop, water, v if 0 <= v <= 10000 else None)
    wanted = {k: v for k, v in ids.items() if k[0] in set(GAEZ_CROP.values())}
    values: dict[tuple, float] = {}
    with ThreadPoolExecutor(max_workers=16) as pool:        # the FAO server answers each raster slowly
        samples = list(pool.map(read, list(wanted.items())))
    for x in samples:
        if not x or x[2] is None:
            continue
        crop, water, v = x
        kind = "Rainfed" if water.startswith("Rainfed") else "Irrigation"
        values[(crop, kind)] = max(v, values.get((crop, kind), -1))
    crops = {}
    for cid, name in GAEZ_CROP.items():
        irr, rain = values.get((name, "Irrigation")), values.get((name, "Rainfed"))
        if irr is None and rain is None:
            continue
        best = max(v for v in (irr, rain) if v is not None)
        crops[cid] = {"irrigated": irr, "rainfed": rain, "class": "very_high" if best >= 8500 else "high" if best >= 7000
                      else "good" if best >= 5500 else "medium" if best >= 4000 else "marginal" if best >= 2500
                      else "very_marginal" if best > 0 else "not_suitable"}
    if not crops:
        return {"status": "empty"}
    return {"status": "ok", "crops": crops, "scale": "0-10000",
            "source": "FAO GAEZ v4 suitability index, current cropland, 1981-2010, high inputs"}


# ---------- US only: PRISM climate, USGS NWIS water, CoCoRaHS rain ----------

PRISM_DIR = Path(__file__).parent / "cache" / "prism"
PRISM_URL = "https://services.nacse.org/prism/data/get/us/4km/{var}/{year}"
PRISM_YEARS = 10


def _us_state(lat: float, lon: float) -> dict | None:
    from . import geo, usa
    if geo.country_at(lat, lon) != "US":
        return None
    return usa.county(lat, lon)


def _prism_value(var: str, year: int, lat: float, lon: float) -> float | None:
    """One PRISM annual grid (4 km, whole US, about 2 MB) is downloaded once and kept for every US point."""
    import rasterio
    from rasterio.warp import transform
    path = PRISM_DIR / f"prism_{var}_{year}.zip"
    if not path.exists():
        try:
            r = httpx.get(PRISM_URL.format(var=var, year=year), timeout=120)
            r.raise_for_status()
            if not r.content.startswith(b"PK"):
                return None
            PRISM_DIR.mkdir(parents=True, exist_ok=True)
            path.write_bytes(r.content)
        except httpx.HTTPError:
            return None
    import zipfile
    try:
        name = next(n for n in zipfile.ZipFile(path).namelist() if n.endswith(".tif") or n.endswith(".bil"))
        with rasterio.open(f"zip://{path}!{name}") as ds:
            xs, ys = transform("EPSG:4326", ds.crs, [lon], [lat])
            v = float(list(ds.sample([(xs[0], ys[0])]))[0][0])
            return None if ds.nodata is not None and v == ds.nodata or v < -1000 else v
    except (OSError, StopIteration, zipfile.BadZipFile):
        return None


def prism(lat: float, lon: float, today: date) -> dict:
    if not _us_state(lat, lon):
        return {"status": "unavailable"}
    years = list(range(today.year - PRISM_YEARS, today.year))
    jobs = [(v, y) for v in ("ppt", "tmean") for y in years]
    values = dict(zip(jobs, _parallel(lambda j: _prism_value(j[0], j[1], lat, lon), jobs)))
    ppt = [values[("ppt", y)] for y in years if values[("ppt", y)] is not None]
    tmean = [values[("tmean", y)] for y in years if values[("tmean", y)] is not None]
    if not ppt and not tmean:
        return {"status": "empty"}
    return {"status": "ok", "years": [years[0], years[-1]],
            "rain_mm": round(sum(ppt) / len(ppt)) if ppt else None, "tmean_c": round(sum(tmean) / len(tmean), 1) if tmean else None,
            "by_year": [{"year": y, "rain_mm": values[("ppt", y)], "tmean_c": values[("tmean", y)]} for y in years],
            "source": "PRISM (Oregon State University), 4 km, terrain-aware"}


NWIS_SITE = "https://waterservices.usgs.gov/nwis/site/"
NWIS_DV = "https://waterservices.usgs.gov/nwis/dv/"
NWIS_STAT = "https://waterservices.usgs.gov/nwis/stat/"


def _rdb(text: str) -> list[dict]:
    lines = [l for l in text.splitlines() if l and not l.startswith("#")]
    if len(lines) < 3:
        return []
    head = lines[0].split("\t")
    return [dict(zip(head, l.split("\t"))) for l in lines[2:]]


def nwis(lat: float, lon: float, today: date) -> dict:
    """Nearest USGS stream gauge (and groundwater well): latest daily flow against its long-term percentiles."""
    if not _us_state(lat, lon):
        return {"status": "unavailable"}
    import math
    out = {}
    for kind, param, site_type in (("stream", "00060", "ST"), ("groundwater", "72019", "GW")):
        try:
            sites = _rdb(httpx.get(NWIS_SITE, timeout=30, params={
                "format": "rdb", "bBox": f"{lon - 0.4:.3f},{lat - 0.3:.3f},{lon + 0.4:.3f},{lat + 0.3:.3f}",
                "parameterCd": param, "siteType": site_type, "siteStatus": "active", "hasDataTypeCd": "dv"}).text)
        except httpx.HTTPError:
            continue
        if not sites:
            continue
        dist = lambda s: math.hypot(float(s["dec_lat_va"]) - lat, (float(s["dec_long_va"]) - lon) * math.cos(math.radians(lat)))  # noqa: E731
        site = min(sites, key=dist)
        try:
            dv = _rdb(httpx.get(NWIS_DV, timeout=30, params={"format": "rdb", "sites": site["site_no"], "parameterCd": param,
                                                             "startDT": (today - timedelta(days=30)).isoformat()}).text)
        except httpx.HTTPError:
            continue
        col = next((k for k in (dv[0] if dv else {}) if k.endswith(f"_{param}_00003")), None)
        rows = [(r["datetime"], float(r[col])) for r in dv if col and r.get(col, "").replace(".", "", 1).isdigit()]
        if not rows:
            continue
        last_date, last = rows[-1]
        pct = None
        try:
            st = _rdb(httpx.get(NWIS_STAT, timeout=30, params={"format": "rdb", "sites": site["site_no"], "parameterCd": param,
                                                               "statReportType": "daily", "statTypeCd": "p10,p25,p50,p75,p90"}).text)
            d = date.fromisoformat(last_date)
            day = next((r for r in st if int(r["month_nu"]) == d.month and int(r["day_nu"]) == d.day), None)
            if day:
                marks = [(10, float(day["p10_va"])), (25, float(day["p25_va"])), (50, float(day["p50_va"])),
                         (75, float(day["p75_va"])), (90, float(day["p90_va"]))]
                pct = next((p for p, v in marks if last <= v), 95)
                if kind == "groundwater":
                    pct = 100 - pct                     # depth below surface: deeper is drier
        except (httpx.HTTPError, ValueError, KeyError):
            pass
        out[kind] = {"site": site["site_no"], "name": site["station_nm"], "km": round(dist(site) * 111),
                     "date": last_date, "value": last, "unit": "ft3/s" if kind == "stream" else "ft below surface",
                     "percentile_band": pct}
    if not out:
        return {"status": "empty"}
    return {"status": "ok", **out, "source": "USGS National Water Information System"}


COCORAHS = "https://data.cocorahs.org/export/exportreports.aspx"
COCORAHS_KM = 30


def cocorahs(lat: float, lon: float, today: date) -> dict:
    """Volunteer rain gauges within 30 km: daily totals of the last 14 days (the ground truth for IMERG)."""
    where = _us_state(lat, lon)
    if not where:
        return {"status": "unavailable"}
    import csv
    import io
    import math
    start = today - timedelta(days=14)
    try:
        r = httpx.get(COCORAHS, timeout=60, params={
            "ReportType": "Daily", "dtf": 1, "Format": "CSV", "State": where["state"], "ReportDateType": "reportdate",
            "StartDate": start.strftime("%m/%d/%Y"), "EndDate": today.strftime("%m/%d/%Y"), "TimesInGMT": "False"})
        r.raise_for_status()
        rows = list(csv.DictReader(io.StringIO(r.text)))
    except (httpx.HTTPError, csv.Error):
        return {"status": "failed"}
    by_station: dict[str, dict] = {}
    for row in rows:
        try:
            la, lo = float(row["Latitude"]), float(row["Longitude"])
            km = 111 * math.hypot(la - lat, (lo - lon) * math.cos(math.radians(lat)))
            if km > COCORAHS_KM:
                continue
            amount = row["TotalPrecipAmt"].strip()
            mm = 0.0 if amount in ("T", "0", "0.00") else float(amount) * 25.4
        except (KeyError, ValueError):
            continue
        s = by_station.setdefault(row["StationNumber"], {"name": row["StationName"], "km": round(km, 1), "days": {}})
        s["days"][row["ObservationDate"].strip()] = round(mm, 1)
    if not by_station:
        return {"status": "empty"}
    stations = sorted(by_station.values(), key=lambda s: s["km"])[:5]
    dates = sorted({d for s in stations for d in s["days"]})
    daily = [{"date": d, "rain_mm": round(sum(s["days"][d] for s in stations if d in s["days"]) /
                                          sum(1 for s in stations if d in s["days"]), 1)} for d in dates]
    return {"status": "ok", "stations": [{"name": s["name"], "km": s["km"], "total_mm": round(sum(s["days"].values()), 1)}
                                         for s in stations],
            "daily": daily, "total_mm": round(sum(d["rain_mm"] for d in daily), 1),
            "source": "CoCoRaHS volunteer rain gauges"}


FUNCS = {"smap": smap, "imerg": imerg, "gldas": gldas, "modis": modis, "hls": hls, "ecostress": ecostress,
         "openet": openet, "gaez": gaez, "prism": prism, "nwis": nwis, "cocorahs": cocorahs}


# ---------- background jobs ----------

def _run(product: str, lat: float, lon: float) -> None:
    try:
        result = FUNCS[product](lat, lon, date.today())
    except ed.EarthdataDown as exc:
        result = {"status": "failed", "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 - one broken product must not stop the others
        result = {"status": "failed", "error": f"{type(exc).__name__}"}
    if result.get("status") in ("ok", "empty", "cloudy", "unavailable"):
        _save(product, lat, lon, result)
    with _lock:
        _jobs[(product, lat, lon)] = result


def get(lat: float, lon: float, start: bool = True) -> dict:
    """{product: result or {"status": "loading"}}; starts the missing fetches in the background."""
    lat, lon = _key(lat, lon)
    out = {}
    for p in PRODUCTS:
        if p in NEEDS_TOKEN and not ed.token():
            out[p] = {"status": "unavailable", "error": "EARTHDATA_TOKEN is not set"}
            continue
        cached = _load(p, lat, lon)
        if cached:
            out[p] = cached
            continue
        with _lock:
            job = _jobs.get((p, lat, lon))
            if job is None and start:
                _jobs[(p, lat, lon)] = "running"
                _pool.submit(_run, p, lat, lon)
                job = "running"
        if job == "running" or job is None:
            out[p] = {"status": "loading"}
        else:
            out[p] = job
            if job.get("status") == "failed":           # try again on the next request
                with _lock:
                    _jobs.pop((p, lat, lon), None)
    return out
