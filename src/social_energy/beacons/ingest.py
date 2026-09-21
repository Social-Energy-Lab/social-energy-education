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

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import polars as pl

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
    # Max difference (s) between clock anchors that still counts as the same boot.
    anchor_tolerance_s: int = 5


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


def _assign_readouts(rows: pl.DataFrame) -> pl.DataFrame:
    """Group lines into readouts: one connection of the base station to one beacon.

    A readout starts at a ``Status`` line, or at a ``Current Timer`` line not directly
    preceded by that beacon's ``Status``. Data lines that come before any start in a
    file (seen in early logs) are attached to that beacon's next readout and flagged.
    """
    rows = rows.sort("source", "line_no")
    prev_kind = pl.col("kind").shift(1).over("source", "header_id")
    starts = (pl.col("kind") == "status") | (
        (pl.col("kind") == "timer") & (prev_kind.is_null() | (prev_kind != "status"))
    )
    rows = rows.with_columns(
        starts.cast(pl.Int64).cum_sum().over("source", "header_id").alias("_local")
    )
    return rows.with_columns(
        (pl.col("_local") == 0).alias("reference_after"),
        pl.when(pl.col("_local") == 0).then(1).otherwise(pl.col("_local")).alias("_local"),
    ).with_columns(
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

    An ambiguous readout for header ``n`` came from beacon ``n`` or ``n + 48``. Every
    readout of one boot shares a clock anchor (``pc_time - current_timer``), so the
    candidate whose unambiguous readouts share this anchor is the right one.
    """
    if config.ambiguous_id_cutoff is None:
        return readouts.with_columns(pl.lit("ok").alias("id_status"))
    cutoff = (
        pl.Series([config.ambiguous_id_cutoff])
        .dt.replace_time_zone(config.timezone)
        .dt.convert_time_zone(UTC)[0]
    )
    is_ambiguous = (
        pl.col("header_id").str.contains(r"^[0-9]$")
        & (pl.col("pc_time") < cutoff)
        & pl.col("anchor").is_not_null()
    )
    readouts = readouts.with_columns(is_ambiguous.alias("_ambiguous"))
    known = readouts.filter(~pl.col("_ambiguous") & pl.col("anchor").is_not_null())
    tolerance = timedelta(seconds=config.anchor_tolerance_s)

    fixed_beacon, status = [], []
    for row in readouts.iter_rows(named=True):
        if not row["_ambiguous"]:
            fixed_beacon.append(row["beacon"])
            status.append("ok")
            continue
        n = int(row["header_id"])
        matches = [
            candidate
            for candidate in (n, n + 48)
            if known.filter(
                (pl.col("beacon") == candidate)
                & ((pl.col("anchor") - row["anchor"]).abs() <= tolerance)
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


def _add_boot_context(readouts: pl.DataFrame, config: BeaconConfig) -> pl.DataFrame:
    tolerance = timedelta(seconds=config.anchor_tolerance_s)
    readouts = readouts.sort("beacon", "pc_time").with_columns(
        pl.col("anchor").shift(1).over("beacon").alias("prev_anchor"),
        pl.int_range(pl.len()).over("beacon").alias("readout_seq"),
    )
    return readouts.with_columns(
        (
            pl.col("prev_anchor").is_not_null()
            & ((pl.col("anchor") - pl.col("prev_anchor")).abs() > tolerance)
        ).alias("reboot_before")
    )


# ---- record tables -------------------------------------------------------------


def _resolve_boots(records: pl.DataFrame, uptime_col: str) -> pl.DataFrame:
    """Decide which boot each record's uptime belongs to, and compute its time.

    Within one readout, records come out in recording order, so a drop in uptime marks
    a reboot. Records after the last drop belong to the current boot, unless even they
    exceed the readout's Current Timer, in which case the current boot has no records
    yet. Records one boot back are resolved with the previous readout's anchor. Records
    further back cannot be placed in time.
    """
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
            > pl.col("current_timer")
        ).alias("_no_current"),
    ).with_columns(
        (pl.col("_last_seg") - pl.col("_seg") + pl.col("_no_current").cast(pl.Int64)).alias(
            "_boots_back"
        )
    )
    anchor = (
        pl.when(pl.col("_boots_back") == 0)
        .then(pl.col("anchor"))
        .when(pl.col("_boots_back") == 1)
        .then(pl.col("prev_anchor"))
    )
    return records.with_columns(
        (pl.col("_boots_back") > 0).alias("pre_reboot"),
        (anchor + pl.duration(seconds=pl.col(uptime_col))).alias("t"),
    ).drop("_seg", "_last_seg", "_no_current", "_boots_back")


def _plausible(t: pl.Expr, config: BeaconConfig) -> pl.Expr:
    start = datetime.combine(config.valid_from, datetime.min.time())
    end = datetime.combine(config.valid_to + timedelta(days=1), datetime.min.time())
    bounds = pl.Series([start, end]).dt.replace_time_zone(config.timezone).dt.convert_time_zone(UTC)
    return (t >= bounds[0]) & (t < bounds[1]) & (t <= pl.col("pc_time"))


def _finish(records: pl.DataFrame, config: BeaconConfig, key: list[str]) -> pl.DataFrame:
    """Add quality flags. A duplicate is a record already exported in an earlier readout."""
    first_readout = pl.col("readout_order").min().over([*key, "t"])
    return records.with_columns(
        (pl.col("t").is_not_null() & ~_plausible(pl.col("t"), config)).alias("implausible_time"),
        (pl.col("t").is_not_null() & (pl.col("readout_order") != first_readout)).alias("duplicate"),
        (pl.col("id_status") == "ambiguous").alias("id_ambiguous"),
    ).with_columns(
        (
            pl.col("t").is_not_null()
            & ~pl.col("implausible_time")
            & ~pl.col("duplicate")
            & ~pl.col("id_ambiguous")
        ).alias("ok")
    )


READOUT_CONTEXT = [
    "readout_key", "beacon", "readout_seq", "readout_order", "pc_time",
    "current_timer", "anchor", "prev_anchor", "id_status",
]  # fmt: skip
FLAGS = ["pre_reboot", "reference_after", "implausible_time", "duplicate", "id_ambiguous", "ok"]


def ingest_logs(paths: Iterable[Path], config: BeaconConfig) -> BeaconTables:
    lines = _classify(_read_lines(paths), config.timezone)
    parsed = _assign_readouts(lines.filter(pl.col("kind") != "unparsed"))

    readouts = _add_boot_context(_repair_ids(_readout_table(parsed), config), config)
    readouts = readouts.sort("pc_time", "source", "first_line").with_columns(
        pl.int_range(pl.len()).alias("readout_order")
    )
    context = readouts.select(READOUT_CONTEXT)
    data = parsed.drop("pc_time").join(context, on="readout_key", how="left")

    contacts = _finish(
        _resolve_boots(
            data.filter(pl.col("kind") == "contact").rename(
                {"_observed": "observed", "_uptime_c": "uptime_s", "_rssi": "rssi"}
            ),
            "uptime_s",
        ),
        config,
        key=["beacon", "observed", "rssi"],
    ).select(
        "beacon", "observed", "rssi", "t", "uptime_s", "readout_seq", *FLAGS,
        "readout_key", "source", "line_no",
    )  # fmt: skip

    self_reports = _finish(
        _resolve_boots(
            data.filter(pl.col("kind") == "self_report").rename({"_uptime_s": "uptime_s"}),
            "uptime_s",
        ),
        config,
        key=["beacon"],
    ).select("beacon", "t", "uptime_s", "readout_seq", *FLAGS, "readout_key", "source", "line_no")

    eco = data.filter(pl.col("kind") == "eco")
    eco = _resolve_boots(eco, "_enter").rename({"t": "t_enter"})
    eco = eco.with_columns(
        (pl.col("t_enter") + pl.duration(seconds=pl.col("_leave") - pl.col("_enter"))).alias(
            "t_leave"
        ),
        pl.col("t_enter").alias("t"),
    )
    eco_sessions = _finish(eco, config, key=["beacon", "_enter", "_leave"]).select(
        "beacon", "t_enter", "t_leave", pl.col("_enter").alias("uptime_enter_s"),
        pl.col("_leave").alias("uptime_leave_s"), "readout_seq", *FLAGS,
        "readout_key", "source", "line_no",
    )  # fmt: skip

    readouts_out = readouts.select(
        "readout_key", "source", "first_line", "header_id", "beacon", "id_status",
        "readout_seq", "pc_time", "current_timer", "anchor", "reboot_before",
        "contact_count", "voltage_mv", "status_byte",
    ).sort("pc_time", "source", "first_line")  # fmt: skip

    kinds = lines["kind"].value_counts()
    count = dict(zip(kinds["kind"].to_list(), kinds["count"].to_list(), strict=True))
    qa = {
        "lines_total": lines.height,
        "lines_unparsed": count.get("unparsed", 0),
        "lines_other": count.get("other", 0),
        "lines_before_first_reference": int(parsed["reference_after"].sum()),
        "readouts": readouts_out.height,
        "contacts": contacts.height,
        "self_reports": self_reports.height,
        "eco_sessions": eco_sessions.height,
        "ids_repaired": int((readouts_out["id_status"] == "repaired").sum()),
        "ids_ambiguous": int((readouts_out["id_status"] == "ambiguous").sum()),
        "reboots": int(readouts_out["reboot_before"].sum()),
        "contacts_not_ok": int((~contacts["ok"]).sum()),
        "contacts_unplaced_in_time": int(contacts["t"].is_null().sum()),
    }
    return BeaconTables(readouts_out, contacts, self_reports, eco_sessions, qa)
