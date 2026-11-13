"""This week's advice for the main crops of the region, computed from the weather of the next 7 days.

For every crop that farmers mainly grow around the point (MapSPAM mix, see regional.plan), in order of area:

  in the field now   growth stage; water the crop uses this week (Kc x ET0, ET0 from sun, heat, humidity,
                     wind) minus the rain that counts, as irrigation in mm and m3/ha with its 10-90 % range
                     from 82 ensemble forecasts; heat days in the crop's sensitive stage; frost nights in its
                     frost-sensitive stage; a scorching ground surface for seedlings; downpours
  to be sown soon    is the seed-depth soil (6 cm) warm enough this week, is a frost coming that would kill
                     the seedlings, is a downpour coming that would crust the soil -> sow now / wait
  out of season      when its next sowing window opens here

Everything is a transparent rule with the threshold in the result, so the advice can be checked.
"""
from __future__ import annotations

from datetime import date, timedelta

from . import agro
from .physics import percentile

DAYS = 7
SOWING_LOOKAHEAD = 21          # a sowing date this many days ahead counts as "to be sown soon"
SOWING_LOOKBACK = 10           # ... and this many days behind, for a late start
MIN_RAIN_MM = 2.0              # smaller showers mostly evaporate from the surface
DOWNPOUR_MM = 20.0             # one day with more rain than this: no irrigation, risk of waterlogging
CRUST_MM = 40.0                # a day this wet right after sowing seals the surface (in the tropics fields are
                               # sown into the rains, so ordinary rainy days do not delay sowing)
IRRIGATE_M3_HA, LIGHT_M3_HA = 150, 50   # below 50 m3/ha (5 mm net) a separate watering is not worth it
SCORCH_C = 50.0                # ground surface this hot burns young seedlings at the soil line
HOT_AIR_C = 35.0
STAGES = ("initial", "development", "mid", "late")


def _stage(crop: dict, day: int) -> str:
    edge = 0
    for name, length in zip(STAGES, crop["stages"]):
        edge += length
        if day < edge:
            return name
    return "late"


def _summary(days: list, members: list) -> dict:
    """The week in numbers, with the spread of the ensemble for rain."""
    rain = sum(d["rain_mm"] for d in days)
    sums = [sum(m.get(d["date"], (d["rain_mm"], None))[0] for d in days) for m in members] if members else []

    def vals(key):
        return [d[key] for d in days if d.get(key) is not None]
    tmax, tmin, ground, seed, sun = vals("tmax"), vals("tmin"), vals("soil_t_max"), vals("soil6_mean"), vals("sun_mj")
    return {
        "from": days[0]["date"], "to": days[-1]["date"],
        "rain_mm": round(rain, 1),
        "rain_range_mm": [round(percentile(sums, 10), 1), round(percentile(sums, 90), 1)] if sums else None,
        "rain_5mm_probability": round(sum(1 for x in sums if x >= 5) / len(sums), 2) if sums else None,
        "rain_days": sum(1 for d in days if d["rain_mm"] >= MIN_RAIN_MM),
        "et0_mm": round(sum(d["et0_mm"] for d in days), 1),
        "sun_mj_mean": round(sum(sun) / len(sun), 1) if sun else None,
        "tmax_max": max(tmax) if tmax else None, "tmin_min": min(tmin) if tmin else None,
        "ground_max": round(max(ground), 1) if ground else None,
        "seed_soil_mean": round(sum(seed) / len(seed), 1) if seed else None,
        "frost_nights": sum(1 for v in tmin if v <= 0), "hot_days": sum(1 for v in tmax if v >= HOT_AIR_C),
        "members": len(members),
    }


