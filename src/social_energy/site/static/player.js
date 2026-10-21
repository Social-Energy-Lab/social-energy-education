// The hero: the camp as a living network on a canvas, with play/pause, a scrubber over the
// shown (daytime) bins, speeds of 1, 3 and 6 hours per second and a day picker. The settings
// are camp_breathes.py's: a sliding two-hour window, a tie when two people were close in at
// least three of its 5-minute bins, a glow that fades over 40 minutes after a press.
import * as model from "./model.js";
import { DEFAULT_SPAN, easeView, fitView, homes, pairKey, Sim } from "./layout.js";

export const WINDOW_BINS = 24;
export const MIN_BINS = 3;
export const GLOW_BINS = 8;
export const SPEEDS = [1, 3, 6]; // hours of camp per second
const NIGHT_MS = 1000;
const START_INDEX = 30; // a full window into the first day

// ----------------------------------------------------------------- pure helpers (tested)

/** Indices of the bins that are shown (night removed). */
export function shownBins(bins) {
  const out = [];
  for (let k = 0; k < bins.shown.length; k++) if (bins.shown[k] === 1) out.push(k);
  return Uint32Array.from(out);
}

/** True under prefers-reduced-motion; takes a MediaQueryList-like object or matchMedia itself. */
export function startPaused(matchMedia) {
  if (typeof matchMedia === "function") {
    try {
      return Boolean(matchMedia("(prefers-reduced-motion: reduce)")?.matches);
    } catch {
      return false;
    }
  }
  return Boolean(matchMedia?.matches);
}

/** The decoded bundle's pairs with an RSSI column at 0: every public pair is already close. */
export function closeView(b) {
  return { pairs: { ...b.pairs, rssi: new Int8Array(b.pairs.bin.length) } };
}

/** Ties in the window ending before `endBin`, from a closeView. */
export function windowEdges(view, endBin, windowBins = WINDOW_BINS, minBins = MIN_BINS) {
  return model.edges(view, { endBin, windowBins, closeRssi: 0, minBins });
}

/** Glow per node at (fractional) bin `now`: 1 at a press, fading to 0 over GLOW_BINS. */
export function glowAt(presses, now, nNodes) {
  const out = new Float32Array(nNodes);
  const lo = model.lowerBound(presses.bin, Math.ceil(now - GLOW_BINS));
  for (let i = lo; i < presses.bin.length && presses.bin[i] <= now; i++) {
    const g = 1 - (now - presses.bin[i]) / GLOW_BINS;
    if (g > out[presses.node[i]]) out[presses.node[i]] = g;
  }
  return out;
}

/** Whether a night lies between shown index i and the next one. */
export function isGap(shown, i) {
  return i + 1 < shown.length && shown[i + 1] - shown[i] > 1;
}

/** The first shown index of every camp day. */
export function dayStarts(bins, shown) {
  const out = [];
  for (let i = 0; i < shown.length; i++) {
    const day = bins.day[shown[i]];
    if (!out.length || out[out.length - 1].day !== day) out.push({ day, index: i, bin: shown[i] });
  }
  return out;
}

// ----------------------------------------------------------------- the player (DOM)

const ICON = {
  play: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.5v13l11-6.5z"/></svg>',
  pause:
    '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 5h3.5v14H7zM13.5 5H17v14h-3.5z"/></svg>',
  full: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" fill="none" stroke="currentColor" stroke-width="2"/></svg>',
};

const slug = (s) => String(s).toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");

