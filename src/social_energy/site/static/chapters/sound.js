// Chapter: how did the two halls sound? Per hall, its daily median level over the academy (the
// loudest tenth of five-minute slots dashed, special days shaded), then its level by programme
// kind: the median as a dot, the middle half as a line, the recorded hours beside it. Levels are
// dBFS, relative to each hall's own recorder, so every hall gets its own scale and the two are
// never drawn on one axis.
import {
  block,
  caption,
  dayLabel,
  dayOrder,
  emptyNote,
  finite,
  fitLabel,
  metaDay,
  named,
  numberFormat,
  onResize,
  svgIn,
  textWidth,
} from "./chart.js";
import { markSpecial } from "./circles.js";

/** The halls, in the order the page shows them (``room_<key>`` in the copy). */
export const ROOMS = ["main_hall", "dining_hall"];

/** sound_day rows of `room` → [{day, leq, p90, hours}] in day order; rows without a level go. */
export function soundDays(rows, room) {
  return (rows ?? [])
    .filter((r) => r?.room === room && finite(r.leq))
    .map((r) => ({
      day: r.day,
      leq: r.leq,
      p90: finite(r.leq_p90) ? r.leq_p90 : null,
      hours: finite(r.hours) ? r.hours : null,
    }))
    .sort((a, b) => dayOrder(a.day, b.day));
}

/** sound_kind rows of `room` → loudest median first; rows without a level go. */
export function soundKinds(rows, room) {
  return (rows ?? [])
    .filter((r) => r?.room === room && finite(r.leq))
    .map((r) => ({
      programme: r.programme,
      leq: r.leq,
      lo: finite(r.lo) ? r.lo : null,
      hi: finite(r.hi) ? r.hi : null,
      hours: finite(r.hours) ? r.hours : null,
    }))
    .sort((a, b) => b.leq - a.leq);
}

/** The days either hall has, in order, so both halls' charts share one time axis. */
export function allDays(rows) {
  return [...new Set((rows ?? []).filter((r) => finite(r?.leq)).map((r) => r.day))].sort(dayOrder);
}

/** The special-day label (excursion, rotation) of `day`, else null. */
export function specialOn(day, meta) {
  const m = metaDay(day, meta);
  if (!m) return null;
  return markSpecial(meta?.days, meta?.special_days).find((d) => d.index === m.index)?.special ?? null;
}

/** A y domain around `values`, padded, at least `span` dB tall. */
export function levelDomain(values, span = 6) {
  const v = values.filter(finite);
  if (!v.length) return [-60, -20];
  let lo = Math.min(...v);
  let hi = Math.max(...v);
  if (hi - lo < span) {
    const mid = (lo + hi) / 2;
    lo = mid - span / 2;
    hi = mid + span / 2;
  }
  const pad = (hi - lo) * 0.08;
  return [lo - pad, hi + pad];
}

