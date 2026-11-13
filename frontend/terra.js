/* TerraShift — Mission Control.
   One page, no build step. Leaflet draws the map, Chart.js the charts, everything else is DOM + SVG.
   All numbers come from /api/analyze; this file only arranges them. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---------- state: defaults < saved < URL ----------
  const DEFAULTS = {
    lat: 40.1158, lon: 67.8422, label: "", lang: null, soil: "auto", irrigation: "furrow", current: null,
    customYears: [["cotton", ""], ["winter_wheat", "mung_bean"]],
    weights: { water: 40, income: 20, soil: 20, risk: 20 },
    layer: "", layerDate: "", opacity: 75, area: 100, metric: "t",
  };
  const saved = (() => { try { return JSON.parse(localStorage.getItem("terrashift.v2") || "{}"); } catch { return {}; } })();
  const state = Object.assign(structuredClone(DEFAULTS), saved);
  (function readUrl() {
    const q = new URLSearchParams(location.search);
    const num = (k) => (q.has(k) && Number.isFinite(+q.get(k)) ? +q.get(k) : null);
    if (num("lat") !== null && num("lon") !== null) { state.lat = clamp(num("lat"), -90, 90); state.lon = clamp(num("lon"), -180, 180); state.label = q.get("place") || ""; }
    if (["furrow", "sprinkler", "drip"].includes(q.get("irr"))) state.irrigation = q.get("irr");
    if (["auto", "light", "medium", "heavy"].includes(q.get("soil"))) state.soil = q.get("soil");
    if (q.get("cur")) state.current = q.get("cur");
    if (q.get("custom")) state.customYears = q.get("custom").split("|").map((y) => { const p = y.split("+"); return [p[0] || "", p[1] || ""]; });
    if (q.get("w")) { const w = q.get("w").split(",").map(Number); if (w.length === 4 && w.every(Number.isFinite)) state.weights = { water: w[0], income: w[1], soil: w[2], risk: w[3] }; }
    if (num("area")) state.area = num("area");
    if (["en", "uz"].includes(q.get("lang"))) state.lang = q.get("lang");
  })();
  if (!state.lang) state.lang = (navigator.language || "en").toLowerCase().startsWith("uz") ? "uz" : "en";
  const save = () => { try { localStorage.setItem("terrashift.v2", JSON.stringify(state)); } catch { /* private mode */ } };

  let options = null, data = null, layers = [];
  let map = null, marker = null, cell = null, overlay = null;
  const charts = {};

  // ---------- text and numbers ----------
  const t = (key, vars) => {
    let s = (window.I18N[state.lang] || {})[key] ?? window.I18N.en[key] ?? key;
    if (vars && typeof s === "string") for (const k in vars) s = s.replaceAll(`{${k}}`, vars[k]);
    return s;
  };
  const nm = (obj) => (obj && obj.name ? (obj.name[state.lang] || obj.name.en) : "");
  const ttl = (obj) => (obj && obj.title ? (obj.title[state.lang] || obj.title.en) : "");
  const nf = (d) => new Intl.NumberFormat(state.lang === "uz" ? "uz-Latn-UZ" : "en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  const fmt = (n, d = 0) => (n === null || n === undefined || Number.isNaN(n) ? "–" : nf(d).format(n).replace(/^-/, "−"));
  const sgn = (n, d = 0) => (n === null || n === undefined ? "–" : (n > 0 ? "+" : "") + fmt(n, d));
  const compact = (n) => {
    if (n === null || n === undefined) return "–";
    const a = Math.abs(n);
    if (a >= 1e9) return fmt(n / 1e9, 1) + t("u_bn");
    if (a >= 1e6) return fmt(n / 1e6, a >= 1e7 ? 0 : 1) + t("u_mn");
    if (a >= 1e4) return fmt(n / 1e3, 0) + t("u_k");
    return fmt(n, 0);
  };
  const months = () => t("months");
  const mmdd = (s) => { if (!s) return "–"; const [m, d] = s.split("-").map(Number); return `${d} ${months()[m - 1]}`; };
  const doyOf = (s) => { const [m, d] = s.split("-").map(Number); return Math.round((Date.UTC(2001, m - 1, d) - Date.UTC(2001, 0, 1)) / 864e5) + 1; };
  const cssVar = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

  const CROP_COLOR = { cotton: "#e8e3ff", winter_wheat: "#ffc857", chickpea: "#f4a261", sorghum: "#ff7a5c", mung_bean: "#6ee7a0", alfalfa: "#2dd4bf" };
  const cropColor = (id) => CROP_COLOR[id] || "#9fb8ff";
  const W = { water: "--water", income: "--income", soil: "--soil", risk: "--risk" };

  function applyStaticTexts() {
    document.documentElement.lang = state.lang;
    document.querySelectorAll("[data-t]").forEach((el) => { el.textContent = t(el.dataset.t); });
    document.querySelectorAll("[data-t-placeholder]").forEach((el) => el.setAttribute("placeholder", t(el.dataset.tPlaceholder)));
    document.querySelectorAll("[data-t-aria]").forEach((el) => el.setAttribute("aria-label", t(el.dataset.tAria)));
    document.querySelectorAll("[data-t-title]").forEach((el) => el.setAttribute("title", t(el.dataset.tTitle)));
    document.querySelectorAll("[data-lang]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lang === state.lang)));
    document.title = t("page_title");
  }

  function toast(msg) {
    const el = $("toast");
    el.textContent = msg;
    el.classList.add("show");
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => el.classList.remove("show"), 2600);
  }

  // ---------- API ----------
  const api = async (path, init) => {
    const res = await fetch(path, init);
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail || res.status));
    return body;
  };

  function query() {
    const q = new URLSearchParams({
      lat: state.lat, lon: state.lon, lang: state.lang, soil: state.soil, irrigation: state.irrigation,
      w_water: state.weights.water, w_income: state.weights.income, w_soil: state.weights.soil, w_risk: state.weights.risk,
    });
    if (state.current === "custom") q.set("custom", customText());
    else if (state.current) q.set("current", state.current);
    return q;
  }
  const customText = () => state.customYears.map((y) => y.filter(Boolean).join("+")).filter(Boolean).join("|");

  let controller = null, timer = null, stepTimer = null;
  const analyzeSoon = (delay = 300) => { clearTimeout(timer); timer = setTimeout(analyze, delay); };

  function setLoading(on) {
    $("verdict").classList.toggle("is-loading", on);
    $("status-dot").className = "dot" + (on ? " busy" : "");
    const steps = [...$("steps").children];
    clearInterval(stepTimer);
    if (!on) return;
    let k = 0;
    steps.forEach((s) => (s.className = ""));
    steps[0].className = "on";
    stepTimer = setInterval(() => {
      if (k >= steps.length - 1) return clearInterval(stepTimer);
      steps[k].className = "done"; k++; steps[k].className = "on";
    }, data ? 260 : 900);
  }

  async function analyze() {
    save();
    syncUrl();
    if (controller) controller.abort();
    const mine = new AbortController();
    controller = mine;
    setLoading(true);
    $("analysis-status").textContent = t("analyzing");
    try {
      const result = await api(`/api/analyze?${query()}`, { signal: mine.signal });
      if (controller !== mine) return;
      data = result;
      render();
      $("analysis-status").textContent = t("analysis_updated");
    } catch (err) {
      if (err.name === "AbortError") return;
      $("alerts").innerHTML = alertHtml("critical", t("error", { msg: err.message }));
      $("status-dot").className = "dot fail";
      $("analysis-status").textContent = t("analysis_failed");
    } finally {
      if (controller === mine) setLoading(false);
    }
  }

  function syncUrl() {
    const q = new URLSearchParams({ lat: state.lat, lon: state.lon, irr: state.irrigation, soil: state.soil,
      w: [state.weights.water, state.weights.income, state.weights.soil, state.weights.risk].join(","), area: state.area, lang: state.lang });
    if (state.label) q.set("place", state.label);
    if (state.current === "custom") q.set("custom", customText());
    if (state.current) q.set("cur", state.current);
    return `${location.origin}${location.pathname}?${q}`;
  }

  // ---------- map ----------
  const LEGEND = {
    vegetation: ["linear-gradient(90deg,#c9a36b,#e8e08a,#7cc26b,#1f7a3a,#0b4a22)", "legend_ndvi"],
    heat: ["linear-gradient(90deg,#2c3cbf,#38b6d8,#f1e36b,#f08a3a,#b51c1c)", "legend_lst"],
    water: ["linear-gradient(90deg,#f3e6c4,#a6d8e8,#3b8fd0,#1e3d9a,#6a2fa0)", "legend_water"],
  };

  function initMap() {
    map = L.map("map", { zoomControl: true, attributionControl: true, worldCopyJump: true, minZoom: 2 }).setView([state.lat, state.lon], 8);
    L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
      maxZoom: 18, attribution: "Imagery © Esri, Maxar, Earthstar Geographics",
    }).addTo(map);
    L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}", {
      maxZoom: 18, pane: "shadowPane", opacity: .85,
    }).addTo(map);
    marker = L.marker([state.lat, state.lon], {
      icon: L.divIcon({ className: "", html: '<div style="position:relative"><div class="pin-pulse"></div><div class="pin"></div></div>', iconSize: [22, 22], iconAnchor: [11, 11] }),
      keyboard: false,
    }).addTo(map);
    cell = L.rectangle([[0, 0], [0, 0]], { className: "grid-cell", interactive: false }).addTo(map);
    drawCell();
    map.on("click", (e) => setPoint(e.latlng.lat, e.latlng.lng, false, ""));
    window.addEventListener("terrashift:app-visible", () => setTimeout(() => map.invalidateSize(), 60));
  }

  /* NASA POWER meteorology grid: 0.5° latitude x 0.625° longitude. Showing the cell makes the 50 km resolution honest. */
  function drawCell() {
    const la = Math.round(state.lat / 0.5) * 0.5, lo = Math.round(state.lon / 0.625) * 0.625;
    cell.setBounds([[la - 0.25, lo - 0.3125], [la + 0.25, lo + 0.3125]]);
    cell.unbindTooltip();
    cell.bindTooltip(t("grid_cell"), { sticky: true });
  }

  function setPoint(lat, lon, recenter = true, label = "") {
    state.lat = Math.round(lat * 1e4) / 1e4;
    state.lon = Math.round((((lon + 180) % 360 + 360) % 360 - 180) * 1e4) / 1e4;
    state.label = label;
    marker.setLatLng([state.lat, state.lon]);
    drawCell();
    if (recenter) {
      const box = map.getContainer().getBoundingClientRect();
      const onScreen = box.bottom > 0 && box.top < innerHeight && !document.hidden;
      if (onScreen && !reduceMotion) map.flyTo([state.lat, state.lon], Math.max(map.getZoom(), 8), { duration: 1.2 });
      else map.setView([state.lat, state.lon], Math.max(map.getZoom(), 8));
    }
    renderPlace();
    renderPresets();
    analyze();
  }

  function renderPlace() {
    const preset = (options?.presets || []).find((p) => p.lat === state.lat && p.lon === state.lon);
    $("place-name").textContent = state.label || (preset ? nm(preset) : t("selected_point"));
    $("place-coords").textContent = `${Math.abs(state.lat).toFixed(3)}°${state.lat >= 0 ? "N" : "S"} ${Math.abs(state.lon).toFixed(3)}°${state.lon >= 0 ? "E" : "W"}`;
  }
  const placeTitle = () => $("place-name").textContent;

  function renderPresets() {
    const host = $("presets");
    host.innerHTML = (options?.presets || []).map((p) => {
      const on = p.lat === state.lat && p.lon === state.lon;
      return `<button type="button" class="chip" data-lat="${p.lat}" data-lon="${p.lon}" aria-pressed="${on}">${esc(nm(p))}</button>`;
    }).join("");
  }

  function renderLayerChips() {
    const host = $("layer-chips");
    const chip = (id, label) => `<button type="button" class="chip" data-layer="${esc(id)}" aria-pressed="${state.layer === id}">${esc(label)}</button>`;
    host.innerHTML = chip("", t("layer_none")) + layers.map((l) => chip(l.id, ttl(l) || l.id)).join("");
    showOverlay();
  }

  function layerDateDefault(layer) {
    const d = new Date(Date.now() - (layer.lag_days || 1) * 864e5);
    return d.toISOString().slice(0, 10);
  }

  function showOverlay() {
    if (!map) return;
    if (overlay) { map.removeLayer(overlay); overlay = null; }
    const layer = layers.find((l) => l.id === state.layer);
    $("layer-tools").hidden = !layer;
    if (!layer) return;
    $("layer-date-wrap").hidden = !layer.dated;
    let url = layer.url;
    if (layer.dated) {
      if (!state.layerDate) state.layerDate = layerDateDefault(layer);
      $("layer-date").value = state.layerDate;
      $("layer-date").max = new Date().toISOString().slice(0, 10);
      $("layer-date").min = "2002-07-01";
      url = url.replace("/default/default/", `/default/${state.layerDate}/`);
    }
    overlay = L.tileLayer(url, { maxNativeZoom: layer.max_zoom, maxZoom: 18, opacity: state.opacity / 100, attribution: esc(layer.attribution), crossOrigin: false }).addTo(map);
    const legend = LEGEND[layer.group];
    $("layer-legend").innerHTML = legend ? `<span>${esc(t("low"))}</span><span class="ramp" style="background:${legend[0]}"></span><span>${esc(t("high"))}</span><span class="muted">${esc(t(legend[1]))}</span>` : "";
    $("opacity").value = state.opacity;
    rangeFill($("opacity"));
  }

  function locate() {
    const btn = $("locate");
    const fail = (key) => { btn.disabled = false; $("search-status").textContent = t(key); };
    if (!window.isSecureContext || !navigator.geolocation) return fail("locate_insecure");
    btn.disabled = true;
    $("search-status").textContent = t("locating");
    navigator.geolocation.getCurrentPosition(
      (pos) => { btn.disabled = false; $("search-status").textContent = ""; setPoint(pos.coords.latitude, pos.coords.longitude, true, t("my_location")); },
      (err) => fail(err.code === 1 ? "locate_denied" : "locate_unavailable"),
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 });
  }

  // ---------- place search ----------
  let placeTimer = null, placeCtl = null, results = [], active = -1;
  function hideResults() {
    $("place-results").hidden = true; $("place-results").replaceChildren(); results = []; active = -1;
    $("place-search").setAttribute("aria-expanded", "false");
  }
  async function searchPlaces(q) {
    if (placeCtl) placeCtl.abort();
    placeCtl = new AbortController();
    $("search-status").textContent = t("searching");
    try {
      const body = await api(`/api/places?${new URLSearchParams({ q, lang: state.lang })}`, { signal: placeCtl.signal });
      results = (body.features || []).filter((f) => f.geometry?.coordinates).map((f) => {
        const p = f.properties || {};
        const primary = p.name || p.city || p.county || p.state || p.country || "";
        const ctx = [...new Set([p.city, p.county, p.state, p.country])].filter((x) => x && x !== primary).join(", ");
        return { primary, ctx, lon: f.geometry.coordinates[0], lat: f.geometry.coordinates[1] };
      });
      const list = $("place-results");
      list.innerHTML = results.map((r, i) => `<li role="option" id="pr-${i}" data-i="${i}" aria-selected="false"><span>${esc(r.primary)}</span><small>${esc(r.ctx)}</small></li>`).join("");
      list.hidden = !results.length;
      $("place-search").setAttribute("aria-expanded", String(!!results.length));
      $("search-status").textContent = results.length ? "" : t("search_none");
    } catch (err) {
      if (err.name !== "AbortError") $("search-status").textContent = t("search_failed");
    }
  }
  function choose(i) {
    const r = results[i];
    if (!r) return;
    $("place-search").value = r.primary;
    hideResults();
    setPoint(r.lat, r.lon, true, r.primary);
  }

  // ---------- passport ----------
  function renderPassport() {
    const sel = $("current");
    sel.innerHTML = options.rotations.map((r) => `<option value="${esc(r.id)}">${esc(nm(r))}</option>`).join("") +
      `<option value="custom">${esc(t("custom_rotation"))}</option>`;
    if (!state.current) state.current = options.default_current;
    sel.value = state.current;
    $("builder").hidden = state.current !== "custom";
    renderBuilder();

    $("irrigation").innerHTML = options.irrigation.map((m) =>
      `<button type="button" data-irr="${m.id}" aria-pressed="${state.irrigation === m.id}" title="${esc(t("efficiency", { pct: Math.round(m.efficiency * 100) }))}">${esc(nm(m))}</button>`).join("");
    const soils = [{ id: "auto", name: { en: t("soil_auto"), uz: t("soil_auto") } }, ...options.soils];
    $("soil").innerHTML = soils.map((s) => `<button type="button" data-soil="${s.id}" aria-pressed="${state.soil === s.id}">${esc(nm(s).replace(/\s*\(.*\)/, ""))}</button>`).join("");
    renderWeights();
    $("area").value = state.area;
  }

  function renderBuilder() {
    const opts = (v, blank) => (blank ? `<option value="">${esc(t("no_second_crop"))}</option>` : "") +
      options.crops.map((c) => `<option value="${c.id}"${c.id === v ? " selected" : ""}>${esc(nm(c))}</option>`).join("");
    $("builder-years").innerHTML = state.customYears.map((y, i) => `<div class="builder-row">
      <span class="tiny mono">${esc(t("year_n", { n: i + 1 }))}</span>
      <select class="input" data-y="${i}" data-k="0" aria-label="${esc(t("year_n", { n: i + 1 }))}">${opts(y[0], false)}</select>
      <select class="input" data-y="${i}" data-k="1" aria-label="${esc(t("second_crop"))}">${opts(y[1], true)}</select></div>`).join("");
    $("remove-year").disabled = state.customYears.length <= 1;
    $("add-year").disabled = state.customYears.length >= 6;
  }

  function renderWeights() {
    const html = (suffix) => Object.keys(W).map((k) => `<div class="weight">
      <span class="sw" style="background:var(${W[k]})"></span>
      <label><span>${esc(t("w_" + k))}</span><input type="range" min="0" max="100" step="5" value="${state.weights[k]}" data-w="${k}" style="--c:var(${W[k]})" aria-label="${esc(t("w_" + k))}"></label>
      <output class="mono" data-wo="${k}">${pct(k)}%</output></div>`).join("");
    $("weights").innerHTML = html();
    $("weights-2").innerHTML = html();
    document.querySelectorAll("input[data-w]").forEach(rangeFill);
  }
  const pct = (k) => { const s = Object.values(state.weights).reduce((a, b) => a + b, 0) || 1; return Math.round(100 * state.weights[k] / s); };
  function rangeFill(el) { const p = ((el.value - el.min) / (el.max - el.min)) * 100; el.style.setProperty("--p", p + "%"); }

  // ---------- render ----------
  function alertHtml(sev, text) {
    const icon = { info: "i", warning: "!", critical: "▲" }[sev] || "i";
    return `<div class="alert ${sev}"><b aria-hidden="true">${icon}</b><span>${esc(text)}</span></div>`;
  }

  function render() {
    if (!data) return;
    $("status-dot").className = "dot" + (data.source === "failed" ? " fail" : "");
    $("alerts").innerHTML = data.warnings.filter((w) => w.provider !== "rotation").map((w) => alertHtml(w.severity, w.text)).join("");
    $("print-meta").textContent = `${placeTitle()} · ${data.location.lat}, ${data.location.lon} · ${new Date().toISOString().slice(0, 10)}`;
    renderSoilNote();
    renderVerdict();
    renderClimate();
    renderRotations();
    renderCrops();
    renderNow();
    renderImpact();
    renderData();
    $("disclaimer").textContent = data.disclaimer || "";
    observeReveal();
  }

  function renderSoilNote() {
    const s = data.soil;
    const how = { measured: t("soil_measured"), chosen: t("soil_chosen"), default: t("soil_default") }[data.coverage.soil];
    $("soil-note").textContent = `${nm(s)} · ${s.awc_mm_per_m} ${t("u_awc")} · ${how}`;
  }

  const rotById = (id) => data.rotations?.items.find((r) => r.id === id);
  const stripHtml = (rot) => rot.years.map((slot, i) => `<span class="rot-year"><span class="yr">${esc(t("y_short", { n: i + 1 }))}</span>${slot.map((c) =>
    `<span class="crop-dot"><i style="background:${cropColor(c.id)}"></i>${esc(nm(c))}</span>`).join('<span class="rot-arrow">+</span>')}</span>`).join('<span class="rot-arrow">→</span>');

  function ring(share) {
    const r = 23, c = 2 * Math.PI * r;
    return `<svg class="ring" viewBox="0 0 54 54" aria-hidden="true"><circle class="bg" cx="27" cy="27" r="${r}"/><circle class="fg" cx="27" cy="27" r="${r}" stroke-dasharray="${c}" stroke-dashoffset="${c * (1 - share)}"/></svg>`;
  }

  function renderVerdict() {
    const R = data.rotations;
    const kp = $("kpis");
    $("verdict-kicker").textContent = t("verdict_kicker_place", { place: placeTitle() });
    if (!R || !R.items.length) {
      $("verdict-title").textContent = t("no_verdict");
      $("verdict-lead").textContent = "";
      $("verdict-strip").innerHTML = kp.innerHTML = $("advice").innerHTML = "";
      return;
    }
    const best = rotById(R.best_id), cur = rotById(R.current_id);
    const same = best.id === cur.id;
    $("verdict-title").innerHTML = same
      ? `${esc(t("verdict_keep"))} <span class="grad">${esc(nm(best))}</span>`
      : `${esc(t("verdict_switch"))} <span class="grad">${esc(nm(best))}</span>`;
    const conf = R.clear_winner ? t("conf_clear", { wins: best.wins, n: R.years_replayed }) : t("conf_close", { wins: best.wins, n: R.years_replayed });
    $("verdict-lead").textContent = (same
      ? t("verdict_lead_keep", { n: R.years_replayed, from: R.period[0], to: R.period[1] })
      : t("verdict_lead_switch", { cur: nm(cur), n: R.years_replayed, from: R.period[0], to: R.period[1] })) + " " + conf;
    $("verdict-strip").innerHTML = stripHtml(best);

    const v = best.vs_current;
    const share = best.wins / Math.max(1, R.years_replayed);
    const kpi = (cls, label, color, val, unit, note, neg) => `<div class="kpi ${cls}"><span class="label"><i style="background:var(${color})"></i>${esc(label)}</span>
      <span class="val${neg ? " neg" : ""}">${val}<small>${esc(unit)}</small></span><span class="note">${note}</span></div>`;
    if (!same && v) {
      kp.innerHTML =
        kpi("water", t("kpi_water_saved"), "--water", (v.water_m3_ha >= 0 ? "" : "+") + fmt(Math.abs(v.water_m3_ha)), t("u_m3ha"),
          esc(t("kpi_water_note", { pct: fmt(Math.abs(v.water_pct ?? 0)), dir: v.water_m3_ha >= 0 ? t("less") : t("more") })), v.water_m3_ha < 0) +
        kpi("income", t("kpi_income"), "--income", sgn(v.income_usd_ha), t("u_usdha"), esc(t("kpi_income_note")), v.income_usd_ha < 0) +
        kpi("soil", t("kpi_soil"), "--soil", sgn(v.soil), t("u_pts"), esc(t("kpi_soil_note", { from: cur.soil.index, to: best.soil.index })), v.soil < 0) +
        `<div class="kpi conf"><span class="label"><i style="background:#9fb8ff"></i>${esc(t("kpi_conf"))}</span>
          <div class="conf-row">${ring(share)}<span class="val">${best.wins}<small>/ ${R.years_replayed}</small></span></div>
          <span class="note">${esc(t("kpi_conf_note"))}</span></div>`;
    } else {
      kp.innerHTML =
        kpi("water", t("kpi_water_use"), "--water", fmt(best.water_m3_ha.p50), t("u_m3ha"), esc(t("range_note", { lo: fmt(best.water_m3_ha.p10), hi: fmt(best.water_m3_ha.p90) }))) +
        kpi("income", t("kpi_income_abs"), "--income", fmt(best.income_usd_ha.p50), t("u_usdha"), esc(t("kpi_income_note"))) +
        kpi("soil", t("kpi_soil_abs"), "--soil", fmt(best.soil.index), "/100", esc(t("kpi_soil_abs_note"))) +
        `<div class="kpi conf"><span class="label"><i style="background:#9fb8ff"></i>${esc(t("kpi_conf"))}</span>
          <div class="conf-row">${ring(share)}<span class="val">${best.wins}<small>/ ${R.years_replayed}</small></span></div>
          <span class="note">${esc(t("kpi_conf_note"))}</span></div>`;
    }
    countUp(kp);
    const order = { critical: 0, warning: 1, tip: 2, info: 3 };
    $("advice").innerHTML = [...(data.advice || [])].sort((a, b) => order[a.severity] - order[b.severity]).slice(0, 6).map((a) =>
      `<li><span class="ic ${a.severity}" aria-hidden="true">${{ tip: "✓", info: "i", warning: "!", critical: "▲" }[a.severity] || "i"}</span><span>${esc(a.text)}</span></li>`).join("");
  }

  function countUp(root) {
    if (reduceMotion) return;
    root.querySelectorAll(".val").forEach((el) => {
      const node = [...el.childNodes].find((n) => n.nodeType === 3 && /\d/.test(n.textContent));
      if (!node) return;
      const final = node.textContent;
      const [, sign, rest] = final.match(/^([+−]?)(.*)$/);
      const target = parseFloat(rest.replace(/[^\d]/g, ""));
      if (!Number.isFinite(target) || /[.,]\d/.test(rest)) return;
      const t0 = performance.now(), dur = 900;
      const step = (now) => {
        const k = Math.min(1, (now - t0) / dur);
        node.textContent = k < 1 ? sign + fmt(target * (1 - Math.pow(1 - k, 3))) : final;
        if (k < 1) requestAnimationFrame(step);
      };
      requestAnimationFrame(step);
    });
  }

  // ----- climate -----
  // `better`: the direction that is good for crops, used only to colour the change.
  const IND = [
    { k: "t_mean", d: 1, unit: "°C", better: "down" },
    { k: "t_max", d: 1, unit: "°C", better: "down" },
    { k: "hot_days", d: 0, unit: "d", better: "down" },
    { k: "frost_days", d: 0, unit: "d", better: "down" },
    { k: "precip_mm", d: 0, unit: "mm", better: "up" },
    { k: "rain_days", d: 0, unit: "d", better: "up" },
    { k: "dry_spell_days", d: 0, unit: "d", better: "down" },
    { k: "et0_mm", d: 0, unit: "mm", better: "down" },
    { k: "aridity", d: 2, unit: "P/ET₀", better: "up" },
    { k: "soil_wetness", d: 2, unit: "0–1", better: "up" },
  ];
  const STRIPES = ["#08306b", "#08519c", "#2171b5", "#4292c6", "#6baed6", "#9ecae1", "#c6dbef", "#deebf7", "#fee0d2", "#fcbba1", "#fc9272", "#fb6a4a", "#ef3b2c", "#cb181d", "#a50f15", "#67000d"];

  function renderClimate() {
    const C = data.climate;
    if (!C) { $("climate-lead").textContent = t("no_climate"); return; }
    const s = C.shift.t_mean;
    $("climate-lead").textContent = t("climate_lead", {
      b0: data.periods.baseline[0], b1: data.periods.baseline[1], r0: data.periods.recent[0], r1: data.periods.recent[1],
      dt: sgn(s.delta, 1), tr: sgn(s.trend_per_decade, 2), sig: s.trend_significant ? t("sig_yes_long") : t("sig_no_long"),
    });
    drawStripes();
    setupTimeMachine();
    renderIndicators();
    renderMonthly();
    renderFrost();
  }

  function drawStripes() {
    const annual = data.climate.annual.filter((r) => r.t_mean !== null);
    const cv = $("stripes");
    const dpr = window.devicePixelRatio || 1;
    const w = cv.clientWidth, h = cv.clientHeight;
    cv.width = w * dpr; cv.height = h * dpr;
    const ctx = cv.getContext("2d");
    ctx.scale(dpr, dpr);
    const base = data.climate.shift.t_mean.baseline;
    const span = Math.max(...annual.map((r) => Math.abs(r.t_mean - base))) || 1;
    const bw = w / annual.length;
    annual.forEach((r, i) => {
      const k = clamp(Math.round(((r.t_mean - base) / span + 1) / 2 * (STRIPES.length - 1)), 0, STRIPES.length - 1);
      ctx.fillStyle = STRIPES[k];
      ctx.fillRect(Math.floor(i * bw), 0, Math.ceil(bw) + 1, h);
    });
    const g = ctx.createLinearGradient(0, h * .45, 0, h);
    g.addColorStop(0, "rgba(0,0,0,0)"); g.addColorStop(1, "rgba(0,0,0,.55)");
    ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);
    cv.setAttribute("aria-label", t("stripes_aria", { from: annual[0].year, to: annual.at(-1).year }));
    $("stripes-sub").textContent = t("stripes_sub", { from: annual[0].year, to: annual.at(-1).year, base: fmt(base, 1) });
    const step = annual.length > 20 ? 5 : 2;
    $("stripes-axis").innerHTML = annual.filter((r, i) => i % step === 0 || i === annual.length - 1).map((r) => `<span>${r.year}</span>`).join("");
    cv.onmousemove = (e) => {
      const rect = cv.getBoundingClientRect();
      const i = clamp(Math.floor((e.clientX - rect.left) / (rect.width / annual.length)), 0, annual.length - 1);
      const r = annual[i], tip = $("stripes-tip");
      tip.hidden = false;
      tip.style.left = (e.clientX - rect.left) + "px"; tip.style.top = (e.clientY - rect.top) + "px";
      tip.innerHTML = `<b>${r.year}</b> · ${fmt(r.t_mean, 2)} °C <span class="${r.t_mean > base ? "up" : "down"}">(${sgn(r.t_mean - base, 2)})</span>`;
    };
    cv.onmouseleave = () => { $("stripes-tip").hidden = true; };
    cv.onclick = (e) => {
      const rect = cv.getBoundingClientRect();
      const i = clamp(Math.floor((e.clientX - rect.left) / (rect.width / annual.length)), 0, annual.length - 1);
      $("tm-range").value = annual[i].year; updateTimeMachine();
    };
  }

  const TM = [
    { k: "t_mean", d: 1, unit: "°C", label: "ind_t_mean" },
    { k: "precip_mm", d: 0, unit: "mm", label: "ind_precip_mm" },
    { k: "et0_mm", d: 0, unit: "mm", label: "ind_et0_mm" },
    { k: "hot_days", d: 0, unit: t("u_days"), label: "ind_hot_days" },
  ];
  function setupTimeMachine() {
    const annual = data.climate.annual;
    const r = $("tm-range");
    r.min = annual[0].year;
    r.max = data.climate.shift.t_mean.projection?.year || 2040;
    if (+r.value < +r.min || +r.value > +r.max) r.value = annual.at(-1).year;
    document.querySelector(".tm-ticks").innerHTML = [r.min, data.periods.baseline[1], annual.at(-1).year, r.max].map((y) => `<span>${y}</span>`).join("");
    updateTimeMachine();
  }
  function tmValue(key, year) {
    const sh = data.climate.shift[key];
    if (!sh) return null;
    const obs = data.climate.annual.find((a) => a.year === year);
    if (obs && obs[key] !== null && obs[key] !== undefined) return { v: obs[key], obs: true };
    const b = sh.projection?.band?.find((x) => x.year === year);
    if (b) return { v: b.value, lo: b.low, hi: b.high, obs: false };
    return null;
  }
  function updateTimeMachine() {
    if (!data?.climate) return;
    const year = +$("tm-range").value;
    rangeFill($("tm-range"));
    $("tm-year").textContent = year;
    const last = data.climate.annual.at(-1).year;
    const obs = year <= last;
    $("tm-mode").className = "tm-mode " + (obs ? "obs" : "proj");
    $("tm-mode").textContent = obs ? t("tm_observed") : t("tm_projected");
    const units = { t_mean: "°C", precip_mm: "mm", et0_mm: "mm", hot_days: t("u_days") };
    $("tm-stats").innerHTML = TM.filter((m) => data.climate.shift[m.k]).map((m) => {
      const v = tmValue(m.k, year), base = data.climate.shift[m.k].baseline;
      if (!v) return `<div class="tm-stat"><span class="label">${esc(t(m.label))}</span><span class="v">–</span></div>`;
      const d = v.v - base;
      const cls = Math.abs(d) < (m.d ? 0.05 : 0.5) ? "flat" : d > 0 ? "up" : "down";
      return `<div class="tm-stat"><span class="label">${esc(t(m.label))}</span>
        <span class="v">${fmt(v.v, m.d)}<small class="muted" style="font-size:.5em;margin-left:4px">${esc(units[m.k])}</small></span>
        <span class="d ${cls}">${sgn(d, m.d)} ${esc(t("vs_baseline"))}</span>
        <span class="band">${v.obs ? esc(t("tm_obs_note")) : esc(t("tm_band", { lo: fmt(v.lo, m.d), hi: fmt(v.hi, m.d) }))}</span></div>`;
    }).join("");
  }
  let tmPlay = null;
  function playTimeMachine() {
    const r = $("tm-range");
    if (tmPlay) { clearInterval(tmPlay); tmPlay = null; $("tm-play").firstElementChild.textContent = t("tm_play"); return; }
    if (+r.value >= +r.max) r.value = r.min;
    $("tm-play").firstElementChild.textContent = t("tm_pause");
    tmPlay = setInterval(() => {
      r.value = +r.value + 1; updateTimeMachine();
      if (+r.value >= +r.max) playTimeMachine();
    }, 180);
  }

  function spark(key) {
    const rows = data.climate.annual.filter((r) => r[key] !== null && r[key] !== undefined);
    if (rows.length < 3) return "";
    const w = 220, h = 42, ys = rows.map((r) => r[key]);
    const lo = Math.min(...ys), hi = Math.max(...ys), sp = hi - lo || 1;
    const x = (i) => (i / (rows.length - 1)) * w, y = (v) => h - 3 - ((v - lo) / sp) * (h - 6);
    const line = rows.map((r, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(r[key]).toFixed(1)}`).join("");
    const tl = data.climate.shift[key].trend_line;
    const tx = (yr) => ((yr - rows[0].year) / (rows.at(-1).year - rows[0].year)) * w;
    const trend = tl ? `<path class="tr" d="M${tx(tl[0].year)},${y(tl[0].value)}L${tx(tl[1].year)},${y(tl[1].value)}" stroke="#fff"/>` : "";
    return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true"><path class="ln" d="${line}" stroke="var(--accent)"/>${trend}</svg>`;
  }

  function renderIndicators() {
    const S = data.climate.shift;
    $("indicators").innerHTML = IND.filter((m) => S[m.k] && S[m.k].baseline !== null).map((m) => {
      const s = S[m.k];
      const bad = (s.delta > 0) !== (m.better === "up");
      const flat = Math.abs(s.delta) < Math.pow(10, -m.d);
      const cls = flat ? "flat" : bad ? "bad-t" : "good-t";
      return `<div class="ind reveal">
        <div class="ind-top"><span class="ind-name">${esc(t("ind_" + m.k))}</span>
          <span class="sig ${s.trend_significant ? "yes" : "no"}" title="Mann-Kendall p = ${fmt(s.trend_p_value, 3)}">${esc(s.trend_significant ? t("sig_yes") : t("sig_no"))}</span></div>
        <div class="ind-vals"><span class="from">${fmt(s.baseline, m.d)} →</span><span class="to">${fmt(s.recent, m.d)}</span><span class="unit">${esc(m.unit === "d" ? t("u_days") : m.unit)}</span></div>
        <span class="ind-delta ${cls}">${sgn(s.delta, m.d)}${s.delta_pct !== null && m.k !== "aridity" && m.k !== "soil_wetness" ? ` (${sgn(s.delta_pct, 0)}%)` : ""} · ${esc(t("trend_dec", { v: sgn(s.trend_per_decade, m.d + 1) }))}</span>
        ${spark(m.k)}</div>`;
    }).join("");
  }

  function chartDefaults() {
    if (!window.Chart) return false;
    Chart.defaults.color = "#8592b4";
    Chart.defaults.borderColor = "rgba(140,170,255,.1)";
    Chart.defaults.font.family = "Inter, system-ui, sans-serif";
    Chart.defaults.plugins.legend.labels.usePointStyle = true;
    Chart.defaults.plugins.legend.labels.boxWidth = 8;
    Chart.defaults.plugins.tooltip.backgroundColor = "rgba(4,6,12,.94)";
    Chart.defaults.plugins.tooltip.borderColor = "rgba(140,170,255,.25)";
    Chart.defaults.plugins.tooltip.borderWidth = 1;
    Chart.defaults.plugins.tooltip.padding = 10;
    Chart.defaults.animation.duration = reduceMotion ? 0 : 700;
    return true;
  }
  function chart(id, config) {
    if (!window.Chart) return;
    if (charts[id]) charts[id].destroy();
    charts[id] = new Chart($(id), config);
  }

  function renderMonthly() {
    const M = data.climate.monthly;
    const metrics = [["t", "°C"], ["rain_mm", "mm"], ["et0_mm", "mm"]];
    $("monthly-metric").innerHTML = metrics.map(([k]) => `<button type="button" data-metric="${k}" aria-pressed="${state.metric === k}">${esc(t("mm_" + k))}</button>`).join("");
    const unit = (metrics.find((m) => m[0] === state.metric) || metrics[0])[1];
    const color = { t: "#ff9f5a", rain_mm: "#4cc9f0", et0_mm: "#ffc857" }[state.metric];
    const type = state.metric === "t" ? "line" : "bar";
    chart("monthly-chart", {
      type,
      data: {
        labels: months(),
        datasets: [
          { label: `${data.periods.baseline[0]}–${data.periods.baseline[1]}`, data: M.baseline[state.metric], borderColor: "rgba(200,210,235,.55)", backgroundColor: "rgba(200,210,235,.18)", borderWidth: 2, tension: .35, pointRadius: 0, borderDash: type === "line" ? [5, 4] : undefined, borderRadius: 4 },
          { label: `${data.periods.recent[0]}–${data.periods.recent[1]}`, data: M.recent[state.metric], borderColor: color, backgroundColor: type === "line" ? color + "22" : color + "cc", borderWidth: 2.5, tension: .35, pointRadius: 0, fill: type === "line", borderRadius: 4 },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
        scales: { y: { title: { display: true, text: unit } }, x: { grid: { display: false } } },
        plugins: { tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${fmt(c.parsed.y, 1)} ${unit}` } } },
      },
    });
  }

  function renderFrost() {
    const F = data.climate.frost;
    const host = $("frost-bar");
    if (!F || !F.baseline || !F.recent) { host.innerHTML = `<p class="muted small">${esc(t("no_frost"))}</p>`; $("frost-axis").innerHTML = ""; $("frost-stats").innerHTML = ""; $("frost-sub").textContent = ""; return; }
    const pos = (s) => ((doyOf(s) - 1) / 365) * 100;
    const track = (cls, f, label) => {
      const a = pos(f.last_spring_frost), b = pos(f.first_autumn_frost);
      const seg = b > a ? `<span class="frost-free" style="left:${a}%;width:${b - a}%"></span>` : `<span class="frost-free" style="left:${a}%;right:0"></span><span class="frost-free" style="left:0;width:${b}%"></span>`;
      return `<div class="frost-track ${cls}"><span>${esc(label)}</span>${seg}</div>`;
    };
    host.innerHTML = track("t1", F.baseline, `${data.periods.baseline[0]}–${data.periods.baseline[1]}`) + track("t2", F.recent, `${data.periods.recent[0]}–${data.periods.recent[1]}`);
    $("frost-axis").innerHTML = months().map((m) => `<span>${esc(m.slice(0, 3))}</span>`).join("");
    $("frost-sub").textContent = t("frost_sub");
    const cs = (k, v, dv) => `<div class="cs"><span class="k">${esc(k)}</span><span class="v">${v}</span>${dv ? `<span class="dv">${dv}</span>` : ""}</div>`;
    const dd = (n, goodNeg) => n === null || n === undefined ? "" : `<span class="${n === 0 ? "flat" : (n < 0) === goodNeg ? "good-t" : "bad-t"}">${sgn(n)} ${esc(t("u_days"))}</span>`;
    $("frost-stats").innerHTML =
      cs(t("last_spring_frost"), `${mmdd(F.baseline.last_spring_frost)} → ${mmdd(F.recent.last_spring_frost)}`, dd(F.last_frost_shift_days, true)) +
      cs(t("frost_free_days"), `${fmt(F.baseline.frost_free_days)} → ${fmt(F.recent.frost_free_days)}`, dd(F.frost_free_change_days, false)) +
      cs(t("first_autumn_frost"), `${mmdd(F.baseline.first_autumn_frost)} → ${mmdd(F.recent.first_autumn_frost)}`) +
      cs(t("late_frost_year"), `${mmdd(F.baseline.last_spring_frost_late_year)} → ${mmdd(F.recent.last_spring_frost_late_year)}`);
  }

  // ----- rotations -----
  function renderRotations() {
    const R = data.rotations;
    if (!R || !R.items.length) { $("rot-list").innerHTML = `<div class="empty">${esc(t("no_rotations"))}</div>`; $("rot-lead").textContent = ""; return; }
    $("rot-lead").textContent = t("rot_lead", { n: R.items.length, y: R.years_replayed, from: R.period[0], to: R.period[1], eff: Math.round(R.irrigation_efficiency * 100) });
    const maxW = Math.max(...R.items.map((r) => r.water_m3_ha.p90)) * 1.05;
    $("rot-list").innerHTML = R.items.map((r) => {
      const best = r.id === R.best_id;
      const tags = [best ? `<span class="tag best">${esc(t("tag_best"))}</span>` : "", r.is_current ? `<span class="tag cur">${esc(t("tag_current"))}</span>` : "",
        r.conflicts.length ? `<span class="tag bad">${esc(t("tag_conflict"))}</span>` : "", `<span class="tag">${esc(t("wins_n", { w: r.wins, n: R.years_replayed }))}</span>`].join("");
      const bar = (k) => `<div class="bar-m"><div class="top"><span>${esc(t("w_" + k))}</span><b>${fmt(r.scores[k])}</b></div><div class="track"><i style="background:var(${W[k]});--w:${r.scores[k]}%"></i></div></div>`;
      const v = r.vs_current;
      const vs = v ? `<span>${esc(t("vs_current"))}: <b class="${v.water_m3_ha >= 0 ? "good-t" : "bad-t"}">${sgn(-v.water_m3_ha)} ${esc(t("u_m3ha"))}</b> · <b class="${v.income_usd_ha >= 0 ? "good-t" : "bad-t"}">${sgn(v.income_usd_ha)} ${esc(t("u_usdha"))}</b> · <b class="${v.soil >= 0 ? "good-t" : "bad-t"}">${sgn(v.soil)} ${esc(t("u_soil_pts"))}</b></span>` : "";
      const L = (x) => (x / maxW * 100).toFixed(1);
      return `<article class="rot${best ? " best" : ""}">
        <div class="rot-head"><span class="rank">${r.rank}</span>
          <div class="rot-title"><h3>${esc(nm(r))}</h3><div class="tags">${tags}</div></div>
          <div class="score"><div class="v">${fmt(r.scores.total, 1)}</div><div class="r">${fmt(r.scores.total_range.p10, 0)}–${fmt(r.scores.total_range.p90, 0)} · p10–p90</div></div></div>
        <div class="rot-strip" style="margin-top:0">${stripHtml(r)}</div>
        <div class="bars">${bar("water")}${bar("income")}${bar("soil")}${bar("risk")}</div>
        <div><div class="range-legend"><span>${esc(t("water_range"))}</span><span class="mono">${fmt(r.water_m3_ha.p10)} · <b style="color:var(--water)">${fmt(r.water_m3_ha.p50)}</b> · ${fmt(r.water_m3_ha.p90)} ${esc(t("u_m3ha"))}</span></div>
          <div class="range"><span class="rt"></span><span class="rb" style="left:${L(r.water_m3_ha.p10)}%;width:${L(r.water_m3_ha.p90 - r.water_m3_ha.p10)}%"></span><span class="rm" style="left:${L(r.water_m3_ha.p50)}%"></span></div></div>
        <div class="rot-facts"><span>${esc(t("income"))}: <b>${fmt(r.income_usd_ha.p50)} ${esc(t("u_usdha"))}</b></span><span>${esc(t("risk"))}: <b>${fmt(r.risk_pct.p50)}%</b></span>${vs}</div>
        ${r.conflicts.length ? `<p class="small" style="color:var(--bad)">${esc(t("conflict_text", { a: nm(CROPS(r.conflicts[0].first)), b: nm(CROPS(r.conflicts[0].second)), d: r.conflicts[0].overlap_days }))}</p>` : ""}
      </article>`;
    }).join("");
    requestAnimationFrame(() => document.querySelectorAll(".track i").forEach((i) => { i.style.width = i.style.getPropertyValue("--w"); }));
    renderTradeoff();
  }
  const CROPS = (id) => options.crops.find((c) => c.id === id) || { name: { en: id } };

  function renderTradeoff() {
    const R = data.rotations;
    chart("tradeoff-chart", {
      type: "bubble",
      data: {
        datasets: R.items.map((r) => ({
          label: nm(r),
          data: [{ x: r.water_m3_ha.p50, y: r.income_usd_ha.p50, r: 6 + r.soil.index / 7, soil: r.soil.index }],
          backgroundColor: r.id === R.best_id ? "rgba(134,176,255,.75)" : r.is_current ? "rgba(255,200,87,.7)" : "rgba(200,210,235,.25)",
          borderColor: r.id === R.best_id ? "#c8d6ff" : r.is_current ? "#ffc857" : "rgba(200,210,235,.6)",
          borderWidth: 1.5,
        })),
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        scales: {
          x: { title: { display: true, text: t("axis_water") }, reverse: true, ticks: { callback: (v) => compact(v) } },
          y: { title: { display: true, text: t("axis_income") } },
        },
        plugins: {
          legend: { position: "bottom", labels: { font: { size: 11 } } },
          tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${fmt(c.raw.x)} ${t("u_m3ha")} · ${fmt(c.raw.y)} ${t("u_usdha")} · ${t("w_soil")} ${c.raw.soil}` } },
        },
      },
    });
  }

  // ----- crops -----
  function renderCrops() {
    const list = data.crops || [];
    if (!list.length) { $("crop-grid").innerHTML = `<div class="empty">${esc(t("no_crops"))}</div>`; return; }
    const today = new Date();
    const todayPos = ((Math.round((Date.UTC(2001, today.getMonth(), today.getDate()) - Date.UTC(2001, 0, 1)) / 864e5)) / 365) * 100;
    $("crop-grid").innerHTML = list.map((c) => {
      const a = (doyOf(c.season.sow) - 1) / 365 * 100, len = c.season.days / 365 * 100;
      const seg = a + len <= 100 ? `<span class="s" style="left:${a}%;width:${len}%;background:${cropColor(c.id)}"></span>`
        : `<span class="s" style="left:${a}%;right:0;background:${cropColor(c.id)}"></span><span class="s" style="left:0;width:${a + len - 100}%;background:${cropColor(c.id)}"></span>`;
      const r = c.recent, b = c.baseline;
      const dv = (n, unit) => n === null || n === undefined ? "" : `<span class="dv ${Math.abs(n) < 1 ? "flat" : n > 0 ? "bad-t" : "good-t"}">${sgn(n)} ${esc(unit)} ${esc(t("vs_baseline"))}</span>`;
      const cs = (k, v, unit, extra = "") => `<div class="cs"><span class="k">${esc(k)}</span><span class="v">${v}<small>${esc(unit)}</small></span>${extra}</div>`;
      const sow = c.sowing ? `${mmdd(c.sowing.baseline)} → ${mmdd(c.sowing.recent)}` : "–";
      return `<article class="crop reveal">
        <div class="crop-head"><h3><i style="background:${cropColor(c.id)}"></i>${esc(nm(c))}</h3><span class="lvl ${c.level}">${esc(t("lvl_" + c.level))}</span></div>
        <div><div class="season" title="${esc(mmdd(c.season.sow))} – ${esc(mmdd(c.season.harvest))}">${seg}<span class="today" style="left:${todayPos}%"></span></div>
          <div class="month-axis">${months().map((m) => `<span>${esc(m[0])}</span>`).join("")}</div></div>
        <div class="crop-stats">
          ${cs(t("c_irrigation"), fmt(r.irrigation_m3_ha.p50), t("u_m3ha"), dv(b ? Math.round((r.irrigation_m3_ha.p50 - b.irrigation_m3_ha.p50)) : null, t("u_m3ha")))}
          ${cs(t("c_need"), fmt(r.water_need_mm), "mm", `<span class="dv flat">${esc(t("c_rain", { mm: fmt(r.rain_mm) }))}</span>`)}
          ${cs(t("c_heat"), fmt(r.heat_days.p50), t("u_days"), dv(b ? r.heat_days.p50 - b.heat_days.p50 : null, t("u_days")))}
          ${cs(t("c_sowing"), sow, "", c.sowing ? dv(c.sowing.shift_days, t("u_days")).replace(/bad-t|good-t/, "flat") : "")}
          ${cs(t("c_irrigations"), fmt(r.irrigations), t("u_times"))}
          ${cs(t("c_frost"), fmt(r.frost_years_share * 100), "%", `<span class="dv flat">${esc(t("c_frost_note"))}</span>`)}
        </div></article>`;
    }).join("");
  }

  // ----- now -----
  function renderNow() {
    const N = data.now;
    if (!N || !N.recent) { $("now-tiles").innerHTML = `<div class="empty" style="grid-column:1/-1">${esc(t("no_now"))}</div>`; $("week").innerHTML = ""; return; }
    const r = N.recent, o = N.outlook;
    $("now-lead").textContent = t("now_lead", { date: r.as_of, n: r.window_days });
    const p = clamp(r.rain_percentile ?? 50, 0, 100);
    $("now-tiles").innerHTML = `
      <div class="big"><span class="k">${esc(t("now_rain30"))}</span><span class="v" style="color:var(--water)">${fmt(r.rain_mm, 1)}<small class="muted" style="font-size:.4em"> mm</small></span>
        <span class="n">${esc(t("now_normal", { p10: fmt(r.rain_normal_mm.p10, 0), p50: fmt(r.rain_normal_mm.p50, 0), p90: fmt(r.rain_normal_mm.p90, 0) }))}</span>
        <div class="gauge"><i style="left:${p}%"></i></div><div class="gauge-l"><span>${esc(t("drier"))}</span><span>${esc(t("pct_n", { p }))}</span><span>${esc(t("wetter"))}</span></div></div>
      <div class="big"><span class="k">${esc(t("now_balance"))}</span><span class="v" style="color:${r.balance_mm < 0 ? "var(--heat)" : "var(--good)"}">${sgn(r.balance_mm, 0)}<small class="muted" style="font-size:.4em"> mm</small></span>
        <span class="n">${esc(t("now_balance_note", { rain: fmt(r.rain_mm, 0), et0: fmt(r.et0_mm, 0) }))}</span></div>
      <div class="big"><span class="k">${esc(t("now_dry"))}</span><span class="v">${fmt(r.days_since_rain)}<small class="muted" style="font-size:.4em"> ${esc(t("u_days"))}</small></span>
        <span class="n">${esc(t("now_temp", { t: fmt(r.t_mean, 1) }))}</span></div>
      <div class="big"><span class="k">${esc(t("now_outlook"))}</span><span class="v">${o ? fmt(o.rain_within_7d_probability * 100) + "%" : "–"}</span>
        <span class="n">${o ? esc(t("now_outlook_note", { p50: fmt(o.rain_30d_mm.p50, 0), y: o.years_used })) : ""}</span></div>`;
    const F = N.forecast;
    if (F && F.days?.length) {
      $("forecast-sub").textContent = t("forecast_sub", { src: F.source, n: F.horizon_days });
      chart("forecast-chart", {
        data: {
          labels: F.days.map((d) => { const [, m, dd] = d.date.split("-").map(Number); return `${dd} ${months()[m - 1].slice(0, 3)}`; }),
          datasets: [
            { type: "bar", label: t("rain_mm"), data: F.days.map((d) => d.rain_mm), backgroundColor: "rgba(76,201,240,.7)", borderRadius: 4, yAxisID: "y" },
            { type: "line", label: "ET₀ mm", data: F.days.map((d) => d.et0_mm), borderColor: "#ffc857", backgroundColor: "#ffc857", tension: .35, pointRadius: 2, yAxisID: "y" },
            { type: "line", label: t("tmax"), data: F.days.map((d) => d.t_max), borderColor: "#ff7a8a", borderDash: [4, 4], pointRadius: 0, tension: .35, yAxisID: "y2" },
          ],
        },
        options: {
          responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
          scales: { y: { title: { display: true, text: "mm" }, beginAtZero: true }, y2: { position: "right", grid: { display: false }, title: { display: true, text: "°C" } }, x: { grid: { display: false } } },
        },
      });
    } else {
      $("forecast-sub").textContent = t("forecast_none");
      if (charts["forecast-chart"]) { charts["forecast-chart"].destroy(); delete charts["forecast-chart"]; }
    }
    const wb = N.week_basis;
    $("week-sub").textContent = wb ? t(wb.source === "forecast" ? "week_sub_fc" : "week_sub_clim", { et0: fmt(wb.et0_7d_mm, 1), rain: fmt(wb.rain_7d_mm, 1) }) : "";
    $("week").innerHTML = N.week.length ? `<table class="table"><thead><tr><th>${esc(t("crop"))}</th><th class="r">${esc(t("day_season"))}</th><th class="r">${esc(t("need_mm"))}</th><th class="r">${esc(t("net_mm"))}</th><th class="r">${esc(t("u_m3ha"))}</th></tr></thead><tbody>${
      N.week.map((w) => `<tr><td><span class="crop-dot"><i style="background:${cropColor(w.id)}"></i>${esc(nm(w))}</span></td><td class="r">${w.day_of_season}</td><td class="r">${fmt(w.need_mm, 1)}</td><td class="r">${fmt(w.net_mm, 1)}</td><td class="r"><b>${fmt(w.m3_ha)}</b></td></tr>`).join("")}</tbody></table>`
      : `<div class="empty">${esc(t("week_none"))}</div>`;
  }

  // ----- impact -----
  const AREA_STEPS = [1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 25000, 50000, 100000, 250000, 500000, 1000000];
  function renderImpact() {
    const R = data.rotations;
    $("impact-area").value = state.area;
    const idx = AREA_STEPS.findIndex((a) => a >= state.area);
    $("impact-range").max = AREA_STEPS.length - 1;
    $("impact-range").value = idx < 0 ? AREA_STEPS.length - 1 : idx;
    rangeFill($("impact-range"));
    const grid = $("impact-grid");
    if (!R || !R.items.length) { grid.innerHTML = ""; $("impact-lead").textContent = t("no_rotations"); return; }
    const best = rotById(R.best_id), cur = rotById(R.current_id);
    if (best.id === cur.id) {
      const alt = R.items.find((r) => r.id !== best.id);
      $("impact-lead").textContent = t("impact_lead_keep", { name: nm(best) });
      const diff = alt ? alt.water_m3_ha.p50 - best.water_m3_ha.p50 : 0;
      grid.innerHTML = impactTiles(diff, best.income_usd_ha.p50 - (alt?.income_usd_ha.p50 ?? best.income_usd_ha.p50), true);
      return;
    }
    $("impact-lead").textContent = t("impact_lead", { cur: nm(cur), best: nm(best) });
    grid.innerHTML = impactTiles(best.vs_current.water_m3_ha, best.vs_current.income_usd_ha, false);
  }
  function impactTiles(m3ha, usdha, keep) {
    const A = state.area;
    const m3 = m3ha * A;
    const pools = m3 / 2500;                 // Olympic pool ≈ 2 500 m³
    const people = m3 / (50 * 365 / 1000);   // 50 L per person per day, the WHO basic-access level
    const poolIcons = pools >= 1 ? `<div class="pools" aria-hidden="true">${"<i></i>".repeat(Math.min(60, Math.round(pools)))}</div>` : "";
    return `
      <div class="big"><span class="k">${esc(t(keep ? "imp_water_keep" : "imp_water"))}</span><span class="v" style="color:var(--water)">${compact(Math.abs(m3))}<small class="muted" style="font-size:.4em"> m³/${esc(t("u_year"))}</small></span><span class="n">${esc(t("imp_water_n", { v: fmt(Math.abs(m3ha)), a: fmt(A, A < 10 ? 1 : 0) }))}</span></div>
      <div class="big"><span class="k">${esc(t("imp_pools"))}</span><span class="v">${compact(Math.abs(pools))}</span>${poolIcons}<span class="n">${esc(t("imp_pools_n"))}</span></div>
      <div class="big"><span class="k">${esc(t("imp_people"))}</span><span class="v" style="color:var(--soil)">${compact(Math.abs(people))}</span><span class="n">${esc(t("imp_people_n"))}</span></div>
      <div class="big"><span class="k">${esc(t("imp_income"))}</span><span class="v" style="color:${usdha * A >= 0 ? "var(--income)" : "var(--bad)"}">${usdha * A >= 0 ? "+" : "−"}$${compact(Math.abs(usdha * A))}</span><span class="n">${esc(t("imp_income_n"))}</span></div>`;
  }

  // ----- data & method -----
  function renderData() {
    const P = data.providers || [];
    const st = (s) => ({ live: ["ok", "status_live"], cache: ["ok", "status_cache"], ok: ["ok", "status_ok"], monthly: ["warn", "status_monthly"], fallback: ["warn", "status_fallback"], failed: ["bad", "status_failed"], disabled: ["off", "status_disabled"] }[s] || ["off", s]);
    const ds = Object.fromEntries((data.datasets || []).map((d) => [d.name, d]));
    const desc = { nasa_power: "ds_power", nasa_gibs: "ds_gibs", soilgrids: "ds_soil", open_meteo: "ds_meteo" };
    $("data-lead").textContent = t("data_lead", { ms: fmt(data.timing_ms), days: fmt(data.climate?.data_quality.days ?? 0), last: data.climate?.data_quality.last_day ?? "–" });
    $("datasets").innerHTML = P.map((p) => {
      const [cls, key] = st(p.status);
      const d = ds[p.name] || (p.id === "nasa_gibs" ? ds["NASA GIBS"] : null);
      const chips = p.id === "nasa_power" && d ? d.parameters : p.id === "nasa_gibs" ? layers.map((l) => l.id.split("_").slice(0, 2).join(" ")) : d?.sources || [];
      return `<div class="ds"><div class="ds-head"><h3>${esc(p.name)}</h3>${p.nasa ? '<span class="badge-nasa">NASA</span>' : `<span class="badge-ext">${esc(t("external"))}</span>`}</div>
        <span class="status ${cls}">${esc(t(key))}</span>
        <p class="small muted">${esc(desc[p.id] ? t(desc[p.id]) : "")}</p>
        ${chips.length ? `<div class="chips-s">${chips.map((c) => `<span>${esc(c)}</span>`).join("")}</div>` : ""}
        ${p.message ? `<p class="tiny muted">${esc(p.message)}</p>` : ""}</div>`;
    }).join("");
    $("limits").innerHTML = ["lim1", "lim2", "lim3", "lim4", "lim5"].map((k) => `<li>${esc(t(k))}</li>`).join("");
    $("cite").innerHTML = ["cite_power", "cite_gibs", "cite_fao"].map((k) => `<p>${esc(t(k))}</p>`).join("");
    $("api-link").innerHTML = `${esc(t("api_hint"))} <a class="mono" href="/api/analyze?${esc(query())}" target="_blank" rel="noopener">/api/analyze</a>`;
  }

  // ---------- scroll: reveal + nav spy ----------
  let revealObs = null;
  function observeReveal() {
    if (reduceMotion || !("IntersectionObserver" in window)) { document.querySelectorAll(".reveal").forEach((el) => el.classList.add("in")); return; }
    revealObs ||= new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("in"); revealObs.unobserve(e.target); } }), { rootMargin: "0px 0px -8% 0px" });
    document.querySelectorAll(".reveal:not(.in)").forEach((el) => revealObs.observe(el));
  }
  function navSpy() {
    const links = [...document.querySelectorAll("#sec-nav a")];
    const obs = new IntersectionObserver((es) => es.forEach((e) => {
      if (!e.isIntersecting) return;
      links.forEach((l) => l.setAttribute("aria-current", String(l.hash === "#" + e.target.id)));
    }), { rootMargin: "-45% 0px -50% 0px" });
    links.forEach((l) => { const s = document.querySelector(l.hash); if (s) obs.observe(s); });
  }

  // ---------- events ----------
  function bind() {
    document.querySelectorAll("[data-lang]").forEach((b) => b.addEventListener("click", () => {
      state.lang = b.dataset.lang;
      applyStaticTexts();
      if (options) { renderPassport(); renderLayerChips(); renderPresets(); renderPlace(); drawCell(); }
      analyze();
    }));
    $("place-pill").addEventListener("click", () => { $("setup").scrollIntoView({ behavior: "smooth" }); setTimeout(() => $("place-search").focus(), 400); });
    $("locate").addEventListener("click", locate);
    $("presets").addEventListener("click", (e) => { const b = e.target.closest("[data-lat]"); if (b) setPoint(+b.dataset.lat, +b.dataset.lon, true, ""); });
    $("layer-chips").addEventListener("click", (e) => {
      const b = e.target.closest("[data-layer]"); if (!b) return;
      if (state.layer !== b.dataset.layer) state.layerDate = "";
      state.layer = b.dataset.layer;
      document.querySelectorAll("#layer-chips .chip").forEach((c) => c.setAttribute("aria-pressed", String(c === b)));
      showOverlay(); save();
    });
    $("layer-date").addEventListener("change", (e) => { state.layerDate = e.target.value; showOverlay(); save(); });
    $("opacity").addEventListener("input", (e) => { state.opacity = +e.target.value; rangeFill(e.target); if (overlay) overlay.setOpacity(state.opacity / 100); save(); });

    const input = $("place-search");
    input.addEventListener("input", () => {
      clearTimeout(placeTimer);
      const q = input.value.trim();
      if (q.length < 3) { hideResults(); $("search-status").textContent = ""; return; }
      placeTimer = setTimeout(() => searchPlaces(q), 320);
    });
    input.addEventListener("keydown", (e) => {
      if (!results.length) return;
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        active = (active + (e.key === "ArrowDown" ? 1 : -1) + results.length) % results.length;
        [...$("place-results").children].forEach((li, i) => li.setAttribute("aria-selected", String(i === active)));
        input.setAttribute("aria-activedescendant", "pr-" + active);
      } else if (e.key === "Enter") { e.preventDefault(); choose(active < 0 ? 0 : active); }
      else if (e.key === "Escape") hideResults();
    });
    $("place-results").addEventListener("mousedown", (e) => { const li = e.target.closest("[data-i]"); if (li) { e.preventDefault(); choose(+li.dataset.i); } });
    input.addEventListener("blur", () => setTimeout(hideResults, 150));

    $("current").addEventListener("change", (e) => { state.current = e.target.value; $("builder").hidden = state.current !== "custom"; analyzeSoon(50); });
    $("builder-years").addEventListener("change", (e) => {
      const s = e.target.closest("select"); if (!s) return;
      state.customYears[+s.dataset.y][+s.dataset.k] = s.value; analyzeSoon(50);
    });
    $("add-year").addEventListener("click", () => { state.customYears.push(["winter_wheat", ""]); renderBuilder(); analyzeSoon(50); });
    $("remove-year").addEventListener("click", () => { state.customYears.pop(); renderBuilder(); analyzeSoon(50); });
    $("irrigation").addEventListener("click", (e) => { const b = e.target.closest("[data-irr]"); if (!b) return; state.irrigation = b.dataset.irr; [...$("irrigation").children].forEach((c) => c.setAttribute("aria-pressed", String(c === b))); analyzeSoon(50); });
    $("soil").addEventListener("click", (e) => { const b = e.target.closest("[data-soil]"); if (!b) return; state.soil = b.dataset.soil; [...$("soil").children].forEach((c) => c.setAttribute("aria-pressed", String(c === b))); analyzeSoon(50); });
    document.addEventListener("input", (e) => {
      const w = e.target.closest("input[data-w]");
      if (!w) return;
      state.weights[w.dataset.w] = +w.value;
      document.querySelectorAll(`input[data-w="${w.dataset.w}"]`).forEach((x) => { if (x !== w) x.value = w.value; rangeFill(x); });
      Object.keys(W).forEach((k) => document.querySelectorAll(`[data-wo="${k}"]`).forEach((o) => { o.textContent = pct(k) + "%"; }));
      analyzeSoon(350);
    });
    const setArea = (v) => { if (!(v > 0)) return; state.area = Math.min(1e6, v); $("area").value = state.area; save(); if (data) renderImpact(); };
    $("area").addEventListener("change", (e) => setArea(+e.target.value));
    $("impact-area").addEventListener("change", (e) => setArea(+e.target.value));
    $("impact-range").addEventListener("input", (e) => setArea(AREA_STEPS[+e.target.value]));
    $("monthly-metric").addEventListener("click", (e) => { const b = e.target.closest("[data-metric]"); if (!b) return; state.metric = b.dataset.metric; save(); renderMonthly(); });
    $("tm-range").addEventListener("input", updateTimeMachine);
    $("tm-play").addEventListener("click", playTimeMachine);

    $("share-btn").addEventListener("click", async () => {
      const url = syncUrl() + "#verdict";
      const best = data?.rotations && rotById(data.rotations.best_id);
      const text = best ? t("share_text", { place: placeTitle(), name: nm(best) }) : "TerraShift";
      try {
        if (navigator.share && matchMedia("(pointer: coarse)").matches) await navigator.share({ title: "TerraShift", text, url });
        else { await navigator.clipboard.writeText(url); toast(t("link_copied")); }
      } catch { /* user closed the share sheet */ }
    });
    $("print-btn").addEventListener("click", () => {
      document.querySelectorAll(".reveal").forEach((el) => el.classList.add("in"));
      Object.values(charts).forEach((c) => c.resize());
      setTimeout(() => window.print(), 150);
    });
    let rs = null;
    window.addEventListener("resize", () => { clearTimeout(rs); rs = setTimeout(() => { if (data?.climate) drawStripes(); }, 150); });
  }

  // ---------- start ----------
  async function start() {
    applyStaticTexts();
    chartDefaults();
    bind();
    navSpy();
    observeReveal();
    initMap();
    renderPlace();
    setLoading(true);
    try {
      [options, layers] = await Promise.all([api("/api/options"), api("/api/layers").catch(() => [])]);
    } catch (err) {
      $("alerts").innerHTML = alertHtml("critical", t("error", { msg: err.message }));
      setLoading(false);
      return;
    }
    renderPassport();
    renderPresets();
    renderPlace();
    renderLayerChips();
    analyze();
  }
  start();
})();
