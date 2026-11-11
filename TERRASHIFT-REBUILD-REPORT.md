# TerraShift 4.1 — Phase Report: Foundation Rebuild

**Scope of this cycle:** Phase 0 (baseline audit) + Phase 1–2 (product/UX + design foundation)
+ Phase 3 (domain database, adapted runtime) + Phase 4 (API & security foundation)
+ Phase 5 (farms/fields/map) + Phase 6 (data catalog & providers) + Phase 8 core
(monitoring & anomaly engine) + Phase 9 (evidence & hypothesis engine) + Phase 10 core
(uncertainty + verification) + Phase 11 core (decisions/outcomes/reports) — implemented
as one verified vertical slice of the full product, per blueprint §13 sequencing adapted
to a single runtime.

**Runtime adaptation (documented deviation per §1.2 / §3):**
- Blueprint target is PostgreSQL/PostGIS + FastAPI. This sandbox runs a single
  Next.js 16 service with Prisma + SQLite (runtime constraints). Polygons are stored
  as GeoJSON with computed geodesic area/centroid; spatial filtering is in-memory
  (48-point cache scale). The FastAPI engine was **ported to TypeScript with exact
  formulas** (FAO-56, cascade, all thresholds) rather than kept as a second service.
- Legacy `/api/*` contract preserved verbatim (health, options, layers, places,
  providers CRUD + admin token, analyze incl. 422/429 semantics).

## 1. Baseline audit (Phase 0)

- Full audit of `workspace-…tar`: FastAPI backend (NASA POWER/GIBS/SoilGrids/
  Open-Meteo providers, FAO-56 physics, climate pipeline, crop simulation, rotations,
  provider registry + SSRF guards, Telegram bot), Next.js shell (13 views, i18n
  EN/RU, zustand, Leaflet), gzip NASA POWER cache (48 grid points), FIXES_AND_VALIDATION.md.
- Confirmed limitations inventory (blueprint §1.4) carried into the honest-UI copy.
- Archive preserved read-only at `audit/` (excluded from build), source tar at
  `upload/`.

## 2. Architecture delivered

- **Single source of truth:** Prisma/SQLite domain schema (17 models: User, Session,
  Organization, Farm, Field, FieldBoundary (versioned), ClimateSnapshot, Provider,
  Job, AuditLog, MonitoringRun, Anomaly, EvidenceItem, Hypothesis, VerificationTask,
  Decision, Outcome, Report) — replacing Prisma User/Post scaffold + gzip files.
- **Engine** `src/server/terra/**` (~4,900 lines): physics (FAO-56 PM/Hargreaves/Ra,
  statistics OLS/Mann-Kendall/t80/percentiles), NASA POWER client (4 parallel ranges,
  monthly fallback), SoilGrids (depth-weighted 0–30 cm), Open-Meteo (forecast +
  elevation), GIBS registry (4 WMTS layers), Photon, SQLite cache w/ nearest-fallback,
  climate pipeline (fill-by-climatology, annual series, shift + projection to 2040,
  frost, recent, outlook), agro simulation (TAW/RAW water balance, heat/frost stress,
  rotations replay 2011–2025, soil health index), intelligence layer (MAD/seasonal-
  baseline/trend anomalies, uncertainty 7 dimensions, rule-based hypotheses,
  infoGain verification recommendations).
- **API** 42 route handlers: `/api/v1/*` (auth scrypt+sessions, org-scoped CRUD,
  RBAC viewer/member/owner, rate limits, audit log, error envelope with requestId)
  + legacy `/api/*` compatibility.
- **Frontend** 20 views in a 4-group shell (WORKSPACE/INTELLIGENCE/DATA/MANAGEMENT),
  EN/RU (1,447 key pairs, exact parity), dark/light global themes, Leaflet workspace
  with custom polygon draw/measure, Recharts with theme hook, AI assistant dock
  (z-ai-web-dev-sdk, backend-only, real-metrics context, honest disclaimers).

## 3. Data migration performed

- **NASA POWER cache:** 47 gzip snapshots from `audit/meteor-field-shift/backend/cache`
  → ClimateSnapshot rows (fields preserved: lat/lon/elevation/resolution/start/
  fetched_at/api_version/sources/params). Real historical daily series 1991→2026-11-10.
- Demo tenant created **through the production API** (register/login/farm/field/
  monitoring): org "Jizzakh Agro Demo", user demo@terrashift.app, 2 farms, 4 fields
  with real polygon boundaries at Jizzakh/Tashkent preset points, 4 monitoring runs
  (coverage=full, source=cache) → 18 real anomalies, 20 evidence items, hypotheses,
  10 verification recommendations. No fabricated values anywhere; empty states are
  honest ("empty, not zero findings").

## 4. Commands actually run and their results

