// Chapter: do people press together? A headline figure (shared presses against chance), then two
// bar charts of the same ratio: by the time between two presses, and by the size of the group
// that pressed. A bar at the 1× line means as often as chance would give.
import { bandStart, block, caption, emptyNote, finite, hbars, numberFormat, onResize } from "./chart.js";

/** Rows of a ratio section as bars ordered by where their band starts; rows without a ratio go. */
function bars(rows, key) {
  return (rows ?? [])
    .filter((r) => finite(r?.ratio))
    .map((r) => ({
      [key]: r[key],
      ratio: r.ratio,
      lo: finite(r.ratio_lo) ? r.ratio_lo : null,
      hi: finite(r.ratio_hi) ? r.ratio_hi : null,
    }))
    .sort((a, b) => bandStart(a[key]) - bandStart(b[key]));
}

/** moments_latency rows → [{band, ratio, lo, hi}] sorted by band start. */
export function latencyBars(rows) {
  return bars(rows, "band");
}

/** moments_size rows → [{size, ratio, lo, hi}] sorted by the smallest group size. */
export function sizeBars(rows) {
  return bars(rows, "size");
}

/** The headline numbers: `numbers` first, else the moments_headline row. */
export function headline(agg) {
  const n = agg?.numbers ?? {};
  const row = (agg?.moments_headline ?? [])[0] ?? {};
  const pick = (a, b) => (finite(a) ? a : finite(b) ? b : null);
  return {
    ratio: pick(n.cascade_excess, row.ratio),
    lo: pick(n.cascade_excess_lo, row.lo),
    hi: pick(n.cascade_excess_hi, row.hi),
  };
}

export function render(el, agg, t, opts = {}) {
  const lang = opts.lang?.() ?? "de";
  const fmt = numberFormat(lang);
  const head = headline(agg);
  const latency = latencyBars(agg?.moments_latency);
  const size = sizeBars(agg?.moments_size);

  const draw = () => {
    el.replaceChildren();
    if (head.ratio === null && !latency.length && !size.length) {
      emptyNote(el, t);
      return;
    }
    if (head.ratio !== null) {
      const fig = document.createElement("div");
      fig.className = "headline";
      const big = document.createElement("strong");
      big.textContent = `${fmt(head.ratio)}×`;
      const sub = document.createElement("span");
      sub.textContent = t("ch_moments_headline");
      fig.append(big, sub);
      el.append(fig);
    }
    const seconds = t("ch_moments_seconds");
    const people = t("ch_moments_people");
    for (const [rows, key, title, unit, aria] of [
      [latency, "band", t("ch_moments_latency"), seconds, "ch_moments_aria_latency"],
      [size, "size", t("ch_moments_size"), people, "ch_moments_aria_size"],
    ]) {
      const fig = block(el, title);
      if (!rows.length) {
        emptyNote(fig, t);
        continue;
      }
      const named = rows.map((r) => {
        const name = `${String(r[key]).replace("-", "–")} ${unit}`;
        const range = finite(r.lo) && finite(r.hi) ? ` (${fmt(r.lo)}–${fmt(r.hi)})` : "";
        return { ...r, value: r.ratio, name, tip: `${name}: ${fmt(r.ratio)}×${range}` };
      });
      hbars(fig, named, {
        label: `${title}. ${t(aria)}`,
        axis: t("ch_moments_ratio"),
        tick: (d) => `${fmt(d)}×`,
        refAt: 1,
        reference: t("ch_moments_reference"),
        reduced: opts.reduced,
        el,
      });
    }
    caption(el, t("chart_interval_note"));
  };
  draw();
  onResize(el, draw);
}
