"""Soil water forecast for one field: when the soil dries out for the crop and how much water it needs.

Method: FAO-56 chapter 7, dual crop coefficient with a daily water balance of two layers.

  ET0     reference evapotranspiration, FAO-56 Penman-Monteith (Open-Meteo), driven by solar radiation,
          air temperature, humidity and wind: more sun and heat -> more water leaves the field
  T       transpiration = Ks x Kcb x ET0; Kcb follows the crop's growth stage, Ks drops when the roots run dry
  E       evaporation from the soil surface = Ke x ET0. It is high while the top 10 cm are wet (after rain
          or irrigation) and the canopy is open, and stops when that layer is dry: this is the part that
          sun and ground heat take straight from the surface (FAO-56 eq. 71-77)
  Zr      root depth grows from 0.15 m at sowing to the crop's full depth at the end of development
  TAW/RAW water the root zone can hold / the part the crop takes up without stress (p x TAW).
          When the depletion passes RAW the soil is "dry for this crop": irrigate back to field capacity.

Where the numbers come from:
  past days     Open-Meteo weather analysis from the last irrigation (soil at field capacity that day).
                Without that date the balance starts at sowing (soil assumed moist, or the crop would not
                have emerged) or 60 days back, and assumes NO irrigation since: right for rain-fed fields,
                and the result says so.
  next 16 days  every member of two ensemble forecasts (ECMWF IFS 51 members, NCEP GEFS 31 members) is
                run through the balance. The dry date is given as the 10 % / 50 % / 90 % quantiles of the
                members, with the probability of drying within 7 and 16 days, instead of one guessed date.
  soil          field capacity and wilting point from the measured texture (SoilGrids + Saxton-Rawls 2006)
                when available, otherwise FAO-56 values of the chosen soil class.

Model soil moisture is not used: weather models do not know about irrigation (an irrigated oasis shows
0.0 m3/m3), so it would move the start in the wrong direction exactly where irrigation matters most.
"""
from __future__ import annotations

import threading
import time
from datetime import date, timedelta

import httpx

from . import agro
from .physics import percentile

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
ERA5 = "https://archive-api.open-meteo.com/v1/era5"     # ECMWF ERA5 reanalysis, about 5 days behind
ERA5_LAG_DAYS = 6
ENSEMBLE = "https://ensemble-api.open-meteo.com/v1/ensemble"
ENSEMBLE_MODELS = "ecmwf_ifs025,gfs_seamless"
FORECAST_DAYS = 16
MAX_PAST_DAYS = 60
MIN_ROOT_M = 0.15
CACHE_TTL_S = 900
FAR_DAYS = 30        # a dry date further than this is not given as a date: rain and snow in between are unknown
KC_MIN = 0.15        # dry bare soil (FAO-56 eq. 76)
KC_MAX = 1.20        # upper limit of evaporation + transpiration right after wetting (FAO-56 eq. 72)
MIN_MEMBERS = 10     # fewer ensemble members than this: fall back to fixed rain scenarios
FALLBACK_RAIN = {"dry": 0.5, "expected": 1.0, "wet": 1.3}

_client = httpx.Client(timeout=12, headers={"User-Agent": "field-shift-app"})
_cache: dict[tuple, tuple[float, object]] = {}
_lock = threading.Lock()


class WeatherDown(Exception):
    pass


# ---------- weather ----------

def _cached(key: tuple, load):
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < CACHE_TTL_S:
            return hit[1]
    value = load()
    with _lock:
        if len(_cache) > 200:
            _cache.clear()
        _cache[key] = (time.time(), value)
    return value


