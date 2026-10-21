"""Oracle test: synthetic SD cards → EDA ingest → spine → the true wear and SCRs come back.

The synthetic devices keep their own clocks: SH01 runs 3 % slow (a sync slave), SH02 0.6 %
slow (the master), SH03 keeps time (a slave, the reference). Truth is in true UTC; the
reference SH03 reads 0.2 s ahead of it, which the tolerances absorb.
"""

from datetime import timedelta

import numpy as np
import polars as pl
import pytest

from social_energy.eda.box import BoxConfig
from social_energy.eda.clock import ClockConfig
from social_energy.eda.ingest import EdaConfig, ingest_eda
from social_energy.eda.person import person_minutes
from social_energy.spine import Spine
from social_energy.synth.eda import EdaSpec, generate_eda


def config_for(synth, **kw) -> EdaConfig:
    day = synth.spec.start.date()
    t0 = synth.spec.start.timestamp()
    return EdaConfig(
        valid_from=day,
        valid_to=day,
        mtime_to_utc_s=synth.spec.mtime_offset_s,
        rotation_s=synth.spec.chunk_s,
        clock=ClockConfig(reference_devices=("SH03",)),
        comotion_windows=((t0 + synth.spec.box_from_min * 60 + 30, t0 + synth.spec.minutes * 60),),
        comotion_window_s=120.0,
        **kw,
    )


@pytest.fixture(scope="module")
def synth(tmp_path_factory):
    return generate_eda(EdaSpec(), tmp_path_factory.mktemp("eda"))


@pytest.fixture(scope="module")
def tables(synth):
    return ingest_eda(synth.cards, [], config_for(synth))


@pytest.fixture(scope="module")
def uncorrected(synth):
    return ingest_eda(synth.cards, [], config_for(synth, correct_clocks=False))


def test_copies_are_read_once_and_the_late_run_is_unanchored(synth, tables):
    dup = tables.files.filter("duplicate")
    assert dup.height > 0 and dup["run"].str.ends_with(" 2").all()
    assert tables.qa["sd_records_unanchored"] == 3 * 3800  # one late run per device
    assert tables.qa["seconds_implausible"] == 0


def test_the_traps_are_actually_present(tables):
    assert tables.qa["sd_records_zero"] > 0 and tables.qa["sd_records_bad"] > 0
    assert tables.files.filter(pl.col("truncated")).height == 3


def test_chunks_are_placed_by_their_headers_not_by_modification_times(tables):
    """Every chunk has a header, so nothing falls back to the modification times."""
    assert tables.qa["sd_records_by_mtime"] == 0 and tables.qa["sd_segments_by_mtime"] == 0


def test_the_clock_model_recovers_each_units_rate(tables):
    """Error rates per hour of the device's own clock: SH01 -0.03 / 0.97 x 3600 = -111.3 s/h,
    the master SH02 -0.006 / 0.994 x 3600 = -21.73 s/h, SH03 0. SH01's two bogus records
    (one in a corrupt block, never read as a record; one with a plausible shape 3112 s off)
    do not count."""
    clock = tables.clock.filter(pl.col("run").str.ends_with("-000")).sort("device")
    rates = dict(zip(clock["device"], clock["rate_s_per_h"], strict=True))
    assert abs(rates["SH01"] - (-111.34)) < 0.5
    assert abs(rates["SH02"] - (-21.73)) < 0.3
    assert abs(rates["SH03"]) < 0.1
    sh01 = clock.row(0, named=True)
    assert sh01["kind"] == "sync" and sh01["records"] == sh01["inliers"] + 1
    assert clock.filter(device="SH02")["kind"].item() == "master"
    assert not clock["uncertain"].any()


def test_corrected_seconds_carry_the_correction_they_got(synth, tables):
    """At true minute 18, SH01's clock reads 0.4 - 0.03 x 1080 = -32.0 s off true, and the
    reference 0.2 s ahead: the correction is +32.2 s."""
    t = synth.spec.start + timedelta(minutes=18)
    row = tables.seconds.filter(
        (pl.col("device") == "SH01") & (pl.col("t") == t.replace(microsecond=0))
    )
    assert abs(row["clock_correction_s"].item() - 32.2) < 0.3
    assert not tables.seconds["clock_uncertain"].any()


def test_wear_bouts_match_the_truth(synth, tables):
    """Each device's bout starts and ends within 2 s of when the electrodes met the skin."""
    got = tables.wear.sort("device", "start")
    want = synth.truth_wear.sort("device", "start")
    assert got["device"].to_list() == want["device"].to_list()
    for g, w in zip(got.iter_rows(named=True), want.iter_rows(named=True), strict=True):
        assert abs(g["start"] - w["start"]) <= timedelta(seconds=2)
        assert abs(g["end"] - w["end"]) <= timedelta(seconds=2)
    assert not tables.wear["clock_uncertain"].any()


