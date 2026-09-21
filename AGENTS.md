# AGENTS.md

The authoritative guide for anyone, human or AI, working in this repo. It is short, opinionated and load-bearing. When this file disagrees with the code, this file wins: fix the code.

## What this repo is

Methods for studying **social energy** in educational settings. This is Mahdi Srour's PhD in Hartmut Rosa's group (FSU Jena and the Max Planck Institute of Geoanthropology). Field phases are residential programmes for young people. The first was the Deutsche SchülerAkademie 2026 in Schwäbisch Gmünd; START-Stiftung and SUPER YOU are planned. Each phase combines:

- wearable BLE proximity **beacons**, with a self-report button;
- **EDA/heart-rate** wearables;
- ambient **acoustics**;
- a structured **survey**;
- **interviews**;
- field **observations**.

The repo holds **methods only**. It is public. The data describes minors and stays on the researchers' machines.

## Read first

1. [`docs/context/project.md`](docs/context/project.md): the PhD project, including hypotheses, research questions, design, data modules and the ethics constraints that bind this repo.
2. [`docs/context/theory.md`](docs/context/theory.md): what "social energy" means here, which measures are candidates for it, and the open tensions.
3. [`docs/context/data-layout.md`](docs/context/data-layout.md): how data is organised on a researcher's machine and how to import or hand it over.
4. [`docs/context/instruments/`](docs/context/instruments/): one file per data source. Covers its format, how it was collected, and its known traps.
5. The study you are working on: [`studies/<id>/README.md`](studies/).
6. [`docs/context/onboarding.md`](docs/context/onboarding.md): setting up a machine, and publishing this repo.
7. [`docs/plans/ongoing/`](docs/plans/ongoing/): what is in flight. Read the Status section first. Then `ready/` and `ideas/`.

## The private half

This repo is one of a pair. The other half is a **private repo** at `$SOCIAL_ENERGY_DATA`, which is also the data root. It holds the source documents, the team's own notes, and the private per-study config — everything that cannot be published. Its `README.md` explains the tiers; each study's `context/README.md` indexes its documents with a sensitivity label (P/U/I/R).

```
$SOCIAL_ENERGY_DATA/         private repo + data root
  _team/                     theory-notes.md · questions.md · perimeter-denylist.txt
  <study-id>/
    context/sources/         source documents (U/I/R): drafts, slides, survey versions, ethics
    context/personal/        field logs and anything naming or tracking people (P) — never in any repo
    notes/                   our findings about this study's records (I)
    local.yaml               private per-study config (platform identifiers)
    spine/ raw/ derived/     data — never in any repo
```

- Read it when a task needs detail the public docs don't have: exact times from a field log, the wording of a survey item, what a slide proposed.
- **Write there by default.** If you are unsure whether something may be published, it goes in the private half. Moving a note from private to public later is easy; a public git history cannot be recalled.
- **Never copy from it into this repo.** Distil in your own words, strip names, never quote unpublished texts. Facts about a person go only into the local spine.
- What belongs *here*: methods, instrument behaviour, formats, non-personal study config, and the **rule** a finding produced ("keep the most complete submission per study ID"). What stays *there*: the finding itself, counts from the real data, anything about a person, and any reconstruction of unpublished work.
- If the environment variable is not set, ask the human where the library is. Don't search the disk for it.

## Invariant 1: the data perimeter

**No research data ever enters this repository.** Not raw, not derived, not "just a sample", not in a notebook output, not in a commit message or plan.

