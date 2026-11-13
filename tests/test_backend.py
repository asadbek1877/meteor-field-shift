"""Run from the repository root: python -m pytest tests -q

No test touches the network: NASA and the other providers are replaced by fakes.
"""
import math
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from backend import agro, climate, geo, landcover, nasa_client, physics, providers, regional, store, suitability, texts
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
    assert len(cool) == len(agro.CROPS)


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
    assert agro.conflicts([["chickpea", "sorghum"]]) == []  # sorghum is sown after the chickpea harvest
    assert agro.conflicts([["cotton", "winter_wheat"]])[0]["overlap_days"] > 0  # wheat then runs into next cotton


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

    def geo_down(*args, **kwargs):
        raise geo.GeoDown("Nominatim: ConnectTimeout")

    monkeypatch.setattr(nasa_client, "fetch_daily", down)
    monkeypatch.setattr(nasa_client, "fetch_monthly", down)
    monkeypatch.setattr(store, "_memory", {"41.3_69.2": fake_data()})
    monkeypatch.setattr(providers, "CONFIG", tmp_path / "providers.json")
    monkeypatch.setattr(providers, "check", lambda p, force=False: {"status": "ok", "ms": 5, "message": None})
    monkeypatch.setattr(providers, "soil", provider_down)
    monkeypatch.setattr(providers, "forecast", provider_down)
    monkeypatch.setattr(geo, "land_cover", geo_down)
    monkeypatch.setattr(geo, "elevation", lambda lat, lon: None)

    def sat_down(*args, **kwargs):
        raise landcover.LandCoverDown("land cover: ConnectTimeout")
    monkeypatch.setattr(landcover, "sample", sat_down)
    from backend import terrain as terrain_mod

    def terrain_down(*args, **kwargs):
        raise terrain_mod.TerrainDown("SRTM: ConnectTimeout")
    monkeypatch.setattr(terrain_mod, "sample", terrain_down)
    from backend import water as water_mod

    def weather_down(*args, **kwargs):
        raise water_mod.WeatherDown("Open-Meteo: ConnectTimeout")
    monkeypatch.setattr(water_mod, "fetch", weather_down)
    monkeypatch.setattr(water_mod, "fetch_ensemble", lambda lat, lon: [])
    monkeypatch.setattr(providers, "SOIL_CACHE_FILE", tmp_path / "soil.json")
    monkeypatch.setattr(providers, "_soil_disk_loaded", True)
    return TestClient(app)


def test_full_analysis_from_cache(client):
    body = client.get("/api/analyze?lat=41.3&lon=69.2&lang=uz").json()
    assert body["source"] == "cache" and body["coverage"]["rotations"] == "full"
    assert body["rotations"]["best_id"] and body["crops"] and body["advice"]
    assert body["region"]["country"]["iso"] == "UZ"  # OSM is down: the offline borders still find the country
    assert body["coverage"]["soil"] == "default" and body["soil"]["class"] == "medium"
    assert body["coverage"]["forecast"] == "climatology" and body["now"]["week_basis"]["source"] == "climatology"
    assert {w["provider"] for w in body["warnings"]} == {"soilgrids", "open_meteo"}
    assert len(body["map_layers"]) == len(providers.BUILTIN[1]["layers"])
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
    monthly["params"] = {k: v[182:] + v[:182] for k, v in monthly["params"].items()}  # southern seasons
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
    body = client.get("/api/analyze?lat=41.3&lon=69.2&custom=cotton%2Bwinter_wheat").json()
    assert body["rotations"]["current_id"] == "custom"
    assert any(w["provider"] == "rotation" for w in body["warnings"])  # overlapping seasons are reported
    assert body["rotations"]["best_id"] != "custom"
    assert client.get("/api/analyze?lat=41.3&lon=69.2&custom=banana").status_code == 422
    assert client.get("/api/analyze?lat=91&lon=0").status_code == 422
    assert client.get("/api/analyze?lat=41.3&lon=69.2&w_water=0&w_income=0&w_soil=0&w_risk=0").status_code == 200
    assert len(client.get("/api/options").json()["crops"]) == len(agro.CROPS)


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

    assert len(client.get("/api/layers").json()) == len(providers.BUILTIN[1]["layers"]) + 1
    assert client.patch("/api/providers/my_tiles", json={"enabled": False}, headers=ok).json()["enabled"] is False
    assert len(client.get("/api/layers").json()) == len(providers.BUILTIN[1]["layers"])
    assert client.patch("/api/providers/nasa_power", json={"enabled": False}, headers=ok).status_code == 200
    off = client.get("/api/analyze?lat=41.3&lon=69.2").json()
    assert off["source"] == "disabled" and off["climate"] is None
    assert client.delete("/api/providers/nasa_power", headers=ok).status_code == 422
    assert client.delete("/api/providers/my_tiles", headers=ok).status_code == 200


