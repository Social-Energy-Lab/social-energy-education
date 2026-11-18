// How the halls sounded through the current camp day: one line per recorder, Leq per 5-minute
// bin, gaps where nothing was recorded, the playhead, and each level placed among that hall's own
// recorded time. Levels are relative to each recorder, so the halls are drawn on their own scales
// and never compared with each other. Click to jump.
import { louderThan } from "../model.js";

const ROW_H = 92;

export function create(el, ctx) {
  const { sound } = ctx;
  const svg = d3.select(el).append("svg").attr("width", "100%");

  function update(state) {
    const bin = Math.floor(state.bin);
    const [lo, hi] = ctx.dayRange(ctx.dayOfBin[bin]);
    const c = ctx.colors;
    const width = el.clientWidth || 800;
    const left = 4;
    const height = sound.rooms.length * ROW_H + 20;
    svg.attr("height", height);
    svg.selectAll("*").remove();
    const x = d3.scaleLinear().domain([lo, hi]).range([left, width - 4]);
    const colors = [c.accent, c.course[1] ?? c.ink2];

    sound.rooms.forEach((room, r) => {
      const top = r * ROW_H;
      const levels = sound.leq[r];
      // Each hall on its own scale: its recorded range over the whole study.
      const all = sound.sorted[r];
      const y = d3.scaleLinear()
        .domain(all.length ? [all[0], all[all.length - 1]] : [-80, -30])
        .range([top + ROW_H - 10, top + 20]);
      let recorded = 0;
      for (let k = lo; k < hi; k++) if (levels[k] !== null) recorded++;
      const now = levels[bin];
      const rank = now === null ? null : louderThan(all, now);
      svg.append("text").attr("x", left).attr("y", top + 12).attr("class", "sound-title")
        .text(`${room}: ${now === null ? "not recorded now" : `now louder than ${rank}% of its recorded time`}`);
      if (!recorded) {
        svg.append("text").attr("x", left).attr("y", top + 50).style("fill", c.ink3)
          .text("not recorded this day");
        return;
      }
      const line = d3.line().defined((k) => levels[k] !== null).x((k) => x(k + 0.5)).y((k) => y(levels[k]));
      svg.append("path").datum(d3.range(lo, hi)).attr("d", line).attr("fill", "none")
        .attr("stroke", colors[r % 2]).attr("stroke-width", 1.4);
      svg.append("line").attr("x1", left).attr("x2", width - 4).attr("y1", top + ROW_H - 10)
        .attr("y2", top + ROW_H - 10).attr("stroke", c.rule);
    });

    const ticks = d3.range(lo, hi, ctx.binsPerHour * 2);
    svg.append("g").attr("class", "axis").attr("transform", `translate(0,${sound.rooms.length * ROW_H})`)
      .call(d3.axisBottom(x).tickValues(ticks).tickFormat((b) => ctx.clockLabel(b)).tickSize(3));
    svg.append("line").attr("class", "cursor").attr("x1", x(bin + 0.5)).attr("x2", x(bin + 0.5))
      .attr("y1", 0).attr("y2", sound.rooms.length * ROW_H);

    svg.append("rect").attr("x", 0).attr("y", 0).attr("width", width).attr("height", height)
      .attr("fill", "transparent").style("cursor", "pointer")
      .on("mousemove", (ev) => {
        const [mx] = d3.pointer(ev);
        const k = Math.max(lo, Math.min(hi - 1, Math.floor(x.invert(mx))));
        const rows = sound.rooms.map((room, r) => {
          const v = sound.leq[r][k];
          return `${room}: ${v === null ? "<span class='muted'>not recorded</span>"
            : `${v.toFixed(1)} dBFS, louder than ${louderThan(sound.sorted[r], v)}% of its time`}`;
        });
        ctx.tip.show(`<b>${ctx.clockLabel(k)}</b><br>${rows.join("<br>")}<br><span class='muted'>click to jump here</span>`,
          ev.clientX, ev.clientY);
      })
      .on("mouseleave", () => ctx.tip.hide())
      .on("click", (ev) => {
        const [mx] = d3.pointer(ev);
        ctx.set({ bin: Math.max(lo, Math.min(hi - 1, Math.floor(x.invert(mx)))), playing: false });
      });
  }

  return { update };
}
