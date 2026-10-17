"""Our ID repair against the beacon team's hand split of the logger ID bug (13-15 Aug).

The ingest repairs readouts printed as "0"-"9" itself (clock anchors, then partners' witnesses).
The beacon team split the same readouts by hand in their ``*_cleaned.log`` files. This compares
the two, readout by readout, to see where ours decides, agrees, disagrees or stays undecided.

Inputs: ``derived/beacons/readouts.parquet`` (``social-energy ingest-beacons``) and the hand-split
logs under ``raw/beacons-reference/`` (never ingested: they would double every line). Readouts are
paired by file and by the order of their ``Current Timer`` lines, which the hand split keeps.

Writes ``derived/analyses/id-repair-benchmark/{summary.json, unsettled.csv}``. Run with
``uv run --extra analysis python studies/dsa-2026/analyses/id_repair_benchmark.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl

from social_energy import paths
from social_energy.beacons.ingest import _parse, _readout_table
from social_energy.study import StudyConfig

STUDY = "dsa-2026"
REPO = Path(__file__).resolve().parents[3]
STUDY_YAML = REPO / "studies" / STUDY / "study.yaml"
HAND_SPLIT_GLOB = "beacons-reference/**/Logs_cleaned/*_cleaned.log"


def header_lines_only(log: Path, out: Path) -> Path:
    """The readout header lines of one log (all the pairing needs), CRLF removed."""
    keep = (",Status:", ",Current Timer:", ",Contact Count:", ",Voltage:")
    target = out / log.name.replace("_cleaned", "")
    with log.open(encoding="utf-8", errors="replace") as src, target.open("w") as dst:
        for line in src:
            if any(k in line for k in keep):
                dst.write(line.rstrip("\r\n") + "\n")
    return target


def main() -> None:
    study = StudyConfig.load(STUDY_YAML)
    config = study.beacon_config()
    layout = paths.study(STUDY)
    out = layout.derived / "analyses" / "id-repair-benchmark"
    work = out / "_headers"
    work.mkdir(parents=True, exist_ok=True)

    hand = [header_lines_only(p, work) for p in sorted(layout.raw.glob(HAND_SPLIT_GLOB))]
    _, parsed = _parse(hand, config)
    theirs = (
        _readout_table(parsed)
        .filter(pl.col("current_timer").is_not_null())
        .sort("source", "first_line")
        .with_columns(pl.int_range(pl.len()).over("source").alias("k"))
        .select("source", "k", pl.col("beacon").alias("hand_label"))
    )
    ours = (
        pl.read_parquet(layout.derived / "beacons" / "readouts.parquet")
        .filter(pl.col("current_timer").is_not_null())
        .sort("source", "first_line")
        .with_columns(pl.int_range(pl.len()).over("source").alias("k"))
    )
    m = ours.join(theirs, on=["source", "k"], how="inner")
    cutoff = (
        pl.lit(config.ambiguous_id_cutoff)
        .dt.replace_time_zone(config.timezone)
        .dt.convert_time_zone("UTC")
    )
    affected = pl.col("header_id").str.contains(r"^[0-9]$") & (pl.col("pc_time") < cutoff)
    amb = m.filter(affected).with_columns(
        pl.when(pl.col("id_status") == "ambiguous")
        .then(pl.lit("undecided"))
        .when(pl.col("beacon") == pl.col("hand_label"))
        .then(pl.lit("agree"))
        .otherwise(pl.lit("disagree"))
        .alias("outcome")
    )
    rest = m.filter(~affected)
    summary = {
        "hand_split_files": len(hand),
        "affected_readouts_with_hand_label": amb.height,
        "outcome": dict(amb["outcome"].value_counts().iter_rows()),
        "outcome_by_status": {
            f"{o}/{s}": n for o, s, n in amb.group_by("outcome", "id_status").len().iter_rows()
        },
        "unaffected_readouts_relabelled_by_hand": int((rest["beacon"] != rest["hand_label"]).sum()),
        "unaffected_readouts": rest.height,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    amb.filter(pl.col("outcome") != "agree").select(
        "source", "first_line", "header_id", "beacon", "hand_label", "id_status"
    ).write_csv(out / "unsettled.csv")
    for f in work.iterdir():
        f.unlink()
    work.rmdir()
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
