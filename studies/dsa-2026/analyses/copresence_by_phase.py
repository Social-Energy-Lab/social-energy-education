"""Co-presence networks over DSA 2026, by day and by phase of the day.

Research question: RQ3, embedded vs peripheral participation and formal vs informal settings
(`research/questions.md`). Construct: co-presence as the substrate on which social energy can
circulate `[inferred]` — the research team has not signed off on this operationalisation.

Unit of analysis: the unordered person pair per 5-minute bin, aggregated to the person-day and to
the day-phase network.

Filters, in order, each counted in ``qa.json``:

1. Source: our own ingest of ``raw/beacons/Logs/`` (``social-energy ingest-beacons``, written to
   ``derived/beacons/contacts/<day>.parquet``), records with ``ok``. It dates each record from
   its power cycle's start and flags resent copies, which the upstream ``Output/`` tables keep
   at a late, shifted time. ``build --upstream`` reads ``Output/contacts_*.csv`` instead.
2. Window: from the tag deployment on 13 Aug to the handover on 29 Aug 09:00 local. After that the
   tags lay together on benches, which the spine does not yet exclude.
3. Both sides resolved through the spine to an entity (``beacon`` assignments).
4. Neither side in an exclusion window (``flag_excluded``, called once per side).
5. Consent: both people in ``spine.consented("beacons")``.
6. RSSI at or above the study's person-tag threshold for person pairs, location-tag threshold for
   rooms (``study.yaml``).

Phases are clock blocks, not programme events: 220 of the spine's events have no end time, so they
cannot bound a window. The blocks follow the academy's usual weekday rhythm `[inferred]`.

Usage (reads and writes only under ``$SOCIAL_ENERGY_DATA``):

    uv run --extra analysis python studies/dsa-2026/analyses/copresence_by_phase.py build
    uv run --extra analysis python studies/dsa-2026/analyses/copresence_by_phase.py report
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, time, timedelta
from pathlib import Path

import polars as pl

from social_energy import paths
from social_energy.presence import copresence, room_per_bin
from social_energy.spine import Spine
from social_energy.study import StudyConfig

STUDY = "dsa-2026"
SLUG = "copresence-by-phase"
BIN = "5m"
TZ = "Europe/Berlin"
FIRST_DAY = date(2026, 8, 13)
LAST_DAY = date(2026, 8, 29)
HANDOVER = "2026-08-29 09:00:00"
# A camp day runs from 07:30 to 07:30, so the night belongs to the evening before it.
DAY_START = timedelta(hours=7, minutes=30)

#: Clock blocks of a usual academy day, local time `[inferred]`.
PHASES: list[tuple[str, time]] = [
    ("morning", time(7, 30)),  # breakfast, plenum, first course block
    ("midday", time(12, 30)),  # lunch
    ("afternoon", time(14, 0)),  # second course block, sport, free time
    ("dinner", time(18, 30)),
    ("evening", time(19, 30)),  # KüA slots
    ("late", time(22, 30)),  # parties, late gatherings
    ("night", time(2, 0)),  # sleep
]
PHASE_ORDER = [p for p, _ in PHASES]

REPO = Path(__file__).resolve().parents[3]
STUDY_YAML = REPO / "studies" / STUDY / "study.yaml"


def out_dir() -> Path:
    d = paths.study(STUDY).derived / "analyses" / SLUG
    d.mkdir(parents=True, exist_ok=True)
    return d


def phase_expr(t_utc: pl.Expr) -> pl.Expr:
    """Phase label and camp day for a UTC timestamp."""
    local = t_utc.dt.convert_time_zone(TZ)
    clock = local.dt.time()
    expr = pl.lit("night")
    for name, start in sorted(PHASES, key=lambda p: p[1]):
        if name == "night":
            continue
        expr = pl.when(clock >= start).then(pl.lit(name)).otherwise(expr)
    late_night = clock < time(2, 0)
    return pl.when(late_night).then(pl.lit("late")).otherwise(expr)


def camp_day_expr(t_utc: pl.Expr) -> pl.Expr:
    return (t_utc.dt.convert_time_zone(TZ) - DAY_START).dt.date()


def read_upstream_contacts(path: Path) -> pl.DataFrame:
    return pl.read_csv(
        path,
        schema={
            "ID1": pl.Int64,
            "ID2": pl.Int64,
            "RSSI": pl.Int64,
            "Contact Local Time": pl.String,
        },
    ).select(
        pl.col("ID1").alias("observer"),
        pl.col("ID2").alias("observed"),
        pl.col("RSSI").alias("rssi"),
        pl.col("Contact Local Time")
        .str.strptime(pl.Datetime("us"), "%Y-%m-%d %H:%M:%S")
        .dt.replace_time_zone(TZ, ambiguous="earliest")
        .dt.convert_time_zone("UTC")
        .alias("t"),
    )


def window_bounds() -> tuple[pl.Expr, pl.Expr]:
    lo = pl.lit(str(FIRST_DAY)).str.strptime(pl.Datetime("us"), "%Y-%m-%d")
    hi = pl.lit(HANDOVER).str.strptime(pl.Datetime("us"), "%Y-%m-%d %H:%M:%S")
    return (
        lo.dt.replace_time_zone(TZ).dt.convert_time_zone("UTC"),
        hi.dt.replace_time_zone(TZ).dt.convert_time_zone("UTC"),
    )


def resolve_contacts(raw: pl.DataFrame, spine: Spine, qa: dict) -> pl.DataFrame:
    lo, hi = window_bounds()
    df = raw.filter((pl.col("t") >= lo) & (pl.col("t") < hi))
    qa["in_window"] = df.height
    df = spine.resolve(
        df, device_col="observer", time_col="t", kind="beacon", out="observer_entity"
    )
    df = spine.resolve(
        df, device_col="observed", time_col="t", kind="beacon", out="observed_entity"
    )
    df = df.filter(
        pl.col("observer_entity").is_not_null() & pl.col("observed_entity").is_not_null()
    )
    qa["both_resolved"] = df.height
    df = spine.flag_excluded(df, device_col="observer", time_col="t", kind="beacon", out="x1")
    df = spine.flag_excluded(df, device_col="observed", time_col="t", kind="beacon", out="x2")
    df = df.filter(~pl.col("x1") & ~pl.col("x2")).drop("x1", "x2")
    qa["not_excluded"] = df.height
    ok = [f"person:{p}" for p in spine.consented("beacons")]
    person_ok = lambda c: ~pl.col(c).str.starts_with("person:") | pl.col(c).is_in(ok)  # noqa: E731
    df = df.filter(person_ok("observer_entity") & person_ok("observed_entity"))
    qa["consented"] = df.height
    return df


def contact_days(layout: paths.StudyLayout, upstream: bool):
    """Per local day: ``YYYYMMDD``, contacts (observer, observed, rssi, t UTC) and a QA dict."""
    if upstream:
        for csv in sorted((layout.raw / "beacons" / "Output").glob("contacts_*.csv")):
            raw = read_upstream_contacts(csv)
            yield re.search(r"(\d{8})", csv.name).group(1), raw, {"rows": raw.height}
        return
    for part in sorted((layout.derived / "beacons" / "contacts").glob("20*.parquet")):
        rows = pl.read_parquet(part)
        raw = rows.filter(pl.col("ok")).select(
            pl.col("beacon").alias("observer"), "observed", "rssi", "t"
        )
        qa = {"rows": rows.height, "rows_ok": raw.height}
        del rows
        yield part.stem.replace("-", ""), raw, qa


def build() -> None:
    study = StudyConfig.load(STUDY_YAML)
    layout = paths.study(STUDY)
    spine = Spine.load(layout.spine)
    thr = study.raw["beacons"]["rssi_threshold_dbm"]
    out = out_dir()
    qa_all = {}
    for day, raw, qa in contact_days(layout, upstream="--upstream" in sys.argv):
        df = resolve_contacts(raw, spine, qa)
        del raw
        persons = df.filter(
            pl.col("observer_entity").str.starts_with("person:")
            & pl.col("observed_entity").str.starts_with("person:")
            & (pl.col("rssi") >= thr["person_tag"])
        )
        qa["person_pairs_above_threshold"] = persons.height
        # A person hears a room tag, or a room tag hears the person: both place the person.
        is_loc = lambda c: pl.col(c).str.starts_with("location:")  # noqa: E731
        is_person = lambda c: pl.col(c).str.starts_with("person:")  # noqa: E731
        rooms = pl.concat(
            [
                df.filter(is_person("observer_entity") & is_loc("observed_entity")),
                df.filter(is_loc("observer_entity") & is_person("observed_entity")).rename(
                    {"observer_entity": "observed_entity", "observed_entity": "observer_entity"}
                ),
            ],
            how="diagonal",
        ).filter(pl.col("rssi") >= thr["location_tag"])
        qa["person_room_above_threshold"] = rooms.height
        pairs = copresence(persons, every=BIN)
        presence = pl.concat(
            [
                df.select(pl.col("observer_entity").alias("entity"), "t"),
                df.select(pl.col("observed_entity").alias("entity"), "t"),
            ]
        ).filter(pl.col("entity").str.starts_with("person:"))
        seen = (
            presence.with_columns(pl.col("t").dt.truncate(BIN).alias("bin"))
            .select("entity", "bin")
            .unique()
        )
        pairs.write_parquet(out / f"pairs_{day}.parquet")
        room_per_bin(rooms, every=BIN).write_parquet(out / f"rooms_{day}.parquet")
        seen.write_parquet(out / f"seen_{day}.parquet")
        qa["pair_bins"] = pairs.height
        qa_all[day] = qa
        print(day, qa, flush=True)
    (out / "qa_build.json").write_text(json.dumps(qa_all, indent=2), encoding="utf-8")


# ---- report ----------------------------------------------------------------------------------

#: "Close" co-presence: the pair's strongest reading in the bin is at least this strong. The
#: study's -80 dBm person-tag threshold marks every participant as tied to nearly every other one
#: every day (shared rooms and meals), so it cannot separate anyone `[inferred: -65 dBm is close
#: range; uncalibrated, see ideas/rssi-calibration.md]`.
CLOSE_RSSI = -65
#: A tie on a camp day: close for at least this many 5-minute bins (one hour) `[inferred]`.
TIE_MIN_BINS = 12
#: A new tie "lasts" if the pair is tied again within this many following days.
PERSIST_DAYS = 3
#: Neighbouring definitions, reported as a sensitivity check.
SENSITIVITY = [(-60, 6), (-65, 12), (-70, 12)]
#: A person counts as present on a camp day once seen for at least this many bins (1 h).
PRESENT_MIN_BINS = 12
#: Groups smaller than this are suppressed in any output (ethics approval: aggregates only).
MIN_GROUP = 5
BLUE, ORANGE, GRAY = "#2a78d6", "#eb6834", "#8a8984"


def course_of(roster: Path) -> dict[str, str]:
    """Study ID → course, read from the local roster conversion (never leaves the machine)."""
    courses: dict[str, str] = {}
    section = None
    for line in roster.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
        if section not in ("Students", "Teachers and organizers") or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        sid = re.sub(r"\D", "", cells[0])
        if sid and re.fullmatch(r"1\.\d", cells[3 if section == "Students" else 1]):
            courses[f"person:{sid}"] = cells[3 if section == "Students" else 1]
    return courses


def load_all(prefix: str) -> pl.DataFrame:
    frames = [pl.read_parquet(p) for p in sorted(out_dir().glob(f"{prefix}_*.parquet"))]
    return pl.concat(frames).with_columns(
        camp_day_expr(pl.col("bin")).alias("day"), phase_expr(pl.col("bin")).alias("phase")
    )


def report() -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import networkx as nx

    layout = paths.study(STUDY)
    spine = Spine.load(layout.spine)
    out = out_dir()
    roster = next((layout.root / "context" / "personal").glob("*StudyIDs*.md"))
    course = course_of(roster)
    participants = {p.ref for p in spine.people if p.role == "participant"}
    days = [FIRST_DAY + timedelta(d) for d in range((LAST_DAY - FIRST_DAY).days)]  # 13-28

    seen = load_all("seen").filter(pl.col("entity").is_in(participants) & pl.col("day").is_in(days))
    pairs_all = load_all("pairs").filter(
        pl.col("a").is_in(participants)
        & pl.col("b").is_in(participants)
        & pl.col("day").is_in(days)
    )
    pairs = pairs_all.filter(pl.col("max_rssi") >= CLOSE_RSSI)
    present = (
        seen.group_by("entity", "day")
        .agg(pl.len().alias("seen_bins"))
        .filter(pl.col("seen_bins") >= PRESENT_MIN_BINS)
    )
    cmap = pl.DataFrame({"p": list(course), "course": list(course.values())})
    pairs = (
        pairs.join(cmap.rename({"p": "a", "course": "ca"}), on="a", how="left")
        .join(cmap.rename({"p": "b", "course": "cb"}), on="b", how="left")
        .with_columns((pl.col("ca") != pl.col("cb")).alias("cross_course"))
    )

    # -- 1. Others nearby per seen person-bin, by day and phase. Robust to coverage loss:
    # a bin where a person's tag was not read out is not counted as time alone.
    ends = pl.concat(
        [
            pairs.select(pl.col("a").alias("entity"), "bin", "cross_course"),
            pairs.select(pl.col("b").alias("entity"), "bin", "cross_course"),
        ]
    )
    per_bin = ends.group_by("entity", "bin").agg(
        pl.len().alias("others"), pl.col("cross_course").sum().alias("others_cross")
    )
    pb = seen.join(per_bin, on=["entity", "bin"], how="left").with_columns(
        pl.col("others").fill_null(0), pl.col("others_cross").fill_null(0)
    )
    heat = (
        pb.group_by("day", "phase")
        .agg(
            pl.col("others").mean().alias("others"),
            pl.col("entity").n_unique().alias("people"),
            (pl.col("others") == 0).mean().alias("share_no_one"),
        )
        .filter(pl.col("people") >= MIN_GROUP)
        .sort("day", "phase")
    )
    by_phase = (
        pb.group_by("phase")
        .agg(
            pl.col("others").mean().alias("others_nearby"),
            (pl.col("others_cross").sum() / pl.col("others").sum()).alias("cross_course_share"),
            (pl.col("others") == 0).mean().alias("share_bins_with_no_one"),
            (pl.len() / 12).alias("person_hours_seen"),
        )
        .sort(pl.col("phase").replace_strict(PHASE_ORDER, list(range(len(PHASE_ORDER)))))
    )

    # -- 2. Daily networks: ties, turnover, structure.
    def with_course(df):
        return (
            df.join(cmap.rename({"p": "a", "course": "ca"}), on="a", how="left")
            .join(cmap.rename({"p": "b", "course": "cb"}), on="b", how="left")
            .with_columns((pl.col("ca") != pl.col("cb")).alias("cross_course"))
        )

    def daily_networks(close: int, min_bins: int):
        ties = (
            pairs_all.filter(pl.col("max_rssi") >= close)
            .group_by("day", "a", "b")
            .agg(pl.len().alias("bins"))
            .filter(pl.col("bins") >= min_bins)
            .pipe(with_course)
        )
        rows, ever, degree_rows, by_day, new_by_day = [], set(), [], {}, {}
        for d in days:
            t = ties.filter(pl.col("day") == d)
            nodes = present.filter(pl.col("day") == d)["entity"].to_list()
            g = nx.Graph()
            g.add_nodes_from(nodes)
            g.add_weighted_edges_from(t.select("a", "b", "bins").iter_rows())
            edges = {tuple(e) for e in t.select("a", "b").iter_rows()}
            new = edges - ever
            ever |= edges
            by_day[d], new_by_day[d] = edges, new
            comms = nx.community.louvain_communities(g, weight="weight", seed=0) if g.edges else []
            cc = max(nx.connected_components(g), key=len) if g.number_of_nodes() else set()
            counts = cmap.filter(pl.col("p").is_in(nodes))["course"].value_counts()["count"]
            n = counts.sum()
            rows.append(
                {
                    "day": d,
                    "people": len(nodes),
                    "ties": len(edges),
                    "mean_degree": 2 * len(edges) / max(len(nodes), 1),
                    "isolates": sum(1 for v in g.nodes if g.degree(v) == 0),
                    "density": nx.density(g),
                    "clustering": nx.average_clustering(g),
                    "communities": len([c for c in comms if len(c) > 1]),
                    "modularity": nx.community.modularity(g, comms, weight="weight")
                    if comms
                    else None,
                    "largest_component_share": len(cc) / max(len(nodes), 1),
                    "cross_course_share": t["cross_course"].mean() if t.height else None,
                    "cross_course_random": 1 - (counts * (counts - 1)).sum() / (n * (n - 1)),
                    "new_tie_share": len(new) / max(len(edges), 1),
                    "cumulative_ties": len(ever),
                }
            )
            degree_rows += [{"day": d, "entity": v, "degree": g.degree(v)} for v in g.nodes]
        # Do ties made on a day last? Of the day's new ties, the share that is a tie again on any of
        # the next PERSIST_DAYS days, overall and for ties across courses.
        cross = set(ties.filter(pl.col("cross_course")).select("a", "b").iter_rows())
        for row in rows:
            d, new = row["day"], new_by_day[row["day"]]
            later = set().union(
                *(by_day.get(d + timedelta(k), set()) for k in range(1, 1 + PERSIST_DAYS))
            )
            new_cross = {e for e in new if e in cross}
            row["new_ties_seen_again"] = len(new & later) / len(new) if new else None
            row["new_cross_course_ties_seen_again"] = (
                len(new_cross & later) / len(new_cross) if new_cross else None
            )
        return pl.DataFrame(rows), pl.DataFrame(degree_rows)

    daily, deg = daily_networks(CLOSE_RSSI, TIE_MIN_BINS)
    sensitivity = pl.concat(
        [
            daily_networks(c, b)[0]
            .select("day", "mean_degree", "new_tie_share", "cross_course_share", "modularity")
            .with_columns(pl.lit(f"{c}dBm/{b * 5}min").alias("definition"))
            for c, b in SENSITIVITY
        ]
    )

    # -- 3. Embeddedness persistence: does the core stay the core? Rank correlation of each
    # person's degree between consecutive days.
    wide = deg.pivot(on="day", index="entity", values="degree")
    cols = [c for c in wide.columns if c != "entity"]
    persistence = [
        {
            "day": cols[i + 1],
            "spearman_vs_previous_day": wide.select(
                pl.corr(cols[i], cols[i + 1], method="spearman")
            ).item(),
        }
        for i in range(len(cols) - 1)
    ]

    # -- 4. Where: share of placed person-time per zone and phase.
    zone = {loc.ref: loc.zone for loc in spine.locations}
    rooms = load_all("rooms").filter(
        pl.col("entity").is_in(participants) & pl.col("day").is_in(days)
    )
    where = (
        rooms.with_columns(pl.col("location").replace_strict(zone, default="unknown").alias("zone"))
        .group_by("phase", "zone")
        .agg(pl.len().alias("bins"))
        .with_columns((pl.col("bins") / pl.col("bins").sum().over("phase")).alias("share"))
        .sort("phase", "share", descending=[False, True])
    )

    # ---- write tables
    for name, df in {
        "daily_network": daily,
        "day_phase": heat,
        "phase": by_phase,
        "zone_by_phase": where,
        "sensitivity": sensitivity,
    }.items():
        df.write_csv(out / f"{name}.csv")
    (out / "persistence.json").write_text(json.dumps(persistence, indent=2, default=str))

    # ---- figures
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
    labels = [d.strftime("%d") for d in days]

    fig, axes = plt.subplots(2, 2, figsize=(11, 7), sharex=True)
    for ax, col, title in [
        (axes[0, 0], "mean_degree", "Mean ties per participant (≥1 h at close range)"),
        (axes[0, 1], "new_tie_share", "Share of the day's ties never seen before"),
        (axes[1, 0], "cross_course_share", "Share of ties across courses"),
        (axes[1, 1], "modularity", "Modularity (how cliquish the day's network is)"),
    ]:
        ax.plot(labels, daily[col].to_list(), color=BLUE, lw=2, marker="o", ms=4)
        if col == "cross_course_share":
            ax.plot(labels, daily["cross_course_random"].to_list(), color=GRAY, lw=2, ls=":")
            ax.annotate(
                "if people mixed at random",
                (4, daily["cross_course_random"][4]),
                fontsize=8,
                color="#52514e",
                ha="center",
                va="top",
                xytext=(0, -4),
                textcoords="offset points",
            )
        # Tags ran low on battery from 24 Aug: fewer scans, not fewer encounters.
        ax.axvspan(labels.index("24") - 0.5, labels.index("27") + 0.5, color="#f1f0ec", zorder=0)
        ax.annotate(
            "batteries failing",
            (labels.index("24") - 0.4, 0.02),
            fontsize=8,
            xycoords=("data", "axes fraction"),
            color="#52514e",
        )
        for special, name in [("18", "excursion"), ("22", "rotation")]:
            i = labels.index(special)
            ax.axvline(i, color=GRAY, lw=1, ls="--")
            ax.annotate(
                name,
                (i, 1),
                xycoords=("data", "axes fraction"),
                fontsize=8,
                color="#52514e",
                ha="left",
                va="top",
                xytext=(3, 0),
                textcoords="offset points",
            )
        ax.set_title(title, loc="left", fontsize=10)
    for ax in axes[1]:
        ax.set_xlabel("August (camp day, 07:30-07:30)")
    fig.suptitle("DSA 2026 participant co-presence network, day by day", x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(out / "fig_daily_network.png", dpi=160)

    # Do the day's new ties last? The last PERSIST_DAYS days have no full follow-up and are left
    # out; days whose follow-up reaches into the restart-heavy, battery-faded end are shaded.
    fig, ax = plt.subplots(figsize=(11, 4))
    keep = daily.head(len(days) - PERSIST_DAYS)
    lab_p = [d.strftime("%d") for d in keep["day"].to_list()]
    vals = keep["new_ties_seen_again"].to_list()
    special = {"18", "22"}
    ax.bar(lab_p, vals, color=[ORANGE if x in special else BLUE for x in lab_p], width=0.7)
    ax.axvspan(lab_p.index("21") - 0.5, len(lab_p) - 0.5, color="#f1f0ec", zorder=0)
    ax.annotate(
        "follow-up days hit by restarts and fading batteries",
        (lab_p.index("21") - 0.4, 0.97),
        xycoords=("data", "axes fraction"),
        fontsize=8,
        color="#52514e",
        va="top",
    )
    for x, name in (("18", "excursion"), ("22", "rotation")):
        i = lab_p.index(x)
        ax.annotate(
            name,
            (i, vals[i] or 0),
            xytext=(0, 4),
            textcoords="offset points",
            ha="center",
            fontsize=8,
            color="#52514e",
        )
    ax.set_title(
        f"Share of a day's new ties that are ties again within {PERSIST_DAYS} days",
        loc="left",
        fontsize=10,
    )
    ax.set_xlabel("August (day the tie was first seen)")
    fig.tight_layout()
    fig.savefig(out / "fig_new_ties_last.png", dpi=160)

    hm = heat.pivot(on="day", index="phase", values="others")
    hm = hm.sort(pl.col("phase").replace_strict(PHASE_ORDER, list(range(len(PHASE_ORDER)))))
    day_cols = [c for c in hm.columns if c != "phase"]
    fig, ax = plt.subplots(figsize=(11, 3.6))
    im = ax.imshow(hm.select(day_cols).to_numpy(), aspect="auto", cmap="Blues")
    ax.set_yticks(range(hm.height), hm["phase"].to_list())
    ax.set_xticks(range(len(day_cols)), [c[-2:] for c in day_cols])
    ax.grid(False)
    fig.colorbar(im, ax=ax, label="others nearby (mean)")
    ax.set_title(
        "Participants within close range of a participant, per 5 minutes seen",
        loc="left",
        fontsize=10,
    )
    ax.set_xlabel("August (camp day)")
    fig.tight_layout()
    fig.savefig(out / "fig_day_phase_heatmap.png", dpi=160)

    fig, ax = plt.subplots(figsize=(9, 5))
    mat = wide.select(cols).fill_null(-1).to_numpy()
    order = (-wide.select(cols).mean_horizontal().fill_null(0).to_numpy()).argsort()
    masked = __import__("numpy").ma.masked_less(mat[order], 0)
    im = ax.imshow(masked, aspect="auto", cmap="Blues", interpolation="nearest")
    ax.set_xticks(range(len(cols)), [str(c)[-2:] for c in cols])
    ax.set_yticks([])
    ax.set_ylabel("participants, most to least connected (no IDs)")
    ax.grid(False)
    fig.colorbar(im, ax=ax, label="ties that day")
    ax.set_title("Who stays central? Each row is one participant", loc="left", fontsize=10)
    fig.tight_layout()
    fig.savefig(out / "fig_person_trajectories.png", dpi=160)
    print(daily)
    print(by_phase)
    print(persistence)


if __name__ == "__main__":
    {"build": build, "report": report}[sys.argv[1]]()
