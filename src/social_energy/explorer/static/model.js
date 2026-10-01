// The explorer's computations: pure functions over a decoded bundle (see bundle.py).
//
// A decoded bundle `b` holds typed-array columns per table, sorted by bin:
//   b.pairs {bin, a, b, rssi} · b.seen {bin, node} · b.rooms {bin, node, loc}
//   b.presses {sec, node} · b.bins {phase, day}
// Nothing here touches the DOM, so it is tested with Node (tests/js/).

const TYPES = { u8: Uint8Array, i8: Int8Array, u16: Uint16Array, u32: Uint32Array };

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
      const arr = new T(spec.count);
      const size = T.BYTES_PER_ELEMENT;
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

/** Mean close others at a press against ordinary seen bins, per phase (null when empty). */
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
  const ordSum = new Array(nPhases).fill(0);
  const nOrd = new Array(nPhases).fill(0);
  for (let i = 0; i < b.seen.bin.length; i++) {
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
  const close = new Set();
  const p = b.pairs;
  for (let i = 0; i < p.bin.length; i++) {
    if (p.rssi[i] >= closeRssi) close.add(`${p.bin[i]}:${p.a[i]}:${p.b[i]}`);
  }
  const isClose = (bin, x, y) => close.has(`${bin}:${Math.min(x, y)}:${Math.max(x, y)}`);
  const { sec, node } = b.presses;
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

/** Mean ties per visible node (2E/N) for windows ending every stepBins; NaN when nobody heard. */
export function tiesSeries(b, { windowBins, closeRssi, minBins }, stepBins, nNodes, nBins) {
  const steps = Math.floor(nBins / stepBins);
  const out = new Float64Array(steps);
  for (let k = 0; k < steps; k++) {
    const endBin = (k + 1) * stepBins;
    const n = visible(b, endBin, windowBins, nNodes).reduce((s, v) => s + v, 0);
    const e = edges(b, { endBin, windowBins, closeRssi, minBins });
    out[k] = n ? (2 * e.a.length) / n : NaN;
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
