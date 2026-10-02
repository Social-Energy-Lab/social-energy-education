"""The file-by-file ingest (``ingest_logs_to``) must equal the in-memory one (``ingest_logs``).

It exists so that a whole camp, which does not fit in memory, can be ingested one log at a time,
with contacts written per local day.
"""

from datetime import date, datetime
from pathlib import Path

import polars as pl
import pytest

from social_energy.beacons import BeaconConfig, ingest_logs, ingest_logs_to

FIX = Path(__file__).parent / "fixtures" / "beacon_logs"
PATHS = [
    FIX / "golden.log",
    FIX / "late_stamps.log",
    FIX / "late_stamps_resend.log",
    FIX / "id_bug.log",
]
CONFIG = BeaconConfig(
    timezone="Europe/Berlin",
    valid_from=date(2026, 8, 12),
    valid_to=date(2026, 8, 29),
    ambiguous_id_cutoff=datetime(2026, 8, 15, 20, 17, 48),
)
ORDER = ["source", "line_no"]


@pytest.fixture(scope="module")
def both(tmp_path_factory):
    out = tmp_path_factory.mktemp("ingest")
    return ingest_logs(PATHS, CONFIG), ingest_logs_to(PATHS, CONFIG, out), out


def test_contacts_are_identical_and_written_per_local_day(both):
    mem, _, out = both
    days = sorted(p.name for p in (out / "contacts").glob("*.parquet"))
    assert "2026-08-20.parquet" in days
    got = pl.read_parquet(out / "contacts" / "*.parquet").sort(ORDER)
    assert got.equals(mem.contacts.sort(ORDER))


def test_a_record_resent_in_another_file_is_a_duplicate(both):
    _, _, out = both
    got = pl.read_parquet(out / "contacts" / "*.parquet")
    resent = got.filter(pl.col("source") == "late_stamps_resend.log")
    assert resent["duplicate"].to_list() == [True]
    assert resent["ok"].to_list() == [False]


def test_other_tables_and_qa_are_identical(both):
    mem, qa, out = both
    for name in ("readouts", "self_reports", "eco_sessions"):
        key = ["source", "first_line"] if name == "readouts" else ORDER
        got = pl.read_parquet(out / f"{name}.parquet").sort(key)
        assert got.equals(getattr(mem, name).sort(key)), name
    assert qa == mem.qa