def _water(crop: dict, sow: date, days: list, members: list, efficiency: float) -> dict:
    """Irrigation this week = crop use - effective rain, for the forecast and the ensemble spread."""
    use = 0.0
    for d in days:
        k = (date.fromisoformat(d["date"]) - sow).days
        if 0 <= k < sum(crop["stages"]):
            use += agro.kc_at(k, crop["stages"], crop["kc"]) * d["et0_mm"]
    use += crop.get("percolation_mm_day", 0.0) * len(days)

    def effective(rains):
        return sum(r for r in rains if r >= MIN_RAIN_MM)

    def need(rain_eff):
        net = max(0.0, use - rain_eff)
        return {"net_mm": round(net, 1), "m3_ha": round(net * 10 / efficiency)}
    best = need(effective([d["rain_mm"] for d in days]))
    if members:
        nets = sorted(max(0.0, use - effective([m.get(d["date"], (d["rain_mm"], None))[0] for d in days])) for m in members)
        low, high = percentile(nets, 10), percentile(nets, 90)
        spread = {"m3_ha_low": round(low * 10 / efficiency), "m3_ha_high": round(high * 10 / efficiency)}
    else:
        spread = {"m3_ha_low": None, "m3_ha_high": None}
    return {"use_mm": round(use, 1), **best, **spread}


def crop_week(crop: dict, today: date, days: list, members: list, efficiency: float, south: bool) -> dict:
    """Status and advice for one localized crop."""
    length = sum(crop["stages"])
    sow_now = None
    for harvest_year in (today.year - 1, today.year, today.year + 1, today.year + 2):
        s = agro.sow_date(crop, harvest_year, south)
        if s + timedelta(days=length) > today - timedelta(days=SOWING_LOOKBACK):
            sow_now = s
            break
    sow_now = sow_now or agro.sow_date(crop, today.year + 1, south)
    day = (today - sow_now).days
    alerts: list[dict] = []
    out = {"id": crop["id"], "name": crop["name"], "sow": sow_now.isoformat(),
           "harvest": (sow_now + timedelta(days=length)).isoformat()}

    if 0 <= day < length:  # ---- in the field
        stage = _stage(crop, day)
        water = _water(crop, sow_now, days, members, efficiency)
        heat, frost = crop.get("heat"), crop.get("frost")
        heat_days = [d["date"] for k, d in enumerate(days)
                     if heat and heat["from_day"] <= day + k <= heat["to_day"] and (d["tmax"] or -99) >= heat["tmax_c"]]
        frost_days = [d["date"] for k, d in enumerate(days)
                      if frost and day + k < frost["first_days"] and (d["tmin"] if d["tmin"] is not None else 99) <= frost["tmin_c"]]
        scorch = [d["date"] for d in days if day < crop["stages"][0] + crop["stages"][1] // 2
                  and (d["soil_t_max"] or -99) >= SCORCH_C]
        downpour = [d["date"] for d in days if d["rain_mm"] >= DOWNPOUR_MM]
        if frost_days:
            alerts.append({"code": "frost", "level": "critical", "dates": frost_days, "t": frost["tmin_c"]})
        if heat_days:
            alerts.append({"code": "heat", "level": "critical" if len(heat_days) >= 3 else "warning",
                           "dates": heat_days, "t": heat["tmax_c"]})
        if scorch:
            alerts.append({"code": "scorch", "level": "warning", "dates": scorch, "t": SCORCH_C})
        if downpour:
            alerts.append({"code": "downpour", "level": "info", "dates": downpour, "mm": DOWNPOUR_MM})
        action = "irrigate" if water["m3_ha"] >= IRRIGATE_M3_HA else "light" if water["m3_ha"] >= LIGHT_M3_HA else "no_irrigation"
        out.update({"status": "in_field", "day": day, "stage": stage, "water": water, "action": action})
    elif -SOWING_LOOKAHEAD <= day < 0:  # ---- to be sown soon
        rule = crop.get("sowing") or {}
        seed = [d["soil6_mean"] for d in days if d.get("soil6_mean") is not None]
        seed_mean = round(sum(seed) / len(seed), 1) if seed else None
        threshold = rule.get("temp_c")
        frost = crop.get("frost")
        frost_days = [d["date"] for d in days if frost and d["tmin"] is not None and d["tmin"] <= frost["tmin_c"]]
        downpour = [d["date"] for d in days if d["rain_mm"] >= CRUST_MM]
        if rule.get("kind") == "autumn":
            ready = seed_mean is not None and threshold is not None and seed_mean <= threshold + 3
        else:
            ready = seed_mean is None or threshold is None or seed_mean >= threshold
        if frost_days and rule.get("kind") != "autumn":
            action = "wait_frost"
        elif not ready:
            action = "wait_cold" if rule.get("kind") != "autumn" else "wait_warm"
        elif downpour:
            action = "wait_rain"
        else:
            action = "sow"
        out.update({"status": "sowing", "days_to_sow": -day, "seed_soil_c": seed_mean, "threshold_c": threshold,
                    "frost_dates": frost_days, "downpour_dates": downpour, "action": action})
    else:  # ---- out of season: the next sowing date after today
        nxt = sow_now
        if day >= 0:
            nxt = next(c for c in (agro.sow_date(crop, y, south) for y in range(today.year, today.year + 4)) if c > today)
        out.update({"status": "off_season", "next_sow": nxt.isoformat(), "days_to_sow": (nxt - today).days,
                    "action": "none"})
    out["alerts"] = alerts
    return out


