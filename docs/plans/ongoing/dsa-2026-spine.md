# DSA 2026 spine: transcribe the field logs into the local spine

**Priority:** high

**Goal:** a validated local spine for DSA 2026 (`$SOCIAL_ENERGY_DATA/dsa-2026/spine/`), so that every sensor record resolves to a person or location and the known bad windows are excluded.

## Status

- **Updated:** 2026-09-22
- **Priority:** high
- **Stage:** roster pass and the zeitgeist linking done; the field-log transcription (exclusions in detail, events, EDA sessions) is next
- **Branch:** `main` (local only, no remote yet)
- **Done:** the roster arrived on 2026-09-21 and is converted into the private library (**P**, `context/personal/`). `init-spine` seeded meta, 67 locations and their tag assignments. `people.yaml` holds every participant and staff member with consent per module, `assignments.yaml` the person tags including the five documented replacements and the location tags that arrived late, failed or moved, `exclusions.yaml` the windows the roster documents. `Spine.load()` validates. Every beacon ID in the delivered contact tables was checked against the spine: all resolve except seven, listed in `spine/open_questions.md`
- **Next:** transcribe the rest of the beacon field log (battery changes, tags taken off, the further broken tags) and build `events.yaml` from the programme
- **Blockers:** the EDA distribution plan (that module is wholly unattributable without it), and the in-person interview log's ambiguous times. The consent conflict on the platform modules was settled on 2026-09-22 — see Design. All open items are in `$SOCIAL_ENERGY_DATA/dsa-2026/spine/open_questions.md`
- **Handoff:** the roster → spine and zeitgeist-linking steps are one-off scripts kept beside the spine, not repo code. The roster script overwrites `people.yaml`, `assignments.yaml` and `exclusions.yaml`; the linking script appends and refuses to run twice. From here on the spine is edited by hand. Consent now comes from the roster, not from "data exists ⇒ consent" — see Design.

## Context

Nothing about people can be interpreted until the spine exists. Who wore which tag when, replacements, lost tags, battery changes, early departures and the programme are all recorded in prose in the field logs. Those logs are in the private context library (the beacon and EDA logs under `context/personal/`, the acoustics log under `context/sources/`). This can start **before** the sensor data arrives.

All output is local. The repo only receives tooling improvements and instrument-level facts (for `studies/dsa-2026/study.yaml`).

## Design

