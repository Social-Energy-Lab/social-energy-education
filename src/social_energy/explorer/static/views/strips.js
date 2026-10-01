// Across the whole study: close ties per participant heard (one strip) and tags heard (another),
// with coverage problems shaded and day notes marked. Click to jump.
import { seenPerBin, tiesSeries } from "../model.js";

const STEP_MIN = 30;

export function create(el, ctx) {
  const { meta, nNodes, nBins } = ctx;
  const step = Math.max(1, Math.round((STEP_MIN * 60) / meta.bin_seconds));
  const seen = seenPerBin(ctx.b, nBins);
  const svg = d3.select(el).append("svg").attr("width", "100%");
  let key = "";
  let ties = new Float64Array(0);

  function update(state, p) {
    const k = `${p.windowBins}-${p.closeRssi}-${p.minBins}`;
    if (k !== key) {
      key = k;
      ties = tiesSeries(ctx.b, p, step, nNodes, nBins);
    }
    const c = ctx.colors;
    const width = el.clientWidth || 800;
    const rowH = 64;
    const height = 2 * rowH + 64;
    svg.attr("height", height);
    svg.selectAll("*").remove();
    const x = d3.scaleLinear().domain([0, nBins]).range([36, width - 8]);
    const rows = [
      { title: "close ties per participant heard", top: 26, data: Array.from(ties, (v, i) => [(i + 1) * step, v]) },
      { title: "tags heard", top: 26 + rowH + 18, data: Array.from(seen, (v, i) => [i, v]) },
    ];
    for (const s of meta.shade) {
      svg.append("rect").attr("x", x(s.start_bin)).attr("width", x(s.end_bin) - x(s.start_bin))
        .attr("y", 4).attr("height", height - 24).attr("fill", c.shade);
      svg.append("text").attr("x", (x(s.start_bin) + x(s.end_bin)) / 2).attr("y", height - 26)
        .attr("text-anchor", "middle").style("fill", c.ink3).style("font-size", "10px").text(s.label);
    }
    for (const r of rows) {
      const y = d3.scaleLinear().domain([0, d3.max(r.data, (d) => (Number.isNaN(d[1]) ? 0 : d[1])) || 1])
        .nice().range([r.top + rowH, r.top + 6]);
      svg.append("text").attr("x", 36).attr("y", r.top).text(r.title);
      svg.append("g").attr("class", "axis").attr("transform", "translate(36,0)").call(d3.axisLeft(y).ticks(2).tickSize(3));
      svg.append("path").attr("fill", "none").attr("stroke", c.accent).attr("stroke-width", 1.5)
        .attr("d", d3.line().defined((d) => !Number.isNaN(d[1])).x((d) => x(d[0])).y((d) => y(d[1]))(r.data));
    }
    const axisY = height - 20;
    svg.append("g").attr("class", "axis").attr("transform", `translate(0,${axisY})`)
      .call(d3.axisBottom(x).tickValues(meta.days.map((d) => d.start_bin)).tickFormat((b) => ctx.dayLabel(b).slice(0, 6)).tickSize(3));
    for (const n of meta.notes) {
      svg.append("circle").attr("cx", x((n.start_bin + n.end_bin) / 2)).attr("cy", 8).attr("r", 3.5)
        .attr("fill", c.glow).attr("stroke", c.ink3).attr("stroke-width", 0.5)
        .on("mousemove", (ev) => ctx.tip.show(n.text, ev.clientX, ev.clientY))
        .on("mouseleave", () => ctx.tip.hide());
    }
    const bin = Math.floor(state.bin);
    svg.append("line").attr("class", "cursor").attr("x1", x(bin)).attr("x2", x(bin)).attr("y1", 4).attr("y2", axisY);
    svg.append("rect").attr("x", 36).attr("y", 14).attr("width", width - 44).attr("height", axisY - 14)
      .attr("fill", "transparent").style("cursor", "pointer")
      .on("click", (ev) => ctx.set({ bin: Math.max(0, Math.min(nBins - 1, Math.round(x.invert(d3.pointer(ev)[0])))), playing: false }))
      .on("mousemove", (ev) => {
        const b = Math.max(0, Math.min(nBins - 1, Math.round(x.invert(d3.pointer(ev)[0]))));
        const t = ties[Math.floor(b / step)];
        ctx.tip.show(`${ctx.dayLabel(b)} ${ctx.clockLabel(b)}<br>` +
          `${Number.isNaN(t) || t === undefined ? "nobody heard" : `${t.toFixed(1)} close ties per participant`}<br>` +
          `${seen[b]} tags heard<br><span class="muted">click to jump here</span>`, ev.clientX, ev.clientY);
      })
      .on("mouseleave", () => ctx.tip.hide());
  }

  return { update };
}
