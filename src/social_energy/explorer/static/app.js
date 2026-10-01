// The explorer: loads the bundle, holds the state, runs playback, and feeds the views.
import * as model from "./model.js";
import * as network from "./views/network.js";
import * as matrix from "./views/matrix.js";
import * as zones from "./views/zones.js";
import * as presses from "./views/presses.js";
import * as strips from "./views/strips.js";
import { explanations } from "./views/explain.js";

const $ = (id) => document.getElementById(id);

async function load() {
  const meta = await (await fetch("bundle/meta.json")).json();
  const names = Object.keys(meta.files);
  const buffers = Object.fromEntries(
    await Promise.all(
      names.map(async (n) => [n, await (await fetch(`bundle/${n}.bin`)).arrayBuffer()]),
    ),
  );
  return { meta, b: model.decode(meta, buffers) };
}

function themeColors(meta) {
  const css = getComputedStyle(document.documentElement);
  const v = (name) => css.getPropertyValue(name).trim();
  const course = meta.courses.map((_, i) => v(`--course-${(i % 6) + 1}`));
  return {
    course,
    unknown: v("--course-unknown"),
    ink1: v("--ink-1"), ink2: v("--ink-2"), ink3: v("--ink-3"),
    rule: v("--rule"), surface: v("--surface-1"), glow: v("--glow"), accent: v("--accent"),
    seqLo: v("--seq-lo"), seqHi: v("--seq-hi"), zoneLo: v("--zone-lo"), zoneHi: v("--zone-hi"),
    shade: v("--shade"),
  };
}

function makeContext(meta, b) {
  const nNodes = meta.nodes.length;
  const nBins = meta.n_bins;
  const t0 = Date.parse(meta.t0);
  const fmtDay = new Intl.DateTimeFormat("en-GB", {
    timeZone: meta.timezone, weekday: "short", day: "2-digit", month: "short",
  });
  const fmtClock = new Intl.DateTimeFormat("en-GB", {
    timeZone: meta.timezone, hour: "2-digit", minute: "2-digit",
  });
  const binTime = (bin) => new Date(t0 + bin * meta.bin_seconds * 1000);
  const nodeCourse = meta.nodes.map((n) => n.course);
  const courseSize = meta.courses.map((_, c) => nodeCourse.filter((x) => x === c).length);
  const hasUnknown = nodeCourse.some((c) => c < 0);
  const dayOfBin = b.bins.day;
  const dayRange = (d) => {
    const start = meta.days.find((x) => x.index === d)?.start_bin ?? 0;
    const next = meta.days.find((x) => x.index === d + 1)?.start_bin ?? nBins;
    return [start, next];
  };
  return {
    meta, b, nNodes, nBins, nodeCourse, courseSize, hasUnknown, dayOfBin, dayRange,
    binsPerHour: 3600 / meta.bin_seconds,
    locZone: meta.locations.map((l) => l.zone),
    courseName: (c) => (c < 0 ? "course not known" : meta.courses[c].name),
    dayLabel: (bin) => fmtDay.format(binTime(bin)),
    clockLabel: (bin) => fmtClock.format(binTime(bin)),
    phaseName: (bin) => meta.phases[b.bins.phase[Math.min(bin, nBins - 1)]] ?? "",
    noteAt: (bin) => meta.notes.filter((n) => bin >= n.start_bin && bin < n.end_bin),
    shadeAt: (bin) => meta.shade.filter((n) => bin >= n.start_bin && bin < n.end_bin),
    colors: themeColors(meta),
  };
}

function initialState(meta) {
  const d = meta.defaults;
  return {
    bin: Math.min(meta.n_bins - 1, 12 * 9), // a morning, so the first screen has ties
    playing: false,
    speed: 36, // bins per second
    closeRssi: Math.max(d.close_rssi, meta.rssi_floor),
    minMinutes: d.min_minutes,
    windowMinutes: d.window_minutes,
    course: null, // highlighted course index
    zone: null, // highlighted zone index
    cell: null, // [ci, cj] highlighted matrix cell
  };
}

function params(state, ctx) {
  const binMin = ctx.meta.bin_seconds / 60;
  return {
    endBin: Math.floor(state.bin) + 1,
    windowBins: Math.max(1, Math.round(state.windowMinutes / binMin)),
    closeRssi: state.closeRssi,
    minBins: Math.max(1, Math.round(state.minMinutes / binMin)),
  };
}

