"""Builds backend/data/local_crops.json.gz: what farmers grow in each region of the world.

Source: MapSPAM 2020 v2r2 (IFPRI, Harvard Dataverse doi:10.7910/DVN/SWPENT), harvested area of
46 crops on a 5 arc-minute grid (about 10 km), all technologies (irrigated + rain-fed).
Output, so a point can be answered offline:
  cells    0.25 degree cells -> [region id of each of the 3x3 native 5' pixels (-1 = no crops),
           [[region id, cropland ha, top crops [[crop index, ha], ...]], ...] one entry per region]
           A cell on a border keeps each side apart, so a point gets the crops of its own province.
  regions  admin-1 regions (province / oblast / state) -> name, country, hectares per crop and, when the
           production file is given, the yield of the province in t/ha (production / harvested area)
Run from the repository root (the zips are the files downloaded from Dataverse):
  python -m backend.tools.build_local_crops spam2020V2r2_global_harvested_area.csv.zip       spam2020V2r2_global_production.csv.zip
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "local_crops.json.gz"
CELL = 0.25          # degrees; about 25 km, finer than NASA POWER (0.5 x 0.625)
TOP_PER_CELL = 8
MIN_CELL_HA = 50     # cells with less cropland than this are dropped


_META_COLS = {
    "grid_code", "x", "y", "fips0", "fips1", "fips2", "adm0_name", "adm1_name", "adm2_name",
    "iso3", "name_cntr", "alloc_key", "rec_type", "tech_type", "country", "continent", "unit",
}


def _sub(y: float, x: float) -> int:
    """Which of the 3x3 native 5' pixels of a 0.25 degree cell (0..8, row-major from the south-west)."""
    k = CELL / 3
    return min(2, int((y % CELL) // k)) * 3 + min(2, int((x % CELL) // k))


def _member(z: zipfile.ZipFile) -> str:
    """The all-technologies table (…_TA.csv), which already sums every production system."""
    names = [n for n in z.namelist() if n.lower().endswith(".csv")]
    ta = [n for n in names if n[:-4].upper().endswith("_TA")]
    if ta:
        return ta[0]
    if len(names) == 1:
        return names[0]
    raise SystemExit(f"cannot pick the all-technologies table among: {names}")


MIN_YIELD_HA = 500   # a province yield from less harvested area than this is too noisy to use


def _production(zip_path: str) -> dict[str, dict[str, float]]:
    """region id -> crop code -> tonnes produced (MapSPAM production, all technologies)."""
    z = zipfile.ZipFile(zip_path)
    reader = csv.DictReader(io.TextIOWrapper(z.open(_member(z)), encoding="utf-8-sig", errors="replace"))
    cols = {c.lower(): c for c in reader.fieldnames or []}
    crop_cols = [c for c in reader.fieldnames if c.lower() not in _META_COLS]
    a0, a1 = cols.get("adm0_name"), cols.get("adm1_name")
    f0 = cols.get("fips0") or cols.get("iso3")
    out: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for row in reader:
        acc = out[f"{row.get(f0, '')}|{row.get(a0, '')}|{row.get(a1, '')}"]
        for c in crop_cols:
            v = row[c]
            if v and v != "0.0":
                acc[c.lower()] += float(v)
    return out


def build(zip_path: str, production_zip: str | None = None) -> dict:
    z = zipfile.ZipFile(zip_path)
    reader = csv.DictReader(io.TextIOWrapper(z.open(_member(z)), encoding="utf-8-sig", errors="replace"))
    cols = {c.lower(): c for c in reader.fieldnames or []}
    # Crop columns are the 4-letter SPAM codes (whea, rice, maiz, ...): everything that is not metadata.
    crop_cols = [c for c in reader.fieldnames if c.lower() not in _META_COLS]
    crops = [c.lower() for c in crop_cols]
    tech = cols.get("tech_type")
    x_col, y_col = cols["x"], cols["y"]
    a0, a1 = cols.get("adm0_name"), cols.get("adm1_name")
    f0 = cols.get("fips0") or cols.get("iso3")

    cells: dict[tuple, list] = defaultdict(lambda: [0.0] * len(crops))   # (iy, ix, region) -> ha per crop
    pixel_region: dict[tuple, dict] = defaultdict(lambda: defaultdict(float))  # (iy, ix, sub) -> region -> ha
    regions: dict[str, dict] = {}
    region_ha: dict[str, list] = defaultdict(lambda: [0.0] * len(crops))
    for row in reader:
        if tech and row[tech].strip().upper() not in ("A", "TA", "ALL"):
            continue
        values = [float(row[c] or 0) for c in crop_cols]
        total = sum(values)
        if total <= 0:
            continue
        x, y = float(row[x_col]), float(row[y_col])
        iy, ix = int((y + 90) // CELL), int((x + 180) // CELL)
        sub = _sub(y + 90, x + 180)
        rid = f"{row.get(f0, '')}|{row.get(a0, '')}|{row.get(a1, '')}"
        if rid not in regions:
            regions[rid] = {"country": row.get(a0, ""), "name": row.get(a1, ""), "code": row.get(f0, "")}
        acc = cells[(iy, ix, rid)]
        for i, v in enumerate(values):
            acc[i] += v
        pixel_region[(iy, ix, sub)][rid] += total
        r = region_ha[rid]
        for i, v in enumerate(values):
            r[i] += v

    region_ids = {rid: n for n, rid in enumerate(sorted(regions))}
    out_cells: dict[str, list] = {}
    for (iy, ix, rid), acc in cells.items():
        total = sum(acc)
        if total < MIN_CELL_HA:
            continue
        top = sorted(((v, i) for i, v in enumerate(acc) if v > 0), reverse=True)[:TOP_PER_CELL]
        entry = out_cells.setdefault(f"{iy},{ix}", [[-1] * 9, []])
        entry[1].append([region_ids[rid], round(total), [[i, round(v)] for v, i in top]])
    for (iy, ix, sub), by_region in pixel_region.items():
        entry = out_cells.get(f"{iy},{ix}")
        if entry:
            kept = {e[0] for e in entry[1]}
            best = max(((region_ids[r], ha) for r, ha in by_region.items() if region_ids[r] in kept),
                       key=lambda kv: kv[1], default=None)
            if best:
                entry[0][sub] = best[0]
    tonnes = _production(production_zip) if production_zip else {}
    out_regions = []
    for rid in sorted(regions):
        ha = region_ha[rid]
        entry = {**regions[rid], "ha": {crops[i]: round(v) for i, v in enumerate(ha) if v >= 1}}
        if rid in tonnes:
            entry["yield"] = {crops[i]: round(tonnes[rid][crops[i]] / v, 2) for i, v in enumerate(ha)
                              if v >= MIN_YIELD_HA and tonnes[rid].get(crops[i], 0) > 0}
        out_regions.append(entry)
    return {
        "_source": "MapSPAM 2020 v2r2 (IFPRI), harvested area, all technologies, 5 arc-minute grid; "
                   f"cells aggregated to {CELL} degree. doi:10.7910/DVN/SWPENT",
        "cell_deg": CELL, "crops": crops, "regions": out_regions, "cells": out_cells,
    }


if __name__ == "__main__":
    data = build(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    OUT.parent.mkdir(exist_ok=True)
    with gzip.open(OUT, "wt", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"), ensure_ascii=False)
    print(f"{len(data['cells'])} cells, {len(data['regions'])} regions, crops: {', '.join(data['crops'])}")
    print(f"-> {OUT} ({OUT.stat().st_size // 1024} KB)")
