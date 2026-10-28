// The person view's computations: pure functions over a decoded bundle and person.json.
//
// Besides the tables in model.js, a bundle with person data holds
//   b.eda {min, node, scr, scr_strict, hr, flags}   sorted by node, then minute
// (minutes since t0; rates x100 with 65535 = none; hr 0 = none; flags 1 usable, 2 hr_ok,
// 4 clock_uncertain) and person.json (see person.py). Nothing here touches the DOM.
import { lowerBound, windowRange } from "./model.js";

export const NONE = 65535;
export const USABLE = 1;
export const HR_OK = 2;
export const CLOCK_UNCERTAIN = 4;

/** Row range [lo, hi) of each node in the node-sorted eda table. */
export function edaIndex(eda, nNodes) {
  const lo = new Int32Array(nNodes).fill(0);
  const hi = new Int32Array(nNodes).fill(0);
  const n = eda ? eda.node.length : 0;
  for (let i = 0; i < n; ) {
    const node = eda.node[i];
    let j = i;
    while (j < n && eda.node[j] === node) j++;
    lo[node] = i;
    hi[node] = j;
    i = j;
  }
  return { lo, hi };
}

/** SCR rate (per minute) of row i under a rule ("scr" or "scr_strict"), or null. */
export function rate(eda, i, rule = "scr") {
  const v = eda[rule][i];
  return v === NONE ? null : v / 100;
}

/** EDA moments of one person: usable minutes whose SCR rate is at least rule.z SDs above the
 *  person-day's mean (days with at least rule.min_usable_minutes usable minutes only); minutes
 *  at most rule.merge_minutes apart join one moment, timed at its first minute and scored by
 *  its highest z. dayOfMin(min) gives the camp day. Exploratory: not a validated measure. */
export function edaMoments(eda, lo, hi, dayOfMin, rule, which = "scr") {
  const days = new Map();
  for (let i = lo; i < hi; i++) {
    const r = rate(eda, i, which);
    if (r === null) continue;
    const d = dayOfMin(eda.min[i]);
    let s = days.get(d);
    if (!s) days.set(d, (s = { n: 0, sum: 0, sq: 0 }));
    s.n += 1;
    s.sum += r;
    s.sq += r * r;
  }
  const stats = new Map();
  for (const [d, s] of days) {
    if (s.n < rule.min_usable_minutes || s.n < 2) continue;
    const mean = s.sum / s.n;
    const sd = Math.sqrt(Math.max(0, (s.sq - s.n * mean * mean) / (s.n - 1)));
    if (sd > 0) stats.set(d, { mean, sd });
  }
  const out = [];
  let cur = null;
  for (let i = lo; i < hi; i++) {
    const r = rate(eda, i, which);
    if (r === null) continue;
    const st = stats.get(dayOfMin(eda.min[i]));
    if (!st) continue;
    const z = (r - st.mean) / st.sd;
    if (z < rule.z) continue;
    const m = eda.min[i];
    if (cur && m - cur.last <= rule.merge_minutes) {
      cur.last = m;
      if (z > cur.z) { cur.z = z; cur.rate = r; }
    } else {
      cur = { min: m, last: m, z, rate: r, uncertain: !!(eda.flags[i] & CLOCK_UNCERTAIN) };
      out.push(cur);
    }
  }
  return out;
}

/** Per bin, the location index the person was placed in, or -1. */
export function roomSeries(b, node, nBins) {
  const out = new Int16Array(nBins).fill(-1);
  const r = b.rooms;
  for (let i = 0; i < r.bin.length; i++) if (r.node[i] === node && r.bin[i] < nBins) out[r.bin[i]] = r.loc[i];
  return out;
}

/** Per bin, 1 when the person's tag was heard. */
export function seenSeries(b, node, nBins) {
  const out = new Uint8Array(nBins);
  const s = b.seen;
  for (let i = 0; i < s.bin.length; i++) if (s.node[i] === node && s.bin[i] < nBins) out[s.bin[i]] = 1;
  return out;
}

/** Per bin, how many others were at or above closeRssi with the person. */
export function closeSeries(b, node, closeRssi, nBins) {
  const out = new Uint16Array(nBins);
  const p = b.pairs;
  for (let i = 0; i < p.bin.length; i++) {
    if (p.rssi[i] < closeRssi || (p.a[i] !== node && p.b[i] !== node)) continue;
    if (p.bin[i] < nBins) out[p.bin[i]] += 1;
  }
  return out;
}

