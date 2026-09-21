---
name: add-data-source
description: "Use when adding ingest for a new instrument or export format (e.g. Shimmer EDA, AudioMoth WAV features, SurveyJS export, interview transcripts) or changing an existing one's canonical tables."
---

# Add a data source

Each data source gets one toolkit subpackage (`src/social_energy/<source>/`), one context doc (`docs/context/instruments/<source>.md`), and tests on synthetic data. Follow the order below. Each step is a commit.

## 1. Document the instrument first

Write or extend `docs/context/instruments/<source>.md`:
- **What it measures**, and what it cannot measure.
- **Raw format**, exactly: file naming, columns/lines, units, clock/timezone semantics, IDs.
- **How it was deployed**: who wore it, when, and which settings changed mid-study. Instrument-level facts only. Per-study facts go in `studies/<id>/study.yaml`.
- **Known traps**: clock drift, resets, gaps, device swaps, firmware bugs. Each one becomes a flag or a test.
- **Privacy**: which fields are sensitive, and what must never be stored. Example: AudioMoth WAVs must be deleted after feature extraction, per the ethics approval.
- Mark anything not confirmed by the research team as `[inferred]` or `[unknown: …]`.

## 2. Golden fixture + failing tests

- Hand-write a tiny raw file in `tests/fixtures/<source>/` covering every record type and every known trap.
- Derive the expected canonical rows **by hand** and explain the arithmetic in the test docstring.
- Run the tests and watch them fail.

## 3. Canonical tables

- A pure function `ingest_*(paths, config) -> <Source>Tables`. It takes no global state and never calls `paths.data_root()` itself.
- Config is a frozen dataclass of *instrument* parameters. The study provides the values.
- Output: `polars` frames keyed by **device** (`beacon`, `eda`, …) and timezone-aware **UTC** times. Keep provenance (`source`, `line_no` or similar).
- **Flag, don't drop.** Add boolean flags plus an `ok` column. The QA dict must account for every input record.
- Never resolve devices to people here. That is `Spine.resolve`.

## 4. Synthetic generator + oracle test

- Extend `social_energy.synth` so the synthetic camp also emits this source in its raw format, with known ground truth that includes the traps.
- Oracle test: synth → ingest → spine → equals the ground truth. Then break the code on purpose once to prove the test can fail.

## 5. Wire into docs

- Update the instrument doc, the layout line in `AGENTS.md`, and the study's `README.md` data-source table.
- Run `uv run ruff check . && uv run ruff format --check . && uv run pytest`.
