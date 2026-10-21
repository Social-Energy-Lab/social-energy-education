"""The public bundle: no course keys, presses per bin, no night. Synthetic hand-built world only.

T0 is 05:30 Berlin, so bin 5 starts 05:55 local (night) and bin 6 starts 06:00 (shown).
"""

from collections import Counter
from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from social_energy.explorer import BundleInput, read_bundle
from social_energy.paths import REPO_ROOT, DataRootError
from social_energy.site import PUBLIC_COLUMNS, PUBLIC_META_KEYS, write_public_bundle
from social_energy.study import ExplorerConfig

T0 = datetime(2026, 8, 14, 3, 30, tzinfo=UTC)
BIN = 300
TZ = "Europe/Berlin"


def _bin(k: int) -> datetime:
    return T0 + timedelta(seconds=BIN * k)


def _world() -> BundleInput:
    pairs = [
        ("person:1", "person:2", 1, -65),  # at the threshold: kept
        ("person:1", "person:3", 2, -70),  # too far: dropped
        ("person:2", "person:3", 5, -50),  # night bin: dropped
        ("person:3", "person:4", 6, -50),  # first shown bin: kept
    ]
    return BundleInput(
        t0=T0,
        n_bins=8,
        bin_seconds=BIN,
        nodes={"person:1": "A", "person:2": "A", "person:3": "B", "person:4": None},
        locations={"location:9": ("hall", "common")},
        pairs=pl.DataFrame(
            {
                "a": [p[0] for p in pairs],
                "b": [p[1] for p in pairs],
                "bin": [_bin(p[2]) for p in pairs],
                "max_rssi": [p[3] for p in pairs],
            }
        ),
        seen=pl.DataFrame(
            {"entity": ["person:1", "person:2", "person:1"], "bin": [_bin(1), _bin(5), _bin(6)]}
        ),
        rooms=pl.DataFrame({"entity": ["person:1"], "bin": [_bin(1)], "location": ["location:9"]}),
        presses=pl.DataFrame(
            {
                "entity": ["person:1", "person:2"],
                "t": [_bin(5) + timedelta(seconds=205), _bin(6) + timedelta(seconds=10)],
            }
        ),
        rssi_floor=-90,
    )


CONFIG = ExplorerConfig(
    courses={"A": "Alpha", "B": "Beta"},
    day_start="06:00",
    phases=[("day", "06:00"), ("night", "22:00")],
    shade=[{"start": "2026-08-14 05:40", "end": "2026-08-14 05:50", "label": "private"}],
)


def _write(tmp_path, **kw):
    kw.setdefault("seed", 3)
    meta = write_public_bundle(_world(), tmp_path / "pub", CONFIG, timezone=TZ, **kw)
    return meta, read_bundle(tmp_path / "pub")[1], tmp_path / "pub"


def test_public_meta_has_only_public_keys(tmp_path):
    meta, tables, out = _write(tmp_path)
    assert set(meta) <= PUBLIC_META_KEYS
    for banned in ("courses", "locations", "qa"):
        assert banned not in meta
    assert all(set(n) == {"course"} for n in meta["nodes"])
    assert meta["mode"] == "public" and meta["synthetic"] is False
    assert meta["n_courses"] == 2
    assert set(tables) == set(PUBLIC_COLUMNS)
    assert "rssi" not in tables["pairs"] and "rooms" not in tables
    assert not (out / "rooms.bin").exists()


def test_pairs_filtered_to_close_range_and_rssi_dropped(tmp_path):
    _meta, tables, _ = _write(tmp_path, night=("00:00", "05:00"))
    p = tables["pairs"]
    assert set(p) == {"bin", "a", "b"}
    assert list(p["bin"]) == [1, 5, 6]  # the -70 pair (bin 2) is absent, -65 present
    assert all(a < b for a, b in zip(p["a"], p["b"], strict=True))


def test_presses_at_bin_resolution(tmp_path):
    # 05:58:20 Berlin is in bin 05:55; an earlier night end keeps it.
    _meta, tables, _ = _write(tmp_path, night=("00:00", "05:00"))
    assert set(tables["presses"]) == {"bin", "node"}
    assert list(tables["presses"]["bin"]) == [5, 6]


def test_night_removed_at_the_boundary(tmp_path):
    _meta, tables, _ = _write(tmp_path)
    shown = list(tables["bins"]["shown"])
    assert shown[5] == 0 and shown[6] == 1 and shown[4] == 0
    for t, col in (("pairs", "bin"), ("seen", "bin"), ("presses", "bin")):
        got = list(tables[t][col])
        assert 5 not in got and all(shown[b] == 1 for b in got), t
    assert 6 in tables["seen"]["bin"] and 6 in tables["presses"]["bin"]


def test_course_indices_permuted_consistently(tmp_path):
    meta, *_ = _write(tmp_path)
    c = [n["course"] for n in meta["nodes"]]
    assert sorted(Counter(c).values()) == [1, 1, 2] and c.count(-1) == 1
    assert sorted(set(c) - {-1}) == list(range(meta["n_courses"]))
    # the two nodes of course A share an index; same seed gives same permutation
    again, *_ = _write(tmp_path / "again")
    assert [n["course"] for n in again["nodes"]] == c


def test_special_days_and_shade_in_bins(tmp_path):
    days = [{"start_bin": 2, "end_bin": 4, "label": "excursion"}]
    meta, *_ = _write(tmp_path, special_days=days, shade_label="records missing")
    assert meta["special_days"] == days
    assert meta["shade"] == [{"start_bin": 2, "end_bin": 4, "label": "records missing"}]


def test_refuses_inside_repo():
    with pytest.raises(DataRootError):
        write_public_bundle(_world(), REPO_ROOT / "x", CONFIG, timezone=TZ)
