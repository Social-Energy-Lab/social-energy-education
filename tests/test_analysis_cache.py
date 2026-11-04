"""Analyses reuse tables built from the contacts only while the contacts have not changed."""

import os
import sys
from pathlib import Path

from social_energy import paths

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "studies" / "dsa-2026" / "analyses"))

import copresence_by_phase as cp  # noqa: E402


def test_a_cache_older_than_the_ingest_or_the_spine_is_not_reused(tmp_path, monkeypatch):
    monkeypatch.setenv("SOCIAL_ENERGY_DATA", str(tmp_path))
    layout = paths.study("some-study")
    qa = layout.derived / "beacons" / "qa.json"
    spine = layout.spine / "people.yaml"
    cache = tmp_path / "cache.parquet"
    for f in (qa, spine, cache):
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x")
    os.utime(qa, (100, 100))
    os.utime(spine, (100, 100))

    assert not cp.cache_is_current(layout, tmp_path / "absent.parquet")
    os.utime(cache, (200, 200))
    assert cp.cache_is_current(layout, cache)
    os.utime(qa, (300, 300))
    assert not cp.cache_is_current(layout, cache)
    os.utime(qa, (100, 100))
    os.utime(spine, (300, 300))
    assert not cp.cache_is_current(layout, cache)
