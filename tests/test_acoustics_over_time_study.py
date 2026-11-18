"""The DSA 2026 acoustics-over-time script's own functions, on invented rows."""

import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest

ANALYSES = Path(__file__).resolve().parents[1] / "studies" / "dsa-2026" / "analyses"


@pytest.fixture(scope="module")
def m():
    sys.path.insert(0, str(ANALYSES))
    spec = importlib.util.spec_from_file_location(
        "acoustics_over_time_script", ANALYSES / "acoustics_over_time.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def utc(hour, minute=0, day=20):
    return datetime(2026, 8, day, hour, minute, tzinfo=UTC)


def windows():
    return pl.DataFrame(
        {
            "event": ["choir", "plenum", "outside", "party"],
            "kind": ["choir", "plenum", "sport", "party"],
            "label": ["Choir", "Morning plenum", "Football", "Party"],
            "all_camp": [False, True, False, True],
            "locations": [["location:hall-1"], [], ["location:field"], ["location:garden"]],
            "start": [utc(10), utc(9, 30), utc(10), utc(9)],
            "end": [utc(11), utc(10, 30), utc(11), utc(12)],
        }
    )


ZONES = {"plenum": {"location:hall-1", "location:hall-2"}, "mensa": {"location:dining"}}


def test_room_items_keeps_items_in_the_zone_and_camp_wide_items_without_a_place(m):
    items = m.room_items(windows(), ZONES)
    got = {(r["recorder"], r["event"], r["where"]) for r in items.iter_rows(named=True)}
    # The choir is in a hall location; the plenum is camp-wide with no place, so it labels both
    # rooms; the football and the garden party are elsewhere and label neither.
    assert got == {
        ("plenum", "choir", "in room"),
        ("plenum", "plenum", "camp-wide"),
        ("mensa", "plenum", "camp-wide"),
    }
    assert items.filter(pl.col("event") == "choir")["min"].to_list() == [60.0]


def test_label_bins_prefers_the_room_s_own_item_then_the_shortest(m):
    items = m.room_items(windows(), ZONES)
    bins = pl.DataFrame(
        {
            "recorder": ["plenum", "plenum", "plenum", "mensa", "mensa"],
            "bin": [utc(9, 30), utc(10, 10), utc(11), utc(10, 25), utc(10, 30)],
        }
    )
    out = m.label_bins(bins, items)
    # 09:30 plenum only; 10:10 both cover it and the choir is in the room; 11:00 the choir has
    # ended (end is exclusive). In the mensa, 10:25's midpoint (10:27:30) is still in the plenum,
    # 10:30's (10:32:30) is not.
    assert out["kind"].to_list() == ["plenum", "choir", m.NONE, "plenum", m.NONE]
    assert out["where"].to_list() == ["camp-wide", "in room", "none", "camp-wide", "none"]
    assert out["bin"].to_list() == bins["bin"].to_list()  # order kept


def test_slot_fallback_names_uncovered_bins_by_their_slot(m):
    df = pl.DataFrame({"kind": ["choir", m.NONE], "slot": ["14:00-16:30", "12:00-13:45"]})
    assert m.with_slot_fallback(df)["kind"].to_list() == ["choir", "no item (12:00-13:45)"]


def test_scheduled_hours_counts_overlaps_once_and_clips(m):
    items = pl.DataFrame(
        {
            "recorder": ["plenum"] * 3,
            "kind": ["choir"] * 3,
            "start": [utc(10), utc(10, 30), utc(13)],
            "end": [utc(11), utc(11, 30), utc(15)],
        }
    )
    out = m.scheduled_hours(items, utc(0), utc(14))
    # 10:00-11:30 as one run (1.5 h), and 13:00-15:00 clipped at 14:00 (1 h).
    assert out.to_dicts() == [{"recorder": "plenum", "kind": "choir", "scheduled_h": 2.5}]


def test_near_floor_blanks_the_centroid_of_a_silent_hall(m):
    n = 50
    bins = pl.DataFrame(
        {
            "recorder": ["plenum"] * n,
            "l90_dbfs": [-73.0] * n,
            # Two silent bins (within 6 dB of the -73 floor), the rest sounding.
            "leq_dbfs": [-72.0, -68.0] + [-50.0] * (n - 2),
            "spectral_centroid_hz": [9000.0, 8000.0] + [1200.0] * (n - 2),
        }
    )
    out = m.flag_near_floor(bins)
    assert out["near_floor"].to_list()[:3] == [True, True, False]
    assert out["centroid_hz"].to_list()[:3] == [None, None, 1200.0]
    assert out["spectral_centroid_hz"].to_list()[:2] == [9000.0, 8000.0]  # flagged, not dropped


def test_spectrum_shift_is_the_kind_s_median_against_the_room_s(m):
    df = pl.DataFrame(
        {
            "recorder": ["plenum"] * 4,
            "kind": ["choir", "choir", "quiet", "quiet"],
            "band_0_300_db": [-40.0, -40.0, -60.0, -60.0],
        }
    )
    out = m.spectrum_shift(df, ["band_0_300_db"])
    # The room's median over all four bins is -50.
    assert dict(zip(out["kind"], out["shift_db"], strict=True)) == {"choir": 10.0, "quiet": -10.0}


def test_bands_sort_by_frequency(m):
    cols = ["t", "band_1000_2000_db", "band_0_300_db", "band_300_1000_db", "rms_dbfs"]
    assert m.bands_of(cols) == ["band_0_300_db", "band_300_1000_db", "band_1000_2000_db"]
    assert m.band_label("band_1000_2000_db") == "1 k-2 k Hz"
