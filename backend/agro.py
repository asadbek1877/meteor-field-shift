"""Crops and rotations on top of the daily climate record.

Method (FAO-56 chapter 8, single crop coefficient with a daily root-zone water balance):
  * Kc curve from four growth stages
  * crop water need ETc = Kc * ET0 each day
  * the soil holds TAW = available water capacity * root depth; rain refills it
  * when depletion passes the readily available water (p * TAW) the field is irrigated
    back to field capacity; the sum of these refills is the net irrigation need
  * heat stress: days above the crop threshold inside its sensitive window
  * frost: minimum temperature below the crop limit after sowing

Every crop is simulated for every year of weather on record. A rotation is then
scored by replaying its crops over the weather of 2011-2025, which gives a spread
(good year / median year / bad year) instead of one number.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from .climate import BASELINE, RECENT, Days, _in, _mmdd
from .physics import mean, percentile, rnd, spread

_DIR = Path(__file__).parent
CONFIG = json.loads((_DIR / "crops.json").read_text(encoding="utf-8"))
ROTATIONS = json.loads((_DIR / "rotations.json").read_text(encoding="utf-8"))
CROPS = {c["id"]: c for c in CONFIG["crops"]}
SPINUP_DAYS = 60
BARE_SOIL_KC = 0.2
RESIDUE_SCORE = {"low": 30, "medium": 60, "high": 100}
SOIL_WEIGHTS = {"legumes": 0.30, "diversity": 0.20, "cover": 0.20, "residue": 0.20, "perennial": 0.10}
DEFAULT_WEIGHTS = {"water": 40, "income": 20, "soil": 20, "risk": 20}


# ---------- single crop ----------

def sow_date(crop: dict, harvest_year: int, south: bool) -> date:
    """Sowing date of the season that is harvested in harvest_year.

    In the southern hemisphere the whole calendar is moved by half a year, so rotations
    keep the same order and gaps between crops as in the north.
    """
    doy = crop["sow_doy"]
    crosses_new_year = doy + sum(crop["stages"]) - 1 > 365
    sow = date(harvest_year - crosses_new_year, 1, 1) + timedelta(days=doy - 1)
    return sow - timedelta(days=182) if south else sow


def kc_at(day: int, stages: list, kc: list) -> float:
    ini, dev, mid, _late = stages
    if day < ini:
        return kc[0]
    if day < ini + dev:
        return kc[0] + (kc[1] - kc[0]) * (day - ini) / dev
    if day < ini + dev + mid:
        return kc[1]
    return kc[1] + (kc[2] - kc[1]) * (day - ini - dev - mid) / stages[3]


def simulate(d: Days, crop: dict, harvest_year: int, awc: float) -> dict | None:
    """One season of one crop under the real weather of that year. None if data does not cover it."""
    sow = sow_date(crop, harvest_year, d.lat < 0)
    i0, length = d.idx(sow), sum(crop["stages"])
    if i0 - SPINUP_DAYS < 0 or i0 + length > d.n:
        return None
    taw = awc * crop["root_m"]
    raw = crop["p"] * taw

    # Fallow period before sowing decides how much water is in the soil at sowing.
    depletion = 0.5 * taw
    for i in range(i0 - SPINUP_DAYS, i0):
        ks = 1.0 if depletion <= raw else max(0.0, (taw - depletion) / (taw - raw))
        depletion = min(taw, max(0.0, depletion + BARE_SOIL_KC * d.et0[i] * ks - d.rain[i]))

    need = rain = irrigation = 0.0
    events = heat_days = 0
    frost = False
    heat, frost_rule = crop.get("heat"), crop.get("frost")
    for day in range(length):
        i = i0 + day
        etc = kc_at(day, crop["stages"], crop["kc"]) * d.et0[i]
        need += etc
        rain += d.rain[i]
        depletion = max(0.0, depletion + etc - d.rain[i])
        if depletion > raw and day < length - 10:  # no irrigation in the last 10 days before harvest
            irrigation += depletion
            events += 1
            depletion = 0.0
        depletion = min(depletion, taw)
        if heat and heat["from_day"] <= day <= heat["to_day"] and d.tmax[i] >= heat["tmax_c"]:
            heat_days += 1
        if frost_rule and day < frost_rule["first_days"] and d.tmin[i] <= frost_rule["tmin_c"]:
            frost = True
    stress = min(1.0, heat_days / heat["limit_days"]) if heat else 0.0
    if frost:
        stress = 1.0
    return {"need": need, "rain": rain, "irrigation": irrigation, "events": events,
            "heat_days": heat_days, "frost": frost, "stress": stress}


def suitable_sowing_doy(d: Days, crop: dict, year: int) -> int | None:
    """First day when the 10-day mean temperature settles on the right side of the sowing threshold."""
    rule = crop.get("sowing")
    if not rule or not d.daily or year not in d.spans:
        return None
    south = d.lat < 0
    spring = rule["kind"] == "spring"
    first = 15 if spring else 213
    if south:
        first = (first - 1 + 182) % 365 + 1
    i0 = d.spans[year][0] + first - 1
    for i in range(i0, min(i0 + 170, d.n - 20)):
        a, b = mean(d.t[i:i + 10]), mean(d.t[i + 10:i + 20])
        if (a >= rule["temp_c"] and b >= rule["temp_c"]) if spring else (a <= rule["temp_c"] and b <= rule["temp_c"]):
            return i - d.spans[year][0] + 1
    return None


class Field:
    """Simulation results for one point, soil and irrigation method. Crop-years are computed once."""

    def __init__(self, d: Days, soil: str = "medium", irrigation: str = "furrow"):
        self.d = d
        self.soil = soil if soil in CONFIG["soils"] else "medium"
        self.method = irrigation if irrigation in CONFIG["irrigation"] else "furrow"
        self.awc = CONFIG["soils"][self.soil]["awc_mm_per_m"]
        self.efficiency = CONFIG["irrigation"][self.method]["efficiency"]
        self._memo: dict[tuple, dict | None] = {}

    def run(self, crop_id: str, year: int) -> dict | None:
        key = (crop_id, year)
        if key not in self._memo:
            self._memo[key] = simulate(self.d, CROPS[crop_id], year, self.awc)
        return self._memo[key]

    def gross_m3(self, net_mm: float) -> float:
        """Net irrigation in mm -> water to deliver in m3 per hectare (1 mm = 10 m3/ha)."""
        return net_mm * 10 / self.efficiency

    # ----- crops -----

    def _period(self, crop: dict, period) -> dict | None:
        rows = [r for y in range(period[0], period[1] + 1) if (r := self.run(crop["id"], y))]
        if not rows:
            return None
        return {
            "years": len(rows),
            "water_need_mm": rnd(mean(r["need"] for r in rows), 0),
            "rain_mm": rnd(mean(r["rain"] for r in rows), 0),
            "irrigation_mm": spread([r["irrigation"] for r in rows]),
            "irrigation_mean_mm": rnd(mean(r["irrigation"] for r in rows), 0),
            "irrigation_m3_ha": spread([self.gross_m3(r["irrigation"]) for r in rows]),
            "irrigations": rnd(percentile([r["events"] for r in rows], 50), 0),
            "heat_days": spread([r["heat_days"] for r in rows]),
            "heat_years_share": rnd(mean(r["heat_days"] >= crop["heat"]["limit_days"] for r in rows), 2),
            "frost_years_share": rnd(mean(r["frost"] for r in rows), 2),
            "stress": rnd(mean(r["stress"] for r in rows), 2),
        }

    def _sowing(self, crop: dict) -> dict | None:
        if not crop.get("sowing"):
            return None
        by_year = {y: suitable_sowing_doy(self.d, crop, y) for y in self.d.years}
        base = percentile([v for y, v in by_year.items() if _in(BASELINE, y)], 50)
        recent = percentile([v for y, v in by_year.items() if _in(RECENT, y)], 50)
        if base is None or recent is None:
            return None
        return {"kind": crop["sowing"]["kind"], "threshold_c": crop["sowing"]["temp_c"],
                "baseline": _mmdd(base), "recent": _mmdd(recent), "shift_days": rnd(recent - base, 0)}

    def crops(self) -> list[dict]:
        south = self.d.lat < 0
        out = []
        for crop in CONFIG["crops"]:
            recent = self._period(crop, RECENT)
            if not recent:
                continue
            base = self._period(crop, BASELINE)
            sow = sow_date(crop, 2001, south)
            water = _level(recent["irrigation_mm"]["p50"], CONFIG["levels"]["irrigation_mm"])
            stress = _level(recent["stress"], CONFIG["levels"]["stress"])
            change = None
            if base:  # means, because single irrigations make medians jump by a whole event
                change = recent["irrigation_mean_mm"] - base["irrigation_mean_mm"]
            out.append({
                "id": crop["id"],
                "name": crop["name"],
                "legume": crop["legume"],
                "season": {"sow": sow.strftime("%m-%d"),
                           "harvest": (sow + timedelta(days=sum(crop["stages"]))).strftime("%m-%d"),
                           "days": sum(crop["stages"])},
                "heat_rule": crop["heat"],
                "baseline": base,
                "recent": recent,
                "irrigation_change_mm": rnd(change, 0),
                "sowing": self._sowing(crop),
                "water_level": water,
                "stress_level": stress,
                "level": max(water, stress, key=["low", "moderate", "high"].index),
            })
        return out

    # ----- this week -----

    def week(self, et0_7d: float, rain_7d: float, today: date) -> list[dict]:
        """Irrigation need of the next 7 days for crops that are in the field today."""
        out = []
        for crop in CONFIG["crops"]:
            length = sum(crop["stages"])
            for year in (today.year, today.year + 1, today.year + 2):
                sow = sow_date(crop, year, self.d.lat < 0)
                if sow <= today < sow + timedelta(days=length):
                    day = (today - sow).days
                    kc = mean(kc_at(min(day + k, length - 1), crop["stages"], crop["kc"]) for k in range(7))
                    net = max(0.0, kc * et0_7d - rain_7d)
                    out.append({"id": crop["id"], "name": crop["name"], "day_of_season": day,
                                "kc": rnd(kc, 2), "need_mm": rnd(kc * et0_7d, 1), "net_mm": rnd(net, 1),
                                "m3_ha": rnd(self.gross_m3(net), 0)})
                    break
        return out

    # ----- rotations -----

    def rotations(self, current_id: str | None, custom: list | None, weights: dict | None) -> dict:
        weights = {k: max(0.0, float((weights or {}).get(k, v))) for k, v in DEFAULT_WEIGHTS.items()}
        if not sum(weights.values()):
            weights = dict(DEFAULT_WEIGHTS)
        candidates = [dict(r) for r in ROTATIONS["rotations"]]
        if custom:
            candidates.append({"id": "custom", "name": {"en": "My rotation", "uz": "Mening rotatsiyam"}, "years": custom})
            current_id = current_id or "custom"
        ids = {r["id"] for r in candidates}
        current_id = current_id if current_id in ids else ROTATIONS["default_current"]

        years = [y for y in range(RECENT[0], RECENT[1] + 1)]
        items = []
        for rot in candidates:
            per_year = self._replay(rot, years)
            if not per_year:
                continue
            items.append({
                "id": rot["id"],
                "name": rot["name"],
                "years": [[{"id": c, "name": CROPS[c]["name"]} for c in slot] for slot in rot["years"]],
                "is_current": rot["id"] == current_id,
                "conflicts": conflicts(rot["years"], self.d.lat < 0),
                "soil": soil_health(rot["years"]),
                "_per_year": per_year,
            })
        if not items:
            return {"items": [], "weights": weights, "current_id": current_id, "best_id": None}

        # Scores 0-100 per criterion. Water and income are relative to the best candidate.
        def scores(values: dict) -> dict:
            """values: rotation id -> {water, income, risk}"""
            low_water = min(v["water"] for v in values.values())
            top_income = max(v["income"] for v in values.values())
            return {rid: {
                "water": 100.0 if v["water"] <= 0 else 100 * low_water / v["water"],
                "income": 100 * v["income"] / top_income if top_income else 0.0,
                "risk": 100 - v["risk"],
            } for rid, v in values.items()}

        def total(s: dict, soil: float) -> float:
            w = weights
            return (w["water"] * s["water"] + w["income"] * s["income"] + w["risk"] * s["risk"]
                    + w["soil"] * soil) / sum(w.values())

        soil_of = {it["id"]: it["soil"]["index"] for it in items}
        common = sorted(set.intersection(*[set(it["_per_year"]) for it in items]))
        median = {it["id"]: {k: percentile([it["_per_year"][y][k] for y in common], 50)
                             for k in ("water", "income", "risk")} for it in items}
        overall = scores(median)
        yearly_totals = {it["id"]: [] for it in items}
        wins = {it["id"]: 0 for it in items}
        for y in common:
            s = scores({it["id"]: it["_per_year"][y] for it in items})
            totals = {rid: total(s[rid], soil_of[rid]) for rid in s}
            for rid, value in totals.items():
                yearly_totals[rid].append(value)
            wins[max(totals, key=totals.get)] += 1

        cur = next(it for it in items if it["is_current"])
        for it in items:
            rid, py = it["id"], it.pop("_per_year")
            s = overall[rid]
            it.update({
                "water_m3_ha": spread([py[y]["water"] for y in common]),
                "irrigation_mm": spread([py[y]["net_mm"] for y in common]),
                "income_usd_ha": spread([py[y]["income"] for y in common]),
                "risk_pct": spread([py[y]["risk"] for y in common]),
                "scores": {"water": rnd(s["water"], 0), "income": rnd(s["income"], 0),
                           "risk": rnd(s["risk"], 0), "soil": rnd(soil_of[rid], 0),
                           "total": rnd(total(s, soil_of[rid]), 1),
                           "total_range": spread(yearly_totals[rid], 1)},
                "wins": wins[rid],
            })
        for it in items:
            c = next(x for x in items if x["is_current"])
            saved = c["water_m3_ha"]["p50"] - it["water_m3_ha"]["p50"]
            it["vs_current"] = None if it["is_current"] else {
                "water_m3_ha": saved,
                "water_pct": rnd(100 * saved / c["water_m3_ha"]["p50"], 0) if c["water_m3_ha"]["p50"] else None,
                "income_usd_ha": it["income_usd_ha"]["p50"] - c["income_usd_ha"]["p50"],
                "soil": it["soil"]["index"] - c["soil"]["index"],
                "risk_pct": it["risk_pct"]["p50"] - c["risk_pct"]["p50"],
            }
        items.sort(key=lambda it: -it["scores"]["total"])
        for rank, it in enumerate(items, 1):
            it["rank"] = rank
        feasible = [it for it in items if not it["conflicts"]]
        best = feasible[0] if feasible else items[0]
        runner = next((it for it in feasible if it["id"] != best["id"]), None)
        return {
            "items": items,
            "weights": weights,
            "current_id": cur["id"],
            "best_id": best["id"],
            "years_replayed": len(common),
            "period": [common[0], common[-1]] if common else None,
            # A lead smaller than the year-to-year spread means the choice is not clear-cut.
            "lead": rnd(best["scores"]["total"] - runner["scores"]["total"], 1) if runner else None,
            "clear_winner": bool(runner) and best["wins"] >= 0.6 * len(common),
            "soil_class": self.soil,
            "irrigation_method": self.method,
            "irrigation_efficiency": self.efficiency,
        }

    def _replay(self, rot: dict, years: list[int]) -> dict:
        """year -> average hectare of the rotation under that year's weather."""
        loss = CONFIG["stress_yield_loss"]
        out = {}
        n = len(rot["years"])
        for y in years:
            runs = [[self.run(crop_id, y) for crop_id in slot] for slot in rot["years"]]
            if any(r is None for slot in runs for r in slot):
                continue  # weather record does not cover this year for every crop
            net = sum(r["irrigation"] for slot in runs for r in slot)
            stress = sum(max(r["stress"] for r in slot) for slot in runs)
            income = sum(CROPS[crop_id]["revenue_usd_ha"] * (1 - loss * r["stress"])
                         for slot, slot_runs in zip(rot["years"], runs)
                         for crop_id, r in zip(slot, slot_runs))
            out[y] = {"net_mm": net / n, "water": self.gross_m3(net / n),
                      "risk": 100 * stress / n, "income": income / n}
        return out


