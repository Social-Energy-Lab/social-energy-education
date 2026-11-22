# A `new-study` command, and a second synthetic study that is not shaped like DSA 2026

**Priority:** medium — two more field phases are planned and the repo has only ever held one study; no date presses, since the phases' dates are still an open `[unknown: ...]` in `next-phase-preregistration.md`
**Gate:** decision:add a `new-study` command and a second, differently shaped synthetic study to the test suite now, before the dates of START-Stiftung and SUPER YOU are known?

**Goal:** `social-energy new-study` creates a complete, loadable study folder with every unfilled fact marked `[unknown: ...]`, and one test runs that scaffold through the CLI on a synthetic camp that differs from DSA 2026 in every setting it can, so what the toolkit still assumes about DSA 2026 shows up as a failing test now and not in the week a new phase's data arrive.

## Context

As of `6dad9b6` (2026-11-21).

- **One study, ever.** `studies/` holds `dsa-2026` only. `docs/context/project.md` lists SUPER YOU and START-Stiftung as planned contrast settings (RQ4). `docs/plans/ideas/next-phase-preregistration.md` already assumes their folders exist: its `Next` copies the agreed plan "into each phase's `studies/<id>/research/analysis-plan.md`", with settings "filled in from its `study.yaml`". Nothing in the repo creates that folder.
- **No command makes a study.** `src/social_energy/cli.py` has `init_spine`, which fills the *private* spine from an existing `study.yaml`. The public half (`study.yaml`, `locations.yaml`, `README.md`, `research/`, `analyses/`) was written by hand for DSA 2026, and the private skeleton is a `mkdir -p` line (followed by `chmod -R go-rwx`) in `docs/context/data-layout.md` (step 3 of the setup list). `main` in `cli.py` calls `StudyConfig.load(args.study_yaml)` before it dispatches any command, so every command needs a study that already exists.
- **The tests do not prove study-independence beyond a DSA-shaped camp.**
  - `tests/test_architecture.py` checks two things: the toolkit imports nothing from `studies`, and no toolkit file contains the strings `dsa-2026` or `schwäbisch`. It cannot see an assumption that is not one of those two strings.
  - `tests/test_synthetic_camp_end_to_end.py` builds `BeaconConfig` by hand from `CampSpec()` and calls `ingest_logs` directly. It never goes through `study.yaml`, `StudyConfig` or the CLI.
  - `tests/test_studies.py` checks that each folder under `studies/` has a README and a `study.yaml` whose `study_id` matches, that `locations.yaml` rows have the five expected keys, and that no person-level key appears.
  - The CLI tests that do use a synthetic study each write their own minimal `study.yaml` by hand: `_study_yaml` in `tests/test_study_config_and_cli.py`, another in `tests/test_eda_cli.py`, `_study_yaml` in `tests/test_zeitgeist.py`, `_study` in `tests/test_beacon_purge.py` and in `tests/test_survey_scoring.py`, and inline ones in `tests/test_survey.py`, `tests/test_acoustics.py` and `tests/test_local_config.py`. The one in `test_study_config_and_cli.py` does run `init-spine` and `ingest-beacons` through the CLI, but on the default `CampSpec()`, so on a DSA-shaped camp. Eight files with hand-kept copies of "what a minimal study looks like", none of them the file a researcher would start from.
  - `CampSpec` in `src/social_energy/synth/camp.py` defaults to `start = 2026-08-14 08:00`, `timezone = "Europe/Berlin"`, `people = 44..55`, room tags `114..116`, 12 hours, with the logger ID bug on. That is a day inside DSA 2026's dates, its timezone, IDs inside its ranges (114..116 are real DSA location tags) and its firmware fault. The two variants in the toolkit change the length, the people and the faults, and keep the date: `_synthetic_spec` in `src/social_energy/site/build.py` also keeps the timezone (and moves the room tags to 201..203); `demo_bundle` in `src/social_energy/explorer/synthetic.py` takes the timezone of the study it is called for, which today is always DSA 2026's.
- **Assumptions already visible by reading, which a second study would hit** (candidates, each to be confirmed by the test, not fixed by this plan):
  - `StudyConfig.beacon_config` reads `self.raw["beacons"]` and `eda_config` reads `self.raw["eda"]` in `src/social_energy/study.py`: a study that has not yet filled in beacon dates, or runs no EDA module, gets a bare `KeyError` or a `ValueError` from `date.fromisoformat`.
  - `Role` in `src/social_energy/spine/models.py` is `participant`, `course_leader`, `academy_leader`, `musician`, `researcher`, `guest`, and `Person` carries a `course` field, with `extra="forbid"`. These are the academy's words. The preregistration draft deliberately speaks of "the phase's main group" (a course, a class or a workshop group) because the next phases are organised differently.
  - 31 of the 32 scripts in `studies/dsa-2026/analyses/` contain the string `dsa-2026` (for example `STUDY = "dsa-2026"` in `confirmatory.py`). The preregistration says the exploratory analyses are "run with the same code" at the next phases; today that code is addressed to one study. A shared harness for the analysis scripts was looked at in the same pass and not filed; this plan only makes the assumption visible.
