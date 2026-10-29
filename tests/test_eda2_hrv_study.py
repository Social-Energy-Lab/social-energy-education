"""The DSA 2026 HRV script's own wiring, on invented rows: one source per device-minute, the
dose levels and familiar vs new partners."""

import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

ANALYSES = Path(__file__).resolve().parents[1] / "studies" / "dsa-2026" / "analyses"
T0 = datetime(2026, 8, 17, 10, 0, tzinfo=UTC)  # a camp day


@pytest.fixture(scope="module")
def hrv():
    sys.path.insert(0, str(ANALYSES))
    spec = importlib.util.spec_from_file_location("eda2_hrv_script", ANALYSES / "eda2_hrv.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def stretch(start, n, ibi_ms, *, source, ok=True, run="r"):
    t = [start + timedelta(milliseconds=ibi_ms * k) for k in range(n)]
    return pl.DataFrame(
        {
            "device": ["D1"] * n,
            "source": [source] * n,
            "run": [run] * n,
            "t": t,
            "ibi_ms": pl.Series([None] + [float(ibi_ms)] * (n - 1), dtype=pl.Float32),
            "plausible": [True] * n,
            "ok": [ok] * n,
            "clock_uncertain": [False] * n,
        }
    )


def test_sd_wins_and_the_export_fills_a_minute_the_card_lacks(hrv):
    # Minute 0: both sources (the export not ok there: the card covers it). Minute 1: export only.
    beats = pl.concat(
        [
            stretch(T0, 50, 1000, source="sd"),
            stretch(T0, 50, 1000, source="export", ok=False, run="e"),
            stretch(T0 + timedelta(minutes=1), 50, 1000, source="export", run="e2"),
        ]
    )
    chosen, pairs = hrv.device_hrv(beats)
    by_min = {r["minute"]: r["hrv_source"] for r in chosen.to_dicts()}
    assert by_min == {T0: "sd", T0 + timedelta(minutes=1): "export"}
    # The agreement pairs ignore ``ok``: minute 0 holds both sources.
    assert pairs["minute"].to_list() == [T0]
    assert pairs["rmssd_sd"][0] == pytest.approx(0.0) and pairs["rmssd_export"][0] == 0.0


def test_dose_levels(hrv):
    df = pl.DataFrame({"c": [0, 0, 1, 2, 3, 4, 7, 8, 20], "h": [0, 3, 1, 2, 3, 4, 7, 8, 20]})
    got = df.select(hrv.dose_level(pl.col("c"), pl.col("h"))).to_series().to_list()
    assert got == ["0", "heard only", "1", "2-3", "2-3", "4-7", "4-7", "8+", "8+"]


def test_familiar_means_tied_on_an_earlier_camp_day(hrv):
    bins = [T0 + timedelta(minutes=5 * k) for k in range(12)]  # one hour close: a tie
    day2 = [b + timedelta(days=1) for b in bins[:1]]
    rows = [("p:a", "p:b", b, -60) for b in bins + day2]
    rows += [("p:a", "p:c", b, -60) for b in day2]  # new on day 2
    rows += [("p:a", "p:d", b, -75) for b in bins + day2]  # never close
    ends = pl.DataFrame(rows, schema=["entity", "other", "bin", "max_rssi"], orient="row")
    fam = hrv.familiarity(ends, close_rssi=-65, tie_min_bins=12).sort("bin")
    first = fam.filter(pl.col("bin") == bins[0]).row(0, named=True)
    assert first["n_close"] == 1 and first["share_familiar"] == 0.0  # tied today, not before
    later = fam.filter(pl.col("bin") == day2[0]).row(0, named=True)
    assert later["n_close"] == 2 and later["share_familiar"] == 0.5  # b familiar, c new
