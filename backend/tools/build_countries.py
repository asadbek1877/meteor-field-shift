"""Builds backend/data/countries.json: country borders for offline "which country is this point in".

Source: Natural Earth 1:50m admin-0 countries (public domain), v5.1.2
  https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/ne_50m_admin_0_countries.geojson
Coordinates are rounded to 0.01 degree (about 1 km), which is enough to pick a country.
Run from the repository root:
  python -m backend.tools.build_countries ne_50m_admin_0_countries.geojson
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "countries.json"


def _ring(ring):
    out = []
    for lon, lat, *_ in ring:
        p = [round(lon, 2), round(lat, 2)]
        if not out or out[-1] != p:
            out.append(p)
    return out if len(out) >= 4 else None


def build(src: str) -> list:
    features = json.loads(Path(src).read_text(encoding="utf-8"))["features"]
    out = []
    for f in features:
        iso = f["properties"].get("ISO_A2_EH") or f["properties"].get("ISO_A2")
        if not iso or iso == "-99":
            continue
        g = f["geometry"]
        polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        polys = [[r for r in map(_ring, poly) if r] for poly in polys]
        polys = [p for p in polys if p]
        lons = [c[0] for p in polys for c in p[0]]
        lats = [c[1] for p in polys for c in p[0]]
        out.append({"iso": iso, "name": f["properties"]["NAME"],
                    "bbox": [min(lats), min(lons), max(lats), max(lons)], "polygons": polys})
    return out


if __name__ == "__main__":
    data = build(sys.argv[1])
    OUT.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    print(f"{len(data)} countries -> {OUT} ({OUT.stat().st_size // 1024} KB)")
