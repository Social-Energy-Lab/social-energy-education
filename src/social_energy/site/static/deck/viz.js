// The deck's own drawings. Data charts read aggregates from the public asset (never a number in
// git); the logic diagram, the clock illustration and the dashboard mock-up are schematic and
// say so. Pure helpers are exported for tests and touch neither the DOM nor d3 at import time.
//
// D3 is the global `d3` (../vendor/d3.min.js). Colours come from CSS tokens through classes in
// deck.css, so the light and dark themes both work without redrawing.
import {
  GROW_MS,
  block,
  caption,
  emptyNote,
  finite,
  hbars,
  numberFormat,
  svgIn,
  textWidth,
} from "../chapters/chart.js";

const fmt2 = numberFormat("en", 2);
const fmt1 = numberFormat("en", 1);

// --- pure helpers -------------------------------------------------------------------------

export const SOURCES = [
  ["beacons", "Beacons", "contact records"],
  ["presses", "Button presses", "presses → episodes"],
  ["survey", "Survey", "submissions"],
  ["eda", "EDA (skin conductance)", "worn minutes → usable"],
  ["heart_rate", "Heart rate", "worn minutes → usable"],
  ["interviews", "Interviews", "coded → analysed"],
];

/** data_state rows in source order, with the kept share in percent; bad rows go. */
export function stateRows(rows) {
  const by = new Map((rows ?? []).map((r) => [r?.source, r]));
  return SOURCES.flatMap(([key, name, unit]) => {
    const r = by.get(key);
    if (!r || !finite(r.raw) || !finite(r.clean) || r.raw <= 0) return [];
    return [{ key, name, unit, raw: r.raw, clean: r.clean, people: r.people,
              kept: Math.min(100, (100 * r.clean) / r.raw) }]; // prettier-ignore
  });
}

/** A share in plain words: "about half" near 50, else "about N%" (one decimal under 1). */
export function roughShare(pct) {
  if (!finite(pct)) return "some";
  if (pct >= 45 && pct <= 55) return "about half";
  return `about ${pct >= 1 ? Math.round(pct) : fmt1(pct)}%`;
}

/**
 * Why a source keeps fewer records than it recorded, in one plain line. Counts and shares come
 * from the row (the asset), never from this file.
 */
export function dropReason(row) {
  const lost = finite(row?.raw) && finite(row?.clean) ? row.raw - row.clean : null;
  const share = finite(row?.kept) ? 100 - row.kept : null;
  const count = (n, one, many) => (n === 1 ? `One ${one}` : `${shortCount(n)} ${many}`);
  switch (row?.key) {
    case "beacons":
      return `Dropped, ${roughShare(share)}: copies, records outside the camp window, and windows when a tag was broken (from the field notes).`;
    case "presses":
      return "Mostly merging: one moment is often several presses (many pressed twice, a 3 s hold each), so presses under 60 s apart are one episode. Also out: copies from overlapping readouts, staff (analysed separately), broken-tag windows, accidental presses.";
    case "survey":
      if (!finite(lost) || lost <= 0) return "Nothing removed.";
      return `${count(lost, "double submission", "double submissions")} removed.`;
    case "eda":
      return "Minutes with artefacts (movement, a loose sensor, impossible jumps) are left out: they would fake arousal peaks.";
    case "heart_rate":
      return `The finger-clip pulse sensor is fragile: ${roughShare(share)} of the worn minutes have no clean heartbeat.`;
    case "interviews":
      if (!finite(lost) || lost <= 0) return "Every coded interview is analysed.";
      return lost === 1
        ? "One recording is not from a participant with interview consent, so it is outside the analysis unit."
        : `${shortCount(lost)} recordings are not from participants with interview consent, so they are outside the analysis unit.`;
    default:
      return "";
  }
}

/** A count in short form: 1,234 · 56.7k · 63.7M. */
export function shortCount(v) {
  if (!finite(v)) return "–";
  const a = Math.abs(v);
  if (a >= 1e6) return `${fmt1(v / 1e6)}M`;
  if (a >= 1e4) return `${fmt1(v / 1e3)}k`;
  return new Intl.NumberFormat("en").format(Math.round(v));
}

export const MEASURES = [
  ["trust", "Trust in life (composite)"],
  ["lust", "Lust for life (composite)"],
  ["trust_scales", "Trust profile (6 scales)"],
  ["lust_scales", "Lust profile (6 scales)"],
  ["all_scales", "All 12 scales"],
];
export const SAMPLES = [
  ["all", "All pairs"],
  ["within", "Same course"],
  ["between", "Different courses"],
];

