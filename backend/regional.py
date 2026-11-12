"""Regional crop plan: what farmers actually grow here, what of it works at this point, and rotations.

Steps for one point:
  1. what is grown here: MapSPAM 2020 (backend/data/local_crops.json.gz), harvested area of 46 crops
     on a ~25 km grid worldwide, for the grid cell that holds the point -> the crop mix of THIS place,
     not just the country average. Falls back to the country's FAOSTAT mix where MapSPAM has no cell
     (e.g. a sea point that still resolves to a nearby coast, or a very small cropland share).
  2. FAOSTAT (backend/data/country_crops.json) also gives national yield (t/ha) and producer price
     (USD/t) for income per hectare, independent of which source picked the crop mix.
  3. every crop in the library is localized to the point (sowing day from its own NASA POWER
     temperatures) and simulated over 2011-2025; it is "possible here" when it ripens in most years
  4. candidate rotations are generated from the crops grown here AND that work here, plus a legume
     when the local mix has none; the typical local rotation is the "current" one
  5. agro.Field then scores the candidates as before (water, income, soil, climate risk)

The crop mix differs from one place to the next even inside one country, because MapSPAM is already
sub-national; the simulated "works here" check differs too, because it uses the climate of the point:
rice drops out in a cold valley, winter wheat in the tropics, cotton where the season is too short.
"""
from __future__ import annotations

import gzip
import json
from functools import lru_cache
from pathlib import Path

from . import agro
from .climate import RECENT, Days

DATA_FILE = Path(__file__).parent / "data" / "country_crops.json"
LOCAL_FILE = Path(__file__).parent / "data" / "local_crops.json.gz"
MIN_SHARE = 0.005          # a crop on less than 0.5 % of the cropland is not "typical"
MAX_FROST, MAX_COLD = 0.3, 0.3   # share of years the crop may fail for that reason
# Heat does not rule a crop out: it cuts yield, which the risk and income scores already count.
HORTICULTURE = {"tomato", "onion", "potato"}  # shown in the profile, left out of field-crop rotations:
                                    # their gross income without production costs would dominate the ranking
OUTLIER = 3.0                       # a country income above 3x the world median is treated as a data error
MAX_ROTATIONS = 8
WINTER = {"winter_wheat", "rapeseed"}                                     # sown in autumn
SECOND = ["mung_bean", "soybean", "dry_bean", "millet", "sorghum", "sunflower", "maize"]  # after a winter crop
SAME_ITEM_ORDER = {15: ["winter_wheat", "spring_wheat"]}                  # FAOSTAT "Wheat" is either


@lru_cache(maxsize=1)
def data() -> dict:
    try:
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"countries": {}, "subregions": {}, "world": {}, "items": {}}


@lru_cache(maxsize=1)
def world_area() -> dict[str, float]:
    """FAOSTAT item -> hectares worldwide; orders crops when the country is unknown."""
    out: dict[str, float] = {}
    for c in data()["countries"].values():
        for item, v in c["crops"].items():
            out[item] = out.get(item, 0) + v["area_ha"]
    return out


# MapSPAM crop code -> library crops it can be (first one that works at the point is used)
SPAM_CROP_IDS = {
    "whea": ["winter_wheat", "spring_wheat"], "rice": ["rice"], "maiz": ["maize"], "barl": ["barley"],
    "mill": ["millet"], "pmil": ["millet"], "sorg": ["sorghum"], "pota": ["potato"], "bean": ["dry_bean"],
    "chic": ["chickpea"], "lent": ["lentil"], "soyb": ["soybean"], "grou": ["groundnut"],
    "sunf": ["sunflower"], "rape": ["rapeseed"], "sugb": ["sugar_beet"], "cott": ["cotton"],
    "toma": ["tomato"], "onio": ["onion"],
}
# names of MapSPAM crops the app does not simulate (shown in the list, not used in rotations)
SPAM_LABEL = {
    "ocer": ("Other cereals", "Boshqa donli ekinlar"), "swpo": ("Sweet potato", "Batat"),
    "yams": ("Yams", "Yams"), "cass": ("Cassava", "Kassava"), "orts": ("Other roots", "Boshqa ildizmevalar"),
    "cowp": ("Cowpea", "Sigir no'xati"), "pige": ("Pigeon pea", "Kaptar no'xati"),
    "opul": ("Other pulses (incl. mung bean)", "Boshqa dukkaklilar (mosh bilan)"),
    "cnut": ("Coconut", "Kokos"), "oilp": ("Oil palm", "Moyli palma"), "sesa": ("Sesame", "Kunjut"),
    "ooil": ("Other oil crops", "Boshqa moyli ekinlar"), "sugc": ("Sugar cane", "Shakarqamish"),
    "ofib": ("Other fibre crops", "Boshqa tolali ekinlar"), "coff": ("Arabica coffee", "Arabika qahva"),
    "rcof": ("Robusta coffee", "Robusta qahva"), "coco": ("Cocoa", "Kakao"), "teas": ("Tea", "Choy"),
    "toba": ("Tobacco", "Tamaki"), "bana": ("Banana", "Banan"), "plnt": ("Plantain", "Plantain"),
    "trof": ("Tropical fruit", "Tropik mevalar"), "temf": ("Orchards (temperate fruit)", "Bog'lar (mevalar)"),
    "vege": ("Vegetables", "Sabzavotlar"), "rest": ("Other crops", "Boshqa ekinlar"),
    "citr": ("Citrus", "Sitrus"), "rubb": ("Rubber", "Kauchuk"),
}