def _onset_errors_s(synth, tables) -> np.ndarray:
    got = tables.scr.filter(pl.col("ok") & pl.col("worn")).sort("device", "onset")
    want = synth.truth_scr.sort("device", "onset")
    assert got.height == want.height
    return (got["onset"] - want["onset"]).dt.total_milliseconds().abs().to_numpy() / 1000


def test_scr_onsets_and_amplitudes_match_the_truth(synth, tables):
    """Every true SCR is found within 1 s, with no extra ones, amplitudes within 15%."""
    assert (_onset_errors_s(synth, tables) <= 1.0).all()
    got = tables.scr.filter(pl.col("ok") & pl.col("worn")).sort("device", "onset")
    want = synth.truth_scr.sort("device", "onset")
    assert np.allclose(got["amplitude_us"], want["amplitude_us"], rtol=0.15, atol=0)


def test_without_the_correction_the_slow_unit_is_seconds_off(synth, uncorrected):
    """The negative control: on its own clock, SH01's SCRs (minutes 8 to 22) sit 14-40 s
    early; the reference unit's are right."""
    err = _onset_errors_s(synth, uncorrected)
    devices = synth.truth_scr.sort("device", "onset")["device"].to_numpy()
    assert (err[devices == "SH01"] > 10).all()


def test_devices_lying_together_agree_after_correction(tables):
    """In the box (shared motion bursts) every device's co-motion residual is under 0.1 s."""
    c = tables.comotion
    assert sorted(c["device"]) == ["SH01", "SH02", "SH03"]
    assert c["residual_s"].abs().max() < 0.1
    assert tables.qa["comotion"]["device_days"] == 3 and tables.qa["comotion"]["max_abs_s"] < 0.1


def test_person_minutes_respect_consent(synth, tables):
    """Only the consenting wearer (SH01) appears, one row per observable minute of wear, with
    every observable SCR of theirs."""
    minutes, qa = person_minutes(tables, Spine.load(synth.spine_dir))
    assert minutes["entity"].unique().to_list() == ["person:11"]
    wear = synth.truth_wear.filter(device="SH01")
    worn_min = sum((r["end"] - r["start"]).total_seconds() for r in wear.iter_rows(named=True))
    assert abs(minutes.height - worn_min / 60) <= 1
    assert minutes["scr_n"].sum() == synth.truth_scr.filter(device="SH01").height
    assert qa["worn_seconds_no_consent"] > 0
    assert not minutes["clock_uncertain"].any()


@pytest.fixture(scope="module")
def with_exports(tmp_path_factory):
    synth = generate_eda(EdaSpec(exports=True), tmp_path_factory.mktemp("eda_exp"))
    return synth, ingest_eda(synth.cards, synth.exports, config_for(synth))


def test_an_export_is_matched_to_its_card_and_fills_what_the_card_lost(with_exports):
    """SH01's export has the device's clock minus one sync offset (Shimmer Base's constant),
    and a 630-s hole the export's repair can only bridge modulo 512 s, so its second segment
    sits 512 s early. Each segment is matched to the card row for row: the first lag is the
    constant (within 0.05 s), the second is off by a whole wrap. Corrected through the card's
    clock model, its seconds coincide with the card's (flagged duplicate, the card wins), and
    the ones the card lost (chunk 2's tail, in the second segment) come back at their true
    times, within 1.5 s."""
    synth, t = with_exports
    f = t.files.filter((pl.col("source") == "export") & (pl.col("device") == "SH01")).row(
        0, named=True
    )
    assert f["clock_model"] == "sd-sync" and f["clock_uncertain"]  # the borrowed segment
    assert abs(f["export_offset_s"] - (-synth.notes["export_constant_s"])) < 0.05
    assert f["export_lag_changes"] == 1  # one jump of a whole wrap, at the hole
    exp = t.seconds.filter((pl.col("source") == "export") & (pl.col("device") == "SH01"))
    only = exp.filter(~pl.col("duplicate"))
    lo, hi = synth.notes["sh01_lost"]
    sec = only["t"].dt.epoch("s").to_numpy()
    inner = sec[(sec > lo - 60) & (sec < hi + 60)]
    assert abs(inner.min() - lo) <= 1.5 and abs(inner.max() + 1 - hi) <= 1.5
    assert exp["duplicate"].mean() > 0.6
    a, b = synth.notes["sh01_unmatched_segment"]
    t_s = exp["t"].dt.epoch("s")
    borrowed = exp.filter((t_s > a + 2) & (t_s < b - 2))
    assert borrowed.height > 100 and borrowed["clock_uncertain"].all()
    assert not exp.filter((t_s < a - 2) | (t_s > b + 2))["clock_uncertain"].any()


