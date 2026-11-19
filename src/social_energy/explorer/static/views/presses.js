// Self-reports: presses per hour across the study (shared moments marked), the picked people one
// row each (their presses and EDA moments across the study), and how many close others a person
// had at a press compared with their ordinary 5-minute bins, by phase.
import { companyByPhase, perHour, sharedMoments, suppress } from "../model.js";
import { pressesOf } from "../person-model.js";

const ROW_H = 22;

const SHARED_S = 5 * 60;

export function create(el, ctx) {
  const { meta, nNodes, nBins } = ctx;
  const nHours = Math.ceil(nBins / ctx.binsPerHour);
  const hourly = perHour(ctx.b, meta.bin_seconds, nHours);
  const top = d3.select(el).append("svg").attr("width", "100%");
  const groupHint = document.createElement("p");
  groupHint.className = "hint muted small";
  el.append(groupHint);
  const group = d3.select(el).append("svg").attr("width", "100%");
  const bottom = d3.select(el).append("svg").attr("width", "100%");
  let rssiKey = null;
  let sharedHourly = new Uint16Array(nHours);
  let company = null;
  let nShared = 0;

  function recompute(closeRssi) {
    if (closeRssi === rssiKey) return;
    rssiKey = closeRssi;
    const shared = sharedMoments(ctx.b, closeRssi, SHARED_S, meta.bin_seconds);
    sharedHourly = new Uint16Array(nHours);
    nShared = 0;
    shared.forEach((s, i) => {
      if (!s) return;
      nShared++;
      sharedHourly[Math.floor(ctx.b.presses.sec[i] / 3600)]++;
    });
    company = companyByPhase(ctx.b, closeRssi, nNodes, nBins, meta.phases.length, meta.bin_seconds);
  }

  function update(state) {
    recompute(state.closeRssi);
    const c = ctx.colors;
    const width = el.clientWidth || 360;
    const bin = Math.floor(state.bin);

    // Presses per hour.
    const h1 = 110;
    top.attr("height", h1);
    top.selectAll("*").remove();
    const x = d3.scaleLinear().domain([0, nHours]).range([30, width - 8]);
    const y = d3.scaleLinear().domain([0, d3.max(hourly) || 1]).nice().range([h1 - 18, 16]);
    top.append("text").attr("x", 30).attr("y", 10).text(`presses per hour · ${ctx.b.presses.sec.length} in all, ${nShared} shared (close people within 5 min)`);
    top.append("g").attr("class", "axis").attr("transform", "translate(30,0)").call(d3.axisLeft(y).ticks(3).tickSize(3));
    const bw = Math.max(1, x(1) - x(0) - 0.5);
    top.append("g").selectAll("rect").data(hourly).join("rect")
      .attr("x", (_, h) => x(h)).attr("width", bw)
      .attr("y", (v) => y(v)).attr("height", (v) => y(0) - y(v))
      .attr("fill", c.accent).attr("opacity", 0.75);
    top.append("g").selectAll("circle").data(Array.from(sharedHourly)).join("circle")
      .attr("cx", (_, h) => x(h) + bw / 2).attr("cy", (_, h) => y(hourly[h]) - 4)
      .attr("r", (v) => (v ? 2.5 : 0)).attr("fill", c.glow).attr("stroke", c.ink3).attr("stroke-width", 0.5);
    for (const d of meta.days) {
      top.append("text").attr("x", x(d.start_bin / ctx.binsPerHour) + 2).attr("y", h1 - 4)
        .style("fill", c.ink3).style("font-size", "10px").text(d.label.slice(4, 6));
    }
    const hx = x(bin / ctx.binsPerHour);
    top.append("line").attr("class", "cursor").attr("x1", hx).attr("x2", hx).attr("y1", 14).attr("y2", h1 - 18);
    top.append("rect").attr("x", 30).attr("y", 14).attr("width", width - 38).attr("height", h1 - 32)
      .attr("fill", "transparent").style("cursor", "pointer")
      .on("click", (ev) => {
        const h = Math.floor(x.invert(d3.pointer(ev)[0]));
        ctx.set({ bin: Math.max(0, Math.min(nBins - 1, h * ctx.binsPerHour)), playing: false });
      })
      .on("mousemove", (ev) => {
        const h = Math.max(0, Math.min(nHours - 1, Math.floor(x.invert(d3.pointer(ev)[0]))));
        const b = h * ctx.binsPerHour;
        ctx.tip.show(`${ctx.dayLabel(b)} ${ctx.clockLabel(b)}: ${hourly[h]} presses` +
          (sharedHourly[h] ? `, ${sharedHourly[h]} shared` : "") + "<br><span class='muted'>click to jump here</span>",
          ev.clientX, ev.clientY);
      })
      .on("mouseleave", () => ctx.tip.hide());

    picked(state, width);

    // Company at a press vs ordinary time, by phase.
    const h2 = 150;
    bottom.attr("height", h2);
    bottom.selectAll("*").remove();
    const phases = meta.phases.map((p, i) => ({
      p, i, at: company.atPress[i], ord: company.ordinary[i], n: company.nPress[i],
    }));
    const x0 = d3.scaleBand().domain(phases.map((d) => d.p)).range([30, width - 8]).padding(0.25);
    const x1 = d3.scaleBand().domain(["ord", "at"]).range([0, x0.bandwidth()]).padding(0.08);
    const ymax = d3.max(phases.flatMap((d) => [d.at ?? 0, d.ord ?? 0])) || 1;
    const y2 = d3.scaleLinear().domain([0, ymax]).nice().range([h2 - 20, 34]);
    bottom.append("text").attr("x", 30).attr("y", 10).text(`close others (≥ ${state.closeRssi} dBm): ordinary 5 min vs at a press`);
    bottom.append("g").attr("class", "axis").attr("transform", "translate(30,0)").call(d3.axisLeft(y2).ticks(3).tickSize(3));
    bottom.append("g").attr("class", "axis").attr("transform", `translate(0,${h2 - 20})`).call(d3.axisBottom(x0).tickSize(0));
    for (const d of phases) {
      const hidden = d.n < meta.min_group;
      for (const [k, v, fill] of [["ord", d.ord, c.ink3], ["at", d.at, c.accent]]) {
        if (v === null || (k === "at" && hidden)) continue;
        bottom.append("rect").attr("x", x0(d.p) + x1(k)).attr("width", x1.bandwidth())
          .attr("y", y2(v)).attr("height", y2(0) - y2(v)).attr("rx", 2).attr("fill", fill)
          .on("mousemove", (ev) => ctx.tip.show(
            `<b>${d.p}</b><br>${k === "at" ? `at a press (${d.n} presses)` : "ordinary 5 minutes"}: ${v.toFixed(2)} close others`,
            ev.clientX, ev.clientY))
          .on("mouseleave", () => ctx.tip.hide());
      }
      if (hidden) {
        bottom.append("text").attr("x", x0(d.p) + x1("at") + x1.bandwidth() / 2).attr("y", y2(0) - 4)
          .attr("text-anchor", "middle").text(suppress(d.n, meta.min_group));
      }
    }
    const lg = bottom.append("g").attr("transform", "translate(30, 18)");
    [["ordinary 5 min", c.ink3], ["at a press", c.accent]].forEach(([t, f], i) => {
      lg.append("rect").attr("x", i * 110).attr("y", 0).attr("width", 10).attr("height", 10).attr("rx", 2).attr("fill", f);
      lg.append("text").attr("x", i * 110 + 15).attr("y", 9).text(t);
    });
  }

  // The picked people, one row each: presses (blue ticks) and EDA moments (yellow dots).
  function picked(state, width) {
    const c = ctx.colors;
    const ids = state.picked;
    group.selectAll("*").remove();
    if (!ids.length) {
      group.attr("height", 0);
      groupHint.hidden = false;
      groupHint.textContent = "Pick people (in the network, the frame, or “their people” in a person's page) to see their presses and EDA moments here, one row each.";
      return;
    }
    groupHint.hidden = true;
    const left = 96;
    const right = 150;
    const h = 18 + ids.length * ROW_H + 18;
    group.attr("height", h);
    const x = d3.scaleLinear().domain([0, nBins]).range([left, width - right]);
    group.append("text").attr("x", 4).attr("y", 11)
      .text(`picked people: presses${ctx.edaMomentsOf ? " (blue) and EDA moments (yellow, exploratory)" : ""}, one row each`);
    for (const d of meta.days) {
      group.append("line").attr("x1", x(d.start_bin)).attr("x2", x(d.start_bin))
        .attr("y1", 16).attr("y2", h - 16).attr("stroke", c.rule);
      group.append("text").attr("x", x(d.start_bin) + 2).attr("y", h - 4)
        .style("fill", c.ink3).style("font-size", "10px").text(d.label.slice(4, 6));
    }
    const binS = meta.bin_seconds;
    ids.forEach((i, r) => {
      const y = 18 + r * ROW_H;
      const row = group.append("g");
      row.append("text").attr("x", 4).attr("y", y + 14).style("font-weight", 600)
        .style("cursor", ctx.openPerson ? "pointer" : null).text(ctx.personName(i))
        .on("click", () => ctx.openPerson?.(i, Math.floor(state.bin)));
      row.append("line").attr("x1", left).attr("x2", width - right).attr("y1", y + ROW_H - 2)
        .attr("y2", y + ROW_H - 2).attr("stroke", c.rule);
      const consent = ctx.person ? ctx.person.people[i]?.self_report : true;
      const secs = consent ? pressesOf(ctx.b, i) : [];
      const eda = ctx.edaMomentsOf?.(i) ?? null;
      for (const s of secs) {
        row.append("line").attr("x1", x(s / binS)).attr("x2", x(s / binS)).attr("y1", y + 3)
          .attr("y2", y + ROW_H - 4).attr("stroke", c.accent).attr("stroke-width", 1.6)
          .on("mousemove", (ev) => ctx.tip.show(`<b>${ctx.personName(i)}</b> pressed<br>${ctx.dayLabel(s / binS)} ${ctx.clockLabel(s / binS)}<br><span class='muted'>click to jump here</span>`, ev.clientX, ev.clientY))
          .on("mouseleave", () => ctx.tip.hide())
          .style("cursor", "pointer").on("click", () => ctx.set({ bin: Math.floor(s / binS), playing: false }));
      }
      for (const m of eda ?? []) {
        const b = (m.min * 60) / binS;
        row.append("circle").attr("cx", x(b)).attr("cy", y + ROW_H / 2).attr("r", 2.6)
          .attr("fill", c.glow).attr("stroke", c.ink3).attr("stroke-width", 0.5)
          .on("mousemove", (ev) => ctx.tip.show(`<b>${ctx.personName(i)}</b>: EDA moment (exploratory)<br>${ctx.dayLabel(b)} ${ctx.clockLabel(b)}`, ev.clientX, ev.clientY))
          .on("mouseleave", () => ctx.tip.hide())
          .style("cursor", "pointer").on("click", () => ctx.set({ bin: Math.floor(b), playing: false }));
      }
      const what = !consent ? "no self-report consent"
        : `${secs.length} presses${ctx.edaMomentsOf ? ` · ${eda ? `${eda.length} EDA` : "no EDA"}` : ""}`;
      row.append("text").attr("x", width - right + 8).attr("y", y + 14).style("fill", c.ink2).text(what);
    });
    const bx = x(Math.floor(state.bin));
    group.append("line").attr("class", "cursor").attr("x1", bx).attr("x2", bx).attr("y1", 16).attr("y2", h - 16);
  }

  return { update };
}
