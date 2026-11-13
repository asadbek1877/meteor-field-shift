"""Run from the repository root: python -m pytest tests -q

No test touches the network: NASA and the other providers are replaced by fakes.
"""
import math
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from backend import agro, climate, nasa_client, physics, providers, store, texts
from backend.main import app

START = date(1991, 1, 1)
END = date(2026, 11, 7)
REAL_SOIL, REAL_FORECAST = providers.soil, providers.forecast  # the client fixture replaces them


# ---------- physics ----------

def test_ra_matches_fao56_example_8():
    # FAO-56 example 8: 20 S, 3 September (day 246) -> Ra = 32.2 MJ/m2/day
    assert abs(physics.extraterrestrial_radiation(-20, 246) - 32.2) < 0.1
    assert physics.extraterrestrial_radiation(80, 355) == 0  # polar night


def test_penman_monteith_matches_fao56_example_18():
    # FAO-56 example 18: Uccle, 6 July -> ET0 = 3.9 mm/day
    ra = physics.extraterrestrial_radiation(50.8, 187)
    et0 = physics.et0_penman_monteith(21.5, 12.3, 16.9, 22.07, 2.078, ra, 100, ea=1.409)
    assert abs(et0 - 3.9) < 0.1


def test_statistics():
    assert physics.percentile([1, 2, 3, 4, 5], 50) == 3
    assert physics.percentile([0, 10], 10) == 1
    fit = physics.ols([1, 2, 3, 4, 5], [2, 4, 6, 8, 10])
    assert math.isclose(fit["slope"], 2) and math.isclose(physics.predict(fit, 10)[0], 20)
    assert physics.mann_kendall_p(list(range(20))) < 0.001
    assert physics.mann_kendall_p([1, 2] * 10) > 0.05


# ---------- synthetic weather ----------

def fake_data(lat=41.3, lon=69.2, warming=0.0):
    """A regular year repeated: hot dry summer, cool wetter winter, rain every 5th day."""
    n = (END - START).days + 1
    p = {name: [] for name in nasa_client.PARAMS}
    for i in range(n):
        d = START + timedelta(days=i)
        season = math.cos((d.timetuple().tm_yday - 196) * 2 * math.pi / 365)  # +1 in mid July
        t = 14 + 13 * season + warming * (d.year - 1991)
        p["T2M"].append(t)
        p["T2M_MAX"].append(t + 7)
        p["T2M_MIN"].append(t - 7)
        p["PRECTOTCORR"].append((6.0 - 5.0 * season) if i % 5 == 0 else 0.0)
        p["RH2M"].append(55 - 20 * season)
        p["WS2M"].append(2.0)
        p["ALLSKY_SFC_SW_DWN"].append(16 + 10 * season)
        p["GWETROOT"].append(0.5 - 0.1 * season)
    return {"lat": lat, "lon": lon, "elevation": 400.0, "resolution": "daily", "start": START.isoformat(),
            "fetched_at": f"test-{lat}-{lon}-{warming}", "sources": ["TEST"], "api_version": "test", "params": p}


def test_climate_detects_warming_and_projects():
    flat = climate.analyze(climate.prepare(fake_data()))
    warm = climate.analyze(climate.prepare(fake_data(warming=0.05)))
    assert abs(flat["shift"]["t_mean"]["delta"]) < 0.05
    assert math.isclose(warm["shift"]["t_mean"]["delta"], 1.0, abs_tol=0.02)
    assert warm["shift"]["t_mean"]["trend_significant"]
    proj = warm["shift"]["t_mean"]["projection"]
    assert proj["low"] <= proj["value"] <= proj["high"] and proj["value"] > warm["shift"]["t_mean"]["recent"]
    assert warm["shift"]["et0_mm"]["delta"] > 0
    assert flat["et0_method"]["penman_monteith_share"] == 1
    assert len(flat["annual"]) == 35 and flat["annual"][-1]["year"] == 2025


def test_recent_and_outlook():
    d = climate.prepare(fake_data())
    recent, look = climate.recent_conditions(d), climate.outlook(d)
    assert recent["as_of"] == END.isoformat() and recent["days_since_rain"] <= 4
    assert look["rain_within_7d_probability"] == 1 and look["days_to_rain"]["p50"] <= 4


# ---------- crops and rotations ----------

