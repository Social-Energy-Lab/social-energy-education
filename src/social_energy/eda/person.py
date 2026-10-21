"""EDA per person-minute, resolved through the spine (AGENTS.md invariant 4).

Only seconds that are ``ok`` and inside a wear bout count; conductance is summarised over the
ones without an artifact (``artifact_s`` says how many had one), and SCRs touching an artifact
are not counted. People without EDA consent are
removed entirely: their data may not be used, so it is not carried in a flag. Exclusion
windows are flagged (``excluded``), so filtering them stays the analyst's visible choice.
"""

from __future__ import annotations

from typing import Any

import polars as pl

from ..spine import Spine
from .ingest import EdaTables


def person_minutes(tables: EdaTables, spine: Spine) -> tuple[pl.DataFrame, dict[str, Any]]:
    consented = [f"person:{i}" for i in spine.consented("eda")]
    worn = tables.seconds.filter(pl.col("ok") & pl.col("worn"))
    s = spine.resolve(worn, device_col="device", time_col="t", kind="eda", out="entity")
    unassigned = int(s["entity"].is_null().sum())
    no_consent = int((s["entity"].is_not_null() & ~s["entity"].is_in(consented)).sum())
    s = s.filter(pl.col("entity").is_in(consented))
    s = spine.flag_excluded(s, device_col="device", time_col="t", kind="eda")
    clean = pl.col("conductance_us").filter(~pl.col("artifact"))
    minutes = s.group_by("entity", pl.col("t").dt.truncate("1m").alias("minute")).agg(
        pl.col("device").first(),
        pl.len().alias("worn_s"),
        pl.col("artifact").sum().alias("artifact_s"),
        clean.mean().alias("conductance_us"),
        clean.median().alias("conductance_median_us"),
        pl.col("motion_sd_g").mean().alias("motion_sd_g"),
        pl.col("hr_bpm").mean().alias("hr_bpm"),
        pl.col("source").first(),
        pl.col("excluded").any(),
    )
    scr = spine.resolve(
        tables.scr.filter(pl.col("ok") & pl.col("worn") & ~pl.col("artifact")),
        device_col="device",
        time_col="onset",
        kind="eda",
        out="entity",
    ).filter(pl.col("entity").is_in(consented))
    per_minute = scr.group_by("entity", pl.col("onset").dt.truncate("1m").alias("minute")).agg(
        pl.len().cast(pl.Int64).alias("scr_n"), pl.col("amplitude_us").sum().alias("scr_amp_us")
    )
    minutes = (
        minutes.join(per_minute, on=["entity", "minute"], how="left")
        .with_columns(pl.col("scr_n").fill_null(0), pl.col("scr_amp_us").fill_null(0.0))
        .sort("entity", "minute")
    )
    qa = {
        "worn_seconds": worn.height,
        "worn_seconds_unassigned": unassigned,
        "worn_seconds_no_consent": no_consent,
        "person_minutes": minutes.height,
        "people": minutes["entity"].n_unique(),
    }
    return minutes, qa