def _level(value, cuts) -> str:
    return "low" if value < cuts[0] else "moderate" if value < cuts[1] else "high"


# ---------- rotation structure ----------

def parse_custom(text: str | None) -> list | None:
    """'cotton|winter_wheat+mung_bean|alfalfa' -> [['cotton'], ['winter_wheat', 'mung_bean'], ['alfalfa']]"""
    if not text:
        return None
    years = [[c for c in slot.split("+") if c] for slot in text.split("|")]
    years = [slot for slot in years if slot]
    if not years or len(years) > 6 or any(len(s) > 2 or any(c not in CROPS for c in s) for s in years):
        raise ValueError("custom rotation: use crop ids separated by | for years and + for a second crop")
    return years


def conflicts(years: list, south: bool = False) -> list[dict]:
    """Crops whose seasons overlap in the field (checked around the cycle)."""
    spans = []
    for k, slot in enumerate(years):
        for crop_id in slot:
            sow = sow_date(CROPS[crop_id], 2001 + k, south)
            spans.append((sow, sow + timedelta(days=sum(CROPS[crop_id]["stages"])), crop_id))
    spans.sort()
    out = []
    cycle = timedelta(days=365 * len(years))
    for a, b in zip(spans, spans[1:] + [(spans[0][0] + cycle, spans[0][1] + cycle, spans[0][2])]):
        if b[0] < a[1] and len(spans) > 1:
            out.append({"first": a[2], "second": b[2], "overlap_days": (a[1] - b[0]).days})
    return out


def soil_health(years: list) -> dict:
    """Transparent rule-based index 0-100. It describes the rotation's design, it is not a soil measurement."""
    n = len(years)
    crops = [CROPS[c] for slot in years for c in slot]
    legume_years = sum(any(CROPS[c]["legume"] for c in slot) for slot in years) / n
    parts = {
        "legumes": min(1.0, legume_years / 0.33) * 100,                       # nitrogen fixation
        "diversity": min(1.0, len({c["family"] for c in crops}) / 3) * 100,   # breaks pest and disease cycles
        "cover": min(1.0, sum(sum(c["stages"]) for c in crops) / (365 * n) / 0.75) * 100,  # soil not left bare
        "residue": mean(mean(RESIDUE_SCORE[CROPS[c]["residue"]] for c in slot) for slot in years),
        "perennial": min(1.0, sum(any(CROPS[c]["perennial"] for c in slot) for slot in years) / n / 0.25) * 100,
    }
    index = sum(SOIL_WEIGHTS[k] * v for k, v in parts.items())
    return {"index": rnd(index, 0), "parts": {k: rnd(v, 0) for k, v in parts.items()}, "weights": SOIL_WEIGHTS}
