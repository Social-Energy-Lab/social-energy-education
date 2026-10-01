"""The explorer bundle: an ID-free, binary copy of already-filtered presence tables.

Golden: a hand-written world of four people, one room and six bins, with hand-derived
contents. Oracle: a synthetic camp, where everyone sharing a room is a pair in every bin.
"""

from collections import Counter
from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from social_energy.explorer import BundleInput, read_bundle, write_bundle
from social_energy.explorer.synthetic import synthetic_inputs
from social_energy.paths import REPO_ROOT, DataRootError
from social_energy.study import ExplorerConfig
from social_energy.synth import CampSpec, generate

T0 = datetime(2026, 1, 1, tzinfo=UTC)
BIN = 300


def _bin(k: int) -> datetime:
    return T0 + timedelta(seconds=BIN * k)


def _golden() -> BundleInput:
    pairs = [
        ("person:1", "person:2", 0, -60),
        ("person:1", "person:3", 1, -70),
        ("person:3", "person:4", 2, -75),
        ("person:1", "person:99", 2, -60),  # no node: dropped
        ("person:1", "person:2", 7, -60),  # outside the bins: dropped
        ("person:2", "person:3", 3, -90),  # below the floor: dropped
    ]
    return BundleInput(
        t0=T0,
        n_bins=6,
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
        seen=pl.DataFrame({"entity": ["person:1", "person:2"], "bin": [_bin(0), _bin(0)]}),
        rooms=pl.DataFrame({"entity": ["person:1"], "bin": [_bin(0)], "location": ["location:9"]}),
        presses=pl.DataFrame(
            {
                "entity": ["person:1", "person:99"],
                "t": [_bin(0) + timedelta(seconds=30), _bin(1)],
            }
        ),
        rssi_floor=-80,
    )


CONFIG = ExplorerConfig(
    courses={"A": "Alpha", "B": "Beta"},
    phases=[("day", "06:00"), ("night", "22:00")],
    notes=[{"start": "2026-01-01 00:10", "end": "2026-01-01 00:20", "text": "a note"}],
)


@pytest.fixture
def golden(tmp_path):
    meta = write_bundle(_golden(), tmp_path / "bundle", CONFIG, timezone="UTC")
    return meta, *read_bundle(tmp_path / "bundle"), tmp_path / "bundle"


def test_golden_pairs_survive_by_course(golden):
    meta, _, cols, _ = golden
    course = [n["course"] for n in meta["nodes"]]
    p = cols["pairs"]
    got = Counter(
        (int(k), tuple(sorted((course[a], course[b]))), int(r))
        for k, a, b, r in zip(p["bin"], p["a"], p["b"], p["rssi"], strict=True)
    )
    assert got == Counter({(0, (0, 0), -60): 1, (1, (0, 1), -70): 1, (2, (-1, 1), -75): 1})


def test_golden_drops_are_counted(golden):
    meta, *_ = golden
    qa = meta["qa"]
    assert (qa["pairs_no_node"], qa["pairs_out_of_range"], qa["pairs_below_floor"]) == (1, 1, 1)
    assert qa["presses_without_node"] == 1


def test_golden_meta_describes_courses_places_and_time(golden):
    meta, *_ = golden
    assert meta["courses"] == [{"key": "A", "name": "Alpha"}, {"key": "B", "name": "Beta"}]
    assert sorted(n["course"] for n in meta["nodes"]) == [-1, 0, 0, 1]
    assert meta["locations"] == [{"label": "hall", "zone": 0}]
    assert meta["zones"] == ["common"]
    assert meta["notes"] == [{"start_bin": 2, "end_bin": 4, "text": "a note"}]
    assert (meta["n_bins"], meta["bin_seconds"], meta["t0"]) == (6, 300, "2026-01-01T00:00:00Z")
    assert meta["mode"] == "team"


def test_golden_presses_rooms_and_bins(golden):
    meta, _, cols, _ = golden
    course = [n["course"] for n in meta["nodes"]]
    assert list(cols["presses"]["sec"]) == [30]
    assert course[int(cols["presses"]["node"][0])] == 0
    assert list(cols["rooms"]["loc"]) == [0]
    assert sorted(course[int(n)] for n in cols["seen"]["node"]) == [0, 0]
    assert list(cols["bins"]["phase"]) == [1] * 6  # 00:00-00:30 UTC is "night"
    assert list(cols["bins"]["day"]) == [0] * 6


def test_bundle_carries_no_entity_strings(golden):
    *_, bundle = golden
    for f in bundle.iterdir():
        data = f.read_bytes()
        assert b"person:" not in data and b"location:" not in data, f.name


def test_nodes_are_shuffled(tmp_path):
    inp = _golden()
    nodes = {f"person:{i:02d}": f"c{i:02d}" for i in range(20)}
    inp = BundleInput(**{**inp.__dict__, "nodes": nodes})
    meta = write_bundle(inp, tmp_path / "b", ExplorerConfig(), timezone="UTC")
    assert [n["course"] for n in meta["nodes"]] != list(range(20))


def test_bundle_inside_repo_is_refused():
    with pytest.raises(DataRootError):
        write_bundle(_golden(), REPO_ROOT / "bundle", CONFIG, timezone="UTC")


def test_synthetic_camp_pairs_match_truth(tmp_path):
    camp = generate(CampSpec(lost=None, reboot=None, swap=None), tmp_path / "camp")
    inp = synthetic_inputs(camp)
    meta = write_bundle(inp, tmp_path / "b", ExplorerConfig(), timezone=camp.spec.timezone)
    _, cols = read_bundle(tmp_path / "b")

    truth = (
        camp.truth_contacts.filter(
            pl.col("observer_entity").str.starts_with("person:")
            & pl.col("observed_entity").str.starts_with("person:")
        )
        .with_columns(
            pl.min_horizontal("observer_entity", "observed_entity").alias("a"),
            pl.max_horizontal("observer_entity", "observed_entity").alias("b"),
            pl.col("t").dt.truncate("5m").alias("bin"),
        )
        .select("a", "b", "bin")
        .unique()
    )
    t0 = datetime.fromisoformat(meta["t0"].replace("Z", "+00:00"))
    truth_per_bin = Counter(int((b - t0).total_seconds() // BIN) for b in truth["bin"])
    assert Counter(int(k) for k in cols["pairs"]["bin"]) == truth_per_bin
    assert meta["qa"]["pairs_no_node"] == 0


def test_synthetic_inputs_cover_a_camp_longer_than_a_day(tmp_path):
    spec = CampSpec(hours=36, lost=None, reboot=None, swap=None, id_bug_until_h=None)
    inp = synthetic_inputs(generate(spec, tmp_path / "camp"))
    assert inp.n_bins >= 36 * 12 - 1
    assert inp.rooms.height > 0  # people are placed in rooms
