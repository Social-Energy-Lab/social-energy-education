"""When, where and in whose company participants pressed the self-report button.

Research question: RQ1, what do "moved" moments look like from the outside
(`research/questions.md`). Construct: a self-report press marks a moment the wearer felt moved
`[inferred]`; from 14 Aug 08:45 the instruction was widened to moments that are not necessarily
positive (``study.yaml``).

Unit of analysis: the press, compared with the same participants' ordinary 5-minute bins.

Filters, each counted in ``qa.json``:

1. Source: our own ingest of the raw logs (``our_self_reports.parquet``, written by
   ``beacon_diagnostics.py --ingest``), records with ``ok``. It dates each press from its power
   cycle's earliest anchor and recognises a press resent in a later readout as a duplicate. The
   upstream ``Output/self_reports.csv`` dates from each readout's own, often late, stamp, so a
   resent press lands minutes away from its first copy and counts twice.
2. From the instruction (14 Aug 08:45) to the handover (29 Aug 09:00).
3. Resolved through the spine to a participant; presses on location tags are handling artefacts
   and fall out here (``spine/open_questions.md`` Q3).
4. Not in an exclusion window; the wearer in ``spine.consented("self_report")``.
5. Accidental chains: a run of presses each less than ``CHAIN_S`` apart that lasts at least
   ``ACCIDENTAL_S`` or holds at least ``ACCIDENTAL_N`` presses is a button held down by something
   else (a tag in a bag), and is dropped. The firmware creates one event per press of 3 s, with no
   cooldown, so something pressing the tag over and over shows up as a dense run (see the beacons
   instrument doc) `[inferred: both thresholds]`.
6. Episodes: presses by the same wearer less than ``EPISODE_S`` apart are one episode, timed at
   its first press `[inferred: the window length]`. The firmware has no cancel press, so a press
   followed by its retraction is two ordinary events seconds apart and becomes one episode.

Exposure for press rates leaves out each tag's lost windows (``lost_windows.parquet`` from
``beacon_diagnostics.py``): a restart wipes presses held in RAM, so that time cannot count.

Company at a press uses the close co-presence bins built by ``copresence_by_phase.py build``, which
must have run first; it only covers participants who also consented to ``beacons``.

    uv run --extra analysis python studies/dsa-2026/analyses/self_report_context.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
import copresence_by_phase as cp

from social_energy import beacons, paths
from social_energy.spine import Spine

INSTRUCTION = "2026-08-14 08:45:00"
EPISODE_S = 60
CHAIN_S = 20
ACCIDENTAL_S = 60
ACCIDENTAL_N = 8
#: Presses by another close participant within this many minutes count as a shared moment.
SHARED_MIN = 5
LAST_GOOD_DAY = "2026-08-23"  # battery decay after this; see copresence_by_phase notes


def local(s: str) -> pl.Expr:
    return (
        pl.lit(s)
        .str.strptime(pl.Datetime("us"), "%Y-%m-%d %H:%M:%S")
        .dt.replace_time_zone(cp.TZ)
        .dt.convert_time_zone("UTC")
    )


def lost_bins(layout: paths.StudyLayout, spine: Spine) -> pl.DataFrame | None:
    """Person and 5-minute bin inside a tag's lost window, or None if none were computed."""
    path = layout.derived / "analyses" / "beacon-diagnostics" / "lost_windows.parquet"
    if not path.exists():
        return None
    w = spine.resolve(
        pl.read_parquet(path), device_col="beacon", time_col="start", kind="beacon", out="entity"
    ).filter(pl.col("entity").is_not_null())
    return (
        w.with_columns(
            pl.datetime_ranges(
                pl.col("start").dt.truncate(cp.BIN), pl.col("end"), interval=cp.BIN
            ).alias("bin")
        )
        .explode("bin")
        .select("entity", "bin")
        .unique()
    )


