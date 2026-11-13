# TerraShift architecture

TerraShift helps a farmer compare crop rotations for one field, using 35 years of
NASA climate data. This file explains how the app is built, how to run it, and what
is still a draft.

## Run it

```bash
pip install -r backend/requirements.txt
uvicorn backend.main:app --port 8000
```

- Site: http://localhost:8000
- API docs: http://localhost:8000/docs
- Tests (no network needed): `pip install pytest && python -m pytest tests -q`
- Refresh the saved demo data: `python -m backend.prewarm`, then commit `backend/cache/`

One server serves both the API and the site, so deployment is one service and one link.

## What happens when a farmer picks a field

1. The site sends `GET /api/analyze?lat=..&lon=..` with the field passport
   (current rotation, irrigation method, soil type) and four priority weights.
2. The server calls every enabled data source in parallel.
3. Whatever arrived is analysed. A source that failed is reported in `warnings`
   and `providers`; the request itself still succeeds.
4. The site draws the verdict, the rotation comparison, climate charts, crop table
   and the current-conditions block.

## Data sources

| Source | Used for | Notes |
|---|---|---|
| NASA POWER daily API | all numbers: climate shift, crop water need, rotation replay | 1991 to yesterday, 8 parameters, four parallel requests (about 3 s). Sources: MERRA-2, GEOS-IT, CERES (SRB, SYN1deg, FLASHFlux). Grid about 50 km |
| NASA POWER monthly API | fallback when the daily request fails | day-level indicators become approximate |
| NASA GIBS | map layers: MODIS NDVI, MODIS land surface temperature, GPM IMERG precipitation, GRACE water storage | images only, no numbers |
| SoilGrids (ISRIC) | soil texture, organic carbon, pH | not NASA. Did not respond from our network during development; the farmer can choose the soil type by hand |
| Open-Meteo | 16-day forecast for the "now" block | not NASA. If it fails, the block uses NASA climatology of the same dates |

Fallback order for NASA POWER: saved data of this point, live daily, live monthly,
nearest saved point within 150 km (shown with a warning), otherwise the climate
part is skipped. Numbers are never invented or "adjusted".

More sources can be added in the site (Data sources button) when the server runs
with `ADMIN_TOKEN` set: a map tile layer, or a JSON API that is returned as raw
`extra` data.

## Code map

