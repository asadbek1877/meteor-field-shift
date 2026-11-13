"""Can crops grow at this point at all? Checked before any crop or rotation advice.

Two independent kinds of evidence:
  land     what covers the ground (OpenStreetMap): building, road, water, ice, rock, town...
  climate  NASA POWER 2011-2025 at the point: growing season length, cold, heat, dryness

Result status:
  unsuitable  crops cannot be grown here; crop and rotation analysis is skipped
  limited     crops are possible only with a strong restriction (irrigation, short season...)
  ok          nothing found that rules farming out
  (land "unknown" when OpenStreetMap did not answer: then only climate is judged)

Thresholds are agronomy rules of thumb, stated in the texts shown to the user:
  - a month counts as a growing month when its mean temperature is at least 10 C
    (the usual base for warm-season crops; Koppen also puts the tundra limit at a warmest month < 10 C)
  - aridity index P/ET0 < 0.05 is "hyper-arid" (UNEP), where rain-fed farming is impossible
  - a warmest-month mean daily maximum above 45 C stops flowering of most crops
"""
from __future__ import annotations

from .climate import RECENT, Days
from .physics import mean, rnd

GROW_MONTH_C = 10.0
SHORT_SEASON_MONTHS = 3
HYPER_ARID = 0.05
EXTREME_TMAX_C = 45.0

# land cover -> verdict
LAND_UNSUITABLE = {"building", "road", "transport", "urban", "park", "water", "sea", "glacier", "rock", "sand"}
LAND_LIMITED = {"wetland", "forest"}


def climate_facts(d: Days) -> dict | None:
    """Monthly means of the recent period and yearly totals; None without data."""
    months = {m: {"t": [], "tmax": [], "rain": [], "et0": []} for m in range(1, 13)}
    years = [y for y in range(RECENT[0], RECENT[1] + 1) if y in d.spans] or d.years[-15:]
    if not years:
        return None
    for y in years:
        i0, i1 = d.spans[y]
        for i in range(i0, i1):
            m = months[d.day(i).month]
            m["t"].append(d.t[i]); m["tmax"].append(d.tmax[i])
            m["rain"].append(d.rain[i]); m["et0"].append(d.et0[i])
    t = [mean(months[m]["t"]) for m in range(1, 13)]
    tmax = [mean(months[m]["tmax"]) for m in range(1, 13)]
    n_years = len(years)
    rain = sum(sum(months[m]["rain"]) for m in months) / n_years
    et0 = sum(sum(months[m]["et0"]) for m in months) / n_years
    warm = max(range(12), key=lambda i: t[i])
    cold = min(range(12), key=lambda i: t[i])
    return {
        "period": [years[0], years[-1]],
        "t_mean_c": rnd(mean(t), 1),
        "warmest_month": warm + 1, "warmest_t_c": rnd(t[warm], 1),
        "coldest_month": cold + 1, "coldest_t_c": rnd(t[cold], 1),
        "warmest_tmax_c": rnd(max(tmax), 1),
        "growing_months": sum(v >= GROW_MONTH_C for v in t),
        "rain_mm": rnd(rain, 0), "et0_mm": rnd(et0, 0),
        "aridity": rnd(rain / et0, 3) if et0 else None,
        "elevation_m": rnd(d.elevation, 0),
    }


# satellite class at the point -> (reason code, level)
SAT_RULE = {
    "water": ("water", "unsuitable"), "snow_ice": ("glacier", "unsuitable"), "built": ("built", "unsuitable"),
    "flooded_vegetation": ("wetland", "limited"), "bare": ("bare", "limited"), "trees": ("trees", "limited"),
    "rangeland": ("rangeland", "info"), "crops": ("crops_seen", "info"),
}
# OSM land codes that describe the same thing as a satellite class (the more specific OSM text is kept)
SAME = {"water": {"water", "sea"}, "glacier": {"glacier"}, "built": {"building", "road", "transport", "urban", "park"},
        "wetland": {"wetland"}, "trees": {"forest"}}
NAME_FITS = {
    "built": {"amenity", "building", "healthcare", "shop", "office", "tourism", "leisure", "man_made",
              "craft", "historic", "landuse", "aeroway", "railway"},
    "water": {"natural", "water", "waterway", "place"}, "deep_water": {"natural", "water", "waterway", "place"},
    "glacier": {"natural"}, "wetland": {"natural"},
}
EDGE_MIN = 3          # of 8 ring points: the field borders water or buildings
DEEP_MIN = 6          # of 8 points on each ring: water all around, not just the shore


SLOPE_RULE = {"moderate": "info", "strong": "limited", "steep": "unsuitable"}


