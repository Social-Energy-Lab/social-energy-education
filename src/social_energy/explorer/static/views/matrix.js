// How courses mix: share of the window's ties per course pair, and the cross-course share over
// the day against what random mixing among the people heard would give.
import { edges, mixing, randomCrossShare, suppress, visible } from "../model.js";

const STEP_MIN = 30;

export function create(el, ctx) {
  const { meta, nodeCourse, nNodes } = ctx;
  const nCourses = meta.courses.length;
  const groups = d3.range(nCourses + (ctx.hasUnknown ? 1 : 0));
  const label = (gi) => (gi === nCourses ? "?" : meta.courses[gi].key);
  const fullName = (gi) => (gi === nCourses ? "course not known" : meta.courses[gi].name);
  const svg = d3.select(el).append("svg").attr("width", "100%");
  const grid = svg.append("g");
  const line = svg.append("g");
  const note = d3.select(el).append("div").attr("class", "empty-note");
  let dayKey = "";
  let series = [];

  function daySeries(state, p) {
    const bin = Math.floor(state.bin);
    const [lo, hi] = ctx.dayRange(ctx.dayOfBin[bin]);
    const key = `${lo}-${p.windowBins}-${p.closeRssi}-${p.minBins}`;
    if (key === dayKey) return;
    dayKey = key;
    const step = Math.max(1, Math.round((STEP_MIN * 60) / meta.bin_seconds));
    series = [];
    for (let end = lo + step; end <= hi; end += step) {
      const q = { ...p, endBin: end };
      const vis = visible(ctx.b, end, p.windowBins, nNodes);
      series.push({
        bin: end - 1,
        cross: mixing(edges(ctx.b, q), nodeCourse, nCourses).crossShare,
        random: randomCrossShare(vis, nodeCourse, nCourses),
      });
    }
    series.lo = lo;
    series.hi = hi;
  }

  function update(state, p, e) {
    const c = ctx.colors;
    const width = el.clientWidth || 360;
    const cell = Math.min(40, Math.floor((width - 40) / groups.length));
    const gridH = cell * groups.length + 24;
    const lineH = 120;
    svg.attr("height", gridH + lineH + 30);

    const mix = mixing(e, nodeCourse, nCourses);
    const n = nCourses + 1;
    const vis = visible(ctx.b, p.endBin, p.windowBins, nNodes);
    const seen = groups.map((gi) => nodeCourse.filter((x, i) => vis[i] && (x < 0 ? nCourses : x) === gi).length);
    const max = d3.max(groups.flatMap((i) => groups.map((j) => mix.counts[i * n + j]))) || 1;
    const fill = d3.interpolateLab(c.seqLo, c.seqHi);
    const cells = groups.flatMap((i) => groups.map((j) => ({ i, j, v: mix.counts[i * n + j] })))
      .filter((d) => d.j >= d.i);

    grid.attr("transform", "translate(40, 18)");
    const sel = grid.selectAll("g.cell").data(cells, (d) => `${d.i}-${d.j}`);
    const enter = sel.enter().append("g").attr("class", "cell").style("cursor", "pointer");
    enter.append("rect").attr("rx", 3);
    enter.append("text").attr("text-anchor", "middle").attr("dominant-baseline", "central");
    const all = enter.merge(sel);
    all.attr("transform", (d) => `translate(${d.j * cell}, ${d.i * cell})`);
    all.select("rect")
      .attr("width", cell - 2).attr("height", cell - 2)
      .attr("fill", (d) => (seen[d.i] < meta.min_group || seen[d.j] < meta.min_group ? c.rule : fill(d.v / max)))
      .attr("stroke", (d) => (state.cell && state.cell[0] === d.i && state.cell[1] === d.j ? c.ink1 : "none"))
      .attr("stroke-width", 2);
    all.select("text")
      .attr("x", (cell - 2) / 2).attr("y", (cell - 2) / 2)
      .style("fill", (d) => (d.v / max > 0.55 ? c.surface : c.ink2))
      .text((d) => {
        if (seen[d.i] < meta.min_group || seen[d.j] < meta.min_group) return suppress(0, meta.min_group);
        return mix.total ? `${Math.round((100 * d.v) / mix.total)}` : "";
      });
    all.on("click", (_, d) => {
      const same = state.cell && state.cell[0] === d.i && state.cell[1] === d.j;
      ctx.set({ cell: same ? null : [d.i, d.j] });
    }).on("mousemove", (ev, d) => {
      ctx.tip.show(
        `<b>${fullName(d.i)}</b> – <b>${fullName(d.j)}</b><br>${d.v} ties` +
        (mix.total ? ` (${Math.round((100 * d.v) / mix.total)}% of ${mix.total})` : "") +
        `<br><span class="muted">click to highlight these ties</span>`, ev.clientX, ev.clientY);
    }).on("mouseleave", () => ctx.tip.hide());
    sel.exit().remove();

    const labels = grid.selectAll("text.lab").data(groups.flatMap((gi) => [["r", gi], ["c", gi]]));
    labels.enter().append("text").attr("class", "lab").merge(labels)
      .attr("x", ([k, gi]) => (k === "r" ? -6 : gi * cell + (cell - 2) / 2))
      .attr("y", ([k, gi]) => (k === "r" ? gi * cell + (cell - 2) / 2 : -6))
      .attr("text-anchor", ([k]) => (k === "r" ? "end" : "middle"))
      .attr("dominant-baseline", ([k]) => (k === "r" ? "central" : "auto"))
      .text(([, gi]) => label(gi));
    note.text(mix.total ? `% of ${mix.total} ties in the window · grey: fewer than ${meta.min_group} people heard` : "No ties in this window");

    // Cross-course share over the day.
    daySeries(state, p);
    const top = gridH + 22;
    const x = d3.scaleLinear().domain([series.lo, series.hi]).range([40, width - 8]);
    const y = d3.scaleLinear().domain([0, 1]).range([top + lineH, top]);
    line.selectAll("*").remove();
    line.append("text").attr("x", 40).attr("y", top - 6).text("share of ties across courses today");
    line.append("g").attr("class", "axis").attr("transform", "translate(40,0)")
      .call(d3.axisLeft(y).ticks(3).tickFormat(d3.format(".0%")).tickSize(3));
    const path = (key) => d3.line().defined((d) => d[key] !== null).x((d) => x(d.bin)).y((d) => y(d[key]))(series);
    line.append("path").attr("d", path("random")).attr("fill", "none")
      .attr("stroke", c.ink3).attr("stroke-dasharray", "4 3").attr("stroke-width", 1.5);
    line.append("path").attr("d", path("cross")).attr("fill", "none")
      .attr("stroke", c.accent).attr("stroke-width", 2);
    const last = series.filter((d) => d.random !== null).at(-1);
    if (last) {
      line.append("text").attr("x", x(last.bin) - 2).attr("y", y(last.random) - 5)
        .attr("text-anchor", "end").style("fill", c.ink3).text("if people mixed at random");
    }
    const bin = Math.floor(state.bin);
    line.append("line").attr("class", "cursor").attr("x1", x(bin)).attr("x2", x(bin))
      .attr("y1", top).attr("y2", top + lineH);
  }

  return { update };
}