@lru_cache(maxsize=1)
def local_data() -> dict | None:
    try:
        with gzip.open(LOCAL_FILE, "rt", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def local_cell(lat: float, lon: float) -> dict | None:
    """MapSPAM crop mix of the ~25 km cell that holds the point, with its province (admin-1)."""
    db = local_data()
    if not db:
        return None
    step = db["cell_deg"]
    cell = db["cells"].get(f"{int((lat + 90) // step)},{int((lon + 180) // step)}")
    if not cell:
        return None
    pixels, entries = cell
    # the province of the ~9 km pixel under the point; a pixel without crops takes the nearest one that has
    k = step / 3
    sy, sx = min(2, int(((lat + 90) % step) // k)), min(2, int(((lon + 180) % step) // k))
    order = sorted(range(9), key=lambda i: (i // 3 - sy) ** 2 + (i % 3 - sx) ** 2)
    rid = next((pixels[i] for i in order if pixels[i] >= 0), entries[0][0])
    region_id = next((e for e in entries if e[0] == rid), entries[0])[0]
    region = db["regions"][region_id]
    # One ~25 km cell can be noisy where cropland is small, so the 3x3 cells around the point
    # (about 75 km) are summed, keeping only the part that lies in the same province.
    iy, ix = int((lat + 90) // step), int((lon + 180) // step)
    ha_by_crop: dict[int, float] = {}
    total_ha = 0
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            near = db["cells"].get(f"{iy + dy},{ix + dx}")
            for e in (near[1] if near else []):
                if e[0] == region_id:
                    total_ha += e[1]
                    for i, ha in e[2]:
                        ha_by_crop[i] = ha_by_crop.get(i, 0) + ha
    top = sorted(ha_by_crop.items(), key=lambda kv: -kv[1])[:8]
    return {"region": region["name"], "country": region["country"], "cropland_ha": total_ha,
            "top": [(db["crops"][i], ha) for i, ha in top], "source": db["_source"]}


def crop_ids(item: int) -> list[str]:
    return SAME_ITEM_ORDER.get(item) or [c["id"] for c in agro.CONFIG["crops"] if c.get("fao_item") == item]


def economics(iso: str | None) -> dict[str, dict]:
    """crop id -> {usd_ha, yield_t_ha, price_usd_t, source}; source says which level filled the gap."""
    db = data()
    country = db["countries"].get(iso or "")
    sub = db["subregions"].get(country["subregion"], {}) if country else {}
    out = {}
    for crop in agro.CONFIG["crops"]:
        item = crop.get("fao_item")
        if not item:
            out[crop["id"]] = {"usd_ha": crop["revenue_usd_ha"], "yield_t_ha": None, "price_usd_t": None, "source": "default"}
            continue
        key = str(item)
        mine = (country or {}).get("crops", {}).get(key, {})
        y, p, src = mine.get("yield_t_ha"), mine.get("price_usd_t"), "country"
        for level, name in ((sub.get(key, {}), "subregion"), (db["world"].get(key, {}), "world")):
            if y is None or p is None:
                src = name
                y = y if y is not None else level.get("yield")
                p = p if p is not None else level.get("price")
        w = db["world"].get(key, {})
        if y and p and w.get("yield") and w.get("price") and y * p > OUTLIER * w["yield"] * w["price"]:
            y, p, src = w["yield"], w["price"], "world"
        if y and p:
            out[crop["id"]] = {"usd_ha": round(y * p), "yield_t_ha": round(y, 2), "price_usd_t": round(p), "source": src}
        else:
            out[crop["id"]] = {"usd_ha": crop["revenue_usd_ha"], "yield_t_ha": None, "price_usd_t": None, "source": "default"}
    return out


def _verdict(crop: dict, recent: dict | None) -> str | None:
    """None when the crop works here, otherwise why not."""
    if crop.get("no_window"):
        return "too_warm_for_winter" if crop["sowing"]["kind"] == "autumn" else "season_too_cold"
    if not recent:
        return "no_data"
    if recent["frost_years_share"] > MAX_FROST:
        return "frost"
    if recent["cold_years_share"] > MAX_COLD:
        return "season_too_cold"
    return None


def _name(years: list, lang: str) -> str:
    return " – ".join(" + ".join(agro.CROPS[c]["name"][lang] for c in slot) for slot in years)


def _cycle(years: list) -> tuple:
    """Same key for every starting year of one cycle."""
    keys = [tuple(tuple(slot) for slot in years[k:] + years[:k]) for k in range(len(years))]
    return min(keys)


def _rotation(years: list, origin: str) -> dict:
    return {"id": "|".join("+".join(slot) for slot in years),
            "name": {lang: _name(years, lang) for lang in ("en", "uz")},
            "years": years, "origin": origin}


def plan(d: Days, iso: str | None, soil: str, irrigation: str) -> dict:
    """-> {"field": agro.Field, "candidates", "default_current", "show": crop ids for the crop table, "profile"}"""
    iso = (iso or "").upper() or None
    db = data()
    country = db["countries"].get(iso or "")
    monthly = agro._monthly_recent(d)
    local = {cid: agro.localize(d, crop, monthly) for cid, crop in agro.CROPS.items()}
    money = economics(iso)
    field = agro.Field(d, soil, irrigation, crops=local, revenue={k: v["usd_ha"] for k, v in money.items()})

    # 1. which crops work at this point
    verdict = {cid: _verdict(crop, field._period(crop, RECENT)) for cid, crop in local.items()}
    ok = lambda cid: verdict[cid] is None  # noqa: E731

    # 2. what is grown HERE (MapSPAM cell), else in the country (FAOSTAT), else in the world
    share: dict[str, float] = {}
    cell = local_cell(d.lat, d.lon)
    top: list[dict] = []
    if cell:
        total = sum(ha for _, ha in cell["top"]) or 1
        for code, ha in cell["top"]:
            ids = SPAM_CROP_IDS.get(code)
            cid = next((c for c in ids if ok(c)), ids[0]) if ids else None
            if cid:
                share[cid] = share.get(cid, 0) + ha / total
            en, uz = SPAM_LABEL.get(code, (code, code))
            top.append({"crop_id": cid, "label": None if cid else {"en": en, "uz": uz}, "share": ha / total,
                        "here": None if not cid else ("yes" if ok(cid) else "no"),
                        "reason": verdict.get(cid) if cid else None})
    elif country:
        total = country["cropland_ha"] or 1
        for item, v in sorted(country["crops"].items(), key=lambda kv: -kv[1]["area_ha"]):
            ids = crop_ids(int(item))
            if not ids:
                continue
            pick = next((c for c in ids if ok(c)), ids[0])
            share[pick] = share.get(pick, 0) + v["area_ha"] / total
    else:  # unknown country: the world's most common crops first
        area = world_area()
        for crop in sorted(agro.CONFIG["crops"], key=lambda c: -area.get(str(c.get("fao_item")), 0)):
            share.setdefault(crop["id"], 0.0)
    known_mix = bool(cell or country)
    typical = [c for c, s in sorted(share.items(), key=lambda kv: -kv[1]) if s >= MIN_SHARE or not known_mix]
    grown = [c for c in typical if ok(c)]
    not_here = [{"id": c, "reason": verdict[c]} for c in typical if not ok(c)]

    # a legume for soil health when the local mix has none (soybean, chickpea, bean, lentil, mung, groundnut)
    suggested = []
    if not any(agro.CROPS[c]["legume"] for c in grown[:6]):
        legumes = [c for c in local if agro.CROPS[c]["legume"] and not agro.CROPS[c]["perennial"] and ok(c) and c not in grown]
        legumes.sort(key=lambda c: (field._period(local[c], RECENT) or {}).get("irrigation_mean_mm", 1e9))
        suggested = legumes[:1]

    # 3. rotations
    pool = [c for c in grown if c not in HORTICULTURE][:6]
    south = d.lat < 0
    cands: list[dict] = []

    def add(years: list, origin: str):
        flat = [c for slot in years for c in slot]
        # "wheat - wheat" is just wheat (reference rotations may keep a perennial for two years)
        if not flat or (origin != "reference" and any(x == y for x, y in zip(years, years[1:]))):
            return
        if not all(c in local and ok(c) for c in flat) or agro.conflicts(years, south, local):
            return
        for slot in years:  # a second crop is sown after the first harvest: it must work at that time too
            for crop in agro.placed(slot, local, south)[1:]:
                if _verdict(crop, field._period(crop, RECENT)) is not None:
                    return
        r = _rotation(years, origin)
        # "wheat - cotton" and "cotton - wheat" are the same cycle started in another year
        if all(_cycle(years) != _cycle(c["years"]) for c in cands):
            cands.append(r)

    default_id = None
    if pool:
        a = pool[0]
        b = next((c for c in pool[1:] if agro.CROPS[c]["family"] != agro.CROPS[a]["family"]), pool[1] if len(pool) > 1 else None)
        legume = next((c for c in pool if agro.CROPS[c]["legume"]), None) or (suggested[0] if suggested else None)
        other = next((c for c in pool if c not in (a, b, legume)), None)
        # Typical practice: the two biggest crops of the country, in one year where the climate allows
        # (rice + wheat in Punjab, wheat + maize in Egypt, soybean + maize in Brazil), else one after the other.
        second = pool[1] if len(pool) > 1 and share.get(pool[1], 0) >= 0.25 * share.get(a, 0) else None
        for years in ([[a, second]], [[second, a]], [[a], [second]]) if second else ([[a]],):
            add(years, "typical")
            if cands:
                break
        default_id = cands[0]["id"] if cands else None
        if iso == "UZ":  # reviewed reference rotations of the Uzbek case
            for r in agro.ROTATIONS["rotations"]:
                add(r["years"], "reference")
        # double cropping: two crops in one year, the second sown after the first harvest
        # (winter wheat + mung bean in Uzbekistan, wheat + maize in Egypt, soybean + maize in Brazil)
        warm = min(monthly[0]) >= 15 if all(v is not None for v in monthly[0]) else False
        firsts = [c for c in pool if c in WINTER or warm][:3]
        for w in firsts:
            seconds = ([legume] if legume else []) + [s for s in pool if s in SECOND] + SECOND
            for s in dict.fromkeys(x for x in seconds if x and x != w):
                origin = "local" if s in grown else "suggested"
                before = len(cands)
                add([[w, s]], origin)
                x = a if a != w else b
                if x and x != s:
                    add([[x], [w, s]], origin)
                if len(cands) > before:
                    break
        add([[a]], "local")
        if b:
            add([[a], [b]], "local")
        if legume and legume != a:
            add([[a], [legume]], "local" if legume in grown else "suggested")
            if b and legume != b:
                add([[a], [b], [legume]], "local" if legume in grown else "suggested")
                add([[b], [legume]], "local" if legume in grown else "suggested")
        if other:
            add([[a], [other]], "local")
            if b:
                add([[a], [b], [other]], "local")
    if default_id is None and cands:
        default_id = cands[0]["id"]

    show = list(dict.fromkeys(grown[:8] + suggested))
    if not cell and country:
        for t in country["top"][:10]:
            ids = crop_ids(t["item"])
            cid = next((c for c in ids if c in share), ids[0] if ids else None)
            top.append({"item": t["item"], "name_en": t["name"], "share": t["share"], "crop_id": cid,
                        "here": None if not cid else ("yes" if ok(cid) else "no"),
                        "reason": verdict.get(cid) if cid else None})
    return {
        "field": field,
        "candidates": cands[:MAX_ROTATIONS],
        "default_current": default_id,
        "show": show,
        "profile": {
            "country": {"iso": iso, "name": country["name"], "years": country["years"],
                        "cropland_ha": country["cropland_ha"]} if country else None,
            "local": {"region": cell["region"], "country": cell["country"],
                      "cropland_ha": cell["cropland_ha"], "source": cell["source"]} if cell else None,
            "top": top,
            "grown_here": grown,
            "not_here": not_here,
            "suggested": suggested,
            "economics": {c: money[c] for c in show},
            "sowing": {c: agro.sow_date(local[c], 2001, south).strftime("%m-%d") for c in show},
            "source": db.get("_source"),
        },
    }
