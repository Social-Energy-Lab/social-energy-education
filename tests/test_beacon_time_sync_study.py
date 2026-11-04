"""The DSA 2026 time-sync script's own wiring, on invented rows."""

import importlib.util
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest

ANALYSES = Path(__file__).resolve().parents[1] / "studies" / "dsa-2026" / "analyses"


@pytest.fixture(scope="module")
def m():
    sys.path.insert(0, str(ANALYSES))
    spec = importlib.util.spec_from_file_location(
        "beacon_time_sync_script", ANALYSES / "beacon_time_sync.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_lag_shares_weigh_by_bins_and_leave_out_the_unsettled(m):
    lags = pl.DataFrame(
        {
            "bins": [60, 30, 10, 100],
            "lag_s": [0.0, 120.0, 4000.0, 9999.0],
            "settled": [True, True, True, False],
        }
    )
    s = m.lag_shares(lags)
    assert s["settled_share_of_bins"] == 0.5
    assert (s["within_1_min"], s["1_to_5_min"], s["5_to_30_min"], s["over_30_min"]) == (
        0.6,
        0.3,
        0.0,
        0.1,
    )


def coverage(rows):
    hour = datetime(2026, 8, 14, 10, tzinfo=UTC)
    return pl.DataFrame(
        [{"beacon": b, "hour": hour, "state": s, "heard": h} for b, s, h in rows],
        schema={
            "beacon": pl.Int64,
            "hour": pl.Datetime("us", "UTC"),
            "state": pl.String,
            "heard": pl.Boolean,
        },
    )


def test_neither_side_counts_pairs_with_no_record_from_either(m):
    # Four tags present: two recorded, two missing. Six pairs, one with neither: 1/6. If gaps were
    # independent: (2/4)^2 = 1/4. Tag 5 is unheard and has no records: not present, not counted.
    cov = coverage(
        [
            (1, "recorded", True),
            (2, "recorded_eco", False),
            (3, "not_logged", True),
            (4, "erased_by_reboot", True),
            (5, "not_read_out", False),
        ]
    )
    r = m.neither_side(cov).row(0, named=True)
    assert r["day"] == date(2026, 8, 14)
    assert r["neither"] == round(1 / 6, 4)
    assert r["expected"] == 0.25


def test_old_periods_keep_only_placed_anchors(m):
    readouts = pl.DataFrame(
        {
            "readout_key": ["a", "b", "c"],
            "beacon": [1, 1, None],
            "current_timer": [10, None, 30],
            "cycle": [1, 1, 1],
            "cycle_start": [datetime(2026, 8, 14, tzinfo=UTC)] * 3,
        }
    )
    assert m.old_periods(readouts)["readout_key"].to_list() == ["a"]


def test_fitted_periods_give_lost_windows_up_to_the_fitted_boot():
    # Read at 10:00, then a period booted at 12:00 by the fit, first read at 15:00, stamped late.
    # The window runs from the last readout to the fitted boot. Then one more readout, same period.
    sys.path.insert(0, str(ANALYSES))
    import beacon_diagnostics as bd

    from social_energy.beacons import lost_windows

    at = lambda h: datetime(2026, 8, 14, h, tzinfo=UTC)  # noqa: E731
    periods = pl.DataFrame(
        {
            "beacon": [1, 1, 1],
            "ts": [at(10), at(15), at(16)],
            "timer": [7200, 3600, 7200],
            "boot": [at(8), at(12), at(12)],
            "evidence": ["first", "timer_back", None],
        }
    )
    assert lost_windows(bd.fitted_cycles(periods)).rows() == [(1, at(10), at(12))]
