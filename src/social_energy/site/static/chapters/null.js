// Chapter: what we did not find. The pre-registered tests as a forest plot: a dot for each
// estimate, a line for its interval, and the no-effect line (0 for effects in standard
// deviations, 1 for rate ratios). The two scales get separate axes, never one shared one.
import {
  block,
  caption,
  emptyNote,
  finite,
  named,
  numberFormat,
  onResize,
  svgIn,
  textWidth,
} from "./chart.js";

export const NULL_AT = { sd: 0, rr: 1 };

/** confirmatory rows → [{test, label, estimate, lo, hi, scale, crossesNull}]; bad rows go. */
export function forestRows(rows) {
  return (rows ?? [])
    .filter(
      (r) =>
        Object.hasOwn(NULL_AT, r?.scale) && finite(r.estimate) && finite(r.lo) && finite(r.hi),
    )
    .map((r) => ({
      test: r.test ?? r.label,
      label: r.label ?? r.test,
      estimate: r.estimate,
      lo: r.lo,
      hi: r.hi,
      scale: r.scale,
      crossesNull: r.lo < NULL_AT[r.scale] && NULL_AT[r.scale] < r.hi,
    }));
}

/** The test's name from the copy (test_<id>), else the row's own label. */
function testName(t, r) {
  const own = named(t, "test", r.test);
  return own === String(r.test) ? String(r.label) : own;
}

function forest(host, rows, { scale, axis, noEffect, label, fmt, t }) {
  const top = 24;
  const bottom = 42;
  // Draw once to measure the labels: side labels when they fit in under half the width,
  // otherwise each label sits above its interval.
  const probe = svgIn(host, 10, label);
  const textW = textWidth(probe.svg, rows.map((r) => testName(t, r))) + 12;
  probe.svg.remove();
  const narrow = textW > probe.width * 0.45;
  const rowH = narrow ? 52 : 36;
  const labelW = narrow ? 0 : textW;
  const height = top + rows.length * rowH + bottom;
  const { svg, width } = svgIn(host, height, label);
  const right = 18;
  const left = labelW + 12;
  const nul = NULL_AT[scale];
  const lo = Math.min(nul, ...rows.map((r) => r.lo));
  const hi = Math.max(nul, ...rows.map((r) => r.hi));
  const log = scale === "rr" && lo > 0;
  const x = (log ? d3.scaleLog() : d3.scaleLinear())
    .domain(log ? [lo / 1.1, hi * 1.1] : [lo - (hi - lo) * 0.06, hi + (hi - lo) * 0.06])
    .range([left, width - right]);
  if (!log) x.nice();
  const ticks = log ? x.ticks(4).filter((_, i, a) => a.length <= 6 || i % 2 === 0) : x.ticks(5);
  const dotY = (i) => top + i * rowH + (narrow ? 34 : rowH / 2);

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
  svg
    .append("line")
    .attr("class", "reference")
    .attr("x1", x(nul))
    .attr("x2", x(nul))
    .attr("y1", top - 6)
    .attr("y2", height - bottom);
  const ax = svg.append("g").attr("class", "axis").attr("transform", `translate(0,${height - bottom})`);
  ax.selectAll("text")
    .data(ticks)
    .join("text")
    .attr("x", (d) => x(d))
    .attr("y", 16)
    .attr("text-anchor", "middle")
    .text((d) => fmt(d));
  ax.append("text")
    .attr("class", "axis-title")
    .attr("x", width - right)
    .attr("y", 34)
    .attr("text-anchor", "end")
    .text(axis);
  svg
    .append("text")
    .attr("class", "reference-label")
    .attr("x", x(nul))
    .attr("y", top - 10)
    .attr("text-anchor", x(nul) > width / 2 ? "end" : "start")
    .text(noEffect);

  const g = svg.append("g").selectAll("g").data(rows).join("g");
  g.append("text")
    .attr("class", "row-label")
    .attr("x", narrow ? left : labelW)
    .attr("y", (_, i) => (narrow ? top + i * rowH + 14 : dotY(i)))
    .attr("dy", narrow ? 0 : "0.35em")
    .attr("text-anchor", narrow ? "start" : "end")
    .text((r) => testName(t, r));
  if (narrow) {
    // A label above its interval sits on a backing in the surface colour, so the grid and the
    // no-effect line never run through the words.
    g.select("text").each(function () {
      const box = this.getBBox();
      d3.select(this.parentNode)
        .insert("rect", "text")
        .attr("class", "label-bg")
        .attr("x", box.x - 4)
        .attr("y", box.y - 1)
        .attr("width", box.width + 8)
        .attr("height", box.height + 2);
    });
  }
  g.append("line")
    .attr("class", "interval")
    .attr("x1", (r) => x(r.lo))
    .attr("x2", (r) => x(r.hi))
    .attr("y1", (_, i) => dotY(i))
    .attr("y2", (_, i) => dotY(i));
  g.append("circle")
    .attr("class", "estimate")
    .attr("cx", (r) => x(r.estimate))
    .attr("cy", (_, i) => dotY(i))
    .attr("r", 6)
    .append("title")
    .text((r) => `${testName(t, r)}: ${fmt(r.estimate)} (${fmt(r.lo)}–${fmt(r.hi)})`);
}

export function render(el, agg, t, opts = {}) {
  const fmt = numberFormat(opts.lang?.() ?? "de");
  const rows = forestRows(agg?.confirmatory);
  const draw = () => {
    el.replaceChildren();
    if (!rows.length) {
      emptyNote(el, t);
      return;
    }
    for (const [scale, axis] of [
      ["sd", t("ch_null_axis_sd")],
      ["rr", t("ch_null_axis_rr")],
    ]) {
      const part = rows.filter((r) => r.scale === scale);
      if (!part.length) continue;
      const fig = block(el, axis);
      forest(fig, part, {
        scale,
        axis,
        noEffect: t("ch_null_no_effect"),
        label: `${axis}. ${t("ch_null_aria")}`,
        fmt,
        t,
      });
    }
    caption(el, t("ch_null_note"));
  };
  draw();
  onResize(el, draw);
}
