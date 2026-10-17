"""Room sound in the dining hall and the main hall against self-report press density. EXPLORATORY.

Research question: the exploratory acoustics item of ``research/analysis-plan.md`` (room loudness
and spectral activity against press density at the same times). Construct: group sound (meals,
applause, singing, laughter) as an outward trace of collective arousal, the "sound of solidarity"
`[inferred]`; a press marks a moment the wearer felt moved `[inferred]`. Nothing here is a test:
correlations are reported with intervals, never with p-values, and the plots are the result.

Unit of analysis: one recorder (``audiomoth:mensa``, ``audiomoth:plenum``) per 5-minute bin, and
per recording session (one scheduled slot on one day). Five minutes is the beacon bin of the other
analyses, and every slot of the AudioMoth schedule (``study.yaml``) starts and ends on a multiple
of five minutes, so bins tile the sessions exactly.

Filters, each counted in ``summary.json``:

1. Acoustics: the per-second features of ``social-energy extract-acoustics``, read from the day
   folders ``derived/acoustics/<device>/<YYYYMMDD>/``; files loose in the device folder are not
   part of the delivery's day structure and are skipped. Bins with less than 80 % of their
   seconds recorded are left out (``bin_features``). Bins outside the device's scheduled slots
   are left out.
2. Time: from the self-report instruction (14 Aug 08:45, later than the observation window's
   start) to the handover (``beacons.observation_window`` end), leaving out the half hour on
   14 Aug when the recorder settings were being changed (``acoustics.incidents``).
3. Presses: exactly as ``self_report_context.py`` (our ingest, ``ok``, resolved to a participant,
   not excluded, ``self_report`` consent, accidental chains dropped, episodes merged), counted at
   the episode's first press.
4. Exposure: participants with ``self_report`` consent seen by the beacons in the bin. A bin a tag
   could not report (lost after a restart, or an unsettled readout; ``beacon_diagnostics.py``) is
   removed from both the presses and the person-time, as in ``self_report_context.py``.
5. In the room: participants placed in the recorder's zone in the bin (``room_per_bin``: the room
   tag heard most often, at least two hits; built by ``copresence_by_phase.py build``). Placement
   needs beacon data, so this side also needs ``beacons`` consent.
6. Suppression: any bin or session with fewer than ``MIN_GROUP`` people has its press figures
   blanked (ethics approval: aggregates only).

Press density is presses per 10 person-hours: (a) camp-wide, among everyone present anywhere, and
(b) among the people placed in the recorder's room. The obvious confound is the clock: meals and
plenums happen at fixed times and both sound and presses follow the day's rhythm. So every
correlation is also computed *within slot*: each variable minus its mean for that recorder and
slot across days, which compares, say, a loud breakfast with a quiet breakfast. Spearman rank
correlations throughout (press rates are skewed and often zero). Intervals: bins come in runs
within a session, so bin-level intervals resample whole sessions; session-level intervals resample
whole days (``social_energy.stats.cluster_bootstrap``).

Inputs: ``social-energy extract-acoustics``, ``social-energy ingest-beacons``,
``copresence_by_phase.py build`` and ``beacon_diagnostics.py`` must have run.

    uv run --extra analysis python studies/dsa-2026/analyses/acoustics_presses.py
"""

from __future__ import annotations

import json
import sys
from datetime import time, timedelta
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
import copresence_by_phase as cp
import self_report_context as srx

from social_energy import paths
from social_energy.acoustics import bin_features
from social_energy.spine import Spine
from social_energy.stats import cluster_bootstrap
from social_energy.study import StudyConfig

SLUG = "acoustics-presses"
BIN = timedelta(minutes=5)
BIN_H = BIN.total_seconds() / 3600
#: Least share of a bin's seconds that must be recorded for the bin to count.
MIN_COVERAGE = 0.8
MIN_GROUP = cp.MIN_GROUP
#: Least exposure for a pooled clock block to be drawn in the day-rhythm figure.
MIN_PERSON_HOURS = 5
#: Recorder settings possibly wrong while the schedules were changed (``acoustics.incidents``).
SETTINGS_INCIDENT = ("2026-08-14 10:00:00", "2026-08-14 10:30:00")
N_BOOT = 2000
SEED = 20261103
#: Acoustic summaries compared with presses. Leq is the primary one; the rest are descriptive.
FEATURES = {
    "leq_dbfs": "level (Leq)",
    "l10_dbfs": "loud moments (L10)",
    "l90_dbfs": "background (L90)",
    "spectral_centroid_hz": "spectral centroid",
    "spectral_flatness": "spectral flatness",
}
MEASURES = {
    "rate_camp": "presses / 10 person-h, camp",
    "rate_room": "presses / 10 person-h, in room",
    "people_room": "people in room",
}
RHO = "\N{GREEK SMALL LETTER RHO}"
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
COLOR = {"mensa": "#2a78d6", "plenum": "#eb6834"}
NAME = {"mensa": "Dining hall (Mensa)", "plenum": "Main hall (Plenum)"}


