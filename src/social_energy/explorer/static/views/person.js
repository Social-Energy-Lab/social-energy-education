// The person view: one person, one moment, and the people around them.
//
// Picker → membrane profile (survey composites, scales, items; interview codes) → timeline across
// the academy (programme, place, company, presses, EDA, heart rate) → a moment (a press, an EDA
// moment or any clicked time) with who was close, whether they pressed too, their profiles and
// the EDA around it → special moments per day against the camp. Clicking a close person opens
// their view at the same moment, with a breadcrumb back.
import * as pm from "../person-model.js";

const CASCADE_S = 5 * 60; // "pressed too": within 5 minutes, the cascade window of the analyses
const AROUND_MIN = 15; // EDA shown this many minutes either side of a moment
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const fmt = (x, d = 2) => (x === null || x === undefined ? "–" : Number(x).toFixed(d));
const signed = (x, d = 2) => (x === null || x === undefined ? "–" : `${x > 0 ? "+" : ""}${Number(x).toFixed(d)}`);

export function create(root, ctx) {
  const { meta, b, nNodes, nBins, person: P } = ctx;
  const binS = meta.bin_seconds;
  const binsPerMin = 60 / binS;
  const edaIx = pm.edaIndex(b.eda, nNodes);
  const rule = P.moment_rule;
  const dayOfMin = (m) => b.bins.day[Math.min(nBins - 1, Math.floor(m * binsPerMin))];
  const nDays = meta.days.length;
  const people = P.people;
  const wave = P.waves[0];
  const scaleByKey = Object.fromEntries(P.scales.map((s) => [s.key, s]));
  const $ = (sel) => root.querySelector(sel);

  const st = {
    node: null,
    moment: null, // {sec, kind: "press" | "eda" | "time"}
    day: -1, // -1: whole academy
    which: "scr",
    crumbs: [], // [{node, moment}]
    course: "",
    type: "",
    q: "",
    open: new Set(), // expanded scales
  };
  const momentsCache = new Map();
  const moments = (node) => {
    const key = `${node}-${st.which}`;
    if (!momentsCache.has(key)) {
      momentsCache.set(key, pm.edaMoments(b.eda, edaIx.lo[node], edaIx.hi[node], dayOfMin, rule, st.which));
    }
    return momentsCache.get(key);
  };
  let closeRssi = null;
  let rendered = false;

  const name = ctx.personName;
  const typeOf = (i) => pm.typeLabel(people[i].type) ?? "no survey type";
  const when = (sec) => {
    const bin = Math.min(nBins - 1, Math.floor(sec / binS));
    const t = new Date(Date.parse(meta.t0) + sec * 1000);
    const clock = new Intl.DateTimeFormat("en-GB", { timeZone: meta.timezone, hour: "2-digit", minute: "2-digit" }).format(t);
    return `${ctx.dayLabel(bin)} ${clock}`;
  };

  // ---- picker -------------------------------------------------------------------------------------
  function picker() {
    const el = $("#person-picker");
    const courseOpts = meta.courses.map((c, i) => `<option value="${i}">${esc(c.name)}</option>`).join("");
    const typeOpts = [["high-high", "high trust · high lust"], ["high-low", "high trust · low lust"],
      ["low-high", "low trust · high lust"], ["low-low", "low trust · low lust"], ["none", "no survey type"]]
      .map(([k, l]) => `<option value="${k}">${l}</option>`).join("");
    el.innerHTML = `
      <div class="picker-filters">
        <label>study ID <input type="search" data-q placeholder="find" size="10"></label>
        <label>course <select data-f="course"><option value="">all</option>${courseOpts}</select></label>
        <label>membrane type <select data-f="type"><option value="">all</option>${typeOpts}</select></label>
      </div>
      <div class="picker-list" role="listbox" aria-label="People"></div>`;
    for (const sel of el.querySelectorAll("select")) {
      sel.value = st[sel.dataset.f];
      sel.addEventListener("change", () => { st[sel.dataset.f] = sel.value; pickerList(); });
    }
    const q = el.querySelector("[data-q]");
    q.value = st.q;
    q.addEventListener("input", () => { st.q = q.value.trim().toLowerCase(); pickerList(); });
    pickerList();
  }

  function pickerList() {
    const list = $(".picker-list");
    const rows = [];
    for (let i = 0; i < nNodes; i++) {
      if (st.course !== "" && ctx.nodeCourse[i] !== Number(st.course)) continue;
      if (st.type !== "" && pm.typeKey(people[i].type) !== st.type) continue;
      if (st.q && !name(i).toLowerCase().includes(st.q)) continue;
      const p = people[i];
      const n = pm.pressesOf(b, i).length;
      const mods = [p.survey ? "survey" : null, p.membrane ? "interview" : null,
        p.eda && edaIx.hi[i] > edaIx.lo[i] ? "EDA" : null].filter(Boolean).join(" · ");
      rows.push(`<button type="button" class="pick${i === st.node ? " on" : ""}" data-node="${i}" role="option" aria-selected="${i === st.node}">
        <span class="swatch" style="background:${ctx.nodeCourse[i] < 0 ? ctx.colors.unknown : ctx.colors.course[ctx.nodeCourse[i] % 6]}"></span>
        <b>${name(i)}</b><span>${esc(ctx.courseName(ctx.nodeCourse[i]))}</span>
        <span>${typeOf(i)}</span><span>${n} presses</span><span class="muted">${mods || "beacons only"}</span>
      </button>`);
    }
    list.innerHTML = rows.join("") || "<p class='muted'>Nobody matches these filters.</p>";
    for (const btn of list.querySelectorAll(".pick")) {
      btn.addEventListener("click", () => open(Number(btn.dataset.node), null, true));
    }
  }

  // ---- navigation ---------------------------------------------------------------------------------
  function open(node, moment, fresh) {
    if (fresh) st.crumbs = [];
    st.node = node;
    st.moment = moment;
    if (moment) st.day = dayOfMin(Math.floor(moment.sec / 60));
    render();
  }

  function jumpTo(other) {
    st.crumbs.push({ node: st.node, moment: st.moment, day: st.day });
    open(other, st.moment ? { sec: st.moment.sec, kind: "time" } : null, false);
  }

  function crumbs() {
    const el = $("#person-crumbs");
    if (!st.crumbs.length) { el.innerHTML = ""; return; }
    const parts = st.crumbs.map((c, k) => `<button type="button" class="crumb" data-k="${k}">${name(c.node)}${c.moment ? ` @ ${when(c.moment.sec)}` : ""}</button>`);
    el.innerHTML = `${parts.join(" › ")} › <b>${name(st.node)}</b>`;
    for (const btn of el.querySelectorAll(".crumb")) {
      btn.addEventListener("click", () => {
        const k = Number(btn.dataset.k);
        const c = st.crumbs[k];
        st.crumbs = st.crumbs.slice(0, k);
        st.day = c.day;
        open(c.node, c.moment, false);
      });
    }
  }

  // ---- profile ------------------------------------------------------------------------------------
  function header() {
    const i = st.node;
    const p = people[i];
    const bits = [ctx.courseName(ctx.nodeCourse[i]), p.age !== null ? `${p.age} years` : null,
      p.gender ? `gender ${p.gender}` : null, typeOf(i)].filter(Boolean);
    $("#person-head").innerHTML = `
      <button type="button" data-step="-1" aria-label="Previous person">‹</button>
      <h2 class="person-name">${name(i)}</h2>
      <button type="button" data-step="1" aria-label="Next person">›</button>
      <span class="person-bits">${bits.map(esc).join(" · ")}</span>`;
    for (const btn of $("#person-head").querySelectorAll("button")) {
      btn.addEventListener("click", () => open((i + Number(btn.dataset.step) + nNodes) % nNodes, null, true));
    }
  }

  function quadrant(el) {
    const pts = [];
    people.forEach((p, i) => {
      const w = p.survey?.[wave];
      if (w?.trust && w?.lust && w.trust[1] !== null && w.lust[1] !== null) pts.push({ i, x: w.trust[1], y: w.lust[1] });
    });
    const c = ctx.colors;
    const size = 220;
    const svg = d3.select(el).append("svg").attr("width", size).attr("height", size).attr("class", "quadrant");
    const ext = Math.max(2.5, d3.max(pts, (d) => Math.max(Math.abs(d.x), Math.abs(d.y))) || 0);
    const x = d3.scaleLinear().domain([-ext, ext]).range([24, size - 8]);
    const y = d3.scaleLinear().domain([-ext, ext]).range([size - 24, 8]);
    const mx = d3.median(pts, (d) => d.x) ?? 0;
    const my = d3.median(pts, (d) => d.y) ?? 0;
    svg.append("line").attr("x1", x(mx)).attr("x2", x(mx)).attr("y1", 8).attr("y2", size - 24).attr("stroke", c.rule);
    svg.append("line").attr("y1", y(my)).attr("y2", y(my)).attr("x1", 24).attr("x2", size - 8).attr("stroke", c.rule);
    svg.append("text").attr("x", size - 8).attr("y", size - 10).attr("text-anchor", "end").text("trust in life (z) →");
    svg.append("text").attr("transform", `translate(12,${8}) rotate(90)`).text("lust for life (z) →");
    svg.append("g").selectAll("circle").data(pts).join("circle")
      .attr("cx", (d) => x(d.x)).attr("cy", (d) => y(d.y))
      .attr("r", (d) => (d.i === st.node ? 6 : 3))
      .attr("fill", (d) => (d.i === st.node ? c.accent : c.ink3))
      .attr("opacity", (d) => (d.i === st.node ? 1 : 0.5)).style("cursor", "pointer")
      .on("click", (_, d) => open(d.i, null, true))
      .on("mousemove", (ev, d) => ctx.tip.show(`<b>${name(d.i)}</b><br>trust ${signed(d.x)} · lust ${signed(d.y)} (z)<br><span class="muted">click to open</span>`, ev.clientX, ev.clientY))
      .on("mouseleave", () => ctx.tip.hide());
    svg.selectAll("circle").filter((d) => d.i === st.node).raise();
    if (!pts.some((d) => d.i === st.node)) {
      svg.append("text").attr("x", size / 2).attr("y", size / 2).attr("text-anchor", "middle").text("no composites for this person");
    }
  }

  function scaleRows(block) {
    const sv = people[st.node].survey;
    const waves = P.waves.filter((w) => sv?.[w]);
    const rows = P.scales.filter((s) => s.block === block).map((s) => {
      const vals = waves.map((w) => sv[w].scales?.[s.key]).map((v) => v ?? [null, null]);
      if (vals.every((v) => v[0] === null) && !waves.some((w) => sv[w].items?.[s.key])) return "";
      const dots = vals.map((v, k) => (v[1] === null ? "" :
        `<span class="zdot w${k}" style="left:${Math.max(0, Math.min(100, (v[1] + 3) / 6 * 100))}%" title="${esc(waves[k])}: z ${signed(v[1])}"></span>`)).join("");
      const open = st.open.has(s.key);
      const items = open ? itemTable(s, waves) : "";
      return `<div class="scale${s.core ? " core" : ""}${s.kind === "gradient" ? " gradient" : ""}">
        <button type="button" class="scale-row" data-key="${esc(s.key)}" aria-expanded="${open}">
          <span class="scale-label">${esc(s.label)}${s.core ? " ●" : ""}${s.kind === "gradient" ? " (gradient)" : ""}</span>
          <span class="zaxis">${dots}</span>
          <span class="scale-val">${vals.map((v) => `${fmt(v[0])} <span class="muted">(${signed(v[1], 1)})</span>`).join(" / ")}</span>
        </button>${items}</div>`;
    });
    return rows.join("");
  }

  function itemTable(s, waves) {
    const sv = people[st.node].survey;
    const means = P.item_means?.[wave]?.[s.key] ?? [];
    const head = `<tr><th>item</th>${waves.map((w) => `<th>${esc(w)}</th>`).join("")}<th>camp mean</th></tr>`;
    const body = s.items.map((code, k) => `<tr><td>${esc(code)}</td>${waves.map((w) =>
      `<td>${fmt(sv[w].items?.[s.key]?.[k], 0)}</td>`).join("")}<td>${fmt(means[k], 2)}</td></tr>`).join("");
    return `<table class="items"><caption>range ${s.range[0]}–${s.range[1]}, recoded (reverse-keyed items turned)</caption>${head}${body}</table>`;
  }

  function profile() {
    const el = $("#person-profile");
    el.innerHTML = "";
    const p = people[st.node];
    if (!p.survey) {
      el.innerHTML = "<p class='muted'>No survey for this person (no consent, or no linked submission).</p>";
      return;
    }
    const top = document.createElement("div");
    top.className = "profile-top";
    el.append(top);
    const q = document.createElement("div");
    top.append(q);
    quadrant(q);
    const w = p.survey[wave];
    const comp = document.createElement("div");
    comp.className = "composites";
    comp.innerHTML = `
      <div class="big"><span>trust in life</span><b>${signed(w?.trust?.[1])}</b><span class="muted">z vs camp · composite ${fmt(w?.trust?.[0])}</span></div>
      <div class="big"><span>lust for life</span><b>${signed(w?.lust?.[1])}</b><span class="muted">z vs camp · composite ${fmt(w?.lust?.[0])}</span></div>
      <p class="muted">${esc(P.notes?.waves ?? "")}</p>`;
    top.append(comp);
    const scales = document.createElement("div");
    scales.className = "scales";
    scales.innerHTML = `
      <div class="zhead"><span></span><span class="zaxis-labels"><span>−3</span><span>0</span><span>+3</span></span><span>mean (z)</span></div>
      <h3>Trust in life</h3>${scaleRows("trust")}
      <h3>Lust for life</h3>${scaleRows("lust")}`;
    el.append(scales);
    for (const btn of scales.querySelectorAll(".scale-row")) {
      btn.addEventListener("click", () => {
        const k = btn.dataset.key;
        if (st.open.has(k)) st.open.delete(k); else st.open.add(k);
        profile();
      });
    }
  }

  function membrane() {
    const el = $("#person-membrane");
    const p = people[st.node];
    const m = p.membrane;
    if (!m) {
      el.innerHTML = "<p class='muted'>No interview codes for this person (no consent, or no coded interview).</p>";
      return;
    }
    const state = (k, label) => {
      const s = m[k];
      if (!s) return "";
      const flags = [s.confidence ? `${s.confidence} confidence` : null, s.led ? "led" : null,
        s.varies ? "varies" : null, s.reviewed === true ? "reviewed" : s.reviewed === "unsure" ? "review unsure" : null]
        .filter(Boolean).join(", ");
      return `<tr><th>${label}</th><td><b>${s.value ?? "na"}</b></td><td class="muted">${flags}</td></tr>`;
    };
    const eps = (m.episodes ?? []).map((e) => `<li>${esc(e.direction ?? "?")} · ${esc(e.category)}${e.day ? ` · ${esc(e.day)}` : " · not placed"}</li>`).join("");
    el.innerHTML = `
      <table class="codes">
        ${state("M_everyday", "everyday life")}
        ${state("M_arrival", "on arrival")}
        ${state("M_now", "at the interview (strict)")}
        ${state("M_now_lenient", "at the interview (lenient)")}
        <tr class="primary"><th>change over the academy<br><span class="muted">D_academy_lenient, primary</span></th><td><b>${signed(m.D_academy_lenient, 0)}</b></td><td class="muted">strict ${signed(m.D_academy, 0)} · signed amount ${signed(m.change_signed, 0)}</td></tr>
        <tr><th>academy vs everyday</th><td><b>${signed(m.D_vs_everyday, 0)}</b></td><td></td></tr>
        <tr><th>own account</th><td><b>${esc(m.direction?.value ?? "na")}</b></td><td class="muted">${esc(m.direction?.confidence ?? "")}</td></tr>
        <tr><th>selective</th><td>${m.selective ? "yes" : "no"}</td><td class="muted">${m.primed ? "primed by the lecture" : m.known_elsewhere ? "metaphor known elsewhere" : ""}</td></tr>
        <tr><th>openers</th><td colspan="2">${(m.openers ?? []).map(esc).join(", ") || "–"}</td></tr>
        <tr><th>closers</th><td colspan="2">${(m.closers ?? []).map(esc).join(", ") || "–"}</td></tr>
      </table>
      ${eps ? `<p class="muted">Episodes</p><ul class="episodes">${eps}</ul>` : ""}
      <p class="muted">Interview: ${p.interview_sec !== null ? when(p.interview_sec) : "time not known"}. Scale 1 closed – 5 open, within this person's own range. ${esc(P.notes?.membrane ?? "")} Codes only: no transcript text is in the bundle.</p>`;
  }

  // ---- timeline -----------------------------------------------------------------------------------
  function range() {
    if (st.day < 0) return [0, nBins];
    return ctx.dayRange(st.day);
  }

  function timeline() {
    const el = $("#person-timeline");
    el.innerHTML = "";
    const i = st.node;
    const c = ctx.colors;
    const [from, to] = range();
    const controls = document.createElement("div");
    controls.className = "tl-controls";
    controls.innerHTML = `<label>show <select data-c="day"><option value="-1">whole academy</option>${meta.days.map((d) => `<option value="${d.index}">${esc(d.label)}</option>`).join("")}</select></label>
      <label title="Which SCR rule the rate and the EDA moments use">SCR rule <select data-c="which"><option value="scr">main (all detections)</option><option value="scr_strict">amplitude ≥ 0.2 µS</option></select></label>`;
    el.append(controls);
    controls.querySelector("[data-c=day]").value = String(st.day);
    controls.querySelector("[data-c=which]").value = st.which;
    controls.querySelector("[data-c=day]").addEventListener("change", (e) => { st.day = Number(e.target.value); timeline(); });
    controls.querySelector("[data-c=which]").addEventListener("change", (e) => { st.which = e.target.value; render(); });

    const width = el.clientWidth || 900;
    const rows = [["programme", 34], ["place", 16], ["close others", 40], ["moments", 26], ["SCR / min", 64], ["heart rate", 54]];
    const left = 92;
    const rowGap = 8;
    const height = rows.reduce((s, r) => s + r[1] + rowGap, 0) + 24;
    const svg = d3.select(el).append("svg").attr("width", "100%").attr("height", height);
    const x = d3.scaleLinear().domain([from, to]).range([left, width - 8]);
    const xm = (min) => x(min * binsPerMin);
    const tops = [];
    let yy = 4;
    for (const [label, h] of rows) {
      tops.push(yy);
      svg.append("text").attr("x", 4).attr("y", yy + Math.min(h, 24) / 2 + 4).text(label);
      yy += h + rowGap;
    }
    const axisY = yy;

    // Shading: day notes / coverage spans from the study config.
    for (const s of meta.shade) {
      if (s.end_bin <= from || s.start_bin >= to) continue;
      svg.append("rect").attr("x", x(Math.max(from, s.start_bin))).attr("width", x(Math.min(to, s.end_bin)) - x(Math.max(from, s.start_bin)))
        .attr("y", 0).attr("height", axisY).attr("fill", c.shade);
    }

    const rooms = pm.roomSeries(b, i, nBins);
    const seen = pm.seenSeries(b, i, nBins);
    // 1. Programme items that apply to the person.
    const runs = pm.eventRuns(P.events, rooms, from, to);
    const lanes = [];
    const g1 = svg.append("g");
    for (const [k, a, z] of runs) {
      let lane = lanes.findIndex((end) => end <= a);
      if (lane < 0) { lane = lanes.length; lanes.push(0); }
      lanes[lane] = z;
      if (lane > 2) continue;
      const e = P.events[k];
      g1.append("rect").attr("x", x(a)).attr("width", Math.max(1, x(z) - x(a))).attr("y", tops[0] + lane * 11).attr("height", 10)
        .attr("rx", 2).attr("fill", e.all_camp ? c.zoneHi : c.zoneLo).attr("stroke", e.end_known ? "none" : c.ink3).attr("stroke-dasharray", "2 2")
        .on("mousemove", (ev) => ctx.tip.show(`<b>${esc(e.label)}</b><br>${esc(e.kind)}${e.all_camp ? " · all camp" : " · in their room"}<br>${ctx.clockLabel(e.start_bin)}–${ctx.clockLabel(e.end_bin)}${e.end_known ? "" : " (end filled with the kind's median)"}`, ev.clientX, ev.clientY))
        .on("mouseleave", () => ctx.tip.hide());
    }
    // 2. Place: zone of the room per bin; heard but not placed in grey; not heard blank.
    const g2 = svg.append("g");
    const zoneKey = (k) => (rooms[k] >= 0 ? ctx.locZone[rooms[k]] : seen[k] ? -1 : -2);
    for (const [a, z, key] of pm.runs(from, to, zoneKey)) {
      if (key === -2) continue;
      g2.append("rect").attr("x", x(a)).attr("width", Math.max(0.6, x(z) - x(a))).attr("y", tops[1]).attr("height", 14)
        .attr("fill", key < 0 ? c.rule : c.course[key % 6]).attr("opacity", key < 0 ? 1 : 0.75)
        .on("mousemove", (ev) => ctx.tip.show(`${key < 0 ? "tag heard, not placed in a room" : `zone: ${esc(meta.zones[key])}`}<br>${ctx.clockLabel(a)}–${ctx.clockLabel(z)}`, ev.clientX, ev.clientY))
        .on("mouseleave", () => ctx.tip.hide());
    }
    // 3. Close others.
    const close = pm.closeSeries(b, i, closeRssi, nBins);
    let maxClose = 1;
    for (let k = from; k < to; k++) maxClose = Math.max(maxClose, close[k]);
    const yc = d3.scaleLinear().domain([0, maxClose]).range([tops[2] + 40, tops[2]]);
    svg.append("path").attr("fill", c.accent).attr("opacity", 0.35)
      .attr("d", d3.area().x((k) => x(k)).y0(yc(0)).y1((k) => yc(close[k])).curve(d3.curveStepAfter)(d3.range(from, to)));
    svg.append("g").attr("class", "axis").attr("transform", `translate(${left},0)`).call(d3.axisLeft(yc).ticks(2).tickSize(3));
    // 4. Moments: presses (1st person), EDA moments (3rd person, exploratory), the interview.
    const presses = pm.pressesOf(b, i);
    const edaM = moments(i);
    const g4 = svg.append("g");
    const inView = (sec) => sec >= from * binS && sec < to * binS;
    for (const s of presses.filter(inView)) {
      g4.append("rect").attr("x", x(s / binS) - 1.5).attr("width", 3).attr("y", tops[3]).attr("height", 12).attr("fill", c.accent)
        .style("cursor", "pointer").on("click", () => select({ sec: s, kind: "press" }))
        .on("mousemove", (ev) => ctx.tip.show(`press at ${when(s)}<br><span class="muted">click for this moment</span>`, ev.clientX, ev.clientY))
        .on("mouseleave", () => ctx.tip.hide());
    }
    for (const m of edaM.filter((m) => inView(m.min * 60))) {
      g4.append("circle").attr("cx", xm(m.min)).attr("cy", tops[3] + 19).attr("r", 3.5).attr("fill", c.glow).attr("stroke", c.ink3).attr("stroke-width", 0.5)
        .style("cursor", "pointer").on("click", () => select({ sec: m.min * 60, kind: "eda" }))
        .on("mousemove", (ev) => ctx.tip.show(`EDA moment at ${when(m.min * 60)} (exploratory)<br>SCR ${fmt(m.rate, 1)}/min, z ${fmt(m.z, 1)} vs the person-day${m.uncertain ? "<br>clock uncertain" : ""}<br><span class="muted">click for this moment</span>`, ev.clientX, ev.clientY))
        .on("mouseleave", () => ctx.tip.hide());
    }
    const iv = people[i].interview_sec;
    if (iv !== null && inView(iv)) {
      g4.append("path").attr("d", d3.symbol(d3.symbolDiamond, 60)()).attr("transform", `translate(${x(iv / binS)},${tops[3] + 6})`).attr("fill", c.ink1)
        .on("mousemove", (ev) => ctx.tip.show(`interview at ${when(iv)}`, ev.clientX, ev.clientY)).on("mouseleave", () => ctx.tip.hide());
    }
    // 5-6. EDA and heart rate: per minute in a day, mean per 5-minute bin over the academy.
    edaRows(svg, i, from, to, x, tops[4], 64, tops[5], 54, left);

    svg.append("g").attr("class", "axis").attr("transform", `translate(0,${axisY})`).call(
      st.day < 0
        ? d3.axisBottom(x).tickValues(meta.days.map((d) => d.start_bin)).tickFormat((k) => ctx.dayLabel(k).slice(0, 6)).tickSize(3)
        : d3.axisBottom(x).ticks(12).tickFormat((k) => ctx.clockLabel(k)).tickSize(3),
    );
    if (st.moment && inView(st.moment.sec)) {
      const mx = x(st.moment.sec / binS);
      svg.append("line").attr("class", "cursor").attr("x1", mx).attr("x2", mx).attr("y1", 0).attr("y2", axisY);
    }
    // Click anywhere else: inspect that time.
    svg.insert("rect", ":first-child").attr("x", left).attr("y", 0).attr("width", width - left - 8).attr("height", axisY)
      .attr("fill", "transparent").style("cursor", "crosshair")
      .on("click", (ev) => {
        const k = Math.max(from, Math.min(to - 1, Math.floor(x.invert(d3.pointer(ev)[0]))));
        select({ sec: k * binS, kind: "time" });
      });
  }

  function edaRows(svg, i, from, to, x, top1, h1, top2, h2, left) {
    const c = ctx.colors;
    const lo = edaIx.lo[i];
    const hi = edaIx.hi[i];
    if (!people[i].eda || hi <= lo) {
      svg.append("text").attr("x", left + 4).attr("y", top1 + 20).attr("class", "muted")
        .text(people[i].eda ? "no worn EDA minutes" : "no EDA consent for this person");
      return;
    }
    const e = b.eda;
    const fromMin = (from * binS) / 60;
    const toMin = (to * binS) / 60;
    const perBin = st.day < 0;
    const step = perBin ? binS / 60 : 1; // minutes per drawn point
    const n = Math.ceil((toMin - fromMin) / step);
    const scr = new Float64Array(n).fill(NaN);
    const hr = new Float64Array(n).fill(NaN);
    const worn = new Uint8Array(n);
    const unsure = new Uint8Array(n);
    const ns = new Uint16Array(n);
    const nh = new Uint16Array(n);
    for (let r = lo; r < hi; r++) {
      const m = e.min[r];
      if (m < fromMin || m >= toMin) continue;
      const k = Math.floor((m - fromMin) / step);
      worn[k] = 1;
      if (e.flags[r] & pm.CLOCK_UNCERTAIN) unsure[k] = 1;
      const v = pm.rate(e, r, st.which);
      if (v !== null) { scr[k] = (ns[k] ? scr[k] : 0) + v; ns[k]++; }
      if (e.flags[r] & pm.HR_OK && e.hr[r]) { hr[k] = (nh[k] ? hr[k] : 0) + e.hr[r]; nh[k]++; }
    }
    for (let k = 0; k < n; k++) { if (ns[k]) scr[k] /= ns[k]; if (nh[k]) hr[k] /= nh[k]; }
    const xs = (k) => x((fromMin + k * step) / (binS / 60));
    const w = Math.max(0.6, xs(1) - xs(0));
    // Not worn: a pale band; clock uncertain: shaded.
    for (const [a, z, key] of pm.runs(0, n, (k) => (!worn[k] ? 1 : unsure[k] ? 2 : 0))) {
      if (!key) continue;
      for (const [t, h] of [[top1, h1], [top2, h2]]) {
        svg.append("rect").attr("x", xs(a)).attr("width", Math.max(0.6, xs(z) - xs(a))).attr("y", t).attr("height", h)
          .attr("fill", key === 1 ? c.rule : c.glow).attr("opacity", key === 1 ? 0.45 : 0.18)
          .on("mousemove", (ev) => ctx.tip.show(key === 1 ? "EDA not worn" : "device clock uncertain: times may be off", ev.clientX, ev.clientY))
          .on("mouseleave", () => ctx.tip.hide());
      }
    }
    const ext = (arr) => { let a = Infinity, z = -Infinity; for (const v of arr) if (!Number.isNaN(v)) { a = Math.min(a, v); z = Math.max(z, v); } return a === Infinity ? [0, 1] : [a, z]; };
    const y1 = d3.scaleLinear().domain([0, Math.max(1, ext(scr)[1])]).nice().range([top1 + h1, top1 + 2]);
    const [ha, hz] = ext(hr);
    const y2 = d3.scaleLinear().domain([Math.min(ha, 60), Math.max(hz, 100)]).nice().range([top2 + h2, top2 + 2]);
    svg.append("g").attr("class", "axis").attr("transform", `translate(${left},0)`).call(d3.axisLeft(y1).ticks(2).tickSize(3));
    svg.append("g").attr("class", "axis").attr("transform", `translate(${left},0)`).call(d3.axisLeft(y2).ticks(2).tickSize(3));
    const line = (arr, y) => d3.line().defined((k) => !Number.isNaN(arr[k])).x((k) => xs(k) + w / 2).y((k) => y(arr[k]))(d3.range(n));
    svg.append("path").attr("fill", "none").attr("stroke", c.accent).attr("stroke-width", 1).attr("d", line(scr, y1));
    svg.append("path").attr("fill", "none").attr("stroke", c.course[1]).attr("stroke-width", 1).attr("d", line(hr, y2));
  }

  // ---- moment -------------------------------------------------------------------------------------
  function select(moment) {
    st.moment = moment;
    timeline();
    momentPanel();
  }

  function momentPanel() {
    const el = $("#person-moment");
    const i = st.node;
    if (!st.moment) {
      el.innerHTML = "<p class='muted'>Click a press (blue tick), an EDA moment (yellow dot) or any time on the timeline.</p>";
      return;
    }
    const { sec, kind } = st.moment;
    const bin = Math.min(nBins - 1, Math.floor(sec / binS));
    const rooms = pm.roomSeries(b, i, nBins);
    const loc = rooms[bin];
    const evs = pm.eventsAt(P.events, bin, loc);
    const place = loc >= 0 ? `${esc(meta.locations[loc].label)} (${esc(meta.zones[meta.locations[loc].zone])})` : "not placed in a room";
    const close = pm.closeAt(b, i, bin, closeRssi);
    const title = kind === "press" ? "Press (first-person special moment)"
      : kind === "eda" ? "EDA moment (third-person, exploratory)" : "A moment on the timeline";
    const others = close.map(({ node: o, rssi }) => {
      const p = people[o];
      const gap = pm.nearestPress(b, o, sec, CASCADE_S);
      const w = p.survey?.[wave];
      return `<tr>
        <td><button type="button" class="jump" data-node="${o}">${name(o)}</button></td>
        <td>${esc(ctx.courseName(ctx.nodeCourse[o]))}</td>
        <td>${rssi} dBm</td>
        <td>${gap === null ? "–" : `pressed ${gap === 0 ? "at the same time" : `${Math.abs(Math.round(gap / 60 * 10) / 10)} min ${gap < 0 ? "before" : "after"}`}`}</td>
        <td>${pm.typeLabel(p.type) ?? "–"}</td>
        <td>${signed(w?.trust?.[1], 1)} / ${signed(w?.lust?.[1], 1)}</td>
        <td>${p.membrane ? signed(p.membrane.D_academy_lenient, 0) : "–"}</td>
      </tr>`;
    }).join("");
    el.innerHTML = `
      <h3>${title}</h3>
      <p class="moment-when"><b>${when(sec)}</b> · ${esc(ctx.phaseName(bin))} · ${place}</p>
      <p>Programme: ${evs.length ? evs.map((e) => `<b>${esc(e.label)}</b> <span class="muted">(${esc(e.kind)}${e.end_known ? "" : ", end inferred"})</span>`).join("; ") : "<span class='muted'>no programme item placed here</span>"}</p>
      <h4>Close in this 5-minute bin (≥ ${closeRssi} dBm)</h4>
      ${close.length ? `<table class="close"><tr><th>person</th><th>course</th><th>strongest signal</th><th>pressed within ±5 min</th><th>type</th><th>trust / lust (z)</th><th>D lenient</th></tr>${others}</table>` : "<p class='muted'>Nobody at close range in this bin.</p>"}
      <p class="caveat">Close means the strongest beacon signal between the two tags in the bin reached the threshold. Beacons cannot tell whether two people faced each other or talked: walls, pockets and bodies change the signal.</p>
      <h4>EDA around this moment</h4>
      <div class="around"></div>
      <p class="caveat">The camp-wide analysis found no arousal peak at presses. One person's trace around one moment is a clue to look at, not a confirmation. EDA moments are a working rule (SCR rate ≥ ${rule.z} SD above the person-day's mean, not adjusted for movement), not a validated measure.</p>
      <p><button type="button" class="to-camp">See this moment in the camp view</button></p>`;
    for (const btn of el.querySelectorAll(".jump")) btn.addEventListener("click", () => jumpTo(Number(btn.dataset.node)));
    el.querySelector(".to-camp").addEventListener("click", () => ctx.set({ tab: "camp", bin, playing: false }));
    around(el.querySelector(".around"), i, Math.floor(sec / 60), close.map((c) => c.node));
  }

  function around(el, i, centerMin, others) {
    const c = ctx.colors;
    if (!people[i].eda || edaIx.hi[i] <= edaIx.lo[i]) {
      el.innerHTML = "<p class='muted'>No EDA for this person.</p>";
      return;
    }
    const series = [{ node: i, own: true }, ...others.filter((o) => people[o].eda && edaIx.hi[o] > edaIx.lo[o]).map((o) => ({ node: o }))];
    const data = series.map((s) => ({ ...s, w: pm.edaAround(b.eda, edaIx.lo[s.node], edaIx.hi[s.node], centerMin, AROUND_MIN, AROUND_MIN, st.which) }));
    const width = Math.min(560, el.clientWidth || 560);
    const h = 120;
    const svg = d3.select(el).append("svg").attr("width", width).attr("height", h * 2 + 30);
    const x = d3.scaleLinear().domain([-AROUND_MIN, AROUND_MIN]).range([40, width - 26]);
    const max = (f) => d3.max(data.flatMap((d) => d.w.map((v) => (v ? f(v) : null)).filter((v) => v !== null))) ?? 1;
    const min = (f) => d3.min(data.flatMap((d) => d.w.map((v) => (v ? f(v) : null)).filter((v) => v !== null))) ?? 0;
    const panels = [["SCR / min", (v) => v.scr, 0, d3.scaleLinear().domain([0, Math.max(1, max((v) => v.scr))]).nice().range([h, 14])],
      ["heart rate", (v) => v.hr, h + 20, d3.scaleLinear().domain([Math.min(60, min((v) => v.hr)), Math.max(100, max((v) => v.hr))]).nice().range([2 * h + 6, h + 34])]];
    for (const [label, f, top, y] of panels) {
      svg.append("text").attr("x", 40).attr("y", top + 10).text(label);
      svg.append("g").attr("class", "axis").attr("transform", "translate(40,0)").call(d3.axisLeft(y).ticks(3).tickSize(3));
      for (const d of data) {
        d.w.forEach((v, k) => {
          if (v?.uncertain && d.own) svg.append("rect").attr("x", x(k - AROUND_MIN) - 3).attr("width", 6).attr("y", y.range()[1]).attr("height", y.range()[0] - y.range()[1]).attr("fill", c.glow).attr("opacity", 0.15);
        });
        const path = d3.line().defined((v) => v && f(v) !== null).x((v) => x(v.off)).y((v) => y(f(v)))(d.w);
        svg.append("path").attr("fill", "none").attr("stroke", d.own ? c.accent : c.ink3).attr("stroke-width", d.own ? 2 : 1).attr("opacity", d.own ? 1 : 0.6).attr("d", path);
      }
    }
    svg.append("line").attr("class", "cursor").attr("x1", x(0)).attr("x2", x(0)).attr("y1", 12).attr("y2", 2 * h + 6);
    svg.append("g").attr("class", "axis").attr("transform", `translate(0,${2 * h + 8})`).call(d3.axisBottom(x).ticks(6).tickFormat((d) => `${d > 0 ? "+" : ""}${d} min`).tickSize(3));
    if (series.length > 1) {
      d3.select(el).append("p").attr("class", "muted").text(`Blue: ${name(i)}. Grey: the ${series.length - 1} close ${series.length === 2 ? "person" : "people"} with EDA. Shaded: this person's clock is uncertain there.`);
    }
  }

  // ---- distribution -------------------------------------------------------------------------------
  let campCache = null;
  function campMeans() {
    const key = st.which;
    if (campCache?.key === key) return campCache;
    const pressArrays = [];
    const edaArrays = [];
    const pressPh = [];
    const edaPh = [];
    const nPh = meta.phases.length;
    for (let o = 0; o < nNodes; o++) {
      if (people[o].self_report) {
        const secs = pm.pressesOf(b, o);
        pressArrays.push(pm.countBy(secs.map((s) => b.bins.day[Math.min(nBins - 1, Math.floor(s / binS))]), nDays));
        pressPh.push(pm.countBy(secs.map((s) => b.bins.phase[Math.min(nBins - 1, Math.floor(s / binS))]), nPh));
      }
      if (people[o].eda && edaIx.hi[o] > edaIx.lo[o]) {
        const ms = moments(o);
        edaArrays.push(pm.countBy(ms.map((m) => dayOfMin(m.min)), nDays));
        edaPh.push(pm.countBy(ms.map((m) => b.bins.phase[Math.min(nBins - 1, Math.floor(m.min * binsPerMin))]), nPh));
      }
    }
    campCache = {
      key,
      press: pm.meanCounts(pressArrays, nDays), eda: pm.meanCounts(edaArrays, nDays),
      pressPh: pm.meanCounts(pressPh, nPh), edaPh: pm.meanCounts(edaPh, nPh),
      nPress: pressArrays.length, nEda: edaArrays.length,
    };
    return campCache;
  }

  function distribution() {
    const el = $("#person-dist");
    el.innerHTML = "";
    const i = st.node;
    const camp = campMeans();
    const secs = pm.pressesOf(b, i);
    const ms = people[i].eda ? moments(i) : [];
    const nPh = meta.phases.length;
    const own = {
      press: pm.countBy(secs.map((s) => b.bins.day[Math.min(nBins - 1, Math.floor(s / binS))]), nDays),
      eda: pm.countBy(ms.map((m) => dayOfMin(m.min)), nDays),
      pressPh: pm.countBy(secs.map((s) => b.bins.phase[Math.min(nBins - 1, Math.floor(s / binS))]), nPh),
      edaPh: pm.countBy(ms.map((m) => b.bins.phase[Math.min(nBins - 1, Math.floor(m.min * binsPerMin))]), nPh),
    };
    const c = ctx.colors;
    const chart = (title, labels, series) => {
      const width = el.clientWidth || 800;
      const h = 130;
      const svg = d3.select(el).append("svg").attr("width", "100%").attr("height", h);
      svg.append("text").attr("x", 36).attr("y", 11).text(title);
      const x0 = d3.scaleBand().domain(labels.map((_, k) => k)).range([36, width - 8]).padding(0.2);
      const x1 = d3.scaleBand().domain(series.map((_, k) => k)).range([0, x0.bandwidth()]).padding(0.1);
      const ymax = d3.max(series.flatMap((s) => [...s.own, ...s.camp.map((v) => v ?? 0)])) || 1;
      const y = d3.scaleLinear().domain([0, ymax]).nice().range([h - 20, 18]);
      svg.append("g").attr("class", "axis").attr("transform", "translate(36,0)").call(d3.axisLeft(y).ticks(3).tickSize(3));
      svg.append("g").attr("class", "axis").attr("transform", `translate(0,${h - 20})`).call(d3.axisBottom(x0).tickFormat((k) => labels[k]).tickSize(0));
      series.forEach((s, j) => {
        labels.forEach((lab, k) => {
          const v = s.own[k];
          svg.append("rect").attr("x", x0(k) + x1(j)).attr("width", x1.bandwidth()).attr("y", y(v)).attr("height", y(0) - y(v)).attr("rx", 1.5).attr("fill", s.fill)
            .on("mousemove", (ev) => ctx.tip.show(`<b>${esc(lab)}</b><br>${s.name}: ${v} (camp mean per person ${fmt(s.camp[k], 2)})`, ev.clientX, ev.clientY))
            .on("mouseleave", () => ctx.tip.hide());
          if (s.camp[k] !== null) {
            svg.append("line").attr("x1", x0(k) + x1(j)).attr("x2", x0(k) + x1(j) + x1.bandwidth()).attr("y1", y(s.camp[k])).attr("y2", y(s.camp[k]))
              .attr("stroke", c.ink1).attr("stroke-width", 1.5);
          }
        });
      });
      const lg = svg.append("g").attr("transform", `translate(${Math.max(200, width - 380)}, 4)`);
      [...series.map((s) => [s.name, s.fill]), ["camp mean per person", c.ink1]].forEach(([t, f], k) => {
        lg.append("rect").attr("x", k * 125).attr("y", 0).attr("width", 10).attr("height", k === series.length ? 2 : 10).attr("fill", f);
        lg.append("text").attr("x", k * 125 + 14).attr("y", 9).text(t);
      });
    };
    const series = (a, b2) => [
      { name: "presses", own: own[a], camp: camp[a], fill: c.accent },
      ...(people[i].eda ? [{ name: "EDA moments", own: own[b2], camp: camp[b2], fill: c.glow }] : []),
    ];
    chart("special moments per camp day", meta.days.map((d) => d.label.slice(4, 6)), series("press", "eda"));
    chart("by phase of the day", meta.phases, series("pressPh", "edaPh"));
    d3.select(el).append("p").attr("class", "muted").text(
      `Camp mean per person: over the ${camp.nPress} participants with a self-report dot and, for EDA moments, the ${camp.nEda} with worn EDA. ` +
      `Days with fewer worn hours have fewer chances for either.`);
  }

  // ---- render -------------------------------------------------------------------------------------
  function render() {
    rendered = true;
    if (st.node === null) st.node = 0;
    picker();
    crumbs();
    header();
    profile();
    membrane();
    timeline();
    momentPanel();
    distribution();
  }

  ctx.openPerson = (node, bin) => {
    st.node = node;
    st.crumbs = [];
    st.moment = bin === undefined ? null : { sec: bin * binS, kind: "time" };
    if (st.moment) st.day = b.bins.day[Math.min(nBins - 1, bin)];
    rendered = false;
    ctx.set({ tab: "person" });
  };

  function update(state, _p, _e, changed) {
    if (state.tab !== "person") return;
    const rssiChanged = closeRssi !== state.closeRssi;
    closeRssi = state.closeRssi;
    if (!rendered || changed.has("tab") || changed.has("theme")) render();
    else if (rssiChanged) { timeline(); momentPanel(); }
  }

  return { update };
}
