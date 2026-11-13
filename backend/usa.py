"""United States detail: when the point is in the US, official USDA field-level data replace the global estimates.

  county   FCC Census Area API: state and county of the point (needed by NASS)
  CDL      USDA NASS Cropland Data Layer, 30 m, every year since 2008 (CropScape GetCDLValue):
           what was actually grown on THIS field each year -> the farmer's real rotation
  SSURGO   USDA NRCS Soil Data Access: the dominant soil component of the map unit under the point,
           its texture, organic matter, pH, available water capacity, drainage, hydrologic group and
           erodibility (K factor) -> replaces the 250 m SoilGrids estimate
  NASS     USDA NASS QuickStats (API key): county yields of the last 5 survey years -> replaces the
           province yield; state level when the county value is withheld

Everything is cached on disk: these values change once a year at most.
"""
from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

CACHE_FILE = Path(__file__).parent / "cache" / "usa.json"
FCC = "https://geo.fcc.gov/api/census/area"
CDL = "https://nassgeodata.gmu.edu/axis2/services/CDLService/GetCDLValue"
SDA = "https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest"
NASS = "https://quickstats.nass.usda.gov/api/api_GET/"
CDL_YEARS = range(2008, 2026)
NASS_YEARS = 5
ACRE_HA = 0.40468564

# CDL class -> library crop (double crops are listed as "first + second")
CDL_CROPS = {
    1: ["maize"], 2: ["cotton"], 3: ["rice"], 4: ["sorghum"], 5: ["soybean"], 6: ["sunflower"], 10: ["groundnut"],
    21: ["barley"], 22: ["spring_wheat"], 23: ["spring_wheat"], 24: ["winter_wheat"], 26: ["winter_wheat", "soybean"],
    29: ["millet"], 31: ["rapeseed"], 36: ["alfalfa"], 41: ["sugar_beet"], 42: ["dry_bean"], 43: ["potato"],
    49: ["onion"], 51: ["chickpea"], 52: ["lentil"], 54: ["tomato"], 225: ["winter_wheat", "maize"],
    226: ["maize"], 228: ["maize"], 236: ["winter_wheat", "sorghum"], 237: ["barley", "maize"],
    238: ["winter_wheat", "cotton"], 239: ["soybean", "cotton"], 240: ["soybean"], 241: ["maize", "soybean"],
    254: ["barley", "soybean"],
}
# NASS commodity, short_desc start, unit -> (crop, kg per unit); bushel weights are the USDA standard ones
NASS_YIELD = {
    "CORN, GRAIN - YIELD, MEASURED IN BU / ACRE": ("maize", 25.40),
    "SOYBEANS - YIELD, MEASURED IN BU / ACRE": ("soybean", 27.22),
    "WHEAT, WINTER - YIELD, MEASURED IN BU / ACRE": ("winter_wheat", 27.22),
    "WHEAT, SPRING, (EXCL DURUM) - YIELD, MEASURED IN BU / ACRE": ("spring_wheat", 27.22),
    "SORGHUM, GRAIN - YIELD, MEASURED IN BU / ACRE": ("sorghum", 25.40),
    "BARLEY - YIELD, MEASURED IN BU / ACRE": ("barley", 21.77),
    "COTTON, UPLAND - YIELD, MEASURED IN LB / ACRE": ("cotton", 0.4536 / 0.38),   # lint -> seed cotton (38 % lint)
    "RICE - YIELD, MEASURED IN LB / ACRE": ("rice", 0.4536),
    "SUNFLOWER - YIELD, MEASURED IN LB / ACRE": ("sunflower", 0.4536),
    "PEANUTS - YIELD, MEASURED IN LB / ACRE": ("groundnut", 0.4536),
    "SUGARBEETS - YIELD, MEASURED IN TONS / ACRE": ("sugar_beet", 907.18),
    "BEANS, DRY EDIBLE, (EXCL CHICKPEAS) - YIELD, MEASURED IN LB / ACRE": ("dry_bean", 0.4536),
}

_client = httpx.Client(timeout=20, headers={"User-Agent": "field-shift-app"})
_cache: dict | None = None
_lock = threading.Lock()


def _cached(key: str, load):
    global _cache
    with _lock:
        if _cache is None:
            try:
                _cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                _cache = {}
        if key in _cache:
            return _cache[key]
    value = load()
    if value is not None:
        with _lock:
            _cache[key] = value
            try:
                CACHE_FILE.parent.mkdir(exist_ok=True)
                CACHE_FILE.write_text(json.dumps(_cache), encoding="utf-8")
            except OSError:
                pass
    return value