def recorders(study: StudyConfig) -> list[dict]:
    """Device folder, zone and scheduled slots (local start, end) per recorder."""
    out = []
    for dev in study.raw["acoustics"]["devices"]:
        key = next(k for k in dev if k.startswith("schedule_from_"))
        slots = []
        for s in dev[key]:
            a, b = s.split("-")
            slots.append((time.fromisoformat(a), time.fromisoformat(b)))
        out.append(
            {
                "recorder": dev["id"].split(":", 1)[1],
                "zone": dev["zone"],
                "from": key.removeprefix("schedule_from_"),
                "slots": slots,
            }
        )
    return out


def slot_expr(bin_utc: pl.Expr, slots: list[tuple[time, time]]) -> pl.Expr:
    """``HH:MM-HH:MM`` of the scheduled slot holding the whole bin, else null."""
    start = bin_utc.dt.convert_time_zone(cp.TZ).dt.time()
    end = (bin_utc + BIN).dt.convert_time_zone(cp.TZ).dt.time()
    expr = pl.lit(None, dtype=pl.String)
    for a, b in slots:
        label = f"{a:%H:%M}-{b:%H:%M}"
        inside = (start >= a) & (end <= b) & (end > start)
        expr = pl.when(inside).then(pl.lit(label)).otherwise(expr)
    return expr


def acoustic_bins(layout: paths.StudyLayout, rec: dict, qa: dict) -> pl.DataFrame:
    root = layout.derived / "acoustics" / rec["recorder"]
    files = sorted(p for d in root.iterdir() if d.is_dir() for p in d.glob("*.parquet"))
    qa["feature_files"] = len(files)
    qa["loose_files_skipped"] = len(list(root.glob("*_*.parquet")))
    binned = pl.concat(
        [bin_features(pl.read_parquet(f), BIN, min_coverage=MIN_COVERAGE) for f in files]
    )
    # A bin split across two files (a recording restarted inside it) is kept once per file only
    # if each part alone has enough coverage; keep the better covered part.
    binned = binned.sort("coverage", descending=True).unique("bin", keep="first").sort("bin")
    qa["bins_covered"] = binned.height
    lo, hi = srx.local(srx.INSTRUCTION), srx.local(cp.HANDOVER)
    binned = binned.filter((pl.col("bin") >= lo) & (pl.col("bin") + BIN <= hi))
    qa["bins_in_window"] = binned.height
    a, b = (srx.local(x) for x in SETTINGS_INCIDENT)
    binned = binned.filter((pl.col("bin") + BIN <= a) | (pl.col("bin") >= b))
    qa["bins_outside_settings_incident"] = binned.height
    binned = binned.with_columns(slot_expr(pl.col("bin"), rec["slots"]).alias("slot"))
    qa["bins_off_schedule"] = binned.filter(pl.col("slot").is_null()).height
    binned = binned.filter(pl.col("slot").is_not_null())
    qa["bins"] = binned.height
    return binned.with_columns(
        pl.lit(rec["recorder"]).alias("recorder"),
        pl.col("bin").dt.convert_time_zone(cp.TZ).dt.date().alias("day"),
    )


def rate(presses: pl.Expr, person_bins: pl.Expr) -> pl.Expr:
    return pl.when(person_bins > 0).then(presses / (person_bins * BIN_H) * 10)


def energy_mean(col: str) -> pl.Expr:
    return 10 * (10 ** (pl.col(col) / 10)).mean().log10()


