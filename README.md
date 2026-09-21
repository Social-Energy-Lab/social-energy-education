# social-energy

Methods for studying **social energy** in educational settings. Following Hartmut Rosa, social energy is the collective capacity to get things done that emerges, circulates or gets blocked in interaction. The repo combines wearable proximity beacons, event self-reports, physiological sensors, ambient acoustics, surveys and interviews.

> **Methods only. Never data.**
> This repository is public. The research data, gathered from young people under an ethics approval, stays on the researchers' machines. The only data here is synthetic, generated for tests. See [AGENTS.md](AGENTS.md#invariant-1-the-data-perimeter).
>
> Everything that cannot be published — source documents, the team's working notes, anything naming or tracking a person — lives in a separate **private** repo, which is also the data root. New here? Start with [`docs/context/onboarding.md`](docs/context/onboarding.md).

## Layout

| Path | What it is |
|---|---|
| [`src/social_energy/`](src/social_energy/) | **Toolkit.** Reusable across studies. It knows nothing about any specific camp. |
| [`studies/`](studies/) | **Studies.** One folder per field phase: context, config, research questions and analyses. No data. |
| [`docs/context/`](docs/context/) | Background that agents and people should read first: theory and instruments. |
| [`docs/plans/`](docs/plans/), [`docs/decisions/`](docs/decisions/) | Work in flight and durable rationale. |
| [`tests/`](tests/) | Tests, run on a synthetic camp only. |

## Quick start

```bash
uv sync
uv run pytest                          # everything runs on synthetic data
git config core.hooksPath .githooks    # enable the data-perimeter pre-commit hook

# Point the toolkit at your local data (outside this repo):
export SOCIAL_ENERGY_DATA=~/research-data/social-energy
```

With data in place:

```bash
uv run social-energy init-spine studies/dsa-2026/study.yaml          # local spine templates
uv run social-energy ingest-beacons studies/dsa-2026/study.yaml      # logs → parquet + QA
uv run social-energy extract-acoustics studies/dsa-2026/study.yaml   # WAV → features (--delete-wavs)
uv run --extra zeitgeist social-energy fetch-zeitgeist studies/dsa-2026/study.yaml  # AI interviews + survey (needs ZEITGEIST_DATABASE_URL and local.yaml)
uv run social-energy ingest-survey studies/dsa-2026/study.yaml       # survey export → parquet + QA
```

Expected local data layout (never committed). The full layout, the import rules and how to hand data to another researcher are in [`docs/context/data-layout.md`](docs/context/data-layout.md):

```
$SOCIAL_ENERGY_DATA/            the data root, and the private repo
  _team/      notes across studies; the perimeter denylist
  <study-id>/
    local.yaml  private per-study config (platform identifiers)
    context/    source documents as markdown; personal/ for anything naming a person
    notes/      our findings about this study's records
    raw/        instrument data exactly as delivered, per instrument and device, with IMPORT.md + SHA256SUMS
    spine/      who wore what when, consent, locations, events, exclusions (IDs only)
    derived/    canonical tables produced by the toolkit
```

## Licence

MIT. See [LICENSE](LICENSE).