- **Study facts and toolkit code still move together.** In the 90-day window (243 commits) `studies/dsa-2026/study.yaml` changed in the same commits as `src/social_energy/study.py` (7), `src/social_energy/beacons/ingest.py` (4), `src/social_energy/acoustics/features.py` (2) and `src/social_energy/synth/camp.py` (2).
- **Nothing in the backlog covers it.** `next-field-phase-beacon-practice.md` is a checklist for the beacon team, `next-phase-preregistration.md` the analysis plan, `structured-field-log.md` a name-free field log that imports into the spine. All three start after the study exists in the repo. No decision in `docs/decisions/` speaks to it. Open PR #29 (`feat/data-package`, open and conflicting since 2026-10-29) adds a `package` command to `cli.py`; this plan adds its own command beside it, a few lines of overlap, so it rebases over that PR and is not gated on it.

## Design

Two parts that land together: the scaffold is what the second synthetic study is made with, so the test exercises the file a researcher will really start from.

**1. The template, kept in the toolkit.** A folder of template files shipped with the package, `src/social_energy/templates/study/`:

- `study.yaml` — `study_id` and `timezone` filled from the command's arguments; every other fact present as a key with a `[unknown: <question>]` comment (arrival and departure, beacon plausibility window, observation window, ID ranges, which modules run). Modules the phase may not run (EDA, acoustics, survey) are commented-out sections, not empty ones.
- `locations.yaml` — the header comment explaining the five columns and the `kind` values, no rows.
- `README.md` — the headings of `studies/dsa-2026/README.md` (setting, programme rhythm, data modules, consent, the button instruction), each body a `[unknown: ...]`, with the "no data, no names" line at the top.
- `research/questions.md`, `research/constructs.md`, `research/analysis-plan.md` — headings only, pointing at `docs/context/theory.md` and at the shared preregistration draft.
- `analyses/` — empty, with a one-line pointer to the `add-analysis` skill.

The template holds no fact about any real phase, so it is toolkit, not record: it says what a study must state, which is a fact about the toolkit.

**2. The command.** Illustrative:

```
social-energy new-study studies/<id>/study.yaml --timezone Europe/Berlin
```

It keeps the CLI's two positionals (the command, then the path to `study.yaml`; the command name joins the parser's `choices`), is dispatched in `main` before `StudyConfig.load`, and:

- refuses if `studies/<id>/` already exists (same rule as `init-spine`: never overwrite work), and refuses an id that is not kebab-case;
- writes the public folder from the template;
- when `$SOCIAL_ENERGY_DATA` is set, also creates the private skeleton that `data-layout.md` now describes by hand (`context/sources`, `context/personal`, `notes`, `raw`, `spine`, `derived`) and a commented `local.yaml` stub, with the same owner-only permissions the hand step sets (`chmod -R go-rwx`), never touching anything that exists; when it is not set, it says so and writes the public half only;
- prints the next steps in plain words: fill in the unknowns, run `init-spine`, list the markers with `scripts/record-check.py --list`.

The logic lives in a small module (`scaffold.py`: `new_study(study_dir, study_id, timezone, data_root=None)`), with `cli.py` only parsing and calling it, so tests call the function directly.

**3. The second synthetic study.** One new end-to-end test builds a camp that is unlike DSA 2026 wherever `CampSpec` allows: another year and season, a timezone that is not Europe/Berlin and is far enough from UTC that the local day and the UTC day disagree, several days, person and room tag numbers outside DSA's ranges, the logger ID bug off, no EDA section. It then runs the researcher's path: `new_study` into `tmp_path` → fill the unknowns from the spec → `StudyConfig.load` → `init-spine` → `ingest-beacons` → the spine resolves the contacts → the true contacts come back (the oracle `tests/test_synthetic_camp_end_to_end.py` already uses), then the toolkit's outcome tables on top.

What fails is the deliverable. Each failure is either fixed in the same PR when it is a few lines and changes nothing for DSA 2026, or written down as an `xfail` with its reason and a line in this plan. Vocabulary questions (`Role`, `Person.course`) are not decided here: the test records them and the question goes to `questions-for-research-team.md`.