def test_kc_curve_and_season_dates():
    cotton, wheat = agro.CROPS["cotton"], agro.CROPS["winter_wheat"]
    assert agro.kc_at(0, cotton["stages"], cotton["kc"]) == 0.35
    assert agro.kc_at(100, cotton["stages"], cotton["kc"]) == 1.15
    assert agro.kc_at(179, cotton["stages"], cotton["kc"]) < 0.65
    sow = agro.sow_date(wheat, 2020, south=False)
    assert sow.year == 2019 and sow.month == 10  # sown in autumn, harvested next June
    assert agro.sow_date(cotton, 2020, south=True).year == 2019  # shifted half a year in the south


def test_water_balance_is_physical():
    d = climate.prepare(fake_data())
    cotton = agro.simulate(d, agro.CROPS["cotton"], 2020, awc=150)
    wheat = agro.simulate(d, agro.CROPS["winter_wheat"], 2020, awc=150)
    assert cotton["irrigation"] > wheat["irrigation"] > 0          # summer crop needs more than winter crop
    assert cotton["irrigation"] <= cotton["need"] + 150 * 1.2      # cannot apply more than demand plus one soil refill
    assert cotton["need"] - cotton["rain"] - 150 * 1.2 <= cotton["irrigation"]
    sandy = agro.simulate(d, agro.CROPS["cotton"], 2020, awc=100)
    assert sandy["events"] > cotton["events"]                      # light soil holds less, so more irrigations
    assert agro.simulate(d, agro.CROPS["winter_wheat"], 1991, awc=150) is None  # season starts before the record


def test_warming_raises_water_need():
    cool = agro.Field(climate.prepare(fake_data())).crops()
    warm = agro.Field(climate.prepare(fake_data(warming=0.08))).crops()
    need = lambda rows: next(c for c in rows if c["id"] == "cotton")["recent"]["water_need_mm"]
    assert need(warm) > need(cool)
    assert len(cool) == 6


def test_rotations_ranking_follows_priorities():
    field = agro.Field(climate.prepare(fake_data()), "medium", "furrow")
    water = field.rotations("cotton_mono", None, {"water": 100, "income": 0, "soil": 0, "risk": 0})
    soil = field.rotations("cotton_mono", None, {"water": 0, "income": 0, "soil": 100, "risk": 0})
    assert len(water["items"]) == 5 and water["current_id"] == "cotton_mono"
    assert water["best_id"] == "wheat_chickpea_sorghum"      # least water
    assert soil["best_id"] == "cotton_wheat_alfalfa"         # legumes, perennial, diversity
    mono = next(it for it in water["items"] if it["id"] == "cotton_mono")
    assert mono["is_current"] and mono["vs_current"] is None
    best = water["items"][0]
    assert best["vs_current"]["water_m3_ha"] > 0 and best["water_m3_ha"]["p10"] <= best["water_m3_ha"]["p90"]
    assert sum(it["wins"] for it in water["items"]) == water["years_replayed"] == 15
    drip = agro.Field(climate.prepare(fake_data()), "medium", "drip").rotations(None, None, None)
    by_id = lambda r, i: next(it for it in r["items"] if it["id"] == i)
    assert by_id(drip, "cotton_mono")["water_m3_ha"]["p50"] < mono["water_m3_ha"]["p50"]  # drip wastes less


def test_soil_index_and_custom_rotation():
    assert agro.soil_health([["cotton"]])["index"] < agro.soil_health([["cotton"], ["winter_wheat", "mung_bean"]])["index"]
    assert agro.parse_custom("cotton|winter_wheat+mung_bean") == [["cotton"], ["winter_wheat", "mung_bean"]]
    with pytest.raises(ValueError):
        agro.parse_custom("cotton|banana")
    assert agro.conflicts([["cotton"], ["winter_wheat", "mung_bean"]]) == []
    assert agro.conflicts([["chickpea", "sorghum"]])[0]["overlap_days"] > 0


def _advice_inputs():
    d = climate.prepare(fake_data())
    field = agro.Field(d)
    rot = field.rotations("cotton_mono", None, {"water": 100, "income": 0, "soil": 0, "risk": 0})
    return climate.analyze(d), field.crops(), rot


def test_advice_when_current_rotation_needs_no_water():
    clim, crops, rot = _advice_inputs()
    best = next(it for it in rot["items"] if it["id"] == rot["best_id"])
    best["vs_current"].update({"water_m3_ha": -500, "water_pct": None})  # current p50 water is 0
    for lang in ("en", "uz"):
        assert texts.advice(lang, clim, crops, rot, {})