| Command | Result |
|---|---|
| `bun run db:push` | schema applied, client generated |
| `bun scripts/seed.ts` | cache migrated 45+2; farms/fields created; 4 monitoring runs OK (3.5–8.7 s each); stats: farms=2 fields=4 monitored=4 anomalies=18 pendingVerification=10 |
| `bun run lint` | **0 errors, 0 warnings** |
| `bunx tsc --noEmit` | **0 errors** project-wide |
| Engine self-verification (transient `bun -e` runs by Task 2-a) | FAO-56 Ex.8 Ra(-20°,246)=32.19 ✓; Ex.18 PM ET0=3.88 ✓; percentile/MK ✓; live NASA POWER fetch 13,098 days in 2.2 s ✓; determinism (byte-identical repeat) ✓; SSRF guard 21/21 cases ✓ |
| Browser E2E (agent-browser) | see §5 |

## 5. Browser-verified flows (agent-browser, dev server :3000)

- Anonymous shell → login (demo@terrashift.app / terrashift-demo) → workspace loads.
- Overview: 5 KPI (2 farms, 4 monitored, 4 GIBS layers, 18 anomalies, 10 pending),
  map with 4 field polygons, critical-alerts panel with real deltas, activity feed.
- Field Intelligence: field header (54.2 ha, boundary v1, coverage FULL/cache),
  6-tab workspace, climate shift table (baseline→recent, Mann-Kendall significance),
  monthly climatology chart, crops, rotations, now, provenance.
- Anomalies: list+detail, real baselines/observations/deviations; **Confirm/Dismiss
  PATCH works** (state persisted).
- Verification Planner: recommendation cards with honest infoGain framing;
  **Accept action works** (task → ПРИНЯТА).
- Decisions & Outcomes: **created decision through the dialog** (persisted with
  rationale/action/owner).
- Reports: **generated field_summary from latest run** (reproducibility block:
  run id, coverage, timing, params).
- AI Assistant: asked about Cotton North climate shift — replied citing the exact
  stored metrics (+0.3 °C, 14.06→14.38) with AI-generated disclaimer footer.
- Evidence Explorer: provenance DAG + list (20 evidence items).
- EN ⇄ RU switching verified; mobile 390 px: no horizontal scroll, sticky statusbar
  (mt-auto) confirmed; VLM screenshot review passed (palette/layout 4/5, remaining
  nits are dev-mode overlays).
- dev.log: no errors attributable to product code; all requests 200.

## 6. API changes vs legacy

- New `/api/v1/*` namespace (blueprint §9). Legacy endpoints preserved with
  identical response shapes; `providers` admin auth now also accepts owner-role
  session in addition to `X-Admin-Token`.
- Breaking: none. Telegram client path (`/api/analyze`) unchanged.

## 7. Known limitations (honest)

1. **Runtime:** SQLite instead of PostgreSQL/PostGIS; spatial queries in-memory;
   single-service (no Redis/queue/S3). Raster pipeline (Sentinel-2 STAC, COG,
   zonal stats) NOT implemented — GIBS layers are visualization-only (stated in UI).
2. Anomaly/hypothesis engines are the transparent statistical layer; agronomic
   cause attribution and crop-specific modules remain roadmap (blueprint §6).
3. Verification infoGain is a heuristic, not a probability — labelled as such.
4. Monitoring jobs are synchronous request-scoped records (no worker queue yet).
5. Uzbek language exists only in backend localized config; UI is EN/RU (per
   acceptance list; uz labels fall back to EN).
6. Hydration-attribute warning in dev console (persisted lang/view vs SSR) —
   recovers instantly, no visual impact.
7. Legacy static frontend + Telegram bot not migrated (archive preserved); their
   scenarios are covered by the new UI workflows; Telegram remains on `/api/analyze`.
8. No production build/gateway validation in this cycle (dev-server verified only,
   per environment rules).

## 8. Acceptance status

- Single frontend ownership (Next.js `/` SPA) — ✓
- Single canonical domain DB — ✓ (SQLite adaptation documented)
- No unjustified feature regression — ✓ for legacy analyze/climate/crops/rotations/
  water/layers/providers/places (ported, live-tested); assistant upgraded to real LLM.
- Core workflow end-to-end — ✓ org→farm→field→monitoring→anomaly→evidence→
  hypothesis→verification→decision→report (browser-verified)
- Honest data states — ✓ (coverage/freshness/quality badges, empty vs zero)
- EN/RU complete — ✓ (1,447×2 keys, parity-checked)
- Dark/light global themes — ✓
- Responsive QA 390/1440 — ✓
- Raster pipeline / scientific validation / load & security testing / production
  deployment — **not in this cycle** (roadmap per blueprint Phases 7, 12–14).