# ---------- can crops grow here? ----------

SQUARE = {"type": "Polygon", "coordinates": [[[69.19, 41.29], [69.21, 41.29], [69.21, 41.31], [69.19, 41.31], [69.19, 41.29]]]}


def test_point_in_area_and_distance_to_road():
    assert geo.where(SQUARE, 41.30, 69.20) == (True, 0.0)
    inside, dist = geo.where(SQUARE, 41.40, 69.20)  # 10 km north of the square
    assert inside is False and 9_000 < dist < 11_000
    road = {"type": "LineString", "coordinates": [[69.20, 41.30], [69.21, 41.30]]}
    inside, dist = geo.where(road, 41.30005, 69.205)  # about 5.5 m north of the road
    assert inside is None and 4 < dist < 7


@pytest.mark.parametrize("cover, status, code", [
    ({"kind": "building", "osm": "building=yes", "name": None, "found": True}, "unsuitable", "building"),
    ({"kind": "road", "osm": "highway=primary", "name": "Amir Temur", "found": True}, "unsuitable", "road"),
    ({"kind": "water", "osm": "natural=water", "name": "Lake", "found": True}, "unsuitable", "water"),
    ({"kind": "farmland", "osm": "landuse=farmland", "name": None, "found": True}, "ok", "farmland"),
    ({"kind": None, "osm": None, "name": None, "found": True}, "ok", None),
])
def test_land_cover_decides(cover, status, code):
    s = suitability.judge(cover, None, False)
    assert s["status"] == status
    assert (s["reasons"][0]["code"] if s["reasons"] else None) == code


def test_open_sea_and_climate_limits():
    sea = suitability.judge({"kind": None, "found": False}, None, no_soil=True)
    assert sea["status"] == "unsuitable" and sea["reasons"][0]["code"] == "sea"
    facts = suitability.climate_facts(climate.prepare(fake_data()))
    assert facts["growing_months"] >= 6 and facts["warmest_month"] == 7
    assert suitability.judge(None, facts, False)["status"] == "ok"
    cold = {**facts, "growing_months": 0, "warmest_t_c": 4.0}
    assert suitability.judge(None, cold, False)["reasons"][0]["code"] == "too_cold"
    desert = {**facts, "aridity": 0.02}
    assert suitability.judge(None, desert, False)["status"] == "limited"
    for lang in texts.LANGS:  # every reason has a text in every language
        for code in ["building", "road", "transport", "urban", "park", "water", "sea", "no_soil", "glacier",
                     "rock", "sand", "wetland", "forest", "too_cold", "short_season", "hyper_arid", "extreme_heat", "farmland"]:
            assert code in texts.SUIT[lang]
        assert texts.suitability(lang, suitability.judge(None, cold, False))["headline"] == texts.SUIT[lang]["head_unsuitable"]


def test_building_skips_crop_advice_but_keeps_climate(client, monkeypatch):
    monkeypatch.setattr(geo, "land_cover", lambda lat, lon, lang: {
        "kind": "building", "osm": "building=yes", "name": "School 5", "place": "Tashkent", "country_code": "uz", "found": True})
    body = client.get("/api/analyze?lat=41.3&lon=69.2&lang=uz").json()
    s = body["suitability"]
    assert s["status"] == "unsuitable" and s["headline"] == "Bu yerda ekin ekib bo'lmaydi"
    assert "School 5" in s["items"][0]["title"] and s["todo"] and s["facts"]
    assert body["rotations"] is None and body["crops"] is None
    assert body["climate"] is not None and all(a["group"] == "climate" for a in body["advice"])


def test_land_cover_down_still_analyses(client):
    body = client.get("/api/analyze?lat=41.3&lon=69.2").json()
    assert body["suitability"]["status"] == "ok" and body["suitability"]["note"]
    assert body["rotations"]["best_id"]


