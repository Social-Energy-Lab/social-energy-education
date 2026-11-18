"""How the dining and main halls sounded over the academy, against the programme. EXPLORATORY.

Research question: none of its own; a descriptive first look for the research team, asked for by
the project lead (2026-11): did the rooms' sound change over the academy, and does it follow the
programme's peaks and lows? Construct: group sound as an outward trace of collective arousal, the
"sound of solidarity" `[inferred]`. Nothing here is a test: no intervals, no p-values, and no
press data. The figures are the result.

Unit of analysis: one recorder (``audiomoth:mensa``, ``audiomoth:plenum``) per 5-minute bin inside
its scheduled slots. Bins come from ``acoustics_presses.acoustic_bins`` unchanged: the per-second
features of ``social-energy extract-acoustics`` in the delivery's day folders, bins with at least
80 % of their seconds, from the self-report instruction to the handover, without the half hour of
the 14 Aug settings incident, inside the device's scheduled slots.

Measures per bin: ``leq_dbfs`` (level), ``l90_dbfs`` (background), ``spectral_centroid_hz``
(brightness: babble is darker than music or clapping) and the six band levels ``band_<lo>_<hi>_db``
(how the spectrum shifts). Levels are dBFS, relative to the recorder's full scale, not calibrated
sound pressure: compare a recorder with itself over time, not the two rooms with each other.

Programme: the spine's items with missing ends filled per kind (``exploratory_presses
.event_windows``). An item labels a recorder's bin if it covers the bin's midpoint and either has
a location in the recorder's zone ("in room") or is a camp-wide item without a location
("camp-wide"); an in-room item wins over a camp-wide one, and among several the shortest wins.
Bins no item covers are "no item on record", which in the dining hall is mostly meals: the spine
records few meals.

Context for any per-kind comparison: how much of the academy each kind took. ``by_kind.parquet``
carries, per recorder and kind, the hours recorded and the hours the programme scheduled in that
room, so a kind that looks loud on two recorded hours is read as two hours.

Outputs, to ``$SOCIAL_ENERGY_DATA/dsa-2026/derived/analyses/acoustics-over-time/`` only:
``bins.parquet``, ``by_kind.parquet``, ``spectrum_by_kind.parquet``, ``per_day.parquet``,
``summary.json``, and the figures ``overview.png``, ``per_day.png``, ``by_kind.png``,
``spectrum_by_kind.png`` and ``days/<date>.png``. Programme labels come from the spine and appear
only in those local outputs.

    uv run --extra analysis python studies/dsa-2026/analyses/acoustics_over_time.py
"""

from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
import acoustics_presses as ap
import copresence_by_phase as cp
import exploratory_presses as xp

from social_energy import paths
from social_energy.spine import Spine
from social_energy.study import StudyConfig

SLUG = "acoustics-over-time"
BIN = ap.BIN
BIN_H = BIN.total_seconds() / 3600
NONE = "no item on record"
FEATURES = {
    "leq_dbfs": "level, Leq (dBFS)",
    "l90_dbfs": "background, L90 (dBFS)",
    "centroid_hz": "spectral centroid (Hz), sounding bins",
}
#: A bin whose Leq is within this many dB of the recorder's floor is near silent: its spectrum is
#: the recorder's own noise, so its centroid says nothing about the room.
FLOOR_MARGIN_DB = 6.0
#: The floor: this quantile of the recorder's L90 over all its bins.
FLOOR_QUANTILE = 0.02
#: Day-level items worth naming on the per-day figure.
SPECIAL_KINDS = ("special", "excursion", "party", "concert", "lecture")
INK, INK2, INK3 = ap.INK, ap.INK2, "#8a8984"
COLOR, NAME = ap.COLOR, ap.NAME


# ---- pure functions ----------------------------------------------------------------------------


def bands_of(columns: list[str]) -> list[str]:
    """Band columns in frequency order (``band_<lo>_<hi>_db``)."""
    bands = [c for c in columns if c.startswith("band_") and c.endswith("_db")]
    return sorted(bands, key=lambda c: int(c.split("_")[1]))


def band_label(col: str) -> str:
    lo, hi = (int(x) for x in col.split("_")[1:3])
    k = lambda v: f"{v // 1000} k" if v >= 1000 else str(v)  # noqa: E731
    return f"{k(lo)}-{k(hi)} Hz"


