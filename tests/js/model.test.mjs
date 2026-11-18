// model.js: the explorer's computations, on a hand-built bundle with hand-derived answers.
//
// Four nodes: 0 and 1 in course 0, node 2 in course 1, node 3 course unknown. Six 5-min bins.
//   pairs   bin0: (0,1) -60, (0,2) -70 · bin1: (0,1) -62, (2,3) -80 · bin2: (0,1) -55
//   seen    bin0: 0,1,2 · bin1: 0,1,2,3 · bin2: 0,1 · bin3: 3
//   rooms   bin0: 0→loc0, 1→loc1 · bin1: 0→loc0      (loc0 in zone 0, loc1 in zone 1)
//   presses 10 s node 0 · 100 s node 1 · 700 s node 2
//   phases  bins 0-1 phase 0, bins 2-5 phase 1
import assert from "node:assert/strict";
import { test } from "node:test";

import * as m from "../../src/social_energy/explorer/static/model.js";

const B = {
  pairs: {
    bin: Uint16Array.from([0, 0, 1, 1, 2]),
    a: Uint16Array.from([0, 0, 0, 2, 0]),
    b: Uint16Array.from([1, 2, 1, 3, 1]),
    rssi: Int8Array.from([-60, -70, -62, -80, -55]),
  },
  seen: {
    bin: Uint16Array.from([0, 0, 0, 1, 1, 1, 1, 2, 2, 3]),
    node: Uint16Array.from([0, 1, 2, 0, 1, 2, 3, 0, 1, 3]),
  },
  rooms: {
    bin: Uint16Array.from([0, 0, 1]),
    node: Uint16Array.from([0, 1, 0]),
    loc: Uint16Array.from([0, 1, 0]),
  },
  presses: { sec: Uint32Array.from([10, 100, 700]), node: Uint16Array.from([0, 1, 2]) },
  bins: { phase: Uint8Array.from([0, 0, 1, 1, 1, 1]), day: Uint8Array.from([0, 0, 0, 0, 0, 0]) },
};
const N = 4;
const NBINS = 6;
const COURSE = [0, 0, 1, -1];

test("edges keeps pairs close in enough bins of the window", () => {
  const e = m.edges(B, { endBin: 3, windowBins: 3, closeRssi: -65, minBins: 2 });
  assert.deepEqual([e.a, e.b, e.bins, e.maxRssi], [[0], [1], [3], [-55]]);
});

test("edges at a threshold nobody meets is empty, and so is mixing", () => {
  const e = m.edges(B, { endBin: 3, windowBins: 3, closeRssi: -50, minBins: 1 });
  assert.equal(e.a.length, 0);
  const mix = m.mixing(e, COURSE, 2);
  assert.equal(mix.total, 0);
  assert.equal(mix.crossShare, null);
});

test("mixing counts within, across, and an unknown course in the last row", () => {
  const e = m.edges(B, { endBin: 3, windowBins: 3, closeRssi: -80, minBins: 1 });
  const mix = m.mixing(e, COURSE, 2);
  assert.equal(mix.total, 3);
  assert.equal(mix.counts[0 * 3 + 0], 1); // (0,1) inside course 0
  assert.equal(mix.counts[0 * 3 + 1], 1); // (0,2) across
  assert.equal(mix.counts[2 * 3 + 1], 1); // (2,3): course 1 with unknown, unknown is row 2
  assert.equal(mix.crossShare, 2 / 3);
});

test("random mixing baseline for two courses of two", () => {
  const share = m.randomCrossShare(Uint8Array.from([1, 1, 1, 1]), [0, 0, 1, 1], 2);
  assert.ok(Math.abs(share - 2 / 3) < 1e-12, String(share));
  assert.equal(m.randomCrossShare(Uint8Array.from([1, 0, 0, 0]), [0, 0, 1, 1], 2), null);
});

test("visible marks nodes heard in the window", () => {
  assert.deepEqual([...m.visible(B, 3, 1, N)], [1, 1, 0, 0]);
});

test("zone series counts placed people per zone and seen-but-unplaced apart", () => {
  const z = m.zoneSeries(B, [0, 1], 2, 0, 2);
  assert.deepEqual([...z.counts], [1, 1, 1, 1, 0, 3]);
});

test("close counts per bin and node", () => {
  const c = m.closeCounts(B, -65, N, NBINS);
  assert.deepEqual([...c.slice(0, 3 * N)], [1, 1, 0, 0, 1, 1, 0, 0, 1, 1, 0, 0]);
});

test("company at a press against ordinary bins, per phase", () => {
  const c = m.companyByPhase(B, -65, N, NBINS, 2);
  assert.deepEqual(c.nPress, [2, 1]);
  assert.deepEqual(c.atPress, [1, 0]);
  // Ordinary bins are those of the participants who pressed (nodes 0-2), as in the analysis.
  assert.deepEqual(c.ordinary, [4 / 6, 1]);
});