def test_place_search(client, monkeypatch):
    monkeypatch.setattr(geo, "search", lambda q, lang, limit: [{"name": "Uzbekistan", "lat": 41.3, "lon": 63.9,
                                                                 "bbox": [37.2, 56.0, 45.6, 73.2], "outline": None}])
    assert client.get("/api/places?q=Uzbekistan").json()["results"][0]["bbox"][0] == 37.2

    def down(*a, **k):
        raise geo.GeoDown("x")
    monkeypatch.setattr(geo, "search", down)
    assert client.get("/api/places?q=Uzbekistan").status_code == 502


def test_nearest_object_counts_only_when_the_point_is_on_it(monkeypatch):
    house = {"type": "Polygon", "coordinates": [[[69.2000, 41.3000], [69.2001, 41.3000], [69.2001, 41.3001], [69.2000, 41.3001], [69.2000, 41.3000]]]}
    town = {"city": "Tashkent", "neighbourhood": "Chilanzar", "country_code": "uz"}
    village = {"village": "Qishloq", "country_code": "uz"}

    def answer(address):
        monkeypatch.setattr(geo, "_cover_cache", {})
        monkeypatch.setattr(geo, "_nominatim", lambda path, params: {
            "category": "building", "type": "yes", "geojson": house, "address": address, "display_name": "x"})

    answer(town)
    assert geo.land_cover(41.30005, 69.20005)["kind"] == "building"   # inside the house
    assert geo.land_cover(41.30014, 69.20005)["kind"] == "building"   # 4 m off its wall
    assert geo.land_cover(41.30040, 69.20005)["kind"] == "urban"      # 33 m away, in a town
    answer(village)
    assert geo.land_cover(41.30040, 69.20005)["kind"] is None         # 33 m away, village fields
    assert geo.land_cover(41.30200, 69.20005)["kind"] is None


# ---------- regional crop plan ----------

def test_country_profile_and_income_come_from_faostat():
    uz = regional.data()["countries"]["UZ"]
    assert uz["top"][0]["name"] == "Wheat" and uz["cropland_ha"] > 1_000_000
    money = regional.economics("UZ")
    assert money["cotton"]["source"] == "country" and 500 < money["cotton"]["usd_ha"] < 5000
    assert regional.economics(None)["maize"]["source"] == "world"
    assert regional.economics("UZ")["alfalfa"]["source"] == "default"  # FAOSTAT has no alfalfa


def test_rotations_follow_the_country(monkeypatch):
    monkeypatch.setattr(regional, "local_cell", lambda lat, lon: None)  # no MapSPAM cell: country mix
    d = climate.prepare(fake_data())
    uz, us = regional.plan(d, "UZ", "medium", "furrow"), regional.plan(d, "US", "medium", "furrow")
    crops_of = lambda p: {c for r in p["candidates"] for slot in r["years"] for c in slot}  # noqa: E731
    assert "cotton" in crops_of(uz) and "soybean" in crops_of(us)
    assert uz["profile"]["country"]["name"] == "Uzbekistan" and us["default_current"] != uz["default_current"]
    for p in (uz, us):  # every generated rotation is feasible
        assert p["candidates"] and all(not agro.conflicts(r["years"], False, p["field"].lib) for r in p["candidates"])
    rot = uz["field"].rotations(None, None, None, uz["candidates"], uz["default_current"])
    assert rot["current_id"] == uz["default_current"] and rot["best_id"]
    region = texts.region("uz", uz["profile"])
    assert region["title"] == "Hudud: Uzbekistan — nima ekiladi" and region["top"][0]["name"] == "Kuzgi bug'doy"


def test_cold_point_drops_warm_crops():
    data = fake_data()  # the whole record 12 C colder
    data["params"] = {k: ([v - 12 for v in vals] if k.startswith("T2M") else vals) for k, vals in data["params"].items()}
    data["fetched_at"] = "cold"
    p = regional.plan(climate.prepare(data), "US", "medium", "furrow")
    out = {x["id"] for x in p["profile"]["not_here"]}
    assert "cotton" in out and "cotton" not in p["profile"]["grown_here"]


