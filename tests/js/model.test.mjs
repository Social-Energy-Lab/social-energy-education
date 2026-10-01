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
  assert.deepEqual(c.ordinary, [4 / 7, 2 / 3]);
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
