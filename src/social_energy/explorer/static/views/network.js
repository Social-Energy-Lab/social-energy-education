// Network: who is close to whom in the window, drawn on a canvas with a live force layout.
// Each course has a home on a ring; ties pull people away from it, so a node in the middle is
// spending time with other courses. The home ring is a drawing choice, not a finding.
import { lowerBound, windowRange } from "../model.js";

const R = 300; // home ring radius, world units
const EXTENT = 430;
const GLOW_S = 40 * 60;

export function create(el, ctx, legendEl) {
  const { nNodes, nodeCourse, meta } = ctx;
  const nCourses = meta.courses.length;
  const canvas = document.createElement("canvas");
  el.append(canvas);
  const empty = document.createElement("div");
  empty.className = "empty";
  el.append(empty);
  const g = canvas.getContext("2d");

  const home = (c) => {
    if (c < 0) return [0, 0];
    const a = (c / Math.max(nCourses, 1)) * 2 * Math.PI - Math.PI / 2;
    return [R * Math.cos(a), R * Math.sin(a)];
  };
  const nodes = d3.range(nNodes).map((i) => {
    const [hx, hy] = home(nodeCourse[i]);
    return { i, hx, hy, x: hx + (Math.random() - 0.5) * 40, y: hy + (Math.random() - 0.5) * 40 };
  });
  let links = [];
  let linkKeys = "";
  let vis = new Uint8Array(nNodes);
  let glow = new Float32Array(nNodes);
  let zoneOf = new Int16Array(nNodes).fill(-1);
  let st = null;
  let pr = null;
  let degree = new Uint16Array(nNodes);

  const sim = d3.forceSimulation(nodes)
    .force("link", d3.forceLink([]).id((d) => d.i).distance(40))
    .force("charge", d3.forceManyBody().strength(-40).distanceMax(200))
    .force("x", d3.forceX((d) => d.hx).strength((d) => (vis[d.i] ? 0.07 : 0.15)))
    .force("y", d3.forceY((d) => d.hy).strength((d) => (vis[d.i] ? 0.07 : 0.15)))
    .force("collide", d3.forceCollide(7))
    .alphaTarget(0.06)
    .alphaDecay(0.02)
    .on("tick", draw);

  // Legend: course names with swatches; click to highlight.
  function legend() {
    legendEl.replaceChildren();
    const items = meta.courses.map((c, i) => [i, c.name, ctx.colors.course[i]]);
    if (ctx.hasUnknown) items.push([-1, "course not known", ctx.colors.unknown]);
    for (const [i, name, color] of items) {
      const item = document.createElement("span");
      item.className = "item";
      if (st && st.course !== null && st.course !== i) item.classList.add("dim");
      item.innerHTML = `<span class="swatch" style="background:${color}"></span>${name}`;
      if (i >= 0) item.addEventListener("click", () => ctx.set({ course: st.course === i ? null : i }));
      legendEl.append(item);
    }
    const glowItem = document.createElement("span");
    glowItem.className = "item";
    glowItem.innerHTML = `<span class="swatch" style="background:${ctx.colors.glow};box-shadow:0 0 6px ${ctx.colors.glow}"></span>pressed the button (last 40 min)`;
    legendEl.append(glowItem);
  }

  function transform() {
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    const s = Math.min(w, h) / (2 * EXTENT);
    return { w, h, s, ox: w / 2, oy: h / 2 };
  }

  const group = (c) => (c < 0 ? nCourses : c);
  function edgeLit(l) {
    if (!st) return true;
    const ca = nodeCourse[l.source.i];
    const cb = nodeCourse[l.target.i];
    if (st.course !== null && ca !== st.course && cb !== st.course) return false;
    if (st.cell) {
      const [x, y] = st.cell;
      const ga = group(ca);
      const gb = group(cb);
      if (!((ga === x && gb === y) || (ga === y && gb === x))) return false;
    }
    if (st.zone !== null && (zoneOf[l.source.i] !== st.zone || zoneOf[l.target.i] !== st.zone)) {
      return false;
    }
    return true;
  }
  function nodeLit(i) {
    if (!st) return true;
    if (st.course !== null && nodeCourse[i] !== st.course) return false;
    if (st.cell && !st.cell.includes(group(nodeCourse[i]))) return false;
    if (st.zone !== null && zoneOf[i] !== st.zone) return false;
    return true;
  }

  function draw() {
    const dpr = window.devicePixelRatio || 1;
    const { w, h, s, ox, oy } = transform();
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
    }
    const c = ctx.colors;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, h);
    const X = (x) => ox + x * s;
    const Y = (y) => oy + y * s;

    // Course names at their homes.
    g.font = "600 12px system-ui, sans-serif";
    g.textAlign = "center";
    g.textBaseline = "middle";
    meta.courses.forEach((course, i) => {
      const [hx, hy] = home(i);
      const half = g.measureText(course.name).width / 2;
      const lx = Math.min(w - half - 4, Math.max(half + 4, X(hx * 1.33)));
      const ly = Y(hy * 1.27);
      g.fillStyle = c.ink2;
      g.globalAlpha = st && st.course !== null && st.course !== i ? 0.35 : 1;
      g.fillText(course.name, lx, ly);
    });
    g.globalAlpha = 1;

    // Edges: same course in the course colour, across courses in ink.
    const maxBins = pr ? pr.windowBins : 24;
    for (const l of links) {
      const same = nodeCourse[l.source.i] === nodeCourse[l.target.i] && nodeCourse[l.source.i] >= 0;
      const lit = edgeLit(l);
      g.strokeStyle = same ? c.course[nodeCourse[l.source.i]] : c.ink2;
      g.globalAlpha = lit ? 0.25 + 0.6 * Math.min(1, l.bins / maxBins) : 0.05;
      g.lineWidth = 0.8 + 2.2 * Math.min(1, l.bins / maxBins);
      g.beginPath();
      g.moveTo(X(l.source.x), Y(l.source.y));
      g.lineTo(X(l.target.x), Y(l.target.y));
      g.stroke();
    }
    g.globalAlpha = 1;

    // Glows, then nodes with a surface ring.
    for (const n of nodes) {
      if (glow[n.i] <= 0) continue;
      const r = 6 + 16 * glow[n.i];
      const grad = g.createRadialGradient(X(n.x), Y(n.y), 2, X(n.x), Y(n.y), r);
      grad.addColorStop(0, c.glow);
      grad.addColorStop(1, "rgba(0,0,0,0)");
      g.globalAlpha = 0.35 + 0.6 * glow[n.i];
      g.fillStyle = grad;
      g.beginPath();
      g.arc(X(n.x), Y(n.y), r, 0, 2 * Math.PI);
      g.fill();
    }
    for (const n of nodes) {
      const course = nodeCourse[n.i];
      g.globalAlpha = (vis[n.i] ? 1 : 0.18) * (nodeLit(n.i) ? 1 : 0.2);
      g.fillStyle = course < 0 ? c.unknown : c.course[course];
      g.strokeStyle = c.surface;
      g.lineWidth = 2;
      g.beginPath();
      g.arc(X(n.x), Y(n.y), 5.5, 0, 2 * Math.PI);
      g.fill();
      g.stroke();
    }
    g.globalAlpha = 1;
  }

  function update(state, p, e, changed) {
    st = state;
    pr = p;
    const { b } = ctx;
    vis = new Uint8Array(nNodes);
    const [slo, shi] = windowRange(b.seen.bin, p.endBin, p.windowBins);
    for (let i = slo; i < shi; i++) vis[b.seen.node[i]] = 1;

    const key = e.a.map((a, i) => `${a}-${e.b[i]}-${e.bins[i]}`).join(",");
    if (key !== linkKeys) {
      linkKeys = key;
      const old = new Map(links.map((l) => [`${l.source.i}-${l.target.i}`, l]));
      links = e.a.map((a, i) => {
        const l = old.get(`${a}-${e.b[i]}`) ?? { source: a, target: e.b[i] };
        l.bins = e.bins[i];
        l.maxRssi = e.maxRssi[i];
        return l;
      });
      sim.force("link").links(links).strength((l) => 0.02 + 0.2 * Math.min(1, l.bins / p.windowBins));
      degree = new Uint16Array(nNodes);
      for (let i = 0; i < e.a.length; i++) { degree[e.a[i]]++; degree[e.b[i]]++; }
      sim.alpha(Math.max(sim.alpha(), 0.15));
    }
    sim.force("x").initialize(nodes);
    sim.force("y").initialize(nodes);

    // Glow: presses in the last 40 minutes.
    const now = state.bin * meta.bin_seconds;
    glow = new Float32Array(nNodes);
    const ps = b.presses;
    for (let i = lowerBound(ps.sec, now - GLOW_S); i < ps.sec.length && ps.sec[i] <= now; i++) {
      glow[ps.node[i]] = Math.max(glow[ps.node[i]], 1 - (now - ps.sec[i]) / GLOW_S);
    }

    // Zone of each node at the playhead (for the zone filter and tooltips).
    zoneOf = new Int16Array(nNodes).fill(-1);
    const bin = Math.floor(state.bin);
    const [rlo, rhi] = windowRange(b.rooms.bin, bin + 1, 1);
    for (let i = rlo; i < rhi; i++) zoneOf[b.rooms.node[i]] = ctx.locZone[b.rooms.loc[i]];

    empty.textContent = vis.some((v) => v)
      ? (e.a.length ? "" : "No ties in this window at these settings")
      : "No tags heard in this window";
    if (changed.has("course") || changed.has("theme") || changed.has("init")) legend();
    draw();
  }

  // Hover: a node within 10 px, else an edge within 5 px.
  canvas.addEventListener("mousemove", (ev) => {
    const rect = canvas.getBoundingClientRect();
    const { s, ox, oy } = transform();
    const mx = ev.clientX - rect.left;
    const my = ev.clientY - rect.top;
    let best = null;
    let bestD = 10;
    for (const n of nodes) {
      const d = Math.hypot(ox + n.x * s - mx, oy + n.y * s - my);
      if (d < bestD) { best = n; bestD = d; }
    }
    if (best) {
      const i = best.i;
      const [dlo, dhi] = ctx.dayRange(ctx.dayOfBin[Math.floor(st.bin)]);
      let today = 0;
      const ps = ctx.b.presses;
      const lo = lowerBound(ps.sec, dlo * meta.bin_seconds);
      for (let k = lo; k < ps.sec.length && ps.sec[k] < dhi * meta.bin_seconds; k++) {
        if (ps.node[k] === i) today++;
      }
      const zone = zoneOf[i] >= 0 ? meta.zones[zoneOf[i]] : "not placed";
      ctx.tip.show(
        `<b>${ctx.courseName(nodeCourse[i])}</b><br>` +
        `${vis[i] ? `${degree[i]} close ties in the window` : "<span class='muted'>tag not heard in the window</span>"}<br>` +
        `place now: ${zone}<br>button presses today: ${today}`,
        ev.clientX, ev.clientY,
      );
      return;
    }
    for (const l of links) {
      const ax = ox + l.source.x * s, ay = oy + l.source.y * s;
      const bx = ox + l.target.x * s, by = oy + l.target.y * s;
      const t = Math.max(0, Math.min(1, ((mx - ax) * (bx - ax) + (my - ay) * (by - ay)) /
        ((bx - ax) ** 2 + (by - ay) ** 2 || 1)));
      if (Math.hypot(ax + t * (bx - ax) - mx, ay + t * (by - ay) - my) < 5) {
        ctx.tip.show(
          `<b>${ctx.courseName(nodeCourse[l.source.i])}</b> – <b>${ctx.courseName(nodeCourse[l.target.i])}</b><br>` +
          `${l.bins * meta.bin_seconds / 60} min at close range in the window<br>` +
          `strongest signal ${l.maxRssi} dBm`,
          ev.clientX, ev.clientY,
        );
        return;
      }
    }
    ctx.tip.hide();
  });
  canvas.addEventListener("mouseleave", () => ctx.tip.hide());

  return { update };
}
