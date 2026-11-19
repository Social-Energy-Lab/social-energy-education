// The explorer: loads the bundle, holds the state, runs playback, and feeds the views.
import * as model from "./model.js";
import * as network from "./views/network.js";
import * as matrix from "./views/matrix.js";
import * as zones from "./views/zones.js";
import * as presses from "./views/presses.js";
import * as strips from "./views/strips.js";
import * as person from "./views/person.js";
import * as programme from "./views/programme.js";
import * as framePanel from "./views/frame.js";
import * as soundView from "./views/sound.js";
import { explanations, personExplanations } from "./views/explain.js";

const $ = (id) => document.getElementById(id);

async function load() {
  const status = $("loading");
  const meta = await (await fetch("bundle/meta.json")).json();
  // The hosted copy ships a gzip copy of each file (deploy.py): a fifth of the bytes.
  const gz = await fetch("bundle/compressed.json").then((r) => r.ok, () => false)
    && typeof DecompressionStream === "function";
  let done = 0;
  const get = async (file) => {
    const res = await fetch(`bundle/${file}${gz ? ".gz" : ""}`);
    if (!res.ok) throw new Error(`${file}: HTTP ${res.status}`);
    const body = gz ? new Response(res.body.pipeThrough(new DecompressionStream("gzip"))) : res;
    const buf = await body.arrayBuffer();
    done++;
    status.textContent = `Loading the data… ${done} of ${total} files`;
    return buf;
  };
  const names = Object.keys(meta.files);
  const total = names.length + (meta.person ? 1 : 0) + (meta.person?.moments ? 1 : 0) + (meta.sound ? 1 : 0);
  const buffers = Object.fromEntries(
    await Promise.all(names.map(async (n) => [n, await get(`${n}.bin`)])),
  );
  const json = async (file) => JSON.parse(new TextDecoder().decode(await get(file)));
  // The person view's data, in a team bundle that carries it.
  const personDoc = meta.person ? await json(meta.person.file) : null;
  // What participants wrote about their moments: team bundles that carry it only.
  const moments = meta.person?.moments ? (await json(meta.person.moments)).moments : null;
  // How the halls sounded, per room and 5-minute bin (bundle.py): no people in it.
  const sound = meta.sound ? await json(meta.sound) : null;
  if (sound) sound.sorted = sound.leq.map((row) => model.sortedLevels(row));
  return { meta, b: model.decode(meta, buffers), person: personDoc, moments, sound };
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

function makeContext(meta, b, personDoc, moments) {
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
    meta, b, person: personDoc, moments, events: personDoc?.events ?? [], nNodes, nBins, nodeCourse, courseSize, hasUnknown, dayOfBin, dayRange,
    binsPerHour: 3600 / meta.bin_seconds,
    locZone: meta.locations.map((l) => l.zone),
    courseName: (c) => (c < 0 ? "course not known" : meta.courses[c].name),
    // The study ID where the team bundle carries one, else the shuffled index.
    personName: (i) => personDoc?.people[i]?.study_id ?? `Person ${i}`,
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
    picked: [], // nodes picked in the network or the frame, highlighted everywhere
    item: null, // programme item (index into ctx.events) whose people alone are shown
    tab: "camp", // "camp" or "person"
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
  if (ctx.person) {
    $("tabs").hidden = false;
    for (const btn of $("tabs").querySelectorAll("button")) {
      btn.addEventListener("click", () => set({ tab: btn.dataset.tab, playing: false }));
    }
  }

  const scrub = $("scrub");
  scrub.max = String(ctx.nBins - 1);
  for (const d of meta.days) $("day").append(new Option(d.label, String(d.start_bin)));
  $("phase").append(new Option("—", ""));
  meta.phases.forEach((p, i) => $("phase").append(new Option(p, String(i))));
  meta.courses.forEach((c, i) => $("course").append(new Option(c.name, String(i))));
  $("rssi").min = String(Math.max(-80, meta.rssi_floor));

  // The plain sentence: "Lines join two people who were [close] for at least [15 min] in the
  // last [2 h]". Each choice moves the matching slider under Advanced, and back.
  const plainClose = model.closenessOptions(initialState(meta).closeRssi, Number($("rssi").min));
  ctx.plain = {
    close: plainClose.map((o) => [o.value, o.label]),
    min: [5, 10, 15, 30, 60].map((m) => [m, `${m} min`]),
    win: [30, 60, 120, 180, 360].map((m) => [m, m < 60 ? `${m} min` : `${m / 60} h`]),
  };
  for (const [id, key] of [["close-plain", "closeRssi"], ["min-plain", "minMinutes"], ["win-plain", "windowMinutes"]]) {
    $(id).addEventListener("change", (e) => set({ [key]: Number(e.target.value) }));
  }

  // More views: one at a time; the view redraws when it is shown, so it measures its width.
  for (const btn of document.querySelectorAll("[data-more]")) {
    btn.addEventListener("click", () => {
      for (const b2 of document.querySelectorAll("[data-more]")) {
        b2.setAttribute("aria-selected", String(b2 === btn));
      }
      for (const pane of document.querySelectorAll("[data-pane]")) {
        pane.hidden = pane.dataset.pane !== btn.dataset.more;
      }
      set({});
    });
  }

  // Advanced is a menu: a click elsewhere or Esc closes it.
  const adv = document.querySelector(".advanced");
  document.addEventListener("click", (e) => { if (adv.open && !adv.contains(e.target)) adv.open = false; });
  document.addEventListener("keydown", (e) => { if (e.code === "Escape") adv.open = false; });

  // The person drawer.
  const closeDrawer = () => set({ tab: "camp" });
  $("drawer-close").addEventListener("click", closeDrawer);
  $("drawer-backdrop").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (e) => {
    if (e.code === "Escape" && $("popup").hidden && state.tab === "person") closeDrawer();
  });

  // A link to this view. The clipboard needs a secure page; elsewhere the link is shown to copy.
  $("share").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(location.href);
      $("share").textContent = "Link copied";
      setTimeout(() => { $("share").textContent = "Copy link"; }, 2000);
    } catch {
      $("share-out").hidden = false;
      $("share-out").value = location.href;
      $("share-out").select();
    }
  });

  // The time bar is sticky and its height varies (programme rows, wrapping): the workspace
  // below fills what is left of the screen.
  new ResizeObserver(() => {
    document.documentElement.style.setProperty("--nav-h", `${$("controls").offsetHeight}px`);
  }).observe($("controls"));

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
      course: null, zone: null, cell: null, picked: [], item: null });
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
  const personTab = state.tab === "person";
  $("person-view").hidden = !personTab;
  $("drawer-backdrop").hidden = !personTab;
  document.body.classList.toggle("person-mode", personTab);
  for (const btn of $("tabs").querySelectorAll("button")) {
    btn.setAttribute("aria-selected", String(btn.dataset.tab === state.tab));
  }
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
  plainSelect($("close-plain"), state.closeRssi, ctx.plain.close, (v) => `${v} dBm (set under Advanced)`);
  plainSelect($("min-plain"), state.minMinutes, ctx.plain.min, (v) => `${v} min`);
  plainSelect($("win-plain"), state.windowMinutes, ctx.plain.win,
    (v) => (v % 60 ? `${v} min` : `${v / 60} h`));
  const day = ctx.meta.days.find((d) => d.index === ctx.dayOfBin[bin]);
  if (day) $("day").value = String(day.start_bin);
  $("when-day").textContent = ctx.dayLabel(bin);
  $("when-clock").textContent = `${ctx.clockLabel(bin)} · ${ctx.phaseName(bin)}`;
  const camp = model.programmeAt(ctx.events, bin).filter((e) => e.all_camp).map((e) => e.label);
  const note = [...camp, ...ctx.noteAt(bin).map((n) => n.text),
    ...ctx.shadeAt(bin).map((n) => n.label)].join(" · ");
  $("when-note").textContent = note;
  $("when-note").title = note;
}