function setupControls(ctx, state, set) {
  const { meta } = ctx;
  $("badge").textContent =
    meta.mode === "team"
      ? "Team view · pseudonymised data · keep it to the research team"
      : meta.mode === "synthetic" ? "Synthetic data · no real people" : "Public view";
  $("badge").classList.toggle("team", meta.mode === "team");

  const scrub = $("scrub");
  scrub.max = String(ctx.nBins - 1);
  for (const d of meta.days) $("day").append(new Option(d.label, String(d.start_bin)));
  $("phase").append(new Option("—", ""));
  meta.phases.forEach((p, i) => $("phase").append(new Option(p, String(i))));
  meta.courses.forEach((c, i) => $("course").append(new Option(c.name, String(i))));
  $("rssi").min = String(Math.max(-80, meta.rssi_floor));

  scrub.addEventListener("input", () => set({ bin: Number(scrub.value), playing: false }));
  $("play").addEventListener("click", () => set({ playing: !state.playing }));
  $("speed").addEventListener("change", (e) => set({ speed: Number(e.target.value) }));
  $("day").addEventListener("change", (e) => set({ bin: Number(e.target.value) }));
  $("phase").addEventListener("change", (e) => {
    if (e.target.value === "") return;
    const want = Number(e.target.value);
    const [lo, hi] = ctx.dayRange(ctx.dayOfBin[Math.floor(state.bin)]);
    for (let k = lo; k < hi; k++) {
      if (ctx.b.bins.phase[k] === want) return set({ bin: k });
    }
  });
  $("rssi").addEventListener("input", (e) => set({ closeRssi: Number(e.target.value) }));
  $("min").addEventListener("input", (e) => set({ minMinutes: Number(e.target.value) }));
  $("win").addEventListener("input", (e) => set({ windowMinutes: Number(e.target.value) }));
  $("course").addEventListener("change", (e) =>
    set({ course: e.target.value === "" ? null : Number(e.target.value) }),
  );
  $("reset").addEventListener("click", () => {
    const d = initialState(meta);
    set({ closeRssi: d.closeRssi, minMinutes: d.minMinutes, windowMinutes: d.windowMinutes,
      course: null, zone: null, cell: null });
  });
  $("theme").addEventListener("click", () => {
    const root = document.documentElement;
    const dark = root.dataset.theme
      ? root.dataset.theme === "dark"
      : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("explorer-theme", root.dataset.theme); } catch { /* private mode */ }
    ctx.colors = themeColors(meta);
    set({});
  });
  document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
    if (e.code === "Space") { e.preventDefault(); set({ playing: !state.playing }); }
    if (e.code === "ArrowRight") set({ bin: Math.min(ctx.nBins - 1, Math.floor(state.bin) + 1) });
    if (e.code === "ArrowLeft") set({ bin: Math.max(0, Math.floor(state.bin) - 1) });
  });
}

function syncControls(ctx, state) {
  const bin = Math.floor(state.bin);
  $("play").textContent = state.playing ? "❚❚" : "▶";
  $("play").setAttribute("aria-label", state.playing ? "Pause" : "Play");
  $("scrub").value = String(bin);
  $("rssi").value = String(state.closeRssi);
  $("rssi-out").textContent = String(state.closeRssi);
  $("min").value = String(state.minMinutes);
  $("min-out").textContent = String(state.minMinutes);
  $("win").value = String(state.windowMinutes);
  $("win-out").textContent =
    state.windowMinutes % 60 ? `${state.windowMinutes} min` : `${state.windowMinutes / 60} h`;
  $("course").value = state.course === null ? "" : String(state.course);
  const day = ctx.meta.days.find((d) => d.index === ctx.dayOfBin[bin]);
  if (day) $("day").value = String(day.start_bin);
  $("when-day").textContent = ctx.dayLabel(bin);
  $("when-clock").textContent = `${ctx.clockLabel(bin)} · ${ctx.phaseName(bin)}`;
  $("when-note").textContent = [...ctx.noteAt(bin).map((n) => n.text),
    ...ctx.shadeAt(bin).map((n) => n.label)].join(" · ");
}

async function main() {
  try {
    const saved = localStorage.getItem("explorer-theme");
    if (saved) document.documentElement.dataset.theme = saved;
  } catch { /* private mode */ }
  let loaded;
  try {
    loaded = await load();
  } catch (err) {
    $("error").hidden = false;
    $("error").textContent = `Could not load the bundle: ${err.message}. Run the export first.`;
    return;
  }
  const ctx = makeContext(loaded.meta, loaded.b);
  const state = initialState(ctx.meta);
  const tooltip = $("tooltip");
  ctx.tip = {
    show(html, x, y) {
      tooltip.innerHTML = html;
      tooltip.hidden = false;
      const w = tooltip.offsetWidth;
      tooltip.style.left = `${Math.min(x + 14, window.innerWidth - w - 8)}px`;
      tooltip.style.top = `${y + 14}px`;
    },
    hide() { tooltip.hidden = true; },
  };

  let dirty = true;
  const changed = new Set();
  const set = (patch) => {
    for (const [k, v] of Object.entries(patch)) {
      if (state[k] !== v) changed.add(k);
      state[k] = v;
    }
    if (Object.keys(patch).length === 0) changed.add("theme");
    dirty = true;
  };
  ctx.set = set;

  const views = [
    network.create($("network"), ctx, $("legend")),
    matrix.create($("matrix"), ctx),
    zones.create($("zones"), ctx),
    presses.create($("presses"), ctx),
    strips.create($("strips"), ctx),
  ];
  setupControls(ctx, state, set);
  explanations(ctx);

  let last = performance.now();
  const frame = (now) => {
    const dt = Math.min(0.1, (now - last) / 1000);
    last = now;
    if (state.playing) {
      const next = state.bin + state.speed * dt;
      if (Math.floor(next) !== Math.floor(state.bin)) changed.add("bin");
      state.bin = next >= ctx.nBins - 1 ? 0 : next;
      dirty = true;
    }
    if (dirty) {
      const p = params(state, ctx);
      const e = model.edges(ctx.b, p);
      for (const v of views) v.update(state, p, e, changed);
      syncControls(ctx, state);
      changed.clear();
      dirty = false;
    }
    requestAnimationFrame(frame);
  };
  changed.add("init");
  requestAnimationFrame(frame);
  window.addEventListener("resize", () => set({}));
}

main();
