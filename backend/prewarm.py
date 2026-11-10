"""Download real NASA data for the preset locations into backend/cache/.

Run from the repository root, then commit the .json.gz files:
    python -m backend.prewarm
"""
from . import nasa_client, store
from .main import PRESETS

if __name__ == "__main__":
    for p in PRESETS:
        try:
            store.put(nasa_client.fetch_daily(p["lat"], p["lon"]))
            print(f"ok    {p['id']}")
        except nasa_client.PowerError as exc:
            print(f"FAIL  {p['id']}: {exc}")
