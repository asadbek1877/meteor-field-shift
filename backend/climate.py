"""Climate analysis of the daily NASA POWER record of one point.

prepare()  cleans the record and computes daily reference evapotranspiration
analyze()  climate shift between two periods, trends, projection, frost season,
           the last 30 days and a climatological outlook for the next 30 days
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import date, timedelta

from . import physics as ph
from .physics import mean, percentile, rnd, spread

BASELINE = (1991, 2005)
RECENT = (2011, 2025)
PROJECTION_YEAR = 2040
HOT_DAY_C = 35.0
RAIN_DAY_MM = 1.0


@dataclass
class Days:
    lat: float
    lon: float
    elevation: float
    resolution: str          # "daily" or "monthly" (monthly means repeated for every day)
    start: date
    n: int                   # number of days with data
    t: list
    tmax: list
    tmin: list
    rain: list
    et0: list
    soil: list
    year: list
    doy: list
    spans: dict              # year -> (first index, last index + 1) for complete years
    pm_share: float          # share of days where Penman-Monteith could be used
    gaps: int                # days filled from the previous day

    @property
    def daily(self) -> bool:
        return self.resolution == "daily"

    @property
    def years(self) -> list[int]:
        return sorted(self.spans)

    def idx(self, d: date) -> int:
        return (d - self.start).days

    def day(self, i: int) -> date:
        return self.start + timedelta(days=i)


_prepared: dict[tuple, Days] = {}
_prepared_lock = threading.Lock()


def _fill(values: list, n: int, default):
    """Forward-fill gaps. Returns (list, number of filled days)."""
    out, last, gaps = [], None, 0
    first = next((v for v in values[:n] if v is not None), default)
    for v in values[:n]:
        if v is None:
            gaps += 1
            v = last if last is not None else first
        out.append(v)
        last = v
    return out, gaps


def prepare(data: dict) -> Days:
    key = (data["lat"], data["lon"], data["fetched_at"])
    if key in _prepared:
        return _prepared[key]
    p = data["params"]
    start = date.fromisoformat(data["start"])
    n = len(p["T2M"])
    while n and p["T2M"][n - 1] is None:
        n -= 1  # the newest 1-3 days are usually not published yet

    t, gaps = _fill(p["T2M"], n, 0.0)
    tmax, _ = _fill(p["T2M_MAX"], n, None)
    tmin, _ = _fill(p["T2M_MIN"], n, None)
    rain = [v if v is not None else 0.0 for v in p["PRECTOTCORR"][:n]]
    soil = p["GWETROOT"][:n]
    rh, ws, rs = p["RH2M"], p["WS2M"], p["ALLSKY_SFC_SW_DWN"]

    year, doy = [], []
    d = start
    one = timedelta(days=1)
    for _ in range(n):
        year.append(d.year)
        doy.append(d.timetuple().tm_yday)
        d += one

    lat, elev = data["lat"], data.get("elevation") or 0.0
    ra_by_doy = [ph.extraterrestrial_radiation(lat, k) for k in range(0, 367)]
    et0, pm_days = [], 0
    for i in range(n):
        hi = tmax[i] if tmax[i] is not None else t[i] + 6
        lo = tmin[i] if tmin[i] is not None else t[i] - 6
        ra = ra_by_doy[doy[i]]
        if rs[i] is not None and rh[i] is not None and ws[i] is not None:
            et0.append(ph.et0_penman_monteith(hi, lo, t[i], rs[i], ws[i], ra, elev, rh=rh[i]))
            pm_days += 1
        else:
            et0.append(ph.et0_hargreaves(t[i], hi, lo, ra))
        tmax[i], tmin[i] = hi, lo

    spans = {}
    for y in range(start.year, year[-1] + 1 if n else start.year):
        i0, i1 = (date(y, 1, 1) - start).days, (date(y + 1, 1, 1) - start).days
        if i0 >= 0 and i1 <= n:
            spans[y] = (i0, i1)

    days = Days(lat, data["lon"], elev, data.get("resolution", "daily"), start, n, t, tmax, tmin,
                rain, et0, soil, year, doy, spans, pm_days / n if n else 0.0, gaps)
    with _prepared_lock:  # requests run in parallel threads
        if len(_prepared) > 24:
            _prepared.pop(next(iter(_prepared)), None)
        _prepared[key] = days
    return days


# ---------- annual series and shifts ----------

def _longest_dry_spell(rain: list) -> int:
    best = run = 0
    for r in rain:
        run = run + 1 if r < RAIN_DAY_MM else 0
        best = max(best, run)
    return best


def annual_series(d: Days) -> list[dict]:
    out = []
    for y, (i0, i1) in sorted(d.spans.items()):
        rain, et0 = sum(d.rain[i0:i1]), sum(d.et0[i0:i1])
        row = {
            "year": y,
            "t_mean": rnd(mean(d.t[i0:i1]), 2),
            "precip_mm": rnd(rain, 0),
            "et0_mm": rnd(et0, 0),
            # aridity index P/ET0: below 0.2 arid, 0.2-0.5 semi-arid (UNEP classes)
            "aridity": rnd(rain / et0, 3) if et0 else None,
            "soil_wetness": rnd(mean(d.soil[i0:i1]), 3),
            "t_max": None, "hot_days": None, "frost_days": None, "rain_days": None, "dry_spell_days": None,
        }
        if d.daily:
            row.update({
                "t_max": rnd(max(d.tmax[i0:i1]), 1),
                "hot_days": sum(v >= HOT_DAY_C for v in d.tmax[i0:i1]),
                "frost_days": sum(v < 0 for v in d.tmin[i0:i1]),
                "rain_days": sum(v >= RAIN_DAY_MM for v in d.rain[i0:i1]),
                "dry_spell_days": _longest_dry_spell(d.rain[i0:i1]),
            })
        out.append(row)
    return out


def _in(period, year) -> bool:
    return period[0] <= year <= period[1]


def shift(annual: list[dict], field: str, digits: int) -> dict:
    """Baseline vs recent period for one annual metric, with trend and projection."""
    years = [a["year"] for a in annual]
    values = [a[field] for a in annual]
    base = mean(a[field] for a in annual if _in(BASELINE, a["year"]))
    recent = mean(a[field] for a in annual if _in(RECENT, a["year"]))
    delta = recent - base if base is not None and recent is not None else None
    fit = ph.ols(years, values)
    p = ph.mann_kendall_p(values)
    out = {
        "baseline": rnd(base, digits),
        "recent": rnd(recent, digits),
        "delta": rnd(delta, digits),
        "delta_pct": rnd(100 * delta / base, 1) if delta is not None and base else None,
        "trend_per_decade": rnd(fit["slope"] * 10, max(digits, 2)) if fit else None,
        "trend_p_value": rnd(p, 3),
        "trend_significant": p is not None and p < 0.05,
        "trend_line": None,
        "projection": None,
    }
    if fit:
        y0, y1 = years[0], years[-1]
        out["trend_line"] = [{"year": y, "value": rnd(fit["intercept"] + fit["slope"] * y, max(digits, 2))}
                             for y in (y0, y1)]
        value, low, high = ph.predict(fit, PROJECTION_YEAR)
        d2 = max(digits, 2)
        out["projection"] = {
            "year": PROJECTION_YEAR, "value": rnd(value, digits), "low": rnd(low, digits), "high": rnd(high, digits),
            # 80% prediction interval of the linear trend, year by year, for the chart
            "band": [{"year": y, "value": rnd(v, d2), "low": rnd(lo, d2), "high": rnd(hi, d2)}
                     for y in range(y1 + 1, PROJECTION_YEAR + 1) for v, lo, hi in [ph.predict(fit, y)]],
        }
    return out


def monthly_climatology(d: Days, period) -> dict:
    """Average year of a period: 12 values per metric, for the 'then vs now' charts."""
    sums = {k: [[] for _ in range(12)] for k in ("t", "rain_mm", "et0_mm", "soil")}
    for y in range(period[0], period[1] + 1):
        if y not in d.spans:
            continue
        for m in range(1, 13):
            i0 = d.idx(date(y, m, 1))
            i1 = d.idx(date(y + (m == 12), m % 12 + 1, 1))
            sums["t"][m - 1].append(mean(d.t[i0:i1]))
            sums["rain_mm"][m - 1].append(sum(d.rain[i0:i1]))
            sums["et0_mm"][m - 1].append(sum(d.et0[i0:i1]))
            sums["soil"][m - 1].append(mean(d.soil[i0:i1]))
    digits = {"t": 1, "rain_mm": 1, "et0_mm": 1, "soil": 3}
    return {k: [rnd(mean(v), digits[k]) for v in months] for k, months in sums.items()}


# ---------- frost season ----------

def _mmdd(doy) -> str | None:
    if doy is None:
        return None
    return (date(2001, 1, 1) + timedelta(days=int(round(doy)) - 1)).strftime("%m-%d")


def frost_season(d: Days) -> dict | None:
    """Last spring frost, first autumn frost and frost-free days. Northern hemisphere, daily data only."""
    if not d.daily or d.lat < 0:
        return None
    rows = {}
    for y, (i0, i1) in d.spans.items():
        mid = i0 + 181
        last = next((i - i0 + 1 for i in range(mid, i0 - 1, -1) if d.tmin[i] < 0), None)
        first = next((i - i0 + 1 for i in range(mid, i1) if d.tmin[i] < 0), None)
        rows[y] = (last, first)
    if not any(a is not None for a, _ in rows.values()):
        return None

    def stats(period):
        last = [rows[y][0] or 1 for y in rows if _in(period, y)]
        first = [rows[y][1] or 366 for y in rows if _in(period, y)]
        return {
            "last_spring_frost": _mmdd(percentile(last, 50)),
            "last_spring_frost_late_year": _mmdd(percentile(last, 90)),
            "first_autumn_frost": _mmdd(min(percentile(first, 50), 365)),
            "frost_free_days": rnd(mean(f - l for l, f in zip(last, first)), 0),
            "_last": percentile(last, 50),
        }

    base, recent = stats(BASELINE), stats(RECENT)
    out = {
        "baseline": {k: v for k, v in base.items() if not k.startswith("_")},
        "recent": {k: v for k, v in recent.items() if not k.startswith("_")},
        "last_frost_shift_days": rnd(recent["_last"] - base["_last"], 0),
        "frost_free_change_days": rnd(recent["frost_free_days"] - base["frost_free_days"], 0),
    }
    return out


# ---------- now: last 30 days and typical next 30 days ----------

def _same_day(d: Days, y: int, ref: date) -> int:
    day = min(ref.day, 28) if ref.month == 2 else ref.day
    return d.idx(date(y, ref.month, day))


def recent_conditions(d: Days, window: int = 30) -> dict | None:
    if not d.daily or d.n < window:
        return None
    i1 = d.n
    as_of = d.day(i1 - 1)
    rain, et0 = sum(d.rain[i1 - window:i1]), sum(d.et0[i1 - window:i1])
    since = next((k for k in range(i1) if d.rain[i1 - 1 - k] >= RAIN_DAY_MM), None)
    history = []
    for y in d.years:
        j1 = _same_day(d, y, as_of) + 1
        if j1 - window >= 0 and j1 <= d.n and y != as_of.year:
            history.append(sum(d.rain[j1 - window:j1]))
    rank = rnd(100 * sum(h <= rain for h in history) / len(history), 0) if history else None
    return {
        "as_of": as_of.isoformat(),
        "window_days": window,
        "rain_mm": rnd(rain, 1),
        "et0_mm": rnd(et0, 1),
        "balance_mm": rnd(rain - et0, 1),
        "t_mean": rnd(mean(d.t[i1 - window:i1]), 1),
        "days_since_rain": since,
        "rain_normal_mm": spread(history, 1),
        "rain_percentile": rank,  # 0 = driest on record for these dates, 100 = wettest
    }


def outlook(d: Days) -> dict | None:
    """What the next 30 days usually look like here: statistics of the same dates in 2011-2025.

    This is climatology, not a weather forecast.
    """
    if not d.daily:
        return None
    today = d.day(d.n - 1) + timedelta(days=1)
    rain30, rain7, et30, et7, wait, t30 = [], [], [], [], [], []
    for y in range(RECENT[0], RECENT[1] + 1):
        j0 = _same_day(d, y, today)
        if j0 < 0 or j0 + 30 > d.n:
            continue
        rain30.append(sum(d.rain[j0:j0 + 30]))
        rain7.append(sum(d.rain[j0:j0 + 7]))
        et30.append(sum(d.et0[j0:j0 + 30]))
        et7.append(sum(d.et0[j0:j0 + 7]))
        t30.append(mean(d.t[j0:j0 + 30]))
        wait.append(next((k for k in range(30) if d.rain[j0 + k] >= RAIN_DAY_MM), 30))
    if not rain30:
        return None
    return {
        "from": today.isoformat(),
        "years_used": len(rain30),
        "rain_30d_mm": spread(rain30, 1),
        "rain_7d_mm": spread(rain7, 1),
        "et0_30d_mm": spread(et30, 1),
        "et0_7d_mm": spread(et7, 1),
        "t_mean_30d": spread(t30, 1),
        "rain_within_7d_probability": rnd(sum(w < 7 for w in wait) / len(wait), 2),
        "days_to_rain": spread(wait, 0),
    }


# ---------- entry point ----------

def analyze(d: Days) -> dict:
    annual = annual_series(d)
    fields = [("t_mean", 2), ("precip_mm", 0), ("et0_mm", 0), ("aridity", 3), ("soil_wetness", 3)]
    if d.daily:
        fields += [("t_max", 1), ("hot_days", 0), ("frost_days", 0), ("rain_days", 0), ("dry_spell_days", 0)]
    return {
        "shift": {name: shift(annual, name, digits) for name, digits in fields},
        "annual": annual,
        "monthly": {"baseline": monthly_climatology(d, BASELINE), "recent": monthly_climatology(d, RECENT)},
        "frost": frost_season(d),
        "et0_method": {
            "penman_monteith_share": rnd(d.pm_share, 3),
            "name": "FAO-56 Penman-Monteith" if d.pm_share > 0.9 else "FAO-56 Penman-Monteith + Hargreaves",
        },
        "data_quality": {"resolution": d.resolution, "days": d.n, "filled_days": d.gaps,
                         "last_day": d.day(d.n - 1).isoformat(), "elevation_m": rnd(d.elevation, 0)},
    }
