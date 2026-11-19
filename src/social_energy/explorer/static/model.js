// The explorer's computations: pure functions over a decoded bundle (see bundle.py).
//
// A decoded bundle `b` holds typed-array columns per table, sorted by bin:
//   b.pairs {bin, a, b, rssi} · b.seen {bin, node} · b.rooms {bin, node, loc}
//   b.presses {sec, node} · b.bins {phase, day}
// Nothing here touches the DOM, so it is tested with Node (tests/js/).

const TYPES = { u8: Uint8Array, i8: Int8Array, u16: Uint16Array, u32: Uint32Array };
const LITTLE_ENDIAN = new Uint8Array(new Uint16Array([1]).buffer)[0] === 1;

/** Columns per table from meta.files and the raw .bin buffers (little-endian). */
export function decode(meta, buffers) {
  const out = {};
  for (const [name, spec] of Object.entries(meta.files)) {
    const buf = buffers[name];
    const view = new DataView(buf);
    let offset = 0;
    const cols = {};
    for (const [col, type] of spec.columns) {
      const T = TYPES[type];
      const size = T.BYTES_PER_ELEMENT;
      if (LITTLE_ENDIAN) {
        // Copy the column out (offsets need not be aligned) and view it: no per-value loop.
        cols[col] = new T(buf.slice(offset, offset + size * spec.count));
        offset += size * spec.count;
        continue;
      }
      const arr = new T(spec.count);
      for (let i = 0; i < spec.count; i++) {
        const at = offset + i * size;
        arr[i] =
          type === "u8" ? view.getUint8(at)
          : type === "i8" ? view.getInt8(at)
          : type === "u16" ? view.getUint16(at, true)
          : view.getUint32(at, true);
      }
      cols[col] = arr;
      offset += size * spec.count;
    }
    out[name] = cols;
  }
  return out;
}