# ---------- county ----------

def county(lat: float, lon: float) -> dict | None:
    def load():
        try:
            r = _client.get(FCC, params={"lat": lat, "lon": lon, "format": "json"})
            r.raise_for_status()
            res = r.json().get("results") or []
        except (httpx.HTTPError, ValueError):
            return None
        if not res:
            return None
        x = res[0]
        return {"state": x["state_code"], "state_name": x["state_name"], "state_fips": x["state_fips"],
                "county_fips": x["county_fips"], "county": x["county_name"]}
    return _cached(f"county|{round(lat, 3)}|{round(lon, 3)}", load)


# ---------- Cropland Data Layer ----------

def _albers(lat: float, lon: float) -> tuple[float, float]:
    """WGS 84 -> NAD83 / Conus Albers (EPSG:5070), the grid of the CDL."""
    from rasterio.warp import transform
    xs, ys = transform("EPSG:4326", "EPSG:5070", [lon], [lat])
    return xs[0], ys[0]


def _cdl_year(x: float, y: float, year: int):
    try:
        r = _client.get(CDL, params={"year": year, "x": round(x, 1), "y": round(y, 1)})
        r.raise_for_status()
        text = r.text
        value = int(text.split("value:")[1].split(",")[0])
        category = text.split('category: "')[1].split('"')[0]
        return {"year": year, "code": value, "name": category, "crops": CDL_CROPS.get(value, [])}
    except (httpx.HTTPError, ValueError, IndexError):
        return None


def cdl_history(lat: float, lon: float) -> list[dict] | None:
    """[{year, code, name, crops}] for every CDL year, oldest first."""
    def load():
        x, y = _albers(lat, lon)
        with ThreadPoolExecutor(max_workers=6) as pool:
            rows = [r for r in pool.map(lambda yr: _cdl_year(x, y, yr), CDL_YEARS) if r]
        return sorted(rows, key=lambda r: r["year"]) or None
    return _cached(f"cdl|{round(lat, 4)}|{round(lon, 4)}", load)


def rotation_from_history(history: list[dict], years: int = 8) -> dict | None:
    """The farmer's rotation from the CDL years.

    -> {"years": [[crop], ...], "exact": bool}. A cycle of 1-3 years that repeats in at least 70 % of the
    last years is "exact" (maize, soybean, maize, soybean -> maize - soybean). Real fields are rarely that
    regular, so otherwise the crops grown at least twice are taken in the order they last appeared
    (sorghum 2023, soybean 2024, wheat 2025 -> sorghum - soybean - wheat).
    """
    seq = [tuple(r["crops"]) for r in (history or [])[-years:] if r["crops"]]
    if len(seq) < 3:
        return None
    for period in (1, 2, 3):
        pattern = seq[-period:]
        fits = sum(1 for k, s in enumerate(reversed(seq)) if s == pattern[-1 - (k % period)])
        if fits / len(seq) >= 0.7 and (period == 1 or len(set(pattern)) > 1):
            return {"years": [list(p) for p in pattern], "exact": True}
    counts: dict[tuple, int] = {}
    last_seen: dict[tuple, int] = {}
    for k, s in enumerate(seq):
        counts[s] = counts.get(s, 0) + 1
        last_seen[s] = k
    main = sorted((s for s in counts if counts[s] >= 2), key=lambda s: last_seen[s])[-3:]
    return {"years": [list(s) for s in main], "exact": False} if len(main) >= 2 else None


# ---------- SSURGO ----------

