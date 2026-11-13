/* TerraShift site. One page, no build step: Leaflet for the map, Chart.js for charts. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const on = (id, event, handler) => { const el = $(id); if (el) el.addEventListener(event, handler); };
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // ---------- state ----------
  const saved = (() => { try { return JSON.parse(localStorage.getItem("terrashift") || "{}"); } catch { return {}; } })();
  if (!saved.picked) { delete saved.lat; delete saved.lon; delete saved.locationLabel; }  // old builds saved a default point
  const state = Object.assign({
    lat: null, lon: null, picked: false, lang: "uz", soil: "auto", irrigation: "furrow", current: null,
    customYears: [["cotton", ""], ["winter_wheat", ""]],
    weights: { water: 40, income: 20, soil: 20, risk: 20 }, layer: "", opacity: 70, metric: "t_mean", locationLabel: "",
  }, saved);
  const save = () => { try { localStorage.setItem("terrashift", JSON.stringify(state)); } catch { /* private mode */ } };

  let options = null, data = null, map = null, marker = null, overlay = null, outline = null, layers = [];
  let placeController = null, placeResults = [], activePlaceIndex = -1;
  const hasPoint = () => state.picked && Number.isFinite(state.lat) && Number.isFinite(state.lon);
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
    if (!hasPoint()) { renderNoPoint(); return; }
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
    map = L.map("map", { zoomControl: true, attributionControl: true, worldCopyJump: true });
    if (hasPoint()) map.setView([state.lat, state.lon], 10);
    else map.setView([25, 15], 2);  // the whole world: nothing is chosen until the user searches, locates or clicks
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap" }).addTo(map);
    map.on("click", (e) => { clearOutline(); setPoint(e.latlng.lat, e.latlng.lng, false, ""); });
  }

  function pinIcon(status) {
    return L.divIcon({ className: "", html: `<div class="pin${status ? " " + status : ""}"></div>`, iconSize: [18, 18], iconAnchor: [9, 9] });
  }

  function setPoint(lat, lon, recenter = true, locationLabel = "", zoom = 13) {
    if (!map) return;
    state.lat = Math.round(lat * 1e4) / 1e4;
    state.lon = Math.round((((lon + 180) % 360 + 360) % 360 - 180) * 1e4) / 1e4;  // wrap any world copy to -180..180
    state.picked = true;
    if (state.current !== "custom") state.current = null;  // each region has its own typical rotation
    state.locationLabel = locationLabel;
    if (!marker) marker = L.marker([state.lat, state.lon], { icon: pinIcon("checking") }).addTo(map);
    marker.setLatLng([state.lat, state.lon]).setIcon(pinIcon("checking"));
    if (recenter) map.setView([state.lat, state.lon], Math.max(map.getZoom(), zoom));
    $("coords").textContent = `${state.lat.toFixed(4)}, ${state.lon.toFixed(4)}`;
    if ($("place-search") && locationLabel) $("place-search").value = locationLabel;
    if ($("place-info")) $("place-info").textContent = locationLabel ? t("place_selected", { place: locationLabel }) : "";
    analyze();
  }

  function clearOutline() { if (outline && map) { map.removeLayer(outline); outline = null; } }

  // Show a found place: outline and whole extent for a country or region, a close view for a village.
  function showPlace(place) {
    clearOutline();
    if (place.outline) {
      outline = L.geoJSON(place.outline, { interactive: false, style: { color: css("--accent-strong") || "#2563eb", weight: 2, fillOpacity: 0.06 } }).addTo(map);
    }
    const b = place.bbox;
    const big = !!b && (Math.abs(b[2] - b[0]) > 0.05 || Math.abs(b[3] - b[1]) > 0.05);
    if (big) {
      map.fitBounds([[b[0], b[1]], [b[2], b[3]]], { padding: [16, 16], maxZoom: 13 });
      setPoint(place.lat, place.lon, false, place.label);
      if ($("place-info")) $("place-info").textContent = t("place_selected", { place: place.label }) + " " + t("place_area_hint");
    } else {
      setPoint(place.lat, place.lon, true, place.label, 15);
    }
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
      (pos) => { setPending(false); clearOutline(); setPoint(pos.coords.latitude, pos.coords.longitude, true, t("my_location"), 15); },
      (err) => { fail(err.code === 1 ? "locate_denied" : "locate_unavailable"); },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 });
  }

  function hidePlaceResults() {
    const list = $("place-results"), input = $("place-search");
    if (!list || !input) return;
    list.hidden = true;
    list.replaceChildren();
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
    activePlaceIndex = -1;
  }

  function renderPlaceResults(chosen) {
    const list = $("place-results");
    if (!list) return;
    activePlaceIndex = -1;
    if (placeResults.length < 2) { hidePlaceResults(); return; }
    list.innerHTML = placeResults.map((place, index) => `
      <li role="presentation"><button type="button" class="place-option${index === chosen ? " active" : ""}" role="option" id="place-result-${index}" aria-selected="${index === chosen}" tabindex="-1" data-place-index="${index}">
        <span>${esc(place.name)}</span>${place.context ? `<small>${esc(place.context)}</small>` : ""}
      </button></li>`).join("");
    list.hidden = false;
    $("place-search").setAttribute("aria-expanded", "true");
  }

  async function searchPlaces(query) {
    if (placeController) placeController.abort();
    const requestController = new AbortController();
    placeController = requestController;
    $("place-search-status").textContent = t("place_searching");
    $("place-search").setAttribute("aria-busy", "true");
    if ($("place-go")) $("place-go").disabled = true;
    try {
      const params = new URLSearchParams({ q: query, limit: 5, lang: state.lang });
      const result = await api(`/api/places?${params}`, { signal: requestController.signal });
      if (placeController !== requestController) return;
      placeResults = (Array.isArray(result.results) ? result.results : [])
        .filter((p) => Number.isFinite(p.lat) && Number.isFinite(p.lon) && Math.abs(p.lat) <= 90 && Math.abs(p.lon) <= 180);
      if (!placeResults.length) {
        hidePlaceResults();
        $("place-search-status").textContent = t("place_search_empty");
        return;
      }
      $("place-search-status").textContent = placeResults.length > 1 ? t("place_search_count", { n: placeResults.length }) : "";
      renderPlaceResults(0);
      showPlace(placeResults[0]);
    } catch (err) {
      if (err.name === "AbortError") return;
      if (placeController === requestController) {
        hidePlaceResults();
        $("place-search-status").textContent = t("place_search_error");
      }
    } finally {
      if (placeController === requestController) {
        $("place-search").setAttribute("aria-busy", "false");
        if ($("place-go")) $("place-go").disabled = false;
      }
    }
  }

  function choosePlace(index) {
    const place = placeResults[index];
    if (!place) return;
    $("place-search-status").textContent = "";
    renderPlaceResults(index);
    showPlace(place);
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
    renderCurrentSelect();
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

  // Rotations differ by region, so the "current rotation" list is filled from the latest analysis.
  function renderCurrentSelect() {
    const sel = $("current");
    if (!sel) return;
    const items = data && data.rotations ? data.rotations.items : [];
    const origin = (data && data.region && data.region.origin_text) || {};
    const typical = items.filter((r) => r.origin === "typical" || r.is_current);
    const rest = items.filter((r) => !typical.includes(r));
    sel.innerHTML = (items.length
      ? [...typical, ...rest].map((r) => `<option value="${esc(r.id)}">${esc(name(r))}${origin[r.origin] ? " · " + esc(origin[r.origin]) : ""}</option>`).join("")
      : `<option value="">${esc(t(hasPoint() ? "current_none" : "current_pick_place"))}</option>`) +
      `<option value="custom">${esc(t("custom_rotation"))}</option>`;
    sel.value = state.current === "custom" ? "custom" : (data && data.rotations ? data.rotations.current_id : "");
    if ($("builder")) $("builder").hidden = sel.value !== "custom";
  }

  function renderWeights() {
    if (!$("sliders")) return;
    const sum = Object.values(state.weights).reduce((a, b) => a + b, 0) || 1;
    for (const k in state.weights) $("o-" + k).textContent = Math.round(100 * state.weights[k] / sum) + "%";
  }

  function renderBuilder() {
    if (!$("builder-years")) return;
    $("builder").hidden = !$("current") || $("current").value !== "custom";
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

  // Card shown on every page: can crops grow at this point at all, and why not.
  function suitCard() {
    let card = $("suit-card");
    if (!card) {
      const main = document.querySelector("main");
      if (!main) return null;
      card = document.createElement("section");
      card.id = "suit-card";
      card.className = "card suit";
      card.setAttribute("aria-live", "polite");
      card.hidden = true;
      main.prepend(card);
    }
    return card;
  }

  function renderSuitability() {
    const s = data.suitability, card = suitCard();
    if (marker) marker.setIcon(pinIcon(s ? s.status : ""));
    if (!card) return;
    if (!s || (s.status === "ok" && !s.items.length && !s.note)) { card.hidden = true; return; }
    const lv = { unsuitable: "critical", limited: "warning", info: "info" };
    const items = s.items.map((r) => `
      <li class="${lv[r.level] || "info"}"><span class="ico" aria-hidden="true">${ICON[lv[r.level]] || "i"}</span>
        <span><b>${esc(r.title)}</b><br>${esc(r.detail)}</span></li>`).join("");
    card.className = `card suit ${s.status}`;
    card.innerHTML = `
      <div class="eyebrow">${esc(t("suit_eyebrow"))}</div>
      <h2>${esc(s.headline)}</h2>
      <p class="lead">${esc(s.summary)}</p>
      ${items ? `<ul class="advice">${items}</ul>` : ""}
      ${s.todo ? `<p class="todo">${esc(s.todo)}</p>` : ""}
      ${s.land && s.land.place ? `<p class="hint">${esc(t("suit_place", { place: s.land.place }))}</p>` : ""}
      ${s.facts ? `<p class="hint">${esc(t("suit_facts"))} ${esc(s.facts)}</p>` : ""}
      ${s.terrain ? `<p class="hint">${esc(s.terrain)}</p>` : ""}
      ${s.note ? `<p class="hint">${esc(s.note)}</p>` : ""}`;
    card.hidden = false;
  }

  // "What is grown in <country>": FAOSTAT shares, whether each crop works at this point, and income.
  function renderRegion() {
    const card = $("region-card");
    if (!card) return;
    const r = data.region;
    if (!r) { card.hidden = true; return; }
    const pct = (v) => (v >= 0.1 ? Math.round(v * 100) : Math.round(v * 1000) / 10) + "%";
    const max = Math.max(...r.top.map((x) => x.share), 0.01);
    const rows = r.top.map((x) => `
      <li class="${x.here === "yes" ? "yes" : x.here === "no" ? "no" : "na"}">
        <span class="nm">${esc(x.name)}</span>
        <span class="bar" aria-hidden="true"><span style="width:${Math.max(2, 100 * x.share / max)}%"></span></span>
        <span class="pc">${pct(x.share)}</span>
        <span class="here" title="${esc(x.reason || "")}">${x.here === "yes" ? "✓ " : x.here === "no" ? "✕ " : ""}${esc(x.here_text)}${x.reason ? `<small>${esc(x.reason)}</small>` : ""}</span>
      </li>`).join("");
    const econ = Object.entries(r.economics || {});
    const table = econ.length ? `
      <div class="table-wrap" role="region" tabindex="0" aria-label="${esc(t("region_econ_title"))}"><table class="econ">
        <thead><tr><th>${esc(t("th_crop"))}</th><th>${esc(t("region_sow"))}</th><th>${esc(t("region_yield"))}</th><th>${esc(t("region_price"))}</th><th>${esc(t("region_income"))}</th></tr></thead>
        <tbody>${econ.map(([id, e]) => `<tr><td><b>${esc(e.name)}</b>${r.suggested.includes(id) ? `<span class="sub">${esc(t("region_new"))}</span>` : ""}</td>
          <td>${md(r.sowing[id])}</td>
          <td class="num">${e.yield_t_ha != null ? fmt(e.yield_t_ha, 1) + " " + t("u_tha") : "–"}</td>
          <td class="num">${e.price_usd_t != null ? "$" + fmt(e.price_usd_t) : "–"}</td>
          <td class="num">$${fmt(e.usd_ha)}<span class="sub">${esc(e.source_text)}</span></td></tr>`).join("")}</tbody>
      </table></div>` : "";
    card.innerHTML = `
      <div class="eyebrow">${esc(t("region_eyebrow"))}</div>
      <h2 id="region-title">${esc(r.title)}</h2>
      <p class="lead">${esc(r.summary)}</p>
      ${rows ? `<ul class="shares">${rows}</ul>` : ""}
      ${r.suggested_text ? `<p class="hint">${esc(r.suggested_text)}</p>` : ""}
      ${r.field_history ? `<h3>${esc(t("region_history", { county: r.county ? r.county.county + ", " + r.county.state : "" }))}</h3>
        <ol class="history">${r.field_history.map((h) => `<li><b>${h.year}</b> ${esc(h.crop_ids && h.crop_ids.length ? h.crop_ids.map((id) => name(options.crops.find((c) => c.id === id))).join(" + ") : h.name)}</li>`).join("")}</ol>
        <p class="hint">${esc(t(r.field_rotation_exact ? "region_history_exact" : "region_history_approx"))}</p>` : ""}
      ${econ.length ? `<h3>${esc(t("region_econ_title"))}</h3>${table}<p class="hint">${esc(t("region_econ_note"))}</p>` : ""}
      ${r.source_text ? `<p class="hint">${esc(r.source_text)}</p>` : ""}`;
    card.hidden = false;
  }

  function seenText(s) {
    const parts = [];
    if (s.ndvi) parts.push(t("wk_seen_ndvi", { v: fmt(s.ndvi.ndvi, 2), st: t("obs_ndvi_" + s.ndvi.state), d: isoDay(s.ndvi.date), src: s.ndvi.source }));
    if (s.smap) parts.push(t("wk_seen_smap", { v: fmt(s.smap.rootzone * 100, 0) }));
    if (s.rain_7d_observed_mm != null) parts.push(t("wk_seen_rain", { v: fmt(s.rain_7d_observed_mm, 0) }));
    return t("wk_seen") + " " + parts.join(" · ");
  }

  // This week's advice for the region's main crops, from the next 7 days of weather.
  function renderWeekPlan() {
    const card = $("week-card");
    if (!card) return;
    const w = data.week_plan;
    if (!w || !w.crops.length) { card.hidden = true; return; }
    const s = w.summary, dOf = (iso) => isoDay(iso);
    const range = s.rain_range_mm ? ` (${fmt(s.rain_range_mm[0], 0)}–${fmt(s.rain_range_mm[1], 0)})` : "";
    const kpis = [
      [t("wk_rain"), `${fmt(s.rain_mm, 0)} mm${range}`, s.rain_5mm_probability != null ? t("wk_rain_p", { p: Math.round(s.rain_5mm_probability * 100) }) : ""],
      [t("wk_et0"), `${fmt(s.et0_mm, 0)} mm`, t("wk_et0_d")],
      [t("wk_sun"), s.sun_mj_mean != null ? `${fmt(s.sun_mj_mean, 1)} MJ/m²` : "–", t("wk_sun_d")],
      [t("wk_air"), s.tmax_max != null ? `${fmt(s.tmin_min, 0)} … ${fmt(s.tmax_max, 0)} °C` : "–", s.frost_nights ? t("wk_frost_n", { n: s.frost_nights }) : s.hot_days ? t("wk_hot_n", { n: s.hot_days }) : ""],
      [t("wk_ground"), s.ground_max != null ? `${fmt(s.ground_max, 0)} °C` : "–", s.seed_soil_mean != null ? t("wk_seed", { t: fmt(s.seed_soil_mean, 1) }) : ""],
    ].map(([k, v, d]) => `<div class="kpi"><span class="k">${esc(k)}</span><span class="v">${esc(v)}</span><span class="d">${esc(d)}</span></div>`).join("");
    const dates = (list) => list.slice(0, 3).map(dOf).join(", ") + (list.length > 3 ? "…" : "");
    const rows = w.crops.map((c) => {
      let main, sev = "info";
      if (c.status === "in_field") {
        const x = c.water, rng = x.m3_ha_low != null && x.m3_ha_low !== x.m3_ha_high ? ` (${fmt(x.m3_ha_low)}–${fmt(x.m3_ha_high)})` : "";
        main = t("wk_act_" + c.action, { m3: fmt(x.m3_ha), rng, use: fmt(x.use_mm, 0), net: fmt(x.net_mm, 0) });
        sev = c.action === "irrigate" ? "warning" : "tip";
      } else if (c.status === "sowing") {
        main = t("wk_sow_" + c.action, { n: c.days_to_sow, soil: c.seed_soil_c != null ? fmt(c.seed_soil_c, 1) : "–", thr: c.threshold_c,
          d: dOf(c.sow), f: dates(c.frost_dates || []), r: dates(c.downpour_dates || []) });
        sev = c.action === "sow" ? "tip" : "warning";
      } else {
        main = t("wk_off", { d: dOf(c.next_sow), n: c.days_to_sow });
      }
      const alerts = c.alerts.map((a) => `<li class="${a.level}"><span class="ico" aria-hidden="true">${ICON[a.level]}</span><span>${esc(t("wk_alert_" + a.code, { d: dates(a.dates), n: a.dates.length, t: a.t, mm: a.mm }))}</span></li>`).join("");
      const stage = c.status === "in_field" ? `<span class="badge">${esc(t("wk_stage_" + c.stage))} · ${esc(t("wk_day", { n: c.day }))}</span>` : "";
      const share = c.share >= 0.01 ? `<span class="muted small">${esc(t("wk_share", { p: Math.round(c.share * 100) }))}</span>` : "";
      return `<article class="wk-crop ${c.status}">
        <div class="wk-head"><b>${esc(name(c))}</b>${stage}${share}</div>
        <ul class="advice"><li class="${sev}"><span class="ico" aria-hidden="true">${ICON[sev]}</span><span>${esc(main)}</span></li>${alerts}</ul>
      </article>`;
    }).join("");
    card.innerHTML = `
      <div class="eyebrow">${esc(t("wk_eyebrow"))}</div>
      <h2 id="week-plan-title">${esc(t("wk_title", { a: dOf(s.from), b: dOf(s.to) }))}</h2>
      <div class="kpis">${kpis}</div>
      ${w.seen ? `<p class="seen">${esc(seenText(w.seen))}</p>` : ""}
      <div class="wk-list">${rows}</div>
      <p class="hint">${esc(t(w.method === "ensemble" ? "wk_method" : "wk_method_det", { n: s.members }))}</p>`;
    card.hidden = false;
  }

  function renderNoPoint() {
    const card = suitCard();
    if (card) {
      card.className = "card suit empty";
      card.innerHTML = `<h2>${esc(t("no_point_title"))}</h2><p class="lead">${esc(t($("map") ? "no_point_sub" : "no_point_sub_other"))}</p>` +
        ($("map") ? "" : `<a class="btn primary" href="/">${esc(t("no_point_link"))}</a>`);
      card.hidden = false;
    }
    if ($("verdict")) { $("verdict").textContent = t("no_point_title"); $("verdict").closest(".verdict").hidden = true; }
    if ($("region-card")) $("region-card").hidden = true;
    if ($("week-card")) $("week-card").hidden = true;
    if ($("verdict-sub")) $("verdict-sub").textContent = "";
    if ($("coords")) $("coords").textContent = "";
    if ($("analysis-status")) $("analysis-status").textContent = "";
  }

  function render() {
    if ($("coords")) $("coords").textContent = `${state.lat.toFixed(4)}, ${state.lon.toFixed(4)}`;
    renderSuitability();
    if ($("warnings")) $("warnings").innerHTML = data.warnings.map((w) => alertHtml(w.severity, w.text)).join("");
    renderChips();
    if ($("layer") && JSON.stringify(data.map_layers.map((l) => l.id)) !== JSON.stringify(layers.map((l) => l.id))) {
      layers = data.map_layers; renderLayerSelect();
    }
    renderSoilNote();
    renderRegion();
    renderWeekPlan();
    renderCurrentSelect();
    const ok = !!data.rotations;
    const unsuitable = data.suitability && data.suitability.status === "unsuitable";
    const verdictCard = $("verdict") && $("verdict").closest(".verdict");
    if (verdictCard) verdictCard.hidden = unsuitable;  // the suitability card already says why
    if (!ok) {
      const noCrops = !unsuitable && data.region;
      if ($("verdict")) $("verdict").textContent = t(unsuitable ? "verdict_unsuitable" : noCrops ? "no_crops_title" : "no_data_title");
      if ($("verdict-sub")) $("verdict-sub").textContent = unsuitable ? t("verdict_unsuitable_sub") : noCrops ? data.region.summary : t("no_data_sub");
      if ($("advice-top")) $("advice-top").innerHTML = "";
      if ($("rotations")) { $("rotations").innerHTML = ""; $("rotations-meta").textContent = ""; }
      if ($("crops")) $("crops").innerHTML = "";
      if ($("now-card")) $("now-card").hidden = true;
    } else if ($("verdict") || $("verdict-sub") || $("advice-top")) renderVerdict();
    if (data.climate && $("climate-card")) renderClimate();
    if ($("w-crop") && !$("w-crop").options.length) renderWaterForm();
    if ($("obs-card")) loadObservations();
    if (ok) {
      if ($("rotations")) renderRotations();
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
        it.origin && data.region && data.region.origin_text[it.origin] && it.origin !== "local"
          ? `<span class="badge origin ${esc(it.origin)}">${esc(data.region.origin_text[it.origin])}</span>` : "",
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

  // ---------- soil water forecast for one field ----------
  function renderWaterForm() {
    const sel = $("w-crop");
    if (!sel || !options) return;
    const local = (data && data.region && data.region.grown_here) || [];
    const first = local.concat(((data && data.region && data.region.suggested) || []).filter((c) => !local.includes(c)));
    const rest = options.crops.map((c) => c.id).filter((id) => !first.includes(id));
    const label = (id) => esc(name(options.crops.find((c) => c.id === id)));
    sel.innerHTML = (first.length ? `<optgroup label="${esc(t("water_local_crops"))}">${first.map((id) => `<option value="${id}">${label(id)}</option>`).join("")}</optgroup>` : "") +
      `<optgroup label="${esc(t("water_other_crops"))}">${rest.map((id) => `<option value="${id}">${label(id)}</option>`).join("")}</optgroup>`;
    const w = state.water || {};
    sel.value = w.crop && [...sel.options].some((o) => o.value === w.crop) ? w.crop : (first[0] || rest[0]);
    $("w-area").value = w.area || 1;
    $("w-sow").value = w.sow || "";
    $("w-last").value = w.last || "";
    const today = new Date().toISOString().slice(0, 10);
    $("w-last").max = today;
    $("w-last").min = new Date(Date.now() - 60 * 864e5).toISOString().slice(0, 10);
  }

  async function runWater() {
    if (!hasPoint()) { $("water-status").textContent = t("no_point_sub_other"); return; }
    state.water = { crop: $("w-crop").value, area: +$("w-area").value || 1, sow: $("w-sow").value, last: $("w-last").value };
    save();
    const q = new URLSearchParams({ lat: state.lat, lon: state.lon, crop: state.water.crop, area_ha: state.water.area,
      soil: state.soil, irrigation: state.irrigation });
    if (state.water.sow) q.set("sow", state.water.sow);
    if (state.water.last) q.set("last_irrigation", state.water.last);
    $("water-status").textContent = t("water_loading");
    $("w-go").disabled = true;
    try {
      renderWater(await api(`/api/water?${q}`));
      $("water-status").textContent = "";
    } catch (err) {
      $("water-status").textContent = t("error", { msg: err.message });
    } finally {
      $("w-go").disabled = false;
    }
  }

  function renderWater(w) {
    $("water-result").hidden = false;
    const crop = name(w.crop), dOf = (iso) => isoDay(iso);
    const inDays = (iso) => Math.round((new Date(iso) - new Date(w.today)) / 864e5);
    let head;
    if (!w.crop.in_field_today) head = t("water_not_in_field", { crop, sow: dOf(w.crop.sow), harvest: dOf(w.crop.harvest) });
    else if (w.already_dry) head = t("water_dry_now", { crop });
    else if (w.dry_on.expected) {
      const e = w.dry_on.expected, a = w.dry_on.earliest || e, b = w.dry_on.latest;
      head = t("water_dry_expected", { crop, d: dOf(e), n: inDays(e) }) + " " +
        (b ? t("water_dry_span", { a: dOf(a), b: dOf(b) }) : t("water_dry_span_open", { a: dOf(a) }));
    } else if (w.dry_on.earliest) {
      head = t("water_dry_unlikely", { crop, a: dOf(w.dry_on.earliest), pct: Math.round(w.dry_probability.d16 * 100) });
    } else if (w.dry_beyond_forecast) {
      const x = w.dry_beyond_forecast;
      head = x.after_harvest ? t("water_ok_season", { crop })
        : x.days > 30 ? t("water_dry_far", { crop, use: fmt(x.use_mm_day, 1) })
        : t("water_dry_beyond", { crop, d: dOf(x.date), n: x.days, use: fmt(x.use_mm_day, 1) });
    } else head = t("water_ok_16", { crop });
    $("water-head").textContent = head;

    const lines = [];
    if (w.irrigation && w.crop.in_field_today) {
      const i = w.irrigation;
      lines.push(["tip", t(w.irrigation_is_estimate ? "water_need_est" : "water_need", {
        mm: fmt(i.gross_mm, 0), l2: fmt(i.litres_m2, 0), m3ha: fmt(i.m3_ha), area: fmt(w.area_ha, 2),
        m3: fmt(i.m3_field, 0), litres: fmt(i.litres_field), eff: Math.round(w.efficiency * 100) })]);
    }
    if (w.forecast_irrigation && w.crop.in_field_today) {
      const f = w.forecast_irrigation;
      lines.push(["info", t("water_16d", { n: f.times, m3: fmt(f.m3_field, 0), litres: fmt(f.litres_field) })]);
    }
    if (w.dry_probability && w.crop.in_field_today && !w.already_dry) {
      lines.push(["info", t(w.method === "ensemble" ? "water_prob" : "water_prob_scen", {
        p7: Math.round(w.dry_probability.d7 * 100), p16: Math.round(w.dry_probability.d16 * 100), n: w.members })]);
    }
    const sd = w.surface_dry_on;
    lines.push(["info", sd.now ? t("water_surface_now")
      : sd.expected ? t("water_surface", { d: dOf(sd.expected), n: inDays(sd.expected) }) : t("water_surface_wet")]);
    const rr = w.forecast_rain_range_mm;
    lines.push(["info", t("water_balance", { evap: fmt(w.forecast_evap_mm, 0), transp: fmt(w.forecast_transp_mm, 0),
      rain: fmt(w.forecast_rain_mm, 0) }) + (rr ? " " + t("water_rain_range", { a: fmt(rr[0], 0), b: fmt(rr[1], 0) }) : "")]);
    lines.push(["info", t("water_soil_" + w.soil.source, { awc: w.soil.awc_mm_per_m, fc: Math.round(w.soil.fc * 100), wp: Math.round(w.soil.wp * 100) })]);
    lines.push([w.start_from === "last_irrigation" ? "tip" : "warning",
      t("water_start_" + w.start_from, { n: w.days_without_irrigation, d: dOf(w.start_date) })]);
    $("water-lines").innerHTML = lines.map(([sev, text]) => `<li class="${sev}"><span class="ico" aria-hidden="true">${ICON[sev]}</span><span>${esc(text)}</span></li>`).join("");

    const m = w.means;
    $("water-kpis").innerHTML = [
      [t("water_k_sun"), m.sun_mj != null ? `${fmt(m.sun_mj, 1)} MJ/m²` : "–", t("water_k_sun_d")],
      [t("water_k_tmax"), m.tmax != null ? `${fmt(m.tmax, 1)} °C` : "–", ""],
      [t("water_k_soil"), m.soil_t_max != null ? `${fmt(m.soil_t_max, 1)} °C` : "–", t("water_k_soil_d")],
      [t("water_k_et0"), m.et0_mm != null ? `${fmt(m.et0_mm, 1)} mm` : "–", t("water_k_et0_d")],
    ].map(([k, v, d]) => `<div class="kpi"><span class="k">${esc(k)}</span><span class="v">${esc(v)}</span><span class="d">${esc(d)}</span></div>`).join("");

    const rows = w.days;
    const opts = baseOptions();
    opts.plugins.legend.display = true;
    opts.scales.y = Object.assign(opts.scales.y, { min: 0, max: 100, title: { display: true, text: t("water_axis_pct"), color: css("--muted") } });
    opts.scales.y2 = { position: "right", min: 0, grid: { display: false }, ticks: { color: css("--muted") }, title: { display: true, text: "mm", color: css("--muted") } };
    const rawPct = rows.map((r) => r.taw_mm ? Math.round(100 * (1 - r.raw_mm / r.taw_mm)) : null);
    chart("water-chart", { type: "bar", data: { labels: rows.map((r) => isoDay(r.date)), datasets: [
      { type: "line", label: t("water_ds_soil"), data: rows.map((r) => r.water_pct), borderColor: css("--s1"), backgroundColor: css("--s1"), borderWidth: 2, pointRadius: 0, tension: 0.2, yAxisID: "y",
        segment: { borderDash: (ctx) => (rows[ctx.p1DataIndex] && !rows[ctx.p1DataIndex].past ? [5, 4] : undefined) } },
      { type: "line", label: t("water_ds_raw"), data: rawPct, borderColor: css("--critical"), borderWidth: 1.5, borderDash: [2, 3], pointRadius: 0, yAxisID: "y" },
      { type: "line", label: t("water_ds_surface"), data: rows.map((r) => r.surface_pct), borderColor: css("--muted"), borderWidth: 1.5, pointRadius: 0, tension: 0.2, yAxisID: "y" },
      { label: t("water_ds_rain"), data: rows.map((r) => r.rain_mm), backgroundColor: css("--info"), yAxisID: "y2", maxBarThickness: 14, stack: "rain" },
      { label: t("water_ds_evap"), data: rows.map((r) => r.evap_mm), backgroundColor: css("--critical"), yAxisID: "y2", maxBarThickness: 14, stack: "use" },
      { label: t("water_ds_use"), data: rows.map((r) => r.transp_mm), backgroundColor: css("--warning"), yAxisID: "y2", maxBarThickness: 14, stack: "use" },
    ] }, options: opts });

    const reliab = (r) => { const n = inDays(r.date); return r.past ? t("water_rel_past") : n <= 3 ? t("water_rel_good") : n <= 7 ? t("water_rel_mid") : t("water_rel_low"); };
    $("water-table").innerHTML = `<thead><tr>${["water_th_day", "water_th_rain", "water_th_sun", "water_th_temp", "water_th_soilt", "water_th_et0", "water_th_evap", "water_th_use", "water_th_surface", "water_th_left", "water_th_rel"].map((k) => `<th>${esc(t(k))}</th>`).join("")}</tr></thead><tbody>` +
      rows.filter((r) => !r.past || inDays(r.date) >= -14).map((r) => `<tr class="${r.dry ? "dry" : ""}${r.past ? " past" : ""}">
        <td>${esc(isoDay(r.date))}</td>
        <td class="num">${fmt(r.rain_mm, 1)}${!r.past && r.rain_high_mm != null ? `<span class="sub">${fmt(r.rain_low_mm, 0)}–${fmt(r.rain_high_mm, 0)} mm</span>` : r.rain_prob != null && !r.past ? `<span class="sub">${r.rain_prob}%</span>` : ""}</td>
        <td class="num">${r.sun_mj != null ? fmt(r.sun_mj, 1) : "–"}</td>
        <td class="num">${r.tmax != null ? `${fmt(r.tmax, 0)} / ${fmt(r.tmin, 0)}` : "–"}</td>
        <td class="num">${r.soil_t_max != null ? fmt(r.soil_t_max, 0) : "–"}</td>
        <td class="num">${fmt(r.et0_mm, 1)}</td>
        <td class="num">${fmt(r.evap_mm, 1)}</td>
        <td class="num">${fmt(r.transp_mm, 1)}</td>
        <td class="num">${r.surface_pct != null ? r.surface_pct + "%" : "–"}</td>
        <td class="num">${r.water_pct != null ? r.water_pct + "%" : "–"}${r.dry ? `<span class="sub">${esc(t("water_dry_tag"))}</span>` : ""}</td>
        <td>${esc(reliab(r))}</td></tr>`).join("") + "</tbody>";
  }

  // ---------- NASA observations at the field (loaded in the background on the server) ----------
  let obsTimer = null, obsFor = "";
  async function loadObservations(attempt = 0) {
    const key = `${state.lat},${state.lon}`;
    if (attempt === 0) { if (obsFor === key) return; obsFor = key; clearTimeout(obsTimer); }
    if (obsFor !== key) return;
    try {
      const o = await api(`/api/observations?lat=${state.lat}&lon=${state.lon}`);
      if (obsFor !== key) return;
      renderObservations(o);
      if (!o.complete && attempt < 40) obsTimer = setTimeout(() => loadObservations(attempt + 1), 4000);
    } catch (err) {
      $("obs-status").textContent = t("error", { msg: err.message });
    }
  }

  function renderObservations(o) {
    const card = $("obs-card"), p = o.products, dOf = (iso) => isoDay(iso);
    card.hidden = false;
    const names = { smap: "SMAP", imerg: "GPM IMERG", gldas: "GLDAS", modis: "MODIS", hls: "HLS", ecostress: "ECOSTRESS", openet: "OpenET",
      gaez: "FAO GAEZ", prism: "PRISM", nwis: "USGS NWIS", cocorahs: "CoCoRaHS" };
    $("obs-status").textContent = o.complete ? t("obs_done") : t("obs_loading", { list: o.pending.map((x) => names[x]).join(", ") });
    const tiles = [];
    if (p.hls && p.hls.status === "ok") tiles.push([t("obs_k_ndvi"), fmt(p.hls.latest.ndvi, 2), t("obs_ndvi_" + p.hls.state) + " · " + dOf(p.hls.latest.date) + " · HLS 30 m"]);
    else if (p.modis && p.modis.status === "ok") tiles.push([t("obs_k_ndvi"), fmt(p.modis.latest.ndvi, 2), dOf(p.modis.latest.date) + " · MODIS 250 m"]);
    else if (p.hls && p.hls.status === "cloudy") tiles.push([t("obs_k_ndvi"), "–", t("obs_cloudy")]);
    if (p.smap && p.smap.status === "ok") tiles.push([t("obs_k_smap"), `${fmt(p.smap.latest.rootzone * 100, 0)}%`, t("obs_smap_d", { s: fmt((p.smap.latest.surface || 0) * 100, 0), d: dOf(p.smap.latest.date) })]);
    if (p.imerg && p.imerg.status === "ok") tiles.push([t("obs_k_rain"), `${fmt(p.imerg.total_30d_mm, 0)} mm`, t("obs_rain_d", { n: p.imerg.days_since_rain, h: p.imerg.heavy_days })]);
    if (p.gldas && p.gldas.status === "ok") tiles.push([t("obs_k_gldas"), t("obs_gldas_" + p.gldas.class), t("obs_gldas_d", { m: p.gldas.latest.date, pct: p.gldas.percentile })]);
    if (p.ecostress && p.ecostress.status === "ok") {
      if (p.ecostress.hottest) tiles.push([t("obs_k_lst"), `${fmt(p.ecostress.hottest.lst_c, 1)} °C`, dOf(p.ecostress.hottest.date) + " · ECOSTRESS 70 m"]);
      if (p.ecostress.et_mean_mm != null) tiles.push([t("obs_k_et"), `${fmt(p.ecostress.et_mean_mm, 1)} mm/${t("obs_day")}`, t("obs_et_d", { n: p.ecostress.et.length })]);
    }
    if (p.openet && p.openet.status === "ok") tiles.push([t("obs_k_openet"), `${fmt(p.openet.total_mm)} mm`, t("obs_openet_d", { y: p.openet.year })]);
    if (p.prism && p.prism.status === "ok") tiles.push([t("obs_k_prism"), `${fmt(p.prism.rain_mm)} mm · ${fmt(p.prism.tmean_c, 1)} °C`, t("obs_prism_d", { a: p.prism.years[0], b: p.prism.years[1] })]);
    if (p.cocorahs && p.cocorahs.status === "ok") tiles.push([t("obs_k_cocorahs"), `${fmt(p.cocorahs.total_mm, 0)} mm`, t("obs_cocorahs_d", { n: p.cocorahs.stations.length })]);
    if (p.nwis && p.nwis.status === "ok" && p.nwis.stream) tiles.push([t("obs_k_stream"), `${fmt(p.nwis.stream.value, 1)} ft³/s`, `${p.nwis.stream.name} · ${p.nwis.stream.km} km`]);
    if (p.nwis && p.nwis.status === "ok" && p.nwis.groundwater) tiles.push([t("obs_k_well"), `${fmt(p.nwis.groundwater.value, 1)} ft`, `${p.nwis.groundwater.name} · ${p.nwis.groundwater.km} km`]);
    $("obs-kpis").innerHTML = tiles.map(([k, v, d]) => `<div class="kpi"><span class="k">${esc(k)}</span><span class="v">${esc(v)}</span><span class="d">${esc(d)}</span></div>`).join("");

    // vegetation: MODIS 3 years + HLS recent; soil water and rain: SMAP + IMERG
    if (window.Chart) {
      const opts = baseOptions();
      opts.plugins.legend.display = true;
      opts.scales.x = { type: "category", grid: { color: css("--line") }, ticks: { color: css("--muted"), maxTicksLimit: 8, maxRotation: 0 } };
      const mod = p.modis && p.modis.status === "ok" ? p.modis.series : [];
      const hl = p.hls && p.hls.status === "ok" ? p.hls.series : [];
      const labels = [...new Set([...mod.map((r) => r.date), ...hl.map((r) => r.date)])].sort();
      if (labels.length) {
        const at = (rows) => labels.map((d) => (rows.find((r) => r.date === d) || {}).ndvi ?? null);
        chart("obs-ndvi", { type: "line", data: { labels, datasets: [
          { label: "NDVI · MODIS 250 m", data: at(mod), borderColor: css("--s1"), backgroundColor: css("--s1"), borderWidth: 2, pointRadius: 0, spanGaps: true, tension: 0.2 },
          { label: "NDVI · HLS 30 m", data: at(hl), borderColor: css("--good"), backgroundColor: css("--good"), borderWidth: 0, pointRadius: 4, showLine: false },
        ] }, options: opts });
      }
      const sm = p.smap && p.smap.status === "ok" ? p.smap.series : [];
      const rn = p.imerg && p.imerg.status === "ok" ? p.imerg.series.slice(-31) : [];
      const l2 = [...new Set([...sm.map((r) => r.date), ...rn.map((r) => r.date)])].sort();
      if (l2.length) {
        const o2 = baseOptions();
        o2.plugins.legend.display = true;
        o2.scales.y = Object.assign(o2.scales.y, { min: 0, title: { display: true, text: "%", color: css("--muted") } });
        o2.scales.y2 = { position: "right", min: 0, grid: { display: false }, ticks: { color: css("--muted") }, title: { display: true, text: "mm", color: css("--muted") } };
        chart("obs-water", { type: "bar", data: { labels: l2.map((d) => isoDay(d)), datasets: [
          { type: "line", label: t("obs_ds_smap"), data: l2.map((d) => { const r = sm.find((x) => x.date === d); return r ? Math.round(r.rootzone * 1000) / 10 : null; }), borderColor: css("--s2"), backgroundColor: css("--s2"), borderWidth: 2, pointRadius: 0, spanGaps: true, yAxisID: "y" },
          { label: t("obs_ds_rain"), data: l2.map((d) => (rn.find((x) => x.date === d) || {}).rain_mm ?? null), backgroundColor: css("--info"), yAxisID: "y2", maxBarThickness: 10 },
        ] }, options: o2 });
      }
    }
    const notes = [];
    if (p.modis && p.modis.status === "ok" && p.modis.same_time_before != null) {
      const diff = p.modis.latest.ndvi - p.modis.same_time_before;
      notes.push([Math.abs(diff) < 0.05 ? "info" : diff > 0 ? "tip" : "warning", t("obs_modis_cmp", { now: fmt(p.modis.latest.ndvi, 2), before: fmt(p.modis.same_time_before, 2) })]);
    }
    if (p.smap && p.smap.status === "ok") notes.push(["info", t(p.smap.change_30d >= 0 ? "obs_smap_up" : "obs_smap_down", { d: fmt(Math.abs(p.smap.change_30d) * 100, 1) })]);
    if (p.gldas && p.gldas.status === "ok" && ["dry", "very_dry"].includes(p.gldas.class)) notes.push(["warning", t("obs_gldas_dry", { pct: p.gldas.percentile })]);
    if (p.gaez && p.gaez.status === "ok") {
      const local = (data && data.region && data.region.grown_here) || [];
      const ids = Object.keys(p.gaez.crops).filter((id) => !local.length || local.includes(id) || (data.region.suggested || []).includes(id));
      const label = (id) => name(options.crops.find((c) => c.id === id));
      const parts = ids.map((id) => { const g = p.gaez.crops[id]; return `${label(id)}: ${t("obs_gaez_" + g.class)} (${t("obs_gaez_irr")} ${g.irrigated != null ? fmt(g.irrigated / 100) : "–"}, ${t("obs_gaez_rain")} ${g.rainfed != null ? fmt(g.rainfed / 100) : "–"})`; });
      if (parts.length) notes.push(["info", t("obs_gaez") + " " + parts.join(" · ")]);
    }
    if (p.cocorahs && p.cocorahs.status === "ok" && p.imerg && p.imerg.status === "ok") {
      const from = p.cocorahs.daily.length ? p.cocorahs.daily[0].date : null;
      const sat = from ? p.imerg.series.filter((r) => r.date >= from).reduce((a, r) => a + r.rain_mm, 0) : null;
      if (sat != null) notes.push(["info", t("obs_validate", { ground: fmt(p.cocorahs.total_mm, 0), sat: fmt(sat, 0) })]);
    }
    const failed = Object.entries(p).filter(([, v]) => ["failed", "empty"].includes(v.status)).map(([k]) => names[k]);
    if (failed.length) notes.push(["info", t("obs_missing", { list: failed.join(", ") })]);
    $("obs-notes").innerHTML = notes.map(([sev, text]) => `<li class="${sev}"><span class="ico" aria-hidden="true">${ICON[sev]}</span><span>${esc(text)}</span></li>`).join("");
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
    on("place-form", "submit", (e) => {
      e.preventDefault();
      const query = $("place-search").value.trim();
      if (query.length < 2) { $("place-search-status").textContent = t("place_search_min"); return; }
      searchPlaces(query);
    });
    on("place-search", "keydown", (e) => {
      if (e.key === "ArrowDown" && placeResults.length) {
        e.preventDefault();
        updateActivePlace(activePlaceIndex + 1);
      } else if (e.key === "ArrowUp" && placeResults.length) {
        e.preventDefault();
        updateActivePlace(activePlaceIndex < 0 ? placeResults.length - 1 : activePlaceIndex - 1);
      } else if (e.key === "Enter" && activePlaceIndex >= 0 && !$("place-results").hidden) {
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
    on("water-form", "submit", (e) => { e.preventDefault(); runWater(); });
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
    if ($("map") && hasPoint()) setPoint(state.lat, state.lon, true, state.locationLabel, 10);
    else analyze();
    if ($("providers")) loadProviders().catch(showProviderError);
  }
  start();
})();