- Data lives under `$SOCIAL_ENERGY_DATA/<study-id>/{context,raw,spine,derived}`, organised as in [`docs/context/data-layout.md`](docs/context/data-layout.md). `social_energy.paths` refuses a data root inside the repo.
- `scripts/check_perimeter.py` runs as a pre-commit hook (`git config core.hooksPath .githooks`) and in CI. It rejects data-like file types, `data/` directories, notebooks with outputs, and files over 1 MB. **Never bypass it** (`--no-verify`). If it blocks something legitimate, change the check in a reviewed commit.
- When `$SOCIAL_ENERGY_DATA` is set, the same check also refuses any file containing a string from `_team/perimeter-denylist.txt`: names, private platform identifiers, phrases from unpublished work. The list stays in the private repo, which is how names are checked for without being published. CI has no data root, so it runs the file-type half only — the denylist protects the commit, not the pull request.
- Identifiers of a private deployment (which interview agent, which platform question) live in `$SOCIAL_ENERGY_DATA/<study-id>/local.yaml`, read by `StudyConfig.local`. `study.yaml` refuses them.
- The only data allowed in the repo is **synthetic**, generated by `social_energy.synth` or written by hand in `tests/fixtures/`.
- Never write real names, initials, study-ID ↔ person mappings, quotes from participants, survey free text, or details that could identify a person into code, docs, tests, plans or commit messages. Refer to people by study ID only where needed, and prefer not at all.
- Unpublished texts shared with the team (for example Rosa's manuscripts) are summarised in our own words, never quoted or committed.
- **Git history is permanent and this repo is public.** Treat every commit as publication.

Use the [`data-perimeter`](.agents/skills/data-perimeter/SKILL.md) skill whenever you touch ingest code, fixtures, notebooks or docs about a study.

## Invariant 2: toolkit vs study

| | `src/social_energy/` (toolkit) | `studies/<id>/` (study) |
|---|---|---|
| Knows about | instruments, formats, methods | one field phase: dates, rooms, programme, questions |
| May import | its own modules, libraries | the toolkit |
| Contains | functions, models, synthetic generators | config (`study.yaml`), context docs, research questions, analyses |

The toolkit **never** imports from `studies/` and never hard-codes a study's dates, IDs, rooms or cutoffs. They are passed in as config. `tests/test_architecture.py` enforces this. A fact true of one camp goes in that camp's `study.yaml`. A fact true of an instrument (a firmware behaviour, an export format) goes in `docs/context/instruments/`.

## Invariant 3: flag, don't drop

Ingest functions are pure: raw files in, canonical `polars` tables out. Suspicious records get boolean flags (`duplicate`, `implausible_time`, `pre_reboot`, …) plus an `ok` summary column, and every ingest returns a QA dict that accounts for every input line. Filtering is the analyst's explicit, visible choice.

## Invariant 4: the spine resolves identity

Raw tables speak in device IDs (`beacon:7`, `eda:SH07`). Only the **spine** (`social_energy.spine`) turns "device X at time t" into `person:<id>` or `location:<id>`. The spine covers people with consent per module, locations and zones, device assignments over time, programme events and exclusion windows. It lives locally under `$SOCIAL_ENERGY_DATA/<study>/spine/` as YAML. The repo ships its schema and synthetic examples only. Analyses must respect **consent per module** (`spine.consented("eda")`) and **exclusion windows** (`spine.flag_excluded`).

## Layout

```
src/social_energy/   paths · study · cli · presence · zeitgeist · spine/ · beacons/ · acoustics/ · survey/ · synth/  (next: eda/)
studies/<id>/        README.md · study.yaml · research/ · analyses/
docs/context/        theory.md · instruments/*.md
docs/plans/          ideas/ → ready/ → ongoing/   (managing-plans-lifecycle skill)
docs/decisions/      durable rationale (ADR-lite)
tests/               synthetic data only; fixtures/ is the one data-format exception
scripts/             check_perimeter.py
```

## Working rules

- **Stack:** Python 3.12, `uv`, `polars`, `pydantic`, `pytest`, `ruff` (line length 100). Datetimes are timezone-aware UTC internally. Naive wall-clock times in spine files and logs are interpreted in the study's timezone.
- **Tests before code** for anything that parses or transforms data. The pattern is a hand-written golden fixture with hand-derived expectations, plus an oracle test against `social_energy.synth`. A test that passes on first run gets a deliberate mutation to prove it can fail.
- **Before claiming done:** `uv run ruff check . && uv run ruff format --check . && uv run pytest`.
- **Uncertainty markers,** used literally so they stay greppable: `[inferred]` means derived from documents but not confirmed by the research team. `[unknown: <question>]` means not determinable, and the text is the question to ask. Never silently drop one.
- **Commits:** Conventional Commits (`feat(beacons): …`, `docs(context): …`, `test: …`). Commit small.
- **Plans:** follow [`managing-plans-lifecycle`](https://github.com/alvaro-francisco-gil/agent-plans), installed as a plugin. Brainstorming and planning output goes in `docs/plans/ideas/` without date prefixes. There is no `docs/superpowers/`. A priority label is required. There is no `soak/`, `incidents/` or `ops/`.

## Skills

| Skill | Use when |
|---|---|
| [`data-perimeter`](.agents/skills/data-perimeter/SKILL.md) | touching anything near real data, fixtures, notebooks, study docs |
| [`add-data-source`](.agents/skills/add-data-source/SKILL.md) | adding an ingest for a new instrument or export format |
| [`add-analysis`](.agents/skills/add-analysis/SKILL.md) | writing an analysis under `studies/<id>/analyses/` |
| [`managing-plans-lifecycle`](https://github.com/alvaro-francisco-gil/agent-plans) | creating, promoting or retiring plans |

## Repo health beats every rule above

If a rule here makes the repo worse for a specific change, break the rule and update this file in the same commit. **Invariant 1 is the exception.** It is an ethics obligation, not a convention.