function dayChart(host, series, days, { meta, lang, t, room }) {
  const fmt = numberFormat(lang, 1);
  const unit = t("ch_sound_unit");
  const summary = `${named(t, "room", room)}: ${t("ch_sound_days")}. ${t("ch_sound_aria_days")}`;
  const top = 22;
  const bottom = 30;
  const right = 12;
  const height = 210;
  const { svg, width } = svgIn(host, height, summary);
  const narrow = width < 560;
  const y = d3
    .scaleLinear()
    .domain(levelDomain(series.flatMap((p) => [p.leq, p.p90])))
    .nice()
    .range([height - bottom, top]);
  const ticks = y.ticks(4);
  const tickW = textWidth(svg.append("g").attr("class", "axis"), ticks.map(fmt), "yt");
  svg.select("g.axis").remove();
  const left = Math.max(40, Math.ceil(tickW) + 10);
  const x = d3.scalePoint(days, [left, width - right]).padding(0.5);
  const step = x.step();

  // Special days (excursion, rotation): a soft band with its label above.
  const specials = days.map((d) => ({ d, label: specialOn(d, meta) })).filter((s) => s.label);
  const sg = svg.append("g").selectAll("g").data(specials).join("g");
  sg.append("rect")
    .attr("class", "special")
    .attr("x", (s) => x(s.d) - step / 2)
    .attr("width", step)
    .attr("y", top)
    .attr("height", height - bottom - top);
  sg.append("text")
    .attr("class", "special-label")
    // On a phone the labels of nearby special days would run into each other: alternate them
    // to the left and right of their band.
    .attr("x", (s, i) => x(s.d) + (narrow ? (i % 2 ? -step / 2 : step / 2) : 0))
    .attr("y", top - 7)
    .attr("text-anchor", (s, i) => (narrow ? (i % 2 ? "start" : "end")
      : x(s.d) > width * 0.75 ? "end" : x(s.d) < width * 0.25 ? "start" : "middle"))
    .text((s) => named(t, "label", s.label));

  svg
    .append("g")
    .attr("class", "grid")
    .selectAll("line")
    .data(ticks)
    .join("line")
    .attr("x1", left)
    .attr("x2", width - right)
    .attr("y1", (d) => y(d))
    .attr("y2", (d) => y(d));
  const ax = svg.append("g").attr("class", "axis");
  ax.selectAll(".yt")
    .data(ticks)
    .join("text")
    .attr("class", "yt")
    .attr("x", left - 6)
    .attr("y", (d) => y(d))
    .attr("dy", "0.35em")
    .attr("text-anchor", "end")
    .text(fmt);
  const every = Math.max(1, Math.ceil(days.length / Math.floor((width - left) / (narrow ? 34 : 64))));
  ax.selectAll(".xt")
    .data(days.filter((_, i) => i % every === 0))
    .join("text")
    .attr("class", "xt")
    .attr("x", (d) => x(d))
    .attr("y", height - bottom + 18)
    .attr("text-anchor", "middle")
    .text((d) => dayLabel(d, meta, lang, narrow));

  // A day the hall has no row for leaves a gap rather than a line across it.
  const byDay = new Map(series.map((p) => [p.day, p]));
  const slots = days.map((d) => byDay.get(d) ?? { day: d, leq: null, p90: null });
  const line = (key) =>
    d3
      .line()
      .defined((p) => finite(p[key]))
      .x((p) => x(p.day))
      .y((p) => y(p[key]));
  svg.append("path").attr("class", "expected").attr("d", line("p90")(slots));
  svg.append("path").attr("class", "line").attr("d", line("leq")(slots));
  svg
    .append("g")
    .selectAll("circle")
    .data(series)
    .join("circle")
    .attr("class", "point")
    .attr("cx", (p) => x(p.day))
    .attr("cy", (p) => y(p.leq))
    .attr("r", 4)
    .append("title")
    .text((p) => {
      const loud = p.p90 === null ? "" : ` · ${t("ch_sound_loud")}: ${fmt(p.p90)} ${unit}`;
      const hours = p.hours === null ? "" : ` · ${fmt(p.hours)} ${t("ch_sound_hours")}`;
      return `${dayLabel(p.day, meta, lang)}: ${fmt(p.leq)} ${unit}${loud}${hours}`;
    });
}