/** gradient_pairs rows grouped by measure (in MEASURES order), each with its samples. */
export function gradientGroups(rows) {
  const ok = (rows ?? []).filter(
    (r) => finite(r?.r) && finite(r?.null_lo) && finite(r?.null_hi),
  );
  return MEASURES.flatMap(([key, name]) => {
    const dots = SAMPLES.flatMap(([s, sName], i) => {
      const r = ok.find((d) => d.measure === key && d.sample === s);
      return r ? [{ ...r, sampleIndex: i, sampleName: sName }] : [];
    });
    return dots.length ? [{ key, name, dots }] : [];
  });
}

/** gradient_presses rows for one measure, near → far. */
export function copressRows(rows, measure = "trust") {
  const order = ["near", "middle", "far"];
  return (rows ?? [])
    .filter((r) => r?.measure === measure && finite(r.share) && finite(r.time_null))
    .sort((a, b) => order.indexOf(a.tercile) - order.indexOf(b.tercile));
}

/** eda_press_profile rows in offset order, complete ones only. */
export function profileRows(rows) {
  return (rows ?? [])
    .filter((r) => [r?.offset, r?.observed, r?.null_lo, r?.null_hi].every(finite))
    .sort((a, b) => a.offset - b.offset);
}

export const REASON_NAMES = {
  people: "Other people",
  programme: "Programme items",
  arts: "Music and the arts",
  vulnerability: "Others opening up",
  freedom: "Freedom from school pressure",
  being_heard: "Being heard",
  course: "The course",
  nature: "Nature",
  conflict: "Conflict",
  fatigue: "Fatigue",
  withdrawal_need: "Needing time alone",
  pressure: "Pressure",
  safety: "Feeling unsafe",
  loss: "Loss",
  end: "The end approaching",
};

/** membrane_reasons rows for one direction, largest share first. */
export function reasonRows(rows, direction) {
  return (rows ?? [])
    .filter((r) => r?.direction === direction && finite(r.share))
    .sort((a, b) => b.share - a.share)
    .map((r) => ({ name: REASON_NAMES[r.reason] ?? r.reason, value: r.share,
                   tip: `${REASON_NAMES[r.reason] ?? r.reason}: ${fmt1(r.share)}%` })); // prettier-ignore
}