def fetch(lat: float, lon: float, past_days: int) -> dict:
    """Daily weather (past days + 16-day forecast) and the daily maximum of the ground surface temperature."""
    def load():
        params = {
            "latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": FORECAST_DAYS, "past_days": past_days,
            "daily": "precipitation_sum,precipitation_probability_max,et0_fao_evapotranspiration,"
                     "shortwave_radiation_sum,temperature_2m_max,temperature_2m_min",
            "hourly": "soil_temperature_0cm,soil_temperature_6cm",
        }
        try:
            r = _client.get(OPEN_METEO, params=params)
            r.raise_for_status()
            body = r.json()
            daily, hourly = body["daily"], body["hourly"]
            ground: dict[str, float] = {}
            seed: dict[str, list] = {}
            for stamp, value, v6 in zip(hourly["time"], hourly["soil_temperature_0cm"],
                                        hourly.get("soil_temperature_6cm") or [None] * len(hourly["time"])):
                if value is not None:
                    ground[stamp[:10]] = max(value, ground.get(stamp[:10], -99.0))
                if v6 is not None:
                    seed.setdefault(stamp[:10], []).append(v6)
            days = []
            for i, t in enumerate(daily["time"]):
                et0 = daily["et0_fao_evapotranspiration"][i]
                if et0 is None:
                    continue
                days.append({
                    "date": t, "rain_mm": daily["precipitation_sum"][i] or 0.0,
                    "rain_prob": daily["precipitation_probability_max"][i], "et0_mm": et0,
                    "sun_mj": daily["shortwave_radiation_sum"][i],
                    "tmax": daily["temperature_2m_max"][i], "tmin": daily["temperature_2m_min"][i],
                    "soil_t_max": ground.get(t),
                    # mean temperature at seed depth (6 cm): what decides germination
                    "soil6_mean": round(sum(seed[t]) / len(seed[t]), 1) if seed.get(t) else None,
                })
        except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError) as exc:
            raise WeatherDown(f"Open-Meteo: {type(exc).__name__}") from exc
        if not days:
            raise WeatherDown("Open-Meteo: no days")
        _era5_past(lat, lon, days)
        return {"days": days, "timezone": body.get("timezone"), "elevation": body.get("elevation")}
    return _cached(("det", round(lat, 2), round(lon, 2), past_days), load)


def _era5_past(lat: float, lon: float, days: list) -> None:
    """Days older than the ERA5 lag take rain and ET0 from the ERA5 reanalysis (the observed past), the
    newer ones keep the forecast model's analysis. Each day says where its numbers come from."""
    for d in days:
        d["source"] = "forecast"
    cutoff = (date.today() - timedelta(days=ERA5_LAG_DAYS)).isoformat()
    past = [d for d in days if d["date"] <= cutoff]
    if not past:
        return
    try:
        r = _client.get(ERA5, params={"latitude": lat, "longitude": lon, "start_date": past[0]["date"], "end_date": past[-1]["date"],
                                      "daily": "precipitation_sum,et0_fao_evapotranspiration,shortwave_radiation_sum,"
                                               "temperature_2m_max,temperature_2m_min", "timezone": "auto"})
        r.raise_for_status()
        daily = r.json()["daily"]
    except (httpx.HTTPError, ValueError, KeyError):
        return                                   # keep the forecast model's values
    by_date = {t: i for i, t in enumerate(daily["time"])}
    for d in past:
        i = by_date.get(d["date"])
        if i is None or daily["et0_fao_evapotranspiration"][i] is None:
            continue
        d.update({"rain_mm": daily["precipitation_sum"][i] or 0.0, "et0_mm": daily["et0_fao_evapotranspiration"][i],
                  "sun_mj": daily["shortwave_radiation_sum"][i], "tmax": daily["temperature_2m_max"][i],
                  "tmin": daily["temperature_2m_min"][i], "source": "era5"})


def fetch_ensemble(lat: float, lon: float) -> list[dict]:
    """Ensemble members as {date: (rain_mm, et0_mm)}; [] when the service does not answer."""
    def load():
        params = {"latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": FORECAST_DAYS,
                  "daily": "precipitation_sum,et0_fao_evapotranspiration", "models": ENSEMBLE_MODELS}
        try:
            r = _client.get(ENSEMBLE, params=params)
            r.raise_for_status()
            daily = r.json()["daily"]
            times = daily["time"]
            members = []
            for key, rain in daily.items():
                if not key.startswith("precipitation_sum"):
                    continue
                et0 = daily.get("et0_fao_evapotranspiration" + key[len("precipitation_sum"):])
                if not et0:
                    continue
                members.append({t: (rain[i], et0[i]) for i, t in enumerate(times)
                                if rain[i] is not None and et0[i] is not None})
            return [m for m in members if len(m) >= 7]
        except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError):
            return []
    return _cached(("ens", round(lat, 2), round(lon, 2)), load)


