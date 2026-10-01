"""Instrument diagnostics for the DSA 2026 beacons: one figure per open question.

Not a research analysis. It backs the questions to the firmware team and the analysis choices put
to the research team with data, so each question arrives with the evidence that raised it. All
figures are aggregates over tags; none shows a person.

Filters: contacts and presses go through the spine exactly as in ``copresence_by_phase.py``
(window, both sides resolved, exclusions on both sides, consent). The timestamp comparison is
device-level by nature and keeps only presses that resolve to a consenting person.

Inputs: ``copresence_by_phase.py build`` must have run. The timestamp comparison needs our own
ingest of the logs without contact lines, which this script produces itself (``--ingest``); the
full logs do not fit in memory on the machine that ran this.

    uv run --extra analysis python studies/dsa-2026/analyses/beacon_diagnostics.py [--ingest]
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
import copresence_by_phase as cp

from social_energy import paths
from social_energy.beacons.ingest import ingest_logs
from social_energy.spine import Spine
from social_energy.study import StudyConfig

SLUG = "beacon-diagnostics"
#: Days whose tags were healthy, used wherever a "typical day" is needed.
TYPICAL = [date(2026, 8, d) for d in range(14, 24)]
INK, INK2 = "#0b0b0b", "#52514e"


def out_dir() -> Path:
    d = paths.study(cp.STUDY).derived / "analyses" / SLUG
    d.mkdir(parents=True, exist_ok=True)
    return d


def ingest_without_contacts() -> None:
    """Our ingest over every log with contact lines removed: readouts, presses, eco sessions."""
    layout = paths.study(cp.STUDY)
    work = out_dir() / "nocontacts"
    work.mkdir(exist_ok=True)
    for log in sorted((layout.raw / "beacons" / "Logs").glob("*.log")):
        with (
            log.open(encoding="utf-8", errors="replace") as src,
            (work / log.name).open("w") as dst,
        ):
            dst.writelines(line for line in src if ",ID2: " not in line)
    study = StudyConfig.load(cp.STUDY_YAML)
    tables = ingest_logs(sorted(work.glob("*.log")), study.beacon_config())
    tables.self_reports.write_parquet(out_dir() / "our_self_reports.parquet")
    tables.readouts.write_parquet(out_dir() / "our_readouts.parquet")
    tables.eco_sessions.write_parquet(out_dir() / "our_eco.parquet")
    (out_dir() / "qa_ingest.json").write_text(json.dumps(tables.qa, indent=2))


def resets(work: Path) -> pl.DataFrame:
    """Tag restarts, read straight off the logs' clock anchors.

    Within one power cycle, readout time minus uptime is constant up to the logger's timestamp
    jitter (minutes). A restart shows as uptime falling behind elapsed wall time by more than an
    hour. Everything the tag stored since its previous readout was in RAM and is gone, so the lost
    window runs from that readout to the restart `[inferred: the 1 h margin]`.
    """
    rows = []
    for log in sorted(work.glob("*.log")):
        for line in log.open(encoding="utf-8", errors="replace"):
            if ",Current Timer: " not in line:
                continue
            ts, tag, rest = line.strip().split(",", 2)
            try:
                rows.append((ts, int(tag.split(":")[1]), int(rest.split(":")[1])))
            except ValueError:
                continue
    r = (
        pl.DataFrame(rows, schema=["ts", "beacon", "timer"], orient="row")
        .with_columns(
            pl.col("ts")
            .str.strptime(pl.Datetime("us"), "%Y-%m-%d %H:%M:%S")
            .dt.replace_time_zone(cp.TZ)
        )
        .unique()
        .sort("beacon", "ts", "timer")
        .with_columns(
            (pl.col("ts") - pl.duration(seconds=pl.col("timer"))).alias("boot"),
            pl.col("ts").shift().over("beacon").alias("prev_ts"),
            pl.col("timer").shift().over("beacon").alias("prev_timer"),
        )
    )
    elapsed = (pl.col("ts") - pl.col("prev_ts")).dt.total_seconds()
    return r.filter(
        pl.col("prev_timer").is_not_null()
        & (pl.col("timer") < pl.col("prev_timer") + elapsed - 3600)
    ).with_columns(pl.max_horizontal("prev_ts", pl.min_horizontal("boot", "ts")).alias("boot"))


def anchors(work: Path) -> pl.DataFrame:
    """Every clock anchor in the logs, with its power cycle and that cycle's earliest start.

    ``implied`` = readout PC time minus uptime. Within a power cycle it should be constant; it only
    ever sits above the cycle's minimum (the PC stamps late), so ``cycle_start`` = that minimum is
    the best estimate of when the cycle began, and ``delay_s`` how late each stamp was.
    """
    rows = []
    for log in sorted(work.glob("*.log")):
        for line in log.open(encoding="utf-8", errors="replace"):
            if ",Current Timer: " not in line:
                continue
            ts, tag, rest = line.strip().split(",", 2)
            try:
                rows.append((ts, int(tag.split(":")[1]), int(rest.split(":")[1])))
            except ValueError:
                continue
    elapsed = (pl.col("ts") - pl.col("ts").shift().over("beacon")).dt.total_seconds()
    restart = pl.col("timer") < pl.col("timer").shift().over("beacon") + elapsed - 3600
    return (
        pl.DataFrame(rows, schema=["ts", "beacon", "timer"], orient="row")
        .with_columns(
            pl.col("ts")
            .str.strptime(pl.Datetime("us"), "%Y-%m-%d %H:%M:%S")
            .dt.replace_time_zone(cp.TZ)
            .dt.convert_time_zone("UTC")
        )
        .unique()
        .sort("beacon", "ts", "timer")
        .with_columns((pl.col("ts") - pl.duration(seconds=pl.col("timer"))).alias("implied"))
        .with_columns(restart.fill_null(True).cum_sum().over("beacon").alias("cycle"))
        .with_columns(pl.col("implied").min().over("beacon", "cycle").alias("cycle_start"))
        .with_columns(
            (pl.col("implied") - pl.col("cycle_start")).dt.total_seconds().alias("delay_s")
        )
    )


def timing_check(log_names: list[str]) -> dict:
    """Do mirrored contacts line up better after dating from each cycle's earliest anchor?

    For a tag pair, A hearing B and B hearing A should happen within seconds. For each pair, the
    median gap to the nearest mirrored record is compared as dated by our ingest and as
    (cycle start + uptime). Runs our full ingest on the given logs only, because the whole camp
    does not fit in memory; the cycles come from the anchors of every log.
    """
    layout = paths.study(cp.STUDY)
    study = StudyConfig.load(cp.STUDY_YAML)
    files = [layout.raw / "beacons" / "Logs" / n for n in log_names]
    contacts = ingest_logs(files, study.beacon_config()).contacts.filter(pl.col("ok"))
    c = contacts.select(
        pl.col("beacon").cast(pl.Int64), pl.col("observed").cast(pl.Int64), "t", "uptime_s"
    )
    an = anchors(out_dir() / "nocontacts")
    cycles = an.group_by("beacon", "cycle").agg(pl.col("cycle_start").first()).sort("cycle_start")
    c = (
        c.sort("t")
        .join_asof(
            cycles.select("beacon", "cycle_start"),
            left_on="t",
            right_on="cycle_start",
            by="beacon",
            strategy="backward",
            check_sortedness=False,
        )
        .with_columns((pl.col("cycle_start") + pl.duration(seconds=pl.col("uptime_s"))).alias("t2"))
        .filter(((pl.col("t2") - pl.col("t")).dt.total_seconds()).abs() < 7200)
    )

    def pair_offsets(col: str):
        ab = c.select(
            pl.col("beacon").alias("x"), pl.col("observed").alias("y"), pl.col(col).alias("t")
        )
        ba = ab.rename({"x": "y", "y": "x", "t": "tb"})
        j = (
            ab.unique()
            .sort("t")
            .join_asof(
                ba.unique().sort("tb"),
                left_on="t",
                right_on="tb",
                by=["x", "y"],
                strategy="nearest",
                check_sortedness=False,
            )
            .with_columns((pl.col("tb") - pl.col("t")).dt.total_seconds().alias("d"))
            .filter(pl.col("d").abs() < 3600)
        )
        per = j.group_by("x", "y").agg(pl.col("d").median().alias("md"), pl.len().alias("n"))
        return per.filter(pl.col("n") >= 20)

    result = {
        "files": log_names,
        "anchor_delay_s_median": float(an["delay_s"].median()),
        "anchor_delay_s_p90": float(an["delay_s"].quantile(0.9)),
    }
    for col, name in (("t", "as_dated"), ("t2", "cycle_start_corrected")):
        per = pair_offsets(col)
        md = per["md"].abs()
        result[name] = {
            "pairs": per.height,
            "median_s": float(md.median()),
            "share_over_60s": float((md > 60).mean()),
            "share_over_300s": float((md > 300).mean()),
        }
        if col == "t":
            bias = per.group_by("x").agg(pl.col("md").median().alias("b"), pl.len().alias("k"))
            bias = bias.filter(pl.col("k") >= 5)["b"].abs()
            result["per_tag_bias_s"] = {
                "median": float(bias.median()),
                "p90": float(bias.quantile(0.9)),
            }
    return result


def style(plt) -> None:
    plt.rcParams.update(
        {
            "font.size": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.color": "#e4e3df",
            "grid.linewidth": 0.6,
            "axes.titlesize": 10,
            "axes.titlelocation": "left",
            "text.color": INK,
            "axes.labelcolor": INK2,
        }
    )


def upstream_presses(layout) -> pl.DataFrame:
    return pl.read_csv(layout.raw / "beacons" / "Output" / "self_reports.csv").select(
        pl.col("ID").alias("beacon"),
        pl.col("Local Time")
        .str.strptime(pl.Datetime("us"), "%Y-%m-%d %H:%M:%S")
        .dt.replace_time_zone(cp.TZ)
        .dt.convert_time_zone("UTC")
        .alias("t"),
    )


def consenting_presses(df: pl.DataFrame, spine: Spine) -> pl.DataFrame:
    ok = {f"person:{p}" for p in spine.consented("self_report")}
    return spine.resolve(
        df.with_columns(pl.col("beacon").cast(pl.Int64)),
        device_col="beacon",
        time_col="t",
        kind="beacon",
        out="entity",
    ).filter(pl.col("entity").is_in(ok))


def main() -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    style(plt)
    layout = paths.study(cp.STUDY)
    spine = Spine.load(layout.spine)
    out = out_dir()
    if "--ingest" in sys.argv or not (out / "our_self_reports.parquet").exists():
        ingest_without_contacts()
    summary: dict = {}
    participants = {p.ref for p in spine.people if p.role == "participant"}
    person_tags = {
        int(a.device.split(":")[1])
        for a in spine.assignments
        if a.device_kind == "beacon" and a.entity.startswith("person:")
    }

    # ---- 1. Timestamps: our ingest vs Output/self_reports.csv ---------------------------------
    ours = (
        consenting_presses(
            pl.read_parquet(out / "our_self_reports.parquet").filter(pl.col("ok")), spine
        )
        .select("beacon", "t", "source")
        .unique(["beacon", "t"])
    )
    up = consenting_presses(upstream_presses(layout), spine).select("beacon", "t").unique()
    exact = ours.join(up, on=["beacon", "t"], how="semi")
    ours_only = ours.join(up, on=["beacon", "t"], how="anti")
    up_only = up.join(ours, on=["beacon", "t"], how="anti")
    nearest = (
        ours_only.sort("t")
        .join_asof(
            up.sort("t").rename({"t": "tu"}),
            left_on="t",
            right_on="tu",
            by="beacon",
            strategy="nearest",
            check_sortedness=False,
        )
        .with_columns(((pl.col("t") - pl.col("tu")).dt.total_seconds() / 3600).alias("hours"))
    )
    summary["timestamps"] = {
        "ours_ok": ours.height,
        "upstream": up.height,
        "exact_match": exact.height,
        "ours_only": ours_only.height,
        "upstream_only": up_only.height,
        "ours_only_by_file": dict(ours_only.group_by("source").len().sort("source").iter_rows()),
        "ours_later_than_nearest_upstream": int((nearest["hours"] > 0).sum()),
    }
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8), gridspec_kw={"width_ratios": [1, 1.4]})
    cats = ["same second", "ours only", "upstream only"]
    vals = [exact.height, ours_only.height, up_only.height]
    axes[0].barh(cats[::-1], vals[::-1], color=[cp.GRAY, cp.ORANGE, cp.BLUE][::-1], height=0.6)
    for i, v in enumerate(vals[::-1]):
        axes[0].annotate(f"{v:,}", (v, i), xytext=(4, 0), textcoords="offset points", va="center")
    axes[0].set_title("Self-reports: our ingest vs Output/self_reports.csv")
    axes[0].set_xlabel("presses (whole camp, consenting participants)")
    h = nearest["hours"].drop_nulls().to_numpy()
    axes[1].hist(h, bins=np.logspace(-1, np.log10(max(h.max(), 1) * 1.1), 30), color=cp.ORANGE)
    axes[1].set_xscale("log")
    axes[1].set_title("Ours-only presses: how much later than the nearest upstream press")
    axes[1].set_xlabel("hours later (log scale)")
    axes[1].set_ylabel("presses")
    axes[1].annotate(
        "all from the last readouts, 28-29 Aug",
        (0.02, 0.92),
        xycoords="axes fraction",
        color=INK2,
        fontsize=9,
    )
    fig.tight_layout()
    fig.savefig(out / "q_timestamps.png", dpi=160)
    plt.close(fig)

    # ---- 2. Tag health per day: voltage, two-sided detection, hours seen -----------------------
    readouts = pl.read_parquet(out / "our_readouts.parquet").filter(
        pl.col("voltage_mv").is_not_null() & pl.col("beacon").is_in(list(person_tags))
    )
    volt = (
        readouts.with_columns(cp.camp_day_expr(pl.col("pc_time")).alias("day"))
        .group_by("day")
        .agg(
            pl.col("voltage_mv").quantile(0.25).alias("q25"),
            pl.col("voltage_mv").median().alias("med"),
            pl.col("voltage_mv").quantile(0.75).alias("q75"),
        )
        .sort("day")
    )
    pairs = cp.load_all("pairs").filter(pl.col("a").is_in(participants))
    two_sided = (
        pairs.group_by("day").agg((pl.col("directions") == 2).mean().alias("both")).sort("day")
    )
    seen = cp.load_all("seen").filter(pl.col("entity").is_in(participants))
    hours = (
        seen.group_by("day")
        .agg((pl.len() / pl.col("entity").n_unique() / 12).alias("h"))
        .sort("day")
    )
    days = [cp.FIRST_DAY + timedelta(d) for d in range(16)]

    def on_days(df, col):
        m = dict(zip(df["day"].to_list(), df[col].to_list(), strict=True))
        return [m.get(d) for d in days]

    lab = [d.strftime("%d") for d in days]
    fig, axes = plt.subplots(3, 1, figsize=(10, 7.5), sharex=True)
    med, lo, hi = on_days(volt, "med"), on_days(volt, "q25"), on_days(volt, "q75")
    axes[0].errorbar(
        lab,
        med,
        yerr=[
            [m - q for m, q in zip(med, lo, strict=True)],
            [q - m for m, q in zip(med, hi, strict=True)],
        ],
        fmt="o",
        color=cp.BLUE,
        ecolor=cp.BLUE,
        elinewidth=1.5,
        capsize=0,
        ms=5,
    )
    axes[0].set_title("Person-tag battery voltage at readout (median, middle half)")
    axes[0].set_ylabel("mV")
    axes[1].plot(lab, on_days(two_sided, "both"), color=cp.BLUE, lw=2, marker="o", ms=4)
    axes[1].set_title("Share of close pair contacts heard from both sides")
    axes[2].plot(lab, on_days(hours, "h"), color=cp.BLUE, lw=2, marker="o", ms=4)
    axes[2].set_title("Hours per day a participant's tag appears in any contact")
    axes[2].set_xlabel("August (camp day, 07:30-07:30)")
    for ax in axes:
        ax.axvspan(lab.index("24") - 0.5, lab.index("27") + 0.5, color="#f1f0ec", zorder=0)
    fig.tight_layout()
    fig.savefig(out / "q_battery.png", dpi=160)
    plt.close(fig)
    summary["battery"] = {"voltage_median_by_day": dict(zip(lab, med, strict=True))}

    # ---- 3. Hour of day: contacts, eco mode, presses -------------------------------------------
    ph_rows, rssi_hist, per_min, tag_rssi, asym = [], np.zeros(111), np.zeros(200), [], []
    for d in TYPICAL:
        raw = cp.read_upstream_contacts(
            layout.raw / "beacons" / "Output" / f"contacts_{d:%Y%m%d}.csv"
        )
        df = cp.resolve_contacts(raw, spine, {})
        del raw
        pp = df.filter(
            pl.col("observer_entity").is_in(participants)
            & pl.col("observed_entity").is_in(participants)
        )
        local = pp["t"].dt.convert_time_zone(cp.TZ)
        ph_rows.append(local.dt.hour().value_counts().rename({"t": "hour"}))
        r = np.clip(-pp["rssi"].to_numpy(), 0, 110)
        rssi_hist += np.bincount(r, minlength=111)[:111]
        pm = pp.group_by("observer", "observed", pl.col("t").dt.truncate("1m")).len()["len"]
        per_min += np.bincount(np.clip(pm.to_numpy(), 0, 199), minlength=200)[:200]
        # Tag offsets: the same pair heard from both sides in the same minute. If tags were
        # identical, A hearing B and B hearing A would differ only by noise.
        pm_max = pp.group_by("observer", "observed", pl.col("t").dt.truncate("1m")).agg(
            pl.col("rssi").max()
        )
        both = pm_max.join(
            pm_max.rename({"observer": "observed", "observed": "observer", "rssi": "back"}),
            on=["observer", "observed", "t"],
        ).with_columns((pl.col("rssi") - pl.col("back")).alias("diff"))
        tag_rssi.append(
            both.group_by("observer").agg(pl.col("diff").sum().alias("s"), pl.len().alias("n"))
        )
        asym.append(both["diff"].to_numpy())
    by_hour = pl.concat(ph_rows).group_by("hour").agg(pl.col("count").sum() / len(TYPICAL))
    by_hour = by_hour.sort("hour")

    eco = pl.read_parquet(out / "our_eco.parquet").filter(
        pl.col("ok") & pl.col("beacon").is_in(list(person_tags))
    )
    eco = eco.with_columns(
        pl.col("t_enter").dt.convert_time_zone(cp.TZ).alias("a"),
        pl.col("t_leave").dt.convert_time_zone(cp.TZ).alias("b"),
    ).filter(pl.col("a").dt.date().is_in(TYPICAL))
    eco_min = np.zeros(24)
    for a, b in eco.select("a", "b").iter_rows():
        t = a
        while t < b:
            nxt = min(b, (t + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0))
            eco_min[t.hour] += (nxt - t).total_seconds() / 60
            t = nxt
    n_tags = eco["beacon"].n_unique() or 1
    eco_share = eco_min / (len(TYPICAL) * n_tags * 60)

    presses = consenting_presses(upstream_presses(layout), spine).with_columns(
        pl.col("t").dt.convert_time_zone(cp.TZ).alias("lt")
    )
    presses = presses.filter(pl.col("lt").dt.date().is_in(TYPICAL))
    press_h = presses["lt"].dt.hour().value_counts().rename({"lt": "hour"}).sort("hour")

    hrs = list(range(24))

    def per_hour(df, col):
        m = dict(zip(df["hour"].to_list(), df[col].to_list(), strict=True))
        return [m.get(h, 0) for h in hrs]

    fig, axes = plt.subplots(3, 1, figsize=(10, 7.5), sharex=True)
    axes[0].bar(hrs, per_hour(by_hour, "count"), color=cp.BLUE, width=0.8)
    axes[0].set_title("Participant-to-participant contact rows per hour (mean of 14-23 Aug)")
    axes[1].bar(hrs, eco_share, color=cp.BLUE, width=0.8)
    axes[1].set_title("Share of person-tag time in eco mode (scanning 100 ms every 5 min)")
    axes[1].set_ylim(0, 1)
    axes[2].bar(
        hrs, [v / len(TYPICAL) for v in per_hour(press_h, "count")], color=cp.BLUE, width=0.8
    )
    axes[2].set_title("Raw self-report rows per hour (mean of 14-23 Aug)")
    axes[2].set_xticks(hrs)
    axes[2].set_xlabel("hour of day (local)")
    for ax in axes:
        for _, start in cp.PHASES:
            ax.axvline(start.hour + start.minute / 60 - 0.5, color=cp.GRAY, lw=0.8, ls="--")
    for i, (name, start) in enumerate(cp.PHASES):
        axes[0].annotate(
            name,
            (start.hour + start.minute / 60 - 0.4, 1.0 - 0.09 * (i % 2)),
            xycoords=("data", "axes fraction"),
            fontsize=8,
            color=INK2,
            va="top",
        )
    fig.tight_layout()
    fig.savefig(out / "q_hour_of_day.png", dpi=160)
    plt.close(fig)
    summary["eco_share_by_hour"] = [round(float(x), 3) for x in eco_share]

    # ---- 4. RSSI distribution and tag-to-tag spread --------------------------------------------
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8))
    x = -np.arange(111)
    axes[0].bar(x[40:81], rssi_hist[40:81] / rssi_hist.sum(), color=cp.BLUE, width=0.9)
    for thr in (-80, -70, -65, -60):
        axes[0].axvline(thr, color=cp.ORANGE if thr == -65 else cp.GRAY, lw=1.2, ls="--")
        axes[0].annotate(
            f"{thr}",
            (thr, 0.97),
            xycoords=("data", "axes fraction"),
            fontsize=8,
            color=INK2,
            ha="left",
            va="top",
            xytext=(2, 0),
            textcoords="offset points",
        )
    axes[0].set_title("RSSI of participant-to-participant contacts, 14-23 Aug")
    axes[0].set_xlabel("dBm")
    axes[0].set_ylabel("share of rows")
    tr = (
        pl.concat(tag_rssi)
        .group_by("observer")
        .agg(pl.col("s").sum(), pl.col("n").sum())
        .filter(pl.col("n") >= 500)
        .with_columns((pl.col("s") / pl.col("n")).alias("offset"))
        .sort("offset")
    )
    diffs = np.concatenate(asym)
    axes[1].scatter(range(tr.height), tr["offset"].to_list(), color=cp.BLUE, s=14)
    axes[1].axhline(0, color=cp.GRAY, lw=1)
    axes[1].set_xticks([])
    axes[1].set_xlabel("person tags, sorted (no IDs)")
    axes[1].set_title("Per-tag offset: how much stronger a tag hears than it is heard")
    axes[1].set_ylabel("dB (same pair, same minute)")
    fig.tight_layout()
    fig.savefig(out / "q_rssi.png", dpi=160)
    plt.close(fig)
    summary["rssi"] = {
        "share_at_or_above": {
            str(t): float(rssi_hist[: -t + 1].sum() / rssi_hist.sum()) for t in (-80, -70, -65, -60)
        },
        "tag_offset_db_range": [float(tr["offset"].min()), float(tr["offset"].max())],
        "tag_offset_db_iqr": [float(x) for x in np.percentile(tr["offset"].to_numpy(), [25, 75])],
        "same_minute_pair_diff_sd_db": float(diffs.std()),
    }

    # ---- 5. Rows per heard pair per minute -----------------------------------------------------
    fig, ax = plt.subplots(figsize=(8, 3.6))
    k = np.arange(1, 13)
    ax.bar(k, per_min[1:13] / per_min[1:].sum(), color=cp.BLUE, width=0.8)
    ax.axvline(60 / 7, color=cp.ORANGE, lw=1.2, ls="--")
    ax.annotate(
        "one scan every 7 s",
        (60 / 7, 0.95),
        xycoords=("data", "axes fraction"),
        xytext=(4, 0),
        textcoords="offset points",
        fontsize=8,
        color=INK2,
    )
    ax.set_title("Contact rows per (tag, heard tag, minute), 14-23 Aug")
    ax.set_xlabel("rows in the minute")
    ax.set_ylabel("share of tag-minutes")
    fig.tight_layout()
    fig.savefig(out / "q_rows_per_minute.png", dpi=160)
    plt.close(fig)
    summary["rows_per_minute_share_above_9"] = float(per_min[10:].sum() / per_min[1:].sum())

    # ---- 6. Self-report gaps: held press vs cancelling second press ----------------------------
    pr = consenting_presses(upstream_presses(layout), spine).unique().sort("beacon", "t")
    gaps = (
        pr.with_columns(pl.col("t").diff().over("beacon").dt.total_seconds().alias("gap"))["gap"]
        .drop_nulls()
        .to_numpy()
    )
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8))
    axes[0].hist(gaps[gaps >= 1], bins=np.logspace(0, 5, 60), color=cp.BLUE)
    axes[0].set_xscale("log")
    axes[0].axvline(60, color=cp.ORANGE, lw=1.2, ls="--")
    axes[0].set_title("Time between consecutive presses on one tag")
    axes[0].set_xlabel("seconds (log scale; 60 s = our merge window)")
    axes[0].set_ylabel("pairs of presses")
    axes[1].hist(gaps[gaps < 60], bins=np.arange(0, 61, 1), color=cp.BLUE)
    axes[1].set_title("Zoom: gaps under one minute, 1-second bins")
    axes[1].set_xlabel("seconds")
    fig.tight_layout()
    fig.savefig(out / "q_press_gaps.png", dpi=160)
    plt.close(fig)
    burst = (
        pr.with_columns(
            (pl.col("t").diff().over("beacon").dt.total_seconds().fill_null(999) >= 60)
            .cum_sum()
            .over("beacon")
            .alias("b")
        )
        .group_by("beacon", "b")
        .len()["len"]
    )
    summary["presses"] = {
        "gaps_under_60s": int((gaps < 60).sum()),
        "gap_quartiles_under_60s": [float(q) for q in np.percentile(gaps[gaps < 60], [25, 50, 75])],
        "burst_size_counts": {
            int(k): int(v)
            for k, v in zip(*np.unique(burst.to_numpy(), return_counts=True), strict=True)
        },
    }

    # ---- 7. Room placement: how decisive is the strongest room tag -----------------------------
    rooms = cp.load_all("rooms").filter(pl.col("entity").is_in(participants))
    fig, ax = plt.subplots(figsize=(8, 3.6))
    ax.hist(rooms["share"].to_numpy(), bins=np.linspace(0, 1, 21), color=cp.BLUE)
    ax.set_title("Share of a 5-minute bin's room-tag readings that go to the winning room")
    ax.set_xlabel("share (1 = only one room tag heard)")
    ax.set_ylabel("person-bins")
    fig.tight_layout()
    fig.savefig(out / "q_room_placement.png", dpi=160)
    plt.close(fig)
    summary["room_share_median"] = float(rooms["share"].median())

    # ---- 8. Threshold sensitivity for the co-presence definition -------------------------------
    pairs_p = cp.load_all("pairs").filter(
        pl.col("a").is_in(participants)
        & pl.col("b").is_in(participants)
        & pl.col("day").is_in(TYPICAL)
    )
    n_people = seen.filter(pl.col("day").is_in(TYPICAL))["entity"].n_unique()
    thresholds, minutes = [-80, -75, -70, -65, -60, -55], [15, 30, 60, 120]
    grid = np.zeros((len(minutes), len(thresholds)))
    for i, mins in enumerate(minutes):
        for j, thr in enumerate(thresholds):
            ties = (
                pairs_p.filter(pl.col("max_rssi") >= thr)
                .group_by("day", "a", "b")
                .len()
                .filter(pl.col("len") >= mins // 5)
            )
            grid[i, j] = 2 * ties.height / len(TYPICAL) / n_people
    fig, ax = plt.subplots(figsize=(8, 3.6))
    im = ax.imshow(grid, cmap="Blues", aspect="auto")
    ax.set_xticks(range(len(thresholds)), [f"{t}" for t in thresholds])
    ax.set_yticks(range(len(minutes)), [f"{m} min" for m in minutes])
    ax.grid(False)
    for i in range(len(minutes)):
        for j in range(len(thresholds)):
            v = grid[i, j]
            ax.annotate(
                f"{v:.0f}",
                (j, i),
                ha="center",
                va="center",
                fontsize=9,
                color="white" if v > grid.max() * 0.55 else INK,
            )
    ax.add_patch(plt.Rectangle((2.5, 1.5), 1, 1, fill=False, ec=cp.ORANGE, lw=2))
    ax.set_xlabel("closeness threshold (dBm)")
    ax.set_ylabel("time together per day")
    ax.set_title(f"Mean ties per participant per day, 14-23 Aug (of {n_people - 1} possible)")
    fig.colorbar(im, ax=ax)
    fig.tight_layout()
    fig.savefig(out / "q_threshold_grid.png", dpi=160)
    plt.close(fig)
    summary["threshold_grid"] = {
        f"{m}min": dict(zip(map(str, thresholds), grid[i].round(1).tolist(), strict=True))
        for i, m in enumerate(minutes)
    }

    # ---- 9. Restarts: how often tags reset, and how much unread data each reset wiped -----------
    all_resets = resets(out / "nocontacts")
    # The lost windows, for every tag, in a table other analyses join: a press or a one-sided
    # measure inside one cannot be observed, so it belongs outside the exposure.
    all_resets.select(
        "beacon",
        pl.col("prev_ts").dt.convert_time_zone("UTC").alias("start"),
        pl.col("boot").dt.convert_time_zone("UTC").alias("end"),
    ).filter(pl.col("end") > pl.col("start")).write_parquet(out / "lost_windows.parquet")
    rs = all_resets.filter(pl.col("beacon").is_in(list(person_tags)))
    days9 = [cp.FIRST_DAY + timedelta(d) for d in range(16)]
    lost = np.zeros(len(days9))
    for a, b in rs.select("prev_ts", "boot").iter_rows():
        t = a
        while t < b:
            nxt = min(b, (t + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0))
            i = (t.date() - cp.FIRST_DAY).days
            if 0 <= i < len(days9):
                lost[i] += (nxt - t).total_seconds() / 3600
            t = nxt
    lost_share = lost / (len(person_tags) * 24)
    per_day = rs.group_by(pl.col("boot").dt.date().alias("d")).len()
    n_by_day = dict(zip(per_day["d"].to_list(), per_day["len"].to_list(), strict=True))
    lab9 = [d.strftime("%d") for d in days9]
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.2), gridspec_kw={"width_ratios": [1.2, 1.2, 1]})
    axes[0].bar(lab9, [n_by_day.get(d, 0) for d in days9], color=cp.BLUE, width=0.75)
    axes[0].set_title("Person-tag restarts per day")
    axes[0].set_xlabel("August")
    axes[1].bar(lab9, lost_share, color=cp.ORANGE, width=0.75)
    axes[1].set_title("Share of person-tag time wiped by a restart")
    axes[1].set_xlabel("August")
    axes[1].set_ylim(0, max(0.3, float(lost_share.max()) * 1.15))
    hours_rs = rs["boot"].dt.hour().value_counts().rename({"boot": "hour"})
    hm = dict(zip(hours_rs["hour"].to_list(), hours_rs["count"].to_list(), strict=True))
    axes[2].bar(range(24), [hm.get(h, 0) for h in range(24)], color=cp.BLUE, width=0.8)
    axes[2].set_title("Restarts by hour of day")
    axes[2].set_xlabel("hour (local)")
    axes[2].set_xticks(range(0, 24, 3))
    fig.tight_layout()
    fig.savefig(out / "q_resets.png", dpi=160)
    plt.close(fig)
    lost_h = ((pl.col("boot") - pl.col("prev_ts")).dt.total_seconds() / 3600).alias("h")
    summary["resets"] = {
        "person_tag_resets": rs.height,
        "tags_with_reset": rs["beacon"].n_unique(),
        "person_tags": len(person_tags),
        "lost_window_hours_quartiles": [
            float(x) for x in np.percentile(rs.select(lost_h)["h"].to_numpy(), [25, 50, 75])
        ],
        "lost_share_by_day": dict(zip(lab9, lost_share.round(3).tolist(), strict=True)),
    }

    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    if "--timing" in sys.argv:
        # Two log files of one mid-camp day: enough pairs, and it fits in memory.
        res = timing_check(["dsa_20260820_0828.log", "dsa_20260820_1227.log"])
        (out_dir() / "timing_check.json").write_text(json.dumps(res, indent=2))
        print(json.dumps(res, indent=2))
    else:
        main()