function fullSwing(ctx) {
  const n = new Uint16Array(ctx.nBins);
  for (const bin of ctx.b.seen.bin) n[bin]++;
  const first = n.findIndex((k) => k >= ctx.nNodes / 2);
  return first < 0 ? 0 : Math.min(ctx.nBins - 1, first + 2 * ctx.binsPerHour);
}

// Fill a plain choice; a value set with the Advanced sliders gets its own entry.
function plainSelect(sel, value, options, customLabel) {
  const opts = options.some(([v]) => v === value) ? options : [...options, [value, customLabel(value)]];
  const key = opts.map(([v]) => v).join(",");
  if (sel.dataset.key !== key) {
    sel.dataset.key = key;
    sel.replaceChildren(...opts.map(([v, label]) => new Option(label, String(v))));
  }
  sel.value = String(value);
}

// People in a link go by study ID where the bundle has one, else by index.
function linkId(ctx, i) { return ctx.person?.people[i]?.study_id ?? String(i); }
function linkNode(ctx, id) {
  const byId = ctx.person?.people.findIndex((p) => p.study_id === id) ?? -1;
  const node = byId >= 0 ? byId : /^\d+$/.test(id) ? Number(id) : -1;
  return node >= 0 && node < ctx.nNodes ? node : null;
}

