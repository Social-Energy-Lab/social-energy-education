"""Person profiles of the EDA second pass (analysis G), on invented rows: the Spearman-Brown
reliability, the gate, consent and small-n withholding."""

import importlib.util
import math
import sys
from pathlib import Path

import polars as pl
import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "studies"
    / "dsa-2026"
    / "analyses"
    / "eda2_person_profiles.py"
)


@pytest.fixture(scope="module")
def g():
    spec = importlib.util.spec_from_file_location("eda2_person_profiles_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


def long(profile: str, disc: list, rep: list, all_: list | None = None) -> pl.DataFrame:
    rows = []
    for half, vals in (("discovery", disc), ("replication", rep), ("all", all_ or [])):
        rows += [
            {"entity": f"person:{i}", "half": half, "profile": profile, "value": v}
            for i, v in enumerate(vals)
            if v is not None
        ]
    return pl.DataFrame(rows, schema={"entity": pl.String, "half": pl.String,
                                      "profile": pl.String, "value": pl.Float64})  # fmt: skip


def test_spearman_brown(g):
    assert g.spearman_brown(0.5) == pytest.approx(2 / 3)
    assert g.spearman_brown(1.0) == 1.0
    assert g.spearman_brown(0.0) == 0.0
    assert g.spearman_brown(-0.2) == pytest.approx(-0.4 / 0.8)
    assert g.spearman_brown(-1.0) == -math.inf
    assert math.isnan(g.spearman_brown(math.nan))


def test_split_half_perfect_and_reversed(g):
    up = long("hrv_level", [1, 2, 3, 4, 5, 6], [10, 20, 30, 40, 50, 60])
    r = g.split_half(up, "hrv_level", n_boot=200)
    assert r["n_both"] == 6
    assert r["r_split"] == pytest.approx(1.0)
    assert r["reliability"] == pytest.approx(1.0)
    down = long("hrv_level", [1, 2, 3, 4, 5, 6], [6, 5, 4, 3, 2, 1])
    assert g.split_half(down, "hrv_level", n_boot=200)["reliability"] == -math.inf


def test_split_half_hand_value(g):
    # Ranks 1..5 against 2,1,3,4,5: d^2 sums to 2, rho = 1 - 6*2/(5*24) = 0.9.
    t = long("x", [1, 2, 3, 4, 5], [2, 1, 3, 4, 5])
    r = g.split_half(t, "x", n_boot=200)
    assert r["r_split"] == pytest.approx(0.9)
    assert r["reliability"] == pytest.approx(1.8 / 1.9)
    assert r["rel_lo"] <= r["reliability"] <= r["rel_hi"]


def test_split_half_needs_both_halves_and_min_group(g):
    # Six people, but only four have both halves: withheld.
    t = long("x", [1, 2, 3, 4, 5, 6], [1, 2, 3, 4, None, None])
    r = g.split_half(t, "x", n_boot=200)
    assert r["n_both"] == 4
    assert math.isnan(r["reliability"])
    assert math.isnan(g.split_half(long("x", [1, 2], []), "x")["r_split"])


def test_gate(g):
    assert g.passes(0.5)
    assert g.passes(0.9)
    assert not g.passes(0.49)
    assert not g.passes(math.nan)
    assert not g.passes(-math.inf)
    assert not g.passes(None)


def test_reliability_table_gates_only_reliable_profiles(g):
    stable = long("hrv_level", list(range(8)), list(range(8)))
    noisy = long("hrv_dose", [1, 2, 3, 4, 5, 6, 7, 8], [8, 1, 7, 2, 6, 3, 5, 4])
    tab = g.reliability_table(pl.concat([stable, noisy]), n_boot=200)
    assert set(tab["profile"]) == set(g.PROFILES)  # every profile reported, even empty ones
    gated = set(tab.filter(pl.col("passes_gate"))["profile"])
    assert gated == {"hrv_level"}
    empty = tab.filter(pl.col("profile") == "sync_dtonic").row(0, named=True)
    assert empty["n_both"] == 0 and not empty["passes_gate"]


def test_relations_respect_consent_and_withhold_small_n(g):
    vals = [float(i) for i in range(8)]
    prof = long("hrv_level", [], [], vals)
    targets = pl.DataFrame(
        {
            "entity": [f"person:{i}" for i in range(8)],
            "trust": vals,
            "lust": vals,
            "D_academy_lenient": [1.0, 2.0, 3.0, 4.0, None, None, None, None],
            "degree": [-v for v in vals],
        }
    )
    everyone = {f"person:{i}" for i in range(8)}
    consents = {"eda": everyone, "beacons": everyone, "interview_in_person": everyone,
                "survey": everyone - {"person:0", "person:1", "person:2", "person:3"}}  # fmt: skip
    rel = g.relations(prof, targets, ["hrv_level"], consents, n_boot=200)
    by = {r["target"]: r for r in rel.iter_rows(named=True)}
    assert by["degree"]["n"] == 8 and by["degree"]["rho"] == pytest.approx(-1.0)
    # Survey consent leaves four people: withheld.
    assert by["trust"]["n"] == 4 and by["trust"]["rho"] is None
    # Interview codes for four people only: withheld.
    assert by["D_academy_lenient"]["n"] == 4 and by["D_academy_lenient"]["rho"] is None
