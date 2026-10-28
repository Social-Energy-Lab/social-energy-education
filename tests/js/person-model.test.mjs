// person-model.js: the person view's computations, on hand-built tables with hand-derived answers.
//
// Three nodes, six 5-min bins (the B of model.test.mjs, trimmed):
//   pairs   bin0: (0,1) -60, (0,2) -70 · bin1: (0,1) -62 · bin2: (0,1) -55
//   seen    bin0: 0,1,2 · bin1: 0,1 · bin2: 0
//   rooms   bin0: 0→loc0, 1→loc1 · bin1: 0→loc1
//   presses 10 s node 0 · 100 s node 1 · 700 s node 0
import assert from "node:assert/strict";
import { test } from "node:test";

import * as p from "../../src/social_energy/explorer/static/person-model.js";

const B = {
  pairs: {
    bin: Uint16Array.from([0, 0, 1, 2]),
    a: Uint16Array.from([0, 0, 0, 0]),
    b: Uint16Array.from([1, 2, 1, 1]),
    rssi: Int8Array.from([-60, -70, -62, -55]),
  },
  seen: { bin: Uint16Array.from([0, 0, 0, 1, 1, 2]), node: Uint16Array.from([0, 1, 2, 0, 1, 0]) },
  rooms: { bin: Uint16Array.from([0, 0, 1]), node: Uint16Array.from([0, 1, 0]), loc: Uint16Array.from([0, 1, 1]) },
  presses: { sec: Uint32Array.from([10, 100, 700]), node: Uint16Array.from([0, 1, 0]) },
};

// EDA: node 1 has ten usable minutes on day 0, rate 1/min except minutes 4 and 5 (rate 9) and
// minute 8 (unusable); node 2 has two minutes.
const N = p.NONE;
const EDA = {
  min: Uint32Array.from([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 0, 1]),
  node: Uint16Array.from([1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2, 2]),
  scr: Uint16Array.from([100, 100, 100, 100, 900, 900, 100, 100, N, 100, 200, 300]),
  scr_strict: Uint16Array.from([0, 0, 0, 0, 400, 0, 0, 0, N, 0, 0, 0]),
  hr: Uint8Array.from([70, 71, 72, 0, 90, 91, 70, 70, 70, 70, 0, 0]),
  flags: Uint8Array.from([3, 3, 3, 1, 7, 7, 3, 3, 2, 3, 1, 1]),
};
const RULE = { z: 1.5, min_usable_minutes: 5, merge_minutes: 2 };

test("eda index finds each node's rows; a node without EDA has an empty range", () => {
  const ix = p.edaIndex(EDA, 3);
  assert.deepEqual([[...ix.lo], [...ix.hi]], [[0, 0, 10], [0, 10, 12]]);
});

test("EDA moments: high SCR minutes against the person-day, merged into one", () => {
  // Usable rates: seven 1s and two 9s (minute 8 is not usable): mean 25/9, so z(9) ~ 2.0.
  const mean = 25 / 9;
  const sd = Math.sqrt((7 * (1 - mean) ** 2 + 2 * (9 - mean) ** 2) / 8);
  const m = p.edaMoments(EDA, 0, 10, () => 0, RULE);
  assert.equal(m.length, 1);
  assert.equal(m[0].min, 4);
  assert.equal(m[0].last, 5);
  assert.equal(m[0].uncertain, true);
  assert.ok(Math.abs(m[0].z - (9 - mean) / sd) < 1e-9);
});

test("EDA moments need enough usable minutes in the person-day", () => {
  assert.deepEqual(p.edaMoments(EDA, 10, 12, () => 0, RULE), []);
  assert.deepEqual(p.edaMoments(EDA, 0, 10, () => 0, { ...RULE, min_usable_minutes: 20 }), []);
});

test("EDA moments follow the chosen SCR rule", () => {
  const m = p.edaMoments(EDA, 0, 10, () => 0, RULE, "scr_strict");
  assert.deepEqual(m.map((x) => x.min), [4]);
});

test("rooms, seen and close-other series for one person", () => {
  assert.deepEqual([...p.roomSeries(B, 0, 4)], [0, 1, -1, -1]);
  assert.deepEqual([...p.seenSeries(B, 1, 4)], [1, 1, 0, 0]);
  assert.deepEqual([...p.closeSeries(B, 0, -65, 4)], [1, 1, 1, 0]);
  assert.deepEqual([...p.closeSeries(B, 0, -80, 4)], [2, 1, 1, 0]);
});

test("who was close in a bin, strongest first", () => {
  assert.deepEqual(p.closeAt(B, 0, 0, -80), [{ node: 1, rssi: -60 }, { node: 2, rssi: -70 }]);
  assert.deepEqual(p.closeAt(B, 2, 0, -65), []);
});

test("a person's presses, and the nearest one within a window", () => {
  assert.deepEqual(p.pressesOf(B, 0), [10, 700]);
  assert.equal(p.nearestPress(B, 1, 10, 300), 90);
  assert.equal(p.nearestPress(B, 1, 500, 300), null);
  assert.equal(p.nearestPress(B, 0, 400, 300), 300);
});

test("programme items apply when all-camp or in the person's room", () => {
  const events = [
    { start_bin: 0, end_bin: 2, all_camp: true, locs: [] },
    { start_bin: 0, end_bin: 4, all_camp: false, locs: [1] },
  ];
  assert.deepEqual(p.eventsAt(events, 0, 0), [events[0]]);
  assert.deepEqual(p.eventsAt(events, 1, 1), events);
  assert.deepEqual(p.eventsAt(events, 3, -1), []);
  const rooms = p.roomSeries(B, 0, 4); // [0, 1, -1, -1]
  assert.deepEqual(p.eventRuns(events, rooms, 0, 4), [[0, 0, 2], [1, 1, 2]]);
});

test("membrane type labels and keys", () => {
  assert.equal(p.typeLabel({ trust: "high", lust: "low" }), "high trust · low lust");
  assert.equal(p.typeKey(null), "none");
  assert.equal(p.typeKey({ trust: "low", lust: "high" }), "low-high");
});

test("counts per day and the camp's mean per person", () => {
  assert.deepEqual(p.countBy([0, 0, 2, 5], 3), [2, 0, 1]);
  assert.deepEqual(p.meanCounts([[2, 0], [0, 4]], 2), [1, 2]);
  assert.deepEqual(p.meanCounts([], 2), [null, null]);
});

test("EDA around a minute, with gaps as null", () => {
  const w = p.edaAround(EDA, 0, 10, 4, 2, 6);
  assert.equal(w.length, 9);
  assert.deepEqual(w[0], { off: -2, scr: 1, hr: 72, uncertain: false });
  assert.deepEqual(w[1], { off: -1, scr: 1, hr: null, uncertain: false });
  assert.equal(w[2].scr, 9);
  assert.equal(w[6].scr, null); // minute 8: worn, not usable
  assert.equal(w[7].scr, 1); // minute 9
  assert.equal(w[8], null); // minute 10: not worn
});

test("runs of equal keys", () => {
  const keys = [1, 1, 2, 2, 2, 1];
  assert.deepEqual(p.runs(0, 6, (k) => keys[k]), [[0, 2, 1], [2, 5, 2], [5, 6, 1]]);
  assert.deepEqual(p.runs(1, 3, (k) => keys[k]), [[1, 2, 1], [2, 3, 2]]);
  assert.deepEqual(p.runs(3, 3, (k) => keys[k]), []);
});
