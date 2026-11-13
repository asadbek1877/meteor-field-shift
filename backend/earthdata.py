"""NASA Earthdata access with a user token: find granules (CMR) and read single pixels from them.

Two ways to read one point without downloading whole files:
  OPeNDAP subset   opendap.earthdata.nasa.gov (Hyrax in the cloud) returns a tiny NetCDF-4 with just the
                   requested array cells (SMAP, IMERG, GLDAS, MODIS, VIIRS)
  COG pixel        LP DAAC cloud GeoTIFFs (HLS, ECOSTRESS): the token is exchanged for a signed S3 link,
                   GDAL then reads only the internal tile that holds the point

The token comes from the EARTHDATA_TOKEN environment variable (backend/.env, never committed).
"""
from __future__ import annotations

import io
import math
import os
from datetime import date, datetime

import httpx

CMR = "https://cmr.earthdata.nasa.gov/search/granules.umm_json"
TIMEOUT_S = 90


class EarthdataDown(Exception):
    pass


def token() -> str | None:
    return os.environ.get("EARTHDATA_TOKEN") or None


def _client() -> httpx.Client:
    tok = token()
    if not tok:
        raise EarthdataDown("EARTHDATA_TOKEN is not set")
    return httpx.Client(timeout=TIMEOUT_S, follow_redirects=True,
                        headers={"Authorization": f"Bearer {tok}", "User-Agent": "field-shift-app"})


# ---------- finding granules ----------

def granules(short_name: str, start: date, end: date, lat: float | None = None, lon: float | None = None,
             limit: int = 400, version: str | None = None) -> list[dict]:
    """Granules of a collection in a date range (optionally covering a point), oldest first.

    -> [{"id", "date", "time", "opendap", "files": [https urls]}]
    """
    params = {"short_name": short_name, "temporal": f"{start.isoformat()}T00:00:00Z,{end.isoformat()}T23:59:59Z",
              "page_size": min(limit, 2000), "sort_key": "start_date"}
    if lat is not None and lon is not None:
        params["point"] = f"{lon},{lat}"
    if version:
        params["version"] = version
    try:
        r = httpx.get(CMR, params=params, timeout=30)
        r.raise_for_status()
        items = r.json().get("items", [])
    except (httpx.HTTPError, ValueError) as exc:
        raise EarthdataDown(f"CMR: {type(exc).__name__}") from exc
    out = []
    for it in items:
        u = it["umm"]
        begin = (u.get("TemporalExtent", {}).get("RangeDateTime", {}) or {}).get("BeginningDateTime", "")
        urls = [x["URL"] for x in u.get("RelatedUrls", [])]
        out.append({
            "id": u["GranuleUR"], "date": begin[:10], "time": begin[11:19],
            "opendap": next((x for x in urls if "opendap.earthdata.nasa.gov" in x), None),
            "files": [x for x in urls if x.startswith("https://data.") and not x.endswith(".xml")],
        })
    return out


# ---------- OPeNDAP subset ----------

def dap(url: str, constraint: str) -> dict:
    """{variable path: numpy array} for a DAP4 constraint such as "/sm_rootzone[273][2578]"."""
    import h5py
    with _client() as c:
        for attempt in (1, 2):
            try:
                r = c.get(url + ".dap.nc4", params={"dap4.ce": constraint})
                r.raise_for_status()
                break
            except httpx.HTTPError as exc:
                if attempt == 2:
                    raise EarthdataDown(f"OPeNDAP: {type(exc).__name__}") from exc
    out = {}
    with h5py.File(io.BytesIO(r.content), "r") as f:
        f.visititems(lambda n, o: out.__setitem__(n, o[...]) if isinstance(o, h5py.Dataset) else None)
    return out


# ---------- cloud-optimized GeoTIFF pixel ----------

def cog_point(url: str, lat: float, lon: float) -> float | None:
    """Value of the pixel under the point, scaled; None for no-data."""
    import rasterio
    from rasterio.warp import transform
    os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
    os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "2")
    try:
        with _client() as c:
            r = c.get(url, follow_redirects=False)
        signed = r.headers.get("location") if r.status_code in (301, 302, 303, 307) else None
        if not signed:
            raise EarthdataDown(f"no signed link (HTTP {r.status_code})")
        with rasterio.open("/vsicurl/" + signed) as ds:
            xs, ys = transform("EPSG:4326", ds.crs, [lon], [lat])
            value = float(list(ds.sample([(xs[0], ys[0])]))[0][0])
            nodata, scale, offset = ds.nodata, (ds.scales or [1])[0] or 1, (ds.offsets or [0])[0] or 0
    except (httpx.HTTPError, OSError) as exc:      # rasterio errors derive from OSError / RasterioIOError
        raise EarthdataDown(f"COG: {type(exc).__name__}") from exc
    if nodata is not None and (value == nodata or (math.isnan(nodata) and math.isnan(value))):
        return None
    if math.isnan(value):
        return None
    return value * scale + offset


# ---------- grid positions ----------

def ease2_9km(lat: float, lon: float) -> tuple[int, int]:
    """Row and column in the global EASE-Grid 2.0, 9 km (SMAP L4: 1624 x 3856)."""
    a, e = 6378137.0, 0.0818191908426
    k0 = math.cos(math.radians(30))
    s = math.sin(math.radians(lat))
    q = (1 - e * e) * (s / (1 - e * e * s * s) - (1 / (2 * e)) * math.log((1 - e * s) / (1 + e * s)))
    x, y = a * k0 * math.radians(lon), a * q / (2 * k0)
    cell = 9008.055210146
    return int((7314540.830638334 - y) // cell), int((x + 17367530.445161499) // cell)


def modis_sin(lat: float, lon: float, pixels: int = 4800) -> tuple[str, int, int]:
    """MODIS sinusoidal tile name (h22v04) and row/column; 4800 pixels per tile for 250 m."""
    r_earth, tile = 6371007.181, 1111950.5197665
    x = r_earth * math.radians(lon) * math.cos(math.radians(lat))
    y = r_earth * math.radians(lat)
    h, v = int((x + 20015109.354) // tile), int((10007554.677 - y) // tile)
    cell = tile / pixels
    col = int(((x + 20015109.354) - h * tile) // cell)
    row = int(((10007554.677 - y) - v * tile) // cell)
    return f"h{h:02d}v{v:02d}", row, col


def imerg_index(lat: float, lon: float) -> tuple[int, int]:
    """(lon index, lat index) in the 0.1 degree IMERG grid (3600 x 1800, from -179.95 / -89.95)."""
    return min(3599, max(0, round((lon + 179.95) / 0.1))), min(1799, max(0, round((lat + 89.95) / 0.1)))


def gldas_index(lat: float, lon: float) -> tuple[int, int]:
    """(lat index, lon index) in the 0.25 degree GLDAS grid (600 x 1440, from -59.875 / -179.875)."""
    return min(599, max(0, round((lat + 59.875) / 0.25))), min(1439, max(0, round((lon + 179.875) / 0.25)))


def days_in_month(d: date) -> int:
    nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return (nxt - date(d.year, d.month, 1)).days


def parse_day(text: str) -> date:
    return datetime.strptime(text[:10], "%Y-%m-%d").date()