def flag_near_floor(bins: pl.DataFrame) -> pl.DataFrame:
    """Add ``near_floor`` (Leq within ``FLOOR_MARGIN_DB`` of the recorder's floor) and
    ``centroid_hz``: the spectral centroid of sounding bins, null where ``near_floor``."""
    floor = pl.col("l90_dbfs").quantile(FLOOR_QUANTILE, "linear").over("recorder")
    near = pl.col("leq_dbfs") < floor + FLOOR_MARGIN_DB
    return bins.with_columns(near.alias("near_floor")).with_columns(
        pl.when(~pl.col("near_floor")).then(pl.col("spectral_centroid_hz")).alias("centroid_hz")
    )


def with_slot_fallback(labelled: pl.DataFrame) -> pl.DataFrame:
    """Bins no item covers take their recording slot as kind, e.g. ``no item (12:00-13:45)``.
    In the dining hall the slots are mostly meals, which the spine rarely records."""
    return labelled.with_columns(
        pl.when(pl.col("kind") == NONE)
        .then(pl.format("no item ({})", pl.col("slot")))
        .otherwise(pl.col("kind"))
        .alias("kind")
    )


def room_items(windows: pl.DataFrame, zone_locations: dict[str, set[str]]) -> pl.DataFrame:
    """Per recorder, the programme items that can label its bins, with ``where`` and minutes.

    ``windows``: event, kind, label, all_camp, locations, start, end (UTC). ``zone_locations``:
    recorder -> the location refs in its zone. An item is "in room" if one of its locations is in
    the zone, "camp-wide" if it is all-camp and has no location, and otherwise not the room's.
    """
    rows = []
    for rec, locs in zone_locations.items():
        for r in windows.iter_rows(named=True):
            if set(r["locations"] or []) & locs:
                where = "in room"
            elif r["all_camp"] and not r["locations"]:
                where = "camp-wide"
            else:
                continue
            rows.append({"recorder": rec, **{k: r[k] for k in ("event", "kind", "label")},
                         "start": r["start"], "end": r["end"], "where": where})  # fmt: skip
    schema = {"recorder": pl.String, "event": pl.String, "kind": pl.String, "label": pl.String,
              "start": pl.Datetime("us", "UTC"), "end": pl.Datetime("us", "UTC"),
              "where": pl.String}  # fmt: skip
    out = pl.DataFrame(rows, schema=schema)
    return out.with_columns(
        ((pl.col("end") - pl.col("start")).dt.total_seconds() / 60).alias("min")
    )


def label_bins(bins: pl.DataFrame, items: pl.DataFrame) -> pl.DataFrame:
    """``bins`` (recorder, bin) with the item covering each bin's midpoint: event, kind, label,
    where. In room beats camp-wide; then the shortest item wins. Uncovered bins get ``NONE``."""
    mid = (pl.col("bin") + BIN / 2).alias("_mid")
    b = bins.with_row_index("_row").with_columns(mid)
    hits = (
        b.select("_row", "recorder", "_mid")
        .join(items, on="recorder")
        .filter((pl.col("start") <= pl.col("_mid")) & (pl.col("_mid") < pl.col("end")))
        .with_columns((pl.col("where") != "in room").cast(pl.Int8).alias("_tier"))
        .sort("_row", "_tier", "min", "event")
        .unique("_row", keep="first")
        .select("_row", "event", "kind", "label", "where")
    )
    return (
        b.join(hits, on="_row", how="left")
        .with_columns(
            pl.col("kind").fill_null(NONE),
            pl.col("label").fill_null(NONE),
            pl.col("where").fill_null("none"),
        )
        .sort("_row")
        .drop("_row", "_mid")
    )


