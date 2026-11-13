/* Dalaviy shell: the one icon sprite and the one header shared by every dashboard page (Dala, Iqlim, ...).
   Each page puts <div data-shell-sprite></div> and <header data-shell-header></header> in its .dash root and loads
   this script right after them; the markup is filled in synchronously, before app.js and field.js run.
   The page decides which data providers its status pills show: <body data-providers="nasa_power,open_meteo">. */
(() => {
  "use strict";
  const providers = document.body.dataset.providers || "nasa";
  const SPRITE = `<svg class="dash-sprite" aria-hidden="true" focusable="false">
      <symbol id="i-drop" viewBox="0 0 24 24"><path d="M12 2.8c3.4 4.1 6.2 7.6 6.2 11.2a6.2 6.2 0 0 1-12.4 0c0-3.6 2.8-7.1 6.2-11.2Z"/></symbol>
      <symbol id="i-layers" viewBox="0 0 24 24"><path d="m12 3 9 4.8-9 4.8-9-4.8Z"/><path d="m3 12.2 9 4.8 9-4.8"/><path d="m3 16.4 9 4.8 9-4.8"/></symbol>
      <symbol id="i-growth" viewBox="0 0 24 24"><path d="M5 20v-5M10 20v-8M15 20v-6M20 20V8"/><path d="m4 11 5-4 4 3 7-6"/><path d="M16 4h4v4"/></symbol>
      <symbol id="i-soil" viewBox="0 0 24 24"><path d="M12 15V8"/><path d="M12 10c0-3.3-2.3-5.2-6-5.2 0 3.3 2.3 5.2 6 5.2Zm0-1.6c0-3 2.2-4.8 5.6-4.8 0 3-2.2 4.8-5.6 4.8Z"/><path d="M3 15h18M5 18.5h14M8 22h8"/></symbol>
      <symbol id="i-leaf" viewBox="0 0 24 24"><path d="M5 20c0-9.4 6.2-15.6 15-15.6 0 9.8-6.5 15.6-15 15.6Z"/><path d="M5 20 14 11"/></symbol>
      <symbol id="i-shield" viewBox="0 0 24 24"><path d="M12 3 4.8 5.8v5.6c0 4.6 3 8 7.2 9.6 4.2-1.6 7.2-5 7.2-9.6V5.8Z"/><path d="m8.8 12 2.2 2.2 4.2-4.4"/></symbol>
      <symbol id="i-risk" viewBox="0 0 24 24"><path d="M4 20v-3M9 20v-6M14 20v-9M19 20V6"/></symbol>
      <symbol id="i-pin" viewBox="0 0 24 24"><path d="M12 21.2s-6.8-6-6.8-11.4a6.8 6.8 0 0 1 13.6 0c0 5.4-6.8 11.4-6.8 11.4Z"/><circle cx="12" cy="9.8" r="2.5"/></symbol>
      <symbol id="i-target" viewBox="0 0 24 24"><circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="2.2"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/></symbol>
      <symbol id="i-wheat" viewBox="0 0 24 24"><path d="M12 22V8"/><path d="M12 8.5c-2-.8-3.2-2.6-3.2-4.8 2 .4 3.2 1.9 3.2 3.6 0-1.7 1.2-3.2 3.2-3.6 0 2.2-1.2 4-3.2 4.8Z"/><path d="M12 13.6c-2.2-.6-3.8-2.2-4-4.4 2.2.2 3.8 1.6 4 3.4.2-1.8 1.8-3.2 4-3.4-.2 2.2-1.8 3.8-4 4.4Z"/><path d="M12 18.4c-2.2-.6-3.8-2.2-4-4.4 2.2.2 3.8 1.6 4 3.4.2-1.8 1.8-3.2 4-3.4-.2 2.2-1.8 3.8-4 4.4Z"/></symbol>
      <symbol id="i-cotton" viewBox="0 0 24 24"><path d="M12 13.5V22"/><path d="M8.6 13.4a3.2 3.2 0 0 1-1.2-6 3.4 3.4 0 0 1 4.6-3.6 3.4 3.4 0 0 1 4.6 3.6 3.2 3.2 0 0 1-1.2 6Z"/><path d="M8.5 16.5c1.5 0 2.8.6 3.5 1.6.7-1 2-1.6 3.5-1.6"/></symbol>
      <symbol id="i-sprout" viewBox="0 0 24 24"><path d="M12 21v-8"/><path d="M12 14c0-4-2.8-6.4-7.4-6.4 0 4 2.8 6.4 7.4 6.4Zm0-2.4c0-3.6 2.6-5.8 6.8-5.8 0 3.6-2.6 5.8-6.8 5.8Z"/></symbol>
      <symbol id="i-chart" viewBox="0 0 24 24"><path d="M5 20v-7M10 20V6M15 20v-9M20 20V9"/></symbol>
      <symbol id="i-trend" viewBox="0 0 24 24"><path d="M3 20h18"/><path d="m4 15 5-5 4 3 7-7"/><path d="M15 6h5v5"/></symbol>
      <symbol id="i-arrow" viewBox="0 0 24 24"><path d="M5 12h14M13 6l6 6-6 6"/></symbol>
      <symbol id="i-expand" viewBox="0 0 24 24"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/></symbol>
      <symbol id="i-chevron" viewBox="0 0 24 24"><path d="m6 9 6 6 6-6"/></symbol>
      <symbol id="i-user" viewBox="0 0 24 24"><circle cx="12" cy="8.2" r="3.8"/><path d="M4.5 20.5c.6-3.7 3.8-5.8 7.5-5.8s6.9 2.1 7.5 5.8"/></symbol>
      <symbol id="i-gear" viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M12 2.5v2.6M12 18.9v2.6M4.6 4.6l1.9 1.9M17.5 17.5l1.9 1.9M2.5 12h2.6M18.9 12h2.6M4.6 19.4l1.9-1.9M17.5 6.5l1.9-1.9"/></symbol>
      <symbol id="i-scan" viewBox="0 0 24 24"><path d="M12 3 20 7.6v8.8L12 21l-8-4.6V7.6Z"/><circle cx="12" cy="12" r="2.6"/></symbol>
      <symbol id="i-calendar" viewBox="0 0 24 24"><rect x="3.5" y="5" width="17" height="15.5" rx="2.5"/><path d="M3.5 10h17M8 3v4M16 3v4M8 14h2M14 14h2M8 17h2"/></symbol>
      <symbol id="i-sliders" viewBox="0 0 24 24"><path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/></symbol>
      <symbol id="i-globe" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.6 3.8 5.6 3.8 9s-1.3 6.4-3.8 9c-2.5-2.6-3.8-5.6-3.8-9S9.5 5.6 12 3Z"/></symbol>
      <symbol id="i-polygon" viewBox="0 0 24 24"><path d="M5 7 12 3.5 20 8l-2 10-11 2.5Z"/><circle cx="5" cy="7" r="1.6"/><circle cx="12" cy="3.5" r="1.6"/><circle cx="20" cy="8" r="1.6"/><circle cx="18" cy="18" r="1.6"/><circle cx="7" cy="20.5" r="1.6"/></symbol>
      <symbol id="i-area" viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M4 9h16M9 4v16" opacity=".5"/></symbol>
      <symbol id="i-news" viewBox="0 0 24 24"><rect x="3.5" y="4.5" width="17" height="15" rx="2.5"/><path d="M7.5 9h9M7.5 12.5h9M7.5 16h5"/></symbol>
      <symbol id="i-bell" viewBox="0 0 24 24"><path d="M6 16.5V11a6 6 0 0 1 12 0v5.5l1.5 2h-15Z"/><path d="M10 20.5a2 2 0 0 0 4 0"/></symbol>
      <symbol id="i-cloud" viewBox="0 0 24 24"><path d="M7 18a4 4 0 0 1-.5-8A5.5 5.5 0 0 1 17 9.2 3.5 3.5 0 0 1 17 18Z"/></symbol>
      <symbol id="i-check" viewBox="0 0 24 24"><path d="m5 12.5 4.5 4.5L19 7.5"/></symbol>
      <symbol id="i-undo" viewBox="0 0 24 24"><path d="M9 7 4.5 11.5 9 16"/><path d="M5 11.5h9.5a5 5 0 0 1 0 10H12"/></symbol>
      <symbol id="i-trash" viewBox="0 0 24 24"><path d="M4.5 7h15M10 7V4.5h4V7M6.5 7l1 13h9l1-13"/></symbol>
      <symbol id="i-flask" viewBox="0 0 24 24"><path d="M9.5 3.5h5M10.5 3.5v6L5 19a1.5 1.5 0 0 0 1.3 2.2h11.4A1.5 1.5 0 0 0 19 19l-5.5-9.5v-6"/><path d="M7.5 15h9"/></symbol>
      <symbol id="i-thermo" viewBox="0 0 24 24"><path d="M14 14.8V5a2 2 0 0 0-4 0v9.8a4 4 0 1 0 4 0Z"/><path d="M12 9v7.5"/><circle cx="12" cy="17.6" r="1.4"/></symbol>
      <symbol id="i-sun" viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M5.3 18.7l1.6-1.6M17.1 6.9l1.6-1.6"/></symbol>
      <symbol id="i-wind" viewBox="0 0 24 24"><path d="M3 8.5h10.5a2.5 2.5 0 1 0-2.5-2.5M3 12.5h15a2.5 2.5 0 1 1-2.5 2.5M3 16.5h8"/></symbol>
      <symbol id="i-gauge" viewBox="0 0 24 24"><path d="M4.5 17a8 8 0 1 1 15 0"/><path d="m12 13 3.5-4"/><circle cx="12" cy="13.5" r="1.2"/></symbol>
      <symbol id="i-grid" viewBox="0 0 24 24"><rect x="4" y="4" width="6.5" height="6.5" rx="1.5"/><rect x="13.5" y="4" width="6.5" height="6.5" rx="1.5"/><rect x="4" y="13.5" width="6.5" height="6.5" rx="1.5"/><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.5"/></symbol>
      <symbol id="i-coins" viewBox="0 0 24 24"><ellipse cx="9" cy="7" rx="5" ry="2.2"/><path d="M4 7v3.4c0 1.2 2.2 2.2 5 2.2s5-1 5-2.2V7"/><path d="M10 15.4v2.4c0 1.2 2.2 2.2 5 2.2s5-1 5-2.2v-5.6c0-1.2-2.2-2.2-5-2.2"/><path d="M10 15.4c0 1.2 2.2 2.2 5 2.2s5-1 5-2.2"/></symbol>
      <symbol id="i-chev-r" viewBox="0 0 24 24"><path d="m9 6 6 6-6 6"/></symbol>
      <symbol id="i-info" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 11v5.5M12 7.6v.4"/></symbol>
    </svg>`;
  const HEADER = `<header class="dash-top" id="app-top" data-in style="--i: 0">
      <a class="dash-brand" href="/" data-t-aria="brand_home">
        <svg class="dash-logo" viewBox="0 0 48 48" aria-hidden="true">
          <defs><linearGradient id="logo-g" x1="0" y1="1" x2="1" y2="0"><stop offset="0" stop-color="#2f7dff"/><stop offset="1" stop-color="#53d6ff"/></linearGradient></defs>
          <ellipse cx="24" cy="24" rx="20" ry="9.5" transform="rotate(-38 24 24)" fill="none" stroke="url(#logo-g)" stroke-width="3.2"/>
          <path d="M14 33c1.5-10.5 8.4-17.2 20-19-1.2 11.6-8 18.6-20 19Z" fill="url(#logo-g)" opacity=".92"/>
          <path d="M16.5 31 27 20.5" stroke="#07101f" stroke-width="2" stroke-linecap="round"/>
        </svg>
        <span class="dash-brand-text"><strong data-t="brand_name"></strong><small data-t="brand_sub"></small></span>
      </a>
      <span class="dash-demo-badge" id="dash-demo" data-t-title="demo_note" hidden><b data-t="demo_badge"></b><span data-t="demo_short"></span></span>
      <nav class="dash-nav glass-navigation" data-t-aria="main_nav_label">
        <span class="nav-glow" aria-hidden="true"></span>
        <a href="/#app" data-page-link="home" data-t="nav_home"></a>
        <a href="/rotations.html" data-page-link="rotations" data-t="nav_rotations"></a>
        <a href="/climate.html" data-page-link="climate" data-t="nav_climate"></a>
        <a href="/crops.html" data-page-link="crops" data-t="nav_crops"></a>
        <a href="/sources.html" data-page-link="sources" data-t="nav_reports"></a>
      </nav>
      <div class="dash-actions">
        <div id="chips" class="dash-status" data-filter="${providers}" aria-live="polite"></div>
        <div class="dash-menu dash-alerts" data-menu hidden>
          <button type="button" class="dash-alert-btn" aria-haspopup="true" aria-expanded="false" data-t-aria="warnings_label">
            <svg><use href="#i-info"/></svg><span class="dash-alert-count">0</span>
          </button>
          <div class="dash-pop dash-pop-wide" hidden>
            <div id="warnings" class="dash-warnings" aria-live="polite"></div>
          </div>
        </div>
        <div class="dash-menu" data-menu>
          <button type="button" class="dash-lang-btn" aria-haspopup="true" aria-expanded="false" data-t-aria="language_group">
            <span class="dash-lang-current">UZ</span><svg class="ico-sm"><use href="#i-chevron"/></svg>
          </button>
          <div class="dash-pop" role="group" data-t-aria="language_group" hidden>
            <button type="button" data-lang="uz">O'zbekcha <span>UZ</span></button>
            <button type="button" data-lang="en">English <span>EN</span></button>
          </div>
        </div>
        <div class="dash-menu" data-menu>
          <button type="button" class="dash-avatar" aria-haspopup="true" aria-expanded="false" data-t-aria="profile_menu">
            <svg><use href="#i-user"/></svg>
          </button>
          <div class="dash-pop dash-pop-right" hidden>
            <button type="button" data-open-prefs><svg><use href="#i-sliders"/></svg><span data-t="prefs_title"></span></button>
            <a href="/current.html"><svg><use href="#i-drop"/></svg><span data-t="nav_now_long"></span></a>
            <a href="/sources.html"><svg><use href="#i-info"/></svg><span data-t="sources_btn"></span></a>
          </div>
        </div>
      </div>
    </header>`;
  const spriteSlot = document.querySelector("[data-shell-sprite]");
  if (spriteSlot) spriteSlot.outerHTML = SPRITE;
  const headerSlot = document.querySelector("[data-shell-header]");
  if (headerSlot) headerSlot.outerHTML = HEADER;
})();
