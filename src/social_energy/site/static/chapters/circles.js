// Chapter: do the courses keep to themselves? The share of ties across course lines per day, with
// the share random mixing would give as a dashed line and the special days marked; then how many
// new ties came back in the following days, by the kind of day they formed on. A button moves the
// hero's playhead to the afternoon of the first special day and scrolls up to it.
import {
  block,
  caption,
  dayLabel,
  dayOrder,
  emptyNote,
  finite,
  hbars,
  metaDay,
  named,
  numberFormat,
  onResize,
  svgIn,
} from "./chart.js";

/** The hour of the special day the "show me on the network" button jumps to (local time). */
export const SHOW_HOUR = 15;

/**
 * meta.days → the same days with `special`: the label of a special day that starts within the
 * day (from its start_bin to the next day's), else null.
 */
export function markSpecial(days, specialDays) {
  const list = days ?? [];
  return list.map((d, i) => {
    const end = i + 1 < list.length ? list[i + 1].start_bin : Infinity;
    const hit = (specialDays ?? []).find((s) => d.start_bin <= s.start_bin && s.start_bin < end);
    return { ...d, special: hit ? hit.label : null };
  });
}

/** Minutes past local midnight of `bin` in the camp's time zone. */
function localMinutes(meta, bin) {
  const at = new Date(Date.parse(meta.t0) + bin * meta.bin_seconds * 1000);
  const parts = new Intl.DateTimeFormat("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    timeZone: meta.timezone,
  }).formatToParts(at);
  const get = (type) => Number(parts.find((p) => p.type === type)?.value ?? 0);
  return get("hour") * 60 + get("minute");
}

/** The bin at SHOW_HOUR on the first special day (its start when later), or null. */
export function showBin(meta, hour = SHOW_HOUR) {
  const specials = [...(meta?.special_days ?? [])].sort((a, b) => a.start_bin - b.start_bin);
  const first = specials[0];
  if (!first || !meta.t0 || !meta.bin_seconds) return null;
  const ahead = hour * 60 - localMinutes(meta, first.start_bin);
  const bin = first.start_bin + Math.round((ahead * 60) / meta.bin_seconds);
  return Math.max(first.start_bin, Math.min(bin, first.end_bin - 1));
}

/** daily_mixing rows → one point per day in day order (the first row of a day wins). */
export function mixingSeries(rows) {
  const seen = new Map();
  for (const r of rows ?? []) {
    if (!finite(r?.cross_share) || seen.has(r.day)) continue;
    seen.set(r.day, {
      day: r.day,
      kind: r.kind ?? null,
      observed: r.cross_share,
      expected: finite(r.expected) ? r.expected : null,
    });
  }
  return [...seen.values()].sort((a, b) => dayOrder(a.day, b.day));
}