/** First index i with sorted[i] >= value. */
export function lowerBound(sorted, value) {
  let lo = 0;
  let hi = sorted.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (sorted[mid] < value) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/** Row range [lo, hi) of a bin-sorted column for bins in [endBin - windowBins, endBin). */
export function windowRange(binCol, endBin, windowBins) {
  return [lowerBound(binCol, Math.max(0, endBin - windowBins)), lowerBound(binCol, endBin)];
}

/** Pairs at or above closeRssi in at least minBins bins of the window. */
export function edges(b, { endBin, windowBins, closeRssi, minBins }) {
  const p = b.pairs;
  const [lo, hi] = windowRange(p.bin, endBin, windowBins);
  const acc = new Map();
  for (let i = lo; i < hi; i++) {
    if (p.rssi[i] < closeRssi) continue;
    const key = p.a[i] * 65536 + p.b[i];
    const cur = acc.get(key);
    if (cur) {
      cur[0] += 1;
      if (p.rssi[i] > cur[1]) cur[1] = p.rssi[i];
    } else acc.set(key, [1, p.rssi[i]]);
  }
  const e = { a: [], b: [], bins: [], maxRssi: [] };
  for (const [key, [n, r]] of acc) {
    if (n < minBins) continue;
    e.a.push(Math.floor(key / 65536));
    e.b.push(key % 65536);
    e.bins.push(n);
    e.maxRssi.push(r);
  }
  return e;
}

/** 1 for every node whose tag was heard in the window. */
export function visible(b, endBin, windowBins, nNodes) {
  const out = new Uint8Array(nNodes);
  const [lo, hi] = windowRange(b.seen.bin, endBin, windowBins);
  for (let i = lo; i < hi; i++) out[b.seen.node[i]] = 1;
  return out;
}

const group = (course, nCourses) => (course < 0 ? nCourses : course);

/** Ties by course pair, symmetric, with unknown course as the last row/column. */
export function mixing(e, nodeCourse, nCourses) {
  const n = nCourses + 1;
  const counts = new Float64Array(n * n);
  let cross = 0;
  for (let i = 0; i < e.a.length; i++) {
    const ca = group(nodeCourse[e.a[i]], nCourses);
    const cb = group(nodeCourse[e.b[i]], nCourses);
    counts[ca * n + cb] += 1;
    if (ca !== cb) {
      counts[cb * n + ca] += 1;
      cross += 1;
    }
  }
  const total = e.a.length;
  return { counts, total, crossShare: total ? cross / total : null };
}

/** Share of ties across courses expected if the visible people mixed at random. */
export function randomCrossShare(vis, nodeCourse, nCourses) {
  const sizes = new Array(nCourses + 1).fill(0);
  let total = 0;
  vis.forEach((v, i) => {
    if (!v) return;
    sizes[group(nodeCourse[i], nCourses)] += 1;
    total += 1;
  });
  if (total < 2) return null;
  const same = sizes.reduce((s, k) => s + k * (k - 1), 0);
  return 1 - same / (total * (total - 1));
}

/** Per bin in [fromBin, toBin): people per zone, then seen-but-unplaced, flattened. */
export function zoneSeries(b, locZone, nZones, fromBin, toBin) {
  const width = nZones + 1;
  const len = Math.max(0, toBin - fromBin);
  const counts = new Uint16Array(len * width);
  const placed = new Set();
  const [rlo, rhi] = windowRange(b.rooms.bin, toBin, len);
  for (let i = rlo; i < rhi; i++) {
    const k = b.rooms.bin[i] - fromBin;
    counts[k * width + locZone[b.rooms.loc[i]]] += 1;
    placed.add(b.rooms.bin[i] * 65536 + b.rooms.node[i]);
  }
  const [slo, shi] = windowRange(b.seen.bin, toBin, len);
  for (let i = slo; i < shi; i++) {
    if (!placed.has(b.seen.bin[i] * 65536 + b.seen.node[i])) {
      counts[(b.seen.bin[i] - fromBin) * width + nZones] += 1;
    }
  }
  return { counts, width };
}

/** Number of close others per (bin, node), as a flat nBins * nNodes array. */
export function closeCounts(b, closeRssi, nNodes, nBins) {
  const out = new Uint16Array(nBins * nNodes);
  const p = b.pairs;
  for (let i = 0; i < p.bin.length; i++) {
    if (p.rssi[i] < closeRssi) continue;
    out[p.bin[i] * nNodes + p.a[i]] += 1;
    out[p.bin[i] * nNodes + p.b[i]] += 1;
  }
  return out;
}

/** Mean close others at a press against the pressers' ordinary seen bins, per phase. */
export function companyByPhase(b, closeRssi, nNodes, nBins, nPhases, binSeconds = 300) {
  const close = closeCounts(b, closeRssi, nNodes, nBins);
  const pressSum = new Array(nPhases).fill(0);
  const nPress = new Array(nPhases).fill(0);
  for (let i = 0; i < b.presses.sec.length; i++) {
    const k = Math.floor(b.presses.sec[i] / binSeconds);
    if (k >= nBins) continue;
    const ph = b.bins.phase[k];
    pressSum[ph] += close[k * nNodes + b.presses.node[i]];
    nPress[ph] += 1;
  }
  // Ordinary bins: those of the participants who pressed at least once, as in the analysis.
  const pressed = new Uint8Array(nNodes);
  for (const n of b.presses.node) pressed[n] = 1;
  const ordSum = new Array(nPhases).fill(0);
  const nOrd = new Array(nPhases).fill(0);
  for (let i = 0; i < b.seen.bin.length; i++) {
    if (!pressed[b.seen.node[i]]) continue;
    const k = b.seen.bin[i];
    const ph = b.bins.phase[k];
    ordSum[ph] += close[k * nNodes + b.seen.node[i]];
    nOrd[ph] += 1;
  }
  const mean = (s, n) => s.map((v, i) => (n[i] ? v / n[i] : null));
  return { atPress: mean(pressSum, nPress), ordinary: mean(ordSum, nOrd), nPress };
}

/** 1 for a press when another wearer, close in that bin, pressed within withinSec. */
export function sharedMoments(b, closeRssi, withinSec, binSeconds) {
  const { sec, node } = b.presses;
  const p = b.pairs;
  // Close pairs, only in bins that hold a press: numeric keys bin * 2^32 + a * 2^16 + b.
  const close = new Set();
  const pressBins = new Set(Array.from(sec, (s) => Math.floor(s / binSeconds)));
  for (const bin of pressBins) {
    const [lo, hi] = windowRange(p.bin, bin + 1, 1);
    for (let i = lo; i < hi; i++) {
      if (p.rssi[i] >= closeRssi) close.add(bin * 4294967296 + p.a[i] * 65536 + p.b[i]);
    }
  }
  const isClose = (bin, x, y) =>
    close.has(bin * 4294967296 + Math.min(x, y) * 65536 + Math.max(x, y));
  const out = new Uint8Array(sec.length);
  for (let i = 0; i < sec.length; i++) {
    for (let j = i + 1; j < sec.length && sec[j] - sec[i] <= withinSec; j++) {
      if (node[i] === node[j]) continue;
      const bi = Math.floor(sec[i] / binSeconds);
      const bj = Math.floor(sec[j] / binSeconds);
      if (isClose(bi, node[i], node[j]) || isClose(bj, node[i], node[j])) {
        out[i] = 1;
        out[j] = 1;
      }
    }
  }
  return out;
}

/** Presses per hour since t0. */
export function perHour(b, binSeconds, nHours) {
  const out = new Uint16Array(nHours);
  for (const s of b.presses.sec) {
    const h = Math.floor(s / 3600);
    if (h < nHours) out[h] += 1;
  }
  return out;
}

/** Mean ties per visible node (2E/N) for windows ending every stepBins; NaN when nobody heard.
 *  One pass with a sliding window, so a slider can redraw it while it moves. */
export function tiesSeries(b, { windowBins, closeRssi, minBins }, stepBins, nNodes, nBins) {
  const steps = Math.floor(nBins / stepBins);
  const out = new Float64Array(steps);
  const p = b.pairs;
  const s = b.seen;
  const pairCount = new Map(); // a * 65536 + b -> close bins in the window
  const seenCount = new Uint32Array(nNodes);
  let ties = 0;
  let heard = 0;
  let pIn = 0, pOut = 0, sIn = 0, sOut = 0;
  const pairDelta = (i, d) => {
    if (p.rssi[i] < closeRssi) return;
    const key = p.a[i] * 65536 + p.b[i];
    const before = pairCount.get(key) ?? 0;
    const after = before + d;
    if (after) pairCount.set(key, after); else pairCount.delete(key);
    if (before < minBins && after >= minBins) ties++;
    if (before >= minBins && after < minBins) ties--;
  };
  for (let k = 0; k < steps; k++) {
    const endBin = (k + 1) * stepBins;
    const startBin = Math.max(0, endBin - windowBins);
    for (; pIn < p.bin.length && p.bin[pIn] < endBin; pIn++) pairDelta(pIn, 1);
    for (; pOut < pIn && p.bin[pOut] < startBin; pOut++) pairDelta(pOut, -1);
    for (; sIn < s.bin.length && s.bin[sIn] < endBin; sIn++) if (seenCount[s.node[sIn]]++ === 0) heard++;
    for (; sOut < sIn && s.bin[sOut] < startBin; sOut++) if (--seenCount[s.node[sOut]] === 0) heard--;
    out[k] = heard ? (2 * ties) / heard : NaN;
  }
  return out;
}

/** Number of tags heard per bin. */
export function seenPerBin(b, nBins) {
  const out = new Uint16Array(nBins);
  for (const k of b.seen.bin) if (k < nBins) out[k] += 1;
  return out;
}

/** A count fit to show, or "<min" when the group is too small to protect anonymity. */
export function suppress(n, min) {
  return n < min ? `<${min}` : String(n);
}

/** Close bins per pair before startBin (from bin 0) at or above closeRssi: key a*65536+b -> bins.
 *  "Already close before" in the paused frame: social familiarity, as against closeness now. */
export function pairHistory(b, closeRssi, startBin) {
  const p = b.pairs;
  const hi = lowerBound(p.bin, startBin);
  const out = new Map();
  for (let i = 0; i < hi; i++) {
    if (p.rssi[i] < closeRssi) continue;
    const key = p.a[i] * 65536 + p.b[i];
    out.set(key, (out.get(key) ?? 0) + 1);
  }
  return out;
}

/** The window's ties, each with its close bins before the window and its history level:
 *  0 new (fewer than levels[0] bins before), 1 acquainted (fewer than levels[1]), 2 close.
 *  Also the count of ties per level, and per visible node its ties and ties per level. */
export function frame(e, history, levels, vis) {
  const ties = [];
  const counts = [0, 0, 0];
  const per = new Map();
  for (let i = 0; i < e.a.length; i++) {
    const before = history.get(e.a[i] * 65536 + e.b[i]) ?? 0;
    const level = before < levels[0] ? 0 : before < levels[1] ? 1 : 2;
    ties.push({ a: e.a[i], b: e.b[i], bins: e.bins[i], maxRssi: e.maxRssi[i], before, level });
    counts[level]++;
    for (const n of [e.a[i], e.b[i]]) {
      const row = per.get(n) ?? [0, 0, 0];
      row[level]++;
      per.set(n, row);
    }
  }
  const people = [];
  vis.forEach((v, n) => {
    if (!v) return;
    const row = per.get(n) ?? [0, 0, 0];
    people.push({ node: n, ties: row[0] + row[1] + row[2], levels: row });
  });
  return { ties, counts, people };
}

/** Indices of presses with fromSec <= sec < toSec. */
export function pressesIn(b, fromSec, toSec) {
  const s = b.presses.sec;
  const out = [];
  for (let i = lowerBound(s, fromSec); i < s.length && s[i] < toSec; i++) out.push(i);
  return out;
}

/** What node wrote about a press at sec: their description timed nearest to it within
 *  toleranceSec, or null. `moments` is moments.json's list ({node, sec, day, when, text});
 *  writers gave clock times to the hour at best, so the default tolerance is wide. */
export function descriptionAt(moments, node, sec, toleranceSec = 45 * 60) {
  let best = null;
  for (const m of moments || []) {
    if (m.node !== node || m.sec === null || Math.abs(m.sec - sec) > toleranceSec) continue;
    if (best === null || Math.abs(m.sec - sec) < Math.abs(best.sec - sec)) best = m;
  }
  return best;
}

/** Descriptions written by node, or dated to camp day `day` (null: any), in file order. */
export function descriptionsOf(moments, { node = null, day = null } = {}) {
  return (moments || []).filter((m) => (node === null || m.node === node) &&
    (day === null || m.day === day));
}

/** Programme items overlapping [fromBin, toBin) in lanes, so overlapping items never share one:
 *  [{k, start, end, lane}] (k indexes `events`), with the number of lanes used. All-camp items
 *  are placed first, so they take the top lanes. */
export function programmeLanes(events, fromBin, toBin) {
  const items = [];
  events.forEach((e, k) => {
    if (e.end_bin <= fromBin || e.start_bin >= toBin) return;
    items.push({ k, start: Math.max(fromBin, e.start_bin), end: Math.min(toBin, e.end_bin),
      all: e.all_camp ? 0 : 1 });
  });
  items.sort((x, y) => x.all - y.all || x.start - y.start || y.end - x.end);
  const laneEnd = [];
  for (const it of items) {
    let lane = laneEnd.findIndex((end) => end <= it.start);
    if (lane < 0) { lane = laneEnd.length; laneEnd.push(0); }
    laneEnd[lane] = it.end;
    it.lane = lane;
    delete it.all;
  }
  return { items, lanes: laneEnd.length };
}

/** Programme items running at bin: all-camp ones, then the rest. */
export function programmeAt(events, bin) {
  const on = events.filter((e) => bin >= e.start_bin && bin < e.end_bin);
  return [...on.filter((e) => e.all_camp), ...on.filter((e) => !e.all_camp)];
}

// The plain choices for "together means": a stricter step, the analysis default, a looser step
// and everything recorded (the export floor). Signal strength is uncalibrated, so the labels
// say stricter or looser, never metres.
export function closenessOptions(defaultRssi, floor, step = 7) {
  const opts = [
    { key: "strict", value: defaultRssi + step, label: "very close (strongest signals only)" },
    { key: "default", value: defaultRssi, label: "close (the analysis setting)" },
    { key: "loose", value: defaultRssi - step, label: "nearby (weaker signals too)" },
    { key: "all", value: floor, label: "anything recorded" },
  ];
  const out = [];
  for (const o of opts) {
    const v = Math.max(o.value, floor);
    if (!out.some((x) => x.value === v)) out.push({ ...o, value: v });
  }
  return out;
}

// What the address keeps of a view: the 5-minute bin, picked people, the person open and any
// setting that differs from the analysis defaults. People go by study ID (or index).
export function viewToHash(view, defaults) {
  const q = [`t=${Math.floor(view.bin)}`];
  if (view.picked?.length) q.push(`pick=${view.picked.join(",")}`);
  if (view.closeRssi !== defaults.closeRssi) q.push(`close=${view.closeRssi}`);
  if (view.minMinutes !== defaults.minMinutes) q.push(`min=${view.minMinutes}`);
  if (view.windowMinutes !== defaults.windowMinutes) q.push(`win=${view.windowMinutes}`);
  if (view.course !== null && view.course !== undefined) q.push(`course=${view.course}`);
  if (view.person !== null && view.person !== undefined) q.push(`person=${view.person}`);
  if (view.item !== null && view.item !== undefined) q.push(`item=${view.item}`);
  return q.join("&");
}

// The view an address names; anything missing or malformed is left out. `bin=` is the older
// spelling of `t=`.
export function hashToView(hash) {
  const h = new URLSearchParams(hash.replace(/^#/, ""));
  const out = {};
  const int = (k) => (h.has(k) && /^-?\d+$/.test(h.get(k)) ? Number(h.get(k)) : null);
  const bin = int("t") ?? int("bin");
  if (bin !== null) out.bin = bin;
  const picked = (h.get("pick") ?? "").split(",").filter(Boolean);
  if (picked.length) out.picked = picked;
  for (const [k, name] of [["close", "closeRssi"], ["min", "minMinutes"], ["win", "windowMinutes"], ["course", "course"], ["item", "item"]]) {
    const v = int(k);
    if (v !== null) out[name] = v;
  }
  if (h.get("person")) out.person = h.get("person");
  return out;
}

// A room's recorded levels, ascending, gaps (null) left out: the reference for louderThan.
export function sortedLevels(levels) {
  return Float32Array.from(levels.filter((v) => v !== null && v !== undefined)).sort();
}

// The percent of a room's recorded 5-minute bins quieter than `value`; null with no recording.
export function louderThan(sorted, value) {
  if (!sorted.length) return null;
  return Math.round((100 * lowerBound(sorted, value)) / sorted.length);
}

// ---- one programme item ---------------------------------------------------------------------------

// Who was at a programme item: placed by their room tag in one of the item's rooms for more than
// half of the 5-minute bins they were placed in, over the item's bins in [fromBin, toBin) (the
// whole item when that is empty, as when the playhead is before it). 1 per member; null for an
// all-camp item (everyone) or one without a room in the log (cannot tell).
export function itemMembers(b, event, fromBin, toBin, nNodes) {
  if (event.all_camp || !event.locs?.length) return null;
  let a = Math.max(fromBin, event.start_bin);
  let z = Math.min(toBin, event.end_bin);
  if (z <= a) { a = event.start_bin; z = event.end_bin; }
  const locs = new Set(event.locs);
  const placed = new Uint16Array(nNodes);
  const inside = new Uint16Array(nNodes);
  const r = b.rooms;
  for (let i = lowerBound(r.bin, a), hi = lowerBound(r.bin, z); i < hi; i++) {
    placed[r.node[i]]++;
    if (locs.has(r.loc[i])) inside[r.node[i]]++;
  }
  const out = new Uint8Array(nNodes);
  for (let n = 0; n < nNodes; n++) out[n] = inside[n] * 2 > placed[n] ? 1 : 0;
  return out;
}

// The ties whose two people are both members.
export function filterEdges(e, members) {
  const out = { a: [], b: [], bins: [], maxRssi: [] };
  for (let i = 0; i < e.a.length; i++) {
    if (!members[e.a[i]] || !members[e.b[i]]) continue;
    out.a.push(e.a[i]);
    out.b.push(e.b[i]);
    out.bins.push(e.bins[i]);
    out.maxRssi.push(e.maxRssi[i]);
  }
  return out;
}

// ---- one person's people --------------------------------------------------------------------------

// Everyone who was at close range of `node` over the study: {node, bins, perDay}, most close
// bins first (ties by node).
export function tiesOf(b, node, closeRssi, dayOfBin, nDays) {
  const p = b.pairs;
  const acc = new Map();
  for (let i = 0; i < p.bin.length; i++) {
    if (p.rssi[i] < closeRssi) continue;
    const other = p.a[i] === node ? p.b[i] : p.b[i] === node ? p.a[i] : -1;
    if (other < 0) continue;
    let t = acc.get(other);
    if (!t) { t = { node: other, bins: 0, perDay: new Uint16Array(nDays) }; acc.set(other, t); }
    t.bins++;
    const d = dayOfBin[p.bin[i]];
    if (d !== undefined && d < nDays) t.perDay[d]++;
  }
  return [...acc.values()].sort((x, y) => y.bins - x.bins || x.node - y.node);
}

// Indices of the room items (members not null) that both `i` and `j` were at.
export function sharedItems(memberships, i, j) {
  const out = [];
  memberships.forEach((m, k) => { if (m && m[i] && m[j]) out.push(k); });
  return out;
}

// ---- sound ----------------------------------------------------------------------------------------

// A bin's frequency mix from its six band levels (dB, bands 0-300, 300-1000, 1000-2000,
// 2000-4000, 4000-8000, 8000-24000 Hz): the share of the sound's power below 300 Hz, in the
// voice range 300-4000 Hz, and above 4000 Hz. Null without levels.
export function soundMix(bands) {
  if (!bands || bands.some((v) => v === null || v === undefined)) return null;
  const pw = bands.map((v) => 10 ** (v / 10));
  const total = pw.reduce((s, v) => s + v, 0);
  if (!(total > 0)) return null;
  return [pw[0] / total, (pw[1] + pw[2] + pw[3]) / total, (pw[4] + pw[5]) / total];
}
