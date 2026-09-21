# Foundation: repo skeleton, data perimeter, spine, beacon ingest, synthetic camp

**Goal:** a public methods repo that is useful before any real data arrives. It covers the agent context, the privacy guardrails, the study spine, and a beacon ingest tool tested against a synthetic camp.

## Status

- **Updated:** 2026-09-21
- **Priority:** high
- **Stage:** all implementation tasks done; the only remaining task is review and publishing
- **Branch:** `main` (local only, no remote yet)
- **Done:** see Tasks
- **Next:** Álvaro reviews the first commit. Then `gh repo create alvaro-francisco-gil/social-energy --public`, and CI goes green on GitHub.
- **Blockers:** Shimmer EDA exports are still being collected by Mahdi. **Beacons are no longer a blocker:** the full delivery (105 logs, 13–29 Aug, plus upstream-derived tables) was imported on 2026-09-20; follow-up in `ideas/beacon-differential-check.md` and `ideas/beacon-device-reuse.md`. The AI interviews and the survey are downloadable (`fetch-zeitgeist`, see `docs/context/data-layout.md`); linking them to study IDs is in `ongoing/dsa-2026-spine.md`
- **Handoff:** `uv sync && uv run pytest` runs the whole suite on synthetic data. Run `git config core.hooksPath .githooks` once per clone to enable the data-perimeter pre-commit hook. The private context library for DSA 2026 is at `$SOCIAL_ENERGY_DATA/dsa-2026/context/` (Álvaro's machine: `~/research-data/social-energy`). Follow-up work is planned in `ongoing/dsa-2026-spine.md` and `ideas/*`. Survey ingest continues in `ongoing/survey-scoring.md`.

## Context

Mahdi Srour's PhD studies Hartmut Rosa's concept of *social energy*. The first field phase was the Deutsche SchülerAkademie in Schwäbisch Gmünd, 13–29 Aug 2026. It combined BLE proximity beacons with a self-report button, Shimmer EDA sensors, two AudioMoth recorders, a SurveyJS questionnaire, interviews and field notes. More field phases are planned (START-Stiftung, SUPER YOU).

The ethics approval allows publishing analysis code. It does not allow publishing any person-level data. So this repo holds **methods only**. Data stays on the researchers' machines.

## Design

These choices were agreed in conversation on 2026-09-17/18:

1. **One repo, two layers.**
   - `src/social_energy/` is a toolkit with no knowledge of any specific study.
   - `studies/<id>/` holds study context, config and analyses.
   - The toolkit must never import from `studies/`, and a test enforces this.
   - The two layers can split into two repos later without untangling anything.
2. **Data perimeter.**
   - Data lives under `$SOCIAL_ENERGY_DATA/<study>/{raw,spine,derived}`, never inside the repo.
   - `paths.py` refuses to resolve a data root inside the working tree.
   - `scripts/check_perimeter.py` runs from the pre-commit hook and from CI. It fails on data-like file types and on files over 1 MB. The only exception is the synthetic fixtures in `tests/fixtures/`.
3. **Spine.** A validated model of people (with consent per data module), devices, device assignments over time, locations/zones, programme events and exclusion windows. It is the only place that resolves "device X at time t" to a person or a room.
4. **Canonical tables.**
   - Ingest is a set of pure functions: raw files in, polars DataFrames out.
   - Records are flagged, never silently dropped.
   - Every ingest returns a QA summary.
5. **Synthetic camp.** It generates a spine and beacon logs in the logger's exact text format, from known ground truth. All tests run against it.
6. **Stack.** Python 3.12, uv, polars, pydantic, pytest, ruff. Timestamps are timezone-aware UTC internally; the study config sets the display timezone.

## Tasks

- [x] Skeleton: `pyproject.toml`, `.gitignore`, MIT `LICENSE`, `README.md`
- [x] Agent setup: `AGENTS.md`, `CLAUDE.md`, `.agents/skills/*`, `.claude/settings.json`
- [x] Data perimeter: `scripts/check_perimeter.py` + tests + `.githooks/pre-commit` + CI job
- [x] Context docs: `docs/context/theory.md`, `docs/context/instruments/*.md`
- [x] Study: `studies/dsa-2026/{README.md,study.yaml,research/*}`
- [x] `social_energy.paths`: data-root resolution with an in-repo guard
- [x] `social_energy.spine`: models, YAML loader, validation, device→entity resolution
- [x] `social_energy.beacons`: log parser, clock resolution, beacon-ID repair, canonical tables, QA summary
- [x] `social_energy.synth`: synthetic camp → spine + logs
- [x] End-to-end test: synth → ingest → spine resolution recovers the ground truth
- [x] `social_energy.study` + CLI: `init-spine`, `ingest-beacons`
- [x] Acoustics: AudioMoth features + verified deletion (`extract-acoustics`)
- [x] `social_energy.presence`: co-presence per bin, room per bin, context around events (tested for exactness and direction; ~4M log lines ingest in ~5 s)
- [ ] Álvaro reviews; create the public GitHub repo; CI green

## Follow-ups

Tracked as their own plans: `ongoing/dsa-2026-spine.md`, `ongoing/survey-scoring.md`, and in `ideas/`: `questions-for-research-team`, `eda-shimmer-ingest`, `self-report-context-analysis`, `copresence-networks-by-phase`, `structured-field-log`, `rssi-calibration`.

Retire this plan once the repo is public and CI is green. Candidate decision to extract then: "one repo, toolkit vs study split, data perimeter enforced by hook + CI".
