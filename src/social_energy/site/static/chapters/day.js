// Chapter: a day at the academy. A heatmap with a row per day and a column per time of day; the
// colour shows either how many others someone had close by on average, or the share of people
// who were close to no one. A toggle switches between the two; the choice survives a redraw.
import {
  block,
  caption,
  dayLabel,
  dayOrder,
  emptyNote,
  finite,
  numberFormat,
  onResize,
  phaseLabel,
  svgIn,
  textWidth,
} from "./chart.js";

export const MEASURES = ["others", "share_no_one"];

/** day_phase rows → [{day, phase, value}] for `value`; rows without a finite value go. */
export function heatCells(rows, value) {
  return (rows ?? [])
    .filter((r) => finite(r?.[value]))
    .map((r) => ({ day: r.day, phase: r.phase, value: r[value] }));
}

/** Phases in the camp's order: meta.phases for names, numeric order for indices. */
function phaseOrder(phases, meta) {
  const known = meta?.phases ?? [];
  const rank = (p) => {
    if (typeof p === "number") return p;
    const i = known.indexOf(p);
    return i < 0 ? known.length + phases.indexOf(p) : i;
  };
  return [...phases].sort((a, b) => rank(a) - rank(b));
}

function heatmap(host, cells, { measure, meta, lang, t }) {
  const days = [...new Set(cells.map((c) => c.day))].sort(dayOrder);
  const phases = phaseOrder([...new Set(cells.map((c) => c.phase))], meta);
  const share = measure === "share_no_one";
  const fmt = numberFormat(lang, share ? 0 : 1);
  const show = (v) => (share ? `${fmt(v)} %` : fmt(v));
  const summary = `${t(share ? "ch_day_show_alone" : "ch_day_show_others")}. ${t("ch_day_aria")}`;

  const probe = svgIn(host, 10, summary);
  const narrow = probe.width < 560;
  const dayNames = days.map((d) => dayLabel(d, meta, lang));
  const phaseNames = phases.map((p) => phaseLabel(p, meta, t));
  const labelW = textWidth(probe.svg, dayNames) + 12;
  const headW = textWidth(probe.svg, phaseNames);
  probe.svg.remove();

  const cellH = narrow ? 30 : 34;
  // Column heads slant when they would not fit across; a slanted head reaches about
  // cos 40° of its length to the right of its column's centre.
  const slant = headW > 0 && phaseNames.length * (headW + 8) > probe.width - labelW - 4;
  const right = slant ? Math.max(4, Math.round(headW * 0.77 - 16)) : 4;
  const top = slant ? Math.round(headW * 0.7) + 14 : 26;
  const height = top + days.length * cellH + 4;
  const { svg, width } = svgIn(host, height, summary);
  const x = d3.scaleBand(phases, [labelW, width - right]).paddingInner(0.06);
  const y = d3.scaleBand(days, [top, top + days.length * cellH]).paddingInner(0.08);
  const [lo, hi] = d3.extent(cells, (c) => c.value);
  const level = (v) => (hi > lo ? (v - lo) / (hi - lo) : 0.5);
  const opacity = (v) => 0.1 + 0.9 * level(v);

  const heads = svg.append("g").attr("class", "axis");
  heads
    .selectAll("text")
    .data(phases)
    .join("text")
    .attr("class", "row-label")
    .attr("transform", (p) => {
      const cx = x(p) + x.bandwidth() / 2;
      return slant ? `translate(${cx + 4},${top - 8}) rotate(-40)` : `translate(${cx},${top - 10})`;
    })
    .attr("text-anchor", slant ? "start" : "middle")
    .text((_, i) => phaseNames[i]);
  svg
    .append("g")
    .selectAll("text")
    .data(days)
    .join("text")
    .attr("class", "row-label")
    .attr("x", labelW - 10)
    .attr("y", (d) => y(d) + y.bandwidth() / 2)
    .attr("dy", "0.35em")
    .attr("text-anchor", "end")
    .text((_, i) => dayNames[i]);

  const byKey = new Map(cells.map((c) => [`${c.day}|${c.phase}`, c]));
  const slots = days.flatMap((d) => phases.map((p) => ({ day: d, phase: p })));
  const g = svg
    .append("g")
    .selectAll("g")
    .data(slots)
    .join("g")
    .attr("transform", (s) => `translate(${x(s.phase)},${y(s.day)})`);
  g.each(function (s) {
    const node = d3.select(this);
    const c = byKey.get(`${s.day}|${s.phase}`);
    const w = x.bandwidth();
    const h = y.bandwidth();
    if (!c) {
      node.append("rect").attr("class", "cell-empty").attr("width", w).attr("height", h).attr("rx", 3);
      return;
    }
    const rect = node
      .append("rect")
      .attr("class", "cell")
      .attr("width", w)
      .attr("height", h)
      .attr("rx", 3)
      .attr("fill-opacity", opacity(c.value));
    rect
      .append("title")
      .text(`${dayNames[days.indexOf(s.day)]}, ${phaseNames[phases.indexOf(s.phase)]}: ${show(c.value)}`);
    if (w >= 30) {
      node
        .append("text")
        .attr("class", `cell-text${opacity(c.value) > 0.65 ? " strong" : ""}`)
        .attr("x", w / 2)
        .attr("y", h / 2)
        .attr("dy", "0.35em")
        .attr("text-anchor", "middle")
        .attr("font-size", w < 44 ? 10.5 : 12)
        .text(show(c.value));
    }
  });
}

export function render(el, agg, t, opts = {}) {
  const lang = opts.lang?.() ?? "de";
  const meta = opts.meta ?? null;
  const rows = agg?.day_phase;
  const draw = () => {
    el.replaceChildren();
    const measure = MEASURES.includes(el.dataset.measure) ? el.dataset.measure : "others";
    const toggle = document.createElement("div");
    toggle.className = "toggle";
    toggle.setAttribute("role", "group");
    toggle.setAttribute("aria-label", t("ch_day_toggle"));
    for (const [m, key] of [
      ["others", "ch_day_show_others"],
      ["share_no_one", "ch_day_show_alone"],
    ]) {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = t(key);
      b.setAttribute("aria-pressed", String(m === measure));
      b.addEventListener("click", () => {
        el.dataset.measure = m;
        draw();
        // The redraw replaced the buttons; keep the keyboard where it was.
        el.querySelector('.toggle [aria-pressed="true"]')?.focus();
      });
      toggle.append(b);
    }
    const cells = heatCells(rows, measure);
    if (!heatCells(rows, "others").length && !heatCells(rows, "share_no_one").length) {
      emptyNote(el, t);
      return;
    }
    el.append(toggle);
    const fig = block(el, t(measure === "others" ? "ch_day_show_others" : "ch_day_show_alone"));
    if (!cells.length) {
      emptyNote(fig, t);
      return;
    }
    heatmap(fig, cells, { measure, meta, lang, t });
    caption(el, t("ch_day_legend"));
  };
  draw();
  onResize(el, draw);
}
