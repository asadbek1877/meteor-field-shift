/* Dalaviy field section: UI behaviour only (data rendering lives in app.js).
   Entrance after the landing journey, background video, tabs, menus, dropdowns, the priorities dialog and row details. */
(() => {
  "use strict";
  const dash = document.querySelector(".dash");
  if (!dash) return;
  const $ = (id) => document.getElementById(id);
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const saveData = Boolean(navigator.connection && navigator.connection.saveData);
  const later = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  /* ---------- entrance: right away with /#app, otherwise when the journey hands over ---------- */
  const journey = document.getElementById("journey");
  const journeyOpen = () => journey && !journey.hidden && !journey.classList.contains("is-done");
  let entered = false;
  function enter() {
    if (entered) return;
    entered = true;
    dash.classList.add("is-in");
    loadVideo();
  }
  if (journeyOpen()) {
    document.addEventListener("journey:exit", enter, { once: true });
    document.addEventListener("journey:surface", () => loadVideo(), { once: true });   /* warm up during the last scene */
  } else {
    setTimeout(enter, 0);
  }

  /* ---------- crops page on phones: the plant video starts where the heading text ends ---------- */
  const cropLead = document.querySelector(".crop-lead");
  if (cropLead && "ResizeObserver" in window) {
    const placeVideo = () => dash.style.setProperty("--lead-bottom", `${Math.round(cropLead.getBoundingClientRect().bottom - dash.getBoundingClientRect().top)}px`);
    new ResizeObserver(placeVideo).observe(cropLead);
    placeVideo();
  }

  /* ---------- background video: loads once, loops natively, pauses when unseen ---------- */
  const video = $("dash-video");
  let videoVisible = true;
  function loadVideo() {
    if (!video || video.getAttribute("src") || reduceMotion.matches || saveData) return;
    video.preload = "auto";
    video.src = video.dataset.src;
    video.load();
    syncVideo();
  }
  function syncVideo() {
    if (!video || !video.getAttribute("src")) return;
    const run = entered && videoVisible && !document.hidden && !reduceMotion.matches;
    if (run && video.paused) video.play().catch(() => { /* autoplay blocked: the poster stays */ });
    else if (!run && !video.paused) video.pause();
  }
  if (video) {
    new IntersectionObserver(([entry]) => { videoVisible = entry.isIntersecting; syncVideo(); }).observe(video);
    document.addEventListener("visibilitychange", syncVideo);
    reduceMotion.addEventListener("change", () => (reduceMotion.matches ? video.pause() : (loadVideo(), syncVideo())));
  }

  /* ---------- tabs: the old view fades out, then the new one fades in ---------- */
  const tabs = [...document.querySelectorAll('.dash-tabs [role="tab"]')];
  let tabRun = 0;
  async function selectTab(tab, focus) {
    const run = ++tabRun;
    const next = $(tab.getAttribute("aria-controls"));
    const prev = tabs.map((t) => $(t.getAttribute("aria-controls"))).find((p) => p && !p.hidden && p !== next);
    tabs.forEach((t) => {
      const on = t === tab;
      t.setAttribute("aria-selected", String(on));
      t.tabIndex = on ? 0 : -1;
    });
    if (focus) tab.focus();
    if (prev && !reduceMotion.matches) {
      prev.classList.add("is-leaving");
      await later(140);
      if (run !== tabRun) return;
    }
    tabs.forEach((t) => {
      const panel = $(t.getAttribute("aria-controls"));
      if (!panel) return;
      panel.classList.remove("is-leaving");
      panel.hidden = panel !== next;
    });
    if (next && window.Chart) next.querySelectorAll("canvas").forEach((c) => { const ch = window.Chart.getChart(c); if (ch) ch.resize(); });
  }
  tabs.forEach((tab, i) => {
    tab.addEventListener("click", () => { if (tab.getAttribute("aria-selected") !== "true") selectTab(tab); });
    tab.addEventListener("keydown", (e) => {
      const step = { ArrowRight: 1, ArrowLeft: -1 }[e.key];
      if (step) { e.preventDefault(); selectTab(tabs[(i + step + tabs.length) % tabs.length], true); }
      if (e.key === "Home") { e.preventDefault(); selectTab(tabs[0], true); }
      if (e.key === "End") { e.preventDefault(); selectTab(tabs[tabs.length - 1], true); }
    });
  });

  /* ---------- header menus (language, profile, warnings) ---------- */
  const menus = [...dash.querySelectorAll("[data-menu]")];
  function closeMenus(except) {
    menus.forEach((m) => {
      if (m === except) return;
      m.querySelector("[aria-expanded]").setAttribute("aria-expanded", "false");
      m.querySelector(".dash-pop").hidden = true;
    });
  }
  menus.forEach((m) => {
    const button = m.querySelector("[aria-expanded]");
    const pop = m.querySelector(".dash-pop");
    button.addEventListener("click", () => {
      const open = button.getAttribute("aria-expanded") !== "true";
      closeMenus(m);
      closeCombos();
      button.setAttribute("aria-expanded", String(open));
      pop.hidden = !open;
      if (open) { const first = pop.querySelector("button, a"); if (first) first.focus(); }
    });
    pop.addEventListener("click", (e) => { if (e.target.closest("button, a")) { closeMenus(); button.focus(); } });
    m.addEventListener("keydown", (e) => { if (e.key === "Escape" && !pop.hidden) { e.stopPropagation(); closeMenus(); button.focus(); } });
  });
  const langLabel = dash.querySelector(".dash-lang-current");
  const showLang = () => { if (langLabel) langLabel.textContent = (document.documentElement.lang || "uz").toUpperCase(); };
  dash.querySelectorAll("[data-lang]").forEach((b) => b.addEventListener("click", () => requestAnimationFrame(() => { showLang(); syncCombos(); })));
  showLang();

  /* ---------- data source warnings: a badge in the header instead of text over the layout ---------- */
  const warnings = $("warnings");
  const alertMenu = dash.querySelector(".dash-alerts");
  if (warnings && alertMenu) {
    const count = alertMenu.querySelector(".dash-alert-count");
    const update = () => {
      const n = warnings.querySelectorAll(".alert").length;
      count.textContent = String(n);
      alertMenu.hidden = n === 0;
      if (!n) closeMenus();
    };
    new MutationObserver(update).observe(warnings, { childList: true });
    update();
  }

  /* ---------- dropdowns: a dark listbox in front of each native select ----------
     The native <select> stays in the page (hidden) and keeps its id, value and change event,
     so app.js reads and writes it exactly as before. */
  const combos = [];
  let comboId = 0;
  const escHtml = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  function enhance(select) {
    const wrap = select.parentElement;
    const id = ++comboId;
    const label = document.querySelector(`label[for="${select.id}"]`) || wrap.closest("label");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "dash-combo";
    button.setAttribute("aria-haspopup", "listbox");
    button.setAttribute("aria-expanded", "false");
    const value = document.createElement("span");
    value.className = "dash-combo-value";
    value.id = `combo-value-${id}`;
    button.append(value);
    const list = document.createElement("ul");
    list.className = "dash-listbox";
    list.id = `combo-list-${id}`;
    list.setAttribute("role", "listbox");
    list.hidden = true;
    button.setAttribute("aria-controls", list.id);
    if (label) {
      if (!label.id) label.id = `combo-label-${id}`;
      list.setAttribute("aria-labelledby", label.id);
      button.setAttribute("aria-labelledby", `${label.id} ${value.id}`);
    }
    select.tabIndex = -1;
    select.setAttribute("aria-hidden", "true");
    wrap.classList.add("is-enhanced");
    wrap.insertBefore(button, select);
    wrap.append(list);
    if (label && label.tagName === "LABEL") label.addEventListener("click", (e) => { if (!list.contains(e.target)) { e.preventDefault(); button.focus(); } });

    const combo = { select, wrap, button, value, list, active: -1 };
    const items = () => [...list.children];
    combo.sync = () => {
      const opt = select.selectedOptions[0];
      value.textContent = opt ? opt.textContent : "–";
      button.title = opt ? (opt.title || opt.textContent) : "";
      button.disabled = select.disabled || !select.options.length;
    };
    combo.build = () => {
      list.innerHTML = [...select.options].map((o, i) =>
        `<li role="option" id="combo-${id}-${i}" data-index="${i}" aria-selected="${o.selected}" style="--li: ${i}">${escHtml(o.textContent)}</li>`).join("");
    };
    combo.highlight = (i) => {
      const all = items();
      if (!all.length) return;
      combo.active = (i + all.length) % all.length;
      all.forEach((li, k) => li.classList.toggle("is-active", k === combo.active));
      button.setAttribute("aria-activedescendant", all[combo.active].id);
      all[combo.active].scrollIntoView({ block: "nearest" });
    };
    combo.open = () => {
      if (button.disabled) return;
      closeCombos(combo);
      closeMenus();
      combo.build();
      const box = button.getBoundingClientRect();
      const room = window.innerHeight - box.bottom;
      wrap.classList.toggle("opens-up", room < 260 && box.top > room);
      list.hidden = false;
      wrap.classList.add("is-open");
      button.setAttribute("aria-expanded", "true");
      combo.highlight(Math.max(0, select.selectedIndex));
    };
    combo.close = (focus) => {
      if (list.hidden) return;
      list.hidden = true;
      wrap.classList.remove("is-open");
      button.setAttribute("aria-expanded", "false");
      button.removeAttribute("aria-activedescendant");
      if (focus) button.focus();
    };
    combo.choose = (i) => {
      const opt = select.options[i];
      if (opt && select.selectedIndex !== i) {
        select.selectedIndex = i;
        select.dispatchEvent(new Event("change", { bubbles: true }));
      }
      combo.sync();
      combo.close(true);
    };
    button.addEventListener("click", () => (list.hidden ? combo.open() : combo.close()));
    button.addEventListener("keydown", (e) => {
      const isOpen = !list.hidden;
      if (["ArrowDown", "ArrowUp", "Enter", " "].includes(e.key) && !isOpen) { e.preventDefault(); combo.open(); return; }
      if (!isOpen) return;
      if (e.key === "ArrowDown") { e.preventDefault(); combo.highlight(combo.active + 1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); combo.highlight(combo.active - 1); }
      else if (e.key === "Home") { e.preventDefault(); combo.highlight(0); }
      else if (e.key === "End") { e.preventDefault(); combo.highlight(items().length - 1); }
      else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); combo.choose(combo.active); }
      else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); combo.close(true); }
      else if (e.key === "Tab") combo.close();
    });
    list.addEventListener("mousedown", (e) => e.preventDefault());       /* keep focus on the button */
    list.addEventListener("mousemove", (e) => { const li = e.target.closest("li"); if (li && +li.dataset.index !== combo.active) combo.highlight(+li.dataset.index); });
    list.addEventListener("click", (e) => { const li = e.target.closest("li"); if (li) combo.choose(+li.dataset.index); });
    select.addEventListener("change", combo.sync);
    new MutationObserver(() => { combo.sync(); if (!list.hidden) combo.build(); }).observe(select, { childList: true, subtree: true, attributes: true });
    combo.sync();
    combos.push(combo);
  }
  function closeCombos(except) { combos.forEach((c) => { if (c !== except) c.close(); }); }
  function syncCombos() { combos.forEach((c) => c.sync()); }
  dash.querySelectorAll(".dash-select select, .field-current select").forEach(enhance);
  document.addEventListener("click", (e) => {
    if (!e.target.closest("[data-menu]")) closeMenus();
    if (!e.target.closest(".is-enhanced")) closeCombos();
  });
  window.addEventListener("resize", () => closeCombos());

  /* ---------- scrolling: sections reveal once, the header sticks with a glass background ---------- */
  const reveal = [...dash.querySelectorAll("[data-reveal]")];
  if (reduceMotion.matches || !("IntersectionObserver" in window)) reveal.forEach((el) => el.classList.add("is-visible"));
  else {
    const io = new IntersectionObserver((entries) => entries.forEach((e) => {
      if (e.isIntersecting) { e.target.classList.add("is-visible"); io.unobserve(e.target); }
    }), { rootMargin: "0px 0px -10% 0px", threshold: 0.05 });
    reveal.forEach((el) => io.observe(el));
  }
  const top = $("app-top");
  let stuck = false;
  const onScroll = () => {
    const next = window.scrollY > 8;
    if (next !== stuck) { stuck = next; top.classList.toggle("is-stuck", next); }
  };
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  /* ---------- updates feed: a counter that bumps when new items arrive, cleared once they were seen ---------- */
  const newsBadge = $("news-new");
  const newsSection = $("news-section");
  let newsSeenTimer = 0;
  document.addEventListener("news:update", (e) => {
    const fresh = e.detail.fresh;
    if (!newsBadge || !fresh) return;
    $("news-count").textContent = String(fresh);
    newsBadge.hidden = false;
    newsBadge.classList.remove("is-bump");
    void newsBadge.offsetWidth;
    newsBadge.classList.add("is-bump");
    clearTimeout(newsSeenTimer);
  });
  if (newsSection && "IntersectionObserver" in window) {
    new IntersectionObserver(([e]) => {
      if (!e.isIntersecting || !newsBadge || newsBadge.hidden) return;
      clearTimeout(newsSeenTimer);
      newsSeenTimer = setTimeout(() => {
        newsBadge.hidden = true;
        dash.querySelectorAll(".news-card.is-new").forEach((c) => c.classList.add("is-seen"));
      }, 5000);
    }, { threshold: 0.3 }).observe(newsSection);
  }

  /* ---------- a newly applied field boundary is briefly highlighted on the dashboard ---------- */
  document.addEventListener("field:applied", () => {
    const row = dash.querySelector(".field-area-row");
    if (!row) return;
    row.classList.remove("is-changed");
    void row.offsetWidth;
    row.classList.add("is-changed");
    row.scrollIntoView({ block: "nearest", behavior: reduceMotion.matches ? "auto" : "smooth" });
  });

  /* ---------- navigation capsule: the indicator rests on the current page and follows the hovered item ---------- */
  const nav = dash.querySelector(".dash-nav");
  const glow = nav && nav.querySelector(".nav-glow");
  if (nav && glow) {
    const place = (link) => {
      if (!link) { glow.style.opacity = "0"; return; }
      const a = link.getBoundingClientRect(), n = nav.getBoundingClientRect();
      glow.style.setProperty("--nx", `${(a.left - n.left).toFixed(1)}px`);
      glow.style.setProperty("--nw", `${a.width.toFixed(1)}px`);
      glow.style.opacity = "";
    };
    const current = () => nav.querySelector('a[aria-current="page"]');
    const rest = () => { nav.classList.remove("is-hovering"); place(current()); };
    nav.addEventListener("pointerover", (e) => { const a = e.target.closest("a"); if (a) { nav.classList.add("is-hovering"); place(a); } });
    nav.addEventListener("pointerleave", rest);
    nav.addEventListener("focusin", (e) => { const a = e.target.closest("a"); if (a) place(a); });
    nav.addEventListener("focusout", rest);
    // aria-current and the translated labels arrive from app.js; place without animation first, then animate
    const init = () => { rest(); requestAnimationFrame(() => glow.classList.add("is-ready")); };
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(init); else setTimeout(init, 0);
    new MutationObserver(rest).observe(nav, { subtree: true, attributes: true, attributeFilter: ["aria-current"], characterData: true, childList: true });
    window.addEventListener("resize", rest);
  }

  /* ---------- glass specular: a soft light under the pointer on interactive glass (one listener, one frame) ---------- */
  const GLASS = ".glass-interactive, .dash-pill, .dash-lang-btn, .dash-avatar, .dash-alert-btn, .dash-combo, .field-link, .dash-btn, .dash-panel-action, .rot-go, .clim-advice-go, .field-expand, .field-hint, .dash-tabs [role='tab']";
  let glassTarget = null, glassEvent = null, glassFrame = 0;
  if (window.matchMedia("(hover: hover) and (pointer: fine)").matches) {
    document.addEventListener("pointermove", (e) => {
      glassEvent = e;
      if (glassFrame) return;
      glassFrame = requestAnimationFrame(() => {
        glassFrame = 0;
        const el = glassEvent.target.closest && glassEvent.target.closest(GLASS);
        if (el !== glassTarget) glassTarget = el;
        if (!el) return;
        const r = el.getBoundingClientRect();
        el.style.setProperty("--gx", `${(glassEvent.clientX - r.left).toFixed(0)}px`);
        el.style.setProperty("--gy", `${(glassEvent.clientY - r.top).toFixed(0)}px`);
      });
    }, { passive: true });
  }

  /* ---------- page lifecycle: release work when leaving, restore cleanly from the back/forward cache ---------- */
  window.addEventListener("pagehide", () => {
    if (video && !video.paused) video.pause();
    if (glassFrame) { cancelAnimationFrame(glassFrame); glassFrame = 0; }
    closeMenus();
    closeCombos();
  });
  window.addEventListener("pageshow", (e) => {
    if (!e.persisted) return;
    syncVideo();
    if (nav && glow) { glow.classList.remove("is-ready"); requestAnimationFrame(() => { const a = nav.querySelector('a[aria-current="page"]'); if (a) { const r = a.getBoundingClientRect(), n = nav.getBoundingClientRect(); glow.style.setProperty("--nx", `${(r.left - n.left).toFixed(1)}px`); glow.style.setProperty("--nw", `${r.width.toFixed(1)}px`); } requestAnimationFrame(() => glow.classList.add("is-ready")); }); }
  });

  /* ---------- priorities dialog (sliders, own rotation, soil note) ---------- */
  const prefs = $("prefs-dialog");
  const openPrefs = () => { if (prefs && !prefs.open) prefs.showModal(); };
  dash.querySelectorAll("[data-open-prefs]").forEach((b) => b.addEventListener("click", openPrefs));
  if (prefs) {
    prefs.querySelectorAll("[data-close-dialog]").forEach((b) => b.addEventListener("click", () => prefs.close()));
    prefs.addEventListener("click", (e) => { if (e.target === prefs) prefs.close(); });       /* backdrop */
  }
  const current = $("current");
  if (current) current.addEventListener("change", () => { if (current.value === "custom") openPrefs(); });

  /* ---------- rotation rows: details open in place; state survives re-renders ---------- */
  const list = $("rot-list");
  const open = new Set();
  let firstRender = true;
  function setRow(row, expand, animate) {
    const button = row.querySelector(".rot-go");
    const detail = row.querySelector(".rot-detail");
    if (!button || !detail) return;
    button.setAttribute("aria-expanded", String(expand));
    row.classList.toggle("is-open", expand);
    if (expand) {
      detail.hidden = false;
      open.add(row.dataset.rot);
      if (animate && !reduceMotion.matches) {
        requestAnimationFrame(() => requestAnimationFrame(() => detail.classList.add("is-open")));
        detail.addEventListener("transitionend", () => row.scrollIntoView({ block: "nearest", behavior: "smooth" }), { once: true });
      } else detail.classList.add("is-open");
    } else {
      detail.classList.remove("is-open");
      open.delete(row.dataset.rot);
      const hide = () => { if (!detail.classList.contains("is-open")) detail.hidden = true; };
      if (animate && !reduceMotion.matches) detail.addEventListener("transitionend", hide, { once: true });
      else hide();
    }
  }
  if (list) {
    list.addEventListener("click", (e) => {
      const main = e.target.closest(".rot-main");
      if (!main || (window.getSelection && String(window.getSelection()).length)) return;
      const row = main.closest(".rot-row");
      setRow(row, row.querySelector(".rot-go").getAttribute("aria-expanded") !== "true", true);
    });
  }
  document.addEventListener("dash:render", () => {
    if (!list) return;
    list.querySelectorAll(".rot-row[data-rot]").forEach((row) => { if (open.has(row.dataset.rot)) setRow(row, true, false); });
    /* only the first set of rows rises in; later results update in place (app.js updateRows) */
    if (firstRender && list.querySelector(".rot-row[data-rot]")) {
      list.classList.add("is-fresh");
      firstRender = false;
      setTimeout(() => list.classList.remove("is-fresh"), 1200);
    }
    showLang();
    syncCombos();
  });
})();