def test_frost_advice_says_shorter_when_season_shrinks():
    clim, crops, rot = _advice_inputs()
    clim["frost"] = {"baseline": {"last_spring_frost": "04-01"}, "recent": {"last_spring_frost": "04-10"},
                     "frost_free_change_days": -7}
    frost = lambda lang: next(a["text"] for a in texts.advice(lang, clim, crops, rot, {})
                              if "frost-free" in a["text"] or "sovuqsiz" in a["text"])
    assert "7 days shorter" in frost("en") and "-7" not in frost("en")
    assert "7 kunga qisqargan" in frost("uz") and "-7" not in frost("uz")


# ---------- API ----------

@pytest.fixture
def client(monkeypatch, tmp_path):
    def down(*args, **kwargs):
        raise nasa_client.PowerError("timeout")

    def provider_down(*args, **kwargs):
        raise providers.ProviderDown("ConnectTimeout")

    monkeypatch.setattr(nasa_client, "fetch_daily", down)
    monkeypatch.setattr(nasa_client, "fetch_monthly", down)
    monkeypatch.setattr(store, "_memory", {"41.3_69.2": fake_data()})
    monkeypatch.setattr(providers, "CONFIG", tmp_path / "providers.json")
    monkeypatch.setattr(providers, "check", lambda p, force=False: {"status": "ok", "ms": 5, "message": None})
    monkeypatch.setattr(providers, "soil", provider_down)
    monkeypatch.setattr(providers, "forecast", provider_down)
    return TestClient(app)


def test_full_analysis_from_cache(client):
    body = client.get("/api/analyze?lat=41.3&lon=69.2&lang=uz").json()
    assert body["source"] == "cache" and body["coverage"]["rotations"] == "full"
    assert body["rotations"]["best_id"] and len(body["crops"]) == 6 and body["advice"]
    assert body["coverage"]["soil"] == "default" and body["soil"]["class"] == "medium"
    assert body["coverage"]["forecast"] == "climatology" and body["now"]["week_basis"]["source"] == "climatology"
    assert {w["provider"] for w in body["warnings"]} == {"soilgrids", "open_meteo"}
    assert len(body["map_layers"]) == 6
    chosen = client.get("/api/analyze?lat=41.3&lon=69.2&soil=light&irrigation=drip").json()
    assert chosen["coverage"]["soil"] == "chosen" and chosen["rotations"]["irrigation_efficiency"] == 0.9
    assert not any(w["provider"] == "soilgrids" for w in chosen["warnings"])


def test_soil_and_forecast_are_used_when_available(client, monkeypatch):
    monkeypatch.setattr(providers, "soil", lambda p, lat, lon: {"class": "heavy", "clay_pct": 40.0, "sand_pct": 20.0})
    monkeypatch.setattr(providers, "forecast", lambda p, lat, lon: {
        "source": "Open-Meteo", "days": [], "rain_7d_mm": 0.0, "et0_7d_mm": 20.0,
        "next_rain_date": None, "next_rain_mm": None, "horizon_days": 16})
    body = client.get("/api/analyze?lat=41.3&lon=69.2").json()
    assert body["soil"]["class"] == "heavy" and body["coverage"]["soil"] == "measured"
    assert body["coverage"]["forecast"] == "forecast" and body["now"]["week_basis"]["et0_7d_mm"] == 20.0
    assert not body["warnings"]


def test_degrades_step_by_step(client, monkeypatch):
    near = client.get("/api/analyze?lat=41.8&lon=69.2&lang=uz").json()
    assert near["source"] == "fallback" and 40 < near["fallback"]["distance_km"] < 70
    assert near["coverage"]["climate"] == "approx" and near["rotations"]

    far = client.get("/api/analyze?lat=-10&lon=-50")
    body = far.json()
    assert far.status_code == 200  # a failed provider must not break the request
    assert body["climate"] is None and body["rotations"] is None and body["coverage"]["climate"] == "skipped"
    assert body["coverage"]["map_layers"] == "available"
    assert any(w["severity"] == "critical" for w in body["warnings"])

    # daily data fails, monthly data arrives: analysis still runs, marked approximate
    monthly = fake_data(lat=-10.0, lon=-50.0)
    monthly["resolution"] = "monthly"
    monkeypatch.setattr(nasa_client, "fetch_monthly", lambda lat, lon: monthly)
    body = client.get("/api/analyze?lat=-10&lon=-50").json()
    assert body["source"] == "monthly" and body["coverage"]["climate"] == "approx" and body["rotations"]["items"]
    assert body["climate"]["shift"].get("hot_days") is None and body["now"]["recent"] is None