# ---------- crop ----------

def season_sow(crop: dict, today: date, south: bool) -> date:
    """Sowing date of the season that is in the field today, else of the next one."""
    for harvest_year in (today.year - 1, today.year, today.year + 1, today.year + 2):
        sow = agro.sow_date(crop, harvest_year, south)
        if sow + timedelta(days=sum(crop["stages"])) > today:
            return sow
    return agro.sow_date(crop, today.year + 1, south)


def root_depth(crop: dict, day: int) -> float:
    ini, dev = crop["stages"][0], crop["stages"][1]
    full = crop["root_m"]
    if day >= ini + dev:
        return full
    return MIN_ROOT_M + (full - MIN_ROOT_M) * max(0, day) / (ini + dev)


def basal_kc(crop: dict) -> list:
    """Kcb at the initial, mid and end stage from the single Kc values (FAO-56 Tables 12 and 17:
    Kcb is 0.15 at the start, and 0.05-0.10 below Kc once the canopy is closed)."""
    ini, mid, end = crop["kc"]
    if crop.get("percolation_mm_day"):      # paddy rice stands in water: evaporation is not limited
        return [ini, mid, end]
    first = 0.30 if crop.get("perennial") else KC_MIN
    return [first, mid - 0.05, max(KC_MIN, end - 0.10)]


# ---------- the balance ----------

class State:
    """Depletion of the root zone and of the 10 cm evaporation layer, in mm below field capacity."""
    __slots__ = ("dr", "de")

    def __init__(self, dr: float, de: float):
        self.dr, self.de = dr, de

    def copy(self) -> "State":
        return State(self.dr, self.de)


def step(state: State, crop: dict, kcb3: list, day: int, soil: dict, et0: float, rain: float) -> dict:
    """One day of the two-layer balance; changes state and returns the numbers of that day."""
    length = sum(crop["stages"])
    in_field = 0 <= day < length
    zr = root_depth(crop, day) if in_field else MIN_ROOT_M
    taw = soil["awc_mm_per_m"] * zr
    raw = crop["p"] * taw
    tew, rew = soil["tew_mm"], soil["rew_mm"]
    kcb = agro.kc_at(day, crop["stages"], kcb3) if in_field else 0.0
    state.dr, state.de = min(state.dr, taw), min(state.de, tew)

    # rain first wets the surface layer and the root zone; what the soil cannot hold drains away
    state.de = max(0.0, state.de - rain)
    state.dr = max(0.0, state.dr - rain)

    cover = min(0.99, max(0.0, (kcb - KC_MIN) / (KC_MAX - KC_MIN)) ** 1.5) if kcb > KC_MIN else 0.0
    exposed = max(0.01, 1.0 - cover)                                    # soil the sun reaches (few)
    kr = 1.0 if state.de <= rew else max(0.0, (tew - state.de) / (tew - rew))
    ke = min(kr * (KC_MAX - kcb), exposed * KC_MAX)
    ks = 1.0 if state.dr <= raw else (max(0.0, (taw - state.dr) / (taw - raw)) if taw > raw else 0.0)
    evap = ke * et0
    transp = ks * kcb * et0
    state.de = min(tew, state.de + evap / exposed)
    state.dr = min(taw, state.dr + evap + transp)
    return {"in_field": in_field, "day": day, "kcb": kcb, "evap": evap, "transp": transp, "taw": taw, "raw": raw,
            "dr": state.dr, "de": state.de, "dry": in_field and state.dr > raw, "surface_dry": state.de >= tew * 0.95}