def press_episodes(
    layout: paths.StudyLayout, spine: Spine, participants: set[str], consented: set[str]
) -> tuple[pl.DataFrame, dict]:
    """Self-report press episodes of consenting participants, with a QA count per filter."""
    ours = pl.read_parquet(
        layout.derived / "analyses" / "beacon-diagnostics" / "our_self_reports.parquet"
    )
    raw = ours.filter(pl.col("ok")).select(pl.col("beacon").cast(pl.Int64), "t").unique()
    qa = {"rows": ours.height, "rows_ok_unique": raw.height}
    df = raw.filter((pl.col("t") >= local(INSTRUCTION)) & (pl.col("t") < local(cp.HANDOVER)))
    qa["in_window"] = df.height
    df = spine.resolve(df, device_col="beacon", time_col="t", kind="beacon", out="entity")
    df = df.filter(pl.col("entity").is_in(participants))
    qa["participant"] = df.height
    df = spine.flag_excluded(df, device_col="beacon", time_col="t", kind="beacon")
    df = df.filter(~pl.col("excluded") & pl.col("entity").is_in(consented))
    qa["not_excluded_consented"] = df.height
    presses, merged = beacons.press_episodes(
        df.select("entity", "t"),
        chain_s=CHAIN_S,
        accidental_s=ACCIDENTAL_S,
        accidental_n=ACCIDENTAL_N,
        episode_s=EPISODE_S,
    )
    qa |= merged
    presses = presses.with_columns(
        pl.col("t").dt.truncate(cp.BIN).alias("bin"),
        cp.camp_day_expr(pl.col("t")).alias("day"),
        cp.phase_expr(pl.col("t")).alias("phase"),
    )
    return presses, qa