def test_sowing_is_computed_for_the_point():
    d = climate.prepare(fake_data())
    maize = agro.localize(d, agro.CROPS["maize"])
    assert maize["local_sow"] and 60 < maize["sow_doy"] < 180
    south = fake_data(lat=-30.0)  # the same climate with the seasons moved by half a year
    south["params"] = {k: v[182:] + v[:182] for k, v in south["params"].items()}
    south["fetched_at"] = "south"
    sow_s = agro.sow_date(agro.localize(climate.prepare(south), agro.CROPS["maize"]), 2001, True)
    sow_n = agro.sow_date(maize, 2001, False)
    gap = (sow_s.timetuple().tm_yday - sow_n.timetuple().tm_yday) % 365
    assert abs(gap - 182) <= 15  # spring comes in October, not in April


def test_offline_country_and_second_crop_placement():
    assert geo.country_at(41.3, 69.2) == "UZ" and geo.country_at(42.0, -93.5) == "US" and geo.country_at(35.0, -40.0) is None
    wheat, mung = agro.placed(["winter_wheat", "mung_bean"], agro.CROPS, False)
    harvest = agro.sow_date(wheat, 2001, False) + agro.timedelta(days=sum(wheat["stages"]))
    assert agro.sow_date(mung, 2001, False) == harvest + agro.timedelta(days=agro.SECOND_CROP_GAP_DAYS)


def test_local_crop_mix_comes_from_the_province():
    tashkent, khorezm, iowa = regional.local_cell(41.3, 69.2), regional.local_cell(41.45, 60.8), regional.local_cell(42.0, -93.5)
    assert tashkent["country"] == "Uzbekistan"  # the cell crosses into Kazakhstan, the pixel does not
    assert khorezm["region"] == "Khorezm" and khorezm["top"][0][0] == "cott"
    assert {c for c, _ in iowa["top"][:2]} == {"maiz", "soyb"}
    d = climate.prepare(fake_data(lat=42.0, lon=-93.5))
    p = regional.plan(d, "US", "medium", "furrow")
    assert p["profile"]["local"]["region"] == "Iowa" and {"maize", "soybean"} <= set(p["profile"]["grown_here"][:2])
    region = texts.region("uz", p["profile"])
    assert region["title"].startswith("Iowa") and "MapSPAM" in region["source_text"]
    assert regional.local_cell(35.0, -40.0) is None  # open sea


# ---------- soil water forecast ----------

from backend import water  # noqa: E402

TODAY = date(2026, 7, 1)
LOAM = agro.soil_water("medium")


def _weather(n_past, n_future, et0=6.0, rain=None, sun=25.0):
    days = []
    for k in range(-n_past, n_future):
        d = TODAY + timedelta(days=k)
        days.append({"date": d.isoformat(), "rain_mm": (rain or {}).get(k, 0.0), "rain_prob": 10, "et0_mm": et0,
                     "sun_mj": sun, "tmax": 36.0, "tmin": 22.0, "soil_t_max": 52.0})
    return {"days": days, "timezone": "UTC"}


def _plan(monkeypatch, weather, members=(), crop="cotton", sow=date(2026, 4, 15), last=3, area=2.5):
    monkeypatch.setattr(water, "fetch", lambda lat, lon, past: weather)
    monkeypatch.setattr(water, "fetch_ensemble", lambda lat, lon: list(members))
    last_date = TODAY - timedelta(days=last) if last is not None else None
    return water.plan(41.3, 69.2, agro.CROPS[crop], LOAM, 0.6, area, sow, last_date, TODAY)


def test_soil_dries_faster_under_more_sun_and_heat(monkeypatch):
    hot = _plan(monkeypatch, _weather(3, 16, et0=7.0))
    mild = _plan(monkeypatch, _weather(3, 16, et0=3.5))
    assert hot["dry_on"]["expected"] < (mild["dry_on"]["expected"] or "9999")  # more evaporation, earlier dry
    i = hot["irrigation"]
    assert abs(i["m3_field"] - i["m3_ha"] * 2.5) <= 1.3 and abs(i["litres_field"] - i["m3_field"] * 1000) <= 100
    assert abs(i["gross_mm"] - i["net_mm"] / 0.6) < 0.2 and hot["start_from"] == "last_irrigation"
    assert hot["forecast_irrigation"]["times"] >= 1 and hot["method"] == "scenarios"