def _simulate(days: list, crop: dict, kcb3: list, sow: date, soil: dict, state: State,
              refill_from: str | None = None) -> list:
    """Runs the balance over days = [{date, et0_mm, rain_mm}]. With refill_from, the field is irrigated back
    to field capacity every time it gets dry on or after that day."""
    out = []
    for d in days:
        day = (date.fromisoformat(d["date"]) - sow).days
        r = step(state, crop, kcb3, day, soil, d["et0_mm"], d["rain_mm"])
        irrigated = 0.0
        if refill_from and d["date"] >= refill_from and r["dry"]:
            irrigated, state.dr, state.de = state.dr, 0.0, 0.0
            r["dr"], r["de"], r["dry"] = 0.0, 0.0, False
        r["date"], r["irrigated"] = d["date"], irrigated
        out.append(r)
    return out


def _quantile_date(dates: list, q: float, base: date) -> str | None:
    """Quantile of the members' dates; a member where it never happens counts as later than every date."""
    far = 10_000
    offsets = sorted((date.fromisoformat(x) - base).days if x else far for x in dates)
    if not offsets:
        return None
    value = offsets[min(len(offsets) - 1, int(q * len(offsets)))]
    return None if value >= far else (base + timedelta(days=value)).isoformat()


def plan(lat: float, lon: float, crop: dict, soil: dict, efficiency: float, area_ha: float,
         sow: date | None, last_irrigation: date | None, today: date, obs: dict | None = None) -> dict:
    """soil: agro.soil_water() result; obs: observe.get() (NASA observations that are ready).

    With observations: past rain is NASA GPM IMERG (measured from space, not a model), and when the
    farmer gives no last-irrigation date the start comes from NASA SMAP root-zone soil moisture.
    """
    south = lat < 0
    sow = sow or season_sow(crop, today, south)
    length = sum(crop["stages"])
    harvest = sow + timedelta(days=length)
    in_field_today = sow <= today < harvest
    kcb3 = basal_kc(crop)
    today_s = today.isoformat()

    # where the balance starts
    if last_irrigation:
        begin, start_from = last_irrigation, "last_irrigation"
    elif today - timedelta(days=MAX_PAST_DAYS) <= sow <= today:
        begin, start_from = sow, "sowing"            # sown into moist soil, no irrigation since
    else:
        begin, start_from = today - timedelta(days=MAX_PAST_DAYS), "history"
    past_days = min(MAX_PAST_DAYS, max(1, (today - begin).days))
    weather = fetch(lat, lon, past_days)
    days = [d for d in weather["days"] if d["date"] >= begin.isoformat()]
    if not days:
        raise WeatherDown("Open-Meteo: no days")
    past = [d for d in days if d["date"] < today_s]
    future = [d for d in days if d["date"] >= today_s]
    imerg = (obs or {}).get("imerg") or {}
    if imerg.get("status") == "ok":              # observed rain replaces the model's past rain
        seen = {r["date"]: r["rain_mm"] for r in imerg["series"]}
        for d in past:
            if d["date"] in seen:
                d["rain_mm"], d["rain_source"] = seen[d["date"]], "imerg"

    # at the start the soil is at field capacity (irrigation, sowing) or half-way to stress (unknown history)
    taw0 = soil["awc_mm_per_m"] * (root_depth(crop, (begin - sow).days) if sow <= begin < harvest else MIN_ROOT_M)
    state = State(0.0, 0.0) if start_from != "history" else State(0.5 * crop["p"] * taw0, soil["rew_mm"])
    smap = (obs or {}).get("smap") or {}
    smap_used = None
    if start_from == "history" and smap.get("status") == "ok":
        # SMAP root zone (0-100 cm) at the start day, turned into depletion of this soil
        first_day = days[0]["date"]
        row = min(smap["series"], key=lambda r: abs((date.fromisoformat(r["date"]) - date.fromisoformat(first_day)).days))
        theta = row["rootzone"]
        frac = min(1.0, max(0.0, (soil["fc"] - theta) / (soil["fc"] - soil["wp"]))) if soil["fc"] > soil["wp"] else 0.5
        state = State(frac * taw0, soil["rew_mm"] if (row.get("surface") or theta) < soil["fc"] * 0.6 else 0.0)
        start_from, smap_used = "smap", row
    past_rows = _simulate(past, crop, kcb3, sow, soil, state)
    now = state.copy()

    # deterministic "best" forecast: the table, the chart and the irrigation amount
    best_rows = _simulate(future, crop, kcb3, sow, soil, now.copy())
    first_dry = next((r for r in best_rows if r["dry"]), None)
    refilled = _simulate(future, crop, kcb3, sow, soil, now.copy(), refill_from=today_s)
    events = [r for r in refilled if r["irrigated"] > 0]

    # every ensemble member: when does the soil get dry, and how much water is missing then
    members = fetch_ensemble(lat, lon)
    fallback = {d["date"]: (d["rain_mm"], d["et0_mm"]) for d in future}
    member_days = []
    if len(members) >= MIN_MEMBERS:
        for m in members:
            member_days.append([{"date": d["date"], "rain_mm": m.get(d["date"], fallback[d["date"]])[0],
                                 "et0_mm": m.get(d["date"], fallback[d["date"]])[1]} for d in future])
        method = "ensemble"
    else:
        for factor in FALLBACK_RAIN.values():
            member_days.append([{"date": d["date"], "rain_mm": d["rain_mm"] * factor, "et0_mm": d["et0_mm"]} for d in future])
        method = "scenarios"
    dry_dates, dry_depl, surface_dates = [], [], []
    for series in member_days:
        rows = _simulate(series, crop, kcb3, sow, soil, now.copy())
        hit = next((r for r in rows if r["dry"]), None)
        dry_dates.append(hit["date"] if hit else None)
        if hit:
            dry_depl.append(hit["dr"])
        top = next((r for r in rows if r["surface_dry"]), None)
        surface_dates.append(top["date"] if top else None)

    def within(n: int) -> float:
        limit = (today + timedelta(days=n)).isoformat()
        return round(sum(1 for x in dry_dates if x and x < limit) / len(dry_dates), 2)

    dry_on = {"earliest": _quantile_date(dry_dates, 0.10, today), "expected": _quantile_date(dry_dates, 0.50, today),
              "latest": _quantile_date(dry_dates, 0.90, today)}
    already_dry = bool(best_rows) and best_rows[0]["dry"] and in_field_today

    def water(net_mm: float) -> dict:
        gross_mm = net_mm / efficiency
        m3_ha = gross_mm * 10
        return {"net_mm": round(net_mm, 1), "gross_mm": round(gross_mm, 1), "m3_ha": round(m3_ha),
                "m3_field": round(m3_ha * area_ha, 1), "litres_field": round(m3_ha * area_ha * 1000),
                "litres_m2": round(gross_mm, 1)}

    # Not dry within the forecast for most members: extend with the average use of its last week
    # (no rain assumed), clearly marked as an estimate beyond the forecast.
    beyond = None
    if best_rows and not dry_on["expected"] and in_field_today and not already_dry:
        last = best_rows[-1]
        use = sum(r["evap"] + r["transp"] for r in best_rows[-7:]) / min(7, len(best_rows))
        if use > 0.05 and last["raw"] > last["dr"]:
            n = int((last["raw"] - last["dr"]) / use) + 1
            when = date.fromisoformat(last["date"]) + timedelta(days=n)
            beyond = {"date": when.isoformat(), "days": (when - today).days, "use_mm_day": round(use, 1),
                      "after_harvest": when >= harvest}

    if first_dry:
        irrigation, estimate = water(first_dry["dr"]), False
    elif dry_depl and dry_on["expected"]:
        irrigation, estimate = water(percentile(dry_depl, 50)), False
    elif beyond and not beyond["after_harvest"] and beyond["days"] <= FAR_DAYS:
        irrigation, estimate = water(best_rows[-1]["raw"]), True
    else:
        irrigation, estimate = None, False

    by_date = {d["date"]: d for d in days}
    rain_by_date: dict[str, list] = {}
    if method == "ensemble":
        for series in member_days:
            for d in series:
                rain_by_date.setdefault(d["date"], []).append(d["rain_mm"])
    table = []
    for r in past_rows + best_rows:
        w = by_date[r["date"]]
        spread = rain_by_date.get(r["date"])
        table.append({
            "date": r["date"], "past": r["date"] < today_s, "day_of_season": r["day"] if r["in_field"] else None,
            "rain_mm": round(w["rain_mm"], 1), "rain_prob": w["rain_prob"],
            "rain_low_mm": round(percentile(spread, 10), 1) if spread else None,
            "rain_high_mm": round(percentile(spread, 90), 1) if spread else None,
            "et0_mm": round(w["et0_mm"], 1), "sun_mj": w["sun_mj"], "tmax": w["tmax"], "tmin": w["tmin"],
            "soil_t_max": w["soil_t_max"],
            "evap_mm": round(r["evap"], 1), "transp_mm": round(r["transp"], 1), "etc_mm": round(r["evap"] + r["transp"], 1),
            "depletion_mm": round(r["dr"], 1), "taw_mm": round(r["taw"], 1), "raw_mm": round(r["raw"], 1),
            "water_pct": round(100 * (1 - r["dr"] / r["taw"])) if r["taw"] else None,
            "surface_pct": round(100 * (1 - r["de"] / soil["tew_mm"])) if soil["tew_mm"] else None,
            "dry": r["dry"], "surface_dry": r["surface_dry"],
        })
    horizon = [r for r in table if not r["past"]]
    total_net = sum(r["irrigated"] for r in events)
    return {
        "crop": {"id": crop["id"], "name": crop["name"], "sow": sow.isoformat(), "harvest": harvest.isoformat(),
                 "in_field_today": in_field_today, "day_of_season": (today - sow).days if in_field_today else None},
        "soil": soil, "efficiency": efficiency, "area_ha": area_ha, "today": today_s,
        "start_from": start_from, "start_date": begin.isoformat(), "days_without_irrigation": (today - begin).days,
        "smap_start": smap_used,
        "observed_rain_days": sum(1 for d in past if d.get("rain_source") == "imerg"),
        "era5_days": sum(1 for d in past if d.get("source") == "era5"),
        "method": method, "members": len(member_days),
        "dry_on": dry_on if in_field_today else {"earliest": None, "expected": None, "latest": None},
        "dry_probability": {"d7": within(7), "d16": within(FORECAST_DAYS)} if in_field_today else None,
        "already_dry": already_dry,
        "dry_beyond_forecast": beyond,
        "surface_dry_on": {"earliest": _quantile_date(surface_dates, 0.10, today),
                           "expected": _quantile_date(surface_dates, 0.50, today),
                           "now": bool(best_rows) and best_rows[0]["surface_dry"]},
        "irrigation": irrigation if in_field_today else None,
        "irrigation_is_estimate": estimate,
        "forecast_use_mm": round(sum(r["etc_mm"] for r in horizon), 1),
        "forecast_evap_mm": round(sum(r["evap_mm"] for r in horizon), 1),
        "forecast_transp_mm": round(sum(r["transp_mm"] for r in horizon), 1),
        "forecast_rain_mm": round(sum(r["rain_mm"] for r in horizon), 1),
        "forecast_rain_range_mm": [round(percentile([sum(d["rain_mm"] for d in s) for s in member_days], q), 1)
                                   for q in (10, 90)] if method == "ensemble" else None,
        "forecast_irrigation": {**water(total_net), "times": len(events), "dates": [r["date"] for r in events]}
        if total_net and in_field_today else None,
        "means": {"sun_mj": _avg(horizon, "sun_mj"), "tmax": _avg(horizon, "tmax"),
                  "soil_t_max": _avg(horizon, "soil_t_max"), "et0_mm": _avg(horizon, "et0_mm")},
        "days": table,
        "timezone": weather.get("timezone"),
    }


def _avg(rows: list, key: str):
    vals = [r[key] for r in rows if r.get(key) is not None]
    return round(sum(vals) / len(vals), 1) if vals else None
