// How the halls sounded: across the whole camp (or one day), one block per recorder. In each, the
// loudness (Leq per 5-minute bin) and, under it, the frequency mix: the share of the sound's power
// below 300 Hz, in the voice range (300-4000 Hz) and above 4000 Hz (model.soundMix). Gaps are not
// recorded. Levels are relative to each recorder, so each hall is drawn on its own scale: days can
// be compared within a hall (same recorder), the two halls only by the shape over time. Click to
// jump.
import { louderThan, soundMix } from "../model.js";

const LEVEL_H = 70;
const MIX_H = 34;
const ROOM_H = 16 + LEVEL_H + 6 + MIX_H + 14;
const MIX_NAMES = ["below 300 Hz", "voice range 300–4000 Hz", "above 4000 Hz"];

export function create(el, ctx) {
  const { sound, meta } = ctx;
  sound.mix = sound.bands ? sound.bands.db.map((row) => row.map(soundMix)) : null;
  let span = "camp"; // "camp": the whole study; "day": the playhead's camp day
  const bar = document.createElement("div");
  bar.className = "seg";
  bar.innerHTML = `<button type="button" data-span="camp" aria-pressed="true">Whole camp</button>
    <button type="button" data-span="day" aria-pressed="false">This day</button>`;
  el.append(bar);
  for (const btn of bar.querySelectorAll("button")) {
    btn.addEventListener("click", () => {
      span = btn.dataset.span;
      for (const b2 of bar.querySelectorAll("button")) b2.setAttribute("aria-pressed", String(b2 === btn));
      ctx.set({});
    });
  }
  const svg = d3.select(el).append("svg").attr("width", "100%");

  function update(state) {
    const bin = Math.floor(state.bin);
    const [lo, hi] = span === "day" ? ctx.dayRange(ctx.dayOfBin[bin]) : [0, ctx.nBins];
    const c = ctx.colors;
    const mixColors = [c.ink3, c.accent, c.glow];
    const width = el.clientWidth || 800;
    const left = 22; // room for the first day label
    const legendH = sound.mix ? 18 : 0;
    const top0 = legendH;
    const height = top0 + sound.rooms.length * ROOM_H + 20;
    svg.attr("height", height);
    svg.selectAll("*").remove();
    const x = d3.scaleLinear().domain([lo, hi]).range([left, width - 4]);
    const axisY = top0 + sound.rooms.length * ROOM_H;

    if (sound.mix) {
      const lg = svg.append("g").attr("transform", `translate(${left},4)`);
      let lx = 0;
      MIX_NAMES.forEach((t, k) => {
        lg.append("rect").attr("x", lx).attr("y", 0).attr("width", 10).attr("height", 10).attr("fill", mixColors[k]);
        const txt = lg.append("text").attr("x", lx + 14).attr("y", 9).text(t);
        lx += 14 + (txt.node().getComputedTextLength?.() || t.length * 6) + 16;
      });
    }
    // The playhead's day, shaded in the whole-camp view.
    if (span === "camp") {
      const [dlo, dhi] = ctx.dayRange(ctx.dayOfBin[bin]);
      svg.append("rect").attr("x", x(dlo)).attr("width", Math.max(1, x(dhi) - x(dlo)))
        .attr("y", top0).attr("height", axisY - top0).attr("fill", c.shade);
    }

    sound.rooms.forEach((room, r) => {
      const top = top0 + r * ROOM_H;
      const levels = sound.leq[r];
      const all = sound.sorted[r];
      const y = d3.scaleLinear()
        .domain(all.length ? [all[0], all[all.length - 1]] : [-80, -30])
        .range([top + 16 + LEVEL_H, top + 18]);
      let recorded = 0;
      for (let k = lo; k < hi; k++) if (levels[k] !== null) recorded++;
      const now = levels[bin];
      const rank = now === null ? null : louderThan(all, now);
      svg.append("text").attr("x", left).attr("y", top + 12).attr("class", "sound-title")
        .text(`${room}: ${now === null ? "not recorded now" : `now louder than ${rank}% of its recorded time`}`);
      if (!recorded) {
        svg.append("text").attr("x", left).attr("y", top + 50).style("fill", c.ink3)
          .text(span === "day" ? "not recorded this day" : "not recorded");
        return;
      }
      const ks = d3.range(lo, hi);
      const line = d3.line().defined((k) => levels[k] !== null).x((k) => x(k + 0.5)).y((k) => y(levels[k]));
      svg.append("path").datum(ks).attr("d", line).attr("fill", "none")
        .attr("stroke", c.ink1).attr("stroke-width", span === "day" ? 1.4 : 0.9);
      svg.append("line").attr("x1", left).attr("x2", width - 4).attr("y1", top + 16 + LEVEL_H)
        .attr("y2", top + 16 + LEVEL_H).attr("stroke", c.rule);
      svg.append("text").attr("x", width - 6).attr("y", top + 26).attr("text-anchor", "end")
        .attr("class", "muted small-svg").text("loudness, its own scale");

      if (sound.mix) {
        const mix = sound.mix[r];
        const mTop = top + 16 + LEVEL_H + 6;
        const ym = d3.scaleLinear().domain([0, 1]).range([mTop + MIX_H, mTop]);
        [0, 1, 2].forEach((layer) => {
          const base = (k) => mix[k].slice(0, layer).reduce((s, v) => s + v, 0);
          const area = d3.area().defined((k) => mix[k] !== null)
            .x((k) => x(k + 0.5)).y0((k) => ym(base(k))).y1((k) => ym(base(k) + mix[k][layer]))
            .curve(d3.curveStepAfter);
          svg.append("path").datum(ks).attr("d", area).attr("fill", mixColors[layer]).attr("opacity", 0.85);
        });
        svg.append("text").attr("x", width - 6).attr("y", mTop + MIX_H + 11).attr("text-anchor", "end")
          .attr("class", "muted small-svg").text("frequency mix, share of the sound's power");
      }
    });

    const ticks = span === "day"
      ? d3.range(lo, hi, ctx.binsPerHour * 2)
      : meta.days.map((d) => d.start_bin);
    svg.append("g").attr("class", "axis").attr("transform", `translate(0,${axisY})`)
      .call(d3.axisBottom(x).tickValues(ticks)
        .tickFormat((b) => (span === "day" ? ctx.clockLabel(b) : ctx.dayLabel(b).slice(0, 6))).tickSize(3));
    svg.append("line").attr("class", "cursor").attr("x1", x(bin + 0.5)).attr("x2", x(bin + 0.5))
      .attr("y1", top0).attr("y2", axisY);

    const pct = (v) => `${Math.round(100 * v)}%`;
    svg.append("rect").attr("x", 0).attr("y", 0).attr("width", width).attr("height", height)
      .attr("fill", "transparent").style("cursor", "pointer")
      .on("mousemove", (ev) => {
        const [mx] = d3.pointer(ev);
        const k = Math.max(lo, Math.min(hi - 1, Math.floor(x.invert(mx))));
        const rows = sound.rooms.map((room, r) => {
          const v = sound.leq[r][k];
          const m = sound.mix?.[r][k];
          return `<b>${room}</b>: ${v === null ? "<span class='muted'>not recorded</span>"
            : `${v.toFixed(1)} dBFS, louder than ${louderThan(sound.sorted[r], v)}% of its time` +
              (m ? `<br><span class='muted'>mix: ${pct(m[0])} low · ${pct(m[1])} voice range · ${pct(m[2])} high</span>` : "")}`;
        });
        ctx.tip.show(`<b>${ctx.dayLabel(k)} ${ctx.clockLabel(k)}</b><br>${rows.join("<br>")}<br><span class='muted'>click to jump here</span>`,
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
