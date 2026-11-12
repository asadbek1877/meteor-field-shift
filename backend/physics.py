"""Physics and statistics helpers. Pure Python.

Evapotranspiration follows FAO Irrigation and Drainage Paper 56 (Allen et al., 1998):
  * Penman-Monteith reference ET0 (eq. 6) with net radiation from eq. 37-40
  * Hargreaves ET0 (eq. 52) when radiation, humidity or wind are missing
  * extraterrestrial radiation Ra (eq. 21)
"""
from __future__ import annotations

import math


# ---------- statistics ----------

def mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def percentile(values, q: float):
    """Linear-interpolated percentile, q in 0..100."""
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    pos = (len(values) - 1) * q / 100
    lo = math.floor(pos)
    hi = min(lo + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


def rnd(value, digits: int = 2):
    if value is None:
        return None
    return round(value, digits) if digits else int(round(value))


def spread(values, digits: int = 0) -> dict | None:
    """Year-to-year spread: 10th, 50th and 90th percentile."""
    values = [v for v in values if v is not None]
    if not values:
        return None
    return {f"p{q}": rnd(percentile(values, q), digits) for q in (10, 50, 90)}


def ols(xs, ys) -> dict | None:
    """Least-squares line y = a + b*x with what is needed for a prediction interval."""
    pairs = [(x, y) for x, y in zip(xs, ys) if y is not None]
    n = len(pairs)
    if n < 5:
        return None
    mx = sum(x for x, _ in pairs) / n
    my = sum(y for _, y in pairs) / n
    sxx = sum((x - mx) ** 2 for x, _ in pairs)
    if not sxx:
        return None
    slope = sum((x - mx) * (y - my) for x, y in pairs) / sxx
    intercept = my - slope * mx
    sse = sum((y - intercept - slope * x) ** 2 for x, y in pairs)
    return {"slope": slope, "intercept": intercept, "n": n, "mx": mx, "sxx": sxx,
            "sd": math.sqrt(sse / (n - 2))}


def predict(fit: dict, x: float, t_value: float = 1.31) -> tuple[float, float, float]:
    """Trend value at x with an 80% prediction interval (t = 1.31 for about 30 years of data)."""
    y = fit["intercept"] + fit["slope"] * x
    half = t_value * fit["sd"] * math.sqrt(1 + 1 / fit["n"] + (x - fit["mx"]) ** 2 / fit["sxx"])
    return y, y - half, y + half


def mann_kendall_p(ys):
    """Two-sided p-value of a monotonic trend (normal approximation, no tie correction)."""
    ys = [y for y in ys if y is not None]
    n = len(ys)
    if n < 8:
        return None
    s = sum((ys[j] > ys[i]) - (ys[j] < ys[i]) for i in range(n - 1) for j in range(i + 1, n))
    if s == 0:
        return 1.0
    var = n * (n - 1) * (2 * n + 5) / 18
    z = (s - 1 if s > 0 else s + 1) / math.sqrt(var)
    return math.erfc(abs(z) / math.sqrt(2))


# ---------- evapotranspiration ----------

def saturation_vp(t: float) -> float:
    """Saturation vapour pressure, kPa (FAO-56 eq. 11)."""
    return 0.6108 * math.exp(17.27 * t / (t + 237.3))


def extraterrestrial_radiation(lat_deg: float, day_of_year: int) -> float:
    """Ra in MJ/m2/day (FAO-56 eq. 21)."""
    phi = math.radians(lat_deg)
    dr = 1 + 0.033 * math.cos(2 * math.pi * day_of_year / 365)
    delta = 0.409 * math.sin(2 * math.pi * day_of_year / 365 - 1.39)
    ws = math.acos(max(-1.0, min(1.0, -math.tan(phi) * math.tan(delta))))
    ra = (24 * 60 / math.pi) * 0.0820 * dr * (
        ws * math.sin(phi) * math.sin(delta) + math.cos(phi) * math.cos(delta) * math.sin(ws)
    )
    return max(ra, 0.0)


def et0_hargreaves(t_mean: float, t_max: float, t_min: float, ra: float) -> float:
    """Reference ET in mm/day (FAO-56 eq. 52)."""
    return max(0.0, 0.0023 * (t_mean + 17.8) * math.sqrt(max(t_max - t_min, 0.0)) * 0.408 * ra)


def et0_penman_monteith(t_max: float, t_min: float, t_mean: float, rs: float, u2: float,
                        ra: float, elevation: float, rh: float | None = None,
                        ea: float | None = None, g: float = 0.0) -> float:
    """FAO-56 Penman-Monteith reference ET in mm/day (eq. 6).

    rs: solar radiation MJ/m2/day, u2: wind at 2 m in m/s, rh: mean relative humidity in %,
    ea: actual vapour pressure kPa (used instead of rh when given).
    """
    es = (saturation_vp(t_max) + saturation_vp(t_min)) / 2
    if ea is None:
        ea = es * max(0.0, min(rh, 100.0)) / 100
    delta = 4098 * saturation_vp(t_mean) / (t_mean + 237.3) ** 2
    pressure = 101.3 * ((293 - 0.0065 * elevation) / 293) ** 5.26
    gamma = 0.000665 * pressure
    rso = (0.75 + 2e-5 * elevation) * ra
    rel = min(rs / rso, 1.0) if rso > 0 else 0.5
    rns = 0.77 * rs
    rnl = (4.903e-9 * ((t_max + 273.16) ** 4 + (t_min + 273.16) ** 4) / 2
           * (0.34 - 0.14 * math.sqrt(ea)) * (1.35 * rel - 0.35))
    rn = rns - rnl
    et0 = (0.408 * delta * (rn - g) + gamma * 900 / (t_mean + 273) * u2 * (es - ea)) / (
        delta + gamma * (1 + 0.34 * u2))
    return max(et0, 0.0)