@pytest.mark.parametrize("body", [[1, 2], {"properties": {"layers": [{"name": "clay", "depths": [{}]}]},
                                          "daily": {"time": ["2026-01-01"], "precipitation_sum": 5}}])
def test_malformed_provider_response_does_not_break_analysis(client, monkeypatch, body):
    monkeypatch.setattr(providers, "soil", REAL_SOIL)
    monkeypatch.setattr(providers, "forecast", REAL_FORECAST)
    monkeypatch.setattr(providers, "_soil_cache", {})
    monkeypatch.setattr(providers, "_down_until", {})
    monkeypatch.setattr(providers, "_fetch", lambda p, lat, lon: body)
    res = client.get("/api/analyze?lat=41.3&lon=69.2")
    assert res.status_code == 200 and res.json()["rotations"]["items"]
    assert {w["provider"] for w in res.json()["warnings"]} == {"soilgrids", "open_meteo"}


def test_layer_provider_down_is_reported(client, monkeypatch):
    monkeypatch.setattr(providers, "check", lambda p, force=False: {"status": "down", "ms": None, "message": "Timeout"})
    body = client.get("/api/analyze?lat=41.3&lon=69.2").json()
    assert body["coverage"]["map_layers"] == "unavailable" and body["climate"] is not None
    assert any(w["provider"] == "nasa_gibs" for w in body["warnings"])


def test_custom_rotation_and_validation(client):
    body = client.get("/api/analyze?lat=41.3&lon=69.2&custom=chickpea%2Bsorghum").json()
    assert body["rotations"]["current_id"] == "custom"
    assert any(w["provider"] == "rotation" for w in body["warnings"])  # overlapping seasons are reported
    assert body["rotations"]["best_id"] != "custom"
    assert client.get("/api/analyze?lat=41.3&lon=69.2&custom=banana").status_code == 422
    assert client.get("/api/analyze?lat=91&lon=0").status_code == 422
    assert client.get("/api/analyze?lat=41.3&lon=69.2&w_water=0&w_income=0&w_soil=0&w_risk=0").status_code == 200
    assert len(client.get("/api/options").json()["crops"]) == 6


def test_provider_editing_needs_token_and_validates(client, monkeypatch):
    spec = {"id": "my_tiles", "name": "My tiles", "kind": "layers", "url_template": "https://example.org/{z}/{x}/{y}.png"}
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    assert client.post("/api/providers", json=spec).status_code == 403

    monkeypatch.setenv("ADMIN_TOKEN", "secret")
    assert client.post("/api/providers", json=spec, headers={"X-Admin-Token": "bad"}).status_code == 401
    ok = {"X-Admin-Token": "secret"}
    assert client.post("/api/providers", json=spec, headers=ok).status_code == 200
    assert client.post("/api/providers", json={**spec, "id": "bad_url", "url_template": "http://x/{z}/{x}/{y}"}, headers=ok).status_code == 422
    assert client.post("/api/providers", json={**spec, "id": "local", "url_template": "https://127.0.0.1/{z}/{x}/{y}"}, headers=ok).status_code == 422

    assert len(client.get("/api/layers").json()) == 7
    assert client.patch("/api/providers/my_tiles", json={"enabled": False}, headers=ok).json()["enabled"] is False
    assert len(client.get("/api/layers").json()) == 6
    assert client.patch("/api/providers/nasa_power", json={"enabled": False}, headers=ok).status_code == 200
    off = client.get("/api/analyze?lat=41.3&lon=69.2").json()
    assert off["source"] == "disabled" and off["climate"] is None
    assert client.delete("/api/providers/nasa_power", headers=ok).status_code == 422
    assert client.delete("/api/providers/my_tiles", headers=ok).status_code == 200


def test_gibs_layers_are_dated_except_grace():
    from backend import providers
    gibs = next(p for p in providers.BUILTIN if p["id"] == "nasa_gibs")
    ids = {layer["id"]: layer for layer in gibs["layers"]}
    assert "SMAP_L4_Analyzed_Root_Zone_Soil_Moisture" in ids
    assert ids["VIIRS_SNPP_CorrectedReflectance_TrueColor"]["url"].endswith(".jpg")
    assert not ids["GRACE_Tellus_Liquid_Water_Equivalent_Thickness_Mascon_CRI"]["dated"]
    for layer in gibs["layers"]:
        assert "/default/default/" in layer["url"]  # the site swaps the second "default" for a date
