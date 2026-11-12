"""Builds backend/data/country_crops.json from FAOSTAT bulk files (run once, offline afterwards).

What is grown in each country, how much it yields and what farmers are paid:
  area harvested (ha), yield (t/ha)   FAOSTAT domain QCL "Crops and livestock products"
  producer price (USD/tonne)          FAOSTAT domain PP  "Producer prices"
Values are means of the last YEARS years that have data. Countries are keyed by ISO 3166 alpha-2,
matched through the UN M49 code. Sub-region and world medians fill gaps for yield and price.

Download (about 45 MB together):
  https://bulks-faostat.fao.org/production/Production_Crops_Livestock_E_All_Data_(Normalized).zip
  https://bulks-faostat.fao.org/production/Prices_E_All_Data_(Normalized).zip
  https://raw.githubusercontent.com/lukes/ISO-3166-Countries-with-Regional-Codes/master/all/all.csv
Run from the repository root:
  python -m backend.tools.build_country_crops QCL.zip PP.zip all.csv
"""
from __future__ import annotations

import csv
import io
import json
import statistics
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

YEARS = 5
TOP_N = 12
OUT = Path(__file__).resolve().parent.parent / "data" / "country_crops.json"
AREA, YIELD, PRICE_USD = "5312", "5412", "5532"


def _rows(zip_path: str, member_suffix: str):
    z = zipfile.ZipFile(zip_path)
    name = next(n for n in z.namelist() if n.endswith(member_suffix))
    yield from csv.DictReader(io.TextIOWrapper(z.open(name), encoding="latin1"))


def _m49(code: str) -> str:
    return code.strip("'").lstrip("0") or "0"


def _yield_t_ha(value: float, unit: str) -> float:
    unit = unit.strip().lower()
    if unit in ("hg/ha", "100 g/ha"):
        return value / 10_000
    if unit == "kg/ha":
        return value / 1000
    if unit == "t/ha":
        return value
    raise ValueError(f"unknown yield unit {unit!r}")


def build(qcl_zip: str, pp_zip: str, iso_csv: str) -> dict:
    iso = {}
    with open(iso_csv, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            iso[r["country-code"].lstrip("0")] = {"iso": r["alpha-2"], "name": r["name"],
                                                  "subregion": r["intermediate-region"] or r["sub-region"]}
    items: dict[int, str] = {}
    # (m49, item) -> year -> value
    area, yld, price = (defaultdict(dict) for _ in range(3))
    for r in _rows(qcl_zip, "All_Data_(Normalized).csv"):
        el = r["Element Code"]
        if el not in (AREA, YIELD):
            continue
        m49, item = _m49(r["Area Code (M49)"]), int(r["Item Code"])
        if m49 not in iso or item >= 1700 or not r["Value"]:  # skip regions and aggregate items
            continue
        items[item] = r["Item"]
        value = float(r["Value"])
        if el == AREA:
            area[(m49, item)][int(r["Year"])] = value
        else:
            yld[(m49, item)][int(r["Year"])] = _yield_t_ha(value, r["Unit"])
    for r in _rows(pp_zip, "All_Data_(Normalized).csv"):
        if r["Element Code"] != PRICE_USD or r.get("Months Code") != "7021" or not r["Value"]:
            continue
        m49 = _m49(r["Area Code (M49)"])
        if m49 in iso:
            price[(m49, int(r["Item Code"]))][int(r["Year"])] = float(r["Value"])

    def recent(series: dict, last: int) -> tuple[float | None, list[int]]:
        """Mean of the years last-YEARS+1..last that have a value (older data is not "grown now")."""
        years = sorted(y for y, v in series.items() if v and v > 0 and y > last - YEARS)
        return (statistics.fmean(series[y] for y in years), years) if years else (None, [])

    countries, by_sub = {}, defaultdict(lambda: defaultdict(lambda: {"yield": [], "price": []}))
    world = defaultdict(lambda: {"yield": [], "price": []})
    for m49, meta in iso.items():
        crops, span = {}, []
        mine = {item: series for (m, item), series in area.items() if m == m49}
        last = max((y for series in mine.values() for y, v in series.items() if v and v > 0), default=None)
        if last is None:
            continue
        price_last = max((y for (m, _i), ser in price.items() if m == m49 for y in ser), default=last)
        for item, series in mine.items():
            ha, years = recent(series, last)
            if not ha:
                continue
            y, _ = recent(yld.get((m49, item), {}), last)
            p, _ = recent(price.get((m49, item), {}), price_last)
            crops[item] = {"area_ha": round(ha), "yield_t_ha": round(y, 3) if y else None,
                           "price_usd_t": round(p) if p else None}
            span += years
            for bucket in (by_sub[meta["subregion"]][item], world[item]):
                if y:
                    bucket["yield"].append(y)
                if p:
                    bucket["price"].append(p)
        if not crops:
            continue
        total = sum(c["area_ha"] for c in crops.values())
        top = sorted(crops.items(), key=lambda kv: -kv[1]["area_ha"])[:TOP_N]
        countries[meta["iso"]] = {
            "name": meta["name"], "subregion": meta["subregion"],
            "years": [min(span), max(span)], "cropland_ha": round(total),
            "top": [{"item": i, "name": items[i], "area_ha": c["area_ha"], "share": round(c["area_ha"] / total, 4)} for i, c in top],
            "crops": {str(i): c for i, c in crops.items()},
        }

    def medians(buckets):
        return {str(i): {k: round(statistics.median(v), 3) if v else None for k, v in b.items()} for i, b in buckets.items()}

    return {
        "_source": "FAOSTAT QCL (area harvested, yield) and PP (producer price, USD/tonne), FAO of the UN, "
                   f"means of the last {YEARS} years with data; built by backend/tools/build_country_crops.py",
        "items": {str(i): n for i, n in sorted(items.items())},
        "countries": countries,
        "subregions": {s: medians(b) for s, b in by_sub.items()},
        "world": medians(world),
    }


if __name__ == "__main__":
    data = build(*sys.argv[1:4])
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(data['countries'])} countries -> {OUT} ({OUT.stat().st_size // 1024} KB)")