def test_rain_delays_drying_and_season_is_respected(monkeypatch):
    dry = _plan(monkeypatch, _weather(2, 16), last=2, area=1)
    wet = _plan(monkeypatch, _weather(2, 16, rain={k: 25.0 for k in range(0, 16, 3)}), last=2, area=1)
    assert dry["dry_on"]["expected"]
    assert wet["dry_on"]["expected"] is None or wet["dry_on"]["expected"] > dry["dry_on"]["expected"]
    late = _plan(monkeypatch, _weather(2, 16), sow=date(2026, 9, 1), last=None)  # not sown yet
    assert not late["crop"]["in_field_today"] and late["dry_on"]["expected"] is None and late["irrigation"] is None


def test_ensemble_gives_a_date_range_and_a_probability(monkeypatch):
    base = _weather(3, 16, et0=6.0)
    future = [d["date"] for d in base["days"] if d["date"] >= TODAY.isoformat()]
    dry_member = {t: (0.0, 6.5) for t in future}
    wet_member = {t: (12.0, 4.0) for t in future}                  # rain every day: never dry
    r = _plan(monkeypatch, base, members=[dry_member] * 9 + [wet_member] * 3)
    assert r["method"] == "ensemble" and r["members"] == 12
    assert r["dry_on"]["earliest"] and r["dry_on"]["expected"] and r["dry_on"]["latest"] is None  # 3 of 12 stay moist
    assert r["dry_probability"]["d16"] == 0.75 and r["forecast_rain_range_mm"][1] > 100
    few = _plan(monkeypatch, base, members=[dry_member] * 3)       # too few members: fixed scenarios
    assert few["method"] == "scenarios"


def test_sun_dries_the_surface_first_and_wet_soil_evaporates_more(monkeypatch):
    # young crop, open canopy: after a soaking the surface loses water fast, then evaporation stops
    r = _plan(monkeypatch, _weather(0, 16, et0=7.0), sow=TODAY - timedelta(days=10), last=0)
    days = r["days"]
    assert days[0]["evap_mm"] > 5 and days[-1]["evap_mm"] < 0.5        # wet surface vs dry crust
    assert days[0]["evap_mm"] > days[0]["transp_mm"]                   # seedlings: the sun takes more than the crop
    assert r["surface_dry_on"]["expected"] and r["surface_dry_on"]["expected"] <= days[6]["date"]
    assert days[0]["surface_pct"] > days[5]["surface_pct"]
    # closed canopy in mid-season: the crop takes almost everything
    mid = _plan(monkeypatch, _weather(0, 16, et0=7.0), sow=TODAY - timedelta(days=100), last=0)
    assert mid["days"][0]["transp_mm"] > 5 * mid["days"][0]["evap_mm"]


def test_start_of_the_balance(monkeypatch):
    w = _weather(60, 16, et0=5.0)
    assert _plan(monkeypatch, w, last=5)["start_from"] == "last_irrigation"
    sown = _plan(monkeypatch, w, sow=TODAY - timedelta(days=30), last=None)
    assert sown["start_from"] == "sowing" and sown["days_without_irrigation"] == 30
    old = _plan(monkeypatch, w, last=None)                            # sown 77 days ago, nothing known
    assert old["start_from"] == "history" and old["already_dry"]      # 60 dry hot days without irrigation


# ---------- accuracy: elevation, soil texture, province yield ----------

def test_temperature_is_corrected_to_the_field_elevation():
    assert climate.elevation_correction(800, 820) == (0.0, 0.0, 0.0)              # under 100 m: no change
    mean_c, max_c, min_c = climate.elevation_correction(786, 332)                 # field 454 m below the cell
    assert 2.9 < max_c < 3.0 and 2.0 < min_c < 2.1 and min_c < mean_c < max_c     # nights corrected less
    assert climate.elevation_correction(500, None) == (0.0, 0.0, 0.0)
    data = fake_data()
    grid, valley = climate.prepare(data), climate.prepare(data, point_elevation=0.0)  # cell is at 400 m
    assert abs((valley.tmax[200] - grid.tmax[200]) - 2.6) < 0.01 and valley.elevation == 0.0
    assert sum(valley.et0[:365]) > sum(grid.et0[:365])                            # warmer -> more evaporation