/** A small seeded PRNG (mulberry32), for the schematic drawings only. */
export function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let x = Math.imul(a ^ (a >>> 15), 1 | a);
    x = (x + Math.imul(x ^ (x >>> 7), 61 | x)) ^ x;
    return ((x ^ (x >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * The clock illustration's lanes: each instrument's events as it recorded them (`raw`) and on
 * the camp clock (`true`), in 0..1 of the drawn day. Invented, not data.
 */
export function syncLanes(n = 7) {
  const at = Array.from({ length: n }, (_, i) => 0.08 + (i * 0.84) / (n - 1));
  return [
    { key: "programme", name: "Programme (timetable)", events: at.map((x) => ({ true: x, raw: x })) },
    { key: "beacons", name: "Beacons (drifting tag clock)",
      events: at.map((x) => ({ true: x, raw: x + 0.01 + x * 0.07 })) },
    { key: "eda", name: "EDA wristbands (device clock)",
      events: at.map((x) => ({ true: x, raw: x - 0.05 - x * 0.03 })) },
    { key: "interviews", name: "Interviews (local time)",
      events: at.filter((_, i) => i % 3 === 1).map((x) => ({ true: x, raw: x - 0.09 })) },
  ]; // prettier-ignore
}

// --- drawing ------------------------------------------------------------------------------

const reducedMotion = (opts) => Boolean(opts?.reduced);
const ease = () => d3.easeCubicOut;

/** Data state: per source, the share of records kept, with counts and people beside it. */
export function drawState(el, agg, opts) {
  const rows = stateRows(agg?.data_state);
  el.replaceChildren();
  if (!rows.length) return emptyNote(el, opts.t);
  const list = document.createElement("div");
  list.className = "state";
  for (const r of rows) {
    const row = document.createElement("div");
    row.className = "state-row";
    row.innerHTML = `<div class="state-name"></div><div class="state-track"><div class="state-bar"></div></div><div class="state-text"></div><div class="state-reason"></div>`;
    row.querySelector(".state-name").textContent = r.name;
    const people = finite(r.people) ? ` · ${shortCount(r.people)} people` : "";
    row.querySelector(".state-text").textContent =
      `${shortCount(r.clean)} of ${shortCount(r.raw)} ${r.unit}${people}`;
    row.querySelector(".state-reason").textContent = dropReason(r);
    row.title = `${r.name}: ${fmt1(r.kept)}% kept`;
    const bar = row.querySelector(".state-bar");
    bar.dataset.kept = `${Math.round(r.kept)}%`;
    list.append(row);
    requestAnimationFrame(() => {
      bar.style.width = `${r.kept}%`;
    });
  }
  el.append(list);
  caption(el, "Bar: share of recorded data that is usable after cleaning and consent filtering.");
}

/** EDA minutes by clock source: one stacked bar from the asset's numbers. */
export function drawClockBar(el, numbers) {
  const parts = [
    ["sync", "synced to a reference clock", numbers?.eda_clock_sync_pct],
    ["rate", "rate-corrected (fallback)", numbers?.eda_clock_rate_pct],
    ["box", "anchored by the charging box", numbers?.eda_clock_box_pct],
  ].filter(([, , v]) => finite(v) && v > 0);
  if (!parts.length) return;
  const fig = block(el, "EDA worn minutes, by how their clock was fixed");
  const bar = document.createElement("div");
  bar.className = "stack";
  const legend = document.createElement("ul");
  legend.className = "legend-inline";
  for (const [key, name, v] of parts) {
    const seg = document.createElement("div");
    seg.className = `seg seg-${key}`;
    seg.style.flexGrow = String(v);
    seg.title = `${name}: ${fmt1(v)}%`;
    bar.append(seg);
    const li = document.createElement("li");
    li.innerHTML = `<span class="sw seg-${key}"></span>`;
    li.append(`${name} · ${Math.round(v)}%`);
    legend.append(li);
  }
  fig.append(bar, legend);
}

/** The clock illustration: each lane's marks slide from their own clock onto the camp clock. */
export function drawSync(el, opts) {
  el.replaceChildren();
  const fig = block(el, "");
  const lanes = syncLanes();
  const laneH = 46;
  const top = 10;
  const height = top + lanes.length * laneH + 26;
  const probe = svgIn(fig, 10, "");
  const labelW = Math.min(probe.width * 0.42, textWidth(probe.svg, lanes.map((l) => l.name)) + 16);
  probe.svg.remove();
  const { svg, width } = svgIn(
    fig,
    height,
    "Illustration: events from four instruments, each on its own clock, move onto one camp clock.",
  );
  const x = d3.scaleLinear().domain([0, 1]).range([labelW, width - 12]);
  const g = svg
    .selectAll("g.lane")
    .data(lanes)
    .join("g")
    .attr("class", (d) => `lane lane-${d.key}`)
    .attr("transform", (_, i) => `translate(0,${top + i * laneH})`);
  g.append("line").attr("class", "lane-rule").attr("x1", labelW).attr("x2", width - 12)
    .attr("y1", laneH / 2).attr("y2", laneH / 2); // prettier-ignore
  g.append("text").attr("class", "row-label").attr("x", labelW - 10).attr("y", laneH / 2)
    .attr("dy", "0.35em").attr("text-anchor", "end").text((d) => d.name); // prettier-ignore
  const marks = g
    .selectAll("rect.mark")
    .data((d) => d.events)
    .join("rect")
    .attr("class", "mark")
    .attr("y", laneH / 2 - 11)
    .attr("width", 6)
    .attr("height", 22)
    .attr("rx", 3)
    .attr("x", (d) => x(d.raw) - 3);
  const moment = svg
    .append("line")
    .attr("class", "moment")
    .attr("y1", top - 4)
    .attr("y2", top + lanes.length * laneH)
    .attr("x1", x(lanes[0].events[3].true))
    .attr("x2", x(lanes[0].events[3].true))
    .attr("opacity", 0);
  svg
    .append("text")
    .attr("class", "axis-title moment-label")
    .attr("x", x(lanes[0].events[3].true))
    .attr("y", height - 6)
    .attr("text-anchor", "middle")
    .attr("opacity", 0)
    .text("one moment, every source");
  const settle = (instant) => {
    const tr = (sel, delay = 0) =>
      instant ? sel : sel.transition().delay(delay).duration(1400).ease(ease());
    tr(marks, 500).attr("x", (d) => x(d.true) - 3);
    tr(moment, 1900).attr("opacity", 1);
    tr(svg.select(".moment-label"), 1900).attr("opacity", 1);
  };
  settle(reducedMotion(opts));
  caption(fig, "Illustration, not data: how far each clock drifts here is invented.");
}

/** Skin conductance around a press: observed line against the shuffled-press band. */
export function drawEdaProfile(el, agg, opts) {
  const rows = profileRows(agg?.eda_press_profile);
  el.replaceChildren();
  if (!rows.length) return emptyNote(el, opts.t);
  const fig = block(el, "Skin-conductance responses around a press (within person and day)");
  const height = 260;
  const { svg, width } = svgIn(
    fig,
    height,
    "Line: skin-conductance response rate in the minutes around a press. Band: the range expected if presses fell at random times of the same person's day.",
  );
  const m = { l: 46, r: 14, t: 20, b: 42 };
  const x = d3.scaleLinear().domain(d3.extent(rows, (r) => r.offset)).range([m.l, width - m.r]);
  const lo = d3.min(rows, (r) => Math.min(r.null_lo, r.observed));
  const hi = d3.max(rows, (r) => Math.max(r.null_hi, r.observed));
  const y = d3.scaleLinear().domain([lo, hi]).nice().range([height - m.b, m.t]);
  svg.append("g").attr("class", "grid").selectAll("line").data(y.ticks(4)).join("line")
    .attr("x1", m.l).attr("x2", width - m.r).attr("y1", y).attr("y2", y); // prettier-ignore
  const ax = svg.append("g").attr("class", "axis");
  ax.selectAll("text.y").data(y.ticks(4)).join("text").attr("class", "y").attr("x", m.l - 6)
    .attr("y", y).attr("dy", "0.35em").attr("text-anchor", "end").text((d) => fmt2(d)); // prettier-ignore
  ax.selectAll("text.x").data(x.ticks(Math.min(10, Math.floor(width / 70)))).join("text")
    .attr("class", "x").attr("x", x).attr("y", height - m.b + 18).attr("text-anchor", "middle")
    .text((d) => (d > 0 ? `+${d}` : `${d}`)); // prettier-ignore
  ax.append("text").attr("class", "axis-title").attr("x", width - m.r).attr("y", height - 4)
    .attr("text-anchor", "end").text("minutes from the press"); // prettier-ignore
  svg.append("path").datum(rows).attr("class", "band")
    .attr("d", d3.area().x((r) => x(r.offset)).y0((r) => y(r.null_lo)).y1((r) => y(r.null_hi))); // prettier-ignore
  svg.append("line").attr("class", "reference").attr("x1", x(0)).attr("x2", x(0))
    .attr("y1", m.t - 6).attr("y2", height - m.b); // prettier-ignore
  svg.append("text").attr("class", "reference-label").attr("x", x(0) + 6).attr("y", m.t)
    .text("press"); // prettier-ignore
  const line = svg.append("path").datum(rows).attr("class", "line")
    .attr("d", d3.line().x((r) => x(r.offset)).y((r) => y(r.observed))); // prettier-ignore
  svg.append("g").selectAll("circle").data(rows).join("circle").attr("class", "estimate")
    .attr("cx", (r) => x(r.offset)).attr("cy", (r) => y(r.observed)).attr("r", 4)
    .append("title")
    .text((r) => `${r.offset > 0 ? "+" : ""}${r.offset} min: ${fmt2(r.observed)} (expected ${fmt2(r.null_lo)} to ${fmt2(r.null_hi)})`); // prettier-ignore
  if (!reducedMotion(opts)) {
    const len = line.node().getTotalLength?.() ?? 0;
    line.attr("stroke-dasharray", `${len} ${len}`).attr("stroke-dashoffset", len)
      .transition().duration(1600).ease(d3.easeCubicInOut).attr("stroke-dashoffset", 0); // prettier-ignore
  }
  const legend = document.createElement("ul");
  legend.className = "legend-inline";
  legend.innerHTML =
    '<li><span class="sw sw-line-accent"></span>around the real presses</li><li><span class="sw sw-band"></span>expected if presses were shuffled (95%)</li>';
  fig.append(legend);
}

/** What opens and what closes the membrane: two bar blocks, share of interviewees. */
export function drawReasons(el, agg, opts) {
  el.replaceChildren();
  const opens = reasonRows(agg?.membrane_reasons, "opens");
  const closes = reasonRows(agg?.membrane_reasons, "closes");
  if (!opens.length && !closes.length) return emptyNote(el, opts.t);
  for (const [rows, title] of [
    [opens, "What opens it"],
    [closes, "What closes it"],
  ]) {
    if (!rows.length) continue;
    const fig = block(el, title);
    hbars(fig, rows, {
      label: `${title}: share of interviewees naming each reason.`,
      axis: "% of interviewees",
      tick: (d) => `${d}%`,
      reduced: opts.reduced,
      el,
    });
  }
  caption(el, "Reasons named by fewer than 5 people are not shown. Model-coded, not yet hand-checked.");
}

/** Gradient theory, pairs: partial r per distance measure and sample, with the null band. */
export function drawGradients(el, agg, opts) {
  const groups = gradientGroups(agg?.gradient_pairs);
  el.replaceChildren();
  if (!groups.length) return emptyNote(el, opts.t);
  const fig = block(el, "Membrane difference and time spent close");
  const rowH = 46;
  const m = { t: 30, b: 44, r: 14 };
  const height = m.t + groups.length * rowH + m.b;
  const probe = svgIn(fig, 10, "");
  const labelW = Math.min(probe.width * 0.38, textWidth(probe.svg, groups.map((g) => g.name)) + 16);
  probe.svg.remove();
  const { svg, width } = svgIn(
    fig,
    height,
    "Dots: partial correlation of membrane difference with close minutes, per measure and sample. Grey bars: the range a reshuffle of membranes gives. Left of zero: similar people meet more.",
  );
  const all = groups.flatMap((g) => g.dots);
  const ext = d3.max(all, (d) => Math.max(Math.abs(d.r), Math.abs(d.null_lo), Math.abs(d.null_hi)));
  const x = d3.scaleLinear().domain([-ext * 1.1, ext * 1.1]).nice().range([labelW, width - m.r]);
  const ticks = x.ticks(Math.max(3, Math.min(7, Math.floor((width - labelW) / 70))));
  svg.append("g").attr("class", "grid").selectAll("line").data(ticks).join("line")
    .attr("x1", x).attr("x2", x).attr("y1", m.t).attr("y2", height - m.b); // prettier-ignore
  const ax = svg.append("g").attr("class", "axis");
  ax.selectAll("text").data(ticks).join("text").attr("x", x).attr("y", height - m.b + 16)
    .attr("text-anchor", "middle").text((d) => fmt2(d)); // prettier-ignore
  ax.append("text").attr("class", "axis-title").attr("x", labelW).attr("y", height - 6)
    .text("← similar meet more"); // prettier-ignore
  ax.append("text").attr("class", "axis-title").attr("x", width - m.r).attr("y", height - 6)
    .attr("text-anchor", "end").text("different meet more →"); // prettier-ignore
  svg.append("line").attr("class", "reference").attr("x1", x(0)).attr("x2", x(0))
    .attr("y1", m.t - 8).attr("y2", height - m.b); // prettier-ignore
  const g = svg.selectAll("g.measure").data(groups).join("g").attr("class", "measure")
    .attr("transform", (_, i) => `translate(0,${m.t + i * rowH})`); // prettier-ignore
  g.append("text").attr("class", "row-label").attr("x", labelW - 10).attr("y", rowH / 2)
    .attr("dy", "0.35em").attr("text-anchor", "end").text((d) => d.name); // prettier-ignore
  const dy = (d) => rowH / 2 + (d.sampleIndex - 1) * 12;
  const dots = g.selectAll("g.dot").data((d) => d.dots).join("g").attr("class", "dot");
  dots.append("line").attr("class", "null-band").attr("x1", (d) => x(d.null_lo))
    .attr("x2", (d) => x(d.null_hi)).attr("y1", dy).attr("y2", dy); // prettier-ignore
  const marks = dots.append("circle").attr("class", (d) => `sample sample-${d.sampleIndex}`)
    .attr("r", 5).attr("cy", dy).attr("cx", x(0)); // prettier-ignore
  marks.append("title").text((d) =>
    `${d.sampleName}, ${groups.find((g) => g.dots.includes(d))?.name}: r ${fmt2(d.r)} (reshuffles ${fmt2(d.null_lo)} to ${fmt2(d.null_hi)})`);
  if (reducedMotion(opts)) marks.attr("cx", (d) => x(d.r));
  else marks.transition().delay((d) => 300 + d.sampleIndex * 150).duration(GROW_MS * 1.6)
    .ease(ease()).attr("cx", (d) => x(d.r)); // prettier-ignore
  const legend = document.createElement("ul");
  legend.className = "legend-inline";
  for (const [i, [, name]] of SAMPLES.entries()) {
    const li = document.createElement("li");
    li.innerHTML = `<span class="sw sw-dot sample-${i}"></span>`;
    li.append(name);
    legend.append(li);
  }
  const li = document.createElement("li");
  li.innerHTML = '<span class="sw sw-band"></span>';
  li.append("range from reshuffling membranes within courses (95%)");
  legend.append(li);
  fig.append(legend);
}

/** Gradient theory, presses: co-press share by membrane difference, against chance timing. */
export function drawCopress(el, agg, opts) {
  const rows = copressRows(agg?.gradient_presses, "trust");
  el.replaceChildren();
  if (!rows.length) return;
  const fig = block(el, "A close partner presses too, by difference in trust in life");
  const names = { near: "Most similar third", middle: "Middle third", far: "Most different third" };
  const rowH = 34;
  const m = { t: 6, b: 40, r: 16 };
  const height = m.t + rows.length * rowH + m.b;
  const probe = svgIn(fig, 10, "");
  const labelW = Math.min(probe.width * 0.42, textWidth(probe.svg, Object.values(names)) + 14);
  probe.svg.remove();
  const { svg, width } = svgIn(
    fig,
    height,
    "Bars: share of moments in which a close partner also pressed, by membrane difference. Ticks: the share expected from each person's own timing.",
  );
  const max = d3.max(rows, (r) => Math.max(r.share, r.time_null)) * 1.1;
  const x = d3.scaleLinear().domain([0, max]).nice().range([labelW, width - m.r]);
  const ticks = x.ticks(Math.max(3, Math.min(6, Math.floor((width - labelW) / 70))));
  svg.append("g").attr("class", "grid").selectAll("line").data(ticks).join("line")
    .attr("x1", x).attr("x2", x).attr("y1", m.t).attr("y2", height - m.b); // prettier-ignore
  const ax = svg.append("g").attr("class", "axis");
  ax.selectAll("text").data(ticks).join("text").attr("x", x).attr("y", height - m.b + 16)
    .attr("text-anchor", "middle").text((d) => `${d}%`); // prettier-ignore
  ax.append("text").attr("class", "axis-title").attr("x", width - m.r).attr("y", height - 6)
    .attr("text-anchor", "end").text("% of moments the partner pressed too"); // prettier-ignore
  const g = svg.selectAll("g.row").data(rows).join("g").attr("class", "row")
    .attr("transform", (_, i) => `translate(0,${m.t + i * rowH})`); // prettier-ignore
  g.append("text").attr("class", "row-label").attr("x", labelW - 10).attr("y", rowH / 2)
    .attr("dy", "0.35em").attr("text-anchor", "end").text((r) => names[r.tercile]); // prettier-ignore
  const bars = g.append("rect").attr("class", "bar").attr("x", x(0)).attr("y", 7)
    .attr("height", rowH - 14).attr("rx", 3).attr("width", 0); // prettier-ignore
  bars.append("title").text((r) =>
    `${names[r.tercile]}: ${fmt1(r.share)}% (from own timing ${fmt1(r.time_null)}%)`);
  g.append("line").attr("class", "chance").attr("x1", (r) => x(r.time_null))
    .attr("x2", (r) => x(r.time_null)).attr("y1", 2).attr("y2", rowH - 2); // prettier-ignore
  const w = (r) => x(r.share) - x(0);
  if (reducedMotion(opts)) bars.attr("width", w);
  else bars.transition().delay((_, i) => 200 + i * 80).duration(GROW_MS).ease(ease()).attr("width", w);
  const legend = document.createElement("ul");
  legend.className = "legend-inline";
  legend.innerHTML =
    '<li><span class="sw sw-bar"></span>observed</li><li><span class="sw sw-chance"></span>expected from each person\'s own timing</li>';
  fig.append(legend);
}

/**
 * The title's night sky: six course clusters on a ring, a few ties, a few glows. Decorative and
 * invented, in the network's colours; not data.
 */
export function drawSky(el) {
  el.replaceChildren();
  const W = 520;
  const H = 520;
  const rand = rng(11);
  const svg = d3
    .select(el)
    .append("svg")
    .attr("class", "sky")
    .attr("viewBox", `0 0 ${W} ${H}`)
    .attr("aria-hidden", "true");
  const cx = W / 2;
  const cy = H / 2;
  const R = 170;
  svg.append("circle").attr("class", "sky-ring").attr("cx", cx).attr("cy", cy).attr("r", R);
  const dots = [];
  for (let c = 0; c < 6; c++) {
    const a = (c / 6) * 2 * Math.PI - Math.PI / 2;
    for (let i = 0; i < 9; i++) {
      const r = R + (rand() - 0.5) * 120;
      const b = a + (rand() - 0.5) * 0.75;
      dots.push({ c, x: cx + r * Math.cos(b), y: cy + r * Math.sin(b) });
    }
  }
  const ties = [];
  for (const d of dots) {
    const near = dots.filter((e) => e !== d && Math.hypot(e.x - d.x, e.y - d.y) < 62);
    for (const e of near.slice(0, 2)) if (rand() < 0.55) ties.push([d, e]);
  }
  svg.append("g").selectAll("line").data(ties).join("line")
    .attr("class", ([a, b]) => `sky-tie ${a.c === b.c ? `c${a.c + 1}` : "cx"}`)
    .attr("x1", ([a]) => a.x).attr("y1", ([a]) => a.y).attr("x2", ([, b]) => b.x).attr("y2", ([, b]) => b.y); // prettier-ignore
  svg.append("g").selectAll("circle").data(dots).join("circle")
    .attr("class", (d) => `c${d.c + 1}`).attr("cx", (d) => d.x).attr("cy", (d) => d.y).attr("r", 5.5); // prettier-ignore
  for (const d of [dots[4], dots[23], dots[41]]) {
    svg.append("circle").attr("class", "sky-glow").attr("cx", d.x).attr("cy", d.y).attr("r", 14)
      .attr("opacity", 0.22); // prettier-ignore
    svg.append("circle").attr("class", "sky-glow").attr("cx", d.x).attr("cy", d.y).attr("r", 6);
  }
}

/** The membrane logic, schematically: two membranes of twelve scales, a gradient, a flow. */
export function drawLogic(el, opts) {
  el.replaceChildren();
  const W = 640;
  const H = 364;
  const svg = d3
    .select(el)
    .append("svg")
    .attr("class", "logic")
    .attr("viewBox", `0 0 ${W} ${H}`)
    .attr("width", "100%")
    .attr("role", "img")
    .attr(
      "aria-label",
      "Diagram: two people, each surrounded by a membrane of twelve process variables, six for trust in life and six for lust for life. The difference between them is a gradient, along which something may flow.",
    );
  const rand = rng(7);
  const people = [
    { cx: 160, cy: 176, r: 92, k: 0 },
    { cx: 480, cy: 176, r: 92, k: 1 },
  ];
  const arc = d3.arc();
  for (const p of people) {
    const g = svg.append("g").attr("transform", `translate(${p.cx},${p.cy})`);
    g.append("circle").attr("class", "core").attr("r", 26);
    for (let i = 0; i < 12; i++) {
      const thick = 8 + rand() * (p.k ? 22 : 12);
      const a0 = (i / 12) * 2 * Math.PI + 0.03;
      const a1 = ((i + 1) / 12) * 2 * Math.PI - 0.03;
      g.append("path")
        .attr("class", i < 6 ? "scale-trust" : "scale-lust")
        .attr("d", arc({ innerRadius: p.r - 30, outerRadius: p.r - 30 + thick, startAngle: a0, endAngle: a1 }))
        .attr("opacity", 0)
        .transition()
        .delay(reducedMotion(opts) ? 0 : 150 + i * 60 + p.k * 300)
        .duration(reducedMotion(opts) ? 0 : 400)
        .attr("opacity", 1);
    }
  }
  const lbl = (x, y, text, cls = "logic-label", anchor = "middle") =>
    svg.append("text").attr("class", cls).attr("x", x).attr("y", y).attr("text-anchor", anchor).text(text);
  lbl(160, 20, "membrane of person A");
  lbl(480, 20, "membrane of person B");
  lbl(40, 322, "■ trust in life: 6 scales", "logic-key trust", "start");
  lbl(330, 322, "■ lust for life: 6 scales", "logic-key lust", "start");
  // The gradient between them.
  const path = "M 268 176 C 320 120, 320 120, 372 176";
  svg.append("path").attr("class", "gradient-path").attr("d", path);
  const dots = svg.append("g");
  for (let i = 0; i < 4; i++) {
    dots.append("circle").attr("class", "flow").attr("r", 5).style("offset-path", `path("${path}")`)
      .style("animation-delay", `${i * 0.6}s`); // prettier-ignore
  }
  lbl(320, 62, "gradient: where membranes differ", "logic-label strong");
  lbl(320, 290, "a reaction may flow, or be held back", "logic-label");
  lbl(320, 350, "moments that matter: a button press (1st person) · EDA, heart rate (3rd person, hypothesis)", "logic-note");
}

/** The person view, as a mock-up with invented data. */
export function drawDashboard(el, opts) {
  el.replaceChildren();
  const rand = rng(42);
  const W = 720;
  const H = 360;
  const svg = d3
    .select(el)
    .append("svg")
    .attr("class", "dash")
    .attr("viewBox", `0 0 ${W} ${H}`)
    .attr("width", "100%")
    .attr("role", "img")
    .attr("aria-label", "Mock-up of the researchers' person view, with invented data: a membrane profile, a day's timeline with programme, presses, skin conductance and heart rate, and a selected moment showing who was close.");
  svg.append("rect").attr("class", "dash-frame").attr("x", 1).attr("y", 1).attr("width", W - 2)
    .attr("height", H - 2).attr("rx", 10); // prettier-ignore
  svg.append("text").attr("class", "dash-title").attr("x", 16).attr("y", 26).text("Person view · invented example");
  // Membrane profile.
  svg.append("text").attr("class", "dash-sub").attr("x", 16).attr("y", 52).text("membrane profile");
  for (let i = 0; i < 12; i++) {
    const v = 0.25 + rand() * 0.75;
    svg.append("rect").attr("class", i < 6 ? "scale-trust" : "scale-lust").attr("x", 16)
      .attr("y", 62 + i * 21).attr("height", 14).attr("rx", 3).attr("width", 0)
      .transition().delay(reducedMotion(opts) ? 0 : i * 50).duration(reducedMotion(opts) ? 0 : 500)
      .attr("width", v * 130); // prettier-ignore
  }
  // Timeline.
  const x0 = 190;
  const x1 = W - 16;
  const x = d3.scaleLinear().domain([8, 23]).range([x0, x1]);
  const blocks = [[8.5, 12.5, "course"], [12.5, 14, "meal"], [14.5, 18, "course"], [18, 19, "meal"], [19.5, 21.5, "KüA"], [21.5, 23, "late"]]; // prettier-ignore
  svg.append("text").attr("class", "dash-sub").attr("x", x0).attr("y", 52).text("programme");
  for (const [a, b, name] of blocks) {
    svg.append("rect").attr("class", `prog prog-${name === "course" ? "a" : "b"}`).attr("x", x(a))
      .attr("y", 60).attr("width", x(b) - x(a) - 2).attr("height", 22).attr("rx", 4); // prettier-ignore
    svg.append("text").attr("class", "dash-tiny").attr("x", x(a) + 5).attr("y", 75).text(name);
  }
  svg.append("text").attr("class", "dash-sub").attr("x", x0).attr("y", 110).text("skin conductance · heart rate");
  const series = (seed, base, amp) => {
    const r = rng(seed);
    let v = base;
    return d3.range(8.5, 18.1, 0.1).map((t) => ({ t, v: (v += (r() - 0.5) * amp) }));
  };
  const eda = series(3, 150, 6);
  const hr = series(9, 190, 5);
  const line = d3.line().x((d) => x(d.t)).y((d) => d.v);
  svg.append("path").attr("class", "dash-eda").attr("d", line(eda));
  svg.append("path").attr("class", "dash-hr").attr("d", line(hr));
  svg.append("text").attr("class", "dash-tiny").attr("x", x(18.3)).attr("y", 200).text("EDA worn in daytime only");
  svg.append("text").attr("class", "dash-sub").attr("x", x0).attr("y", 246).text("button presses");
  const presses = [10.2, 15.6, 20.3, 22.1];
  for (const p of presses) svg.append("circle").attr("class", "dash-press").attr("cx", x(p)).attr("cy", 262).attr("r", 6);
  // The selected moment.
  const sel = presses[2];
  const cursor = svg.append("line").attr("class", "moment").attr("y1", 56).attr("y2", 330)
    .attr("x1", x(8)).attr("x2", x(8)); // prettier-ignore
  const card = svg.append("g").attr("opacity", 0).attr("transform", `translate(${x(sel) - 300},280)`);
  card.append("rect").attr("class", "dash-card").attr("width", 286).attr("height", 62).attr("rx", 8);
  card.append("text").attr("class", "dash-tiny strong").attr("x", 10).attr("y", 18).text("20:18 · KüA · 3 people close");
  card.append("text").attr("class", "dash-tiny").attr("x", 10).attr("y", 36).text("1 pressed too, within 40 s");
  card.append("text").attr("class", "dash-tiny").attr("x", 10).attr("y", 53).text("membrane difference: small · large · large");
  if (reducedMotion(opts)) {
    cursor.attr("x1", x(sel)).attr("x2", x(sel));
    card.attr("opacity", 1);
  } else {
    cursor.transition().delay(400).duration(1800).ease(ease()).attr("x1", x(sel)).attr("x2", x(sel));
    card.transition().delay(2200).duration(400).attr("opacity", 1);
  }
}