function token(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function glowSprite(color) {
  const size = 128;
  const c = document.createElement("canvas");
  c.width = c.height = size;
  const g = c.getContext("2d");
  const grad = g.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  grad.addColorStop(0, color);
  grad.addColorStop(0.25, color);
  grad.addColorStop(1, "transparent");
  g.globalAlpha = 1;
  g.fillStyle = grad;
  g.fillRect(0, 0, size, size);
  // A soft second falloff so the halo reads as light, not as a disc.
  const c2 = document.createElement("canvas");
  c2.width = c2.height = size;
  const g2 = c2.getContext("2d");
  const grad2 = g2.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  grad2.addColorStop(0, "rgba(255,255,255,1)");
  grad2.addColorStop(0.35, "rgba(255,255,255,0.35)");
  grad2.addColorStop(1, "rgba(255,255,255,0)");
  g2.fillStyle = grad2;
  g2.fillRect(0, 0, size, size);
  g2.globalCompositeOperation = "source-in";
  g2.drawImage(c, 0, 0);
  return c2;
}

function el(tag, attrs = {}, html = "") {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (html) node.innerHTML = html;
  return node;
}

/**
 * Mount the hero into `root`. `site` is loadSite()'s {meta, b}; `t` the copy lookup.
 * opts: {lang: () => "de"|"en", paused: boolean, reduced: boolean}.
 * Returns {seekTo(bin), pause(), play(), relabel()}.
 */
export function mountPlayer(root, site, t, opts = {}) {
  const { meta, b } = site;
  const lang = opts.lang ?? (() => "de");
  const reduced = Boolean(opts.reduced);
  const n = meta.nodes.length;
  const nodeCourse = Int16Array.from(meta.nodes, (d) => d.course);
  const shown = shownBins(b.bins);
  const days = dayStarts(b.bins, shown);
  const view = closeView(b);
  const sim = new Sim(homes(nodeCourse, meta.n_courses, 1), 0);
  const t0 = Date.parse(meta.t0);
  const binMs = meta.bin_seconds * 1000;

  // --- DOM
  root.classList.add("player");
  root.innerHTML = "";
  const stage = el("div", { class: "stage", tabindex: "0", role: "group" });
  const canvas = el("canvas", { role: "img" });
  const when = el("div", { class: "when", "aria-live": "off" });
  const whenDay = el("div", { class: "when-day" });
  const whenClock = el("div", { class: "when-clock" });
  const whenNote = el("div", { class: "when-note" });
  when.append(whenDay, whenClock, whenNote);
  const night = el("div", { class: "night", "aria-hidden": "true" });
  const nightTitle = el("strong");
  const nightSub = el("span");
  night.append(nightTitle, nightSub);
  const fsButton = el("button", { class: "icon fs", type: "button" }, ICON.full);
  stage.append(canvas, when, night);
  const canFullscreen = Boolean(root.requestFullscreen) && document.fullscreenEnabled !== false;
  if (canFullscreen) stage.append(fsButton);

  const controls = el("div", { class: "controls" });
  const playButton = el("button", { class: "icon play", type: "button" });
  const scrub = el("input", {
    class: "scrub",
    type: "range",
    min: "0",
    max: String(Math.max(0, shown.length - 1)),
    step: "1",
  });
  const speedGroup = el("div", { class: "speeds", role: "group" });
  const speedButtons = SPEEDS.map((h) => {
    const btn = el("button", { type: "button", "data-speed": String(h) });
    speedGroup.append(btn);
    return btn;
  });
  controls.append(playButton, scrub, speedGroup);
  const dayGroup = el("div", { class: "days", role: "group" });
  const dayButtons = days.map((d) => {
    const btn = el("button", { type: "button", "data-index": String(d.index) });
    dayGroup.append(btn);
    return btn;
  });
  root.append(stage, controls, dayGroup);

  // --- state
  let head = Math.min(START_INDEX, Math.max(0, shown.length - 1));
  let index = -1; // shown index whose window is loaded
  let playing = false;
  let speed = 3;
  let nightUntil = 0;
  let weights = new Map();
  let vis = new Uint8Array(n);
  let edges = { a: [], b: [], bins: [] };
  let raf = 0;
  let last = 0;
  let onscreen = true;
  let colors = {};
  let sprite = null;
  let size = { w: 0, h: 0, dpr: 1 };
  // The camera: eased toward a view that fits every dot below the date block.
  let cam = null;
  let camMoving = false;
  let topBand = 0;

  function readColors() {
    // The stage is a night sky in both themes, so the canvas uses the hero's own tokens.
    colors = {
      courses: [1, 2, 3, 4, 5, 6].map((i) => token(`--hero-course-${i}`) || "#3987e5"),
      unknown: token("--hero-course-unknown") || "#8a8984",
      ink: token("--hero-ink") || "#fff",
      ring: token("--hero-ring") || "#333",
      glow: token("--hero-glow") || "#fff3b0",
    };
    sprite = glowSprite(colors.glow);
  }
  const courseColor = (c) => (c < 0 ? colors.unknown : colors.courses[c % colors.courses.length]);

  function load(i) {
    if (i === index || !shown.length) return;
    index = i;
    const endBin = shown[i] + 1;
    edges = windowEdges(view, endBin);
    weights = new Map();
    for (let k = 0; k < edges.a.length; k++) {
      weights.set(pairKey(edges.a[k], edges.b[k]), edges.bins[k] / WINDOW_BINS);
    }
    vis = model.visible(b, endBin, WINDOW_BINS, n);
    labelTime();
  }

  // --- labels
  function labelTime() {
    if (!shown.length) return;
    const bin = shown[Math.max(0, index)];
    const at = new Date(t0 + bin * binMs);
    const tz = meta.timezone;
    whenDay.textContent = new Intl.DateTimeFormat(lang(), {
      weekday: "long",
      day: "numeric",
      month: "long",
      timeZone: tz,
    }).format(at);
    const clock = new Intl.DateTimeFormat(lang(), {
      hour: "2-digit",
      minute: "2-digit",
      timeZone: tz,
    }).format(at);
    const phaseName = meta.phases?.[b.bins.phase[bin]];
    const phaseKey = `phase_${slug(phaseName ?? "")}`;
    const phase = phaseName ? (t(phaseKey) === phaseKey ? phaseName : t(phaseKey)) : "";
    whenClock.textContent = phase ? `${clock} · ${phase}` : clock;
    const notes = [...(meta.special_days ?? []), ...(meta.shade ?? [])]
      .filter((d) => d.start_bin <= bin && bin < d.end_bin)
      .map((d) => {
        const key = `label_${slug(d.label)}`;
        return t(key) === key ? d.label : t(key);
      });
    whenNote.textContent = notes.join(" · ");
    measureTop();
    scrub.value = String(index);
    scrub.setAttribute("aria-valuetext", `${whenDay.textContent}, ${whenClock.textContent}`);
    const day = b.bins.day[bin];
    days.forEach((d, k) => dayButtons[k].setAttribute("aria-pressed", String(d.day === day)));
  }

  function relabel() {
    stage.setAttribute("aria-label", t("player_label"));
    canvas.setAttribute("aria-label", t("player_summary"));
    stage.title = t("player_keys");
    playButton.innerHTML = playing ? ICON.pause : ICON.play;
    playButton.setAttribute("aria-label", playing ? t("player_pause") : t("player_play"));
    playButton.title = playButton.getAttribute("aria-label");
    scrub.setAttribute("aria-label", t("player_time"));
    speedGroup.setAttribute("aria-label", t("player_speed"));
    speedButtons.forEach((btn, k) => {
      btn.textContent = t("player_speed_value", { h: SPEEDS[k] });
      btn.title = `${SPEEDS[k]} ${t("player_speed_hint")}`;
      btn.setAttribute("aria-pressed", String(SPEEDS[k] === speed));
    });
    dayGroup.setAttribute("aria-label", t("player_day"));
    const dayFmt = new Intl.DateTimeFormat(lang(), {
      weekday: "short",
      day: "numeric",
      timeZone: meta.timezone,
    });
    days.forEach((d, k) => {
      dayButtons[k].textContent = dayFmt.format(new Date(t0 + d.bin * binMs));
    });
    nightTitle.textContent = t("player_night");
    nightSub.textContent = t("player_night_sub");
    const full = document.fullscreenElement === root;
    fsButton.setAttribute("aria-label", full ? t("player_exit_fullscreen") : t("player_fullscreen"));
    fsButton.title = fsButton.getAttribute("aria-label");
    labelTime();
  }

  // --- drawing
  /** The band the date block covers, so the drawing stays clear of it. */
  function measureTop() {
    topBand = when.offsetHeight ? when.offsetTop + when.offsetHeight + 6 : 0;
  }

  function resize() {
    const rect = canvas.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    size = { w: rect.width, h: rect.height, dpr };
    canvas.width = Math.max(1, Math.round(rect.width * dpr));
    canvas.height = Math.max(1, Math.round(rect.height * dpr));
    measureTop();
    cam = null;
    draw();
  }

  /** Draw the frame; `ease` moves the camera a step toward the fit, else it jumps there. */
  function draw(ease = false) {
    const ctx = canvas.getContext("2d");
    const { w, h, dpr } = size;
    if (!w || !h) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const base = Math.min(w, h) / DEFAULT_SPAN; // dot and line sizes do not follow the zoom
    const r = Math.max(2.6, Math.min(6, base * 0.028));
    const target = fitView(sim.pos, w, h, { top: topBand, pad: 2 * r + 4 });
    if (!cam || !ease) {
      cam = target;
      camMoving = false;
    } else {
      cam = easeView(cam, target, 0.08);
      camMoving = cam.moving;
    }
    const { cx, cy, s } = cam;
    const pos = sim.pos;
    const X = (i) => cx + pos[2 * i] * s;
    const Y = (i) => cy - pos[2 * i + 1] * s;

    // The ring the courses live on: a hint, not a label.
    ctx.globalAlpha = 0.5;
    ctx.strokeStyle = colors.ring;
    ctx.lineWidth = 1;
    ctx.setLineDash([2, 6]);
    ctx.beginPath();
    ctx.arc(cx, cy, 0.85 * s, 0, 2 * Math.PI);
    ctx.stroke();
    ctx.setLineDash([]);

    // Ties, batched by colour and four alpha levels.
    const batches = new Map();
    for (let k = 0; k < edges.a.length; k++) {
      const i = edges.a[k];
      const j = edges.b[k];
      const ci = nodeCourse[i];
      const same = ci >= 0 && ci === nodeCourse[j];
      const alpha = Math.min(0.85, Math.max(0.15, (edges.bins[k] / WINDOW_BINS) * 2.2));
      const level = Math.min(3, Math.floor(alpha * 4));
      const key = `${same ? ci : "x"}|${level}`;
      let list = batches.get(key);
      if (!list) batches.set(key, (list = []));
      list.push(i, j);
    }
    ctx.lineWidth = Math.max(0.8, base * 0.004);
    for (const [key, list] of batches) {
      const [c, level] = key.split("|");
      ctx.strokeStyle = c === "x" ? colors.ink : courseColor(+c);
      ctx.globalAlpha = ((+level + 0.5) / 4) * (c === "x" ? 0.55 : 0.8);
      ctx.beginPath();
      for (let k = 0; k < list.length; k += 2) {
        ctx.moveTo(X(list[k]), Y(list[k]));
        ctx.lineTo(X(list[k + 1]), Y(list[k + 1]));
      }
      ctx.stroke();
    }

    // Glow of recent presses.
    const now = shown.length ? shown[Math.floor(head)] + (head - Math.floor(head)) : 0;
    const glow = glowAt(b.presses, now, n);
    ctx.globalCompositeOperation = "lighter";
    for (let i = 0; i < n; i++) {
      if (!glow[i]) continue;
      const g = glow[i];
      const d = r * (5 + 5 * g);
      ctx.globalAlpha = 0.25 + 0.65 * g;
      ctx.drawImage(sprite, X(i) - d, Y(i) - d, 2 * d, 2 * d);
    }
    ctx.globalCompositeOperation = "source-over";

    // Dots, unseen ones faded, batched by colour.
    for (const faded of [true, false]) {
      const byColor = new Map();
      for (let i = 0; i < n; i++) {
        if (Boolean(vis[i]) === faded) continue;
        const c = courseColor(nodeCourse[i]);
        let list = byColor.get(c);
        if (!list) byColor.set(c, (list = []));
        list.push(i);
      }
      ctx.globalAlpha = faded ? 0.2 : 1;
      for (const [c, list] of byColor) {
        ctx.fillStyle = c;
        ctx.beginPath();
        for (const i of list) {
          ctx.moveTo(X(i) + r, Y(i));
          ctx.arc(X(i), Y(i), r, 0, 2 * Math.PI);
        }
        ctx.fill();
      }
    }
    // A bright core on a dot that just pressed.
    ctx.fillStyle = colors.glow;
    for (let i = 0; i < n; i++) {
      if (glow[i] < 0.05) continue;
      ctx.globalAlpha = glow[i];
      ctx.beginPath();
      ctx.arc(X(i), Y(i), r * 0.55, 0, 2 * Math.PI);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
  }

  // --- time
  function settle(steps = 80) {
    for (let k = 0; k < steps; k++) sim.step(weights, vis);
  }

  function frame(ts) {
    raf = 0;
    const dt = last ? Math.min(0.1, (ts - last) / 1000) : 1 / 60;
    last = ts;
    if (playing && shown.length && ts >= nightUntil) {
      night.classList.remove("on");
      let next = head + dt * speed * 12;
      const from = Math.floor(head);
      for (let i = from; i < Math.floor(next) && i < shown.length - 1; i++) {
        if (isGap(shown, i)) {
          next = i + 1;
          nightUntil = ts + (reduced ? 0 : NIGHT_MS);
          night.classList.add("on");
          break;
        }
      }
      if (next >= shown.length - 1) {
        next = shown.length - 1;
        setPlaying(false);
      }
      head = next;
      load(Math.floor(head));
    }
    sim.step(weights, vis, Math.max(1, Math.min(8, Math.round(dt * 120))));
    draw(true);
    const moving = playing || sim.energy() > 0.0004 || ts < nightUntil || camMoving;
    // setPlaying(false) at the end of the timeline may already have scheduled a frame.
    if (raf) return;
    if (moving && onscreen) raf = requestAnimationFrame(frame);
    else last = 0;
  }

  function wake() {
    if (raf || !onscreen) return;
    if (reduced && !playing) {
      settle();
      draw();
      return;
    }
    raf = requestAnimationFrame(frame);
  }

  function setPlaying(on) {
    playing = on && shown.length > 1;
    if (playing && head >= shown.length - 1) head = 0;
    root.classList.toggle("playing", playing);
    relabel();
    wake();
  }

  function seekIndex(i) {
    head = Math.max(0, Math.min(shown.length - 1, i));
    nightUntil = 0;
    night.classList.remove("on");
    load(Math.floor(head));
    wake();
  }

  // --- events
  playButton.addEventListener("click", () => setPlaying(!playing));
  scrub.addEventListener("input", () => seekIndex(+scrub.value));
  speedButtons.forEach((btn, k) =>
    btn.addEventListener("click", () => {
      speed = SPEEDS[k];
      relabel();
    }),
  );
  dayButtons.forEach((btn, k) => btn.addEventListener("click", () => seekIndex(days[k].index)));
  stage.addEventListener("keydown", (e) => {
    if (e.key === " " || e.key === "k") {
      e.preventDefault();
      setPlaying(!playing);
    } else if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      e.preventDefault();
      const step = (e.shiftKey ? 12 : 1) * (e.key === "ArrowRight" ? 1 : -1);
      seekIndex(Math.floor(head) + step);
    }
  });
  fsButton.addEventListener("click", () => {
    if (document.fullscreenElement) document.exitFullscreen?.();
    else root.requestFullscreen?.().catch(() => {});
  });
  document.addEventListener("fullscreenchange", () => {
    relabel();
    requestAnimationFrame(resize);
  });
  new ResizeObserver(() => resize()).observe(canvas);
  if ("IntersectionObserver" in window) {
    new IntersectionObserver((entries) => {
      onscreen = entries.some((e) => e.isIntersecting);
      if (onscreen) wake();
    }).observe(stage);
  }

  // --- start
  readColors();
  load(Math.floor(head));
  settle(reduced ? 120 : 60);
  relabel();
  resize();
  setPlaying(!opts.paused);

  return {
    seekTo(bin) {
      const i = model.lowerBound(shown, bin);
      seekIndex(Math.min(i, shown.length - 1)); // wake() settles at once under reduced motion
    },
    pause: () => setPlaying(false),
    play: () => setPlaying(true),
    relabel,
  };
}
