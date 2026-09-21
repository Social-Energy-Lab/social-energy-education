# Two repos: public methods, private context

**Date:** 2026-09-21 · **Status:** adopted

## Context

Before this repo was published, its full git history was audited against the data perimeter. No
research data and no credentials were found, but three kinds of content would have been wrong to
publish:

1. A section-by-section reconstruction of unpublished manuscripts shared with the team, including
   an unpublished claim about a named partner organisation.
2. Details of internal team discussion, including where team members read the theory differently.
3. Facts about individual records and people: counts from the real export, single anomalous
   records, and anecdotes from the field logs. Some had been generalised in the current files but
   survived in earlier commits.

The cause was structural, not carelessness. A private place existed for **source documents**
(`context/`), but not for **our own notes about them**. An agent that learned something
unpublishable had nowhere to put it except this repo, and the guidance at the time said to
"distil what matters into the repo".

## Decision

Two repos, with the private one holding everything by default.

- **Public** (this repo): the toolkit, instrument behaviour, formats, non-personal study config,
  and the *rule* a finding produced — "keep the most complete submission per study ID".
- **Private** (`$SOCIAL_ENERGY_DATA`, also the data root): source documents, `_team/` notes,
  per-study `notes/`, and `local.yaml` with identifiers of private platform deployments. The
  finding itself stays here.
- **In no repo at all:** `context/personal/` (field logs, rosters, anything naming or tracking a
  person), `spine/`, `raw/`, `derived/`. Git-ignored, hook-refused, handed over as an encrypted
  archive. Pseudonymised data on a third-party host is the project lead's decision to make, not a
  default to drift into.

Three mechanisms enforce it:

- The private repo's pre-commit hook refuses anything outside markdown, text and yaml, and
  anything under a personal or data folder.
- `scripts/check_perimeter.py` gains a content check against `_team/perimeter-denylist.txt` —
  names, private identifiers, phrases from unpublished work. The list lives in the private repo,
  so names can be checked for without being published. CI has no data root and runs the
  file-type half only.
- `StudyConfig.load` refuses platform identifiers in the public `study.yaml` and reads them from
  the private `local.yaml` instead.

The public history was squashed to a single commit before the first push, because the earlier
commits contained material that now lives in the private half.

## Consequences

- Writing goes to the private half by default; promoting a note to the public repo is a
  deliberate act. This is the opposite of the previous default, and it is slower.
- CI cannot run the denylist check, so it protects the commit, not the pull request. A
  contributor without a data root gets less protection — acceptable, because contributors without
  a data root also have nothing private to leak.
- The public repo lost the reconstruction of the unpublished theory. Analyses that need it read
  `_team/theory-notes.md`. When Rosa's texts are published, the public theory doc can cite them
  properly.
- Counts from the real data stay out of plans and docs. A study's participant count remains in
  its `README.md`, where describing the field phase is the point.