def test_an_export_without_a_clock_is_placed_from_its_session(with_exports):
    """SH04's export has -1 in every timestamp and no card. Its session peer (SH01's export)
    started with it, so it is placed from that export's corrected start: its wear bout is within
    2 s of the truth, flagged clock_uncertain, and it reaches person-minutes.
    """
    synth, t = with_exports
    f = t.files.filter(pl.col("device") == "SH04").row(0, named=True)
    assert f["clock"] == "recovered" and f["clock_uncertain"]
    got = t.wear.filter(device="SH04")
    want = synth.truth_wear.filter(device="SH04")
    assert got.height == 1 and got["clock_uncertain"].item()
    assert abs(got["start"].item() - want["start"].item()) <= timedelta(seconds=2)
    minutes, _ = person_minutes(t, Spine.load(synth.spine_dir))
    sh04 = minutes.filter(entity="person:14")
    assert sh04.height > 30 and sh04["clock_uncertain"].all()
    assert set(sh04["clock_source"]) == {"rate"}


# SH05 never writes a sync record (sync on, but silent) and truly loses 0.025 % (0.9 s/h,
# under the 1 s/h a box-only clock may drift) from its start, when it was set to the
# reference's time (SH03 reads 0.2 s ahead of true time); its configured fallback rate is 0.
# It lies in the box with the others.
SILENT = ("SH05", "silent", -0.00025, 0.2)
BOX = BoxConfig(window_s=120.0, max_lag_s=20.0, min_stretch_s=300.0)


@pytest.fixture(scope="module")
def silent(tmp_path_factory):
    spec = EdaSpec(clocks=(*EdaSpec().clocks, SILENT))
    synth = generate_eda(spec, tmp_path_factory.mktemp("silent"))
    with_box = ingest_eda(synth.cards, [], config_for(synth, box=BOX))
    without = ingest_eda(synth.cards, [], config_for(synth, box=BoxConfig(enabled=False)))
    return synth, with_box, without


def _sh05_at(tables, synth, minute):
    t = synth.spec.start + timedelta(minutes=minute)
    return tables.seconds.filter((pl.col("device") == "SH05") & (pl.col("t") == t)).row(
        0, named=True
    )


def test_the_box_measures_a_unit_without_sync_records(silent):
    """At true minute 20, SH05 reads 0.00025 x 1200 = 0.3 s behind: the box-anchored model
    corrects it by +0.3 s (within 0.05), with source ``box`` and no flag. Without the box it
    keeps its fallback (rate 0: no correction), flagged."""
    synth, with_box, without = silent
    row = _sh05_at(with_box, synth, 20)
    assert abs(row["clock_correction_s"] - 0.3) < 0.05
    assert row["clock_source"] == "box" and not row["clock_uncertain"]
    sh05 = with_box.seconds.filter(device="SH05")
    assert not sh05["clock_uncertain"].any() and set(sh05["clock_source"]) == {"box"}
    clock = with_box.clock.filter((pl.col("device") == "SH05") & pl.col("run").str.ends_with("0"))
    assert clock["kind"].to_list() == ["box"] and clock["anchors"].item() == 1
    assert abs(clock["rate_s_per_h"].item() + 0.9) < 0.1
    box = with_box.box.filter(device="SH05").row(0, named=True)
    assert box["status"] == "anchor" and box["triangle"]
    # The measured units are checked by the same box, within a tenth of a second.
    known = with_box.box.filter(pl.col("device") != "SH05")
    assert set(known["status"]) == {"check"} and known["residual_s"].abs().max() < 0.1
    # Leave-one-out: SH01 (3 % slow) without its records comes back from the box, where its
    # fallback would be the unit's own rate (no other run): no correction at all. SH03, the
    # only reference unit, cannot: without its records no clock is measured.
    loo = with_box.box_loo.sort("device")
    assert loo["device"].to_list() == ["SH01", "SH03"] and loo["anchors"].to_list() == [1, 0]
    sh01 = loo.row(0, named=True)
    assert sh01["box_max_abs_s"] < 0.5 and sh01["fallback_max_abs_s"] > 60
    old = _sh05_at(without, synth, 20)
    assert abs(old["clock_correction_s"]) < 0.01
    assert old["clock_source"] == "rate" and old["clock_uncertain"]
