"""The EDA second pass's split-half rule: fixed halves and the verdict per estimate."""

import importlib.util
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl

SCRIPT = Path(__file__).resolve().parents[1] / "studies" / "dsa-2026" / "analyses" / "eda_split.py"
spec = importlib.util.spec_from_file_location("eda_split", SCRIPT)
split = importlib.util.module_from_spec(spec)
spec.loader.exec_module(split)


def test_halves_alternate_and_do_not_overlap():
    days = sorted(split.DISCOVERY + split.REPLICATION)
    assert not set(split.DISCOVERY) & set(split.REPLICATION)
    assert [d in split.DISCOVERY for d in days] == [i % 2 == 0 for i in range(len(days))]


def test_camp_day_starts_at_four_local():
    df = pl.DataFrame({"t": [datetime(2026, 8, 16, 1, 59, tzinfo=UTC),
                             datetime(2026, 8, 16, 2, 0, tzinfo=UTC)]})  # fmt: skip
    days = df.select(split.camp_day(pl.col("t"))).to_series().to_list()
    assert days == [date(2026, 8, 15), date(2026, 8, 16)]


def test_half_of_and_subset():
    df = pl.DataFrame({"day": [date(2026, 8, 15), date(2026, 8, 16), date(2026, 8, 18)]})
    assert df.select(split.half_of(pl.col("day"))).to_series().to_list() == [
        "discovery", "replication", None]  # fmt: skip
    assert split.subset(df, "all").height == 2


def test_verdict():
    assert split.verdict(0.3, 0.1, 0.5, 0.2, 0.05, 0.4) == "replicates"
    assert split.verdict(0.3, 0.1, 0.5, 0.2, -0.1, 0.4) == "same direction"
    assert split.verdict(0.3, 0.1, 0.5, -0.2, -0.4, -0.1) == "does not replicate"
    assert split.verdict(0.3, -0.1, 0.5, 0.2, 0.05, 0.4) == "no lead"
    assert split.verdict(float("nan"), 0, 0, 0, 0, 0) == "not estimable"
