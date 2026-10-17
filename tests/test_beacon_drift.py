"""Timer drift: tags whose uptime counter runs fast against the logger clock.

Oracle: a synthetic camp whose tags all count 500 ppm fast for 60 hours. Uptime then runs ahead of
real time by 43 s a day, and up to about 2 minutes by the end of the camp (tags booted up to 14 h
before it started). Dating records as boot + uptime puts them late by that much; dating them as
boot + uptime / (1 + rate) recovers the true times to within the logger's 1-s rounding.
"""

from datetime import timedelta

import polars as pl
import pytest

from social_energy.beacons import BeaconConfig, estimate_clock_rate, ingest_logs
from social_energy.synth import CampSpec, generate

RATE = 500.0


@pytest.fixture(scope="module")
def camp(tmp_path_factory):
    spec = CampSpec(hours=60, clock_rate_ppm=RATE, reboot=None, swap=None, lost=None,
                    id_bug_until_h=None)  # fmt: skip
    return generate(spec, tmp_path_factory.mktemp("drift_camp"))


def config(camp, rate: float) -> BeaconConfig:
    spec = camp.spec
    return BeaconConfig(
        timezone=spec.timezone,
        valid_from=spec.start.date(),
        valid_to=(spec.start + timedelta(hours=spec.hours)).date(),
        clock_rate_ppm=rate,
    )


def worst_error_s(camp, rate: float) -> float:
    """Largest gap between an ingested self-report and its true time, in seconds."""
    sr = ingest_logs(camp.log_paths, config(camp, rate)).self_reports
    got = sr.select(pl.col("beacon").cast(pl.String).alias("b"), "t").sort("t")
    truth = camp.truth_self_reports.select(
        pl.col("entity").str.replace("person:", "").alias("b"), pl.col("t").alias("t_true")
    ).sort("t_true")
    pairs = got.join_asof(
        truth, left_on="t", right_on="t_true", by="b", strategy="nearest", check_sortedness=False
    )
    assert pairs["t_true"].null_count() == 0
    assert pairs.height == truth.height
    return (pairs["t"] - pairs["t_true"]).dt.total_seconds().abs().max()


def test_uncorrected_dating_drifts_by_minutes(camp):
    assert worst_error_s(camp, 0.0) > 60


def test_correcting_for_the_rate_recovers_true_times(camp):
    assert worst_error_s(camp, RATE) <= 2


def test_the_rate_is_estimated_from_the_readouts(camp):
    readouts = ingest_logs(camp.log_paths, config(camp, 0.0)).readouts
    estimate = estimate_clock_rate(readouts, restart_margin_s=3600)
    assert estimate["cycles_used"] == len(camp.spec.people)
    assert abs(estimate["ppm"] - RATE) < 20