function lineChart(host, series, { meta, lang, t }) {
  const fmt = numberFormat(lang, 0);
  const summary = `${t("ch_circles_observed")}. ${t("ch_circles_aria")}`;
  const marked = markSpecial(meta?.days, meta?.special_days);
  const specialOf = (p) => {
    const m = metaDay(p.day, meta);
    if (m) return marked.find((d) => d.index === m.index)?.special ?? null;
    return p.kind && p.kind !== "ordinary" ? p.kind : null;
  };
  const top = 26;
  const bottom = 30;
  const left = 40;
  const right = 12;
  const height = 250;
  const { svg, width } = svgIn(host, height, summary);
  const narrow = width < 560;
  const x = d3
    .scalePoint(
      series.map((p) => p.day),
      [left, width - right],
    )
    .padding(0.5);
  const max = d3.max(series, (p) => Math.max(p.observed, p.expected ?? 0)) ?? 100;
  const y = d3
    .scaleLinear()
    .domain([0, Math.min(100, Math.max(10, max * 1.1))])
    .nice()
    .range([height - bottom, top]);
  const step = x.step();

  // Special days: a soft band and a label above it.
  const specials = series.map((p) => ({ p, label: specialOf(p) })).filter((s) => s.label);
  const sg = svg.append("g").selectAll("g").data(specials).join("g");
  sg.append("rect")
    .attr("class", "special")
    .attr("x", (s) => x(s.p.day) - step / 2)
    .attr("width", step)
    .attr("y", top)
    .attr("height", height - bottom - top);
  sg.append("text")
    .attr("class", "special-label")
    .attr("x", (s) => x(s.p.day))
    .attr("y", top - 8)
    .attr("text-anchor", (s) => (x(s.p.day) > width * 0.75 ? "end" : x(s.p.day) < width * 0.25 ? "start" : "middle"))
    .text((s) => named(t, "label", s.label));

  const ticks = y.ticks(4);
  svg
    .append("g")
    .attr("class", "grid")
    .selectAll("line")
    .data(ticks)
    .join("line")
    .attr("x1", left)
    .attr("x2", width - right)
    .attr("y1", (d) => y(d))
    .attr("y2", (d) => y(d));
  const ax = svg.append("g").attr("class", "axis");
  ax.selectAll(".yt")
    .data(ticks)
    .join("text")
    .attr("class", "yt")
    .attr("x", left - 6)
    .attr("y", (d) => y(d))
    .attr("dy", "0.35em")
    .attr("text-anchor", "end")
    .text((d) => `${fmt(d)} %`);
  const every = Math.max(1, Math.ceil(series.length / Math.floor((width - left) / (narrow ? 34 : 64))));
  ax.selectAll(".xt")
    .data(series.filter((_, i) => i % every === 0))
    .join("text")
    .attr("class", "xt")
    .attr("x", (p) => x(p.day))
    .attr("y", height - bottom + 18)
    .attr("text-anchor", "middle")
    .text((p) => dayLabel(p.day, meta, lang, narrow));

  const withExpected = series.filter((p) => p.expected !== null);
  if (withExpected.length) {
    svg
      .append("path")
      .attr("class", "expected")
      .attr(
        "d",
        d3
          .line()
          .x((p) => x(p.day))
          .y((p) => y(p.expected))(withExpected),
      );
  }
  svg
    .append("path")
    .attr("class", "line")
    .attr(
      "d",
      d3
        .line()
        .x((p) => x(p.day))
        .y((p) => y(p.observed))(series),
    );
  svg
    .append("g")
    .selectAll("circle")
    .data(series)
    .join("circle")
    .attr("class", "point")
    .attr("cx", (p) => x(p.day))
    .attr("cy", (p) => y(p.observed))
    .attr("r", 4.5)
    .append("title")
    .text((p) => {
      const exp = p.expected === null ? "" : ` · ${t("ch_circles_expected")}: ${fmt(p.expected)} %`;
      return `${dayLabel(p.day, meta, lang)}: ${fmt(p.observed)} %${exp}`;
    });
}

function legend(el, t) {
  const ul = document.createElement("ul");
  ul.className = "legend-inline";
  for (const [cls, key] of [
    ["line", "ch_circles_observed"],
    ["expected", "ch_circles_expected"],
  ]) {
    const li = document.createElement("li");
    li.innerHTML = `<svg width="26" height="10" aria-hidden="true"><line class="${cls}" x1="1" x2="25" y1="5" y2="5"/></svg>`;
    const span = document.createElement("span");
    span.textContent = t(key);
    li.append(span);
    ul.append(li);
  }
  el.append(ul);
}

export function render(el, agg, t, opts = {}) {
  const lang = opts.lang?.() ?? "de";
  const meta = opts.meta ?? null;
  const series = mixingSeries(agg?.daily_mixing);
  const persistence = (agg?.persistence ?? []).filter((r) => finite(r?.share));
  const target = showBin(meta);
  const draw = () => {
    el.replaceChildren();
    if (!series.length && !persistence.length) {
      emptyNote(el, t);
      return;
    }
    if (opts.player && target !== null) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "chart-action";
      btn.textContent = t("ch_circles_show");
      btn.addEventListener("click", () => {
        opts.player?.pause();
        opts.player?.seekTo(target);
        document
          .getElementById("chapter-hero")
          ?.scrollIntoView({ behavior: opts.reduced ? "auto" : "smooth", block: "start" });
      });
      el.append(btn);
    }
    const fig = block(el, t("ch_circles_observed"));
    if (series.length) {
      legend(fig, t);
      lineChart(fig, series, { meta, lang, t });
    } else {
      emptyNote(fig, t);
    }
    const pfig = block(el, t("ch_circles_persistence"));
    if (!persistence.length) {
      emptyNote(pfig, t);
      return;
    }
    const pct = numberFormat(lang, 0);
    hbars(
      pfig,
      persistence.map((r) => {
        const name = named(t, "origin", r.origin);
        const range = finite(r.lo) && finite(r.hi) ? ` (${pct(r.lo)}–${pct(r.hi)} %)` : "";
        return {
          name,
          value: r.share,
          lo: finite(r.lo) ? r.lo : null,
          hi: finite(r.hi) ? r.hi : null,
          tip: `${name}: ${pct(r.share)} %${range}`,
        };
      }),
      {
        label: `${t("ch_circles_persistence")}. ${t("ch_circles_aria_persistence")}`,
        axis: t("ch_circles_share_axis"),
        tick: (d) => `${pct(d)} %`,
        reduced: opts.reduced,
        el,
      },
    );
    caption(el, t("chart_interval_note"));
  };
  draw();
  onResize(el, draw);
}