/** Others close to the person in one bin: [{node, rssi}], strongest first. */
export function closeAt(b, node, bin, closeRssi) {
  const p = b.pairs;
  const [lo, hi] = windowRange(p.bin, bin + 1, 1);
  const out = [];
  for (let i = lo; i < hi; i++) {
    if (p.rssi[i] < closeRssi) continue;
    if (p.a[i] === node) out.push({ node: p.b[i], rssi: p.rssi[i] });
    else if (p.b[i] === node) out.push({ node: p.a[i], rssi: p.rssi[i] });
  }
  return out.sort((x, y) => y.rssi - x.rssi);
}

/** Seconds of the person's presses, ascending. */
export function pressesOf(b, node) {
  const out = [];
  const { sec, node: n } = b.presses;
  for (let i = 0; i < sec.length; i++) if (n[i] === node) out.push(sec[i]);
  return out;
}

/** Signed gap (s) from `sec` to the person's nearest press within windowSec, or null. */
export function nearestPress(b, node, sec, windowSec) {
  const ps = b.presses;
  const lo = lowerBound(ps.sec, sec - windowSec);
  let best = null;
  for (let i = lo; i < ps.sec.length && ps.sec[i] <= sec + windowSec; i++) {
    if (ps.node[i] !== node) continue;
    const gap = ps.sec[i] - sec;
    if (best === null || Math.abs(gap) < Math.abs(best)) best = gap;
  }
  return best;
}

/** Programme items that apply to a person in a bin: all-camp items, or items in their room. */
export function eventsAt(events, bin, loc) {
  return events.filter((e) => bin >= e.start_bin && bin < e.end_bin &&
    (e.all_camp || (loc >= 0 && e.locs.includes(loc))));
}

/** Per event that applies to the person at some bin: its runs of bins, as [event, from, to). */
export function eventRuns(events, rooms, fromBin, toBin) {
  const out = [];
  events.forEach((e, k) => {
    const a = Math.max(fromBin, e.start_bin);
    const z = Math.min(toBin, e.end_bin);
    let start = -1;
    for (let bin = a; bin <= z; bin++) {
      const on = bin < z && (e.all_camp || (rooms[bin] >= 0 && e.locs.includes(rooms[bin])));
      if (on && start < 0) start = bin;
      if (!on && start >= 0) { out.push([k, start, bin]); start = -1; }
    }
  });
  return out;
}

/** "high trust · low lust", or null without both composites. */
export function typeLabel(type) {
  return type ? `${type.trust} trust · ${type.lust} lust` : null;
}

/** Type key "high-low" (trust-lust) for filtering, or "none". */
export function typeKey(type) {
  return type ? `${type.trust}-${type.lust}` : "none";
}

/** Counts per index of `keys` (e.g. camp day per moment) into an array of length n. */
export function countBy(keys, n) {
  const out = new Array(n).fill(0);
  for (const k of keys) if (k >= 0 && k < n) out[k] += 1;
  return out;
}

/** Mean of per-person count arrays (each length n), or nulls when nobody is in the group. */
export function meanCounts(arrays, n) {
  if (!arrays.length) return new Array(n).fill(null);
  const out = new Array(n).fill(0);
  for (const a of arrays) for (let i = 0; i < n; i++) out[i] += a[i];
  return out.map((v) => v / arrays.length);
}

/** EDA around a minute: per offset from -before to +after, {scr, hr, uncertain} or null. */
export function edaAround(eda, lo, hi, centerMin, before, after, which = "scr") {
  const out = [];
  let i = lowerBound(eda.min.subarray(lo, hi), centerMin - before) + lo;
  for (let off = -before; off <= after; off++) {
    const m = centerMin + off;
    while (i < hi && eda.min[i] < m) i++;
    if (i < hi && eda.min[i] === m) {
      const hr = eda.flags[i] & HR_OK && eda.hr[i] ? eda.hr[i] : null;
      out.push({ off, scr: rate(eda, i, which), hr, uncertain: !!(eda.flags[i] & CLOCK_UNCERTAIN) });
    } else out.push(null);
  }
  return out;
}

/** Runs of equal keyFn(k) over [from, to): [start, end, key]. */
export function runs(from, to, keyFn) {
  const out = [];
  let start = from;
  let key = from < to ? keyFn(from) : null;
  for (let k = from + 1; k <= to; k++) {
    const next = k < to ? keyFn(k) : Symbol("end");
    if (next !== key) {
      out.push([start, k, key]);
      start = k;
      key = next;
    }
  }
  return out;
}