def field_now(obs: dict | None, today: date) -> dict | None:
    """What NASA satellites saw at the field lately: vegetation (HLS 30 m, else MODIS 250 m), soil moisture
    (SMAP), rain of the last 7 days (IMERG), surface heat (ECOSTRESS)."""
    obs = obs or {}
    out: dict = {}
    hls, modis = obs.get("hls") or {}, obs.get("modis") or {}
    if hls.get("status") == "ok":
        out["ndvi"] = {**hls["latest"], "state": hls["state"], "source": "HLS 30 m"}
    elif modis.get("status") == "ok":
        v = modis["latest"]["ndvi"]
        out["ndvi"] = {**modis["latest"], "state": "green" if v >= 0.5 else "growing" if v >= 0.3 else
                       "sparse" if v >= 0.15 else "bare", "source": "MODIS 250 m"}
    smap = obs.get("smap") or {}
    if smap.get("status") == "ok":
        out["smap"] = {**smap["latest"], "change_30d": smap["change_30d"]}
    imerg = obs.get("imerg") or {}
    if imerg.get("status") == "ok":
        week_ago = (today - timedelta(days=7)).isoformat()
        out["rain_7d_observed_mm"] = round(sum(r["rain_mm"] for r in imerg["series"] if r["date"] >= week_ago), 1)
        out["days_since_rain"] = imerg["days_since_rain"]
    eco = obs.get("ecostress") or {}
    if eco.get("status") == "ok" and eco.get("hottest"):
        out["lst"] = eco["hottest"]
    return out or None


def analyze(plan: dict, weather: dict, members: list, efficiency: float, today: date, lat: float,
            obs: dict | None = None) -> dict | None:
    """plan: regional.plan() result; weather: water.fetch(); members: water.fetch_ensemble()."""
    days = [d for d in weather["days"] if d["date"] >= today.isoformat()][:DAYS]
    if len(days) < 3:
        return None
    lib = plan["field"].lib
    shares = {r["crop_id"]: r["share"] for r in plan["profile"]["top"] if r.get("crop_id")}
    crops = [crop_week(lib[c], today, days, members, efficiency, lat < 0) for c in plan["show"] if c in lib]
    for c in crops:
        c["share"] = shares.get(c["id"])
    order = {"in_field": 0, "sowing": 1, "off_season": 2}
    crops.sort(key=lambda c: (order[c["status"]], -(c["share"] or 0)))
    seen = field_now(obs, today)
    if seen and seen.get("ndvi"):
        # the satellite and the calendar disagree: say so instead of advising water for an empty field
        for c in crops:
            if c["status"] == "in_field" and seen["ndvi"]["state"] == "bare" and c["day"] > 30:
                c["alerts"].append({"code": "bare_field", "level": "warning", "dates": [seen["ndvi"]["date"]],
                                    "t": seen["ndvi"]["ndvi"]})
    return {"summary": _summary(days, members), "crops": crops, "seen": seen,
            "method": "ensemble" if members else "deterministic"}
