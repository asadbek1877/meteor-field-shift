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
4. The site draws one mission-control page: the verdict, climate shift (warming stripes,
   1991 to 2040 time machine, indicators), rotation ranking and trade-off map, crop cards,
   this week, impact at scale, and the data and method section.

## Data sources

| Source | Used for | Notes |
|---|---|---|
| NASA POWER daily API | all numbers: climate shift, crop water need, rotation replay | 1991 to yesterday, 8 parameters, four parallel requests (about 3 s). Sources: MERRA-2, GEOS-IT, CERES (SRB, SYN1deg, FLASHFlux). Grid about 50 km |
| NASA POWER monthly API | fallback when the daily request fails | day-level indicators become approximate |
| NASA GIBS | map layers: VIIRS true colour, MODIS NDVI, MODIS land surface temperature, SMAP L4 root-zone soil moisture, GPM IMERG precipitation, GRACE water storage | images only, no numbers. Dated layers take a date from the site's date picker (`dated`, `lag_days` in `providers.py`) |
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
| `backend/store.py` | memory and gzip file cache of NASA responses |
| `backend/physics.py` | FAO-56 Penman-Monteith and Hargreaves ET0, statistics |
| `backend/climate.py` | period comparison, trends, 2040 projection, frost season, last 30 days, outlook |
| `backend/agro.py` | crop simulation, rotation replay, soil health index, ranking |
| `backend/texts.py` | warnings and advice in English and Uzbek |
| `backend/crops.json`, `backend/rotations.json` | crop and rotation parameters (edit these, not the code) |
| `frontend/` | one page: landing journey (`index.html`, `hero.css`, `hero.js`) and the mission-control app (`terra.js`, `terra.css`, `i18n.js`); Leaflet and Chart.js in `vendor/`. The old page URLs (`rotations.html`, ...) redirect to the matching section. Every setting is mirrored in the URL so an analysis can be shared |
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
