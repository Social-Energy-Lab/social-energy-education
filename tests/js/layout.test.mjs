// layout.js: the hero's home ring and force simulation (a port of camp_breathes.Simulation).
import assert from "node:assert/strict";
import { test } from "node:test";

import { homes, pairKey, Sim } from "../../src/social_energy/site/static/layout.js";

const meanAngle = (h, course, nodeCourse) => {
  let x = 0;
  let y = 0;
  let n = 0;
  nodeCourse.forEach((c, i) => {
    if (c !== course) return;
    x += h[2 * i];
    y += h[2 * i + 1];
    n += 1;
  });
  return { angle: Math.atan2(y / n, x / n), radius: Math.hypot(x / n, y / n) };
};

test("course 0's home is at the top of the ring, the others around it", () => {
  const nodeCourse = Array.from({ length: 120 }, (_, i) => i % 4);
  const h = homes(nodeCourse, 4, 7);
  assert.equal(h.length, 240);
  const c0 = meanAngle(h, 0, nodeCourse);
  assert.ok(Math.abs(c0.angle - Math.PI / 2) < 0.15, `angle ${c0.angle}`);
  assert.ok(Math.abs(c0.radius - 0.85) < 0.1, `radius ${c0.radius}`);
  const c1 = meanAngle(h, 1, nodeCourse);
  assert.ok(Math.abs(c1.angle - Math.PI) < 0.15, `course 1 at ${c1.angle}`);
});

test("homes are deterministic per seed and differ between seeds", () => {
  const nodeCourse = Int16Array.from([0, 1, 2, 0, 1, 2]);
  assert.deepEqual(homes(nodeCourse, 3, 5), homes(nodeCourse, 3, 5));
  assert.notDeepEqual(homes(nodeCourse, 3, 5), homes(nodeCourse, 3, 6));
});

test("a node of unknown course lives near the centre", () => {
  const h = homes([0, -1], 2, 1);
  assert.ok(Math.hypot(h[2], h[3]) < 0.45);
});

const dist = (pos, i, j) => Math.hypot(pos[2 * i] - pos[2 * j], pos[2 * i + 1] - pos[2 * j + 1]);

test("one weighted pair is pulled together, an unweighted one is not", () => {
  // Four nodes on two opposite homes: 0 and 2 share a tie, 1 and 3 do not.
  const home = Float32Array.from([0, 0.85, 0, 0.85, 0, -0.85, 0, -0.85]);
  const a = new Sim(home, 3);
  const b = new Sim(home, 3);
  const vis = Uint8Array.from([1, 1, 1, 1]);
  const before = dist(a.pos, 0, 2);
  for (let i = 0; i < 30; i++) {
    a.step(new Map([[pairKey(2, 0), 1]]), vis);
    b.step(new Map(), vis);
  }
  assert.ok(dist(a.pos, 0, 2) < before - 0.3, `${dist(a.pos, 0, 2)} vs ${before}`);
  assert.ok(Math.abs(dist(b.pos, 0, 2) - before) < 0.2);
  assert.ok(dist(a.pos, 1, 3) > 1.4);
});

test("speed is capped at 0.03 per substep", () => {
  const home = Float32Array.from([0, 0, 5, 0]);
  const s = new Sim(home, 1);
  const x0 = s.pos[0];
  s.step(new Map([[pairKey(0, 1), 1]]), Uint8Array.from([1, 1]), 1);
  assert.ok(Math.abs(s.pos[0] - x0) <= 0.03 + 1e-6);
});

test("two coincident nodes do not produce NaN", () => {
  const s = new Sim(Float32Array.from([0, 0, 0, 0]), 1);
  s.pos.fill(0);
  s.step(new Map([[pairKey(0, 1), 1]]), Uint8Array.from([1, 1]));
  assert.ok(Array.from(s.pos).every(Number.isFinite));
});