def scheduled_hours(items: pl.DataFrame, lo, hi) -> pl.DataFrame:
    """Per recorder and kind, hours the programme scheduled in the room within [lo, hi):
    the union of that kind's items, clipped, so overlapping items count once."""
    rows = []
    clipped = items.with_columns(pl.col("start").clip(lo, hi), pl.col("end").clip(lo, hi)).filter(
        pl.col("end") > pl.col("start")
    )
    for (rec, kind), g in clipped.group_by("recorder", "kind"):
        total, cur_s, cur_e = timedelta(0), None, None
        for s, e in g.sort("start").select("start", "end").iter_rows():
            if cur_e is None or s > cur_e:
                if cur_e is not None:
                    total += cur_e - cur_s
                cur_s, cur_e = s, e
            else:
                cur_e = max(cur_e, e)
        if cur_e is not None:
            total += cur_e - cur_s
        rows.append({"recorder": rec, "kind": kind, "scheduled_h": total.total_seconds() / 3600})
    return pl.DataFrame(
        rows, schema={"recorder": pl.String, "kind": pl.String, "scheduled_h": pl.Float64}
    )


def kind_summary(labelled: pl.DataFrame, scheduled: pl.DataFrame) -> pl.DataFrame:
    """Per recorder and kind: recorded hours, their share of the recorder's hours, the scheduled
    hours in the room, and the median and quartiles of each feature."""
    agg = [pl.len().alias("bins")]
    for f in FEATURES:
        agg += [
            pl.col(f).median().alias(f"{f}_median"),
            pl.col(f).quantile(0.25, "linear").alias(f"{f}_q1"),
            pl.col(f).quantile(0.75, "linear").alias(f"{f}_q3"),
        ]
    return (
        labelled.group_by("recorder", "kind")
        .agg(*agg)
        .with_columns(
            (pl.col("bins") * BIN_H).alias("recorded_h"),
            (pl.col("bins") / pl.col("bins").sum().over("recorder")).alias("share_of_recorded"),
        )
        .join(scheduled, on=["recorder", "kind"], how="left")
        .sort("recorder", "bins", descending=[False, True])
    )


def spectrum_shift(labelled: pl.DataFrame, bands: list[str]) -> pl.DataFrame:
    """Per recorder, kind and band: the kind's median band level minus the recorder's median
    over all its bins, in dB. Positive: that part of the spectrum is louder than usual."""
    long = labelled.unpivot(
        index=["recorder", "kind"], on=bands, variable_name="band", value_name="db"
    )
    base = long.group_by("recorder", "band").agg(pl.col("db").median().alias("base"))
    return (
        long.group_by("recorder", "kind", "band")
        .agg(pl.col("db").median().alias("median_db"), pl.len().alias("bins"))
        .join(base, on=["recorder", "band"])
        .with_columns((pl.col("median_db") - pl.col("base")).alias("shift_db"))
        .drop("base")
        .sort("recorder", "kind", "band")
    )


def per_day(labelled: pl.DataFrame) -> pl.DataFrame:
    """Per recorder and local day: recorded hours and the median of each feature."""
    return (
        labelled.group_by("recorder", "day")
        .agg(
            (pl.len() * BIN_H).alias("recorded_h"),
            *[pl.col(f).median().alias(f) for f in FEATURES],
            pl.col("l90_dbfs").quantile(0.9, "linear").alias("l90_p90"),
            pl.col("leq_dbfs").quantile(0.9, "linear").alias("leq_p90"),
        )
        .sort("recorder", "day")
    )


# ---- run ---------------------------------------------------------------------------------------


def main() -> None:
    study = StudyConfig.load(cp.STUDY_YAML)
    layout = paths.study(cp.STUDY)
    spine = Spine.load(layout.spine)
    out = layout.derived / "analyses" / SLUG
    (out / "days").mkdir(parents=True, exist_ok=True)

    qa: dict = {}
    recs = ap.recorders(study)
    frames = [ap.acoustic_bins(layout, r, qa.setdefault(r["recorder"], {})) for r in recs]
    bins = pl.concat(frames, how="diagonal_relaxed")
    bands = bands_of(bins.columns)

    zone_locations = {
        r["recorder"]: {loc.ref for loc in spine.locations if loc.zone == r["zone"]} for r in recs
    }
    labels = {e.id: e.label for e in spine.events}
    windows = xp.event_windows(spine, known_only=False).with_columns(
        pl.col("event").replace_strict(labels).alias("label")
    )
    items = room_items(windows, zone_locations)
    bins = flag_near_floor(bins)
    keep = ["recorder", "bin", "day", "slot", "near_floor", "spectral_centroid_hz", *FEATURES,
            *bands]  # fmt: skip
    labelled = with_slot_fallback(label_bins(bins.select(keep), items))
    lo, hi = bins["bin"].min(), bins["bin"].max() + BIN
    sched = scheduled_hours(items, lo, hi)
    kinds = kind_summary(labelled, sched)
    spec = spectrum_shift(labelled, bands)
    days = per_day(labelled)

    labelled.write_parquet(out / "bins.parquet")
    kinds.write_parquet(out / "by_kind.parquet")
    spec.write_parquet(out / "spectrum_by_kind.parquet")
    days.write_parquet(out / "per_day.parquet")
    qa["labelled"] = (
        labelled.group_by("recorder", "where").len().sort("recorder", "where").to_dicts()
    )
    qa["near_floor"] = (
        labelled.group_by("recorder").agg(pl.col("near_floor").sum()).sort("recorder").to_dicts()
    )
    qa["bands"] = bands
    (out / "summary.json").write_text(json.dumps(qa, indent=1, default=str), encoding="utf-8")

    figures(labelled, items, kinds, spec, days, bands, windows, out)
    print(f"{out}: {labelled.height} bins")


