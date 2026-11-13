/* TerraShift landing journey: scene controller.
   Scene 1  space.mp4     loops behind the hero copy.
   Scene 2  approach.mp4  plays once after "Boshlash"; its first frame is the loop's seam frame.
   Scene 3  surface.mp4   plays once and holds its last frame; its first frame is approach.mp4's last frame.
   Videos are stacked; a video only becomes visible after it has presented a frame, so a seam can never show black.
   No dependencies. Playback and the animation loop stop whenever the tab is hidden. */
(() => {
  "use strict";
  const journey = document.getElementById("journey");
  if (!journey || journey.hidden) return;              /* /#app opens the field app directly */

  const root = document.documentElement;
  const app = document.getElementById("app");
  const [space, approach, surface] = ["space", "approach", "surface"].map((name) => journey.querySelector(`[data-video="${name}"]`));
  const ui1 = journey.querySelector(".ui-1");
  const ui3 = journey.querySelector(".ui-3");
  const startButton = document.getElementById("journey-start");
  const restartButton = document.getElementById("journey-restart");
  const sceneTitle = document.getElementById("feature-title");
  const canvas = journey.querySelector(".hero-stars");
  const ctx = canvas.getContext("2d");
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const finePointer = window.matchMedia("(hover: hover) and (pointer: fine)");
  const saveData = Boolean(navigator.connection && navigator.connection.saveData);
  const motion = () => !reduceMotion.matches && !saveData;

  const FPS = 24;
  const DISSOLVE = 1.1;        /* s, space > approach when the loop is mid-way */
  const SEAM_WINDOW = 1.4;     /* s, closer than this to the loop seam: wait for it and cut almost hard */
  const SEAM_FADE = 0.3;       /* s */
  const HANDOFF = 0.4;         /* s, approach > surface overlap; the two frames are near identical */
  const DATA_AT = 1.2;         /* s into surface.mp4, when its own data panels start to draw */

  let scene = 1;
  let run = 0;                 /* bumps on every navigation, so stale async steps stop */
  let busy = false;
  let current = space;
  let alive = true;

  if (app) app.inert = true;

  /* ---------- helpers ---------- */
  const later = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const setScene = (n) => {
    scene = n;
    journey.dataset.scene = String(n);
    ui1.inert = n !== 1;
    ui3.inert = n !== 3;
    journey.classList.toggle("is-data", n === 3 && surface.currentTime > DATA_AT);
    if (n === 3) document.dispatchEvent(new CustomEvent("journey:surface"));
  };
  const load = (video) => {
    if (video.getAttribute("src") || !video.dataset.src) return;
    video.preload = "auto";
    video.src = video.dataset.src;
    video.load();
  };
  const ready = (video, state, ms) => new Promise((resolve) => {
    if (video.readyState >= state) return resolve(true);
    const events = ["loadeddata", "canplay", "canplaythrough"];
    const finish = (ok) => { clearTimeout(timer); events.forEach((e) => video.removeEventListener(e, check)); resolve(ok); };
    const check = () => { if (video.readyState >= state) finish(true); };
    const timer = setTimeout(() => finish(video.readyState >= state), ms);
    events.forEach((e) => video.addEventListener(e, check));
  });
  /* resolves once the video has put a new frame on screen */
  const presented = (video) => new Promise((resolve) => {
    if ("requestVideoFrameCallback" in video) video.requestVideoFrameCallback(() => resolve());
    else requestAnimationFrame(() => requestAnimationFrame(resolve));
    setTimeout(resolve, 700);
  });
  const start = async (video) => {
    const shown = presented(video);
    const playing = video.play();
    playing.catch(() => {});
    const ok = await Promise.race([playing.then(() => true, () => false), later(2500).then(() => false)]);
    if (ok) await shown;
    return ok;
  };
  const crossfade = (video, seconds) => {
    journey.style.setProperty("--xf", `${seconds}s`);
    video.classList.add("is-on");
    return later(seconds * 1000);
  };
  const untilTime = (video, t) => new Promise((resolve) => {
    const step = () => (video.ended || video.currentTime >= t ? resolve() : requestAnimationFrame(step));
    step();
  });
  /* the loop's last frames dissolve into frame 0, which is approach.mp4's first frame */
  const untilLoopSeam = (video) => new Promise((resolve) => {
    let previous = video.currentTime;
    const step = () => {
      const t = video.currentTime;
      if (t < previous || t >= video.duration - 1.5 / FPS) return resolve();
      previous = t;
      requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
    setTimeout(resolve, (SEAM_WINDOW + 0.5) * 1000);
  });
  const flare = () => {
    journey.classList.remove("is-flaring");
    void journey.offsetWidth;                          /* restart the animation */
    journey.classList.add("is-flaring");
  };

  /* ---------- scene 1 > 2 > 3 ---------- */
  async function begin() {
    if (scene !== 1 || busy) return;
    busy = true;
    const id = ++run;
    startButton.classList.add("is-pressed");

    if (!motion()) {                                   /* still frames, short fade */
      setScene(3);
      await crossfade(surface, 0.3);
      if (id === run) { sceneTitle.focus({ preventScroll: true }); busy = false; }
      return;
    }

    load(approach);
    load(surface);
    const waiting = setTimeout(() => startButton.classList.add("is-waiting"), 250);
    const approachReady = await ready(approach, 3, 6000);
    clearTimeout(waiting);
    startButton.classList.remove("is-waiting");
    if (id !== run) return;

    setScene(2);                                       /* the scene 1 copy lifts away */
    if (approachReady) {
      const atSeam = !space.paused && space.duration - space.currentTime < SEAM_WINDOW;
      approach.currentTime = 0;
      if (atSeam) await untilLoopSeam(space);
      if (id !== run) return;
      if (await start(approach)) {
        current = approach;
        if (atSeam) await crossfade(approach, SEAM_FADE);
        else { flare(); await crossfade(approach, DISSOLVE); }
        if (id !== run) return;
        space.pause();
        await ready(surface, 3, Math.max(0, approach.duration - approach.currentTime) * 1000 + 6000);
        await untilTime(approach, approach.duration - HANDOFF);
      }
    }
    if (id !== run) return;

    /* if surface is still loading, its poster (= its first frame) shows until playback starts */
    surface.currentTime = 0;
    const handoff = start(surface);
    await Promise.race([handoff, later(600)]);
    if (id !== run) return;
    current = surface;
    setScene(3);
    await crossfade(surface, approachReady ? HANDOFF + 0.05 : 1.2);
    if (id !== run) return;
    approach.pause();
    space.pause();
    sceneTitle.focus({ preventScroll: true });
    busy = false;
  }

  async function restart() {
    if (scene !== 3) return;
    const id = ++run;
    busy = true;
    journey.classList.add("is-replay");
    if (motion()) { space.currentTime = 0; await start(space); }
    if (id !== run) return;
    current = space;
    setScene(1);
    journey.style.setProperty("--xf", "1.2s");
    surface.classList.remove("is-on");
    approach.classList.remove("is-on");
    await later(1250);
    if (id !== run) return;
    [approach, surface].forEach((video) => { video.pause(); video.currentTime = 0; });
    startButton.classList.remove("is-pressed");
    startButton.focus({ preventScroll: true });
    busy = false;
  }

  /* "Yer holati": hand over to the field app below and free the videos */
  function exitToApp(event) {
    event.preventDefault();
    run++;
    alive = false;
    journey.classList.add("is-done");
    root.classList.remove("journey-on");
    document.dispatchEvent(new CustomEvent("journey:exit"));
    if (app) app.inert = false;
    const target = (event.currentTarget && event.currentTarget.hash) || "#app";
    history.replaceState(null, "", target);
    window.scrollTo(0, 0);
    const section = target !== "#app" && document.querySelector(target);
    if (section) setTimeout(() => section.scrollIntoView({ behavior: "smooth" }), 400);
    window.dispatchEvent(new Event("terrashift:app-visible"));
    const main = document.getElementById("main-content");
    if (main) { main.setAttribute("tabindex", "-1"); main.focus({ preventScroll: true }); }
    setTimeout(() => {
      journey.hidden = true;
      [space, approach, surface].forEach((video) => { video.pause(); video.removeAttribute("src"); video.load(); });
    }, 850);
  }

  startButton.addEventListener("click", begin);
  restartButton.addEventListener("click", restart);
  journey.querySelectorAll("[data-journey-exit]").forEach((link) => link.addEventListener("click", exitToApp));
  surface.addEventListener("timeupdate", () => journey.classList.toggle("is-data", scene === 3 && surface.currentTime > DATA_AT));

  /* ---------- stars ---------- */
  let stars = [];
  let width = 0, height = 0;
  function drawStars(time) {
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = "#dbe6ff";
    for (const s of stars) {
      const twinkle = reduceMotion.matches ? 1 : 0.6 + 0.4 * Math.sin(time * 0.001 * s.speed + s.phase);
      ctx.globalAlpha = s.a * twinkle;
      ctx.beginPath(); ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2); ctx.fill();
    }
    ctx.globalAlpha = 1;
  }
  function resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    width = journey.clientWidth; height = journey.clientHeight;
    canvas.width = Math.round(width * dpr); canvas.height = Math.round(height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const count = Math.min(170, Math.round((width * height) / 9000));
    stars = Array.from({ length: count }, () => ({
      x: Math.random() * width, y: Math.random() * height,
      r: 0.35 + Math.random() ** 3 * 1.1, a: 0.25 + Math.random() * 0.6,
      speed: 0.4 + Math.random() * 1.4, phase: Math.random() * Math.PI * 2,
    }));
    drawStars(0);
  }

  /* ---------- one loop: eased pointer parallax and star twinkle ---------- */
  const target = { x: 0, y: 0 };
  const eased = { x: 0, y: 0 };
  let looping = false, frame = 0;
  function tick(time) {
    if (!looping) return;
    eased.x += (target.x - eased.x) * 0.06;
    eased.y += (target.y - eased.y) * 0.06;
    journey.style.setProperty("--px", eased.x.toFixed(4));
    journey.style.setProperty("--py", eased.y.toFixed(4));
    if (scene === 1 && frame++ % 2 === 0) drawStars(time);   /* ~30 fps is plenty for a slow twinkle */
    requestAnimationFrame(tick);
  }
  function sync() {
    const active = alive && !document.hidden && !reduceMotion.matches;
    if (active && !looping) { looping = true; requestAnimationFrame(tick); }
    if (!active) looping = false;
    if (!alive) return;
    if (document.hidden || !motion()) current.pause();
    else if (!current.ended && current.getAttribute("src")) current.play().catch(() => { /* autoplay blocked: the poster stays */ });
  }

  window.addEventListener("pointermove", (e) => {
    if (!finePointer.matches || e.pointerType === "touch") return;
    target.x = (e.clientX / window.innerWidth) * 2 - 1;
    target.y = (e.clientY / window.innerHeight) * 2 - 1;
  }, { passive: true });
  root.addEventListener("pointerleave", () => { target.x = 0; target.y = 0; });
  document.addEventListener("visibilitychange", sync);
  reduceMotion.addEventListener("change", () => {
    if (reduceMotion.matches) ["--px", "--py"].forEach((p) => journey.style.removeProperty(p));
    drawStars(0);
    sync();
  });
  let resizeTimer;
  window.addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(resize, 150); });

  /* ---------- arrival ---------- */
  let arrived = false;
  const arrive = () => {
    if (arrived) return;
    arrived = true;
    journey.classList.add("is-ready");
    if (!motion()) return;
    load(space);
    start(space);
    /* warm only the next clip; the last one (16 MB) loads once the visitor shows intent to start,
       so people who skip the journey never download it. It still has the whole approach clip to arrive,
       and its poster (= its first frame) covers a slow network. */
    ready(space, 4, 6000).then(() => load(approach));
  };
  const intent = () => { load(approach); load(surface); };
  ["pointerenter", "focus", "touchstart"].forEach((e) => startButton.addEventListener(e, intent, { once: true, passive: true }));
  const poster = new Image();
  poster.onload = poster.onerror = arrive;
  poster.src = space.poster;
  setTimeout(arrive, 1500);

  setScene(1);
  resize();
  sync();
})();
