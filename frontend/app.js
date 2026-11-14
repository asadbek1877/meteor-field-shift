/* TerraShift site. One page, no build step: Leaflet for the map, Chart.js for charts. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const on = (id, event, handler) => { const el = $(id); if (el) el.addEventListener(event, handler); };
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // ---------- state ----------
  const saved = (() => { try { return JSON.parse(localStorage.getItem("terrashift") || "{}"); } catch { return {}; } })();
  const state = Object.assign({
    lat: 40.1158, lon: 67.8422, lang: "uz", soil: "auto", irrigation: "furrow", current: null,
    customYears: [["cotton", ""], ["winter_wheat", ""]],
    weights: { water: 40, income: 20, soil: 20, risk: 20 }, layer: "", opacity: 70, metric: "t_mean", locationLabel: "", period: "",
    field: { name: "", polygon: null, area_ha: null }, mode: "auto", manual: null, autoCurrent: null,
    climPeriod: "", climRegion: "",
    cropCat: "all", cropSel: "", cropSort: "fit", cropAll: false,
  }, saved);
  const save = () => { try { localStorage.setItem("terrashift", JSON.stringify(state)); } catch { /* private mode */ } };

  let options = null, data = null, map = null, marker = null, overlay = null, layers = [];
  let requestMode = "auto";            /* which mode the request in flight was made from */
  if (!state.field || typeof state.field !== "object") state.field = { name: "", polygon: null, area_ha: null };
  let placeTimer = null, placeController = null, placeResults = [], activePlaceIndex = -1;
  const charts = {};

  // ---------- texts and numbers ----------
  const t = (key, vars) => {
    let s = (window.I18N[state.lang] || window.I18N.en)[key] ?? window.I18N.en[key] ?? key;
    if (vars && typeof s === "string") for (const k in vars) s = s.replaceAll(`{${k}}`, vars[k]);
    return s;
  };
  const name = (obj) => (obj && obj.name ? (obj.name[state.lang] || obj.name.en) : "");
  const title = (obj) => (obj && obj.title ? (obj.title[state.lang] || obj.title.en) : "");
  const fmt = (n, digits = 0) => {
    if (n === null || n === undefined || Number.isNaN(n)) return "–";
    const s = Math.abs(n).toFixed(digits);
    const [int, frac] = s.split(".");
    const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, " ");
    return (n < 0 ? "−" : "") + grouped + (frac ? "." + frac : "");
  };
  const sgn = (n, digits = 0) => (n > 0 ? "+" : "") + fmt(n, digits);
  const md = (mmdd) => {
    if (!mmdd) return "–";
    const [m, d] = mmdd.split("-").map(Number);
    return `${d}-${t("months")[m - 1].toLowerCase()}`;
  };
  const isoDay = (iso) => { const [, m, d] = iso.split("-").map(Number); return `${d}-${t("months")[m - 1].toLowerCase()}`; };
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const ICON = { tip: "✓", info: "i", warning: "!", critical: "▲" };

  function applyStaticTexts() {
    document.documentElement.lang = state.lang;
    document.querySelectorAll("[data-t]").forEach((el) => { el.textContent = t(el.dataset.t); });
    document.querySelectorAll("[data-t-placeholder]").forEach((el) => { el.setAttribute("placeholder", t(el.dataset.tPlaceholder)); });
    document.querySelectorAll("[data-t-aria]").forEach((el) => el.setAttribute("aria-label", t(el.dataset.tAria)));
    document.querySelectorAll("[data-t-title]").forEach((el) => el.setAttribute("title", t(el.dataset.tTitle)));
    document.querySelectorAll("[data-lang]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lang === state.lang)));
    if ($("place-info")) $("place-info").textContent = state.locationLabel ? t("place_selected", { place: state.locationLabel }) : "";
    document.querySelectorAll("[data-page-link]").forEach((link) => {
      if (link.dataset.pageLink === document.body.dataset.page) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
    document.title = t(document.body.dataset.title || "page_title_home");
  }

  // ---------- API ----------
  const api = async (path, init) => {
    const res = await fetch(path, init);
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail || res.status));
    return body;
  };

  let controller = null, timer = null;
  function analysisPoint() {
    if ($("clim-region") && state.climRegion && options) {
      const preset = options.presets.find((x) => x.id === state.climRegion);
      if (preset) return { lat: preset.lat, lon: preset.lon };
    }
    return { lat: state.lat, lon: state.lon };
  }
  function analyzeSoon(delay = 250) { clearTimeout(timer); timer = setTimeout(analyze, delay); }

  async function analyze() {
    save();
    if (controller) controller.abort();
    const requestController = new AbortController();
    controller = requestController;
    const pt = analysisPoint();
    const q = new URLSearchParams({
      lat: pt.lat, lon: pt.lon, lang: state.lang, soil: state.soil, irrigation: state.irrigation,
      w_water: state.weights.water, w_income: state.weights.income, w_soil: state.weights.soil, w_risk: state.weights.risk,
    });
    if (state.current === "custom") {
      q.set("custom", state.customYears.map((y) => y.filter(Boolean).join("+")).filter(Boolean).join("|"));
    } else if (state.current) q.set("current", state.current);
    if (state.period) q.set("period", state.period);
    const mode = requestMode;
    dashState(data ? "updating" : "loading", mode);
    if ($("content")) {
      $("content").classList.add("loading");
      $("content").setAttribute("aria-busy", "true");
    }
    if ($("analysis-status")) $("analysis-status").textContent = t("analyzing");
    if (!data && $("verdict")) $("verdict").textContent = t("loading");
    try {
      const fresh = await api(`/api/analyze?${q}`, { signal: requestController.signal });
      if (controller !== requestController) return;          /* a newer request was started meanwhile */
      fresh.mode = mode;
      data = fresh;
      render();
      dashState("ready");
      if ($("analysis-status")) $("analysis-status").textContent = t("analysis_updated");
    } catch (err) {
      if (err.name === "AbortError") return;
      console.error("Analysis failed:", err);
      if (document.querySelector(".dash")) dashError(err);
      else if ($("warnings")) $("warnings").innerHTML = alertHtml("critical", t("error", { msg: err.message }));
      if ($("analysis-status")) $("analysis-status").textContent = t("analysis_failed");
    } finally {
      if (controller === requestController) {
        if ($("content")) {
          $("content").classList.remove("loading");
          $("content").setAttribute("aria-busy", "false");
        }
      }
    }
  }

  // ---------- map ----------
  function initMap() {
    if (!$("map")) return;
    const satellite = $("map").dataset.base === "satellite";
    map = L.map("map", { zoomControl: true, attributionControl: true }).setView([state.lat, state.lon], satellite ? 13 : 7);
    boundaryLayer = L.layerGroup().addTo(map);
    draftLayer = L.layerGroup().addTo(map);
    if (satellite) {
      L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        { maxZoom: 18, attribution: "Imagery © Esri, Maxar, Earthstar Geographics" }).addTo(map);
    } else {
      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, attribution: "© OpenStreetMap" }).addTo(map);
    }
    marker = L.marker([state.lat, state.lon], { icon: L.divIcon({ className: "", html: '<div class="pin"></div>', iconSize: [18, 18], iconAnchor: [9, 9] }) }).addTo(map);
    map.on("click", onMapClick);
    map.on("mousemove", onMapMove);
    if ($("map").closest(".field-media")) setMapInteractive(false);
    drawBoundary(false);
  }

  function setPoint(lat, lon, recenter = true, locationLabel = "", keepBoundary = false) {
    if (!map || !marker) return;
    // A new point outside the drawn field means a different field: the old boundary no longer applies.
    if (!keepBoundary && state.field.polygon && !insidePolygon([lat, lon], state.field.polygon)) {
      state.field = { name: state.field.name, polygon: null, area_ha: null };
      drawBoundary(false);
      drawNote = t("draw_moved");
    }
    state.lat = Math.round(lat * 1e4) / 1e4;
    state.lon = Math.round((((lon + 180) % 360 + 360) % 360 - 180) * 1e4) / 1e4;  // wrap any world copy to -180..180
    state.locationLabel = locationLabel;
    marker.setLatLng([state.lat, state.lon]);
    if (recenter) map.setView([state.lat, state.lon], Math.max(map.getZoom(), 8));
    $("coords").textContent = `${state.lat.toFixed(4)}, ${state.lon.toFixed(4)}`;
    if ($("place-search")) $("place-search").value = locationLabel;
    if ($("place-info")) $("place-info").textContent = locationLabel ? t("place_selected", { place: locationLabel }) : "";
    document.querySelectorAll("#presets .btn").forEach((b) => {
      const selected = +b.dataset.lat === state.lat && +b.dataset.lon === state.lon;
      b.classList.toggle("active", selected);
      b.setAttribute("aria-pressed", String(selected));
    });
    analyze();
  }

  // ---------- field boundary: drawing, geodesic area, apply/cancel ----------
  let boundaryLayer = null, draftLayer = null, guideLine = null, mapExpanded = false;
  const draft = { active: false, closed: false, points: [] };     /* points: L.LatLng */
  let drawNote = "";                                                /* a one-off message, e.g. "boundary removed" */
  const EARTH_RADIUS = 6378137;
  const rad = (d) => d * Math.PI / 180;

  // Area of a polygon on the sphere (m²), from geographic coordinates, not screen pixels:
  // A = |Σ (λ2 − λ1) · (2 + sin φ1 + sin φ2)| · R² / 2  (same formula as Leaflet.draw's geodesicArea).
  function geodesicArea(points) {
    if (points.length < 3) return 0;
    let sum = 0;
    for (let i = 0; i < points.length; i++) {
      const a = points[i], b = points[(i + 1) % points.length];
      sum += rad(b.lng - a.lng) * (2 + Math.sin(rad(a.lat)) + Math.sin(rad(b.lat)));
    }
    return Math.abs(sum * EARTH_RADIUS * EARTH_RADIUS / 2);
  }
  const toLatLngs = (poly) => poly.map(([la, lo]) => L.latLng(la, lo));
  function insidePolygon([lat, lon], poly) {
    let inside = false;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const [yi, xi] = poly[i], [yj, xj] = poly[j];
      if ((yi > lat) !== (yj > lat) && lon < (xj - xi) * (lat - yi) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  }
  function polygonCentroid(points) {
    let a = 0, cx = 0, cy = 0;
    for (let i = 0; i < points.length; i++) {
      const p = points[i], q = points[(i + 1) % points.length];
      const f = p.lng * q.lat - q.lng * p.lat;
      a += f; cx += (p.lng + q.lng) * f; cy += (p.lat + q.lat) * f;
    }
    if (Math.abs(a) < 1e-12) return L.latLng(points.reduce((s, p) => s + p.lat, 0) / points.length, points.reduce((s, p) => s + p.lng, 0) / points.length);
    return L.latLng(cy / (3 * a), cx / (3 * a));
  }
  // Two edges that are not neighbours must not cross (a figure-of-eight is not a field).
  function selfIntersects(points) {
    const n = points.length;
    const cross = (a, b, c) => (b.lng - a.lng) * (c.lat - a.lat) - (b.lat - a.lat) * (c.lng - a.lng);
    const hit = (p1, p2, p3, p4) => {
      const d1 = cross(p3, p4, p1), d2 = cross(p3, p4, p2), d3 = cross(p1, p2, p3), d4 = cross(p1, p2, p4);
      return ((d1 > 0) !== (d2 > 0)) && ((d3 > 0) !== (d4 > 0));
    };
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        if (Math.abs(i - j) <= 1 || (i === 0 && j === n - 1)) continue;
        if (hit(points[i], points[(i + 1) % n], points[j], points[(j + 1) % n])) return true;
      }
    }
    return false;
  }
  const fmtHa = (ha) => `${fmt(ha, ha < 10 ? 2 : 1)} ${t("unit_ha")}`;

  function setMapInteractive(on) {
    if (!map) return;
    ["dragging", "scrollWheelZoom", "doubleClickZoom", "boxZoom", "keyboard", "touchZoom"].forEach((h) => { if (map[h]) map[h][on ? "enable" : "disable"](); });
    $("map").classList.toggle("is-preview", !on);
  }
  function onMapClick(e) {
    if (!mapExpanded) { openMap(false); return; }        /* the small preview opens the big map */
    if (draft.active) { addVertex(e.latlng); return; }
    setPoint(e.latlng.lat, e.latlng.lng, false, "");
  }
  function onMapMove(e) {
    if (!draft.active || !draft.points.length || !guideLine) return;
    guideLine.setLatLngs([draft.points[draft.points.length - 1], e.latlng]);
  }

  // The saved boundary (green). Drawn on the one map instance, so it shows in the preview and the big map.
  function drawBoundary(fit) {
    if (!boundaryLayer) return;
    boundaryLayer.clearLayers();
    const poly = state.field.polygon;
    if (!poly || poly.length < 3) return;
    const shape = L.polygon(toLatLngs(poly), { color: "#47e08c", weight: 2.5, fillColor: "#3ddc84", fillOpacity: 0.2, className: "field-boundary", interactive: false });
    boundaryLayer.addLayer(shape);
    if (fit) map.fitBounds(shape.getBounds(), { padding: [24, 24], maxZoom: 17, animate: false });
  }

  function drawStatus(text, error) {
    if ($("draw-status")) $("draw-status").textContent = text || "";
    if ($("draw-error")) { $("draw-error").hidden = !error; $("draw-error").textContent = error || ""; }
  }

  function renderDraft() {
    if (!draftLayer) return;
    draftLayer.clearLayers();
    guideLine = null;
    const pts = draft.points;
    if (pts.length >= 3) {
      draftLayer.addLayer(L.polygon(pts, { color: "#3ec5ff", weight: 2.5, fillColor: draft.closed ? "#3ddc84" : "#3ec5ff",
        fillOpacity: draft.closed ? 0.24 : 0.14, dashArray: draft.closed ? null : "8 6", className: draft.closed ? "draft-poly is-closed" : "draft-poly", interactive: false }));
    } else if (pts.length === 2) {
      draftLayer.addLayer(L.polyline(pts, { color: "#3ec5ff", weight: 2.5, className: "draft-line", interactive: false }));
    }
    if (draft.active && pts.length) {
      guideLine = L.polyline([pts[pts.length - 1], pts[pts.length - 1]], { color: "#9fe3ff", weight: 1.5, dashArray: "4 6", className: "draft-guide", interactive: false });
      draftLayer.addLayer(guideLine);
    }
    pts.forEach((p, i) => {
      const first = i === 0 && pts.length >= 3 && draft.active;
      const v = L.circleMarker(p, { radius: first ? 8 : 6, color: "#ffffff", weight: 2, fillColor: first ? "#3ddc84" : "#3ec5ff", fillOpacity: 1,
        bubblingMouseEvents: false, className: first ? "draft-vertex is-first" : "draft-vertex" });
      v.bindTooltip(String.fromCharCode(65 + (i % 26)), { permanent: true, direction: "top", offset: [0, -8], className: "vertex-label" });
      v.on("click", () => {
        if (first) closeDraft();
        else if (draft.active) addVertex(p);
      });
      draftLayer.addLayer(v);
    });
    updateDrawUi();
  }

  function updateDrawUi() {
    if (!$("draw-area")) return;
    const n = draft.points.length;
    const showing = draft.active || draft.closed;
    const area = showing ? geodesicArea(draft.points) / 1e4 : (state.field.area_ha || 0);
    $("draw-area").textContent = (showing ? n >= 3 : !!state.field.polygon) ? fmtHa(area) : "–";
    $("draw-points").textContent = showing ? t("draw_points", { n }) : "";
    $("draw-start").hidden = showing;
    $("draw-start").querySelector("span").textContent = t(state.field.polygon ? "draw_redraw" : "draw_start");
    $("draw-undo").disabled = !showing || n === 0;
    $("draw-clear").disabled = !showing || n === 0;
    $("draw-apply").disabled = !showing || n < 3;
    $("map").classList.toggle("is-drawing", draft.active);
    if (draft.active) drawStatus(t(n === 0 ? "draw_hint_first" : n < 3 ? "draw_hint_more" : "draw_hint_close"));
    else if (draft.closed) drawStatus(t("draw_hint_apply"));
    else if ($("draw-error").hidden) drawStatus(drawNote || t(state.field.polygon ? "draw_hint_saved" : "draw_hint_idle"));
  }

  function startDraw() {
    drawNote = "";
    draft.active = true; draft.closed = false; draft.points = [];
    if (boundaryLayer) boundaryLayer.clearLayers();         /* the saved boundary comes back on cancel */
    drawStatus("");
    renderDraft();
  }
  function addVertex(latlng) {
    if (!draft.active) return;
    draft.points.push(L.latLng(latlng.lat, latlng.lng));
    renderDraft();
  }
  function closeDraft() {
    if (draft.points.length < 3) return;
    draft.active = false; draft.closed = true;
    renderDraft();
  }
  function undoVertex() {
    draft.points.pop();
    draft.active = true; draft.closed = false;
    renderDraft();
  }
  function clearDraft() {
    draft.points = []; draft.active = true; draft.closed = false;
    renderDraft();
  }
  // Leaves the draft and shows the saved boundary again. Nothing in state changes.
  function discardDraft() {
    draft.active = false; draft.closed = false; draft.points = [];
    renderDraft();
    drawBoundary(false);
    drawStatus("");
  }
  function applyDraft() {
    const pts = draft.points;
    if (pts.length < 3) { drawStatus("", t("draw_err_points")); return; }
    if (selfIntersects(pts)) { drawStatus("", t("draw_err_cross")); return; }
    const ha = geodesicArea(pts) / 1e4;
    if (!(ha >= 0.01)) { drawStatus("", t("draw_err_small")); return; }
    if (ha > 100000) { drawStatus("", t("draw_err_large")); return; }
    state.field = {
      name: state.field.name || "",
      polygon: pts.map((p) => [Math.round(p.lat * 1e6) / 1e6, Math.round(p.lng * 1e6) / 1e6]),
      area_ha: Math.round(ha * 100) / 100,
    };
    draft.active = false; draft.closed = false; draft.points = [];
    renderDraft();
    drawBoundary(false);
    save();
    const c = polygonCentroid(toLatLngs(state.field.polygon));
    closeMap();                                               /* back to the dashboard */
    setPoint(c.lat, c.lng, false, state.locationLabel, true);  /* analysis follows the field */
    renderFieldFacts();
    document.dispatchEvent(new CustomEvent("field:applied", { detail: { area: state.field.area_ha } }));
  }

  function openMap(draw) {
    const dialog = $("map-dialog");
    if (!map || !dialog) return;
    if (!dialog.open) $("open-map").click();
    if (draw) startDraw();
  }
  function closeMap() {
    const dialog = $("map-dialog");
    if (dialog && dialog.open) dialog.close();
  }
  function fitField() {
    if (!map) return;
    map.invalidateSize({ pan: false });
    const poly = state.field.polygon;
    if (poly) map.fitBounds(L.latLngBounds(toLatLngs(poly)), { padding: [24, 24], maxZoom: 17, animate: false });
    else map.setView([state.lat, state.lon], map.getZoom(), { animate: false });
    if (!draft.active && !draft.closed) drawBoundary(false);   /* while drawing, the saved boundary stays hidden */
  }

  function renderFieldFacts() {
    if (!$("field-area")) return;
    const f = state.field;
    $("field-area").textContent = f.area_ha ? fmtHa(f.area_ha) : t("area_none");
    $("field-area").classList.toggle("is-empty", !f.area_ha);
    document.querySelectorAll("[data-draw] span").forEach((el) => { el.textContent = t(f.polygon ? "draw_edit" : "draw_boundary"); });
    if ($("mf-area")) $("mf-area").textContent = f.area_ha ? fmtHa(f.area_ha) : t("area_none");
    const preset = options && options.presets.find((p) => p.lat === state.lat && p.lon === state.lon);
    const place = state.locationLabel || (preset ? name(preset) : t("field_point"));
    if ($("field-place")) $("field-place").textContent = f.name ? `${f.name} · ${place}` : place;
    if ($("field-coords")) $("field-coords").textContent = `${fmt(state.lat, 4)}, ${fmt(state.lon, 4)}`;
    if ($("mf-location")) $("mf-location").textContent = `${place} (${fmt(state.lat, 3)}, ${fmt(state.lon, 3)})`;
    updateDrawUi();
  }

  function renderLayerSelect() {
    if (!$("layer")) return;
    const sel = $("layer");
    sel.innerHTML = `<option value="">${esc(t("layer_none"))}</option>` +
      layers.map((l) => `<option value="${esc(l.id)}">${esc(title(l))}</option>`).join("");
    if (!layers.some((l) => l.id === state.layer)) state.layer = "";
    sel.value = state.layer;
    showOverlay();
  }

  function showOverlay() {
    if (!map) return;
    if (overlay) { map.removeLayer(overlay); overlay = null; }
    const layer = layers.find((l) => l.id === state.layer);
    $("opacity-row").hidden = !layer;
    if (!layer) return;
    overlay = L.tileLayer(layer.url, { maxNativeZoom: layer.max_zoom, maxZoom: 18, opacity: state.opacity / 100, attribution: esc(layer.attribution) }).addTo(map);
  }

  function locate() {
    const msg = $("locate-msg");
    const button = $("locate");
    const setPending = (pending) => {
      button.disabled = pending;
      button.setAttribute("aria-busy", String(pending));
      button.textContent = t(pending ? "locating" : "locate");
    };
    const fail = (key) => { setPending(false); msg.textContent = t(key); msg.hidden = false; };
    msg.hidden = true;
    if (!window.isSecureContext || !navigator.geolocation) return fail("locate_insecure");
    setPending(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => { setPending(false); setPoint(pos.coords.latitude, pos.coords.longitude); },
      (err) => { fail(err.code === 1 ? "locate_denied" : "locate_unavailable"); },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 });
  }

  function placeName(properties) {
    return properties.name || properties.locality || properties.street || properties.district || properties.city || properties.county || properties.state || properties.country || "";
  }

  function placeContext(properties, primary) {
    return [...new Set([properties.locality, properties.district, properties.city, properties.county, properties.state, properties.country])]
      .filter((part) => part && part !== primary)
      .join(", ");
  }

  function hidePlaceResults() {
    const list = $("place-results"), input = $("place-search");
    if (!list || !input) return;
    list.hidden = true;
    list.replaceChildren();
    placeResults = [];
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
    activePlaceIndex = -1;
  }

  function renderPlaceResults(features) {
    const list = $("place-results");
    if (!list) return;
    placeResults = features.map((feature) => {
      const properties = feature.properties || {};
      const primary = placeName(properties);
      const context = placeContext(properties, primary);
      const coordinates = feature.geometry && feature.geometry.coordinates;
      return {
        primary,
        context,
        label: [primary, context].filter(Boolean).join(", "),
        lon: Number(coordinates && coordinates[0]),
        lat: Number(coordinates && coordinates[1]),
      };
    }).filter((place) => place.primary && Number.isFinite(place.lat) && Number.isFinite(place.lon)
      && place.lat >= -90 && place.lat <= 90 && place.lon >= -180 && place.lon <= 180);
    activePlaceIndex = -1;
    if (!placeResults.length) {
      hidePlaceResults();
      $("place-search-status").textContent = t("place_search_empty");
      return;
    }
    list.innerHTML = placeResults.map((place, index) => `
      <li role="presentation"><button type="button" class="place-option" role="option" id="place-result-${index}" aria-selected="false" tabindex="-1" data-place-index="${index}">
        <span>${esc(place.primary)}</span>${place.context ? `<small>${esc(place.context)}</small>` : ""}
      </button></li>`).join("");
    list.hidden = false;
    $("place-search").setAttribute("aria-expanded", "true");
    $("place-search-status").textContent = t("place_search_count", { n: placeResults.length });
  }

  async function searchPlaces(query) {
    if (placeController) placeController.abort();
    const requestController = new AbortController();
    placeController = requestController;
    $("place-search-status").textContent = t("place_searching");
    $("place-search").setAttribute("aria-busy", "true");
    try {
      const params = new URLSearchParams({ q: query, limit: 6, lang: state.lang });
      const response = await fetch(`/api/places?${params}`, { signal: requestController.signal });
      if (!response.ok) throw new Error(`Place search failed (${response.status})`);
      const result = await response.json();
      if (placeController !== requestController) return;
      renderPlaceResults(Array.isArray(result.features) ? result.features : []);
    } catch (err) {
      if (err.name === "AbortError") return;
      if (placeController === requestController) {
        hidePlaceResults();
        $("place-search-status").textContent = t("place_search_error");
      }
    } finally {
      if (placeController === requestController) $("place-search").setAttribute("aria-busy", "false");
    }
  }

  function choosePlace(index) {
    const place = placeResults[index];
    if (!place) return;
    $("place-search").value = place.label;
    $("place-search-status").textContent = "";
    hidePlaceResults();
    setPoint(place.lat, place.lon, true, place.label);
  }

  function updateActivePlace(index) {
    if (!placeResults.length) return;
    activePlaceIndex = (index + placeResults.length) % placeResults.length;
    const input = $("place-search");
    input.setAttribute("aria-activedescendant", `place-result-${activePlaceIndex}`);
    document.querySelectorAll("#place-results [role='option']").forEach((option, i) => {
      option.setAttribute("aria-selected", String(i === activePlaceIndex));
    });
  }

  // ---------- forms ----------
  function renderForms() {
    if ($("presets")) $("presets").innerHTML = options.presets.map((p) =>
      `<button type="button" class="btn ghost" data-lat="${p.lat}" data-lon="${p.lon}" aria-pressed="${p.lat === state.lat && p.lon === state.lon}">${esc(name(p))}</button>`).join("");
    if ($("current")) {
      $("current").innerHTML = options.rotations.map((r) => `<option value="${esc(r.id)}">${esc(name(r))}</option>`).join("") +
        `<option value="custom">${esc(t("custom_rotation"))}</option>`;
      $("current").value = state.current || options.default_current;
    }
    if ($("irrigation")) {
      $("irrigation").innerHTML = options.irrigation.map((m) =>
        ($("irrigation").closest(".dash")
          ? `<option value="${esc(m.id)}" title="${esc(t("efficiency", { pct: Math.round(m.efficiency * 100) }))}">${esc(name(m))} – ${Math.round(m.efficiency * 100)}%</option>`
          : `<option value="${esc(m.id)}">${esc(name(m))} · ${esc(t("efficiency", { pct: Math.round(m.efficiency * 100) }))}</option>`)).join("");
      $("irrigation").value = state.irrigation;
    }
    if ($("soil")) {
      $("soil").innerHTML = `<option value="auto">${esc(t("soil_auto"))}</option>` +
        options.soils.map((s) => `<option value="${esc(s.id)}">${esc(name(s))}</option>`).join("");
      $("soil").value = state.soil;
    }
    if ($("period")) {
      const last = options.periods.recent[1];
      const choices = [["", "period_recent", options.periods.recent[0]], [`${last - 9}-${last}`, "period_10", last - 9],
        [`2001-${last}`, "period_25", 2001], [`1991-${last}`, "period_all", 1991]];
      $("period").innerHTML = choices.map(([v, key, first]) =>
        `<option value="${v}">${esc(t(key, { a: first, b: last }))}</option>`).join("");
      if (!choices.some(([v]) => v === state.period)) state.period = "";   /* an old or unknown saved value */
      $("period").value = state.period;
      if ($("mf-period")) $("mf-period").innerHTML = $("period").innerHTML;
    }
    renderManualForm();
    renderClimateForm();
    if ($("sliders")) {
      $("sliders").innerHTML = ["water", "income", "soil", "risk"].map((k) => `
        <div class="slider">
          <label for="w-${k}">${esc(t("w_" + k))}</label><output id="o-${k}"></output>
          <input type="range" id="w-${k}" min="0" max="100" step="5" value="${state.weights[k]}" data-w="${k}">
        </div>`).join("");
      renderWeights();
    }
    renderBuilder();
  }

  // ---------- climate page ----------
  // 35 years of NASA POWER at the chosen region; the purple part is the linear trend continued to 2040
  // with its 80% band (a projection, never presented as an observation).
  const CLIM_KEYS = ["t_mean", "precip_mm", "et0_mm", "hot_days", "frost_days", "dry_spell_days", "rain_days", "aridity", "t_max"];
  const CLIM_DIGITS = { t_mean: 1, t_max: 1, aridity: 2 };
  const CLIM_CARDS = [["cm-t", "t_mean"], ["cm-p", "precip_mm"], ["cm-et", "et0_mm"], ["cm-hot", "hot_days"], ["cm-cold", "frost_days"]];
  const unitOf = (key) => { const u = t("unit_" + key); return u ? (u.startsWith("°") ? u : " " + u) : ""; };
  const withUnit = (v, key, signed) => `${signed ? sgn(v, CLIM_DIGITS[key] || 0) : fmt(v, CLIM_DIGITS[key] || 0)}${unitOf(key)}`.replace(/(\d)(°)/, "$1 $2");

  function renderClimateForm() {
    if (!$("clim-region") || !options) return;
    const preset = options.presets.find((p) => p.lat === state.lat && p.lon === state.lon);
    const place = state.field && state.field.name ? state.field.name : state.locationLabel || (preset ? name(preset) : t("field_point"));
    $("clim-region").innerHTML = `<option value="">${esc(t("clim_my_field", { place }))}</option>` +
      options.presets.map((p) => `<option value="${esc(p.id)}">${esc(name(p))}</option>`).join("");
    if (!options.presets.some((p) => p.id === state.climRegion)) state.climRegion = "";
    $("clim-region").value = state.climRegion;
    const last = options.periods.recent[1];
    $("clim-period").innerHTML = [1991, 2001, 2011].map((y) => `<option value="${y === 1991 ? "" : y}">${y}–${last}</option>`).join("");
    if (!["", "2001", "2011"].includes(state.climPeriod)) state.climPeriod = "";
    $("clim-period").value = state.climPeriod;
    $("clim-metric").innerHTML = CLIM_KEYS.map((k) => `<option value="${k}">${esc(t("k_" + k))}</option>`).join("");
    if (!CLIM_KEYS.includes(state.metric)) state.metric = "t_mean";
    $("clim-metric").value = state.metric;
  }

  function renderClimatePage() {
    const c = data.climate, p = data.periods;
    const first = c && c.annual.length ? c.annual[0].year : 1991;
    const last = c && c.annual.length ? c.annual[c.annual.length - 1].year : 2025;
    $("clim-sub").textContent = t("clim_sub", { a: first, b: last, y: 2040 });
    renderClimNow();
    renderClimateForm();
    if (!c) {
      CLIM_CARDS.forEach(([id]) => { setMetric(id, "–"); $(id + "-dir").className = "cm-arrow"; });
      $("clim-findings").innerHTML = `<li class="is-empty">${esc(t("no_data_sub"))}</li>`;
      $("clim-advice-text").textContent = t("no_data_sub");
      $("clim-advice-why").textContent = "";
      return;
    }
    CLIM_CARDS.forEach(([id, key]) => {
      const sh = c.shift[key], dir = $(id + "-dir");
      if (!sh || sh.delta === null || sh.delta === undefined) { setMetric(id, "–"); dir.className = "cm-arrow"; return; }
      setMetric(id, withUnit(sh.delta, key, true), null, sh.delta, (v) => withUnit(v, key, true));
      dir.className = "cm-arrow " + (sh.delta > 0 ? "is-up" : sh.delta < 0 ? "is-down" : "is-flat");
      $(id).closest(".cmetric").title = `${t("k_" + key)}: ${t("before_now", { a: withUnit(sh.baseline, key), b: withUnit(sh.recent, key) })} ` +
        `(${p.baseline[0]}–${p.baseline[1]} → ${p.recent[0]}–${p.recent[1]}) · ${t(sh.trend_significant ? "sig_yes" : "sig_no")}`;
    });
    renderClimAnnual();
    renderClimMonthly();
    renderClimGauge();
    renderClimFindings();
    renderClimAdvice();
  }

  // today's forecast (live, Open-Meteo) in the top-right corner
  function renderClimNow() {
    const box = $("clim-now");
    const fc = data.now && data.now.forecast, d = fc && fc.days && fc.days[0];
    box.hidden = !d;
    if (!d) return;
    const rows = [
      [t("clim_now_temp"), `${fmt(d.t_max, 0)}° / ${fmt(d.t_min, 0)}°`],
      [t("clim_now_rain"), d.rain_probability !== null && d.rain_probability !== undefined ? `${fmt(d.rain_probability)}%` : `${fmt(d.rain_mm, 1)} mm`],
      [t("clim_now_et0"), `${fmt(d.et0_mm, 1)} mm`],
    ];
    box.innerHTML = rows.map(([k, v]) => `<div><dt>${esc(k)}:</dt><dd>${esc(v)}</dd></div>`).join("");
    box.title = t("clim_now_src", { src: fc.source, date: isoDay(d.date) });
  }

  // draws the observed/projection boundary and the two value bubbles on the chart
  const climMarks = {
    id: "climMarks",
    afterDatasetsDraw(ch, args, opts) {
      const { ctx, chartArea: area, scales: { x, y } } = ch;
      (opts.marks || []).forEach((m) => {
        const px = x.getPixelForValue(m.x), py = y.getPixelForValue(m.y);
        if (px < area.left - 1 || px > area.right + 1) return;
        ctx.save();
        if (m.line) {
          ctx.setLineDash([4, 4]); ctx.strokeStyle = "rgba(220, 235, 255, .55)"; ctx.lineWidth = 1;
          ctx.beginPath(); ctx.moveTo(px, area.top); ctx.lineTo(px, area.bottom); ctx.stroke(); ctx.setLineDash([]);
        }
        ctx.font = "600 13px Inter, system-ui, sans-serif";
        const w = Math.max(ctx.measureText(m.text).width, ctx.measureText(m.sub).width) + 20, h = 38;
        let bx = Math.min(Math.max(px - w / 2, area.left), area.right - w), by = py - h - 12;
        if (by < area.top - 6) by = py + 12;
        ctx.fillStyle = "rgba(6, 16, 34, .92)"; ctx.strokeStyle = m.color; ctx.lineWidth = 1.2;
        ctx.shadowColor = m.color; ctx.shadowBlur = 10;
        ctx.beginPath(); ctx.roundRect(bx, by, w, h, 8); ctx.fill(); ctx.shadowBlur = 0; ctx.stroke();
        ctx.fillStyle = "#fff"; ctx.textAlign = "center"; ctx.fillText(m.text, bx + w / 2, by + 16);
        ctx.font = "500 10.5px Inter, system-ui, sans-serif"; ctx.fillStyle = "#b9c8db"; ctx.fillText(m.sub, bx + w / 2, by + 30);
        ctx.restore();
      });
    },
  };

  function climChart(id, config) {
    const existing = charts[id];
    if (existing && existing.config.type === config.type) {
      existing.data = config.data;
      existing.options = config.options;
      existing.update(reduceMotion.matches ? "none" : undefined);
      return;
    }
    if (existing) existing.destroy();
    charts[id] = new Chart($(id), Object.assign({ plugins: [climMarks] }, config));
  }

  function renderClimAnnual() {
    if (!window.Chart || !data || !data.climate) return;
    const c = data.climate;
    const key = CLIM_KEYS.includes(state.metric) && c.shift[state.metric] ? state.metric : "t_mean";
    const sh = c.shift[key], dg = CLIM_DIGITS[key] || 0;
    const from = Number(state.climPeriod) || c.annual[0].year;
    const obs = c.annual.filter((a) => a[key] !== null && a.year >= from).map((a) => ({ x: a.year, y: a[key] }));
    if (!obs.length) return;
    const end = obs[obs.length - 1];
    const band = sh.projection ? sh.projection.band : [];
    const proj = band.length ? [{ x: end.x, y: end.y }].concat(band.map((b) => ({ x: b.year, y: b.value }))) : [];
    const pEnd = band.length ? band[band.length - 1] : null;
    $("clim-chart-title").textContent = key === "t_mean" ? t("clim_title_t") : t("clim_title_other", { name: t("k_" + key) });
    $("clim-lg-hist").textContent = t("clim_hist", { a: obs[0].x, b: end.x });
    $("clim-lg-proj").textContent = pEnd ? t("clim_proj", { a: band[0].year, b: pEnd.year }) : t("clim_proj_none");
    const cyanFill = (ctx) => {
      const area = ctx.chart.chartArea;
      if (!area) return "rgba(62, 197, 255, .15)";
      const g = ctx.chart.ctx.createLinearGradient(0, area.top, 0, area.bottom);
      g.addColorStop(0, "rgba(62, 197, 255, .28)"); g.addColorStop(1, "rgba(62, 197, 255, 0)");
      return g;
    };
    const opts = baseOptions();
    // First draw: the history line runs left to right, then the projection and its band follow.
    // Later updates (indicator, period, region) glide from the old values instead.
    const first = !charts["clim-annual"];
    const histCount = obs.length;
    opts.animation = reduceMotion.matches ? false : {
      duration: first ? 420 : 520, easing: "easeOutCubic",
      delay: (ctx) => (first && ctx.type === "data" && ctx.mode === "default"
        ? (ctx.datasetIndex === 0 ? ctx.dataIndex * 14 : histCount * 14 + 120 + ctx.dataIndex * 22) : 0),
    };
    opts.plugins.legend.display = false;
    opts.plugins.tooltip = {
      animation: { duration: 180, easing: "easeOutCubic" },
      filter: (item) => !!item.dataset.label,
      backgroundColor: "rgba(6, 16, 34, .95)", borderColor: "rgba(110, 170, 240, .4)", borderWidth: 1, padding: 10,
      callbacks: {
        title: (items) => String(items[0].parsed.x),
        label: (item) => `${item.dataset.label}: ${withUnit(item.parsed.y, key)}`,
      },
    };
    opts.plugins.climMarks = { marks: [
      { x: end.x, y: end.y, color: "#3ec5ff", text: withUnit(end.y, key), sub: `(${end.x})`, line: true },
      ...(pEnd ? [{ x: pEnd.year, y: pEnd.value, color: "#c084fc", text: withUnit(pEnd.value, key), sub: `(${pEnd.year}, ${t("clim_proj_short")})` }] : []),
    ] };
    opts.layout = { padding: { top: 46, right: 18 } };
    opts.scales.x = Object.assign(opts.scales.x, { type: "linear", min: obs[0].x, max: pEnd ? pEnd.year : end.x,
      grid: { color: "rgba(110, 160, 230, .08)" }, ticks: { color: "#c7d2e1", stepSize: 5, callback: (v) => String(v) } });
    opts.scales.y = Object.assign(opts.scales.y, { grid: { color: "rgba(110, 160, 230, .1)" },
      ticks: { color: "#c7d2e1", callback: (v) => withUnit(v, key) } });
    climChart("clim-annual", { type: "line", data: { datasets: [
      { label: t("clim_hist_short"), data: obs, borderColor: "#3ec5ff", backgroundColor: cyanFill, fill: "start", borderWidth: 2.2,
        pointRadius: 3.2, pointHoverRadius: 6, pointBackgroundColor: "#c9f1ff", pointBorderColor: "#3ec5ff", tension: 0.25 },
      { label: t("clim_proj_short"), data: proj, borderColor: "#c084fc", backgroundColor: "#c084fc", borderWidth: 2.2,
        pointRadius: (ctx) => (ctx.dataIndex === 0 ? 0 : 2.6), pointHoverRadius: 5, pointBackgroundColor: "#ead7ff", tension: 0.2 },
      { label: "", data: band.map((b) => ({ x: b.year, y: b.high })), borderWidth: 0, pointRadius: 0, backgroundColor: "rgba(192, 132, 252, .22)", fill: "+1" },
      { label: "", data: band.map((b) => ({ x: b.year, y: b.low })), borderWidth: 0, pointRadius: 0, fill: false },
    ] }, options: opts });
  }

  function renderClimMonthly() {
    if (!window.Chart || !data.climate) return;
    const m = data.climate.monthly.recent, p = data.periods;
    $("clim-month-years").textContent = t("clim_month_years", { a: p.recent[0], b: p.recent[1] });
    const opts = baseOptions();
    opts.animation = reduceMotion.matches ? false : { duration: 500 };
    opts.plugins.legend.display = false;
    opts.plugins.tooltip = { backgroundColor: "rgba(6, 16, 34, .95)", borderColor: "rgba(110, 170, 240, .4)", borderWidth: 1, padding: 10 };
    opts.scales = {
      x: { grid: { display: false }, ticks: { color: "#c7d2e1" } },
      y: { position: "left", grid: { color: "rgba(110, 160, 230, .1)" }, ticks: { color: "#c7d2e1", callback: (v) => `${v}°` } },
      y1: { position: "right", grid: { display: false }, beginAtZero: true, ticks: { color: "#c7d2e1" } },
    };
    climChart("clim-monthly", { type: "bar", data: { labels: t("months"), datasets: [
      { type: "line", label: t("m_temp"), data: m.t, yAxisID: "y", borderColor: "#3ec5ff", backgroundColor: "#3ec5ff", borderWidth: 2,
        pointRadius: 3, pointBackgroundColor: "#c9f1ff", tension: 0.35, order: 0 },
      { type: "bar", label: t("m_rain"), data: m.rain_mm, yAxisID: "y1", backgroundColor: "rgba(192, 132, 252, .65)",
        borderColor: "rgba(216, 180, 254, .9)", borderWidth: 1, borderRadius: 4, maxBarThickness: 22, order: 1 },
    ] }, options: opts });
  }

  // Dryness: UNEP aridity index P/ET0 and its standard classes (hyper-arid < 0.05 < arid < 0.2 < semi-arid < 0.5
  // < dry sub-humid < 0.65 < humid). The 2040 value is the trend continued; lower means drier, higher risk.
  function renderClimGauge() {
    const sh = data.climate.shift.aridity;
    if (!sh) { $("clim-gauge-class").textContent = "–"; $("clim-gauge-value").textContent = t("no_data_title"); return; }
    const proj = sh.projection && sh.projection.value !== null ? sh.projection : null;
    const value = proj ? proj.value : sh.recent;
    const cls = value < 0.05 ? "hyper" : value < 0.2 ? "arid" : value < 0.5 ? "semi" : value < 0.65 ? "subhumid" : "humid";
    const pos = Math.max(0, Math.min(1, value));
    $("gauge-fill").style.strokeDasharray = `${(pos * 100).toFixed(1)} 100`;
    const th = Math.PI * (1 - pos);
    $("gauge-dot").setAttribute("transform", `translate(${(90 + 90 * Math.cos(th)).toFixed(1)} ${(-90 * Math.sin(th)).toFixed(1)})`);
    $("clim-gauge-class").textContent = t("ai_" + cls);
    $("clim-gauge-value").textContent = `${fmt(value, 2)} / 1.00`;
    $("clim-gauge-sub").textContent = t("clim_gauge_sub", { y: proj ? proj.year : data.periods.recent[1] });
    $("clim-gauge").dataset.level = cls;
    $("clim-gauge").title = t("clim_gauge_note", { now: fmt(sh.recent, 2) });
  }

  function renderClimFindings() {
    const c = data.climate;
    $("clim-findings").innerHTML = ["t_mean", "precip_mm", "et0_mm", "hot_days"].filter((k) => c.shift[k]).map((k) => {
      const sh = c.shift[k], d = sh.delta;
      const key = Math.abs(d) < (k === "t_mean" ? 0.05 : 1) ? "clim_f_flat" : d > 0 ? "clim_f_up" : "clim_f_down";
      return `<li class="${sh.trend_significant ? "is-sure" : "is-weak"}" title="${esc(t(sh.trend_significant ? "sig_yes" : "sig_no"))}">
        <span class="f-mark" aria-hidden="true">${sh.trend_significant ? icon("i-check") : "≈"}</span>
        <span>${esc(t(key, { name: t("k_" + k), d: withUnit(d, k, true) }))}</span></li>`;
    }).join("");
  }

  // A short rule-based recommendation built only from the shifts on this page; the reasons are listed under it.
  function renderClimAdvice() {
    const c = data.climate, p = data.periods, sh = (k) => c.shift[k] && c.shift[k].delta;
    const recs = [], why = [];
    const et0 = sh("et0_mm"), rain = sh("precip_mm"), hot = sh("hot_days"), frost = sh("frost_days"), dry = sh("dry_spell_days");
    if (et0 > 0 && (rain === null || rain === undefined || rain < et0)) { recs.push("rec_water"); why.push(`ET0 ${withUnit(et0, "et0_mm", true)}`, `${t("k_precip_mm")} ${withUnit(rain || 0, "precip_mm", true)}`); }
    if (hot >= 3) { recs.push("rec_heat"); why.push(`${t("clim_hot")} ${withUnit(hot, "hot_days", true)}`); }
    if (dry >= 5) { recs.push("rec_drought"); why.push(`${t("k_dry_spell_days")} ${withUnit(dry, "dry_spell_days", true)}`); }
    if (frost <= -3) { recs.push("rec_frost"); why.push(`${t("clim_cold")} ${withUnit(frost, "frost_days", true)}`); }
    if (!recs.length) recs.push("rec_stable");
    $("clim-advice-text").textContent = recs.slice(0, 2).map((k) => t(k)).join(" ");
    $("clim-advice-why").textContent = why.length
      ? t("rec_why", { list: why.join(", "), b0: p.baseline[0], b1: p.baseline[1], r0: p.recent[0], r1: p.recent[1] }) : "";
    $("advice-climate").innerHTML = recs.map((k) => `<li class="tip"><span class="ico" aria-hidden="true">✓</span><span>${esc(t(k))}</span></li>`).join("") +
      (data.advice || []).filter((a) => a.group === "climate" || a.group === "crops")
        .map((a) => `<li class="${esc(a.severity)}"><span class="ico" aria-hidden="true">${ICON[a.severity] || "i"}</span><span>${esc(a.text)}</span></li>`).join("");
  }

  // ---------- analysis modes ----------
  // Automatic: quick settings, applied at once. Manual: the user describes the field and the crop plan,
  // then "Calculate" runs the same /api/analyze engine with those inputs (their plan joins the comparison).
  function renderManualForm() {
    if (!$("manual-form") || !options) return;
    const m = Object.assign({ soil: state.soil, irrigation: state.irrigation, prev: "", crop: "cotton", next: "", period: state.period }, state.manual || {});
    const crops = (empty) => (empty ? `<option value="">${esc(t("mf_none"))}</option>` : "") +
      options.crops.map((c) => `<option value="${esc(c.id)}">${esc(name(c))}</option>`).join("");
    $("mf-soil").innerHTML = $("soil").innerHTML;
    $("mf-irrigation").innerHTML = $("irrigation").innerHTML;
    $("mf-prev").innerHTML = crops(true);
    $("mf-crop").innerHTML = crops(false);
    $("mf-next").innerHTML = crops(true);
    if ($("period")) $("mf-period").innerHTML = $("period").innerHTML;
    $("mf-soil").value = m.soil; $("mf-irrigation").value = m.irrigation;
    $("mf-prev").value = m.prev; $("mf-crop").value = m.crop; $("mf-next").value = m.next;
    $("mf-period").value = m.period || "";
    $("mf-name").value = state.field.name || "";
    renderManualWeights();
    renderMode();
  }
  function renderManualWeights() {
    if (!$("mf-weights")) return;
    const w = state.weights, sum = Object.values(w).reduce((a, b) => a + b, 0) || 1;
    $("mf-weights").textContent = ["water", "income", "soil", "risk"].map((k) => `${t("s_" + k)} ${Math.round(100 * w[k] / sum)}%`).join(" · ");
  }
  function renderMode() {
    const manual = state.mode === "manual";
    document.querySelectorAll("[data-mode]").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.mode === state.mode)));
    if ($("mode-auto")) $("mode-auto").hidden = manual;
    if ($("manual-form")) $("manual-form").hidden = !manual;
    if ($("mode-note")) $("mode-note").textContent = t(manual ? "mode_manual_note" : "mode_auto_note");
    const root = document.querySelector(".dash");
    if (root) root.dataset.mode = state.mode;
  }
  function setMode(mode) {
    if (mode === state.mode) return;
    state.mode = mode;
    save();
    renderMode();
    document.dispatchEvent(new CustomEvent("mode:change", { detail: { mode } }));
    // Back to automatic: the user's manual crop plan stops being "current", the standard rotation returns.
    if (mode === "auto" && state.current === "custom" && state.manual) {
      state.current = state.autoCurrent || null;
      if ($("current")) $("current").value = state.current || options.default_current;
      renderBuilder();
      requestMode = "auto";
      analyze();
    }
  }
  function runManual() {
    const get = (id) => $(id).value;
    const m = { soil: get("mf-soil"), irrigation: get("mf-irrigation"), prev: get("mf-prev"), crop: get("mf-crop"), next: get("mf-next"), period: get("mf-period") };
    const error = !m.crop ? t("mf_err_crop") : !options.irrigation.some((x) => x.id === m.irrigation) ? t("mf_err_irrigation") : "";
    $("mf-error").hidden = !error;
    $("mf-error").textContent = error;
    if (error) return;
    if (state.current !== "custom") state.autoCurrent = state.current;
    state.manual = m;
    state.soil = m.soil; state.irrigation = m.irrigation; state.period = m.period;
    state.current = "custom";
    state.customYears = [m.prev, m.crop, m.next].filter(Boolean).map((c) => [c, ""]);
    state.field.name = $("mf-name").value.trim();
    ["soil", "irrigation", "period"].forEach((id) => { if ($(id)) $(id).value = state[id]; });
    if ($("current")) $("current").value = "custom";
    renderBuilder();
    requestMode = "manual";
    analyze();
    document.dispatchEvent(new CustomEvent("manual:run"));
  }

  function renderWeights() {
    renderManualWeights();
    if (!$("sliders")) return;
    const sum = Object.values(state.weights).reduce((a, b) => a + b, 0) || 1;
    for (const k in state.weights) $("o-" + k).textContent = Math.round(100 * state.weights[k] / sum) + "%";
  }

  function renderBuilder() {
    if (!$("builder-years")) return;
    $("builder").hidden = $("current").value !== "custom";
    const opts = (sel, empty) => (empty ? `<option value="">${esc(t("second_crop"))}</option>` : "") +
      options.crops.map((c) => `<option value="${esc(c.id)}"${c.id === sel ? " selected" : ""}>${esc(name(c))}</option>`).join("");
    $("builder-years").innerHTML = state.customYears.map((y, i) => `
      <div class="year"><span>${esc(t("year_n", { n: i + 1 }))}</span>
        <select data-y="${i}" data-s="0" aria-label="${esc(t("year_n", { n: i + 1 }))}">${opts(y[0], false)}</select>
        <select data-y="${i}" data-s="1" aria-label="${esc(t("second_crop"))}">${opts(y[1], true)}</select>
      </div>`).join("");
  }

  // ---------- rendering ----------
  const alertHtml = (severity, text) => `<div class="alert ${esc(severity)}"><span class="ico" aria-hidden="true">${ICON[severity] || "i"}</span><span>${esc(text)}</span></div>`;
  const adviceHtml = (group) => (data.advice || []).filter((a) => a.group === group)
    .map((a) => `<li class="${esc(a.severity)}"><span class="ico" aria-hidden="true">${ICON[a.severity] || "i"}</span><span>${esc(a.text)}</span></li>`).join("");

  function render() {
    if ($("coords")) $("coords").textContent = `${state.lat.toFixed(4)}, ${state.lon.toFixed(4)}`;
    if ($("warnings")) $("warnings").innerHTML = data.warnings.map((w) => alertHtml(w.severity, w.text)).join("");
    renderChips();
    if ($("layer") && JSON.stringify(data.map_layers.map((l) => l.id)) !== JSON.stringify(layers.map((l) => l.id))) {
      layers = data.map_layers; renderLayerSelect();
    }
    renderSoilNote();
    const ok = !!(data.rotations && data.rotations.items && data.rotations.items.length
      && data.rotations.items.some((it) => it.id === data.rotations.best_id));
    if (!ok) {
      if ($("verdict")) $("verdict").textContent = t("no_data_title");
      if ($("verdict-sub")) $("verdict-sub").textContent = t("no_data_sub");
      if ($("advice-top")) $("advice-top").innerHTML = "";
    } else if ($("verdict") || $("verdict-sub") || $("advice-top")) renderVerdict();
    if ($("rot-list")) renderDashboard(ok);
    if ($("clim-annual")) renderClimatePage();
    if ($("crop-table")) renderCropsPage();
    if (ok) {
      if ($("rotations")) renderRotations();
      if ($("now-card")) renderNow();
    }
    if ($("datasets")) renderSources();
  }

  function renderChips() {
    if (!$("chips")) return;
    const cls = { ok: "ok", live: "ok", cache: "ok", monthly: "warn", fallback: "warn", disabled: "warn", failed: "bad", down: "bad" };
    const filter = $("chips").dataset.filter;
    if (filter) {
      const ids = filter === "nasa" ? null : filter.split(",");
      $("chips").innerHTML = data.providers.filter((p) => (ids ? ids.includes(p.id) : p.nasa)).map((p) =>
        `<a class="dash-pill" href="/sources.html" data-provider="${esc(p.id)}" data-state="${data.demo ? "demo" : cls[p.status] || ""}" title="${esc(data.demo ? t("demo_note") : t("st_" + p.status))}${!data.demo && p.message ? " · " + esc(p.message) : ""}"><span class="dot" aria-hidden="true"></span>${esc(p.name)}<span class="sr-only"> · ${esc(data.demo ? t("demo_badge") : t("st_" + p.status))}</span></a>`).join("");
      return;
    }
    $("chips").innerHTML = data.providers.map((p) =>
      `<span class="chip" title="${esc(p.message || "")}"><span class="dot ${cls[p.status] || ""}"></span>${esc(p.name)} · ${esc(t("st_" + p.status))}</span>`).join("");
  }

  function renderSoilNote() {
    if (!$("soil-note")) return;
    const d = data.soil.details, kind = data.coverage.soil;
    $("soil-note").textContent = kind === "measured" && d
      ? t("soil_measured", { clay: fmt(d.clay_pct), sand: fmt(d.sand_pct), soc: d.organic_carbon_g_kg ?? "–", ph: d.ph ?? "–" }) + " → " + name(data.soil)
      : kind === "default" ? t("soil_default") : t("soil_chosen", { awc: data.soil.awc_mm_per_m });
  }

  function methodName() {
    const m = options.irrigation.find((x) => x.id === data.rotations.irrigation_method);
    return name(m);
  }

  function renderVerdict() {
    const r = data.rotations;
    const best = r.items.find((it) => it.id === r.best_id);
    const verdictKey = best.is_current ? "verdict_keep" : "verdict_best";
    if ($("verdict") && "rich" in $("verdict").dataset) {
      const parts = name(best).split(/\s+-\s+/);
      const last = parts.pop();
      const [pre, post = ""] = t(verdictKey, { name: "\u0000" }).split("\u0000");
      $("verdict").innerHTML = `${esc(pre)}${esc(parts.length ? parts.join(" – ") + " – " : "")}<span class="dash-accent">${esc(last)}</span>${esc(post)}`;
    } else if ($("verdict")) $("verdict").textContent = t(verdictKey, { name: name(best) });
    if ($("verdict-sub")) $("verdict-sub").textContent = t("verdict_sub", {
      n: r.items.length, y0: r.period[0], y1: r.period[1], soil: name(data.soil), method: methodName(),
    });
    if ($("advice-top")) $("advice-top").innerHTML = adviceHtml("rotation");
  }

  // One horizontal bar on a shared scale: shaded p10-p90 range plus a mark at the median.
  function rangeBar(sp, max, single) {
    const pct = (v) => Math.max(0, Math.min(100, 100 * v / (max || 1)));
    if (single !== undefined) return `<div class="track thin"><div class="mark" style="left:${pct(single)}%"></div></div>`;
    return `<div class="track thin"><div class="range" style="left:${pct(sp.p10)}%;width:${Math.max(pct(sp.p90) - pct(sp.p10), 1)}%"></div><div class="mark" style="left:${pct(sp.p50)}%"></div></div>`;
  }

  const rangeMax = (r) => {
    const maxOf = (key) => Math.max(...r.items.map((it) => it[key].p90)) * 1.05;
    return { water: maxOf("water_m3_ha"), income: maxOf("income_usd_ha") };
  };

  // Score range, the four criteria with their good-to-hard-year ranges, wins and the change against the current rotation.
  function rotationDetail(it, r, max) {
    const s = it.scores, tr = s.total_range, vs = it.vs_current;
    const mWater = max.water, mIncome = max.income;
    const crit = (label, unit, value, sp, bar, hint) => `
        <div><div class="lbl"><span>${esc(label)}</span><span class="val">${value} <span class="rng">${esc(unit)}</span></span></div>
        ${bar}<div class="rng">${esc(hint)}</div></div>`;
    const good = (v, lowerBetter) => (v === 0 ? "" : (v < 0) === lowerBetter ? "delta-good" : "delta-bad");
    const foot = vs ? `<span>${esc(t("vs_current", { water: "§w", pct: "§p", income: "§i", soil: "§s", risk: "§r" }))
      .replace("§w", `<b class="${good(-vs.water_m3_ha, true)}">${sgn(-vs.water_m3_ha)}</b>`)
      .replace("§p", sgn(-(vs.water_pct ?? 0)))
      .replace("§i", `<b class="${good(vs.income_usd_ha, false)}">${sgn(vs.income_usd_ha)}</b>`)
      .replace("§s", `<b class="${good(vs.soil, false)}">${sgn(vs.soil)}</b>`)
      .replace("§r", `<b class="${good(vs.risk_pct, true)}">${sgn(vs.risk_pct)}</b>`)}</span>` : "";
    return `
        <div class="track" title="${esc(t("range", { a: fmt(tr.p10, 1), b: fmt(tr.p90, 1) }))}">
          <div class="range" style="left:${tr.p10}%;width:${Math.max(tr.p90 - tr.p10, 1)}%"></div><div class="mark" style="left:${s.total}%"></div>
        </div>
        <div class="crit">
          ${crit(t("c_water"), t("u_water"), fmt(it.water_m3_ha.p50), it.water_m3_ha, rangeBar(it.water_m3_ha, mWater), t("range", { a: fmt(it.water_m3_ha.p10), b: fmt(it.water_m3_ha.p90) }))}
          ${crit(t("c_income"), t("u_income"), fmt(it.income_usd_ha.p50), it.income_usd_ha, rangeBar(it.income_usd_ha, mIncome), t("range", { a: fmt(it.income_usd_ha.p10), b: fmt(it.income_usd_ha.p90) }))}
          ${crit(t("c_risk"), t("u_risk"), fmt(it.risk_pct.p50), it.risk_pct, rangeBar(it.risk_pct, 100), t("range", { a: fmt(it.risk_pct.p10), b: fmt(it.risk_pct.p90) }))}
          ${crit(t("c_soil"), t("u_soil"), fmt(it.soil.index), null, rangeBar(null, 100, it.soil.index), t("soil_parts", it.soil.parts))}
        </div>
        <div class="rot-foot"><span>${esc(t("wins", { wins: it.wins, n: r.years_replayed }))}</span>${foot}</div>`;
  }

  function renderRotations() {
    const r = data.rotations;
    $("rotations-meta").textContent = t("rotations_meta", { n: r.years_replayed, method: methodName() });
    const max = rangeMax(r);
    $("rotations").innerHTML = r.items.map((it) => {
      const s = it.scores;
      const badges = [
        it.id === r.best_id ? `<span class="badge best">${esc(t("badge_best"))}</span>` : "",
        it.is_current ? `<span class="badge">${esc(t("badge_current"))}</span>` : "",
        it.conflicts.length ? `<span class="badge bad">${esc(t("badge_conflict"))}</span>` : "",
      ].join("");
      const seq = it.years.map((slot, i) => `<span><b>${esc(t("year_n", { n: i + 1 }))}:</b> ${slot.map((c) => esc(name(c))).join(" + ")}</span>`).join("");
      return `
      <article class="rot${it.id === r.best_id ? " best" : ""}">
        <div class="rot-head">
          <div class="rot-title"><span class="rank">#${it.rank}</span><span class="rot-name">${esc(name(it))}</span>${badges}</div>
          <div class="score">${fmt(s.total, 1)} <small>${esc(t("score_of"))}</small></div>
        </div>
        <div class="seq">${seq}</div>${rotationDetail(it, r, max)}
      </article>`;
    }).join("");
  }

  // ---------- field dashboard ----------
  const CROP_ICON = { cotton: "i-cotton", winter_wheat: "i-wheat", sorghum: "i-wheat" };
  const CROP_TONE = { cotton: "cotton", winter_wheat: "wheat", sorghum: "sorghum" };
  const dashName = (obj) => name(obj).replace(/\s+-\s+/g, " – ");
  const icon = (id, cls = "") => `<svg class="${cls}" aria-hidden="true"><use href="#${id}"/></svg>`;

  function cropChips(it) {
    const groups = [];
    it.years.forEach((slot, i) => {
      const label = slot.map((c) => name(c)).join(" + ");
      const last = groups[groups.length - 1];
      if (last && last.label === label) last.b = i + 1;
      else groups.push({ label, id: slot[0] && slot[0].id, a: i + 1, b: i + 1 });
    });
    return groups.map((g) => {
      const year = g.a === g.b ? t("year_n", { n: g.a }) : t("year_range", { a: g.a, b: g.b });
      return `<span class="crop crop-${CROP_TONE[g.id] || "legume"}">${icon(CROP_ICON[g.id] || "i-sprout")}${esc(year)}: ${esc(g.label)}</span>`;
    }).join("");
  }

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  // Writes a metric. With a number it counts from the previous value; "–" marks a value that is not available.
  function setMetric(id, text, tone, value, format) {
    const el = $(id);
    if (!el) return;
    if (tone) el.dataset.tone = tone; else delete el.dataset.tone;
    el.classList.toggle("is-empty", text === "–");
    const from = Number(el.dataset.value);
    cancelAnimationFrame(el._count || 0);
    if (typeof value !== "number" || !Number.isFinite(value) || !Number.isFinite(from) || reduceMotion.matches || from === value) {
      el.textContent = text;
      el.dataset.value = typeof value === "number" ? String(value) : "";
      return;
    }
    el.dataset.value = String(value);
    const started = performance.now(), duration = 550;
    const step = (now) => {
      const k = Math.min(1, (now - started) / duration), e = 1 - Math.pow(1 - k, 3);
      el.textContent = k < 1 ? format(from + (value - from) * e) : text;
      if (k < 1) el._count = requestAnimationFrame(step);
    };
    el._count = requestAnimationFrame(step);
  }

  // Dashboard state on the root: loading (first request), updating, ready, error, demo.
  let loadingShownAt = 0, loadingTimer = 0, loadingHideTimer = 0;
  function dashState(name, mode) {
    const root = document.querySelector(".dash");
    if (!root) return;
    const busy = name === "loading" || name === "updating";
    const box = $("dash-loading");
    clearTimeout(loadingTimer);
    clearTimeout(loadingHideTimer);
    if (busy) {
      if (box) box.querySelector("[data-t]").textContent = t(name === "loading" ? "loading_dash" : mode === "manual" ? "loading_manual" : "loading_update");
      // Short requests never show a spinner; a shown one stays long enough to be read, so nothing blinks.
      loadingTimer = setTimeout(() => { root.dataset.state = name; if (box) box.hidden = false; loadingShownAt = performance.now(); }, name === "loading" ? 0 : 150);
    } else {
      const left = loadingShownAt ? Math.max(0, 450 - (performance.now() - loadingShownAt)) : 0;
      const finish = () => { root.dataset.state = name; if (box) box.hidden = true; loadingShownAt = 0; };
      if (left) loadingHideTimer = setTimeout(finish, left); else finish();
    }
    if (name !== "error" && $("dash-banner")) $("dash-banner").hidden = true;
  }

  // A failed request never leaves an empty dashboard without a reason and a way out.
  function dashError(err) {
    dashState("error");
    const msg = esc(t("error", { msg: err.message || String(err) }));
    const actions = `<div class="dash-error-actions">
        <button type="button" class="dash-btn dash-btn-primary" data-retry>${esc(t("err_retry"))}</button>
        <button type="button" class="dash-btn dash-btn-secondary" data-demo>${esc(t("demo_btn"))}</button></div>`;
    if (!data && $("crop-rows")) {
      $("crop-rows").innerHTML = `<div class="dash-error" role="alert"><b>${esc(t("err_title"))}</b><p>${msg}</p>${actions}</div>`;
      $("crop-best").innerHTML = "";
      $("crop-findings").innerHTML = `<li class="is-empty">${esc(t("err_sub"))}</li>`;
    } else if ((!data || data.demo) && $("rot-list")) {
      $("rot-list").innerHTML = `<div class="dash-error" role="alert"><b>${esc(t("err_title"))}</b><p>${msg}</p>${actions}</div>`;
      if (!data) {
        ["m-total", "m-water", "m-soil-gain", "m-income", "m-soil"].forEach((id) => setMetric(id, "–"));
        if ($("verdict")) $("verdict").textContent = t("err_title");
        if ($("verdict-sub")) $("verdict-sub").textContent = t("err_sub");
      }
    } else if ($("dash-banner")) {
      $("dash-banner").innerHTML = `<span>${msg} ${esc(t("err_kept"))}</span>${actions}`;
      $("dash-banner").hidden = false;
    }
  }

  // DEMO: a saved sample answer of this same API (Jizzakh), shown with a DEMO label; never presented as live data.
  async function loadDemo() {
    try {
      const sample = await api(`/demo/analysis-${state.lang === "uz" ? "uz" : "en"}.json`);
      if (!options) options = await api("/demo/options.json");
      if (options && (!$("irrigation") || !$("irrigation").options.length)) renderForms();
      data = Object.assign(sample, { demo: true });
      render();
      dashState("demo");
    } catch (err) {
      dashError(err);
    }
  }

  function renderDashboard(ok) {
    renderFieldFacts();
    document.querySelector(".dash").classList.toggle("is-manual-result", data.mode === "manual");
    document.querySelector(".dash").classList.toggle("is-demo", !!data.demo);
    if ($("dash-demo")) $("dash-demo").hidden = !data.demo;
    if (!ok) {
      $("rot-list").innerHTML = `<div class="dash-error" role="status"><b>${esc(t("no_data_title"))}</b><p>${esc(t("no_data_sub"))}</p>
        <div class="dash-error-actions"><button type="button" class="dash-btn dash-btn-primary" data-retry>${esc(t("err_retry"))}</button>
        <button type="button" class="dash-btn dash-btn-secondary" data-demo>${esc(t("demo_btn"))}</button></div></div>`;
      ["m-total", "m-water", "m-soil-gain", "m-income", "m-soil"].forEach((id) => setMetric(id, "–"));
      document.dispatchEvent(new CustomEvent("dash:render"));
      return;
    }
    const r = data.rotations;
    const best = r.items.find((it) => it.id === r.best_id);
    const current = r.items.find((it) => it.is_current);
    const vs = best.vs_current;
    if ($("period") && r.period) $("period").title = t("period_actual", { a: r.period[0], b: r.period[1], n: r.years_replayed });
    $("rotations-meta").textContent = t("rotations_meta", { n: r.years_replayed, method: methodName() });

    const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
    const total = num(best.scores && best.scores.total), soil = num(best.soil && best.soil.index);
    setMetric("m-total", total === null ? "–" : fmt(total, 1), null, total, (v) => fmt(v, 1));
    setMetric("m-soil", soil === null ? "–" : fmt(soil), null, soil, (v) => fmt(v));
    if (vs && current) {
      const water = num(vs.water_pct), soilGain = num(vs.soil);
      const base = num(current.income_usd_ha && current.income_usd_ha.p50), gain = num(vs.income_usd_ha);
      const income = base && gain !== null ? Math.round(100 * gain / base) : null;
      setMetric("m-water", water === null ? "–" : `${sgn(-water)}%`, water === null ? null : water >= 0 ? "good" : "bad", water === null ? null : -water, (v) => `${sgn(Math.round(v))}%`);
      setMetric("m-soil-gain", soilGain === null ? "–" : `${sgn(soilGain)} ${t("m_points")}`, soilGain === null ? null : soilGain >= 0 ? "good" : "bad", soilGain, (v) => `${sgn(Math.round(v))} ${t("m_points")}`);
      setMetric("m-income", income === null ? "–" : `${sgn(income)}%`, income === null ? null : income >= 0 ? "good" : "bad", income, (v) => `${sgn(Math.round(v))}%`);
      $("metrics").title = t("m_vs_current", { name: name(current) });
    } else {
      ["m-water", "m-soil-gain", "m-income"].forEach((id) => setMetric(id, "0", null, 0, (v) => fmt(v)));
      $("metrics").title = t("m_is_current");
    }

    renderFieldTotal(best);
    const max = rangeMax(r);
    const html = r.items.map((it, i) => {
      const isBest = it.id === r.best_id;
      const tags = [
        isBest ? `<span class="tag tag-best">${esc(t("badge_best"))}</span>` : "",
        it.is_current ? `<span class="tag tag-current">${esc(t("badge_current"))}</span>` : "",
        it.conflicts.length ? `<span class="tag tag-bad">${esc(t("badge_conflict"))}</span>` : "",
      ].join("");
      return `
      <article class="rot-row${isBest ? " is-best" : ""}" data-rot="${esc(it.id)}" style="--i: ${i}">
        <div class="rot-main">
          <span class="rot-rank">${isBest ? `<span class="rank-orb">#${it.rank}</span>` : `#${it.rank}`}</span>
          <div class="rot-id">
            <h3 class="rot-title"><span>${esc(dashName(it))}</span>${tags}</h3>
            <div class="rot-crops">${cropChips(it)}</div>
          </div>
          <div class="rot-stat">${icon("i-drop", "ico-blue")}<span><b>${fmt(it.water_m3_ha.p50)}</b><small>${esc(t("u_water_short"))}</small></span></div>
          <div class="rot-stat">${icon("i-layers", "ico-violet")}<span><b>${fmt(it.income_usd_ha.p50)}</b><small>${esc(t("u_income_short"))}</small></span></div>
          <div class="rot-stat">${icon("i-risk", "ico-blue")}<span><b>${fmt(it.risk_pct.p50)}%</b><small>${esc(t("risk_short"))}</small></span></div>
          <div class="rot-stat">${icon("i-shield", "ico-green")}<span><b>${fmt(it.soil.index)}/100</b><small>${esc(t("soil_short"))}</small></span></div>
          <div class="rot-score"><b>${fmt(it.scores.total, 1)}</b><small>/100</small></div>
          <button type="button" class="rot-go" aria-expanded="false" aria-controls="rot-d-${esc(it.id)}" aria-label="${esc(t("row_details", { name: name(it) }))}">${icon("i-arrow")}</button>
        </div>
        <div class="rot-detail" id="rot-d-${esc(it.id)}" hidden><div class="rot-detail-in">${rotationDetail(it, r, max)}</div></div>
      </article>`;
    }).join("");
    updateRows(html);

    renderScoresChart(r);
    renderTrend();
    renderNews();
    renderBasis(best);
    document.dispatchEvent(new CustomEvent("dash:render"));
  }

  // Rows are kept and updated in place (no rebuild, no flash). If the ranking changes they glide to their new place.
  function updateRows(html) {
    const list = $("rot-list");
    const tpl = document.createElement("div");
    tpl.innerHTML = html;
    const fresh = [...tpl.children];
    const old = new Map([...list.querySelectorAll(".rot-row[data-rot]")].map((n) => [n.dataset.rot, n]));
    if (!old.size) { list.replaceChildren(...fresh); return; }
    const before = new Map([...old].map(([id, n]) => [id, n.getBoundingClientRect().top]));
    const same = (a, b) => a && b && a.innerHTML === b.innerHTML;
    const swap = (a, b) => {
      if (!a || !b || same(a, b)) return;
      a.innerHTML = b.innerHTML;
      a.classList.remove("is-changed");
      void a.offsetWidth;
      a.classList.add("is-changed");
    };
    const nodes = fresh.map((f) => {
      const n = old.get(f.dataset.rot);
      if (!n) { f.classList.add("is-enter"); return f; }
      const open = n.classList.contains("is-open");
      n.className = f.className + (open ? " is-open" : "");
      n.style.cssText = f.style.cssText;
      [".rot-rank", ".rot-title", ".rot-crops", ".rot-score"].forEach((sel) => swap(n.querySelector(sel), f.querySelector(sel)));
      const a = n.querySelectorAll(".rot-stat"), b = f.querySelectorAll(".rot-stat");
      a.forEach((el, i) => swap(el, b[i]));
      n.querySelector(".rot-detail-in").innerHTML = f.querySelector(".rot-detail-in").innerHTML;
      n.querySelector(".rot-go").setAttribute("aria-label", f.querySelector(".rot-go").getAttribute("aria-label"));
      return n;
    });
    list.replaceChildren(...nodes);
    if (reduceMotion.matches) return;
    nodes.forEach((n) => {
      const top = before.get(n.dataset.rot);
      if (top === undefined) return;
      const dy = top - n.getBoundingClientRect().top;
      if (Math.abs(dy) > 1) n.animate([{ transform: `translateY(${dy}px)` }, { transform: "none" }], { duration: 480, easing: "cubic-bezier(.22, 1, .36, 1)" });
    });
  }

  // With a drawn field, the per-hectare result becomes a whole-field estimate.
  function renderFieldTotal(best) {
    const el = $("field-total");
    if (!el) return;
    const ha = state.field.area_ha;
    el.hidden = !ha;
    if (!ha) return;
    el.innerHTML = t("field_total", {
      ha: `<b>${esc(fmtHa(ha))}</b>`,
      water: `<b>${fmt(Math.round(best.water_m3_ha.p50 * ha / 10) * 10)} m³</b>`,
      income: `<b>$${fmt(Math.round(best.income_usd_ha.p50 * ha / 10) * 10)}</b>`,
    });
  }

  // ---------- agricultural updates ----------
  // No external news provider is connected, so the feed is built from this analysis only:
  // each card names the data source and date it came from. Nothing here is invented headline news.
  let newsKeys = null;
  function renderNews() {
    const list = $("news-list");
    if (!list) return;
    const items = [];
    const day = (iso) => (iso ? isoDay(String(iso).slice(0, 10)) : "");
    const fetched = data.data_fetched_at ? String(data.data_fetched_at).slice(0, 10) : "";
    const n = data.now || {}, rec = n.recent, fc = n.forecast, look = n.outlook;
    const sourceTag = data.demo ? t("demo_badge") : null;
    if (fc) {
      items.push({ key: `rain|${fc.next_rain_date}|${fc.next_rain_mm}`, cat: "weather", icon: "i-cloud", href: "/current.html", source: fc.source, date: new Date().toISOString().slice(0, 10),
        title: t("nw_rain_title"),
        text: fc.next_rain_date ? t("nw_rain_next", { date: isoDay(fc.next_rain_date), mm: fmt(fc.next_rain_mm, 1) }) : t("nw_rain_none", { n: fc.horizon_days }) });
    } else if (look) {
      items.push({ key: `usual|${look.days_to_rain.p50}`, cat: "weather", icon: "i-cloud", href: "/current.html", source: "NASA POWER", date: fetched,
        title: t("nw_rain_title"), text: t("nw_rain_usual", { n: look.days_to_rain.p50, pct: Math.round(look.rain_within_7d_probability * 100) }) });
    }
    if (rec) {
      items.push({ key: `bal|${rec.as_of}|${rec.rain_mm}|${rec.balance_mm}`, cat: "moisture", icon: "i-drop", href: "/current.html", source: "NASA POWER", date: rec.as_of,
        title: t("nw_balance_title"),
        text: t("nw_balance", { rain: fmt(rec.rain_mm, 1), et0: fmt(rec.et0_mm), bal: sgn(rec.balance_mm), days: rec.days_since_rain ?? "–" }) });
    }
    (n.week || []).filter((w) => w.m3_ha > 0).slice(0, 2).forEach((w) => {
      items.push({ key: `week|${w.id}|${w.m3_ha}`, cat: "irrigation", icon: "i-drop", href: "/current.html", source: "NASA POWER · FAO-56", date: fetched,
        title: t("nw_week_title", { crop: name(w) }), text: t("nw_week", { crop: name(w), need: fmt(w.need_mm, 1), m3: fmt(w.m3_ha) }) });
    });
    const shift = data.climate && data.climate.shift;
    if (shift && shift.t_mean && data.periods) {
      const p = data.periods;
      items.push({ key: `clim|${shift.t_mean.delta}|${shift.hot_days ? shift.hot_days.delta : ""}`, cat: "climate", icon: "i-trend", href: "/climate.html", source: "NASA POWER", date: fetched,
        title: t("nw_climate_title"),
        text: t("nw_climate", { d: sgn(shift.t_mean.delta, 1), b0: p.baseline[0], b1: p.baseline[1], r0: p.recent[0], r1: p.recent[1],
          hot: shift.hot_days ? sgn(shift.hot_days.delta) : "–" }) });
    }
    (data.advice || []).filter((a) => a.severity === "warning" || a.severity === "critical").slice(0, 3).forEach((a, i) => {
      items.push({ key: `adv|${a.group}|${a.severity}|${i}`, cat: a.severity === "critical" ? "alert" : "advice", icon: "i-bell", source: t("nw_model"), date: fetched,
        href: { climate: "/climate.html", crops: "/crops.html", rotation: "/rotations.html", now: "/current.html" }[a.group] || "/sources.html",
        title: t(a.severity === "critical" ? "nw_alert_title" : "nw_advice_title"), text: a.text });
    });
    (data.warnings || []).filter((w) => w.severity !== "info").slice(0, 2).forEach((w, i) => {
      items.push({ key: `warn|${w.provider || ""}|${w.severity}|${i}`, cat: "data", icon: "i-info", href: "/sources.html", source: t("nw_status"), date: new Date().toISOString().slice(0, 10),
        title: t("nw_data_title"), text: w.text });
    });

    const keyOf = (it) => `${it.cat}|${it.key}`;            /* language-independent: a translation is not news */
    const keys = new Set(items.map(keyOf));
    const fresh = newsKeys ? items.filter((it) => !newsKeys.has(keyOf(it))) : [];
    const freshKeys = new Set(fresh.map(keyOf));
    const existing = new Map([...list.children].map((li) => [li.dataset.key, li]));
    const nodes = items.map((it, i) => {
      const key = keyOf(it);
      const li = existing.get(key) || document.createElement("li");
      const known = existing.has(key);
      if (!known) li.className = `news-card news-${it.cat}` + (freshKeys.has(key) ? " is-new" : "");
      li.dataset.key = key;
      li.style.setProperty("--i", i);
      li.innerHTML = `
        <div class="news-top"><span class="news-cat">${icon(it.icon)}${esc(t("nwc_" + it.cat))}</span>${li.classList.contains("is-new") && !li.classList.contains("is-seen") ? `<span class="news-flag">${esc(t("news_flag"))}</span>` : ""}</div>
        <h3 class="news-title">${esc(it.title)}</h3>
        <p class="news-text">${esc(it.text)}</p>
        <div class="news-meta"><span>${esc(sourceTag ? `${sourceTag} · ${it.source}` : it.source)}</span>${it.date ? `<time datetime="${esc(it.date)}">${esc(day(it.date))}</time>` : ""}</div>
        <a class="news-more" href="${esc(it.href)}">${esc(t("news_more"))}${icon("i-arrow")}</a>`;
      return li;
    });
    list.replaceChildren(...nodes);
    if (!items.length) list.innerHTML = `<li class="news-empty">${esc(t("news_empty"))}</li>`;
    newsKeys = keys;
    document.dispatchEvent(new CustomEvent("news:update", { detail: { fresh: fresh.length } }));
  }

  // ---------- what the result rests on ----------
  function renderBasis(best) {
    if (!$("basis-inputs")) return;
    const r = data.rotations, f = state.field;
    const tag = (kind) => `<span class="kind kind-${kind}">${esc(t("kind_" + kind))}</span>`;
    const row = (label, value, kind) => `<li><span class="basis-label">${esc(label)}</span><span class="basis-value">${value}</span>${tag(data.demo ? "demo" : kind)}</li>`;
    const soilKind = { measured: "measured", chosen: "user", default: "assumed" }[data.coverage.soil] || "assumed";
    const method = options.irrigation.find((x) => x.id === r.irrigation_method);
    const current = r.items.find((it) => it.is_current);
    const w = r.weights, sum = Object.values(w).reduce((a, b) => a + b, 0) || 1;
    $("basis-inputs").innerHTML = [
      row(t("basis_field"), f.polygon ? `${esc(f.name || t("field_point"))} · ${esc(fmtHa(f.area_ha))} · ${t("draw_points", { n: f.polygon.length })}` : `${fmt(state.lat, 4)}, ${fmt(state.lon, 4)} · ${esc(t("area_none"))}`, f.polygon ? "user" : "point"),
      row(t("set_soil"), esc(name(data.soil)), soilKind),
      row(t("set_irrigation"), `${esc(name(method))} · ${Math.round(r.irrigation_efficiency * 100)}%`, data.mode === "manual" || state.irrigation !== "furrow" ? "user" : "assumed"),
      row(t("current_rotation"), esc(current ? name(current) : "–"), state.current ? "user" : "assumed"),
      row(t("set_period"), `${r.period[0]}–${r.period[1]} (${t("period_years", { n: r.years_replayed })})`, "historical"),
      row(t("prefs_title"), ["water", "income", "soil", "risk"].map((k) => `${esc(t("s_" + k))} ${Math.round(100 * w[k] / sum)}%`).join(" · "), "user"),
    ].join("");
    const ds = (data.datasets || []).map((d) => {
      const kind = /POWER/.test(d.name) ? "historical" : /Open-Meteo/.test(d.name) ? "live" : /GIBS/.test(d.name) ? "imagery" : /SoilGrids/.test(d.name) ? "measured" : "historical";
      return row(d.name, esc([d.detail, d.resolution].filter(Boolean).join(" · ")), kind);
    });
    ds.push(row(t("basis_model"), esc(t("basis_model_text")), "estimate"));
    if (f.polygon) ds.push(row(t("basis_area"), esc(t("basis_area_text")), "estimate"));
    $("basis-sources").innerHTML = ds.join("");
    $("basis-disclaimer").textContent = data.disclaimer || "";
  }

  function renderScoresChart(r) {
    if (!$("scores-chart") || !window.Chart) return;
    const series = [["water", "s_water", "#38bdf8"], ["income", "s_income", "#a78bfa"], ["risk", "s_risk", "#fbbf24"], ["soil", "s_soil", "#4ade80"]];
    const opts = baseOptions();
    opts.plugins.legend.display = true;
    opts.scales.y = Object.assign(opts.scales.y, { min: 0, max: 100 });
    opts.scales.x.ticks = Object.assign(opts.scales.x.ticks, { autoSkip: false });
    chart("scores-chart", { type: "bar", data: {
      labels: r.items.map((it) => name(it).split(/\s+-\s+/)),
      datasets: series.map(([key, label, color]) => ({ label: t(label), data: r.items.map((it) => it.scores[key]), backgroundColor: color, borderRadius: 4, maxBarThickness: 18 })),
    }, options: opts });
  }

  function renderTrend() {
    const c = data.climate;
    if (!$("metric") || !$("annual-chart") || !c || !window.Chart) return;
    const order = ["t_mean", "precip_mm", "et0_mm", "hot_days", "frost_days", "dry_spell_days", "rain_days", "aridity", "t_max"].filter((k) => c.shift[k]);
    if (!order.includes(state.metric)) state.metric = "t_mean";
    $("metric").innerHTML = order.map((k) => `<option value="${k}">${esc(t("k_" + k))}${t("unit_" + k) ? ", " + esc(t("unit_" + k)) : ""}</option>`).join("");
    $("metric").value = state.metric;
    renderAnnual();
  }

  function chart(id, config) {
    const existing = charts[id];
    if (existing && existing.config.type === config.type && existing.canvas === $(id)) {
      existing.data = config.data;
      existing.options = config.options;
      existing.update("none");
      return;
    }
    if (existing) existing.destroy();
    charts[id] = new Chart($(id), config);
  }

  function baseOptions(extra = {}) {
    const grid = css("--line"), muted = css("--muted");
    return Object.assign({
      responsive: true, maintainAspectRatio: false, animation: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false, labels: { color: css("--fg"), boxWidth: 18, boxHeight: 8, filter: (item) => !!item.text } },
        tooltip: { filter: (item) => !!item.dataset.label },
      },
      scales: {
        x: { grid: { color: grid }, ticks: { color: muted, maxRotation: 0 } },
        y: { grid: { color: grid }, ticks: { color: muted } },
      },
    }, extra);
  }

  function renderAnnual() {
    const c = data.climate, key = state.metric, s = c.shift[key];
    const obs = c.annual.filter((a) => a[key] !== null).map((a) => ({ x: a.year, y: a[key] }));
    const band = s.projection ? s.projection.band : [];
    const trend = s.trend_line ? s.trend_line.map((q) => ({ x: q.year, y: q.value })).concat(band.map((b) => ({ x: b.year, y: b.value }))) : [];
    const opts = baseOptions();
    opts.plugins.legend.display = true;
    opts.scales.x = Object.assign(opts.scales.x, { type: "linear", min: obs.length ? obs[0].x : 1991, max: band.length ? band[band.length - 1].year : 2025, ticks: { color: css("--muted"), stepSize: 5, callback: (v) => String(v) } });
    opts.plugins.tooltip.callbacks = { title: (items) => String(items[0].parsed.x) };
    chart("annual-chart", { type: "line", data: { datasets: [
      { label: t("ds_observed"), data: obs, borderColor: css("--s1"), backgroundColor: css("--s1"), borderWidth: 2, pointRadius: 2.5, pointHoverRadius: 5, tension: 0 },
      { label: t("ds_trend"), data: trend, borderColor: css("--muted"), backgroundColor: css("--muted"), borderWidth: 2, borderDash: [6, 4], pointRadius: 0 },
      { label: t("ds_band"), data: band.map((b) => ({ x: b.year, y: b.high })), borderWidth: 0, pointRadius: 0, backgroundColor: css("--band"), fill: "+1" },
      { label: "", data: band.map((b) => ({ x: b.year, y: b.low })), borderWidth: 0, pointRadius: 0, fill: false },
    ] }, options: opts });
  }

  // ---------- crops page (Ekinlar) ----------
  // Everything shown comes from data.crops (the FAO-56 season simulation, recent 15 years) plus two reference values
  // per crop from crops.json: the favourable mid-season temperature and the typical irrigated yield.
  const CROP_CATS = ["all", "grain", "technical", "vegetable", "legume"];
  const CROP_ROWS = 6;
  const cropImg = (id) => `/media/crops/${encodeURIComponent(id)}.webp`;
  const fitOf = (c) => (c.suitability ? c.suitability.score : null);
  const sortCrops = (list) => list.slice().sort((a, b) => state.cropSort === "water"
    ? a.recent.irrigation_mm.p50 - b.recent.irrigation_mm.p50
    : (fitOf(b) ?? -1) - (fitOf(a) ?? -1));
  const cropsIn = (cat) => (data && data.crops ? data.crops : []).filter((c) => cat === "all" || c.category === cat);
  const ranked = (cat) => cropsIn(cat).slice().sort((a, b) => (fitOf(b) ?? -1) - (fitOf(a) ?? -1));
  const tUnit = (n) => (n >= 10 ? fmt(n, 0) : fmt(n, 1));
  const yieldText = (y) => (y ? `${tUnit(y.low)} – ${tUnit(y.high)} ${t("t_ha")}` : "–");
  function sowWindow(c) {
    const a = c.sowing ? c.sowing.recent : null, b = c.season.sow;
    if (!a || a === b) return md(b);
    const [x, y] = [a, b].sort();
    return `${md(x)} – ${md(y)}`;
  }
  const monthsOf = (c) => {
    const m = (mmdd) => t("months_long")[+mmdd.split("-")[0] - 1];
    const a = c.sowing ? c.sowing.recent : c.season.sow, b = c.season.sow;
    const [x, y] = [a, b].sort();
    return m(x) === m(y) ? m(x) : `${m(x)} – ${m(y)}`;
  };

  function renderCropsPage() {
    const root = document.querySelector(".dash");
    root.classList.toggle("is-demo", !!data.demo);
    if ($("dash-demo")) $("dash-demo").hidden = !data.demo;
    if (!CROP_CATS.includes(state.cropCat)) state.cropCat = "all";
    document.querySelectorAll("#crop-cats [data-cat]").forEach((b) => {
      const on = b.dataset.cat === state.cropCat, n = cropsIn(b.dataset.cat).length;
      b.setAttribute("aria-selected", String(on));
      b.tabIndex = on ? 0 : -1;
      let badge = b.querySelector(".cat-n");
      if (!badge) { badge = document.createElement("span"); badge.className = "cat-n"; b.appendChild(badge); }
      badge.textContent = data.crops ? String(n) : "";
    });
    const place = state.field && state.field.name ? state.field.name : state.locationLabel || `${state.lat.toFixed(2)}, ${state.lon.toFixed(2)}`;
    $("crop-best-sub").textContent = t("crop_best_sub");
    $("crop-best-sub").title = t("crop_place", { place });
    const list = ranked(state.cropCat);
    if (!list.some((c) => c.id === state.cropSel)) state.cropSel = list.length ? list[0].id : (data.crops && data.crops[0] ? data.crops[0].id : "");
    renderCropRows();
    renderCropBest();
    renderCropSeason();
    renderCropFindings();
  }

  function renderCropRows(animate) {
    const box = $("crop-rows");
    const best = ranked(state.cropCat)[0];
    const all = sortCrops(cropsIn(state.cropCat));
    const shown = state.cropAll ? all : all.slice(0, CROP_ROWS);
    document.querySelectorAll("[data-sort-col]").forEach((h) => {
      h.setAttribute("aria-sort", h.dataset.sortCol === state.cropSort ? (state.cropSort === "water" ? "ascending" : "descending") : "none");
    });
    if (!shown.length) {
      box.innerHTML = `<p class="ct-empty">${esc(t(data.crops ? "crop_none" : "no_data_sub"))}</p>`;
    } else {
      const old = new Map([...box.querySelectorAll(".ct-row")].map((r) => [r.dataset.crop, r.getBoundingClientRect().top]));
      box.innerHTML = shown.map((c, i) => {
        const fit = fitOf(c), r = c.recent;
        return `<div class="ct-row${best && c.id === best.id ? " is-best" : ""}${c.id === state.cropSel ? " is-selected" : ""}" role="row" tabindex="0"
            data-crop="${esc(c.id)}" style="--i:${i}" aria-label="${esc(t("crop_row_aria", { crop: name(c), fit: fit ?? "–" }))}">
          <span class="ct-crop" role="cell"><img src="${cropImg(c.id)}" alt="" width="54" height="54" loading="${i < 3 ? "eager" : "lazy"}" decoding="async"><b>${esc(name(c))}</b></span>
          <span class="ct-cell" role="cell" title="${esc(t("crop_sow_tip", { a: md(c.season.sow), b: md(c.season.harvest), d: c.season.days }))}"><svg><use href="#i-calendar"/></svg>${esc(monthsOf(c))}</span>
          <span class="ct-cell" role="cell" title="${esc(t("crop_water_tip", { need: fmt(r.water_need_mm), rain: fmt(r.rain_mm), net: fmt(r.irrigation_mm.p50) }))}"><svg class="i-water"><use href="#i-drop"/></svg>${fmt(r.irrigation_mm.p50)} mm</span>
          <span class="ct-cell" role="cell" title="${esc(c.yield_t_ha ? t("crop_yield_tip", { a: tUnit(c.yield_t_ha.typical[0]), b: tUnit(c.yield_t_ha.typical[1]) }) : "")}"><svg class="i-yield"><use href="#i-coins"/></svg>${esc(yieldText(c.yield_t_ha))}</span>
          <span class="ct-fit" role="cell"><span class="ct-bar" aria-hidden="true"><i style="--fit:${(fit ?? 0) / 100}"></i></span><b>${fit ?? "–"}%</b></span>
          <span class="ct-go" role="cell" aria-hidden="true"><svg><use href="#i-chev-r"/></svg></span>
        </div>`;
      }).join("");
      // rows that only moved glide to their new place (FLIP); new rows rise in
      box.querySelectorAll(".ct-row").forEach((row) => {
        const before = old.get(row.dataset.crop);
        if (reduceMotion.matches) return;
        if (before === undefined || animate) { row.classList.add("is-enter"); return; }
        const dy = before - row.getBoundingClientRect().top;
        if (dy) row.animate([{ transform: `translateY(${dy}px)` }, { transform: "none" }], { duration: 380, easing: "cubic-bezier(.22,1,.36,1)" });
      });
    }
    const more = $("crop-more");
    more.hidden = all.length <= CROP_ROWS;
    more.textContent = state.cropAll ? t("crop_less") : t("crop_more", { n: all.length - CROP_ROWS });
  }

  function renderCropBest(animate) {
    const top = ranked(state.cropCat).slice(0, 3);
    $("crop-best").innerHTML = top.length ? top.map((c, i) => `
      <button type="button" class="best-card${i === 0 ? " is-top" : ""}${animate ? " is-enter" : ""}" style="--i:${i}" data-crop="${esc(c.id)}"
        aria-pressed="${c.id === state.cropSel}" aria-label="${esc(t("crop_row_aria", { crop: name(c), fit: fitOf(c) ?? "–" }))}">
        <img src="${cropImg(c.id)}" alt="" width="92" height="92" decoding="async">
        <b>${esc(name(c))}</b><strong>${fitOf(c) ?? "–"}%</strong>
      </button>`).join("") : `<p class="crop-best-empty">${esc(t(data.crops ? "crop_none" : "no_data_sub"))}</p>`;
  }

  function renderCropSeason() {
    const c = (data.crops || []).find((x) => x.id === state.cropSel);
    const set = (id, text, tip) => {
      const el = $(id);
      if (el.textContent !== text) { el.textContent = text; el.classList.remove("is-swap"); void el.offsetWidth; if (!reduceMotion.matches) el.classList.add("is-swap"); }
      el.parentElement.title = tip || "";
    };
    $("crop-season-name").textContent = c ? name(c) : "–";
    if (!c) { ["cs-sow", "cs-temp", "cs-rh"].forEach((id) => set(id, "–")); return; }
    const r = c.recent, p = data.periods.recent;
    set("cs-sow", monthsOf(c), t("crop_sow_window_tip", { win: sowWindow(c), d: c.sowing ? c.sowing.threshold_c : "–" }));
    set("cs-temp", c.t_opt_c ? `${c.t_opt_c[0]} – ${c.t_opt_c[1]} °C` : "–",
      t("crop_t_opt_tip", { t: r.mid_t_c !== null ? fmt(r.mid_t_c, 1) : "–", a: p[0], b: p[1] }));
    set("cs-rh", r.mid_rh_pct !== null && r.mid_rh_pct !== undefined ? `${fmt(r.mid_rh_pct)} %` : "–", t("crop_rh_tip", { a: p[0], b: p[1] }));
  }

  function renderCropFindings() {
    const box = $("crop-findings");
    const list = ranked(state.cropCat);
    if (!list.length) { box.innerHTML = `<li class="is-empty">${esc(t(data.crops ? "crop_none" : "no_data_sub"))}</li>`; return; }
    const items = [];
    const [a, b] = list;
    items.push({ ok: fitOf(a) >= 60, text: b ? t("crop_f_best2", { a: name(a), b: name(b), x: fitOf(a), y: fitOf(b) }) : t("crop_f_best1", { a: name(a), x: fitOf(a) }) });
    const top = list.slice(0, 3);
    const net = Math.round(top.reduce((s, c) => s + c.recent.irrigation_mm.p50, 0) / top.length);
    const lv = net < 300 ? "low" : net < 600 ? "moderate" : "high";
    const et0 = data.climate && data.climate.shift && data.climate.shift.et0_mm ? data.climate.shift.et0_mm.recent : null;
    items.push({ ok: lv !== "high", text: t("crop_f_water", { level: t("crop_lv_" + lv), mm: fmt(net), et0: et0 !== null ? fmt(et0) : "–" }) });
    const tr = data.climate && data.climate.shift && data.climate.shift.t_mean;
    const stress = a.stress_level;
    items.push({ ok: stress !== "high", text: t(stress === "low" ? "crop_f_yield_ok" : "crop_f_yield_risk", {
      crop: name(a), y: yieldText(a.yield_t_ha), dt: tr && tr.trend_per_decade !== null ? sgn(tr.trend_per_decade, 2) : "–" }) });
    const html = items.map((it, i) => `<li class="${it.ok ? "" : "is-warn"}" style="--i:${i}"><span class="fi" aria-hidden="true"><svg><use href="#${it.ok ? "i-check" : "i-info"}"/></svg></span><span>${esc(it.text)}</span></li>`).join("");
    if (box.innerHTML !== html) {
      box.innerHTML = html;
      box.classList.remove("is-swap"); void box.offsetWidth; box.classList.add("is-swap");
    }
  }

  function selectCrop(id, open) {
    if (!data || !data.crops) return;
    state.cropSel = id; save();
    document.querySelectorAll("#crop-rows .ct-row").forEach((r) => r.classList.toggle("is-selected", r.dataset.crop === id));
    document.querySelectorAll("#crop-best .best-card").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.crop === id)));
    renderCropSeason();
    if (open) openCropDialog(id);
  }

  function openCropDialog(id) {
    const c = data.crops.find((x) => x.id === id), dlg = $("crop-dialog");
    if (!c || !dlg) return;
    const r = c.recent, base = c.baseline, s = c.suitability || { score: null, parts: {} }, p = data.periods;
    const parts = ["temperature", "stress", "water"].filter((k) => s.parts[k] !== undefined)
      .map((k) => `<div class="cd-part"><span>${esc(t("crop_part_" + k))}</span><span class="ct-bar"><i style="--fit:${s.parts[k] / 100}"></i></span><b>${s.parts[k]}</b></div>`).join("");
    const stat = (k, v, sub) => `<div class="cd-stat"><dt>${esc(t(k))}</dt><dd>${esc(v)}${sub ? `<small>${esc(sub)}</small>` : ""}</dd></div>`;
    const tips = [];
    if (c.t_opt_c && r.mid_t_c !== null) {
      if (r.mid_t_c > c.t_opt_c[1]) tips.push({ warn: true, text: t("crop_tip_hot", { t: fmt(r.mid_t_c, 1), b: c.t_opt_c[1] }) });
      else if (r.mid_t_c < c.t_opt_c[0]) tips.push({ warn: true, text: t("crop_tip_cool", { t: fmt(r.mid_t_c, 1), a: c.t_opt_c[0] }) });
      else tips.push({ text: t("crop_tip_temp_ok", { t: fmt(r.mid_t_c, 1) }) });
    }
    if (r.heat_years_share >= 0.2) tips.push({ warn: true, text: t("crop_tip_heat", { pct: Math.round(r.heat_years_share * 100), thr: c.heat_rule.tmax_c }) });
    if (r.frost_years_share >= 0.1) tips.push({ warn: true, text: t("crop_tip_frost", { pct: Math.round(r.frost_years_share * 100) }) });
    tips.push({ warn: c.water_level === "high", text: t("crop_tip_water", { n: r.irrigations, m3: fmt(r.irrigation_m3_ha.p50), irr: name(options && options.irrigation.find((x) => x.id === state.irrigation)) || state.irrigation }) });
    if (c.sowing && Math.abs(c.sowing.shift_days) >= 3) tips.push({ text: t("crop_tip_sow", { a: md(c.sowing.baseline), b: md(c.sowing.recent), d: sgn(c.sowing.shift_days) }) });
    if (c.legume) tips.push({ text: t("crop_tip_legume") });
    $("crop-dialog-body").innerHTML = `
      <div class="cd-head">
        <img src="${cropImg(c.id)}" alt="" width="96" height="96">
        <div><h2 id="crop-dialog-title">${esc(name(c))}</h2><p>${esc(t("cat_" + c.category))} · ${esc(t("crop_season_len", { a: md(c.season.sow), b: md(c.season.harvest), d: c.season.days }))}</p></div>
        <div class="cd-score"><b>${s.score ?? "–"}%</b><span>${esc(t("crop_th_fit"))}</span></div>
      </div>
      <dl class="cd-grid">
        ${stat("crop_sow_window", sowWindow(c), c.sowing ? t("crop_sow_rule", { d: c.sowing.threshold_c }) : "")}
        ${stat("crop_t_opt", c.t_opt_c ? `${c.t_opt_c[0]} – ${c.t_opt_c[1]} °C` : "–", r.mid_t_c !== null ? t("crop_here", { v: `${fmt(r.mid_t_c, 1)} °C` }) : "")}
        ${stat("crop_humidity", r.mid_rh_pct !== null && r.mid_rh_pct !== undefined ? `${fmt(r.mid_rh_pct)} %` : "–", t("crop_mid_season"))}
        ${stat("th_need", `${fmt(r.water_need_mm)} mm`, t("rain_covers", { mm: fmt(r.rain_mm) }))}
        ${stat("crop_th_water", `${fmt(r.irrigation_mm.p50)} mm`, t("range", { a: fmt(r.irrigation_mm.p10), b: fmt(r.irrigation_mm.p90) }) + (c.irrigation_change_mm !== null ? " · " + t("change_since", { d: sgn(c.irrigation_change_mm) }) : ""))}
        ${stat("crop_th_yield", yieldText(c.yield_t_ha), c.yield_t_ha ? t("crop_yield_tip", { a: tUnit(c.yield_t_ha.typical[0]), b: tUnit(c.yield_t_ha.typical[1]) }) : "")}
        ${stat("th_heat", `${fmt(r.heat_days.p50)} ${t("unit_days")}`, t("heat_rule", { thr: c.heat_rule.tmax_c }))}
        ${stat("crop_frost", `${Math.round(r.frost_years_share * 100)} %`, base ? t("before_now", { a: Math.round(base.frost_years_share * 100) + "%", b: Math.round(r.frost_years_share * 100) + "%" }) : "")}
        ${stat("th_gross", `${fmt(r.irrigation_m3_ha.p50)} ${t("m3ha")}`, t("irrigations", { n: r.irrigations }))}
      </dl>
      <h3>${esc(t("crop_fit_parts"))}</h3>
      <div class="cd-parts">${parts}</div>
      <h3>${esc(t("crop_recs"))}</h3>
      <ul class="cd-advice">${tips.map((x) => `<li class="${x.warn ? "is-warn" : ""}">${esc(x.text)}</li>`).join("")}</ul>
      <p class="cd-note">${esc(t("crop_dialog_note", { a: p.recent[0], b: p.recent[1] }))}${data.demo ? " " + esc(t("demo_note")) : ""}</p>
      <div class="cd-actions">
        <a class="dash-btn dash-btn-secondary" href="/rotations.html">${esc(t("crop_to_rot"))}</a>
        <button type="button" class="dash-btn dash-btn-primary" data-close-dialog>${esc(t("close"))}</button>
      </div>`;
    if (!dlg.open) dlg.showModal();
  }

  function bindCrops() {
    if (!$("crop-table")) return;
    const cats = $("crop-cats");
    cats.addEventListener("click", (e) => {
      const b = e.target.closest("[data-cat]");
      if (!b || b.dataset.cat === state.cropCat) return;
      state.cropCat = b.dataset.cat; state.cropAll = false; save();
      if (!data) return;
      const list = ranked(state.cropCat);
      if (list.length) state.cropSel = list[0].id;
      renderCropsPage();
      renderCropRows(true); renderCropBest(true);
    });
    cats.addEventListener("keydown", (e) => {
      const tabs = [...cats.querySelectorAll("[data-cat]")], i = tabs.indexOf(document.activeElement);
      if (i < 0 || !["ArrowRight", "ArrowLeft", "Home", "End"].includes(e.key)) return;
      e.preventDefault();
      const j = e.key === "Home" ? 0 : e.key === "End" ? tabs.length - 1 : (i + (e.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
      tabs[j].focus(); tabs[j].click();
    });
    $("crop-rows").addEventListener("click", (e) => { const row = e.target.closest(".ct-row"); if (row) selectCrop(row.dataset.crop, true); });
    $("crop-rows").addEventListener("keydown", (e) => {
      const row = e.target.closest(".ct-row");
      if (!row) return;
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); selectCrop(row.dataset.crop, true); }
      else if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); const n = e.key === "ArrowDown" ? row.nextElementSibling : row.previousElementSibling; if (n) n.focus(); }
    });
    $("crop-best").addEventListener("click", (e) => { const b = e.target.closest(".best-card"); if (b) selectCrop(b.dataset.crop, true); });
    document.querySelectorAll(".ct-sort").forEach((b) => b.addEventListener("click", () => {
      state.cropSort = b.dataset.sort; save(); if (data) renderCropRows();
    }));
    $("crop-more").addEventListener("click", () => { state.cropAll = !state.cropAll; save(); if (data) renderCropRows(); });
    $("crop-dialog").addEventListener("click", (e) => {
      const d = $("crop-dialog");
      if (e.target === d || e.target.closest("[data-close-dialog]")) d.close();
    });
  }

  function renderNow() {
    const n = data.now, rec = n.recent, look = n.outlook, fc = n.forecast;
    $("now-card").hidden = !rec && !fc;
    if (!rec && !fc) return;
    $("now-meta").textContent = rec ? t("now_meta", { date: isoDay(rec.as_of) }) : "";
    const tiles = [];
    if (rec) {
      tiles.push([t("n_rain30"), `${fmt(rec.rain_mm, 1)} mm`, rec.rain_normal_mm ? t("n_normal", { a: fmt(rec.rain_normal_mm.p10), b: fmt(rec.rain_normal_mm.p90) }) : ""]);
      tiles.push([t("n_et30"), `${fmt(rec.et0_mm)} mm`, t("n_balance", { v: sgn(rec.balance_mm) })]);
      tiles.push([t("n_since"), t("n_days", { n: rec.days_since_rain ?? "–" }), ""]);
    }
    if (fc) {
      tiles.push([t("n_next"), fc.next_rain_date ? `${isoDay(fc.next_rain_date)} · ${fmt(fc.next_rain_mm, 1)} mm` : t("n_next_none", { n: fc.horizon_days }), fc.source]);
    } else if (look) {
      tiles.push([t("n_next"), t("n_usual", { n: look.days_to_rain.p50 }), t("n_prob", { pct: Math.round(look.rain_within_7d_probability * 100) })]);
    }
    $("now-kpis").innerHTML = tiles.map(([k, v, d]) => `<div class="kpi"><span class="k">${esc(k)}</span><span class="v">${esc(v)}</span><span class="d">${esc(d)}</span></div>`).join("");

    $("forecast-wrap").hidden = !fc;
    $("forecast-title").hidden = !fc;
    if (fc) {
      $("forecast-title").textContent = t("forecast_title", { src: fc.source });
      $("forecast-note").textContent = t("forecast_note");
      chart("forecast-chart", { type: "bar", data: {
        labels: fc.days.map((d) => isoDay(d.date)),
        datasets: [{ label: t("m_rain").split(",")[0], data: fc.days.map((d) => d.rain_mm), backgroundColor: css("--s1"), borderRadius: 4, maxBarThickness: 22 }],
      }, options: baseOptions() });
    } else {
      $("forecast-note").textContent = look ? t("outlook_note", { a: fmt(look.rain_30d_mm.p10), b: fmt(look.rain_30d_mm.p90) }) : "";
    }
    const basis = n.week_basis ? t("week_basis_" + n.week_basis.source) : "";
    $("week").innerHTML = `<h3>${esc(t("week_title"))}${basis ? " · " + esc(basis) : ""}</h3>` + (n.week.length
      ? `<ul class="plain">${n.week.map((w) => `<li>${esc(t("week_row", { crop: name(w), need: fmt(w.need_mm, 1), net: fmt(w.net_mm, 1), m3: fmt(w.m3_ha) }))}</li>`).join("")}</ul>`
      : `<p class="hint">${esc(t("week_none"))}</p>`);
    $("advice-now").innerHTML = adviceHtml("now");
  }

  function renderSources() {
    $("datasets").className = "ds";
    $("datasets").innerHTML = data.datasets.map((d) => `
      <div><b>${esc(d.name)}</b> <span class="badge${d.nasa ? " best" : ""}">${esc(t(d.nasa ? "nasa" : "not_nasa"))}</span>
        <div class="muted">${esc(d.detail || "")}${d.resolution ? " · " + esc(d.resolution) : ""}</div>
        ${d.sources && d.sources.length ? `<div class="mono muted">${esc(d.sources.join(", "))}</div>` : ""}
        <a href="${esc(d.url)}" target="_blank" rel="noopener">${esc(d.url)}</a></div>`).join("");
    $("methods").innerHTML = t("methods").map((m) => `<li>${esc(m)}</li>`).join("");
    $("disclaimer").textContent = data.disclaimer;
  }

  // ---------- settings ----------
  async function loadProviders(refresh = false) {
    const res = await api(`/api/providers${refresh ? "?refresh=true" : ""}`);
    $("edit-note").textContent = t(res.editable ? "edit_on" : "edit_off");
    $("provider-form").hidden = !res.editable;
    const dot = { ok: "ok", down: "bad", disabled: "warn" };
    $("providers").innerHTML = res.items.map((p) => `
      <div class="prov">
        <div class="name"><span class="dot ${dot[p.status.status] || ""}"></span>${esc(p.name)}
          <span class="badge${p.nasa ? " best" : ""}">${esc(t(p.nasa ? "nasa" : "not_nasa"))}</span>
          <span class="muted small">${esc(t("st_" + p.status.status))}${p.status.ms ? ` · ${p.status.ms} ms` : ""}${p.status.message ? " · " + esc(p.status.message) : ""}</span></div>
        <div class="row">${res.editable ? `<button type="button" class="btn ghost" data-toggle="${esc(p.id)}" data-on="${p.enabled}">${esc(t(p.enabled ? "disable" : "enable"))}</button>` : ""}
          ${res.editable && !p.builtin ? `<button type="button" class="btn ghost" data-remove="${esc(p.id)}">${esc(t("remove"))}</button>` : ""}</div>
        <div class="desc">${esc(p.description)}</div>
      </div>`).join("");
  }

  async function editProvider(path, method, body) {
    const msg = $("provider-msg");
    try {
      await api(path, { method, headers: { "Content-Type": "application/json", "X-Admin-Token": $("admin-token").value }, body: body ? JSON.stringify(body) : undefined });
      msg.textContent = t("saved");
      await loadProviders();
      if ($("map")) { layers = await api("/api/layers"); renderLayerSelect(); }
      analyze();
    } catch (err) {
      if (msg) msg.textContent = t("error", { msg: err.message });
      else if ($("providers")) $("providers").textContent = t("error", { msg: err.message });
    }
  }

  // ---------- events ----------
  function bind() {
    document.querySelectorAll("[data-lang]").forEach((b) => b.addEventListener("click", () => {
      state.lang = b.dataset.lang;
      applyStaticTexts();
      if (options) renderForms();
      renderLayerSelect();
      if (data) render();
      analyze();
      if ($("providers")) loadProviders().catch(showProviderError);
      if ($("place-search") && $("place-search").value.trim().length >= 3) {
        clearTimeout(placeTimer);
        if (placeController) placeController.abort();
        placeTimer = setTimeout(() => searchPlaces($("place-search").value.trim()), 600);
      }
    }));
    const workspace = $("map-workspace");
    const fullscreenHost = $("fullscreen-map-host");
    const workspaceHome = workspace && workspace.parentElement;
    const workspaceNext = workspace && workspace.nextElementSibling;
    on("open-map", "click", () => {
      const dialog = $("map-dialog");
      if (!map || !workspace || !fullscreenHost || !dialog || dialog.open) return;
      dialog.showModal();
      fullscreenHost.append(workspace);
      mapExpanded = true;
      setMapInteractive(true);
      updateDrawUi();
      requestAnimationFrame(() => {
        fitField();
        $("close-map").focus();
      });
    });
    on("close-map", "click", () => $("map-dialog").close());
    on("map-dialog", "keydown", (e) => {
      if (e.key === "Escape" && !e.defaultPrevented) {
        e.preventDefault();
        if (draft.active && draft.points.length) { discardDraft(); return; }
        $("map-dialog").close();
      }
    });
    on("map-dialog", "close", () => {
      if (draft.active || draft.closed) discardDraft();      /* closing without Apply keeps the previous field */
      mapExpanded = false;
      setMapInteractive(false);
      if (workspace && fullscreenHost && workspace.parentElement === fullscreenHost && workspaceHome) {
        workspaceHome.insertBefore(workspace, workspaceNext && workspaceNext.parentElement === workspaceHome ? workspaceNext : null);
      }
      if (map) requestAnimationFrame(fitField);
      $("open-map").focus({ preventScroll: true });
    });
    on("draw-start", "click", startDraw);
    on("draw-undo", "click", undoVertex);
    on("draw-clear", "click", clearDraft);
    on("draw-apply", "click", () => { if (draft.active && draft.points.length >= 3) draft.closed = true; applyDraft(); });
    on("draw-cancel", "click", () => { discardDraft(); closeMap(); });
    on("map-dialog", "keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z" && (draft.active || draft.closed)) { e.preventDefault(); undoVertex(); }
    });
    document.addEventListener("click", (e) => {
      if (e.target.closest("[data-draw]")) openMap(true);
      else if (e.target.closest("[data-open-map]")) openMap(false);
    });
    on("locate", "click", locate);
    on("place-search", "input", (e) => {
      const query = e.target.value.trim();
      clearTimeout(placeTimer);
      if (placeController) placeController.abort();
      hidePlaceResults();
      $("place-search").setAttribute("aria-busy", "false");
      if (query.length < 3) {
        $("place-search-status").textContent = query ? t("place_search_min") : "";
        return;
      }
      placeTimer = setTimeout(() => searchPlaces(query), 600);
    });
    on("place-search", "keydown", (e) => {
      if (e.key === "ArrowDown" && placeResults.length) {
        e.preventDefault();
        updateActivePlace(activePlaceIndex + 1);
      } else if (e.key === "ArrowUp" && placeResults.length) {
        e.preventDefault();
        updateActivePlace(activePlaceIndex < 0 ? placeResults.length - 1 : activePlaceIndex - 1);
      } else if (e.key === "Enter" && activePlaceIndex >= 0) {
        e.preventDefault();
        choosePlace(activePlaceIndex);
      } else if (e.key === "Escape" && !$("place-results").hidden) {
        e.preventDefault();
        e.stopPropagation();
        hidePlaceResults();
      }
    });
    on("place-results", "click", (e) => {
      const button = e.target.closest("[data-place-index]");
      if (button) choosePlace(Number(button.dataset.placeIndex));
    });
    on("presets", "click", (e) => { const b = e.target.closest("button"); if (b) setPoint(+b.dataset.lat, +b.dataset.lon); });
    on("layer", "change", (e) => { state.layer = e.target.value; save(); showOverlay(); });
    on("opacity", "input", (e) => { state.opacity = +e.target.value; if (overlay) overlay.setOpacity(state.opacity / 100); save(); });
    on("current", "change", (e) => { state.current = e.target.value; requestMode = state.mode; renderBuilder(); analyzeSoon(300); });
    on("irrigation", "change", (e) => { state.irrigation = e.target.value; requestMode = "auto"; analyzeSoon(300); });
    on("soil", "change", (e) => { state.soil = e.target.value; requestMode = "auto"; analyzeSoon(300); });
    on("period", "change", (e) => { state.period = e.target.value; requestMode = "auto"; analyzeSoon(300); });
    document.querySelectorAll("[data-mode]").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));
    on("manual-form", "submit", (e) => { e.preventDefault(); runManual(); });
    on("mf-name", "input", (e) => { state.field.name = e.target.value.trim(); save(); renderFieldFacts(); });
    on("clim-period", "change", (e) => { state.climPeriod = e.target.value; save(); if (data) renderClimAnnual(); });
    on("clim-metric", "change", (e) => { state.metric = e.target.value; save(); if (data) renderClimAnnual(); });
    on("clim-region", "change", (e) => { state.climRegion = e.target.value; requestMode = "auto"; analyzeSoon(300); });
    on("clim-run", "click", () => { requestMode = "auto"; analyze(); });
    on("clim-advice-open", "click", () => { const d = $("clim-advice-dialog"); if (d && !d.open) d.showModal(); });
    on("clim-advice-dialog", "click", (e) => {
      const d = $("clim-advice-dialog");
      if (e.target === d || e.target.closest("[data-close-dialog]")) d.close();
    });
    document.addEventListener("click", (e) => {
      if (e.target.closest("[data-retry]")) { if (options) analyze(); else start(); }
      else if (e.target.closest("[data-demo]")) loadDemo();
    });
    on("sliders", "input", (e) => { const k = e.target.dataset.w; if (!k) return; state.weights[k] = +e.target.value; renderWeights(); analyzeSoon(); });
    on("builder-years", "change", (e) => { const s = e.target; state.customYears[+s.dataset.y][+s.dataset.s] = s.value; analyze(); });
    on("add-year", "click", () => { if (state.customYears.length < 6) { state.customYears.push(["winter_wheat", ""]); renderBuilder(); analyze(); } });
    on("remove-year", "click", () => { if (state.customYears.length > 1) { state.customYears.pop(); renderBuilder(); analyze(); } });
    on("metric", "change", (e) => { state.metric = e.target.value; save(); renderAnnual(); });
    on("refresh-providers", "click", () => loadProviders(true).catch(showProviderError));
    on("providers", "click", (e) => {
      const b = e.target.closest("button"); if (!b) return;
      if (b.dataset.toggle) editProvider(`/api/providers/${b.dataset.toggle}`, "PATCH", { enabled: b.dataset.on !== "true" });
      if (b.dataset.remove) editProvider(`/api/providers/${b.dataset.remove}`, "DELETE");
    });
    on("provider-form", "submit", (e) => {
      e.preventDefault();
      editProvider("/api/providers", "POST", { id: $("p-id").value, name: $("p-name").value, kind: $("p-kind").value, url_template: $("p-url").value });
    });
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { if (data) render(); });
    bindCrops();
  }

  function showProviderError(err) {
    const message = t("error", { msg: err.message });
    if ($("provider-msg")) $("provider-msg").textContent = message;
    else if ($("providers")) $("providers").textContent = message;
  }

  // ---------- start ----------
  let started = false;
  async function start() {
    if (window.Chart) {
      Chart.defaults.font.family = css("--font");
      Chart.defaults.font.size = 12;
    }
    if (!started) {
      started = true;
      applyStaticTexts();
      if ($("opacity")) $("opacity").value = state.opacity;
      initMap();
      bind();
    }
    dashState("loading");
    try {
      [options, layers] = await Promise.all([
        api("/api/options"),
        $("map") ? api("/api/layers") : Promise.resolve([]),
      ]);
    } catch (err) {
      console.error("Options failed:", err);
      if (document.querySelector(".dash")) dashError(err);
      else if ($("warnings")) $("warnings").innerHTML = alertHtml("critical", t("error", { msg: err.message }));
      return;
    }
    renderForms();
    renderLayerSelect();
    if ($("map")) setPoint(state.lat, state.lon, true, state.locationLabel);
    else analyze();
    if ($("providers")) loadProviders().catch(showProviderError);
  }
  start();
})();