test("shared moments: close people pressing within the window", () => {
  assert.deepEqual([...m.sharedMoments(B, -65, 300, 300)], [1, 1, 0]);
  assert.deepEqual([...m.sharedMoments(B, -65, 60, 300)], [0, 0, 0]);
});

test("presses per hour", () => {
  assert.deepEqual([...m.perHour(B, 300, 1)], [3]);
});

test("ties per participant over steps, null when nobody is heard", () => {
  const s = m.tiesSeries(B, { windowBins: 3, closeRssi: -65, minBins: 2 }, 3, N, NBINS);
  assert.deepEqual([...s], [0.5, 0]);
  const empty = m.tiesSeries({ ...B, seen: { bin: new Uint16Array(), node: new Uint16Array() } },
    { windowBins: 3, closeRssi: -65, minBins: 2 }, 3, N, NBINS);
  assert.ok(empty.every((v) => Number.isNaN(v)));
});

test("small groups are suppressed", () => {
  assert.equal(m.suppress(3, 5), "<5");
  assert.equal(m.suppress(7, 5), "7");
  assert.equal(m.suppress(5, 5), "5");
});

test("decode reads columns back from little-endian buffers", () => {
  const meta = {
    files: {
      presses: { count: 2, columns: [["sec", "u32"], ["node", "u16"]] },
    },
  };
  const buf = new ArrayBuffer(2 * 4 + 2 * 2);
  const view = new DataView(buf);
  view.setUint32(0, 10, true);
  view.setUint32(4, 70000, true);
  view.setUint16(8, 3, true);
  view.setUint16(10, 1, true);
  const d = m.decode(meta, { presses: buf });
  assert.deepEqual([...d.presses.sec], [10, 70000]);
  assert.deepEqual([...d.presses.node], [3, 1]);
});

// A bundle of the real size and shape: 1.4M pair readings over 4608 bins among 57 nodes.
function realSize() {
  let seed = 1;
  const r = (k) => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed % k; };
  const n = 1_400_000, N = 57, nBins = 4608;
  const pairs = { bin: new Uint16Array(n), a: new Uint16Array(n), b: new Uint16Array(n), rssi: new Int8Array(n) };
  for (let i = 0; i < n; i++) {
    pairs.bin[i] = Math.floor((i * nBins) / n);
    const a = r(N - 1);
    pairs.a[i] = a;
    pairs.b[i] = a + 1 + r(N - 1 - a);
    pairs.rssi[i] = -80 + r(30);
  }
  const sn = 210_000;
  const seen = { bin: new Uint16Array(sn), node: new Uint16Array(sn) };
  for (let i = 0; i < sn; i++) { seen.bin[i] = Math.floor((i * nBins) / sn); seen.node[i] = i % N; }
  const presses = {
    sec: Uint32Array.from({ length: 2000 }, (_, i) => i * 690),
    node: Uint16Array.from({ length: 2000 }, () => r(N)),
  };
  return { b: { pairs, seen, presses }, N, nBins };
}

// The best of three, so that one busy moment on a shared machine does not fail the test.
const timed = (f) => Math.min(...[0, 1, 2].map(() => {
  const t = performance.now(); f(); return performance.now() - t;
}));

test("slider-driven computations stay interactive at the real size", () => {
  const { b, N, nBins } = realSize();
  const shared = timed(() => m.sharedMoments(b, -80, 300, 300));
  const ties = timed(() => m.tiesSeries(b, { windowBins: 72, closeRssi: -80, minBins: 3 }, 6, N, nBins));
  assert.ok(shared < 200, `sharedMoments took ${Math.round(shared)} ms`);
  assert.ok(ties < 300, `tiesSeries took ${Math.round(ties)} ms`);
});

test("tiesSeries agrees with edges and visible step by step", () => {
  const { b, N, nBins } = realSize();
  const p = { windowBins: 30, closeRssi: -70, minBins: 4 };
  const s = m.tiesSeries(b, p, 6, N, 600);
  for (const k of [0, 3, 50, 99]) {
    const endBin = (k + 1) * 6;
    const n = m.visible(b, endBin, p.windowBins, N).reduce((x, v) => x + v, 0);
    const e = m.edges(b, { ...p, endBin });
    assert.equal(s[k], n ? (2 * e.a.length) / n : NaN);
  }
});

test("pairHistory counts close bins before the window", () => {
  // Before bin 2 at -65: (0,1) in bins 0 and 1; (0,2) is -70, below.
  const h = m.pairHistory(B, -65, 2);
  assert.deepEqual([...h.entries()], [[1, 2]]);
  assert.equal(m.pairHistory(B, -90, 1).get(2), 1); // (0,2) at bin 0
  assert.equal(m.pairHistory(B, -65, 0).size, 0);
});

