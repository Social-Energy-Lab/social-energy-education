// Chapter: where do people press? The press rate per setting, highest first, with intervals.
// The settings are the team's grouping from the programme and the rooms.
import { block, caption, emptyNote, finite, hbars, named, numberFormat, onResize } from "./chart.js";

/** places rows → those with a rate, highest rate first. */
export function placeRows(rows) {
  return (rows ?? []).filter((r) => finite(r?.rate)).sort((a, b) => b.rate - a.rate);
}

export function render(el, agg, t, opts = {}) {
  const fmt = numberFormat(opts.lang?.() ?? "de", 1);
  const rows = placeRows(agg?.places);
  const draw = () => {
    el.replaceChildren();
    if (!rows.length) {
      emptyNote(el, t);
      return;
    }
    const axis = t("ch_places_rate");
    const fig = block(el, axis);
    hbars(
      fig,
      rows.map((r) => {
        const name = named(t, "setting", r.setting);
        const range = finite(r.lo) && finite(r.hi) ? ` (${fmt(r.lo)}–${fmt(r.hi)})` : "";
        return {
          name,
          value: r.rate,
          lo: finite(r.lo) ? r.lo : null,
          hi: finite(r.hi) ? r.hi : null,
          tip: `${name}: ${fmt(r.rate)}${range}`,
        };
      }),
      {
        label: `${axis}. ${t("ch_places_aria")}`,
        axis,
        tick: fmt,
        reduced: opts.reduced,
        el,
      },
    );
    caption(el, t("chart_interval_note"));
  };
  draw();
  onResize(el, draw);
}