def ssurgo(lat: float, lon: float) -> dict | None:
    """Dominant soil component under the point, topsoil (0-30 cm) texture and root-zone (0-100 cm) water capacity."""
    def load():
        query = f"""
            SELECT c.cokey, c.compname, c.comppct_r, c.slope_r, c.hydgrp, c.drainagecl, mu.muname,
                   ch.hzdept_r, ch.hzdepb_r, ch.sandtotal_r, ch.claytotal_r, ch.om_r, ch.awc_r, ch.kwfact, ch.ph1to1h2o_r
            FROM mapunit mu
            JOIN component c ON c.mukey = mu.mukey
            JOIN chorizon ch ON ch.cokey = c.cokey
            WHERE mu.mukey IN (SELECT mukey FROM SDA_Get_Mukey_from_intersection_with_WktWgs84('point({lon} {lat})'))
              AND c.majcompflag = 'Yes'
            ORDER BY c.comppct_r DESC, c.cokey, ch.hzdept_r"""
        try:
            r = _client.post(SDA, json={"format": "JSON+COLUMNNAME", "query": query})
            r.raise_for_status()
            table = r.json().get("Table") or []
        except (httpx.HTTPError, ValueError):
            return None
        if len(table) < 2:
            return None
        head, rows = table[0], [dict(zip(table[0], row)) for row in table[1:]]
        cokey = rows[0]["cokey"]
        hz = [h for h in rows if h["cokey"] == cokey]
        num = lambda v: float(v) if v not in (None, "") else None  # noqa: E731

        def weighted(key, bottom):
            total = weight = 0.0
            for h in hz:
                top, bot, v = num(h["hzdept_r"]), num(h["hzdepb_r"]), num(h[key])
                if top is None or bot is None or v is None or top >= bottom:
                    continue
                w = min(bot, bottom) - top
                total, weight = total + v * w, weight + w
            return total / weight if weight else None
        sand, clay, om = weighted("sandtotal_r", 30), weighted("claytotal_r", 30), weighted("om_r", 30)
        awc = weighted("awc_r", 100)                                  # cm/cm
        c = rows[0]
        return {
            "class": "light" if (sand or 0) >= 65 else "heavy" if (clay or 0) >= 35 else "medium",
            "sand_pct": round(sand, 1) if sand is not None else None,
            "clay_pct": round(clay, 1) if clay is not None else None,
            "silt_pct": round(100 - sand - clay, 1) if sand is not None and clay is not None else None,
            "organic_matter_pct": round(om, 2) if om is not None else None,
            "organic_carbon_g_kg": round(om * 10 / 1.724, 1) if om is not None else None,
            "ph": round(weighted("ph1to1h2o_r", 30), 1) if weighted("ph1to1h2o_r", 30) else None,
            "awc_mm_per_m": round(awc * 1000) if awc else None,
            "k_factor": num(hz[0]["kwfact"]) if hz else None,
            "hydrologic_group": c["hydgrp"], "drainage": c["drainagecl"], "slope_pct": num(c["slope_r"]),
            "component": c["compname"], "share_pct": num(c["comppct_r"]), "map_unit": c["muname"],
            "depth_cm": "0-30", "source": "USDA NRCS SSURGO (Soil Data Access)",
        }
    return _cached(f"ssurgo|{round(lat, 4)}|{round(lon, 4)}", load)


# ---------- NASS QuickStats ----------

def nass_yields(where: dict) -> dict | None:
    """crop id -> {"t_ha", "years", "level"}: mean of the last NASS_YEARS survey years, county else state."""
    key = os.environ.get("NASS_API_KEY")
    if not key or not where:
        return None

    def load():
        out: dict[str, dict] = {}
        for level in ("COUNTY", "STATE"):
            params = {"key": key, "source_desc": "SURVEY", "statisticcat_desc": "YIELD", "agg_level_desc": level,
                      "state_fips_code": where["state_fips"], "year__GE": 2015, "format": "JSON"}
            if level == "COUNTY":
                params["county_code"] = where["county_fips"][-3:]
            try:
                r = _client.get(NASS, params=params, timeout=40)
                if r.status_code != 200:
                    continue
                rows = r.json().get("data", [])
            except (httpx.HTTPError, ValueError):
                continue
            by_crop: dict[str, dict[int, float]] = {}
            for row in rows:
                spec = NASS_YIELD.get(row.get("short_desc", ""))
                value = str(row.get("Value", "")).replace(",", "").strip()
                if not spec or row.get("reference_period_desc") != "YEAR" or not value.replace(".", "").isdigit():
                    continue
                crop, kg = spec
                by_crop.setdefault(crop, {})[int(row["year"])] = float(value) * kg / 1000 / ACRE_HA
            for crop, series in by_crop.items():
                if crop in out:
                    continue
                last = sorted(series)[-NASS_YEARS:]
                out[crop] = {"t_ha": round(sum(series[y] for y in last) / len(last), 2),
                             "years": [last[0], last[-1]], "level": level.lower()}
        return out or None
    return _cached(f"nass|{where['county_fips']}", load)


def detail(lat: float, lon: float) -> dict:
    """Everything above for one point, fetched in parallel. Missing parts are None."""
    with ThreadPoolExecutor(max_workers=3) as pool:
        where_job = pool.submit(county, lat, lon)
        cdl_job = pool.submit(cdl_history, lat, lon)
        soil_job = pool.submit(ssurgo, lat, lon)
        where = where_job.result()
        yields = nass_yields(where) if where else None
        history = cdl_job.result()
        soil = soil_job.result()
    return {"county": where, "cdl": history, "rotation": rotation_from_history(history) if history else None,
            "soil": soil, "yields": yields}