def judge(cover: dict | None, facts: dict | None, no_soil: bool, sat: dict | None = None,
          relief: dict | None = None) -> dict:
    """-> {"status", "reasons": [{"code", "level": unsuitable|limited|info, ...numbers}], "land", "climate"}

    cover: OpenStreetMap at the point (geo.land_cover), sat: 10 m satellite land cover (landcover.sample).
    The satellite decides for water, ice, built-up land and sea; OpenStreetMap adds names and exact
    buildings and roads; NASA POWER decides about the climate.
    """
    reasons: list[dict] = []
    land = cover.get("kind") if cover else None
    center = sat.get("center") if sat else None
    osm_name = cover.get("name") if cover else None
    osm_tag = cover.get("osm") if cover else None

    # 1. satellite: what really covers the ground
    sat_code = None
    if center == "nodata":
        if cover is None or not cover.get("found"):           # no pixel and no address: open sea
            sat_code = "sea"
            reasons.append({"code": "sea", "level": "unsuitable", "name": None, "osm": None})
    elif center in SAT_RULE:
        sat_code, level = SAT_RULE[center]
        if sat_code == "water" and sat["near"].get("water", 0) >= DEEP_MIN and sat["around"].get("water", 0) >= DEEP_MIN:
            sat_code = "deep_water"                            # water for 100 m all around
        # a town-address guess from OSM is overruled when the satellite sees a field
        if land == "urban" and center in ("crops", "rangeland", "bare"):
            land = None
        if not (land and land in SAME.get(sat_code.replace("deep_water", "water"), set())):
            # OSM gives the nearest named object; its name is shown only when it is the same kind of thing
            category = (osm_tag or "").split("=")[0]
            fits = NAME_FITS.get(sat_code, set())
            reasons.append({"code": sat_code, "level": level, "name": osm_name if category in fits else None, "osm": osm_tag})

    # 2. OpenStreetMap: exact buildings and roads, named places
    if land in LAND_UNSUITABLE:
        reasons.append({"code": land, "level": "unsuitable", "name": osm_name, "osm": osm_tag})
    elif land in LAND_LIMITED:
        reasons.append({"code": land, "level": "limited", "name": osm_name, "osm": osm_tag})
    elif no_soil and land != "farmland" and sat_code not in ("sea", "water", "deep_water", "glacier"):
        # NASA POWER has no root-zone soil wetness: the grid cell is ocean, lake or ice sheet.
        open_sea = cover is not None and not cover.get("found")
        reasons.append({"code": "sea" if open_sea else "no_soil", "level": "unsuitable", "name": None, "osm": None})

    # 3. a field next to water or houses: worth a warning, not a refusal
    if sat and center in ("crops", "rangeland", "bare", "trees"):
        for kind in ("water", "built"):
            n = max(sat["near"].get(kind, 0), sat["around"].get(kind, 0))
            if n >= EDGE_MIN:
                reasons.append({"code": "edge_" + kind, "level": "info", "n": n})

    # 4. terrain (NASA SRTM): steep land washes away under annual crops
    if relief and relief.get("class") in SLOPE_RULE and sat_code not in ("sea", "water", "deep_water", "glacier"):
        reasons.append({"code": "slope_" + relief["class"], "level": SLOPE_RULE[relief["class"]],
                        "slope": relief["slope_pct"], "deg": relief["slope_deg"]})

    # 5. climate
    if facts:
        if facts["growing_months"] == 0:
            reasons.append({"code": "too_cold", "level": "unsuitable", "t": facts["warmest_t_c"]})
        elif facts["growing_months"] <= SHORT_SEASON_MONTHS:
            reasons.append({"code": "short_season", "level": "limited", "n": facts["growing_months"], "t": facts["warmest_t_c"]})
        if facts["aridity"] is not None and facts["aridity"] < HYPER_ARID:
            reasons.append({"code": "hyper_arid", "level": "limited", "rain": facts["rain_mm"],
                            "et0": facts["et0_mm"], "ai": facts["aridity"]})
        if facts["warmest_tmax_c"] > EXTREME_TMAX_C:
            reasons.append({"code": "extreme_heat", "level": "limited", "t": facts["warmest_tmax_c"]})

    if land == "farmland":
        reasons.append({"code": "farmland", "level": "info", "name": osm_name, "osm": osm_tag})

    # the most serious reasons first
    order = {"unsuitable": 0, "limited": 1, "info": 2}
    reasons.sort(key=lambda r: order[r["level"]])
    levels = {r["level"] for r in reasons}
    status = "unsuitable" if "unsuitable" in levels else "limited" if "limited" in levels else "ok"
    return {
        "status": status,
        "reasons": reasons,
        "land": {"kind": land, "osm": osm_tag, "place": cover.get("place") if cover else None,
                 "checked": cover is not None or sat is not None, "satellite": sat, "terrain": relief},
        "climate": facts,
    }


def month_name(m: int, lang: str) -> str:
    names = {
        "en": ["January", "February", "March", "April", "May", "June", "July", "August",
               "September", "October", "November", "December"],
        "uz": ["yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust",
               "sentabr", "oktabr", "noyabr", "dekabr"],
    }
    return names[lang][m - 1]