def correlations(df: pl.DataFrame, level: str, cluster: str) -> list[dict]:
    rows = []
    for rec in df["recorder"].unique().sort():
        d = df.filter(pl.col("recorder") == rec)
        within = d.with_columns(
            [pl.col(c) - pl.col(c).mean().over("slot") for c in [*FEATURES, *MEASURES]]
        )
        for f in FEATURES:
            for m in MEASURES:
                for kind, t in (("raw", d), ("within slot", within)):
                    sub = t.filter(pl.col(f).is_not_null() & pl.col(m).is_not_null())
                    c = cluster_bootstrap(
                        sub[f].to_list(),
                        sub[m].to_list(),
                        sub[cluster].cast(pl.String).to_list(),
                        method="spearman",
                        n_boot=N_BOOT,
                        seed=SEED,
                    )
                    rows.append(
                        {
                            "level": level,
                            "recorder": rec,
                            "feature": f,
                            "measure": m,
                            "comparison": kind,
                            "rho": c.r,
                            "lo": c.lo,
                            "hi": c.hi,
                            "n": c.n,
                            "clusters": c.clusters,
                        }
                    )
    return rows


def main() -> None:
    study = StudyConfig.load(cp.STUDY_YAML)
    layout = paths.study(cp.STUDY)
    spine = Spine.load(layout.spine)
    out = layout.derived / "analyses" / SLUG
    out.mkdir(parents=True, exist_ok=True)
    participants = {p.ref for p in spine.people if p.role == "participant"}
    reporters = {f"person:{p}" for p in spine.consented("self_report")} & participants
    placed_ok = reporters & {f"person:{p}" for p in spine.consented("beacons")}
    zone_of = {loc.ref: loc.zone for loc in spine.locations}
    qa: dict = {}

    # Presses and exposure, shared by both recorders.
    presses, qa["presses"] = srx.press_episodes(layout, spine, participants, reporters)
    lost = srx.lost_bins(layout, spine)
    seen = cp.load_all("seen").filter(pl.col("entity").is_in(reporters)).select("entity", "bin")
    if lost is not None:
        seen = seen.join(lost, on=["entity", "bin"], how="anti")
        qa["presses"]["episodes_in_lost_bins"] = presses.join(lost, on=["entity", "bin"]).height
        presses = presses.join(lost, on=["entity", "bin"], how="anti")
    presses = presses.select("entity", "bin")
    camp = (
        seen.group_by("bin")
        .agg(pl.len().alias("people_camp"))
        .join(presses.group_by("bin").agg(pl.len().alias("presses_camp")), on="bin", how="left")
        .with_columns(pl.col("presses_camp").fill_null(0))
    )
    rooms = (
        cp.load_all("rooms")
        .filter(pl.col("entity").is_in(placed_ok))
        .with_columns(pl.col("location").replace_strict(zone_of, default=None).alias("zone"))
        .select("entity", "bin", "zone")
        .join(seen, on=["entity", "bin"], how="semi")  # drops lost bins
    )

    bins_all, rows_room_people = [], []
    for rec in recorders(study):
        q = qa.setdefault(rec["recorder"], {})
        ac = acoustic_bins(layout, rec, q)
        here = rooms.filter(pl.col("zone") == rec["zone"])
        room = (
            here.group_by("bin")
            .agg(pl.len().alias("people_room"))
            .join(
                presses.join(here, on=["entity", "bin"])
                .group_by("bin")
                .agg(pl.len().alias("presses_room")),
                on="bin",
                how="left",
            )
            .with_columns(pl.col("presses_room").fill_null(0))
        )
        b = (
            ac.join(camp, on="bin", how="left")
            .join(room, on="bin", how="left")
            .with_columns(pl.col("people_room", "presses_room").fill_null(0))
        )
        rows_room_people.append(
            here.join(ac.select("bin", "day", "slot", "recorder"), on="bin").select(
                "recorder", "day", "slot", "entity"
            )
        )
        bins_all.append(b)
    bins = pl.concat(bins_all, how="diagonal")

    # Sessions: one recorder, one slot, one day. People are counted as distinct individuals.
    distinct = (
        pl.concat(rows_room_people)
        .group_by("recorder", "day", "slot")
        .agg(pl.col("entity").n_unique().alias("distinct_people_room"))
    )
    sessions = (
        bins.group_by("recorder", "day", "slot")
        .agg(
            pl.len().alias("bins"),
            energy_mean("leq_dbfs").alias("leq_dbfs"),
            pl.col("l10_dbfs").median(),
            pl.col("l90_dbfs").median(),
            pl.col("spectral_centroid_hz").median(),
            pl.col("spectral_flatness").median(),
            pl.col("people_camp").sum().alias("_pb_camp"),
            pl.col("presses_camp").sum(),
            pl.col("people_room").sum().alias("_pb_room"),
            pl.col("presses_room").sum(),
            pl.col("people_room").mean().alias("people_room"),
            pl.col("people_camp").mean().alias("people_camp"),
        )
        .join(distinct, on=["recorder", "day", "slot"], how="left")
        .with_columns(
            rate(pl.col("presses_camp"), pl.col("_pb_camp")).alias("rate_camp"),
            rate(pl.col("presses_room"), pl.col("_pb_room")).alias("rate_room"),
            (pl.col("_pb_room") * BIN_H).alias("person_hours_room"),
            (pl.col("_pb_camp") * BIN_H).alias("person_hours_camp"),
            pl.col("distinct_people_room").fill_null(0),
        )
        .drop("_pb_camp", "_pb_room")
    )
    # Suppress small groups: blank the press figures, keep the sound.
    small_room = pl.col("distinct_people_room") < MIN_GROUP
    sessions = sessions.with_columns(
        *[
            pl.when(small_room).then(None).otherwise(pl.col(c)).alias(c)
            for c in ("presses_room", "rate_room", "people_room", "person_hours_room")
        ],
        pl.when(small_room)
        .then(None)
        .otherwise(pl.col("distinct_people_room"))
        .alias("distinct_people_room"),
    ).sort("recorder", "day", "slot")
    qa["sessions"] = sessions.height
    qa["sessions_room_suppressed"] = sessions.filter(pl.col("rate_room").is_null()).height

    bins = bins.with_columns(
        rate(pl.col("presses_camp"), pl.col("people_camp")).alias("rate_camp"),
        rate(pl.col("presses_room"), pl.col("people_room")).alias("rate_room"),
    )
    small = pl.col("people_room") < MIN_GROUP
    bins = bins.with_columns(
        *[
            pl.when(small).then(None).otherwise(pl.col(c)).alias(c)
            for c in ("people_room", "presses_room", "rate_room")
        ],
        *[
            pl.when(pl.col("people_camp") < MIN_GROUP).then(None).otherwise(pl.col(c)).alias(c)
            for c in ("people_camp", "presses_camp", "rate_camp")
        ],
    )
    qa["bins_room_suppressed"] = bins.filter(pl.col("rate_room").is_null()).height
    bins = bins.with_columns(
        pl.col("bin").dt.convert_time_zone(cp.TZ).dt.strftime("%H:%M").alias("clock"),
        pl.concat_str(
            pl.col("recorder"), pl.col("day").cast(pl.String), pl.col("slot"), separator="|"
        ).alias("session"),
    ).sort("recorder", "bin")

    corr = pl.DataFrame(
        correlations(bins, "bin", "session")
        + correlations(sessions.with_columns(pl.col("day").cast(pl.String)), "session", "day")
    )

    bins.drop("session").write_csv(out / "bins.csv")
    sessions.write_csv(out / "sessions.csv")
    corr.write_csv(out / "correlations.csv")
    figures(bins, sessions, corr, out)

    summary = {
        "exploratory": True,
        "settings": {
            "bin_minutes": 5,
            "min_coverage": MIN_COVERAGE,
            "min_group": MIN_GROUP,
            "correlation": "spearman; within slot = minus the recorder-slot mean across days",
            "intervals": f"95% percentile cluster bootstrap, {N_BOOT} draws: bins by session, "
            "sessions by day",
            "from": srx.INSTRUCTION,
            "to": cp.HANDOVER,
        },
        "qa": qa,
        "session_means": sessions.group_by("recorder", "slot")
        .agg(
            pl.len().alias("sessions"),
            pl.col("leq_dbfs").mean(),
            pl.col("rate_camp").mean(),
            pl.col("rate_room").mean(),
            pl.col("people_room").mean(),
        )
        .sort("recorder", "slot")
        .to_dicts(),
        "primary": corr.filter(pl.col("feature") == "leq_dbfs").to_dicts(),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps(qa, indent=2, default=str))
    with pl.Config(tbl_rows=200, tbl_cols=12):
        print(corr.filter(pl.col("feature") == "leq_dbfs"))


