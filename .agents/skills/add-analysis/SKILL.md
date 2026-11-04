---
name: add-analysis
description: "Use when writing an analysis for a study under studies/<id>/analyses/ — e.g. context around self-report presses, co-presence networks per programme phase, EDA responses — or when promoting a reusable piece of an analysis into the toolkit."
---

# Add an analysis

Analyses answer research questions. They live with their study; the reusable parts move into the toolkit.

## Before writing code

1. Name the research question it serves (`studies/<id>/research/questions.md`) and the construct it operationalises (`research/constructs.md`). If the mapping from Rosa's concept to the measure is your own idea, mark it `[inferred]`. The research team signs off on constructs, not the agent.
2. State the unit of analysis (person, dyad, group, location, time window) and the filters: `ok` flags, exclusion windows, consent module. Write them at the top of the script.

## Shape

- `studies/<id>/analyses/<slug>.py` (or a notebook with outputs cleared). It reads only via `social_energy.paths.study("<id>")` and writes results to `$SOCIAL_ENERGY_DATA/<id>/derived/analyses/<slug>/`, never into the repo.
- Always resolve through the spine: `resolve` → `flag_excluded` → filter on `spine.consented(<module>)`.
- Develop and test against `social_energy.synth` first. The analysis must run end to end on synthetic data in CI, even though its conclusions only mean something on real data.
- If a function would be useful for another study, move it into `src/social_energy/` with its own tests. Study code should mostly be configuration and orchestration.

## Caches

A table cached from the contacts is reused only under `copresence_by_phase.cache_is_current`, so that a new ingest or spine rebuilds it. A cache that only checks its file exists mixes old data into a rerun without a sound.

## Around self-reports

- Compare with shuffled presses in the same clock hour as well as the same phase of day. A phase-of-day null alone shows the timetable as a result.
- Say what the clock-hour null costs: shuffled presses land in the same hour and read a real effect lasting about that long, so its estimates are not effect sizes.
- A split-half verdict is too strict for a rare event, such as a later outcome of shared moments. Plant an effect of known size to see what the rule can catch, and read the all-days interval when the split is underpowered.

## Reporting

- Only aggregate results leave the local machine. Groups too small to protect anonymity are merged or suppressed (the ethics approval requires this).
- Figures and tables go to `derived/`. If one is ever committed (e.g. for a paper), it must be aggregate, and the commit message says so.
- Record surprising, method-shaping findings as a `docs/decisions/` entry, not as numbers in the repo.