function kindChart(host, rows, { lang, t, room }) {
  const fmt = numberFormat(lang, 1);
  const unit = t("ch_sound_unit");
  const hoursText = (r) => (r.hours === null ? "" : `${fmt(r.hours)} ${t("ch_sound_hours")}`);
  const summary = `${named(t, "room", room)}: ${t("ch_sound_kinds")}. ${t("ch_sound_aria_kinds")}`;
  const rowH = 32;
  const top = 22;
  const bottom = 40;
  const height = top + rows.length * rowH + bottom;
  const { svg, width } = svgIn(host, height, summary);
  const names = rows.map((r) => named(t, "programme", r.programme));
  const labelW = Math.min(width * 0.4, textWidth(svg, names) + 14);
  const hoursW = textWidth(svg, rows.map(hoursText)) + 12;
  const right = 8;
  const x = d3
    .scaleLinear()
    .domain(levelDomain(rows.flatMap((r) => [r.leq, r.lo, r.hi])))
    .nice()
    .range([labelW, width - right - hoursW]);
  const ticks = x.ticks(Math.max(3, Math.min(6, Math.floor((width - labelW - hoursW) / 70))));

  svg
    .append("g")
    .attr("class", "grid")
    .selectAll("line")
    .data(ticks)
    .join("line")
    .attr("x1", (d) => x(d))
    .attr("x2", (d) => x(d))
    .attr("y1", top)
    .attr("y2", height - bottom);
  const ax = svg.append("g").attr("class", "axis").attr("transform", `translate(0,${height - bottom})`);
  ax.selectAll("text")
    .data(ticks)
    .join("text")
    .attr("x", (d) => x(d))
    .attr("y", 16)
    .attr("text-anchor", "middle")
    .text(fmt);
  ax.append("text")
    .attr("class", "axis-title")
    .attr("x", width - right - hoursW)
    .attr("y", 34)
    .attr("text-anchor", "end")
    .text(t("ch_sound_axis"));
  svg
    .append("g")
    .attr("class", "axis")
    .append("text")
    .attr("class", "axis-title")
    .attr("x", width - right)
    .attr("y", top - 8)
    .attr("text-anchor", "end")
    .text(t("ch_sound_recorded"));

  const g = svg
    .append("g")
    .selectAll("g")
    .data(rows)
    .join("g")
    .attr("transform", (_, i) => `translate(0,${top + i * rowH})`);
  g.append("text")
    .attr("class", "row-label")
    .attr("x", labelW - 10)
    .attr("y", rowH / 2)
    .attr("dy", "0.35em")
    .attr("text-anchor", "end")
    .each(function (_, i) {
      const node = d3.select(this).text(names[i]);
      const measure = (s) => {
        this.textContent = s;
        return this.getComputedTextLength?.() ?? s.length * 7.5;
      };
      const fit = fitLabel(names[i], labelW - 14, measure);
      node.text(fit);
      if (fit !== names[i]) node.append("title").text(names[i]);
    });
  const ranged = g.filter((r) => r.lo !== null && r.hi !== null);
  for (const cls of ["interval-halo", "interval"]) {
    ranged
      .append("line")
      .attr("class", cls)
      .attr("x1", (r) => x(r.lo))
      .attr("x2", (r) => x(r.hi))
      .attr("y1", rowH / 2)
      .attr("y2", rowH / 2);
  }
  g.append("circle")
    .attr("class", "estimate")
    .attr("cx", (r) => x(r.leq))
    .attr("cy", rowH / 2)
    .attr("r", 6)
    .append("title")
    .text((r, i) => {
      const mid = r.lo === null ? "" : ` (${fmt(r.lo)} – ${fmt(r.hi)})`;
      const hours = r.hours === null ? "" : ` · ${hoursText(r)}`;
      return `${names[i]}: ${fmt(r.leq)} ${unit}${mid}${hours}`;
    });
  g.append("text")
    .attr("class", "row-label")
    .attr("x", width - right)
    .attr("y", rowH / 2)
    .attr("dy", "0.35em")
    .attr("text-anchor", "end")
    .text(hoursText);
}

function legend(el, t) {
  const ul = document.createElement("ul");
  ul.className = "legend-inline";
  for (const [cls, key] of [
    ["line", "ch_sound_median"],
    ["expected", "ch_sound_loud"],
  ]) {
    const li = document.createElement("li");
    li.innerHTML = `<svg width="26" height="10" aria-hidden="true"><line class="${cls}" x1="1" x2="25" y1="5" y2="5"/></svg>`;
    const span = document.createElement("span");
    span.textContent = t(key);
    li.append(span);
    ul.append(li);
  }
  el.append(ul);
}

export function render(el, agg, t, opts = {}) {
  const lang = opts.lang?.() ?? "de";
  const meta = opts.meta ?? null;
  const days = allDays(agg?.sound_day);
  const draw = () => {
    el.replaceChildren();
    const perDay = ROOMS.map((room) => [room, soundDays(agg?.sound_day, room)]);
    const perKind = ROOMS.map((room) => [room, soundKinds(agg?.sound_kind, room)]);
    if (!perDay.some(([, s]) => s.length) && !perKind.some(([, s]) => s.length)) {
      emptyNote(el, t);
      return;
    }
    const dfig = block(el, t("ch_sound_days"));
    legend(dfig, t);
    for (const [room, series] of perDay) {
      const sub = document.createElement("div");
      sub.className = "viz-sub";
      const h = document.createElement("p");
      h.className = "viz-subtitle";
      h.textContent = named(t, "room", room);
      sub.append(h);
      dfig.append(sub);
      if (series.length) dayChart(sub, series, days, { meta, lang, t, room });
      else emptyNote(sub, t);
    }
    const kfig = block(el, t("ch_sound_kinds"));
    for (const [room, rows] of perKind) {
      const sub = document.createElement("div");
      sub.className = "viz-sub";
      const h = document.createElement("p");
      h.className = "viz-subtitle";
      h.textContent = named(t, "room", room);
      sub.append(h);
      kfig.append(sub);
      if (rows.length) kindChart(sub, rows, { lang, t, room });
      else emptyNote(sub, t);
    }
    caption(el, t("ch_sound_note"));
  };
  draw();
  onResize(el, draw);
}