def test_soil_water_from_measured_texture():
    fc, wp = physics.saxton_rawls(40, 20, 2.5)        # loam: Saxton & Rawls (2006) table gives 28 % and 14 %
    assert abs(fc - 0.28) < 0.01 and abs(wp - 0.14) < 0.01
    by_class = agro.soil_water("medium")
    assert by_class["source"] == "class" and by_class["awc_mm_per_m"] == 150
    sandy = agro.soil_water("light", {"clay_pct": 6, "sand_pct": 85, "organic_carbon_g_kg": 4})
    silty = agro.soil_water("medium", {"clay_pct": 15, "sand_pct": 20, "organic_carbon_g_kg": 12})
    assert sandy["source"] == silty["source"] == "texture" and sandy["awc_mm_per_m"] < 90 < 150 < silty["awc_mm_per_m"]
    d = climate.prepare(fake_data())
    low = agro.Field(d, "medium", awc=60).run("cotton", 2020)
    high = agro.Field(d, "medium", awc=190).run("cotton", 2020)
    assert low["events"] > high["events"]             # a soil that holds less is irrigated more often


def test_province_yield_replaces_the_national_average():
    national = regional.economics("IN")["winter_wheat"]
    punjab = regional.economics("IN", regional.local_cell(30.6, 75.2)["yield"])["winter_wheat"]
    assert national["source"] == "country" and punjab["source"] == "region"
    assert punjab["yield_t_ha"] > national["yield_t_ha"] and punjab["price_usd_t"] == national["price_usd_t"]
    absurd = regional.economics("IN", {"whea": 80.0})["winter_wheat"]      # 20x the country: not trusted
    assert absurd["source"] == "country"



# ---------- satellite land cover: water, buildings, ice ----------

def _sat(center, near=None, around=None):
    return {"center": center, "near": near or {center: 8}, "around": around or {center: 8}, "source": "test"}


ROAD = {"kind": None, "osm": "highway=tertiary", "name": "D010", "place": "Bostanlik", "found": True}


@pytest.mark.parametrize("sat, cover, status, code", [
    # the bugs: a reservoir and a hospital yard came back "fine" because OSM only knew a nearby road
    (_sat("water"), ROAD, "unsuitable", "deep_water"),
    (_sat("water", {"water": 3, "crops": 5}, {"crops": 8}), ROAD, "unsuitable", "water"),          # on the shore
    (_sat("built"), {"kind": None, "osm": "amenity=hospital", "name": "City Clinic", "found": True}, "unsuitable", "built"),
    (_sat("snow_ice"), None, "unsuitable", "glacier"),
    (_sat("nodata"), {"kind": None, "found": False}, "unsuitable", "sea"),
    (_sat("flooded_vegetation"), None, "limited", "wetland"),
    (_sat("bare"), None, "limited", "bare"),
    (_sat("crops"), ROAD, "ok", "crops_seen"),
])
def test_satellite_decides_water_buildings_ice(sat, cover, status, code):
    s = suitability.judge(cover, None, False, sat)
    assert s["status"] == status and s["reasons"][0]["code"] == code


def test_satellite_names_and_edges():
    hospital = suitability.judge({"kind": None, "osm": "amenity=hospital", "name": "City Clinic", "found": True}, None, False, _sat("built"))
    assert hospital["reasons"][0]["name"] == "City Clinic"
    lake = suitability.judge(ROAD, None, False, _sat("water"))
    assert lake["reasons"][0]["name"] is None                  # the road's name is not the lake's name
    edge = suitability.judge(None, None, False, _sat("crops", {"crops": 4, "water": 4}, {"crops": 8}))
    assert edge["status"] == "ok" and any(r["code"] == "edge_water" for r in edge["reasons"])
    # an OSM "town address" guess does not overrule a field the satellite sees
    village = suitability.judge({"kind": "urban", "osm": "building=yes", "name": None, "found": True}, None, False, _sat("crops"))
    assert village["status"] == "ok"
    for lang in texts.LANGS:
        out = texts.suitability(lang, edge)
        assert all(item["title"] and item["detail"] for item in out["items"])


def test_building_from_satellite_skips_crop_advice(client, monkeypatch):
    monkeypatch.setattr(landcover, "sample", lambda lat, lon: _sat("built"))
    body = client.get("/api/analyze?lat=41.3&lon=69.2&lang=uz").json()
    assert body["suitability"]["status"] == "unsuitable" and body["rotations"] is None
    assert body["suitability"]["items"][0]["title"].startswith("Bu qurilgan hudud")



# ---------- this week's advice for the region's crops ----------

