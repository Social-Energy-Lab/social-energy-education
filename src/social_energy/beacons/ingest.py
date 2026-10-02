"""Beacon logger `.log` files → canonical tables.

Input format: the text files written by `dsa_logger.py` in
github.com/thofbaur/network-beacon_NRF54L15 (described in
docs/context/instruments/beacons.md). One line per decoded record:

    2026-08-14 12:00:00,ID: 37,Current Timer: 7200
    2026-08-14 12:00:00,ID: 37,ID2: 28, Timer: 6000, RSSI: -73

``ID`` is the beacon being read out. Record timers are that beacon's uptime in
seconds, and the readout's ``Current Timer`` line ties uptime to wall-clock time.

Principles:
* Nothing is dropped silently. Suspicious records get boolean flags, and ``qa``
  accounts for every input line.
* Direction is kept: ``beacon`` heard ``observed``.
* Resolution to people or rooms is not done here. That is the spine's job.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import polars as pl

from .cycles import power_cycles

LINE_RE = r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),ID: ([^,]*),(.*)$"
KINDS: dict[str, str] = {
    "status": r"^Status: (\d+)$",
    "timer": r"^Current Timer: (\d+)$",
    "count": r"^Contact Count: (\d+)$",
    "voltage": r"^Voltage: (\d+)$",
    "contact": r"^ID2: (\d+), Timer: (\d+), RSSI: (-?\d+)$",
    "self_report": r"^Self-report time: (\d+)$",
    "eco": r"^Eco Session Enter: (\d+), Leave: (\d+)$",
}
UTC = "UTC"


@dataclass(frozen=True)
class BeaconConfig:
    timezone: str
    valid_from: date
    valid_to: date
    # Logger bug (fixed upstream in commit 2e1f52d): before this local wall-clock
    # time, beacon IDs 48-57 were printed as the characters "0"-"9".
    ambiguous_id_cutoff: datetime | None = None
    # File-name patterns of logs whose readout IDs were already split by hand (trusted as printed).
    ids_split_in: tuple[str, ...] = ()
    # ID repair: how far (s) an ambiguous readout's implied start may lie before a cycle's estimated
    # start. That estimate is itself the latest of several late stamps, so a little earlier is fine.
    anchor_tolerance_s: int = 300
    # Uptime this far behind the wall time elapsed since the tag's previous anchor is a restart.
    restart_margin_s: int = 3600
    # A gap this long between two lines of one tag in one file starts a new readout.
    readout_gap_s: int = 60


@dataclass
class BeaconTables:
    readouts: pl.DataFrame
    contacts: pl.DataFrame
    self_reports: pl.DataFrame
    eco_sessions: pl.DataFrame
    qa: dict[str, int] = field(default_factory=dict)


# ---- parsing -----------------------------------------------------------------


def _read_lines(paths: Iterable[Path]) -> pl.DataFrame:
    frames = []
    for path in paths:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        frames.append(
            pl.DataFrame(
                {
                    "source": [Path(path).name] * len(lines),
                    "line_no": list(range(1, len(lines) + 1)),
                    "raw": lines,
                },
                schema={"source": pl.String, "line_no": pl.Int64, "raw": pl.String},
            )
        )
    return pl.concat(frames) if frames else pl.DataFrame()


def _classify(lines: pl.DataFrame, tz: str) -> pl.DataFrame:
    parts = lines.with_columns(
        pl.col("raw").str.extract(LINE_RE, 1).alias("_ts"),
        pl.col("raw").str.extract(LINE_RE, 2).alias("header_id"),
        pl.col("raw").str.extract(LINE_RE, 3).alias("rest"),
    )
    kind = pl.when(pl.col("_ts").is_null()).then(pl.lit("unparsed"))
    for name, pattern in KINDS.items():
        kind = kind.when(pl.col("rest").str.contains(pattern)).then(pl.lit(name))
    return parts.with_columns(
        kind.otherwise(pl.lit("other")).alias("kind"),
        pl.col("_ts")
        .str.to_datetime("%Y-%m-%d %H:%M:%S")
        .dt.replace_time_zone(tz, ambiguous="earliest")
        .dt.convert_time_zone(UTC)
        .alias("pc_time"),
        *[
            pl.col("rest").str.extract(KINDS[k], g).cast(pl.Int64).alias(name)
            for k, g, name in [
                ("status", 1, "_status"),
                ("timer", 1, "_timer"),
                ("count", 1, "_count"),
                ("voltage", 1, "_voltage"),
                ("contact", 1, "_observed"),
                ("contact", 2, "_uptime_c"),
                ("contact", 3, "_rssi"),
                ("self_report", 1, "_uptime_s"),
                ("eco", 1, "_enter"),
                ("eco", 2, "_leave"),
            ]
        ],
    ).drop("_ts")


def _assign_readouts(rows: pl.DataFrame, gap_s: int) -> pl.DataFrame:
    """Group lines into readouts: one connection of the base station to one beacon.

    A readout starts at a ``Status`` line, at a ``Current Timer`` line not directly preceded by
    that beacon's ``Status``, at the beacon's first line in a file, or after a gap of more than
    ``gap_s`` since its previous line. Lines of one transfer come seconds apart; a block of records
    arriving later without header lines is a readout of its own, with no clock anchor.
    """
    rows = rows.sort("source", "line_no")
    by = ["source", "header_id"]
    prev_kind = pl.col("kind").shift(1).over(by)
    gap = (pl.col("pc_time") - pl.col("pc_time").shift(1).over(by)).dt.total_seconds()
    starts = (
        (pl.col("kind") == "status")
        | ((pl.col("kind") == "timer") & (prev_kind != "status"))
        | prev_kind.is_null()
        | (gap > gap_s)
    )
    rows = rows.with_columns(starts.cast(pl.Int64).cum_sum().over(by).alias("_local"))
    return rows.with_columns(
        (
            pl.col("source") + "#" + pl.col("header_id") + "#" + pl.col("_local").cast(pl.String)
        ).alias("readout_key")
    )


def _readout_table(rows: pl.DataFrame) -> pl.DataFrame:
    readouts = (
        rows.group_by("readout_key", maintain_order=True)
        .agg(
            pl.col("source").first(),
            pl.col("header_id").first(),
            pl.col("line_no").min().alias("first_line"),
            pl.col("pc_time").filter(pl.col("kind") == "timer").first().alias("pc_time"),
            pl.col("pc_time").min().alias("_pc_any"),
            pl.col("_timer").drop_nulls().first().alias("current_timer"),
            pl.col("_count").drop_nulls().first().alias("contact_count"),
            pl.col("_voltage").drop_nulls().first().alias("voltage_mv"),
            pl.col("_status").drop_nulls().first().alias("status_byte"),
        )
        .with_columns(pl.col("pc_time").fill_null(pl.col("_pc_any")))
        .drop("_pc_any")
    )
    return readouts.with_columns(
        (pl.col("pc_time") - pl.duration(seconds=pl.col("current_timer"))).alias("anchor"),
        pl.col("header_id").cast(pl.Int64, strict=False).alias("beacon"),
    )


# ---- identity repair ---------------------------------------------------------------


def _repair_ids(readouts: pl.DataFrame, config: BeaconConfig) -> pl.DataFrame:
    """Undo the logger bug that printed beacon IDs 48-57 as "0"-"9".

    An ambiguous readout for header ``n`` came from beacon ``n`` or ``n + 48``. Its implied start
    (``pc_time - current_timer``) lies at or a little after the start of the power cycle it belongs
    to, since stamps only run late. The candidate with a cycle (from unambiguous readouts) that
    started at most ``restart_margin_s`` before it, and no more than ``anchor_tolerance_s`` after
    (the cycle's start is estimated from late stamps too), is the right one.
    Logs matching ``ids_split_in`` were split by hand and are trusted.
    """
    if config.ambiguous_id_cutoff is None:
        return readouts.with_columns(pl.lit("ok").alias("id_status"))
    cutoff = (
        pl.Series([config.ambiguous_id_cutoff])
        .dt.replace_time_zone(config.timezone)
        .dt.convert_time_zone(UTC)[0]
    )
    split_by_hand = pl.lit(False)
    for pattern in config.ids_split_in:
        split_by_hand = split_by_hand | pl.col("source").str.contains(_glob_to_regex(pattern))
    is_ambiguous = (
        pl.col("header_id").str.contains(r"^[0-9]$") & (pl.col("pc_time") < cutoff) & ~split_by_hand
    )
    readouts = readouts.with_columns(is_ambiguous.alias("_ambiguous"))
    known = readouts.filter(
        ~pl.col("_ambiguous") & pl.col("anchor").is_not_null() & pl.col("beacon").is_not_null()
    )
    starts = (
        power_cycles(
            known.select(
                "beacon", pl.col("pc_time").alias("ts"), pl.col("current_timer").alias("timer")
            ),
            restart_margin_s=config.restart_margin_s,
        )
        .select("beacon", "cycle_start")
        .unique()
    )
    early = timedelta(seconds=config.anchor_tolerance_s)
    late = timedelta(seconds=config.restart_margin_s)

    fixed_beacon, status = [], []
    for row in readouts.iter_rows(named=True):
        if not row["_ambiguous"]:
            fixed_beacon.append(row["beacon"])
            status.append("ok")
            continue
        n = int(row["header_id"])
        if row["anchor"] is None:
            fixed_beacon.append(n)
            status.append("ambiguous")
            continue
        matches = [
            candidate
            for candidate in (n, n + 48)
            if starts.filter(
                (pl.col("beacon") == candidate)
                & (pl.col("cycle_start") <= row["anchor"] + early)
                & (pl.col("cycle_start") >= row["anchor"] - late)
            ).height
        ]
        if len(matches) == 1:
            fixed_beacon.append(matches[0])
            status.append("ok" if matches[0] == n else "repaired")
        else:
            fixed_beacon.append(n)
            status.append("ambiguous")
    return readouts.with_columns(
        pl.Series("beacon", fixed_beacon, dtype=pl.Int64),
        pl.Series("id_status", status, dtype=pl.String),
    ).drop("_ambiguous")


def _glob_to_regex(pattern: str) -> str:
    return "^" + re.escape(pattern).replace(r"\*", ".*").replace(r"\?", ".") + "$"


def _add_boot_context(readouts: pl.DataFrame, config: BeaconConfig) -> pl.DataFrame:
    """Put every readout in its tag's power cycle (see ``cycles.power_cycles``).

    Readouts with a clock anchor define the cycles; a readout without one (headerless, or with an
    unresolved ID) belongs to the latest cycle that had started by its PC time. ``cycle_start`` is
    the cycle's earliest implied start, so a late stamp does not shift the records it dates.
    """
    anchored = readouts.filter(
        pl.col("anchor").is_not_null()
        & pl.col("beacon").is_not_null()
        & (pl.col("id_status") != "ambiguous")
    ).select(
        "readout_key",
        "beacon",
        pl.col("pc_time").alias("ts"),
        pl.col("current_timer").alias("timer"),
    )
    cyc = power_cycles(anchored, restart_margin_s=config.restart_margin_s).select(
        "readout_key", "restart", "cycle", "cycle_start"
    )
    starts = (
        cyc.join(anchored.select("readout_key", "beacon"), on="readout_key")
        .group_by("beacon", "cycle")
        .agg(pl.col("cycle_start").first())
        .sort("beacon", "cycle")
        .with_columns(pl.col("cycle_start").shift(1).over("beacon").alias("prev_cycle_start"))
    )
    readouts = readouts.join(cyc, on="readout_key", how="left")
    placed = readouts.filter(pl.col("cycle").is_not_null())
    unplaced = (
        readouts.filter(pl.col("cycle").is_null())
        .drop("cycle", "cycle_start")
        .sort("pc_time")
        .join_asof(
            starts.select("beacon", "cycle", "cycle_start").sort("cycle_start"),
            left_on="pc_time",
            right_on="cycle_start",
            by="beacon",
            strategy="backward",
            check_sortedness=False,
        )
        .with_columns(pl.lit(False).alias("restart"))
    )
    readouts = pl.concat([placed, unplaced.select(placed.columns)])
    readouts = readouts.join(
        starts.select("beacon", "cycle", "prev_cycle_start"), on=["beacon", "cycle"], how="left"
    )
    return readouts.sort("beacon", "pc_time").with_columns(
        pl.int_range(pl.len()).over("beacon").alias("readout_seq"),
        pl.col("restart").fill_null(False).alias("reboot_before"),
    )


# ---- record tables -------------------------------------------------------------


def _resolve_boots(records: pl.DataFrame, uptime_col: str) -> pl.DataFrame:
    """Decide which boot each record's uptime belongs to, and compute its time.

    Within one readout, records come out in recording order, so a drop in uptime marks
    a reboot. Records after the last drop belong to the current boot, unless even they
    exceed the readout's Current Timer, in which case the current boot has no records
    yet. Records are dated from their power cycle's start; records one boot back from the
    previous cycle's start. Records further back cannot be placed in time.
    """
    timer_now = pl.coalesce(
        pl.col("current_timer"), (pl.col("pc_time") - pl.col("cycle_start")).dt.total_seconds()
    )
    records = records.sort("readout_key", "line_no").with_columns(
        (pl.col(uptime_col) < pl.col(uptime_col).shift(1).over("readout_key"))
        .fill_null(False)
        .cast(pl.Int64)
        .cum_sum()
        .over("readout_key")
        .alias("_seg")
    )
    records = records.with_columns(
        pl.col("_seg").max().over("readout_key").alias("_last_seg"),
        (
            pl.col(uptime_col)
            .filter(pl.col("_seg") == pl.col("_seg").max())
            .max()
            .over("readout_key")
            > timer_now
        ).alias("_no_current"),
    ).with_columns(
        (pl.col("_last_seg") - pl.col("_seg") + pl.col("_no_current").cast(pl.Int64)).alias(
            "_boots_back"
        )
    )
    anchor = (
        pl.when(pl.col("_boots_back") == 0)
        .then(pl.col("cycle_start"))
        .when(pl.col("_boots_back") == 1)
        .then(pl.col("prev_cycle_start"))
    )
    return records.with_columns(
        (pl.col("_boots_back") > 0).alias("pre_reboot"),
        (anchor + pl.duration(seconds=pl.col(uptime_col))).alias("t"),
    ).drop("_seg", "_last_seg", "_no_current", "_boots_back")


def _plausible(t: pl.Expr, config: BeaconConfig) -> pl.Expr:
    start = datetime.combine(config.valid_from, datetime.min.time())
    end = datetime.combine(config.valid_to + timedelta(days=1), datetime.min.time())
    bounds = pl.Series([start, end]).dt.replace_time_zone(config.timezone).dt.convert_time_zone(UTC)
    # A record of the previous boot must precede the restart that ended it.
    after_restart = pl.col("pre_reboot") & (t >= pl.col("cycle_start"))
    return (t >= bounds[0]) & (t < bounds[1]) & (t <= pl.col("pc_time")) & ~after_restart


OK = (
    pl.col("t").is_not_null()
    & ~pl.col("implausible_time")
    & ~pl.col("duplicate")
    & ~pl.col("id_ambiguous")
).alias("ok")


def _finish(records: pl.DataFrame, config: BeaconConfig) -> pl.DataFrame:
    """Add quality flags, all but ``duplicate``, which needs every copy (``_flag_duplicates``)."""
    return records.with_columns(
        (pl.col("t").is_not_null() & ~_plausible(pl.col("t"), config)).alias("implausible_time"),
        pl.lit(False).alias("duplicate"),
        (pl.col("id_status") == "ambiguous").alias("id_ambiguous"),
    ).with_columns(OK)


def _flag_duplicates(records: pl.DataFrame, key: list[str]) -> pl.DataFrame:
    """A duplicate is a record already exported in an earlier readout: same key, same time."""
    first_readout = pl.col("readout_order").min().over([*key, "t"])
    return records.with_columns(
        (pl.col("t").is_not_null() & (pl.col("readout_order") != first_readout)).alias("duplicate"),
    ).with_columns(OK)


READOUT_CONTEXT = [
    "readout_key", "beacon", "readout_seq", "readout_order", "pc_time",
    "current_timer", "cycle_start", "prev_cycle_start", "id_status",
]  # fmt: skip
FLAGS = ["pre_reboot", "headerless", "implausible_time", "duplicate", "id_ambiguous", "ok"]


CONTACT_KEY = ["beacon", "observed", "rssi"]
SELF_REPORT_KEY = ["beacon"]
ECO_KEY = ["beacon", "uptime_enter_s", "uptime_leave_s"]
RECORD_KINDS = ["contact", "self_report", "eco"]


def _parse(paths: Iterable[Path], config: BeaconConfig) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Classified lines, and the parsed lines grouped into readouts."""
    lines = _classify(_read_lines(paths), config.timezone)
    parsed = _assign_readouts(lines.filter(pl.col("kind") != "unparsed"), config.readout_gap_s)
    return lines, parsed


def _readouts(readout_rows: pl.DataFrame, config: BeaconConfig) -> pl.DataFrame:
    readouts = _add_boot_context(_repair_ids(readout_rows, config), config)
    return readouts.sort("pc_time", "source", "first_line").with_columns(
        pl.int_range(pl.len()).alias("readout_order")
    )


def _records(
    parsed: pl.DataFrame, context: pl.DataFrame, config: BeaconConfig
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, int]:
    """Contacts, self-reports and eco sessions, flagged except for ``duplicate``."""
    data = (
        parsed.filter(pl.col("kind").is_in(RECORD_KINDS))
        .drop("pc_time")
        .join(context, on="readout_key", how="left")
        .with_columns(pl.col("current_timer").is_null().alias("headerless"))
    )
    contacts = _finish(
        _resolve_boots(
            data.filter(pl.col("kind") == "contact").rename(
                {"_observed": "observed", "_uptime_c": "uptime_s", "_rssi": "rssi"}
            ),
            "uptime_s",
        ),
        config).select(
        "beacon", "observed", "rssi", "t", "uptime_s", "readout_seq", *FLAGS,
        "readout_key", "source", "line_no", "readout_order",
    )  # fmt: skip

    self_reports = _finish(
        _resolve_boots(
            data.filter(pl.col("kind") == "self_report").rename({"_uptime_s": "uptime_s"}),
            "uptime_s",
        ),
        config).select(
        "beacon", "t", "uptime_s", "readout_seq", *FLAGS, "readout_key", "source", "line_no",
        "readout_order",
    )  # fmt: skip

    eco = data.filter(pl.col("kind") == "eco")
    eco = _resolve_boots(eco, "_enter").rename({"t": "t_enter"})
    eco = eco.with_columns(
        (pl.col("t_enter") + pl.duration(seconds=pl.col("_leave") - pl.col("_enter"))).alias(
            "t_leave"
        ),
        pl.col("t_enter").alias("t"),
    )
    eco_sessions = _finish(eco, config).select(
        "beacon", "t_enter", "t_leave", pl.col("_enter").alias("uptime_enter_s"),
        pl.col("_leave").alias("uptime_leave_s"), "readout_seq", *FLAGS,
        "readout_key", "source", "line_no", "readout_order", "t",
    )  # fmt: skip
    return contacts, self_reports, eco_sessions, int(data["headerless"].sum())


def _finish_eco(eco: pl.DataFrame) -> pl.DataFrame:
    return _flag_duplicates(eco, ECO_KEY).drop("t", "readout_order")


READOUT_COLUMNS = [
    "readout_key", "source", "first_line", "header_id", "beacon", "id_status",
    "readout_seq", "pc_time", "current_timer", "anchor", "cycle", "cycle_start",
    "reboot_before", "contact_count", "voltage_mv", "status_byte",
]  # fmt: skip


def _qa(
    kinds: dict[str, int],
    headerless: int,
    readouts: pl.DataFrame,
    contacts: dict[str, int],
    self_reports: int,
    eco_sessions: int,
) -> dict[str, int]:
    return {
        "lines_total": sum(kinds.values()),
        "lines_unparsed": kinds.get("unparsed", 0),
        "lines_other": kinds.get("other", 0),
        "records_in_headerless_readouts": headerless,
        "readouts": readouts.height,
        "contacts": contacts["rows"],
        "self_reports": self_reports,
        "eco_sessions": eco_sessions,
        "ids_repaired": int((readouts["id_status"] == "repaired").sum()),
        "ids_ambiguous": int((readouts["id_status"] == "ambiguous").sum()),
        "reboots": int(readouts["reboot_before"].sum()),
        "contacts_not_ok": contacts["not_ok"],
        "contacts_unplaced_in_time": contacts["unplaced"],
    }


def _kind_counts(lines: pl.DataFrame) -> dict[str, int]:
    kinds = lines["kind"].value_counts()
    return dict(zip(kinds["kind"].to_list(), kinds["count"].to_list(), strict=True))


def _contact_counts(contacts: pl.DataFrame) -> dict[str, int]:
    return {
        "rows": contacts.height,
        "not_ok": int((~contacts["ok"]).sum()),
        "unplaced": int(contacts["t"].is_null().sum()),
    }


def ingest_logs(paths: Iterable[Path], config: BeaconConfig) -> BeaconTables:
    """Ingest logger files in memory. For a whole camp, see ``ingest_logs_to``."""
    lines, parsed = _parse(paths, config)
    readouts = _readouts(_readout_table(parsed), config)
    contacts, self_reports, eco, headerless = _records(
        parsed, readouts.select(READOUT_CONTEXT), config
    )
    contacts = _flag_duplicates(contacts, CONTACT_KEY).drop("readout_order")
    self_reports = _flag_duplicates(self_reports, SELF_REPORT_KEY).drop("readout_order")
    eco = _finish_eco(eco)
    readouts_out = readouts.select(READOUT_COLUMNS).sort("pc_time", "source", "first_line")
    qa = _qa(
        _kind_counts(lines),
        headerless,
        readouts_out,
        _contact_counts(contacts),
        self_reports.height,
        eco.height,
    )
    return BeaconTables(readouts_out, contacts, self_reports, eco, qa)


def ingest_logs_to(paths: Iterable[Path], config: BeaconConfig, out: Path) -> dict[str, int]:
    """Ingest logger files one at a time and write the tables to ``out``; return the QA dict.

    Gives the same tables as ``ingest_logs`` without holding every log in memory. Writes
    ``readouts.parquet``, ``self_reports.parquet``, ``eco_sessions.parquet`` and contacts per local
    day of ``t`` as ``contacts/<YYYY-MM-DD>.parquet`` (``contacts/unplaced.parquet`` for records
    with no time). Copies of a record share its time, so duplicates are settled within each day.
    """
    out = Path(out)
    work = out / "_work"
    (out / "contacts").mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    paths = list(paths)

    # 1. Each file alone: readout structure, line counts, parsed records kept on disk.
    kinds: dict[str, int] = {}
    readout_rows = []
    for i, path in enumerate(paths):
        lines, parsed = _parse([path], config)
        for kind, n in _kind_counts(lines).items():
            kinds[kind] = kinds.get(kind, 0) + n
        readout_rows.append(_readout_table(parsed))
        parsed.filter(pl.col("kind").is_in(RECORD_KINDS)).write_parquet(
            work / f"parsed_{i}.parquet"
        )
        del lines, parsed

    # 2. The whole camp: IDs, power cycles, readout order.
    readouts = _readouts(pl.concat(readout_rows), config)
    context = readouts.select(READOUT_CONTEXT)

    # 3. Each file again: date its records.
    self_reports, eco, headerless = [], [], 0
    day = pl.col("t").dt.convert_time_zone(config.timezone).dt.date().alias("_day")
    for i in range(len(paths)):
        parsed = pl.read_parquet(work / f"parsed_{i}.parquet")
        contacts, srs, ecos, n = _records(parsed, context, config)
        headerless += n
        contacts.with_columns(day).write_parquet(work / f"contacts_{i}.parquet")
        self_reports.append(srs)
        eco.append(ecos)
        (work / f"parsed_{i}.parquet").unlink()

    # 4. Each day: flag copies, write.
    scan = pl.scan_parquet(work / "contacts_*.parquet")
    days = scan.select(pl.col("_day").unique()).collect()["_day"].to_list()
    counts = {"rows": 0, "not_ok": 0, "unplaced": 0}
    for d in days:
        part = scan.filter(pl.col("_day").is_null() if d is None else pl.col("_day") == d).collect()
        part = _flag_duplicates(part.drop("_day"), CONTACT_KEY).drop("readout_order")
        name = "unplaced" if d is None else d.isoformat()
        part.write_parquet(out / "contacts" / f"{name}.parquet")
        for k, v in _contact_counts(part).items():
            counts[k] += v
    for f in work.glob("contacts_*.parquet"):
        f.unlink()
    work.rmdir()

    self_reports_out = _flag_duplicates(pl.concat(self_reports), SELF_REPORT_KEY).drop(
        "readout_order"
    )
    eco_out = _finish_eco(pl.concat(eco))
    readouts_out = readouts.select(READOUT_COLUMNS).sort("pc_time", "source", "first_line")
    self_reports_out.write_parquet(out / "self_reports.parquet")
    eco_out.write_parquet(out / "eco_sessions.parquet")
    readouts_out.write_parquet(out / "readouts.parquet")
    return _qa(kinds, headerless, readouts_out, counts, self_reports_out.height, eco_out.height)
