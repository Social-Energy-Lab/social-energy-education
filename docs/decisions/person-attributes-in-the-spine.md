# Person attributes live in the spine

**Date:** 2026-10-17 · **Status:** adopted

## Context

The confirmatory tests in a study's analysis plan need a few facts about each person beyond role
and consent: course membership (the cross-course outcome and the clustering of standard errors),
and age and gender (covariates). The roster carries them. Until now one analysis parsed the
roster's markdown table directly, so the same fact had two readers, and any correction made by
hand in the spine (a course change, a replacement) would not have reached it.

## Decision

- **`people.yaml` carries them**, as optional typed fields on `Person`: `course`, `age`, `gender`.
  Typed fields rather than a free mapping, so a misspelt key fails loudly at load
  (`extra="forbid"`), as every other spine field does.
- **`Spine.people_frame()`** gives one row per person (`entity`, `id`, `role`, `course`, `age`,
  `gender`) for analyses to join on `entity`. Analyses read courses from there and nowhere else.
- **The values come from the roster** and are copied in by a one-off local script beside the
  spine, like the other roster steps. From then on they are edited by hand with the rest of the
  spine.
- **No new privacy tier.** Course, age and gender together are quasi-identifiers. They sit in the
  local spine with consent and assignments, which is already never committed, and outputs follow
  the existing rule: aggregates only, small cells suppressed.

## Rejected

- **A separate `attributes.yaml`.** One more file to keep in step with `people.yaml` for three
  fields that describe the same person.
- **Reading the survey's own gender and age items.** They exist only for survey consenters and
  would make a beacon-only outcome depend on the survey join, which the analysis plan forbids
  before it is frozen.
