"""Explorer inputs from a synthetic camp: for tests, development and a public demo.

Runs the synthetic camp through the real pipeline (ingest, spine resolution, presence), so a
bundle made here exercises the same code paths as one made from field data.
"""

from __future__ import annotations

import tempfile
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import numpy as np
import polars as pl

from ..beacons import BeaconConfig, ingest_logs
from ..presence import copresence, room_per_bin
from ..spine import Spine
from ..study import ExplorerConfig
from ..synth import CampSpec, SyntheticCamp, generate
from .bundle import BundleInput, write_bundle
from .person import EDA_SCHEMA, PersonData

BIN_SECONDS = 300


def synthetic_inputs(camp: SyntheticCamp, *, persons: bool = False, seed: int = 0) -> BundleInput:
    """Bundle inputs for every person in ``camp``; each room is its own zone.

    With ``persons`` the inputs also carry made-up person-view data (``synthetic_persons``).
    """
    spec = camp.spec
    config = BeaconConfig(
        timezone=spec.timezone,
        valid_from=spec.start.date(),
        valid_to=(spec.start + timedelta(hours=spec.hours)).date(),
        ambiguous_id_cutoff=camp.id_bug_cutoff,
    )
    tables = ingest_logs(camp.log_paths, config)
    spine = Spine.load(camp.spine_dir)
    contacts = spine.resolve(
        tables.contacts, device_col="beacon", time_col="t", kind="beacon", out="observer_entity"
    )
    contacts = spine.resolve(
        contacts, device_col="observed", time_col="t", kind="beacon", out="observed_entity"
    ).filter(pl.col("ok") & pl.col("observer_entity").is_not_null())
    contacts = contacts.filter(pl.col("observed_entity").is_not_null())
    reports = spine.resolve(
        tables.self_reports, device_col="beacon", time_col="t", kind="beacon", out="entity"
    ).filter(pl.col("ok") & pl.col("entity").is_not_null())

    people = sorted({p.ref for p in spine.people})
    rooms = {loc.ref: (loc.label, loc.zone) for loc in spine.locations}
    pairs = copresence(contacts, every=f"{BIN_SECONDS}s")
    seen = (
        pl.concat(
            [
                contacts.select(pl.col("observer_entity").alias("entity"), "t"),
                contacts.select(pl.col("observed_entity").alias("entity"), "t"),
            ]
        )
        .filter(pl.col("entity").is_in(people))
        .select("entity", pl.col("t").dt.truncate(f"{BIN_SECONDS}s").alias("bin"))
        .unique()
    )
    t0 = seen["bin"].min()
    n_bins = int((seen["bin"].max() - t0) / timedelta(seconds=BIN_SECONDS)) + 1
    # Two synthetic "courses", alternating, so course views have something to show.
    nodes = {p: f"{i % 2 + 1}" for i, p in enumerate(people)}
    inp = BundleInput(
        t0=t0,
        n_bins=n_bins,
        bin_seconds=BIN_SECONDS,
        nodes=nodes,
        locations=rooms,
        pairs=pairs.select("a", "b", "bin", "max_rssi"),
        seen=seen,
        # One scan per bin in the synthetic camp, so one hit must be enough to place someone.
        rooms=room_per_bin(contacts, every=f"{BIN_SECONDS}s", min_hits=1).select(
            "entity", "bin", "location"
        ),
        presses=reports.select("entity", "t"),
        rssi_floor=int(pairs["max_rssi"].min()) if pairs.height else -128,
    )
    return replace(inp, persons=synthetic_persons(inp, seed=seed)) if persons else inp


#: Made-up survey scales: (key, label, block, in the composite), four items each, range 1-4.
SYNTHETIC_SCALES = [
    ("t_belonging", "belonging", "trust", True),
    ("t_teacher", "teacher-student relationship", "trust", True),
    ("t_family", "family support", "trust", True),
    ("t_perspective", "perspective-taking", "trust", False),
    ("l_efficacy", "self-efficacy", "lust", True),
    ("l_openness", "openness to the unknown", "lust", True),
    ("l_perseverance", "perseverance", "lust", True),
    ("l_cooperation", "cooperation", "lust", False),
]
OPENERS = ["people", "being_heard", "course", "arts", "freedom"]
CLOSERS = ["fatigue", "withdrawal_need", "pressure"]


