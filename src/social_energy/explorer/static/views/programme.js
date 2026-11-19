// The programme of the current camp day: every item from the spine in lanes, all-camp items on
// top, with the playhead. The institutional setting the network and the self-reports happen in.
// Click an item to show only the people at it (model.itemMembers); click it again for everyone.
import { programmeLanes } from "../model.js";

const LANE_H = 17;
const MAX_LANES = 8;
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

// `maxLanes` keeps the strip short where it sits in the time bar.
export function create(el, ctx, { maxLanes = MAX_LANES } = {}) {
  const events = ctx.events;
  const svg = d3.select(el).append("svg").attr("width", "100%");
  const bar = document.createElement("div");
  bar.className = "item-filter";
  bar.hidden = true;
  el.append(bar);
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
    const shown = Math.min(lanes.lanes, maxLanes);
    const top = 4;
    const axisY = top + Math.max(1, shown) * LANE_H + 4;
    const height = axisY + 18;
    svg.attr("height", height);
    svg.selectAll("*").remove();
    const x = d3.scaleLinear().domain([lo, hi]).range([4, width - 4]);

    for (const it of lanes.items) {
      if (it.lane >= maxLanes) continue;
      const e = events[it.k];
      const x0 = x(it.start);
      const w = Math.max(2, x(it.end) - x0 - 1);
      const y = top + it.lane * LANE_H;
      const on = state.item === it.k;
      const filterable = ctx.itemsFull[it.k] !== null;
      const g = svg.append("g").style("cursor", "pointer")
        .style("opacity", state.item !== null && !on ? 0.45 : 1)
        .on("click", () => { ctx.tip.hide(); ctx.pickItem(it.k); })
        .on("mousemove", (ev) => ctx.tip.show(
          `<b>${esc(e.label)}</b><br>${esc(e.kind)} · ${e.all_camp ? "all camp" : `in ${esc(rooms(e)) || "rooms not logged"}`}<br>` +
          `${ctx.clockLabel(e.start_bin)}–${ctx.clockLabel(e.end_bin)}` +
          `${e.end_known ? "" : " (end filled with the kind's median)"}` +
          `<br><span class='muted'>${on ? "click to show everyone again"
            : filterable ? "click to show only the people at it"
            : e.all_camp ? "click to jump to it (whole camp: everyone)"
            : "click to jump to it (no room logged, so it cannot filter)"}</span>`, ev.clientX, ev.clientY))
        .on("mouseleave", () => ctx.tip.hide());
      g.append("rect").attr("x", x0).attr("y", y).attr("width", w).attr("height", LANE_H - 3)
        .attr("rx", 3).attr("fill", e.all_camp ? c.zoneHi : c.zoneLo)
        .attr("stroke", on ? c.ink1 : e.end_known ? "none" : c.ink3)
        .attr("stroke-width", on ? 2 : 1).attr("stroke-dasharray", on ? null : "2 2");
      if (w > 34) {
        g.append("text").attr("x", x0 + 4).attr("y", y + LANE_H - 7)
          .attr("class", e.all_camp ? "prog-label all" : "prog-label")
          .text(fit(e.label, w - 8));
      }
    }
    if (lanes.lanes > maxLanes) {
      const extra = lanes.items.filter((it) => it.lane >= maxLanes).length;
      more.textContent = `+${extra} more items at the same times; the frame lists what runs at the playhead.`;
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
    filterBar(state);
  }

  const rooms = (e) => e.locs.map((l) => ctx.meta.locations[l].label).join(", ");
  function filterBar(state) {
    bar.hidden = state.item === null;
    if (state.item === null) { bar.dataset.key = ""; return; }
    const e = events[state.item];
    const n = ctx.members ? ctx.members.reduce((s, v) => s + v, 0) : 0;
    const key = `${state.item}|${n}`;
    if (bar.dataset.key === key) return;
    bar.dataset.key = key;
    bar.innerHTML = `Showing only the <b>${n}</b> people at <b>${esc(e.label)}</b>
      <span class="muted">(${esc(rooms(e))}, ${ctx.clockLabel(e.start_bin)}–${ctx.clockLabel(e.end_bin)};
      placed there by their room tag for most of the item so far; lines count from the item's start)</span>
      <button type="button">Show everyone</button>`;
    bar.querySelector("button").addEventListener("click", () => ctx.set({ item: null }));
  }

  // Cut a label to fit `px` at about 6 px per character.
  function fit(text, px) {
    const n = Math.floor(px / 6);
    return text.length <= n ? text : `${text.slice(0, Math.max(1, n - 1))}…`;
  }

  return { update };
}