def _week(tmax=30.0, tmin=15.0, rain=0.0, et0=6.0, ground=35.0, seed=20.0, n=7):
    return {"days": [{"date": (TODAY + timedelta(days=k)).isoformat(), "rain_mm": rain, "rain_prob": 10, "et0_mm": et0,
                      "sun_mj": 25.0, "tmax": tmax, "tmin": tmin, "soil_t_max": ground, "soil6_mean": seed} for k in range(n)]}


def test_weekly_irrigation_need_and_alerts():
    from backend import weekly
    cotton = agro.CROPS["cotton"]
    south = False
    sow_day = agro.sow_date(cotton, TODAY.year, south)
    today_mid = sow_day + timedelta(days=80)          # flowering: heat-sensitive window 60-130
    w = _week(tmax=41.0)
    w["days"] = [{**d, "date": (today_mid + timedelta(days=k)).isoformat()} for k, d in enumerate(w["days"])]
    r = weekly.crop_week(cotton, today_mid, w["days"], [], 0.6, south)
    assert r["status"] == "in_field" and r["stage"] == "mid" and r["action"] == "irrigate"
    assert abs(r["water"]["use_mm"] - 7 * 6.0 * cotton["kc"][1]) < 0.5        # Kc mid x ET0 x 7 days
    assert r["water"]["m3_ha"] == round(r["water"]["net_mm"] * 10 / 0.6)
    assert r["alerts"][0]["code"] == "heat" and r["alerts"][0]["level"] == "critical"
    wet = [{**d, "rain_mm": 8.0} for d in w["days"]]
    assert weekly.crop_week(cotton, today_mid, wet, [], 0.6, south)["action"] == "no_irrigation"


def test_weekly_sowing_waits_for_warm_soil_and_no_frost():
    from backend import weekly
    cotton = agro.CROPS["cotton"]
    sow_day = agro.sow_date(cotton, TODAY.year, False)
    before = sow_day - timedelta(days=5)
    days = [{**d, "date": (before + timedelta(days=k)).isoformat()} for k, d in enumerate(_week(seed=9.0)["days"])]
    assert weekly.crop_week(cotton, before, days, [], 0.6, False)["action"] == "wait_cold"   # soil 9 C < 14 C
    warm = [{**d, "soil6_mean": 18.0} for d in days]
    assert weekly.crop_week(cotton, before, warm, [], 0.6, False)["action"] == "sow"
    frosty = [{**d, "soil6_mean": 18.0, "tmin": -2.0} for d in days]
    assert weekly.crop_week(cotton, before, frosty, [], 0.6, False)["action"] == "wait_frost"


def test_weekly_plan_follows_the_region_and_uses_the_ensemble():
    from backend import weekly
    d = climate.prepare(fake_data(lat=42.0, lon=-93.5))
    plan = regional.plan(d, "US", "medium", "furrow")
    week = _week()
    members = [{x["date"]: (r, 6.0) for x in week["days"]} for r in [0.0] * 5 + [10.0] * 5]
    w = weekly.analyze(plan, week, members, 0.75, TODAY, 42.0)
    assert {c["id"] for c in w["crops"]} >= {"maize", "soybean"} and w["method"] == "ensemble"
    s = w["summary"]
    assert s["rain_range_mm"][0] == 0.0 and s["rain_range_mm"][1] == 70.0 and s["rain_5mm_probability"] == 0.5



# ---------- NASA SRTM terrain ----------

def test_slope_from_srtm_window():
    from backend import terrain
    assert terrain.slope_aspect([100.0] * 9)[0] == 0
    # rises 3 m per 60 m to the east: 5 % slope, facing west (270 degrees)
    slope, aspect = terrain.slope_aspect([100, 103, 106, 100, 103, 106, 100, 103, 106])
    assert abs(slope - 5.0) < 0.01 and abs(aspect - 270) < 1
    assert terrain.slope_class(1.5) == "flat" and terrain.slope_class(8) == "moderate" and terrain.slope_class(35) == "steep"


def test_steep_slope_is_not_a_field():
    steep = suitability.judge(None, None, False, _sat("rangeland"), {"class": "steep", "slope_pct": 38.0, "slope_deg": 20.8})
    assert steep["status"] == "unsuitable" and steep["reasons"][0]["code"] == "slope_steep"
    moderate = suitability.judge(None, None, False, _sat("crops"), {"class": "moderate", "slope_pct": 8.0, "slope_deg": 4.6})
    assert moderate["status"] == "ok" and any(r["code"] == "slope_moderate" for r in moderate["reasons"])
    for lang in texts.LANGS:
        assert "38" in texts.suitability(lang, steep)["items"][0]["detail"]