| File | Role |
|---|---|
| `backend/main.py` | API routes, parallel provider calls, warnings, coverage |
| `backend/nasa_client.py` | NASA POWER daily and monthly clients |
| `backend/providers.py` | provider registry, GIBS layers, SoilGrids, Open-Meteo, health checks |
| `backend/geo.py` | place search (Nominatim, Photon backup; search on submit only, 1 req/s) and OSM land cover at the point |
| `backend/terrain.py` | NASA SRTM 30 m (OpenTopoData, 1 req/s, disk cache): height, slope and aspect from a 3×3 window 60 m apart → erosion / steep-slope warnings in `suitability.judge`; height drives the temperature lapse correction |
| `backend/earthdata.py` | Earthdata token (`.env` `EARTHDATA_TOKEN`): CMR granule search, cloud OPeNDAP point subsets read with h5py, LP DAAC COG pixels read with rasterio via the signed S3 link; grid helpers (EASE-2 9 km, MODIS sinusoidal, IMERG 0.1°, GLDAS 0.25°) |
| `backend/observe.py` | `/api/observations`: per-point NASA observations fetched in the background and cached in `backend/cache/obs/` — SMAP L4 soil moisture (30 d), GPM IMERG Late rain (60 d), GLDAS-2.1 monthly soil water percentile since 2000, MODIS MOD13Q1 NDVI (3 y), HLS 30 m NDVI (60 d, Fmask), ECOSTRESS LST + daily ET; FAO GAEZ v4 suitability (global); OpenET (western US, key), PRISM 10-year annual normals, USGS NWIS gauges, CoCoRaHS rain gauges (US) |
| `backend/usa.py` | US fields: FCC county, USDA CDL crop of every year since 2008 → the field's real rotation (the default "current" rotation), SSURGO soil (texture, AWC, drainage, K factor) replacing SoilGrids, NASS QuickStats county yields (`.env` `NASS_API_KEY`) |
| `backend/landcover.py` | 10 m satellite land cover (Sentinel-2, Impact Observatory/Microsoft/Esri, public ImageServer `getSamples`): the point + rings at 30 m and 100 m in one request → water / deep water / built-up / snow-ice / sea / bare / trees / crops. Decides water, buildings, ice and sea in `suitability.judge`; OpenStreetMap only adds names and exact buildings/roads |
| `backend/weekly.py` | this week's advice for the region's main crops (MapSPAM mix): growth stage, irrigation need in m³/ha with the 10–90 % range of 82 ensemble members, heat/frost alerts in the crop's sensitive stage, scorching ground for seedlings, downpours; for crops about to be sown: soil temperature at 6 cm vs. germination threshold, frost and crusting rain → sow / wait |
| `backend/water.py` | `/api/water`: soil water forecast of one field — FAO-56 dual crop coefficient (surface evaporation + transpiration, two-layer daily balance) from the last irrigation through the 16-day forecast; every member of the ECMWF (51) + GEFS (31) ensembles is run, so the dry date comes as 10/50/90 % quantiles with a probability; water need in mm, m³/ha, m³ and litres for the field |
| `backend/regional.py` | regional crop plan: FAOSTAT country mix → crops that ripen at this point (local sowing date, frost, season temperature) → generated rotations (typical / local / with a new legume, double cropping) → scored by `agro.Field` |
| `backend/data/country_crops.json` | FAOSTAT 2020–2024 per country: cropland share, yield, producer price (rebuild: `python -m backend.tools.build_country_crops QCL.zip PP.zip all.csv`) |
| `backend/data/local_crops.json.gz` | MapSPAM 2020 v2r2 (IFPRI, CC BY 4.0): crop mix per province on a 0.25° grid, 3×3 sub-pixels keep border cells apart (rebuild: `python -m backend.tools.build_local_crops spam2020V2r2_global_harvested_area.csv.zip`) |
| `backend/data/countries.json` | Natural Earth 1:50m borders for offline "which country" (rebuild: `python -m backend.tools.build_countries ne_50m_admin_0_countries.geojson`) |
| `backend/suitability.py` | "can crops grow here?": land cover (building, road, water, town...) + NASA POWER climate limits; `unsuitable` skips crop/rotation advice |
| `backend/store.py` | memory and gzip file cache of NASA responses |
| `backend/physics.py` | FAO-56 Penman-Monteith and Hargreaves ET0, statistics |
| `backend/climate.py` | period comparison, trends, 2040 projection, frost season, last 30 days, outlook |
| `backend/agro.py` | crop simulation, rotation replay, soil health index, ranking |
| `backend/texts.py` | warnings and advice in English and Uzbek |
| `backend/crops.json`, `backend/rotations.json` | crop and rotation parameters (edit these, not the code) |
| `frontend/` | static pages: field setup (`index.html`), rotations, climate, crops, current conditions and sources; shared `style.css`, `app.js`, `i18n.js`, Leaflet and Chart.js in `vendor/` |
| `tests/test_backend.py` | 16 tests, including two FAO-56 worked examples |

## Method

- **Reference evapotranspiration (ET0):** FAO-56 Penman-Monteith from daily
  temperature, humidity, wind and solar radiation. Checked against FAO-56
  example 18 (3.88 against 3.9 mm/day).
- **Crop water need:** ETc = Kc x ET0 with a four-stage Kc curve.
- **Irrigation:** daily root-zone water balance. When depletion passes p x TAW
  the field is refilled; the refills add up to the net irrigation need. Water to
  deliver = net / irrigation efficiency.
