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
    weights: { water: 40, income: 20, soil: 20, risk: 20 }, layer: "", opacity: 70, metric: "t_mean", locationLabel: "",
  }, saved);
  const save = () => { try { localStorage.setItem("terrashift", JSON.stringify(state)); } catch { /* private mode */ } };

  let options = null, data = null, map = null, marker = null, overlay = null, layers = [];
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
  function analyzeSoon(delay = 250) { clearTimeout(timer); timer = setTimeout(analyze, delay); }

  async function analyze() {
    save();
    if (controller) controller.abort();
    const requestController = new AbortController();
    controller = requestController;
    const q = new URLSearchParams({
      lat: state.lat, lon: state.lon, lang: state.lang, soil: state.soil, irrigation: state.irrigation,
      w_water: state.weights.water, w_income: state.weights.income, w_soil: state.weights.soil, w_risk: state.weights.risk,
    });
    if (state.current === "custom") {
      q.set("custom", state.customYears.map((y) => y.filter(Boolean).join("+")).filter(Boolean).join("|"));
    } else if (state.current) q.set("current", state.current);
    if ($("content")) {
      $("content").classList.add("loading");
      $("content").setAttribute("aria-busy", "true");
    }
    if ($("analysis-status")) $("analysis-status").textContent = t("analyzing");
    if (!data && $("verdict")) $("verdict").textContent = t("loading");
    try {
      data = await api(`/api/analyze?${q}`, { signal: requestController.signal });
      render();
      if ($("analysis-status")) $("analysis-status").textContent = t("analysis_updated");
    } catch (err) {
      if (err.name === "AbortError") return;
      if ($("warnings")) $("warnings").innerHTML = alertHtml("critical", t("error", { msg: err.message }));
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
    map = L.map("map", { zoomControl: true, attributionControl: true }).setView([state.lat, state.lon], 7);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, attribution: "© OpenStreetMap" }).addTo(map);
    marker = L.marker([state.lat, state.lon], { icon: L.divIcon({ className: "", html: '<div class="pin"></div>', iconSize: [18, 18], iconAnchor: [9, 9] }) }).addTo(map);
    map.on("click", (e) => setPoint(e.latlng.lat, e.latlng.lng, false, ""));
  }

  function setPoint(lat, lon, recenter = true, locationLabel = "") {
    if (!map || !marker) return;
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
        `<option value="${esc(m.id)}">${esc(name(m))} · ${esc(t("efficiency", { pct: Math.round(m.efficiency * 100) }))}</option>`).join("");
      $("irrigation").value = state.irrigation;
    }
    if ($("soil")) {
      $("soil").innerHTML = `<option value="auto">${esc(t("soil_auto"))}</option>` +
        options.soils.map((s) => `<option value="${esc(s.id)}">${esc(name(s))}</option>`).join("");
      $("soil").value = state.soil;
    }
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

  function renderWeights() {
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
    const ok = !!data.rotations;
    if (!ok) {
      if ($("verdict")) $("verdict").textContent = t("no_data_title");
      if ($("verdict-sub")) $("verdict-sub").textContent = t("no_data_sub");
      if ($("advice-top")) $("advice-top").innerHTML = "";
    } else if ($("verdict") || $("verdict-sub") || $("advice-top")) renderVerdict();
    if (ok) {
      if ($("rotations")) renderRotations();
      if ($("climate-card")) renderClimate();
      if ($("crops")) renderCrops();
      if ($("now-card")) renderNow();
    }
    if ($("datasets")) renderSources();
  }

  function renderChips() {
    if (!$("chips")) return;
    const cls = { ok: "ok", live: "ok", cache: "ok", monthly: "warn", fallback: "warn", disabled: "warn", failed: "bad", down: "bad" };
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
    if ($("verdict")) $("verdict").textContent = t(best.is_current ? "verdict_keep" : "verdict_best", { name: name(best) });
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

  function renderRotations() {
    const r = data.rotations;
    $("rotations-meta").textContent = t("rotations_meta", { n: r.years_replayed, method: methodName() });
    const maxOf = (key) => Math.max(...r.items.map((it) => it[key].p90)) * 1.05;
    const mWater = maxOf("water_m3_ha"), mIncome = maxOf("income_usd_ha");
    $("rotations").innerHTML = r.items.map((it) => {
      const s = it.scores, tr = s.total_range, vs = it.vs_current;
      const badges = [
        it.id === r.best_id ? `<span class="badge best">${esc(t("badge_best"))}</span>` : "",
        it.is_current ? `<span class="badge">${esc(t("badge_current"))}</span>` : "",
        it.conflicts.length ? `<span class="badge bad">${esc(t("badge_conflict"))}</span>` : "",
      ].join("");
      const seq = it.years.map((slot, i) => `<span><b>${esc(t("year_n", { n: i + 1 }))}:</b> ${slot.map((c) => esc(name(c))).join(" + ")}</span>`).join("");
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
      <article class="rot${it.id === r.best_id ? " best" : ""}">
        <div class="rot-head">
          <div class="rot-title"><span class="rank">#${it.rank}</span><span class="rot-name">${esc(name(it))}</span>${badges}</div>
          <div class="score">${fmt(s.total, 1)} <small>${esc(t("score_of"))}</small></div>
        </div>
        <div class="seq">${seq}</div>
        <div class="track" title="${esc(t("range", { a: fmt(tr.p10, 1), b: fmt(tr.p90, 1) }))}">
          <div class="range" style="left:${tr.p10}%;width:${Math.max(tr.p90 - tr.p10, 1)}%"></div><div class="mark" style="left:${s.total}%"></div>
        </div>
        <div class="crit">
          ${crit(t("c_water"), t("u_water"), fmt(it.water_m3_ha.p50), it.water_m3_ha, rangeBar(it.water_m3_ha, mWater), t("range", { a: fmt(it.water_m3_ha.p10), b: fmt(it.water_m3_ha.p90) }))}
          ${crit(t("c_income"), t("u_income"), fmt(it.income_usd_ha.p50), it.income_usd_ha, rangeBar(it.income_usd_ha, mIncome), t("range", { a: fmt(it.income_usd_ha.p10), b: fmt(it.income_usd_ha.p90) }))}
          ${crit(t("c_risk"), t("u_risk"), fmt(it.risk_pct.p50), it.risk_pct, rangeBar(it.risk_pct, 100), t("range", { a: fmt(it.risk_pct.p10), b: fmt(it.risk_pct.p90) }))}
          ${crit(t("c_soil"), t("u_soil"), fmt(it.soil.index), null, rangeBar(null, 100, it.soil.index), t("soil_parts", it.soil.parts))}
        </div>
        <div class="rot-foot"><span>${esc(t("wins", { wins: it.wins, n: r.years_replayed }))}</span>${foot}</div>
      </article>`;
    }).join("");
  }

  function chart(id, config) {
    if (charts[id]) charts[id].destroy();
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

  function renderClimate() {
    const c = data.climate, p = data.periods;
    $("climate-meta").textContent = t("climate_meta", { b0: p.baseline[0], b1: p.baseline[1], r0: p.recent[0], r1: p.recent[1], method: c.et0_method.name });
    const digits = { t_mean: 1, aridity: 2, t_max: 1 };
    const tiles = ["t_mean", "precip_mm", "et0_mm", "hot_days", "dry_spell_days"].filter((k) => c.shift[k]);
    $("kpis").innerHTML = tiles.map((k) => {
      const s = c.shift[k], d = digits[k] || 0;
      return `<div class="kpi"><span class="k">${esc(t("k_" + k))}</span>
        <span class="v">${sgn(s.delta, d)} ${esc(t("unit_" + k))}</span>
        <span class="d">${esc(t("before_now", { a: fmt(s.baseline, d), b: fmt(s.recent, d) }))}</span>
        <span class="d">${esc(t(s.trend_significant ? "sig_yes" : "sig_no"))}</span></div>`;
    }).join("");

    const order = ["t_mean", "precip_mm", "et0_mm", "hot_days", "frost_days", "dry_spell_days", "rain_days", "aridity", "t_max"].filter((k) => c.shift[k]);
    if (!order.includes(state.metric)) state.metric = "t_mean";
    $("metric").innerHTML = order.map((k) => `<option value="${k}">${esc(t("k_" + k))}${t("unit_" + k) ? ", " + esc(t("unit_" + k)) : ""}</option>`).join("");
    $("metric").value = state.metric;
    renderAnnual();

    $("legend-base").textContent = `${p.baseline[0]}–${p.baseline[1]}`;
    $("legend-recent").textContent = `${p.recent[0]}–${p.recent[1]}`;
    const months = t("months");
    for (const [id, key] of [["m-t", "t"], ["m-rain", "rain_mm"], ["m-et0", "et0_mm"]]) {
      const line = (label, values, color) => ({ label, data: values, borderColor: color, backgroundColor: color, borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0.3 });
      chart(id, { type: "line", data: { labels: months, datasets: [
        line(`${p.baseline[0]}–${p.baseline[1]}`, c.monthly.baseline[key], css("--s1")),
        line(`${p.recent[0]}–${p.recent[1]}`, c.monthly.recent[key], css("--s2")),
      ] }, options: baseOptions() });
    }
    $("advice-climate").innerHTML = adviceHtml("climate");
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

  function renderCrops() {
    const pill = (lv) => `<span class="pill ${lv}">${{ low: "✓", moderate: "!", high: "▲" }[lv]} ${esc(t("level_" + lv))}</span>`;
    const head = ["th_crop", "th_season", "th_need", "th_irrig", "th_gross", "th_heat", "th_sowing", "th_level"].map((k) => `<th>${esc(t(k))}</th>`).join("");
    $("crops").innerHTML = `<thead><tr>${head}</tr></thead><tbody>` + data.crops.map((c) => {
      const r = c.recent, sow = c.sowing;
      return `<tr>
        <td><b>${esc(name(c))}</b>${c.legume ? `<span class="sub">${esc(t("legume"))}</span>` : ""}</td>
        <td>${md(c.season.sow)} – ${md(c.season.harvest)}<span class="sub">${c.season.days} ${esc(t("unit_hot_days"))}</span></td>
        <td class="num">${fmt(r.water_need_mm)} mm<span class="sub">${esc(t("rain_covers", { mm: fmt(r.rain_mm) }))}</span></td>
        <td class="num">${fmt(r.irrigation_mm.p50)} mm<span class="sub">${esc(t("range", { a: fmt(r.irrigation_mm.p10), b: fmt(r.irrigation_mm.p90) }))} · ${esc(t("irrigations", { n: r.irrigations }))}${c.irrigation_change_mm !== null ? " · " + esc(t("change_since", { d: sgn(c.irrigation_change_mm) })) : ""}</span></td>
        <td class="num">${fmt(r.irrigation_m3_ha.p50)} ${esc(t("m3ha"))}<span class="sub">${esc(t("range", { a: fmt(r.irrigation_m3_ha.p10), b: fmt(r.irrigation_m3_ha.p90) }))}</span></td>
        <td class="num">${fmt(r.heat_days.p50)} (${fmt(r.heat_days.p10)}–${fmt(r.heat_days.p90)})<span class="sub">${esc(t("heat_rule", { thr: c.heat_rule.tmax_c }))} · ${esc(t("heat_years", { pct: Math.round(r.heat_years_share * 100), limit: c.heat_rule.limit_days }))}</span></td>
        <td class="num">${sow ? md(sow.recent) : "–"}${sow ? `<span class="sub">${md(sow.baseline)} → ${md(sow.recent)} · ${esc(t("sowing_shift", { d: sgn(sow.shift_days) }))}</span>` : ""}</td>
        <td>${pill(c.level)}</td></tr>`;
    }).join("") + "</tbody>";
    $("advice-crops").innerHTML = adviceHtml("crops");
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
      requestAnimationFrame(() => {
        map.invalidateSize({ pan: false });
        $("close-map").focus();
      });
    });
    on("close-map", "click", () => $("map-dialog").close());
    on("map-dialog", "keydown", (e) => {
      if (e.key === "Escape" && !e.defaultPrevented) {
        e.preventDefault();
        $("map-dialog").close();
      }
    });
    on("map-dialog", "close", () => {
      if (workspace && fullscreenHost && workspace.parentElement === fullscreenHost && workspaceHome) {
        workspaceHome.insertBefore(workspace, workspaceNext && workspaceNext.parentElement === workspaceHome ? workspaceNext : null);
      }
      if (map) requestAnimationFrame(() => map.invalidateSize({ pan: false }));
      $("open-map").focus();
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
    on("current", "change", (e) => { state.current = e.target.value; renderBuilder(); analyze(); });
    on("irrigation", "change", (e) => { state.irrigation = e.target.value; analyze(); });
    on("soil", "change", (e) => { state.soil = e.target.value; analyze(); });
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
  }

  function showProviderError(err) {
    const message = t("error", { msg: err.message });
    if ($("provider-msg")) $("provider-msg").textContent = message;
    else if ($("providers")) $("providers").textContent = message;
  }

  // ---------- start ----------
  async function start() {
    if (window.Chart) {
      Chart.defaults.font.family = css("--font");
      Chart.defaults.font.size = 12;
    }
    applyStaticTexts();
    if ($("opacity")) $("opacity").value = state.opacity;
    initMap();
    bind();
    try {
      [options, layers] = await Promise.all([
        api("/api/options"),
        $("map") ? api("/api/layers") : Promise.resolve([]),
      ]);
    } catch (err) {
      if ($("warnings")) $("warnings").innerHTML = alertHtml("critical", t("error", { msg: err.message }));
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