# ---------- NASA observations in the water balance ----------

def test_observed_rain_and_smap_start(monkeypatch):
    w = _weather(60, 16, et0=5.0)
    rainy = {"status": "ok", "series": [{"date": (TODAY - timedelta(days=k)).isoformat(), "rain_mm": 30.0}
                                        for k in range(1, 4)]}
    dry = _plan(monkeypatch, w, last=None)                                   # 60 dry days in the model
    monkeypatch.setattr(water, "fetch", lambda lat, lon, past: _weather(60, 16, et0=5.0))
    wet = water.plan(41.3, 69.2, agro.CROPS["cotton"], LOAM, 0.6, 1, date(2026, 4, 15), None, TODAY,
                     {"imerg": rainy})
    assert wet["observed_rain_days"] == 3 and wet["days"][-17]["water_pct"] > dry["days"][-17]["water_pct"]
    smap = {"status": "ok", "series": [{"date": (TODAY - timedelta(days=60)).isoformat(), "rootzone": 0.30, "surface": 0.30}]}
    moist = water.plan(41.3, 69.2, agro.CROPS["cotton"], LOAM, 0.6, 1, date(2026, 4, 15), None, TODAY, {"smap": smap})
    assert moist["start_from"] == "smap" and moist["smap_start"]["rootzone"] == 0.30


def test_observations_without_token(monkeypatch):
    from backend import observe
    monkeypatch.delenv("EARTHDATA_TOKEN", raising=False)
    out = observe.get(41.3, 69.2)
    assert out["smap"]["status"] == "unavailable" and out["hls"]["status"] == "unavailable"


def test_grid_positions():
    from backend import earthdata as ed
    assert ed.ease2_9km(41.45, 60.80) == (273, 2578)            # checked against SMAP cell_lat/cell_lon
    assert ed.modis_sin(41.45, 60.80) == ("h22v04", 4103, 2674)
    j, i = ed.imerg_index(41.45, 60.80)
    assert abs(-179.95 + j * 0.1 - 60.80) <= 0.0501 and abs(-89.95 + i * 0.1 - 41.45) <= 0.0501   # half a cell


# ---------- United States: CDL rotation, NASS units, SSURGO soil water ----------

def test_field_rotation_from_cropland_data_layer():
    from backend import usa
    years = lambda seq: [{"year": 2016 + k, "crops": c} for k, c in enumerate(seq)]  # noqa: E731
    assert usa.rotation_from_history(years([["maize"], ["soybean"]] * 4)) == {"years": [["maize"], ["soybean"]], "exact": True}
    messy = years([["winter_wheat"], ["winter_wheat"], ["sorghum"], ["soybean"], ["winter_wheat"], ["sorghum"],
                   ["soybean"], ["sorghum"], ["soybean"], ["winter_wheat"]])
    got = usa.rotation_from_history(messy)
    assert got["exact"] is False and got["years"] == [["sorghum"], ["soybean"], ["winter_wheat"]]
    assert usa.rotation_from_history(years([[], [], ["maize"]])) is None          # grass and fallow do not count
    assert usa.CDL_CROPS[26] == ["winter_wheat", "soybean"]                       # a double crop stays one year


def test_nass_units_and_ssurgo_water():
    from backend import usa
    crop, kg = usa.NASS_YIELD["CORN, GRAIN - YIELD, MEASURED IN BU / ACRE"]
    assert crop == "maize" and abs(200 * kg / 1000 / usa.ACRE_HA - 12.55) < 0.05   # 200 bu/acre = 12.6 t/ha
    sw = agro.soil_water("medium", {"clay_pct": 26, "sand_pct": 28, "organic_carbon_g_kg": 9, "awc_mm_per_m": 167})
    assert sw["source"] == "ssurgo" and sw["awc_mm_per_m"] == 167
    money = regional.economics("US", None, {"maize": {"t_ha": 13.0, "level": "county", "years": [2021, 2025]}})
    assert money["maize"]["source"] == "nass_county" and money["maize"]["yield_t_ha"] == 13.0
