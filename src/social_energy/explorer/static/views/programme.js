// The programme of the current camp day: every item from the spine in lanes, all-camp items on
// top, with the playhead. The institutional setting the network and the self-reports happen in.
// Click an item to jump to its start.
import { programmeLanes } from "../model.js";

const LANE_H = 17;
const MAX_LANES = 8;
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

export function create(el, ctx) {
  const events = ctx.events;
  const svg = d3.select(el).append("svg").attr("width", "100%");
  const more = document.createElement("p");
  more.className = "muted small";
  el.append(more);
  let dayKey = null;
  let lanes = null;

  function update(state) {
    const bin = Math.floor(state.bin);
    const day = ctx.dayOfBin[bin];
    const [lo, hi] = ctx.dayRange(day);
    if (day !== dayKey) {
      dayKey = day;
      lanes = programmeLanes(events, lo, hi);
    }
    const c = ctx.colors;
    const width = el.clientWidth || 800;
    const shown = Math.min(lanes.lanes, MAX_LANES);
    const top = 4;
    const axisY = top + Math.max(1, shown) * LANE_H + 4;
    const height = axisY + 18;
    svg.attr("height", height);
    svg.selectAll("*").remove();
    const x = d3.scaleLinear().domain([lo, hi]).range([4, width - 4]);

    for (const it of lanes.items) {
      if (it.lane >= MAX_LANES) continue;
      const e = events[it.k];
      const x0 = x(it.start);
      const w = Math.max(2, x(it.end) - x0 - 1);
      const y = top + it.lane * LANE_H;
      const g = svg.append("g").style("cursor", "pointer")
        .on("click", () => ctx.set({ bin: it.start, playing: false }))
        .on("mousemove", (ev) => ctx.tip.show(
          `<b>${esc(e.label)}</b><br>${esc(e.kind)} · ${e.all_camp ? "all camp" : "in its rooms"}<br>` +
          `${ctx.clockLabel(e.start_bin)}–${ctx.clockLabel(e.end_bin)}` +
          `${e.end_known ? "" : " (end filled with the kind's median)"}` +
          "<br><span class='muted'>click to jump to its start</span>", ev.clientX, ev.clientY))
        .on("mouseleave", () => ctx.tip.hide());
      g.append("rect").attr("x", x0).attr("y", y).attr("width", w).attr("height", LANE_H - 3)
        .attr("rx", 3).attr("fill", e.all_camp ? c.zoneHi : c.zoneLo)
        .attr("stroke", e.end_known ? "none" : c.ink3).attr("stroke-dasharray", "2 2");
      if (w > 34) {
        g.append("text").attr("x", x0 + 4).attr("y", y + LANE_H - 7)
          .attr("class", e.all_camp ? "prog-label all" : "prog-label")
          .text(fit(e.label, w - 8));
      }
    }
    if (lanes.lanes > MAX_LANES) {
      const extra = lanes.items.filter((it) => it.lane >= MAX_LANES).length;
      more.textContent = `+${extra} more items at the same times; the frame below lists what runs at the playhead.`;
    } else {
      more.textContent = "";
    }
    if (!lanes.items.length) {
      svg.append("text").attr("x", 8).attr("y", top + 12).style("fill", c.ink3)
        .text("No programme item recorded for this day");
    }
    const ticks = d3.range(lo, hi, ctx.binsPerHour * 2);
    svg.append("g").attr("class", "axis").attr("transform", `translate(0,${axisY})`)
      .call(d3.axisBottom(x).tickValues(ticks).tickFormat((b) => ctx.clockLabel(b)).tickSize(3));
    svg.append("line").attr("class", "cursor").attr("x1", x(bin)).attr("x2", x(bin))
      .attr("y1", 0).attr("y2", axisY);
  }

  // Cut a label to fit `px` at about 6 px per character.
  function fit(text, px) {
    const n = Math.floor(px / 6);
    return text.length <= n ? text : `${text.slice(0, Math.max(1, n - 1))}…`;
  }

  return { update };
}
