// The hero's layout: each course has a home on a ring, and a small force simulation that is
// stepped, not solved, so the dots move continuously. A port of camp_breathes.Simulation
// (studies/dsa-2026/analyses/camp_breathes.py), with the same constants. No DOM here.

/** A seeded PRNG (mulberry32) with a normal draw (Box-Muller). */
export function rng(seed) {
  let s = seed >>> 0 || 0x9e3779b9;
  const uniform = () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  const normal = (sd = 1) => {
    const u = 1 - uniform();
    return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * uniform()) * sd;
  };
  return { uniform, normal };
}

/** The key of an unordered node pair, as used in the weights map. */
export const pairKey = (a, b) => (a < b ? `${a},${b}` : `${b},${a}`);

const RING = 0.85;
const JITTER = 0.1;

/** Home (x, y) per node: course c at angle π/2 + 2πc/nCourses on the ring; unknown at centre. */
export function homes(nodeCourse, nCourses, seed) {
  const r = rng(seed);
  const n = nodeCourse.length;
  const out = new Float32Array(2 * n);
  for (let i = 0; i < n; i++) {
    const c = nodeCourse[i];
    let x = 0;
    let y = 0;
    if (c >= 0 && nCourses > 0) {
      const angle = Math.PI / 2 + (2 * Math.PI * c) / nCourses;
      x = RING * Math.cos(angle);
      y = RING * Math.sin(angle);
    }
    out[2 * i] = x + r.normal(JITTER);
    out[2 * i + 1] = y + r.normal(JITTER);
  }
  return out;
}

const REST = 0.12;
const SPRING = 0.6;
const PUSH = 0.0012;
const PUSH_MIN_DIST = 0.04;
const PUSH_UNSEEN = 0.1;
const GRAVITY_SEEN = 0.03;
const GRAVITY_UNSEEN = 0.08;
const MAX_SPEED = 0.03;

export class Sim {
  constructor(home, seed) {
    const r = rng(seed);
    this.home = home;
    this.n = home.length / 2;
    this.pos = Float32Array.from(home, (v) => v + r.normal(0.05));
    this.vel = new Float32Array(home.length);
    this.force = new Float64Array(home.length);
  }

  /** Advance by `substeps`; `weights` maps pairKey(a, b) to a tie weight in (0, 1]. */
  step(weights, visible, substeps = 4) {
    const { n, pos, vel, home, force } = this;
    // Parse the springs once per call, not once per substep.
    const springs = [];
    for (const [key, w] of weights) {
      const comma = key.indexOf(",");
      springs.push(+key.slice(0, comma), +key.slice(comma + 1), w);
    }
    for (let s = 0; s < substeps; s++) {
      for (let i = 0; i < n; i++) {
        const g = visible[i] ? GRAVITY_SEEN : GRAVITY_UNSEEN;
        force[2 * i] = g * (home[2 * i] - pos[2 * i]);
        force[2 * i + 1] = g * (home[2 * i + 1] - pos[2 * i + 1]);
      }
      // Repulsion between every pair, weaker when either one is unseen.
      for (let i = 0; i < n; i++) {
        const xi = pos[2 * i];
        const yi = pos[2 * i + 1];
        for (let j = i + 1; j < n; j++) {
          const dx = pos[2 * j] - xi;
          const dy = pos[2 * j + 1] - yi;
          const d = Math.max(Math.hypot(dx, dy), 1e-6);
          const both = visible[i] && visible[j] ? 1 : PUSH_UNSEEN;
          const m = Math.max(d, PUSH_MIN_DIST);
          const f = (both * PUSH) / (m * m) / d; // per unit of (dx, dy)
          force[2 * i] -= f * dx;
          force[2 * i + 1] -= f * dy;
          force[2 * j] += f * dx;
          force[2 * j + 1] += f * dy;
        }
      }
      // Springs along ties, towards the rest length.
      for (let k = 0; k < springs.length; k += 3) {
        const i = springs[k];
        const j = springs[k + 1];
        const dx = pos[2 * j] - pos[2 * i];
        const dy = pos[2 * j + 1] - pos[2 * i + 1];
        const d = Math.max(Math.hypot(dx, dy), 1e-6);
        const f = (springs[k + 2] * SPRING * (d - REST)) / d;
        force[2 * i] += f * dx;
        force[2 * i + 1] += f * dy;
        force[2 * j] -= f * dx;
        force[2 * j + 1] -= f * dy;
      }
      for (let i = 0; i < n; i++) {
        let vx = (vel[2 * i] + 0.25 * force[2 * i]) * 0.7;
        let vy = (vel[2 * i + 1] + 0.25 * force[2 * i + 1]) * 0.7;
        const speed = Math.hypot(vx, vy);
        if (speed > MAX_SPEED) {
          vx *= MAX_SPEED / speed;
          vy *= MAX_SPEED / speed;
        }
        vel[2 * i] = vx;
        vel[2 * i + 1] = vy;
        pos[2 * i] += vx;
        pos[2 * i + 1] += vy;
      }
    }
  }

  /** Mean speed in the last substep: small means the layout has settled. */
  energy() {
    let s = 0;
    for (let i = 0; i < this.vel.length; i += 2) s += Math.hypot(this.vel[i], this.vel[i + 1]);
    return this.n ? s / this.n : 0;
  }
}
