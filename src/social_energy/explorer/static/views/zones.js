// Where people are today: participants per zone over the current camp day, from the room tags.
// "Not placed" means the tag was heard but no room tag was heard often enough to place it.
import { zoneSeries } from "../model.js";

export function create(el, ctx) {
  const { meta } = ctx;
  const nZones = meta.zones.length;
  const keys = [...meta.zones, "not placed"];
  const svg = d3.select(el).append("svg").attr("width", "100%");
  const legend = d3.select(el).append("div").attr("class", "legend");
  let dayKey = -1;
  let rows = [];

  function compute(lo, hi) {
    const { counts, width } = zoneSeries(ctx.b, ctx.locZone, nZones, lo, hi);
    rows = d3.range(hi - lo).map((k) => {
      const row = { bin: lo + k };
      keys.forEach((key, z) => { row[key] = counts[k * width + z]; });
      return row;
    });
  }

  function update(state) {
    const c = ctx.colors;
    const bin = Math.floor(state.bin);
    const [lo, hi] = ctx.dayRange(ctx.dayOfBin[bin]);
    if (lo !== dayKey) { dayKey = lo; compute(lo, hi); }
    const width = el.clientWidth || 360;
    const height = 190;
    svg.attr("height", height);
    // Twelve-odd zones cannot each get a hue, so bands alternate two greys and the selected
    // (or hovered) zone is drawn in the accent; the list below names them, largest first.
    const color = (z) => (z === nZones ? c.rule : z === state.zone ? c.accent : z % 2 ? c.zoneLo : c.zoneHi);
    const x = d3.scaleLinear().domain([lo, hi]).range([30, width - 8]);
    const stack = d3.stack().keys(keys)(rows);
    const y = d3.scaleLinear().domain([0, d3.max(stack.at(-1) ?? [], (d) => d[1]) || 1]).nice().range([height - 20, 8]);
    svg.selectAll("*").remove();
    svg.append("g").attr("class", "axis").attr("transform", "translate(30,0)").call(d3.axisLeft(y).ticks(4).tickSize(3));
    const ticks = rows.filter((r) => r.bin % (ctx.binsPerHour * 3) === 0).map((r) => r.bin);
    svg.append("g").attr("class", "axis").attr("transform", `translate(0,${height - 20})`)
      .call(d3.axisBottom(x).tickValues(ticks).tickFormat((b) => ctx.clockLabel(b)).tickSize(3));
    svg.append("g").selectAll("path").data(stack).join("path")
      .attr("d", d3.area().x((d) => x(d.data.bin)).y0((d) => y(d[0])).y1((d) => y(d[1])))
      .attr("fill", (_, z) => color(z))
      .attr("stroke", c.surface).attr("stroke-width", 1)
      .attr("opacity", (_, z) => (state.zone === null || state.zone === z ? 1 : 0.3))
      .style("cursor", (_, z) => (z < nZones ? "pointer" : "default"))
      .on("click", (_, s) => {
        const z = keys.indexOf(s.key);
        if (z < nZones) ctx.set({ zone: state.zone === z ? null : z });
      })
      .on("mouseenter", (ev, s) => { if (keys.indexOf(s.key) < nZones) d3.select(ev.currentTarget).attr("fill", c.accent); })
      .on("mousemove", (ev, s) => {
        const b = Math.round(x.invert(d3.pointer(ev, svg.node())[0]));
        const row = rows[Math.max(0, Math.min(rows.length - 1, b - lo))];
        ctx.tip.show(`<b>${s.key}</b> at ${ctx.clockLabel(row.bin)}: ${row[s.key]} people` +
          (keys.indexOf(s.key) < nZones ? "<br><span class='muted'>click to show only them</span>" : ""),
          ev.clientX, ev.clientY);
      })
      .on("mouseleave", (ev, s) => { d3.select(ev.currentTarget).attr("fill", color(keys.indexOf(s.key))); ctx.tip.hide(); });
    svg.append("line").attr("class", "cursor").attr("x1", x(bin)).attr("x2", x(bin)).attr("y1", 8).attr("y2", height - 20);

    // Right now: zones ranked by people at the playhead, with direct labels.
    const now = rows[Math.max(0, Math.min(rows.length - 1, bin - lo))] ?? {};
    const ranked = keys.map((k, z) => ({ k, z, v: now[k] ?? 0 })).filter((d) => d.v > 0)
      .sort((a, b) => b.v - a.v);
    const total = d3.sum(ranked, (d) => d.v) || 1;
    legend.selectAll("span.item").data(ranked, (d) => d.k).join("span").attr("class", "item")
      .classed("dim", (d) => state.zone !== null && state.zone !== d.z)
      .html((d) => `<span class="swatch" style="border-radius:2px;width:${4 + Math.round(40 * d.v / total)}px;background:${d.z === state.zone ? c.accent : c.ink3}"></span>${d.k} ${d.v}`)
      .on("click", (_, d) => { if (d.z < nZones) ctx.set({ zone: state.zone === d.z ? null : d.z }); });
  }

  return { update };
}
