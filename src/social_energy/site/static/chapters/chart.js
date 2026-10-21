// Shared drawing for the story chapters: an SVG as wide as its box (so text stays readable at
// phone width), number formats in the page language, the "not enough data" note, labels looked
// up in the copy, and marks that grow once they scroll into view. Colour comes from the CSS
// tokens through classes in style.css, so both themes work without redrawing.
//
// D3 is the global `d3` (vendor/d3.min.js, loaded by index.html). Nothing here touches the DOM
// or d3 at import time, so the chapters' pure helpers can be tested under node.

export const finite = (v) => typeof v === "number" && Number.isFinite(v);

export const slug = (s) =>
  String(s)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_|_$/g, "");

/** `t("<prefix>_<slug(name)>")`, or `name` itself when the copy has no such key. */
export function named(t, prefix, name) {
  const key = `${prefix}_${slug(name)}`;
  const text = t(key);
  return text === key ? String(name) : text;
}

/** The leading number of a band such as "10-30", "5+" or "60"; Infinity when there is none. */
export function bandStart(band) {
  const m = String(band).match(/-?\d+(?:\.\d+)?/);
  return m ? Number(m[0]) : Infinity;
}

/** A number formatter for the page language. */
export function numberFormat(lang, digits = 2) {
  const fmt = new Intl.NumberFormat(lang, { maximumFractionDigits: digits });
  return (v) => (finite(v) ? fmt.format(v) : "–");
}

/** The quiet note a chart shows when its section is empty (small-cell rows are dropped). */
export function emptyNote(el, t) {
  const p = document.createElement("p");
  p.className = "pending";
  p.textContent = t("chart_empty");
  el.append(p);
}

/** A caption under a chart, in the page's muted ink. */
export function caption(el, text) {
  const p = document.createElement("p");
  p.className = "chart-note";
  p.textContent = text;
  el.append(p);
  return p;
}

/** A titled block inside a chart container; returns the block. */
export function block(el, title) {
  const fig = document.createElement("figure");
  fig.className = "viz";
  if (title) {
    const cap = document.createElement("figcaption");
    cap.textContent = title;
    fig.append(cap);
  }
  el.append(fig);
  return fig;
}

/** An SVG of the block's width (at least 280) and `height`, with a role and a summary. */
export function svgIn(host, height, label) {
  const width = Math.max(280, Math.round(host.clientWidth || host.parentElement?.clientWidth || 640));
  const svg = d3
    .select(host)
    .append("svg")
    .attr("viewBox", `0 0 ${width} ${height}`)
    .attr("width", "100%")
    .attr("role", "img")
    .attr("aria-label", label);
  return { svg, width };
}

/** The widest of `texts` drawn with `cls` in `svg`, in px (rendered, then removed). */
export function textWidth(svg, texts, cls = "row-label") {
  const probe = svg.append("text").attr("class", cls);
  let max = 0;
  for (const s of texts) {
    probe.text(s);
    max = Math.max(max, probe.node().getComputedTextLength?.() ?? String(s).length * 7.5);
  }
  probe.remove();
  return max;
}

/**
 * Re-run the chapter's draw when its box changes width (rotation, resize). One observer per
 * container; the latest draw wins, so a language switch does not stack observers.
 */
export function onResize(el, draw) {
  el._seeDraw = draw;
  if (el._seeObserver || typeof ResizeObserver === "undefined") return;
  let width = el.clientWidth;
  el._seeObserver = new ResizeObserver(() => {
    const w = el.clientWidth;
    if (Math.abs(w - width) < 8) return;
    width = w;
    el._seeDraw?.();
  });
  el._seeObserver.observe(el);
}

/**
 * Call `grow(instant)` once `target` (default `el`) is on screen: at once and without a
 * transition under reduced motion, without IntersectionObserver, or when the chapter `el` has
 * grown before (a redraw after a resize or a language switch).
 */
export function whenSeen(el, reduced, grow, target = el) {
  if (reduced || el.dataset.seen === "1" || typeof IntersectionObserver === "undefined") {
    el.dataset.seen = "1";
    grow(true);
    return;
  }
  const io = new IntersectionObserver(
    (entries) => {
      if (!entries.some((e) => e.isIntersecting)) return;
      io.disconnect();
      el.dataset.seen = "1";
      grow(false);
    },
    { threshold: 0.25 },
  );
  io.observe(target);
}

export const GROW_MS = 700;

/**
 * Horizontal bars with intervals. rows: [{name, value, lo, hi, tip}]. opts: label (summary),
 * axis (title), tick (formats a tick), refAt (a reference line's value, or null), reference
 * (its label), reduced, el (the chapter, for the scroll-in growth).
 */
