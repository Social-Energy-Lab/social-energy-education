"""Self-report button presses → press episodes.

The firmware makes one self-report event per press held for at least 3 s, with no cooldown, so
several events are several presses: a person pressing again (a second thought, or the cancel press
participants were told about), or a tag pressed over and over in a bag, which yields a long run.
A *chain* is a run of presses each within ``chain_s`` of the previous one; a chain
lasting ``accidental_s`` or holding ``accidental_n`` presses is accidental and dropped. The
remaining presses within ``episode_s`` of the previous one form one episode.

The thresholds are the study's choice and are passed in.
"""

from __future__ import annotations

import polars as pl


def press_episodes(
    presses: pl.DataFrame,
    *,
    chain_s: int,
    accidental_s: int,
    accidental_n: int,
    episode_s: int,
    entity_col: str = "entity",
) -> tuple[pl.DataFrame, dict[str, int]]:
    """Episodes as ``entity``, ``t`` (first press) and ``raw_presses``, plus a QA dict."""
    gap = pl.col("t").diff().over(entity_col).dt.total_seconds()
    df = (
        presses.sort(entity_col, "t")
        .with_columns((gap.fill_null(chain_s + 1) > chain_s).cum_sum().over(entity_col).alias("_c"))
        .with_columns(
            (
                ((pl.col("t").max() - pl.col("t").min()).dt.total_seconds() >= accidental_s)
                | (pl.len() >= accidental_n)
            )
            .over(entity_col, "_c")
            .alias("_accidental")
        )
    )
    accidental = df.filter(pl.col("_accidental"))
    qa = {
        "accidental_chains": accidental.select(entity_col, "_c").n_unique(),
        "accidental_presses": accidental.height,
    }
    episodes = (
        df.filter(~pl.col("_accidental"))
        .with_columns(
            (gap.fill_null(episode_s) >= episode_s).cum_sum().over(entity_col).alias("_e")
        )
        .group_by(entity_col, "_e")
        .agg(pl.col("t").min(), pl.len().alias("raw_presses"))
        .drop("_e")
        .sort(entity_col, "t")
    )
    qa["episodes"] = episodes.height
    qa["pressers"] = episodes[entity_col].n_unique()
    return episodes, qa