def main() -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    layout = paths.study(cp.STUDY)
    spine = Spine.load(layout.spine)
    out = layout.derived / "analyses" / "self-report-context"
    out.mkdir(parents=True, exist_ok=True)
    participants = {p.ref for p in spine.people if p.role == "participant"}
    consented = {f"person:{p}" for p in spine.consented("self_report")}

    presses, qa = press_episodes(layout, spine, participants, consented)

    # Rate per person-hour seen, by phase, for participants whose tag was read at all. Time inside
    # a lost window (a restart wiped what the tag held) is not exposure: a press there could not
    # have been recorded, though others still saw the tag. Windows come from beacon_diagnostics.
    seen = cp.load_all("seen").filter(pl.col("entity").is_in(consented & participants))
    lost = lost_bins(layout, spine)
    if lost is not None:
        qa["seen_bins"] = seen.height
        seen = seen.join(lost, on=["entity", "bin"], how="anti")
        qa["seen_bins_outside_lost_windows"] = seen.height
        qa["presses_inside_lost_windows"] = presses.join(lost, on=["entity", "bin"]).height
    hours = seen.group_by("phase").agg((pl.len() / 12).alias("person_hours"))
    rate = (
        presses.group_by("phase")
        .agg(pl.len().alias("presses"))
        .join(hours, on="phase")
        .with_columns((pl.col("presses") / pl.col("person_hours") * 10).alias("per_10_hours"))
        .sort(pl.col("phase").replace_strict(cp.PHASE_ORDER, list(range(len(cp.PHASE_ORDER)))))
    )
    daily = (
        presses.group_by("day")
        .agg(pl.len().alias("presses"), pl.col("entity").n_unique().alias("pressers"))
        .sort("day")
    )

    # Company: close participants in the press's bin vs in that person's ordinary bins.
    pairs = cp.load_all("pairs").filter(pl.col("max_rssi") >= cp.CLOSE_RSSI)
    ends = pl.concat(
        [
            pairs.select(pl.col("a").alias("entity"), "bin", pl.col("b").alias("other")),
            pairs.select(pl.col("b").alias("entity"), "bin", pl.col("a").alias("other")),
        ]
    )
    ends = ends.filter(pl.col("other").is_in(participants))
    n_close = ends.group_by("entity", "bin").agg(pl.len().alias("close"))
    beacon_people = {f"person:{p}" for p in spine.consented("beacons")}
    with_company = (
        presses.filter(pl.col("entity").is_in(beacon_people))
        .join(n_close, on=["entity", "bin"], how="left")
        .with_columns(pl.col("close").fill_null(0))
    )
    base = (
        seen.filter(pl.col("entity").is_in(with_company["entity"].unique().implode()))
        .join(n_close, on=["entity", "bin"], how="left")
        .with_columns(pl.col("close").fill_null(0))
    )
    company = (
        pl.concat(
            [
                with_company.select("phase", "close", pl.lit("at a press").alias("when")),
                base.select("phase", "close", pl.lit("ordinary 5 minutes").alias("when")),
            ]
        )
        .group_by("when", "phase")
        .agg(
            pl.col("close").mean().alias("close_others"),
            (pl.col("close") == 0).mean().alias("alone_share"),
        )
        .sort("phase", "when")
    )
    overall = (
        pl.concat(
            [
                with_company.select("close", pl.lit("at a press").alias("when")),
                base.select("close", pl.lit("ordinary 5 minutes").alias("when")),
            ]
        )
        .group_by("when")
        .agg(pl.col("close").mean(), (pl.col("close") == 0).mean().alias("alone"))
    )

    # Shared moments: another close participant also pressed within ±SHARED_MIN minutes.
    pr = presses.select("entity", "t", "bin")
    near = (
        pr.join(ends, on=["entity", "bin"])
        .join(pr.select(pl.col("entity").alias("other"), pl.col("t").alias("t_other")), on="other")
        .filter((pl.col("t_other") - pl.col("t")).abs() <= pl.duration(minutes=SHARED_MIN))
        .select("entity", "t")
        .unique()
    )
    shared = near.height / max(with_company.height, 1)
    # Chance: the same test with every press moved to the same clock time one day later.
    shifted = pr.with_columns(
        pl.col("t") + pl.duration(days=1), pl.col("bin") + pl.duration(days=1)
    )
    near_shift = (
        shifted.join(ends, on=["entity", "bin"])
        .join(pr.select(pl.col("entity").alias("other"), pl.col("t").alias("t_other")), on="other")
        .filter((pl.col("t_other") - pl.col("t")).abs() <= pl.duration(minutes=SHARED_MIN))
        .select("entity", "t")
        .unique()
    )
    in_company_shift = shifted.join(ends.select("entity", "bin").unique(), on=["entity", "bin"])
    in_company = pr.join(ends.select("entity", "bin").unique(), on=["entity", "bin"])
    shared_stats = {
        "presses_with_beacon_data": with_company.height,
        "share_shared_within_5min_with_a_close_other": shared,
        "share_among_presses_in_company": near.height / max(in_company.height, 1),
        "chance_same_clock_next_day_among_in_company": near_shift.height
        / max(in_company_shift.height, 1),
    }

    for name, t in {
        "rate_by_phase": rate,
        "daily": daily,
        "company_by_phase": company,
        "company_overall": overall,
    }.items():
        t.write_csv(out / f"{name}.csv")
    (out / "qa.json").write_text(json.dumps({"qa": qa, "shared": shared_stats}, indent=2))

    plt.rcParams.update(
        {
            "font.size": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.color": "#e4e3df",
            "grid.linewidth": 0.6,
        }
    )
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    axes[0].bar(rate["phase"].to_list(), rate["per_10_hours"].to_list(), color=cp.BLUE, width=0.6)
    axes[0].set_title("Presses per 10 participant-hours, by time of day", loc="left", fontsize=10)
    ph = company.pivot(on="when", index="phase", values="close_others")
    ph = ph.sort(pl.col("phase").replace_strict(cp.PHASE_ORDER, list(range(len(cp.PHASE_ORDER)))))
    x = range(ph.height)
    axes[1].bar(
        [i - 0.2 for i in x],
        ph["ordinary 5 minutes"].to_list(),
        0.4,
        color=cp.GRAY,
        label="ordinary 5 minutes",
    )
    axes[1].bar(
        [i + 0.2 for i in x], ph["at a press"].to_list(), 0.4, color=cp.BLUE, label="at a press"
    )
    axes[1].set_xticks(list(x), ph["phase"].to_list())
    axes[1].legend(frameon=False)
    axes[1].set_title("Participants at close range", loc="left", fontsize=10)
    for ax in axes:
        ax.tick_params(axis="x", rotation=30)
    fig.tight_layout()
    fig.savefig(out / "fig_self_reports.png", dpi=160)
    print(json.dumps({"qa": qa, "shared": shared_stats}, indent=2, default=str))
    print(rate, daily, company, overall, sep="\n")


if __name__ == "__main__":
    main()
