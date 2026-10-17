# Survey ingest and scoring (SurveyJS → scale scores)

**Priority:** high
**Gate:** blocked:confirmed reverse-keying list and the live B19/B20 slider range (_team/questions.md #7–8) (recheck 2026-10-30)
**Next:** fill the research team's answers into `studies/dsa-2026/survey_codebook.yaml` (the `pending` list: reverse keys, B19/B20 range, old-code mapping, min-items rule, subscales), flipping each answered entry's status to `confirmed`. Then, once the analysis plan is signed and frozen, set `survey.analysis_plan_frozen` in `study.yaml` and run `social-energy score-survey studies/dsa-2026/study.yaml`. Do not score before the freeze, and do not join scores to beacon outcomes before it either.

**Goal:** `social_energy.survey` flattens a SurveyJS export into one row per respondent and computes validated scale scores from a public codebook.

## Handoff

- **Branch:** `feat/survey-scoring` (not pushed; for review)
- **Done:** ingest (`ingest_zeitgeist`, `ingest-survey`). Scoring: `social_energy.survey.codebook` (pydantic, `extra="forbid"`) and `social_energy.survey.score` (`validate_against`, `recode`, `resolve_submissions`, `score`, `reliability`, `score_survey`), and `social-energy score-survey`, which writes `derived/survey/scoring/{scores,reliability,submissions}.parquet` + `qa.json`. Tests: a golden fixture with hand-derived expectations, a synthetic oracle (`synth.survey.generate_scored_survey`), and the CLI and its gate; each was shown to fail under a deliberate mutation of the code. The DSA 2026 codebook covers every code in the real export, and every codebook code exists in it (checked 2026-10-17, codes only, nothing scored). Observed values fit every codebook range.
- **Handoff:** answers from the research team go into the codebook only, never into the code. `score-survey` exits 3 until `survey.analysis_plan_frozen` is set. The study-ID correction table is private: a CSV under the data root, named in `local.yaml` (`docs/context/data-layout.md`). It waits on the team's mapping table (`ongoing/dsa-2026-spine.md`). Every score row carries `provisional` while any entry it rests on is unconfirmed.

## Context

The baseline questionnaire is the 1st-person anchor for trust in life / lust for life. The full spec is in [`docs/context/instruments/survey.md`](../../context/instruments/survey.md). The export has been seen and ingested (2026-09-18); its format and traps are in the instrument doc.

## Design / approach

- `studies/dsa-2026/survey_codebook.yaml` groups item codes into scales, gradients and item sets. Each group has a block, role, range, printed direction, reverse keys, non-substantive codes and coded values. Old-version codes map to current ones under `renames`, known unscored codes sit under `unscored`, and the open questions under `pending`. It holds **no own-item wording**. PISA and SWE items are referenced by code.
- `social_energy.survey`: `ingest_zeitgeist` (codes, not labels); `recode` (non-substantive and out-of-range → missing, harmonise printed-reversed scales, then reverse-key); `score` (item means with a min-items rule, gradients on their own); `reliability` (α and one-factor ω on complete cases of the kept submissions); `score_survey` with a QA dict covering missingness per item, out-of-range and non-substantive counts, codes outside the codebook, renames and submissions.
- Study-ID normalisation (whitespace removed, upper case) plus a local correction table (swaps, typos) by respondent or by typed value. Join to the spine only through the study ID.
- **Scoring gate:** `score-survey` refuses until `survey.analysis_plan_frozen` names the freeze, so the confirmatory survey hypotheses stay blind in code as well as by convention.
- Synthetic generators for tests (invented answers): `generate_survey` (ingest) and `generate_scored_survey`. The latter encodes known construct-direction answers into printed answers.

## Decided

- Export shape resolved: matrices arrive flattened, values as codes, with labels alongside (see the instrument doc).

- The codebook may be public (item codes, constructs, scales; no wording of own items). Álvaro, 2026-09-18.

- Block C (self-efficacy, self-regulation, motivation) is scored under **lust for life**, block B under **trust in life**, following the questionnaire's own block logic. Mahdi, 2026-09-20.
- **Repeated submissions:** the same typed study ID on several respondent records is the same person re-submitting after a connection drop. Keep the most complete submission per study ID (ties → later `surveys_resolved_at`), flag the others `duplicate_submission`, drop nothing silently. Mahdi, 2026-09-20. Implemented: "most complete" counts non-empty answered items; a remaining tie goes to the later export line. Duplicates are still scored and flagged. Reliability and per-item missingness use the kept submissions only.

## Open questions

The codebook's `pending` list is the authoritative copy of these; every scoring run prints it.

- `[unknown: was a post-academy wave fielded, and with which blocks?]`
- `[unknown: which B19/B20 slider range went live (1–10 or 0–10)?]` The export only shows values 1–10 `[inferred: 1–10]`.
- `[unknown: confirmed reverse-keying list from the PISA handbook]` The candidates agree with the handbook's reversed items wherever it lists them. C15, C18 and `APSI_6` rest on wording alone.
- `[unknown: do the old form-version codes stand for the same items on the same response format?]` (`GRADIENT_variable_C11/C21` → `ZGL_C11/C21_GRAD`, `SWE_05–07_resonance` → `SWE_05–07`)
- `[unknown: is half the items (min_share 0.5) the right minimum for a scale score?]`
- `[unknown: score the PISA single B16/C5 index too, or only the positive/negative subscales? Do the B16 add-ons join negative affect?]`
- `[unknown: are B19 and B20 scales, or read item by item?]`

## Tasks

- [x] Ingest: `ingest_zeitgeist` → items (long) + respondents, flags, QA; golden fixture, synthetic oracle, CLI `ingest-survey`
- [x] Codebook `studies/<id>/survey_codebook.yaml` + loader and validation against the ingested item codes
- [x] Recode: harmonise reversed scales, reverse-key, non-substantive codes (`ZGL_B4_01`, B7 6/7, C16 3, `SYMBOL_2_6/7`) → missing, old → current codes
- [x] Scale scores with a min-items rule; reliability (α/ω) per scale
- [x] Study-ID normalisation + local correction table (code; the team's mapping table has not arrived, see `ongoing/dsa-2026-spine.md`)
- [x] De-duplicate by study ID: keep the most complete submission, flag the rest, account for both in the QA dict
- [ ] Fill in the research team's answers; flip statuses to `confirmed`
- [ ] After the freeze: set `survey.analysis_plan_frozen`, run `score-survey`, check reliability and dimensionality for the adapted and own scales (R-SWE, B15, C5, B16 add-ons); counts go to the private study notes only