test("frame sorts ties by how long the pair was close before", () => {
  // Window = bin 2 only: (0,1) at -55. Before: (0,1) close in 2 bins.
  const e = m.edges(B, { endBin: 3, windowBins: 1, closeRssi: -65, minBins: 1 });
  const vis = m.visible(B, 3, 1, N);
  const h = m.pairHistory(B, -65, 2);
  const at = (levels) => m.frame(e, h, levels, vis);
  assert.deepEqual(at([3, 5]).counts, [1, 0, 0]); // 2 bins before < 3: new
  assert.deepEqual(at([2, 5]).counts, [0, 1, 0]); // 2 >= 2, < 5: acquainted
  assert.deepEqual(at([1, 2]).counts, [0, 0, 1]); // 2 >= 2: close
  const f = at([2, 5]);
  assert.deepEqual(f.ties.map((t) => [t.a, t.b, t.before, t.level]), [[0, 1, 2, 1]]);
  assert.deepEqual(f.people, [{ node: 0, ties: 1, levels: [0, 1, 0] }, { node: 1, ties: 1, levels: [0, 1, 0] }]);
});

test("pressesIn and descriptionAt find a press and what was written for it", () => {
  assert.deepEqual(m.pressesIn(B, 0, 101), [0, 1]);
  assert.deepEqual(m.pressesIn(B, 101, 700), []);
  const moments = [
    { node: 0, sec: 15, day: 0, text: "a" }, { node: 0, sec: 400, day: 0, text: "c" },
    { node: 0, sec: null, day: 1, text: "d" }, { node: 2, sec: 90, day: 0, text: "b" },
  ];
  assert.equal(m.descriptionAt(moments, 0, 10, 120).text, "a");
  assert.equal(m.descriptionAt(moments, 1, 100, 120), null); // node 1 wrote nothing
  assert.equal(m.descriptionAt(moments, 0, 300, 120).text, "c"); // 100 s away, within 120
  assert.equal(m.descriptionAt(moments, 0, 250, 120), null); // 150 s from either of node 0's
  assert.equal(m.descriptionAt(moments, 0, 250).text, "c"); // default tolerance is wide
  assert.deepEqual(m.descriptionsOf(moments, { node: 0 }).map((x) => x.text), ["a", "c", "d"]);
  assert.deepEqual(m.descriptionsOf(moments, { day: 0 }).map((x) => x.text), ["a", "c", "b"]);
  assert.deepEqual(m.descriptionsOf(null, { day: 0 }), []);
});

test("programmeLanes keeps overlapping items apart and all-camp items on top", () => {
  const ev = [
    { start_bin: 0, end_bin: 4, all_camp: false },
    { start_bin: 2, end_bin: 6, all_camp: true },
    { start_bin: 4, end_bin: 5, all_camp: false },
    { start_bin: 9, end_bin: 12, all_camp: false }, // outside [0, 8)
  ];
  const { items, lanes } = m.programmeLanes(ev, 0, 8);
  assert.equal(lanes, 2);
  assert.deepEqual(items.map((i) => [i.k, i.lane, i.start, i.end]), [[1, 0, 2, 6], [0, 1, 0, 4], [2, 1, 4, 5]]);
  assert.deepEqual(m.programmeAt(ev, 3).map((e) => e.start_bin), [2, 0]);
});

// The plain "together means" choices and the link to a view.
test("closeness choices sit around the analysis default, never below the floor", () => {
  const opts = m.closenessOptions(-65, -80);
  assert.deepEqual(opts.map((o) => o.value), [-58, -65, -72, -80]);
  assert.equal(opts[1].key, "default");
  // A floor above the loosest step drops the steps it cuts off.
  assert.deepEqual(m.closenessOptions(-65, -70).map((o) => o.value), [-58, -65, -70]);
});

test("a view goes into the address and comes back, defaults left out", () => {
  const defaults = { closeRssi: -65, minMinutes: 15, windowMinutes: 120 };
  const view = { bin: 300, picked: ["62", "80"], closeRssi: -70, minMinutes: 15,
    windowMinutes: 120, course: 2, person: null };
  const hash = m.viewToHash(view, defaults);
  assert.equal(hash, "t=300&pick=62,80&close=-70&course=2");
  assert.deepEqual(m.hashToView(hash), { bin: 300, picked: ["62", "80"], closeRssi: -70, course: 2 });
  assert.equal(m.viewToHash({ ...view, picked: [], closeRssi: -65, course: null, person: "31" }, defaults),
    "t=300&person=31");
});

test("an address from before keeps working, and junk is ignored", () => {
  assert.deepEqual(m.hashToView("person=12&bin=40"), { bin: 40, person: "12" });
  assert.deepEqual(m.hashToView("t=abc&pick=&close=x&zzz=1"), {});
});

test("a level's place among a room's recorded levels, gaps ignored", () => {
  const sorted = m.sortedLevels([-50, null, -60, -40, null, -55]);
  assert.deepEqual(Array.from(sorted), [-60, -55, -50, -40]);
  assert.equal(m.louderThan(sorted, -50), 50); // above -60 and -55: 2 of the 4
  assert.equal(m.louderThan(sorted, -61), 0);
  assert.equal(m.louderThan(sorted, -40), 75);
  assert.equal(m.louderThan(new Float32Array(0), -40), null);
});