- **Climate risk:** days above the crop's heat threshold in its sensitive stage,
  and frost after sowing, turned into a 0 to 1 stress index.
- **Soil health:** a rule-based index of the rotation design (legumes, diversity,
  soil cover, residue, perennials). It is not a soil measurement.
- **Uncertainty:** every rotation is replayed over each weather year of 2011-2025.
  The site shows the 10th, 50th and 90th percentile and in how many years each
  rotation came first.
- **Trend and projection:** linear regression with the Mann-Kendall test. The 2040
  value is the trend continued with an 80% prediction interval. It is not a
  climate model.

## Known limits and drafts

- The climate grid is about 50 km: neighbouring fields get the same climate.
- Water numbers are computed from regional weather. Over irrigated land the real
  ET0 is usually lower (FAO-56 Annex 6), so the numbers are best used to compare
  crops, rotations and periods.
- `crops.json` and `rotations.json` are drafts. Kc, stage lengths, root depth and
  p follow FAO-56 tables, but heat and frost thresholds, residue classes,
  revenue per hectare and the rotation list must be verified with a local
  agronomy source.
- Near-real-time soil wetness in POWER comes from a different model than the
  long record, so it is not shown in the "now" block.
- Sowing dates in the simulation are fixed per crop; the suitable-date shift is
  reported separately.
- The official challenge page could not be read from our network. The product
  follows the challenge statement as quoted by other teams; confirm it on
  spaceappschallenge.org before submission.

## How to cite the data

- NASA POWER: "These data were obtained from the NASA Langley Research Center
  (LaRC) POWER Project funded through the NASA Earth Science/Applied Science
  Program." Check the exact wording at https://power.larc.nasa.gov/docs/referencing/
- NASA GIBS: "We acknowledge the use of imagery provided by services from NASA's
  Global Imagery Browse Services (GIBS), part of NASA's Earth Science Data and
  Information System (ESDIS)." Check at https://earthdata.nasa.gov/gibs
- FAO-56: Allen, R.G., Pereira, L.S., Raes, D., Smith, M. (1998). Crop
  evapotranspiration. FAO Irrigation and Drainage Paper 56.


## Accuracy measures (2026-11-12)

| Weak point | What is done |
|---|---|
| NASA POWER temperature is for the mean height of a ~50 km cell | `climate.prepare(data, point_elevation)`: lapse-rate correction to the field's height (Copernicus DEM via Open-Meteo, cached in `backend/cache/elevation.json`); 6.5 °C/km for maxima, 4.5 °C/km for minima so valley frost is not corrected away |
| Three soil classes | `agro.soil_water()`: field capacity and wilting point from measured sand/clay/organic carbon (SoilGrids) with Saxton & Rawls (2006); class values only as fallback |
| SoilGrids answers in ~10 s or not at all | background fetch with a 25 s timeout and a disk cache (`backend/cache/soil.json`); a request waits 3.5 s, the next one has the soil |
| One national yield per crop | province yield from MapSPAM (production / harvested area) × country price (FAOSTAT) |
| One rain forecast, guessed ±50 % | 82 ensemble members run through the water balance |
| Small showers, surface drying | dual crop coefficient: the top 10 cm are balanced separately |
| Unknown starting soil moisture | from the farmer's last irrigation date; else from sowing / 60 days of observed weather, stated as "no irrigation assumed" |
| A reservoir or a hospital yard was rated "fine" (OSM reverse returns the nearest label, e.g. a road) | satellite land cover at the point and 100 m around decides; verified on Charvak, Aydarkul, Tuyamuyun, Caspian, two Tashkent hospitals, Fedchenko glacier |
| Past rain was a weather-model estimate | GPM IMERG observed daily rain replaces it in the water balance; ERA5 reanalysis for days older than 6 days |
| Unknown starting soil moisture (no irrigation date) | NASA SMAP L4 root-zone moisture of the start day |
| No check that a crop is really in the field | HLS 30 m NDVI: "bare field" warning in the weekly advice |
