# One validated schema for study.yaml and local.yaml

**Priority:** medium — every instrument feature edits the hand-written mapper in `study.py`, and a misspelt key in either file is silently ignored, including the one that makes the ingest refuse a purged device
**Gate:** decision:may `study.yaml` and `local.yaml` refuse keys the schema does not know, as the spine and the survey codebook already do?

**Goal:** `StudyConfig.load` validates `study.yaml` and `local.yaml` against one pydantic schema, so a new knob is declared once, its default lives in one place, and a misspelt or misplaced key is an error at load instead of a silent default.

## Context

As of `6dad9b6` (2026-11-21), 90-day window (243 commits).

- **The mapper is hand-written, key by key.** `StudyConfig.beacon_config` and `StudyConfig.eda_config` in `src/social_energy/study.py` copy each YAML key into `BeaconConfig` / `EdaConfig` / `ClockConfig` with `section.get("<key>", <default>)`. A knob is therefore written three times: the field in the ingest dataclass, the line in the mapper, the key in `studies/<id>/study.yaml`. `study.py` has 12 commits; all but the first and one fix are feature commits adding config for an instrument or a view (`2f3dc9b` feat(beacons): fit boots in the main ingest, and date past a clock step; `49b14ac` feat(eda): correct Shimmer clocks from the cards' sync records; `22fcf19` Beacons: own ID repair from witnesses, processing-guide fixes, measured drift (#1)). `04beac5` fix(beacons): repair the logger ID bug against power cycles; trust hand-split logs touched `beacons/ingest.py`, `study.py` and `study.yaml` together for one new knob (`ids_split_in`). Co-change in the window: `study.yaml` with `study.py` 7, `cli.py` with `study.py` 8.
- **Defaults are written twice.** `BeaconConfig` (`src/social_energy/beacons/ingest.py`) and `beacon_config` both carry `anchor_tolerance_s` 300, `restart_margin_s` 3600, `readout_gap_s` 60, `witness_tolerance_s` 300, `witness_min_votes` 5, `witness_min_share` 0.9, `witness_peak_s` 10, `witness_min_peak_ratio` 3.0, `clock_rate_ppm` 0.0; `EdaConfig.rotation_s` 3600 and `ClockConfig.reference_to_utc_s` 0.0 likewise. They agree today; nothing keeps them agreeing.
- **A wrong key is silent.** `StudyConfig.raw` is `dict[str, Any]`. A misspelt knob (`witness_min_vote: 3`) loads and the ingest runs on the default. The same holds for the private `local.yaml`, read by `StudyConfig.local`: a misspelt `beacons.purged_devices` yields an empty tuple, and the refusal added in `cd78ab0` feat(beacons): refuse raw logs that name a purged device never fires. Only one sub-section is strict today, by accident: `BoxConfig(**(clock.get("box") or {}))` raises `TypeError` on an unknown key.
- **Readers reach into the dict.** `.raw` is read 6 times in `study.py`, once in `cli.py` (`extract_acoustics`, for `acoustics.filename_timezone`), and 7 times under `studies/dsa-2026/analyses/` (`copresence_by_phase.py` twice, `site_export.py` twice, `explorer_export.py`, `acoustics_presses.py`, `exploratory_mixing_outside_class.py`). `copresence_by_phase.py` re-reads `beacons.observation_window` from the dict although `StudyConfig.beacon_window` already parses it. `explorer.deploy.target` takes `study.local` as a bare dict.
- **The repo already chose this shape elsewhere.** `spine/models.py` (`_Model`) and `survey/codebook.py` (`_Strict`) are pydantic with `extra="forbid"`, and `docs/decisions/person-attributes-in-the-spine.md` gives the reason: "Typed fields rather than a free mapping, so a misspelt key fails loudly at load". `study.py` is the one config reader left on plain dicts. Two more field phases (START-Stiftung, SUPER YOU) will each bring a hand-written `study.yaml`, most likely started as a copy of this one.
- **The privacy rule to keep.** `StudyConfig.load` refuses `survey.zeitgeist.study_id_item`, `ai_interviews.zeitgeist.agents` and `beacons.purged_devices` in the public file with a message pointing to `local.yaml`. The first two come from the `PRIVATE_KEYS` tuple (tested in `tests/test_local_config.py`); `purged_devices` is a separate check beside it (tested in `tests/test_beacon_purge.py`, `test_public_study_yaml_may_not_list_purged_devices`). See `docs/decisions/public-private-repo-pair.md`.

Dependency category: in-process (YAML text in, frozen config objects out; no I/O beyond reading two files).

## Design

Schema models for the two files live in `src/social_energy/study.py` (or a `study_schema.py` beside it if it grows past comfort); the ingest dataclasses stay as they are.

- **`StudyFile`** (public) and **`LocalFile`** (private): pydantic, frozen, `extra="forbid"`, one model per section — `dates`, `beacons`, `eda` (with `clock`, `clock.box`), `acoustics`, `survey`, `course_hours`, `explorer`; and for `local.yaml`: `survey`, `ai_interviews`, `beacons`, `explorer.deploy`. Every section is optional, so the two-line `study.yaml` the tests write still loads.
- **Knobs are declared once, without a default.** A knob field in the schema is `<type> | None = None`; the builder passes only the keys the file sets, so the default stays in the ingest dataclass and nowhere else. Illustrative, not final:

  ```python
  def beacon_config(self) -> BeaconConfig:
      knobs = self.file.beacons.model_dump(exclude_unset=True, include=BEACON_KNOBS)
      return BeaconConfig(timezone=self.timezone, purged_devices=self.purged_devices(), **knobs)
  ```

  The few keys whose YAML shape differs from the config's stay explicit and typed in the section model: `eda.clock.comotion_windows` (`"YYYY-MM-DD HH:MM-HH:MM"` → epoch pairs), `eda.export_starts`, `beacons.observation_window` (local → UTC).
- **Record keys are declared too.** `study.yaml` is also the record of the field phase (`beacons.settings_changes`, `logger_incidents`, `self_report`, `scan`, `eco_scan`, `firmware_commit`, `acoustics.devices`, `incidents`, …). Each gets a field, loosely typed where it is prose. A new kind of fact then costs one schema line; that is the price of catching a misplaced key.
- **The private-key refusal runs first**, before validation, with today's message, so a leftover platform identifier in the public file is still told to move to `local.yaml` rather than reported as "extra field". `PRIVATE_KEYS`, the separate `purged_devices` check and their tests (`tests/test_local_config.py`, `tests/test_beacon_purge.py`) stay.
- **Readers migrate to attributes.** `study.file.beacons.rssi_threshold_dbm.person_tag`, `study.file.course_hours`, `study.file.acoustics.devices`, `study.file.dates.arrival`; `copresence_by_phase.py` uses `beacon_window`'s source instead of the dict; `extract_acoustics` gets `study.acoustics_config()`; `deploy.target` takes the typed `explorer.deploy` section. `StudyConfig.raw` is then removed, so there is no second way in.
- **Errors name the file and the key.** A `ValidationError` is re-raised as `ValueError("<path>: beacons.witness_min_vote: unknown key")`, the way `Spine.load` wraps one in a `SpineError` naming the file. (`Spine.load` also prints the offending entry; this one must not, see next sentence.) For `local.yaml` the message names the key only, never the value: it holds private identifiers and error text ends up in terminals and logs.

Same accepted `studies/dsa-2026/study.yaml`, same resulting `BeaconConfig` / `EdaConfig` / `ExplorerConfig` values. The one observable change is the Gate question: a file with an unknown key stops loading. Before the build turns that on, list the keys (keys only, no values) of the real `$SOCIAL_ENERGY_DATA/dsa-2026/local.yaml` and declare each, so the first run on a researcher's machine does not fail.

PR #29 only adds `package_command` and its dispatch to `cli.py`; this plan changes two lines in `extract_acoustics` and the two `deploy.target` calls. Build after it merges, or rebase over it; the overlap is too small to gate on.

No other plan builds first. `new-study-scaffold` (same pass) builds after this one if both are approved: its template is then validated by this schema.

**Alternatives considered:**
- **A, generic pass-through without pydantic** (`{k: section[k] for k in fields(BeaconConfig) if k in section}` plus a known-keys list): removes the duplicated defaults in fewer lines, but validates no types and leaves the `.raw` readers in the studies untyped.
- **C, make `BeaconConfig` / `EdaConfig` themselves the pydantic schema:** truly one edit per knob, but those configs also carry fields no file sets (`id_overrides`, `id_fallback`, `period_overrides`, `clock_steps`), `beacons/sync.py` and `sensitivity_ingests.py` build variants with `dataclasses.replace`, and it ties instrument modules to one file format.
- **Schema with `extra="ignore"`:** types the readers but keeps the silent-typo failure, which is the main thing worth fixing.

**Testing strategy:** tests at the load boundary, in `tests/test_study_config_and_cli.py` and `tests/test_local_config.py`:
- a golden test that the real `studies/dsa-2026/study.yaml` produces `BeaconConfig`, `EdaConfig` and `ExplorerConfig` equal, field for field, to the ones today's mapper produces (written first, against today's code, then kept as the refactor's proof);
- a default-agreement test: a `study.yaml` with only the required beacon and EDA keys yields configs equal to `BeaconConfig(...)` / `EdaConfig(...)` built with the same required arguments;
- an unknown key in a knob section, in a record section and in `local.yaml` each raises with the file path and dotted key; mutation: remove `extra="forbid"` and the test must fail;
- the existing private-identifier and purged-device refusal tests unchanged.
`test_dsa_study_config_builds_beacon_config` and `test_explorer_config_defaults_when_section_missing` are subsumed by the golden and default tests and are replaced, not kept beside them.

## Paths

As of 2026-11-21:

- `src/social_energy/study.py`
- `src/social_energy/study_schema.py` (new, only if `study.py` grows too long)
- `src/social_energy/cli.py` (`extract_acoustics`, `deploy_explorer`, `explorer_user`; open PR #29 edits this file: rebase over it)
- `src/social_energy/explorer/deploy.py` (`target`)
- `studies/dsa-2026/analyses/copresence_by_phase.py`
- `studies/dsa-2026/analyses/site_export.py`
- `studies/dsa-2026/analyses/explorer_export.py`
- `studies/dsa-2026/analyses/acoustics_presses.py`
- `studies/dsa-2026/analyses/exploratory_mixing_outside_class.py`
- `tests/test_study_config_and_cli.py`
- `tests/test_local_config.py`
- `tests/test_explorer_deploy.py` (calls `deploy.target` with a bare dict four times; follows the new signature)
- other tests that write a synthetic `study.yaml` or `local.yaml`, where a key needs declaring (`tests/test_eda_cli.py`, `tests/test_beacon_purge.py`, `tests/test_explorer_server.py`, `tests/test_survey.py`, `tests/test_survey_scoring.py`, `tests/test_zeitgeist.py`, `tests/test_acoustics.py`, `tests/test_site_build.py`, `tests/test_site_deck.py`)
- `docs/context/data-layout.md` or `docs/context/onboarding.md` (one line: both files are validated; an unknown key is an error)
- `.agents/skills/add-data-source/SKILL.md` (where a new knob is declared)

`studies/dsa-2026/study.yaml`, `src/social_energy/beacons/ingest.py` and `src/social_energy/eda/ingest.py` are not edited.

## Approval

**Needs your yes** — the `Gate` question: may `study.yaml` and `local.yaml` refuse keys the schema does not know? Recommended answer: yes, because a misspelt knob or a misspelt `purged_devices` is today a silent default, and the spine and the codebook already fail loudly for the same reason. The repo's `AGENTS.md` has no `## Approval` section, so nothing here is pre-approved.

## Out of scope

- Changing any knob's value, default or meaning, or any key in `studies/dsa-2026/study.yaml`.
- Turning the ingest configs (`BeaconConfig`, `EdaConfig`, `ClockConfig`, `BoxConfig`) into pydantic models.
- Validating `locations.yaml`, `survey_codebook.yaml` (already strict) or `package.yaml` (PR #29).
- Checking config values against the data (a `valid_from` after `valid_to`, an ID range that matches no tag): a separate, behaviour-changing idea.
- Splitting `cli.py`; its churn is mostly new commands, not config plumbing.