def synthetic_persons(inp: BundleInput, seed: int = 0) -> PersonData:
    """Made-up person-view data for the people in ``inp``: no real person behind any of it.

    Consent leaves some people out of each module, so the view's consent handling shows. EDA
    is worn in daytime with gaps; one stretch per wearer has an uncertain clock; SCR bursts
    make a few EDA moments. Events: an all-camp plenum every fourth hour (as the synthetic camp
    places people) and a block in every other room the rest of the time.
    """
    rng = np.random.default_rng(seed)
    people = sorted(inp.nodes)
    n = len(people)
    t0 = inp.t0
    span_s = inp.n_bins * inp.bin_seconds

    def subset(share: float) -> frozenset[str]:
        return frozenset(p for p in people if rng.random() < share)

    consent = {
        "survey": subset(0.9),
        "interview_in_person": subset(0.8),
        "eda": subset(0.6),
        "self_report": frozenset(people),
    }
    attributes = {
        p: {"age": int(rng.integers(15, 19)), "gender": str(rng.choice(["f", "m", "d"]))}
        for p in people
    }

    # Survey: a latent trust and lust per person; items around them.
    latent = {p: rng.normal(0, 1, 2) for p in people}
    scales, comp, scores, items = [], [], [], []
    for key, label, block, core in SYNTHETIC_SCALES:
        codes = [f"{key.upper()}_{i:02d}" for i in range(1, 5)]
        scales.append({"key": key, "label": label, "block": block, "kind": "scale",
                       "core": core, "items": codes, "range": [1, 4]})  # fmt: skip
    for p in people:
        z_by_block = {"trust": [], "lust": []}
        for key, _, block, core in SYNTHETIC_SCALES:
            mu = 2.5 + 0.5 * latent[p][0 if block == "trust" else 1]
            vals = np.clip(np.round(rng.normal(mu, 0.7, 4)), 1, 4)
            for i, v in enumerate(vals, 1):
                items.append((p, "pre", key, f"{key.upper()}_{i:02d}", float(v)))
            scores.append((p, "pre", key, float(vals.mean())))
            if core:
                z_by_block[block].append(float(vals.mean()))
        comp.append((p, "pre", float(np.mean(z_by_block["trust"])) - 2.5,
                     float(np.mean(z_by_block["lust"])) - 2.5))  # fmt: skip
    composites = pl.DataFrame(comp, schema=["entity", "wave", "trust", "lust"], orient="row")
    scale_scores = pl.DataFrame(scores, schema=["entity", "wave", "group", "mean"], orient="row")
    item_df = pl.DataFrame(items, schema=["entity", "wave", "group", "item", "value"], orient="row")

    # Interview codes and times.
    membrane, interviews = {}, {}
    for p in people:
        arrival = int(rng.integers(2, 5))
        lenient = int(min(5, arrival + rng.integers(0, 3)))
        direction = "opened" if lenient > arrival else "stable"
        membrane[p] = {
            "M_everyday": {"value": int(rng.integers(2, 5)), "confidence": "high", "led": False},
            "M_arrival": {"value": arrival, "confidence": "medium", "led": False},
            "M_now": {"value": min(4, lenient), "confidence": "high", "led": False},
            "M_now_lenient": {"value": lenient, "confidence": "high", "led": False},
            "D_academy_lenient": lenient - arrival,
            "direction": {"value": direction, "confidence": "high"},
            "change_amount": {"value": lenient - arrival, "confidence": "medium"},
            "selective": bool(rng.random() < 0.2),
            "primed": bool(rng.random() < 0.3),
            "openers": sorted(set(rng.choice(OPENERS, 2).tolist())),
            "closers": sorted(set(rng.choice(CLOSERS, 1).tolist())),
            "episodes": [{"direction": "open", "category": "people",
                          "day": (t0 + timedelta(seconds=float(rng.uniform(0, span_s))))
                          .date().isoformat()}],
        }  # fmt: skip
        interviews[p] = t0 + timedelta(seconds=float(rng.uniform(0.6, 0.95) * span_s))

    # EDA: worn minutes for consenting people, with gaps, bursts and an uncertain stretch.
    rows = []
    n_min = span_s // 60
    for p in sorted(consent["eda"]):
        worn = rng.random(n_min) > 0.15
        worn[rng.integers(0, n_min - 60) :][:60] = False  # one long gap
        uncertain = np.zeros(n_min, bool)
        u0 = int(rng.integers(0, max(1, n_min - 90)))
        uncertain[u0 : u0 + 90] = True
        base = rng.gamma(2.0, 1.0, n_min)
        for b in rng.integers(0, n_min, 3):
            base[b : b + 3] += 8
        hr = 75 + 8 * rng.standard_normal(n_min)
        for m in np.flatnonzero(worn):
            usable = bool(rng.random() > 0.1)
            hr_ok = bool(rng.random() > 0.2)
            scr = float(base[m]) if usable else None
            strict = scr * 0.4 if scr is not None else None
            beat = float(hr[m]) if hr_ok else None
            t = t0 + timedelta(minutes=int(m))
            rows.append((p, t, scr, strict, beat, usable, hr_ok, bool(uncertain[m])))
    eda = pl.DataFrame(rows, schema=EDA_SCHEMA, orient="row")

    # Programme: a plenum every fourth hour, all camp; a block in every other room otherwise.
    plenum = [loc for loc, (label, _) in inp.locations.items() if label == "plenum"]
    others = [loc for loc in sorted(inp.locations) if loc not in plenum]
    ev = []
    for h in range(0, span_s // 3600):
        start = t0 + timedelta(hours=h)
        if h % 4 == 0:
            ev.append(("plenum", "plenum", start, start + timedelta(hours=1), True, True, plenum))
        else:
            ev.append(("course block", "course", start, start + timedelta(hours=1), h % 3 != 0,
                       False, others))  # fmt: skip
    events = pl.DataFrame(
        ev,
        schema={"label": pl.String, "kind": pl.String, "start": pl.Datetime("us", "UTC"),
                "end": pl.Datetime("us", "UTC"), "end_known": pl.Boolean,
                "all_camp": pl.Boolean, "locations": pl.List(pl.String)},
        orient="row",
    )  # fmt: skip
    del n
    return PersonData(
        consent=consent,
        attributes=attributes,
        scales=scales,
        composites=composites,
        scale_scores=scale_scores,
        items=item_df,
        membrane=membrane,
        interviews=interviews,
        eda=eda,
        events=events,
        notes={"waves": "Synthetic data: a single (pre) wave."},
    )


def demo_bundle(out_dir: Path, config: ExplorerConfig, *, timezone: str, seed: int = 0) -> Path:
    """A synthetic team-style bundle with the person view, for ``social-energy explore --demo``."""
    spec = CampSpec(
        hours=48, people=tuple(range(44, 64)), lost=None, reboot=None, swap=None,
        id_bug_until_h=None, seed=seed + 7, timezone=timezone,
    )  # fmt: skip
    with tempfile.TemporaryDirectory(prefix="see-camp-") as tmp:
        inp = synthetic_inputs(generate(spec, Path(tmp) / "camp"), persons=True, seed=seed)
    # Spread the people over the study's own course keys, so the legend matches its names.
    keys = list(config.courses) or ["1", "2"]
    inp = replace(inp, nodes={p: keys[i % len(keys)] for i, p in enumerate(sorted(inp.nodes))})
    write_bundle(inp, out_dir, config, timezone=timezone, mode="synthetic", seed=seed)
    return out_dir