**4. A stronger study check.** `tests/test_studies.py` gains "every `studies/*/study.yaml` loads through `StudyConfig.load`", and "the template loads once its unknowns are filled", so the template cannot drift from what the toolkit reads.

**Order.** `typed-study-config` (an idea filed in the same pass) builds first if it is approved: the template is then validated by that schema, and a missing section is a clear error, not a `KeyError`. This plan does not depend on it. Nothing else builds first; the second synthetic study would also give any later shared analysis harness a second caller to test against.

**Alternatives considered:**

- *A committed `studies/synthetic-camp/` (or `studies/_template/`) as the second study.* Lost: `AGENTS.md` makes `studies/<id>/` the record of real field phases, and a made-up study there would sit beside real ones in every listing, in `test_studies.py` and in the record check. A template inside the package plus a study built in `tmp_path` gives the same proof without a fake record.
- *A skill (`add-study`) with no command.* Lost: a procedure a person follows is not something a test can run, and the point is the test. A short skill or an onboarding section that says "run `new-study`, then fill these in" is still written (see Paths).
- *Wait until a phase has dates.* Lost: the scaffold needs no date, the preregistration draft already refers to the folders, and finding a toolkit assumption costs least while no real data depend on the answer.
- *Only widen `test_architecture.py`'s list of forbidden strings.* Lost: it catches spellings, not shapes (a required section, a role name, a timezone).

**Testing strategy:** tests at the new boundary are `new_study` (writes the expected tree; refuses an existing folder and a bad id; public half only without a data root; never overwrites the private side) and the second-study end-to-end run above. They replace, not add to, the hand-written minimal `study.yaml` builders in `tests/test_study_config_and_cli.py`, `tests/test_eda_cli.py`, `tests/test_zeitgeist.py`, `tests/test_beacon_purge.py`, `tests/test_survey_scoring.py`, `tests/test_survey.py`, `tests/test_acoustics.py` and `tests/test_local_config.py`: those tests call the scaffold and set the two or three keys they care about. As the repo's rule asks, the new end-to-end test gets a deliberate mutation (for example, a hard-coded timezone) to prove it can fail.

## Paths

As of 2026-11-21.

- `src/social_energy/scaffold.py` (new)
- `src/social_energy/templates/study/` (new: `study.yaml`, `locations.yaml`, `README.md`, `research/*.md`, `analyses/README.md`)
- `src/social_energy/cli.py` (the command, its help text, dispatch before `StudyConfig.load`; open PR #29 edits this file: rebase over it)
- `pyproject.toml` (only if the wheel needs the template files named; `packages = ["src/social_energy"]` is expected to carry them, as it carries `site/static/`)
- `src/social_energy/synth/camp.py` (only if `CampSpec` cannot express the second camp)
- `tests/test_scaffold.py` (new)
- `tests/test_second_study_end_to_end.py` (new)
- `tests/test_studies.py`
- `tests/test_study_config_and_cli.py`, `tests/test_eda_cli.py`, `tests/test_zeitgeist.py`, `tests/test_beacon_purge.py`, `tests/test_survey_scoring.py`, `tests/test_survey.py`, `tests/test_acoustics.py`, `tests/test_local_config.py` (their hand-written study files replaced by the scaffold)
- `docs/context/onboarding.md`, `docs/context/data-layout.md` (the `mkdir -p` step becomes "run `new-study`"), `README.md` (command list)
- `AGENTS.md` (one line under "Read first" or "Layout": a new study starts with `new-study`)
- `docs/plans/ideas/questions-for-research-team.md` (only if the run raises a vocabulary question)

## Approval

**Needs your yes** — the `Gate` question; recommended answer: yes, because it needs no date or decision from the research team, the preregistration draft already points at folders that do not exist, and the test is the cheapest way to learn what a second phase would break. `AGENTS.md` has no `## Approval` section, so nothing here is pre-approved.

## Out of scope

- Creating `studies/start-stiftung-*` or `studies/super-you-*`: their ids, dates and programmes are unknown, and a study folder is created on the research team's word.
- Renaming `Role` members or `Person.course`, or any change to the spine's schema: recorded as a question, decided elsewhere.
- Making the DSA analysis scripts run for another study (a shared analysis harness; looked at in the same pass, not filed).
- Validating `study.yaml` against a schema (`typed-study-config`).
- The structured field log, the beacon checklist and the preregistration itself.
- Anything in the private repo beyond empty folders and a commented `local.yaml` stub.