# ---- figures -----------------------------------------------------------------------------------


def _clock_min(col: str = "bin") -> pl.Expr:
    t = pl.col(col).dt.convert_time_zone(cp.TZ)
    return t.dt.hour().cast(pl.Int32) * 60 + t.dt.minute().cast(pl.Int32)


def _hours(ax, lo: int = 7, hi: int = 23) -> None:
    ax.set_xticks(range(lo * 60, hi * 60 + 1, 120), [f"{h:02d}:00" for h in range(lo, hi + 1, 2)])
    ax.set_xlim(lo * 60, hi * 60)


def _short(s: str, n: int = 30) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def figures(labelled, items, kinds, spec, days, bands, windows, out: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    ap._style(plt)
    recs = ["mensa", "plenum"]
    lab = labelled.with_columns(_clock_min().alias("m"))
    day_list = sorted(lab["day"].unique().to_list())

    # 1. Overview: day x clock, level and centroid, per recorder.
    fig, axes = plt.subplots(2, 2, figsize=(16, 9), sharex=True, sharey=True)
    for col, rec in enumerate(recs):
        d = lab.filter(pl.col("recorder") == rec)
        for row, (f, cmap) in enumerate((("leq_dbfs", "magma"), ("centroid_hz", "viridis"))):
            grid = np.full((len(day_list), 16 * 12), np.nan)
            for day, m, v in d.select("day", "m", f).iter_rows():
                k = (m - 7 * 60) // 5
                if 0 <= k < grid.shape[1] and v is not None:
                    grid[day_list.index(day), k] = v
            ax = axes[row, col]
            vals = d[f].drop_nulls()
            im = ax.imshow(
                grid, aspect="auto", cmap=cmap, interpolation="nearest",
                extent=(7 * 60, 23 * 60, len(day_list) - 0.5, -0.5),
                vmin=vals.quantile(0.02), vmax=vals.quantile(0.98),
            )  # fmt: skip
            ax.grid(False)
            ax.set_yticks(range(len(day_list)), [f"{x:%a %d %b}" for x in day_list], fontsize=9)
            _hours(ax)
            ax.set_title(f"{NAME[rec]} · {FEATURES[f]}", fontsize=12, loc="left")
            fig.colorbar(im, ax=ax, fraction=0.035, pad=0.01)
    fig.suptitle(
        "How the two halls sounded, day by day (5-minute bins inside the recording slots; "
        "blank = not recorded; centroid blank where the hall was near silent). Exploratory.",
        fontsize=13, x=0.01, ha="left",
    )  # fmt: skip
    fig.tight_layout()
    fig.savefig(out / "overview.png", dpi=150)
    plt.close(fig)

    # 2. Per day: medians over the academy, special days named.
    fig, axes = plt.subplots(2, 1, figsize=(16, 9), sharex=True)
    xs = {d: i for i, d in enumerate(day_list)}
    for rec in recs:
        d = days.filter(pl.col("recorder") == rec)
        x = [xs[v] for v in d["day"]]
        axes[0].plot(
            x, d["leq_dbfs"], marker="o", color=COLOR[rec], lw=2, label=f"{NAME[rec]}, median"
        )
        axes[0].plot(x, d["leq_p90"], ls=(0, (3, 2)), color=COLOR[rec], lw=1.2,
                     label=f"{NAME[rec]}, loudest tenth")  # fmt: skip
        axes[1].plot(x, d["centroid_hz"], marker="o", color=COLOR[rec], lw=2, label=NAME[rec])
    axes[0].set_ylabel("Leq (dBFS)")
    axes[1].set_ylabel("spectral centroid (Hz), sounding bins")
    axes[0].legend(ncol=2, fontsize=10)
    loc_days = windows.with_columns(
        pl.col("start").dt.convert_time_zone(cp.TZ).dt.date().alias("day")
    )
    special = loc_days.filter(pl.col("kind").is_in(SPECIAL_KINDS)).sort("start")
    names: dict = {}
    for r in special.iter_rows(named=True):
        names.setdefault(r["day"], []).append(r["kind"])
    for n, (day, ks) in enumerate(sorted(names.items())):
        if day in xs:
            for ax in axes:
                ax.axvspan(xs[day] - 0.45, xs[day] + 0.45, color=INK3, alpha=0.10, lw=0)
            axes[0].annotate(", ".join(dict.fromkeys(ks)), (xs[day], 1.0 + 0.04 * (n % 2)),
                             xycoords=("data", "axes fraction"), ha="center", va="bottom",
                             fontsize=8.5, color=INK2)  # fmt: skip
    axes[1].set_xticks(
        range(len(day_list)), [x.strftime("%a\n%d %b") for x in day_list], fontsize=9
    )
    fig.suptitle("Over the academy: each day's median within the recording slots "
                 "(shaded: days with a special programme item). dBFS is relative, not SPL.",
                 fontsize=13, x=0.01, ha="left")  # fmt: skip
    fig.tight_layout()
    fig.savefig(out / "per_day.png", dpi=150)
    plt.close(fig)

    # 3. By programme kind: level with quartiles, and recorded against scheduled hours.
    fig, axes = plt.subplots(1, 2, figsize=(16, 9))
    for ax, rec in zip(axes, recs, strict=True):
        k = kinds.filter((pl.col("recorder") == rec) & (pl.col("bins") >= 6)).sort(
            "leq_dbfs_median"
        )
        y = np.arange(k.height)
        ax.hlines(y, k["leq_dbfs_q1"], k["leq_dbfs_q3"], color=COLOR[rec], lw=5, alpha=0.35)
        ax.plot(k["leq_dbfs_median"], y, "o", color=COLOR[rec], ms=8)
        labels = []
        for r in k.iter_rows(named=True):
            sched = r["scheduled_h"]
            sched_s = f" of {sched:.0f} h scheduled" if sched else ""
            labels.append(f"{r['kind']}\n{r['recorded_h']:.1f} h recorded{sched_s}")
        ax.set_yticks(y, labels, fontsize=9)
        ax.set_xlabel("Leq (dBFS): median and quartiles of 5-minute bins")
        ax.set_title(NAME[rec], loc="left")
    fig.suptitle("Level by programme kind. Read each against its recorded hours: a few hours "
                 "are a few events. Kinds with under 30 min recorded are left out.",
                 fontsize=13, x=0.01, ha="left")  # fmt: skip
    fig.tight_layout()
    fig.savefig(out / "by_kind.png", dpi=150)
    plt.close(fig)

    # 4. Spectrum by kind: which bands are louder or quieter than the room's usual.
    fig, axes = plt.subplots(1, 2, figsize=(16, 9))
    for ax, rec in zip(axes, recs, strict=True):
        keep_k = kinds.filter((pl.col("recorder") == rec) & (pl.col("bins") >= 6))
        order = keep_k.sort("bins", descending=True)["kind"].to_list()
        s = spec.filter((pl.col("recorder") == rec) & pl.col("kind").is_in(order))
        grid = np.full((len(order), len(bands)), np.nan)
        for kind, band, v in s.select("kind", "band", "shift_db").iter_rows():
            grid[order.index(kind), bands.index(band)] = v
        lim = max(3.0, float(np.nanmax(np.abs(grid))) if grid.size else 3.0)
        im = ax.imshow(grid, cmap="RdBu_r", vmin=-lim, vmax=lim, aspect="auto")
        ax.grid(False)
        ax.set_xticks(range(len(bands)), [band_label(b) for b in bands], rotation=30, ha="right")
        ax.set_yticks(range(len(order)), order)
        for i in range(grid.shape[0]):
            for j in range(grid.shape[1]):
                if not np.isnan(grid[i, j]):
                    ax.text(j, i, f"{grid[i, j]:+.1f}", ha="center", va="center", fontsize=8,
                            color=INK if abs(grid[i, j]) < lim * 0.6 else "white")  # fmt: skip
        ax.set_title(f"{NAME[rec]}: band level against the room's median (dB)", loc="left")
        fig.colorbar(im, ax=ax, fraction=0.04, pad=0.01)
    fig.suptitle(
        "Where in the spectrum each kind of programme sits. Red: louder than the "
        "room usually is in that band. Blue on special days and excursions: the camp was "
        "elsewhere.",
        fontsize=13,
        x=0.01,
        ha="left",
    )
    fig.tight_layout()
    fig.savefig(out / "spectrum_by_kind.png", dpi=150)
    plt.close(fig)

    # 5. One figure per day: level and background, items shaded and named, centroid below.
    cmap = plt.get_cmap("tab20")
    all_kinds = sorted(items["kind"].unique().to_list())
    kcolor = {k: cmap(i % 20) for i, k in enumerate(all_kinds)}
    it = items.with_columns(
        _clock_min("start").alias("m0"),
        _clock_min("end").alias("m1"),
        pl.col("start").dt.convert_time_zone(cp.TZ).dt.date().alias("day"),
    )
    lo_v = lab["l90_dbfs"].drop_nulls().quantile(0.01)
    hi_v = lab["leq_dbfs"].drop_nulls().max() + 2
    for day in day_list:
        fig, axes = plt.subplots(3, 1, figsize=(16, 9), sharex=True,
                                 gridspec_kw={"height_ratios": [3, 3, 2]})  # fmt: skip
        for ax, rec in zip(axes[:2], recs, strict=True):
            d = lab.filter((pl.col("recorder") == rec) & (pl.col("day") == day)).sort("m")
            row = 0
            for r in (
                it.filter((pl.col("recorder") == rec) & (pl.col("day") == day))
                .sort("m0")
                .iter_rows(named=True)
            ):
                m1 = r["m1"] if r["m1"] > r["m0"] else 24 * 60
                ax.axvspan(r["m0"], m1, color=kcolor[r["kind"]], alpha=0.16, lw=0)
                ax.text(r["m0"] + 2, hi_v - row * 2.6, _short(r["label"]), fontsize=7.5,
                        color=INK2, va="top", clip_on=True)  # fmt: skip
                row = (row + 1) % 4
            for g in ap_segments(d, "m", 5):
                ax.plot(g["m"], g["leq_dbfs"], color=COLOR[rec], lw=1.8)
                ax.plot(g["m"], g["l90_dbfs"], color=COLOR[rec], lw=1, ls=(0, (2, 2)))
                axes[2].plot(g["m"], g["centroid_hz"], color=COLOR[rec], lw=1.5)
            ax.set_ylim(lo_v, hi_v + 1)
            ax.set_ylabel("dBFS")
            ax.set_title(
                f"{NAME[rec]} · solid Leq, dashed L90 (background)", loc="left", fontsize=11
            )
        axes[2].set_ylabel("centroid (Hz)")
        axes[2].set_title(
            "spectral centroid; gaps where the hall was near silent", loc="left", fontsize=11
        )
        _hours(axes[2])
        fig.suptitle(f"{day:%A %d %B %Y}: the two halls against the programme (shaded: items in "
                     "that room or camp-wide). Exploratory; dBFS is relative.",
                     fontsize=13, x=0.01, ha="left")  # fmt: skip
        fig.tight_layout()
        fig.savefig(out / "days" / f"{day:%Y-%m-%d}.png", dpi=130)
        plt.close(fig)


def ap_segments(df: pl.DataFrame, col: str, step: float) -> list[pl.DataFrame]:
    """Runs of consecutive clock positions, so lines do not bridge unrecorded time."""
    if df.is_empty():
        return []
    g = df.with_columns((pl.col(col).diff().fill_null(step) > step).cum_sum().alias("_g"))
    return [d for _, d in g.group_by("_g", maintain_order=True)]


if __name__ == "__main__":
    main()