- Run `uv run social-energy init-spine studies/dsa-2026/study.yaml`. It seeds `meta`, `locations` and location-tag `assignments`.
- Build `people.yaml` from the study-ID list. Roles: participant / course_leader / academy_leader / musician / researcher / guest.
- **Consent comes from the team's roster** (handed over 2026-09-21) for the modules that ran on site: `beacons`, `self_report`, `eda`, `acoustics`, `interview_in_person`. There the paper form is the only record, and a tag logs data whether or not its wearer agreed, so participation proves nothing and `consented()` is a filter that does fire.
- **For the two modules that ran on the platform it does not.** zeitgeist-platform will not start a voice interview until the person has accepted the consent text, and the survey follows inside the same session. So the interview *is* the consent record, there is nothing to fetch, and the roster's QL-2 / QL-3 columns are simply outdated (2026-09-22, Álvaro). The roster also contradicts itself there: most of the people it marks as declining the AI interview it marks as consenting to the survey, which is only reachable by doing the interview.
- Build `assignments.yaml`: each person's beacon from arrival (default: study ID = beacon ID), replacement tags from the swap time, EDA devices per session day.
- Build `exclusions.yaml`: every window in which a tag was not on the person it was assigned to — lost or not worn, battery swaps, tags taken off during an activity, spare and defective tags, departures and withdrawals. The individual cases are listed in the field logs; transcribe them there, not here.
- Build `events.yaml`: the daily programme (plenum, course blocks, meals, choirs), KüAs with rooms and times, special days (excursion, Rotation, concerts, parties) and notable spontaneous gatherings.
- Put instrument-level changes in `study.yaml`: location tags added, moved or damaged (e.g. tag 93 active from 18 Aug 16:10; tag 94 from 20 Aug 12:02; tag 30 failed), and whether location assignments need `end` dates for moved tags.
- **Link the AI-interview and survey platform IDs to study IDs.** The zeitgeist export (`raw/ai-interviews/zeitgeist/<agent>/`, `raw/survey/zeitgeist/<agent>/`) is keyed by the platform's user UUID. Record each link in `assignments.yaml` as a device of kind `zeitgeist`, e.g. `{device: "zeitgeist:<uuid>", entity: "person:<id>", start: <arrival>}` with no end. `Spine.resolve(..., kind="zeitgeist")` then works as it does for beacons, and consent is checked with `spine.consented("interview_ai")` / `("survey")`. Sources for the link, in order of trust:
  1. The answer typed before the interview (`participants.jsonl` → `pre_interview_answers`, also `derived/survey/respondents.parquet` → `study_id_raw`). This turned out to carry the link on its own (2026-09-22): every typed ID resolves to someone on the roster, and where an account appears in both exports the two never disagree, which is an independent check no single source could give. The account, not the person, is the unit: one person can hold several. See [`../../context/instruments/qualitative.md`](../../context/instruments/qualitative.md) for the retry, aborted-call and deleted-account rules.
  2. Where one typed ID occurs on several respondents, the rule is: **keep the most complete submission** per study ID, flag the others as `duplicate_submission`, drop nothing silently (2026-09-20, Mahdi).
  3. Call start times (`interviews.jsonl` → `started_at`), which order a person's accounts and so decide which of them supersedes the others. Survey records carry no usable time at all (see [`../../context/instruments/survey.md`](../../context/instruments/survey.md)), so they are resolved by account.
- Where the log says "check" or leaves a blank ("ADD TIME"), write `[unknown: …]` in a local `open_questions.md` for Mahdi. Never guess a time.

## Tasks

- [x] Get the study-ID list from Mahdi (local, never committed) — arrived 2026-09-21 with consent per module, the location-tag roster, staff and sleeping rooms
- [x] `init-spine`; review the seeded location assignments against moves and damage in the field log (give location tags `end` dates or reassign them)
- [x] Transcribe tag assignments and replacements — the five the roster documents are in; the field log may hold more
- [ ] Transcribe exclusions (lost/found, battery changes, tags taken off, departures, withdrawals) — the roster's are in, the field log's are not
- [ ] Transcribe EDA device ↔ person per session day (needs the distribution plan; Mahdi will supply it later, no date yet)
- [ ] Transcribe the programme and KüA events with locations
- [x] The **in-person** interview log arrived and is in `context/personal/` as **P**. It gives a time and a study ID per interview, and the transcripts are named by start timestamp, so that half needs no mapping table from the team — only the join, which is still to build
- [x] Link every platform UUID in `participants.jsonl` to a study ID (`zeitgeist:<uuid>` assignments). The typed pre-interview ID carries it: every typed ID resolves to someone on the roster, and the survey and interview exports never disagree where they overlap. Conflicts are in `open_questions.md`
- [x] Resolve the calls that have no user row on the platform: they are all one deleted account, with no typed ID and no way to place them, so they are excluded (2026-09-22). Apart from that account no user has more than one call — the earlier note saying otherwise was wrong
- [x] Calls deleted on the platform are **out of scope** (2026-09-20, Mahdi): deleted means not used. Do not ingest them and do not chase them.
- [ ] Check linkage: every platform row resolves to a study ID; unlinked rows are excluded from any analysis
- [ ] `Spine.load()` validates; resolve the synthetic sanity checks; write the open questions for Mahdi
- [ ] Commit only instrument-level additions to `studies/dsa-2026/study.yaml` and any tooling fixes

## Out of scope

- Interpreting any data (see the analysis plans).
- A tool that parses the prose log automatically. The log is too irregular; this is a one-off, careful transcription. Future camps should use a structured log instead (see `ideas/structured-field-log.md`).