# ---- figures -----------------------------------------------------------------------------------


def _style(plt) -> None:
    plt.rcParams.update(
        {
            "font.size": 11,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.edgecolor": INK2,
            "axes.labelcolor": INK2,
            "xtick.color": INK2,
            "ytick.color": INK2,
            "axes.grid": True,
            "grid.color": GRID,
            "grid.linewidth": 0.6,
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "savefig.facecolor": SURFACE,
            "axes.titlecolor": INK,
            "legend.frameon": False,
        }
    )


def _minutes(clock: pl.Expr) -> pl.Expr:
    return clock.str.slice(0, 2).cast(pl.Int32) * 60 + clock.str.slice(3, 2).cast(pl.Int32)


def figures(bins: pl.DataFrame, sessions: pl.DataFrame, corr: pl.DataFrame, out: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _style(plt)
    hours = lambda ax: (  # noqa: E731
        ax.set_xticks(range(7 * 60, 24 * 60, 120), [f"{h:02d}:00" for h in range(7, 24, 2)]),
        ax.set_xlim(7 * 60, 23 * 60),
    )

    # 1. The day's rhythm: sound and presses on the same clock.
    clock = bins.with_columns(_minutes(pl.col("clock")).alias("m"))
    prof = (
        clock.group_by("recorder", "m")
        .agg(
            pl.col("leq_dbfs").median().alias("med"),
            pl.col("leq_dbfs").quantile(0.25).alias("q1"),
            pl.col("leq_dbfs").quantile(0.75).alias("q3"),
        )
        .sort("recorder", "m")
    )
    # Press rates pooled over days in 15-minute clock blocks. Only bins that already hold at
    # least MIN_GROUP people enter (the rest are blank in ``bins``), and a block is drawn only
    # with at least MIN_PERSON_HOURS of exposure, so a handful of people cannot make a spike.
    block = (pl.col("m") // 15 * 15 + 7.5).alias("m15")

    def rates(df: pl.DataFrame, presses: str, people: str, by: list[str]) -> pl.DataFrame:
        return (
            df.filter(pl.col(people).is_not_null())
            .with_columns(block)
            .group_by(*by, "m15")
            .agg(pl.col(presses).sum().alias("pr"), (pl.col(people).sum() * BIN_H).alias("ph"))
            .filter(pl.col("ph") >= MIN_PERSON_HOURS)
            .with_columns((pl.col("pr") / pl.col("ph") * 10).alias("rate"))
            .sort(*by, "m15")
        )

    def segments(df: pl.DataFrame, col: str, step: float):
        """Runs of consecutive clock positions, so lines do not bridge unrecorded time."""
        g = df.with_columns((pl.col(col).diff().fill_null(step) > step).cum_sum().alias("_g"))
        return [d for _, d in g.group_by("_g", maintain_order=True)]

    room_rates = rates(clock, "presses_room", "people_room", ["recorder"])
    camp = rates(clock.unique("bin"), "presses_camp", "people_camp", [])
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(11, 6.2), sharex=True)
    for rec in ("mensa", "plenum"):
        for i, g in enumerate(segments(prof.filter(pl.col("recorder") == rec), "m", 5)):
            a1.fill_between(g["m"], g["q1"], g["q3"], color=COLOR[rec], alpha=0.18, lw=0)
            a1.plot(g["m"], g["med"], color=COLOR[rec], lw=2, label=NAME[rec] if i == 0 else None)
        r = room_rates.filter(pl.col("recorder") == rec)
        for i, g in enumerate(segments(r, "m15", 15)):
            a2.plot(
                g["m15"], g["rate"], color=COLOR[rec], lw=2, marker="o", ms=4,
                label=f"in the {NAME[rec].split(' (')[0].lower()}" if i == 0 else None,
            )  # fmt: skip
    for i, g in enumerate(segments(camp, "m15", 15)):
        a2.plot(
            g["m15"], g["rate"], color=INK2, lw=1.2, ls=(0, (3, 2)),
            label="whole camp" if i == 0 else None,
        )  # fmt: skip
    a1.set_ylabel("Leq (dBFS)")
    a1.set_title(
        "Room level by time of day: median across days, band = middle half",
        loc="left",
        fontsize=11,
    )
    a1.legend(loc="upper left", ncols=2)
    a2.set_ylabel("presses / 10 person-h")
    a2.set_title(
        "Self-report presses per 10 person-hours, same clock times, 15-min blocks, days pooled",
        loc="left",
        fontsize=11,
    )
    a2.legend(loc="upper left", ncols=3)
    hours(a2)
    fig.text(
        0.01, 0.005,
        f"Exploratory. Recording slots only; 5-min bins with fewer than {MIN_GROUP} people "
        f"omitted; rate blocks need {MIN_PERSON_HOURS} person-hours.",
        color=INK2, fontsize=9,
    )  # fmt: skip
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(out / "fig1_day_rhythm.png", dpi=180)
    plt.close(fig)

    # 2. Sessions: raw and within slot.
    fig, axes = plt.subplots(2, 2, figsize=(11, 7.5))
    for col, rec in enumerate(("mensa", "plenum")):
        s = sessions.filter((pl.col("recorder") == rec) & pl.col("rate_room").is_not_null())
        w = s.with_columns(
            [pl.col(c) - pl.col(c).mean().over("slot") for c in ("leq_dbfs", "rate_room")]
        )
        for row, (d, kind) in enumerate(((s, "raw"), (w, "within slot"))):
            ax = axes[row][col]
            ax.scatter(
                d["leq_dbfs"], d["rate_room"], s=42, color=COLOR[rec],
                edgecolor=SURFACE, linewidth=1.5, zorder=3,
            )  # fmt: skip
            c = corr.filter(
                (pl.col("level") == "session")
                & (pl.col("recorder") == rec)
                & (pl.col("feature") == "leq_dbfs")
                & (pl.col("measure") == "rate_room")
                & (pl.col("comparison") == kind)
            ).row(0, named=True)
            ax.set_title(
                f"{NAME[rec]}, {kind}\n{RHO} = {c['rho']:.2f} [{c['lo']:.2f}, {c['hi']:.2f}],"
                f" {c['n']} sessions",
                loc="left",
                fontsize=10,
            )
            if kind == "raw":
                ax.set_xlabel("session Leq (dBFS)")
                ax.set_ylabel("presses / 10 person-h in room")
            else:
                ax.axhline(0, color=INK2, lw=0.8)
                ax.axvline(0, color=INK2, lw=0.8)
                ax.set_xlabel("Leq minus its slot mean (dB)")
                ax.set_ylabel("rate minus its slot mean")
    fig.text(
        0.01, 0.005,
        "One dot per recording session (slot x day). Within slot compares the same slot across "
        "days. 95% intervals resample days. Exploratory.",
        color=INK2, fontsize=9,
    )  # fmt: skip
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(out / "fig2_sessions_level_vs_presses.png", dpi=180)
    plt.close(fig)

    # 3. All correlations at a glance, session level: raw vs within slot.
    c = corr.filter(pl.col("level") == "session")
    labels = [(f, m) for f in FEATURES for m in MEASURES]
    fig, axes = plt.subplots(1, 2, figsize=(11, 7), sharey=True)
    for ax, rec in zip(axes, ("mensa", "plenum"), strict=True):
        for i, (f, m) in enumerate(labels):
            y = len(labels) - 1 - i
            for kind, dy, color in (("raw", 0.18, "#a3a29c"), ("within slot", -0.18, COLOR[rec])):
                r = c.filter(
                    (pl.col("recorder") == rec)
                    & (pl.col("feature") == f)
                    & (pl.col("measure") == m)
                    & (pl.col("comparison") == kind)
                )
                if r.is_empty():
                    continue
                r = r.row(0, named=True)
                ax.plot([r["lo"], r["hi"]], [y + dy, y + dy], color=color, lw=2)
                ax.plot(
                    r["rho"], y + dy, "o", color=color, ms=7, mec=SURFACE, mew=1.5,
                    label=kind if i == 0 else None,
                )  # fmt: skip
        ax.axvline(0, color=INK2, lw=0.8)
        ax.set_xlim(-1, 1)
        ax.set_title(NAME[rec], loc="left", fontsize=11)
        ax.legend(loc="lower right")
        for k in range(1, len(FEATURES)):
            ax.axhline(k * len(MEASURES) - 0.5, color=GRID, lw=1)
    axes[0].set_yticks(
        range(len(labels)),
        [f"{FEATURES[f]} vs {MEASURES[m]}" for f, m in reversed(labels)],
        fontsize=9,
    )
    axes[0].grid(axis="y", visible=False)
    axes[1].grid(axis="y", visible=False)
    fig.supxlabel(
        f"Spearman {RHO} with 95% interval, one point per session (intervals resample days)",
        fontsize=10, color=INK2, y=0.04,
    )  # fmt: skip
    fig.text(
        0.01, 0.005,
        "Raw: across all sessions, so time of day drives both. Within slot: the same slot on "
        "different days. Exploratory: no tests.",
        color=INK2, fontsize=9,
    )  # fmt: skip
    fig.tight_layout(rect=(0, 0.02, 1, 1))
    fig.savefig(out / "fig3_correlations.png", dpi=180)
    plt.close(fig)


if __name__ == "__main__":
    main()