async function main() {
  try {
    const saved = localStorage.getItem("explorer-theme");
    if (saved) document.documentElement.dataset.theme = saved;
  } catch { /* private mode */ }
  let loaded;
  try {
    loaded = await load();
    $("loading").hidden = true;
  } catch (err) {
    $("loading").hidden = true;
    $("error").hidden = false;
    $("error").textContent = `Could not load the bundle: ${err.message}. Run the export first.`;
    return;
  }
  const ctx = makeContext(loaded.meta, loaded.b, loaded.person, loaded.moments);
  ctx.sound = loaded.sound;
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

  // A pop-up with one written description in full (a page element, not a browser dialog).
  const pop = $("popup");
  const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  ctx.showMoment = (m) => {
    const when = m.sec !== null
      ? `${ctx.dayLabel(m.sec / ctx.meta.bin_seconds)} ${ctx.clockLabel(m.sec / ctx.meta.bin_seconds)}`
      : m.day !== null ? ctx.dayLabel(ctx.dayRange(m.day)[0]) : "no date";
    pop.querySelector(".pop-body").innerHTML = `
      <h3>${esc(ctx.personName(m.node))} <span class="muted">· ${esc(ctx.courseName(ctx.nodeCourse[m.node]))}</span></h3>
      <p class="muted">${esc(when)}${m.when ? ` · written as “${esc(m.when)}”` : ""}</p>
      <p class="pop-text">${esc(m.text)}</p>
      <p class="muted small">Transcribed from the participant's paper card. Free text by a minor: research team only.</p>
      <p>${m.sec !== null ? `<button type="button" data-go="${Math.floor(m.sec / ctx.meta.bin_seconds)}">Go to this time</button>` : m.day !== null ? `<button type="button" data-go="${ctx.dayRange(m.day)[0]}">Go to this day</button>` : ""}
      <button type="button" data-pick="${m.node}">${state.picked.includes(m.node) ? "Unpick" : "Pick"} in the network</button>
      ${ctx.openPerson ? `<button type="button" data-person="${m.node}">Open this person</button>` : ""}</p>`;
    pop.hidden = false;
    pop.querySelector("[data-go]")?.addEventListener("click", (e) => {
      pop.hidden = true;
      set({ tab: "camp", bin: Number(e.target.dataset.go), playing: false });
    });
    pop.querySelector("[data-pick]").addEventListener("click", () => {
      pop.hidden = true;
      const has = state.picked.includes(m.node);
      set({ tab: "camp", picked: has ? state.picked.filter((x) => x !== m.node) : [...state.picked, m.node] });
    });
    pop.querySelector("[data-person]")?.addEventListener("click", () => {
      pop.hidden = true;
      ctx.openPerson(m.node, m.sec !== null ? Math.floor(m.sec / ctx.meta.bin_seconds) : undefined);
    });
  };
  pop.querySelector(".pop-close").addEventListener("click", () => { pop.hidden = true; });
  document.addEventListener("keydown", (e) => { if (e.code === "Escape") pop.hidden = true; });

  // One programme item's people: the window starts no earlier than the item, and only people
  // placed in its rooms (model.itemMembers) and the ties between them are shown. The filter
  // ends when the playhead leaves the item.
  let memberKey = "";
  ctx.members = null;
  const itemFilter = (st, p) => {
    const ev = st.item === null ? null : ctx.events[st.item];
    const bin = Math.floor(st.bin);
    if (ev && (bin < ev.start_bin || bin >= ev.end_bin)) st.item = null;
    if (st.item === null) {
      ctx.members = null;
      memberKey = "";
      return model.edges(ctx.b, p);
    }
    p.windowBins = Math.max(1, Math.min(p.windowBins, p.endBin - ev.start_bin));
    const key = `${st.item}|${p.endBin}`;
    if (key !== memberKey) {
      memberKey = key;
      ctx.members = model.itemMembers(ctx.b, ev, ev.start_bin, p.endBin, ctx.nNodes);
    }
    const e = model.edges(ctx.b, p);
    return ctx.members ? model.filterEdges(e, ctx.members) : e;
  };
  // Click an item (programme strip, frame): show only its people, or jump to an all-camp item
  // or one without a room. A second click shows everyone again.
  ctx.pickItem = (k) => {
    const ev = ctx.events[k];
    if (state.item === k) return set({ item: null });
    const bin = Math.floor(state.bin);
    const inside = bin >= ev.start_bin && bin < ev.end_bin;
    const winBins = Math.round(state.windowMinutes / (ctx.meta.bin_seconds / 60));
    const to = inside ? bin : Math.min(ev.end_bin - 1, ev.start_bin + winBins - 1);
    const filterable = ctx.itemsFull[k] !== null;
    set({ bin: to, playing: false, item: filterable ? k : null });
  };
  ctx.itemsFull = ctx.events.map((ev) => model.itemMembers(ctx.b, ev, 0, ctx.nBins, ctx.nNodes));

  const views = [
    network.create($("network"), ctx, $("legend")),
    matrix.create($("matrix"), ctx),
    zones.create($("zones"), ctx),
    presses.create($("presses"), ctx),
    strips.create($("strips"), ctx),
    framePanel.create($("frame"), ctx),
  ];
  if (ctx.events.length) {
    $("programme-panel").hidden = false;
    views.push(programme.create($("programme"), ctx, { maxLanes: 3 }));
  }
  if (ctx.sound) {
    for (const node of document.querySelectorAll("[data-more='sound']")) node.hidden = false;
    views.push(soundView.create($("sound"), ctx));
  }
  if (ctx.person) {
    views.push(person.create($("person-view"), ctx));
    personExplanations(ctx);
  }
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
      const e = itemFilter(state, p);
      // Controls first: they show the active tab, so views measure their real width.
      syncControls(ctx, state);
      for (const v of views) v.update(state, p, e, changed);
      if (!state.playing && [...changed].some((k) => LINKED.has(k))) saveLink();
      changed.clear();
      dirty = false;
    }
    requestAnimationFrame(frame);
  };
  // The address keeps the view (model.viewToHash), so a link or a bookmark reopens it: the time,
  // the picked people, the person open and any changed setting. #person=12&bin=300 still works.
  const defaults = initialState(ctx.meta);
  const LINKED = new Set(["bin", "playing", "picked", "tab", "closeRssi", "minMinutes", "windowMinutes", "course", "person", "item"]);
  const saveLink = () => {
    const open = state.tab === "person" && ctx.currentPerson ? ctx.currentPerson() : null;
    const hash = model.viewToHash({
      ...state,
      picked: state.picked.map((i) => linkId(ctx, i)),
      person: open === null ? null : linkId(ctx, open),
    }, defaults);
    history.replaceState(null, "", `#${hash}`);
  };
  ctx.personChanged = () => { changed.add("person"); dirty = true; };
  const want = model.hashToView(location.hash);
  // Without a link, open where the camp is in full swing: two hours after the first 5 minutes
  // in which half the participants were heard, so the window is full and the network has lines.
  const patch = want.bin === undefined ? { bin: fullSwing(ctx) } : {};
  if (want.bin !== undefined) patch.bin = Math.max(0, Math.min(ctx.nBins - 1, want.bin));
  for (const k of ["closeRssi", "minMinutes", "windowMinutes"]) if (want[k] !== undefined) patch[k] = want[k];
  if (want.course !== undefined && want.course >= 0 && want.course < ctx.meta.courses.length) patch.course = want.course;
  if (want.item !== undefined && ctx.itemsFull[want.item]) patch.item = want.item;
  if (want.picked) patch.picked = want.picked.map((id) => linkNode(ctx, id)).filter((n) => n !== null);
  set(patch);
  if (ctx.openPerson && want.person) {
    const node = linkNode(ctx, want.person);
    if (node !== null) ctx.openPerson(node, want.bin);
  }
  changed.add("init");
  requestAnimationFrame(frame);
  window.addEventListener("resize", () => set({}));
}

main();