export function hbars(host, rows, { label, axis, tick, refAt = null, reference, reduced, el }) {
  const rowH = 34;
  const top = refAt !== null && reference ? 24 : 8;
  const bottom = 40;
  const height = top + rows.length * rowH + bottom;
  const { svg, width } = svgIn(host, height, label);
  const labelW = Math.min(width * 0.45, textWidth(svg, rows.map((r) => r.name)) + 14);
  const right = 16;
  const max = d3.max(rows, (r) => Math.max(r.value, finite(r.hi) ? r.hi : r.value)) ?? 1;
  const x = d3
    .scaleLinear()
    .domain([0, Math.max(refAt === null ? 0 : refAt * 1.2, max * 1.05) || 1])
    .nice()
    .range([labelW, width - right]);
  const y = (i) => top + i * rowH;
  const ticks = x.ticks(Math.max(3, Math.min(6, Math.floor((width - labelW) / 70))));

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
    .text(tick);
  ax.append("text")
    .attr("class", "axis-title")
    .attr("x", width - right)
    .attr("y", 34)
    .attr("text-anchor", "end")
    .text(axis);

  const g = svg
    .append("g")
    .selectAll("g")
    .data(rows)
    .join("g")
    .attr("transform", (_, i) => `translate(0,${y(i)})`);
  g.append("text")
    .attr("class", "row-label")
    .attr("x", labelW - 10)
    .attr("y", rowH / 2)
    .attr("dy", "0.35em")
    .attr("text-anchor", "end")
    .text((r) => r.name);
  const bars = g
    .append("rect")
    .attr("class", "bar")
    .attr("x", x(0))
    .attr("y", 7)
    .attr("height", rowH - 14)
    .attr("rx", 3)
    .attr("width", 0);
  bars.append("title").text((r) => r.tip);
  const whisk = g
    .filter((r) => finite(r.lo) && finite(r.hi))
    .append("line")
    .attr("class", "interval")
    .attr("x1", (r) => x(r.lo))
    .attr("x2", (r) => x(r.hi))
    .attr("y1", rowH / 2)
    .attr("y2", rowH / 2)
    .attr("opacity", 0);

  if (refAt !== null) {
    svg
      .append("line")
      .attr("class", "reference")
      .attr("x1", x(refAt))
      .attr("x2", x(refAt))
      .attr("y1", top - 6)
      .attr("y2", height - bottom);
    if (reference) {
      svg
        .append("text")
        .attr("class", "reference-label")
        .attr("x", x(refAt))
        .attr("y", top - 10)
        .attr("text-anchor", x(refAt) > width / 2 ? "end" : "start")
        .text(reference);
    }
  }

  whenSeen(
    el,
    reduced,
    (instant) => {
      const w = (r) => Math.max(0, x(r.value) - x(0));
      if (instant) {
        bars.attr("width", w);
        whisk.attr("opacity", 1);
        return;
      }
      bars
        .transition()
        .duration(GROW_MS)
        .delay((_, i) => i * 80)
        .ease(d3.easeCubicOut)
        .attr("width", w);
      whisk.transition().delay(GROW_MS).duration(300).attr("opacity", 1);
    },
    host,
  );
}

/** A day as the page shows it: an index into meta.days or an ISO date, else as it is. */
export function dayLabel(day, meta, lang, narrow = false) {
  const opts = narrow ? { day: "numeric" } : { weekday: "short", day: "numeric" };
  const m = metaDay(day, meta);
  if (m) {
    const at = new Date(Date.parse(meta.t0) + m.start_bin * meta.bin_seconds * 1000);
    return new Intl.DateTimeFormat(lang, { ...opts, timeZone: meta.timezone }).format(at);
  }
  if (typeof day === "string" && /^\d{4}-\d{2}-\d{2}$/.test(day)) {
    const at = new Date(`${day}T12:00:00Z`);
    return new Intl.DateTimeFormat(lang, { ...opts, timeZone: "UTC" }).format(at);
  }
  return String(day);
}

/** The local date (YYYY-MM-DD) of `bin` in the camp's time zone. */
export function localDate(meta, bin) {
  const at = new Date(Date.parse(meta.t0) + bin * meta.bin_seconds * 1000);
  return new Intl.DateTimeFormat("en-CA", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    timeZone: meta.timezone,
  }).format(at);
}

/** The meta.days entry a row's day refers to: by index, or by local date; else null. */
export function metaDay(day, meta) {
  const days = meta?.days ?? [];
  if (typeof day === "number") return days.find((d) => d.index === day) ?? null;
  if (typeof day === "string" && meta?.t0) {
    return days.find((d) => localDate(meta, d.start_bin) === day) ?? null;
  }
  return null;
}

/** Sort key for a day: its index or its ISO date, both order correctly. */
export const dayOrder = (a, b) => (a < b ? -1 : a > b ? 1 : 0);

/** A phase as the page shows it: an index into meta.phases or a name, through phase_<name>. */
export function phaseLabel(phase, meta, t) {
  const name = typeof phase === "number" ? (meta?.phases?.[phase] ?? String(phase)) : phase;
  return named(t, "phase", name);
}
