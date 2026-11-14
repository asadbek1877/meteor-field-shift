/* Dalaviy directional page transitions, shared by every page. Loaded in <head>.
   Direction comes from the navigation order: going to a page further right, the current page leaves to the
   left and the new one enters from the right; going back, the reverse. It also works for browser back/forward.

   Browsers with cross-document View Transitions (Chrome/Edge 126+): the browser snapshots both pages and
   transitions.css animates them; the shared header and the active nav pill are captured separately, so the
   header stays put and the pill glides to its new place. Other browsers: the page slides out, the next page
   slides in (a shorter, same-direction fallback). Reduced motion: no movement. */
(() => {
  "use strict";
  const ORDER = ["home", "rotations", "climate", "crops", "sources", "current"];
  const FILES = { "": "home", "index.html": "home", "rotations.html": "rotations", "climate.html": "climate",
    "crops.html": "crops", "sources.html": "sources", "current.html": "current" };
  const pageOf = (href) => {
    try {
      const url = new URL(href, location.href);
      if (url.origin !== location.origin) return null;
      return FILES[url.pathname.split("/").pop()] ?? null;
    } catch { return null; }
  };
  const direction = (fromHref, toHref) => {
    const a = ORDER.indexOf(pageOf(fromHref)), b = ORDER.indexOf(pageOf(toHref));
    if (a < 0 || b < 0 || a === b) return null;
    return b > a ? "forward" : "back";
  };
  const root = document.documentElement;
  const reduce = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const native = "onpagereveal" in window && window.CSS && CSS.supports("view-transition-name: x");
  if (native) root.classList.add("vt-native");
  // A skipped or interrupted transition rejects its promises; that is expected, not an error.
  const quiet = (vt) => ["ready", "finished", "updateCallbackDone"].forEach((k) => { if (vt[k] && vt[k].catch) vt[k].catch(() => {}); });

  const slideIn = (dir, how) => {
    root.classList.add("vt-enter", "vt-" + dir);
    root.dataset.vtLast = dir + (how ? "-" + how : "");
    const done = () => root.classList.remove("vt-enter", "vt-forward", "vt-back");
    window.addEventListener("animationend", (ev) => { if (ev.target === document.body) done(); }, { once: true });
    setTimeout(done, 1200);
  };

  if (native) {
    // Old page: tag the transition, or skip it for links that are not page-to-page moves.
    window.addEventListener("pageswap", (e) => {
      if (!e.viewTransition) return;
      quiet(e.viewTransition);
      const to = e.activation && e.activation.entry && e.activation.entry.url;
      const dir = to && direction(location.href, to);
      if (dir && !reduce()) e.viewTransition.types.add(dir);
      else e.viewTransition.skipTransition();
    });
    // New page: same tag, worked out from where we came from (also on back/forward).
    window.addEventListener("pagereveal", (e) => {
      const act = window.navigation && navigation.activation;
      const from = act && act.from && act.from.url;
      const dir = from && act.navigationType !== "reload" && direction(from, location.href);
      if (!e.viewTransition) {
        // The browser can drop a cross-document transition (render timeout, a snapshot it cannot take, some
        // embedded views). The page must still arrive from the right side, so it slides in on its own.
        if (dir && !reduce()) slideIn(dir, "fallback");
        return;
      }
      quiet(e.viewTransition);
      root.dataset.vtLast = dir || "none";                 /* lets a test see which way the last move went */
      if (dir && !reduce()) e.viewTransition.types.add(dir);
      else e.viewTransition.skipTransition();
    });
    // Chrome sometimes reveals the page before the listener above sees it ("Page already revealed"). If nothing
    // handled the arrival by the first frame and no transition is running, slide in here instead.
    requestAnimationFrame(() => {
      if (root.dataset.vtLast) return;
      const act = window.navigation && navigation.activation;
      const from = act && act.from && act.from.url;
      const dir = from && act.navigationType !== "reload" && direction(from, location.href);
      const vt = document.activeViewTransition;
      if (vt) {                                   /* the transition runs, but untagged: give it its direction */
        quiet(vt);
        root.dataset.vtLast = (dir || "none") + "-late";
        if (dir && !reduce()) vt.types.add(dir); else vt.skipTransition();
        return;
      }
      root.dataset.vtLast = (dir || "none") + "-checked";
      if (dir && !reduce()) slideIn(dir, "late");
    });
    return;
  }

  // ---------- fallback: slide out, navigate, slide in ----------
  const KEY = "dalaviy:nav";
  try {
    const saved = JSON.parse(sessionStorage.getItem(KEY) || "null");
    sessionStorage.removeItem(KEY);
    if (saved && Date.now() - saved.at < 5000 && saved.to === location.pathname && !reduce()) {
      slideIn(saved.dir);
    }
  } catch { /* storage blocked: no animation */ }

  document.addEventListener("click", (e) => {
    const a = e.target.closest && e.target.closest("a[href]");
    if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    if (a.target && a.target !== "_self") return;
    if (a.hasAttribute("download")) return;
    const url = new URL(a.href, location.href);
    if (url.pathname === location.pathname) return;          /* same page, e.g. /#app */
    const dir = direction(location.href, url.href);
    if (!dir) return;
    if (reduce()) return;
    e.preventDefault();
    try { sessionStorage.setItem(KEY, JSON.stringify({ dir, to: url.pathname, at: Date.now() })); } catch { /* fine */ }
    root.classList.add("vt-leave", "vt-" + dir);
    setTimeout(() => { location.href = url.href; }, 170);
  });
  // coming back from the bfcache must not leave the page half-faded
  window.addEventListener("pageshow", (e) => { if (e.persisted) root.classList.remove("vt-leave", "vt-forward", "vt-back"); });
})();
