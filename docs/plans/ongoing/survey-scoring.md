# Survey ingest and scoring (SurveyJS → scale scores)

**Priority:** high
**Gate:** ready
**Next:** the analysis plan was frozen on 2026-10-19 (commit 109bc50) and `survey.analysis_plan_frozen` is set: run `social-energy score-survey studies/dsa-2026/study.yaml`, then check reliability and dimensionality.

**Goal:** `social_energy.survey` flattens a SurveyJS export into one row per respondent and computes validated scale scores from a public codebook.

## Handoff

- **Branch:** `main` (#6 and #8 merged).
- **Done:** ingest (`ingest_zeitgeist`, `ingest-survey`). Scoring: `social_energy.survey.codebook` (pydantic, `extra="forbid"`) and `social_energy.survey.score` (`validate_against`, `recode`, `resolve_submissions`, `score`, `reliability`, `score_survey`), and `social-energy score-survey`, which writes `derived/survey/scoring/{scores,reliability,submissions}.parquet` + `qa.json`. Tests: a golden fixture with hand-derived expectations, a synthetic oracle (`synth.survey.generate_scored_survey`), and the CLI and its gate; each was shown to fail under a deliberate mutation of the code. The DSA 2026 codebook covers every code in the real export, and every codebook code exists in it (checked 2026-10-17, codes only, nothing scored). Observed values fit every codebook range. Pre-scoring checks (2026-10-18): `social_energy.survey.checks` (`reverse_key_check`, `version_equivalence`) and `social-energy check-survey`, which writes `derived/survey/checks/{reverse_keys,versions}.parquet` + `summary.json` and computes no score, so it is not gated. Run on the real export: the reverse-keying list agreed with the data for every scale (all `reverse_status: confirmed_by_check`); the version check gave no verdict. Results with numbers in the private note only.
- **Handoff:** answers from the research team go into the codebook only, never into the code. `score-survey` exits 3 until `survey.analysis_plan_frozen` is set. The study-ID correction table is private: a CSV under the data root, named in `local.yaml` (`docs/context/data-layout.md`). It waits on the team's mapping table (`ongoing/dsa-2026-spine.md`). Every score row carries `provisional` while any entry it rests on is not settled (`confirmed`, `decided` or `confirmed_by_check`).

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

Decided by Álvaro, 2026-10-18 (provisional, may be revised; recorded in the codebook's `decisions`):

- **Min items:** a scale score needs at least max(3, ceil(0.5 × k)) valid items, capped at k (k = items in the scale). Codebook `min_items_floor: 3`, `min_share: 0.5`.
- **B16 and C5:** positive and negative affect subscales only; no PISA single index.
- **B16 add-ons** (tired, listless, exhausted): their own `fatigue` subscale; if its reliability is poor it is reported item by item.
- **B19, B20:** read item by item, exploratory only; never in a scale score or composite (`kind: items`).
- **Reverse-keying:** the PISA 2022 handbook where it lists reversed items; where it is silent (C15, C18, `APSI_6`) the wording, confirmed by an empirical check: before reversal, each reversed item correlates negatively with the rest of its scale. Checked 2026-10-18: agreed for every scale.
- **Old form-version codes** count as their current codes if the old code's answer distribution matches the current code's across form versions. Checked 2026-10-18: too few old-code answers for a verdict; the renames stay `inferred`.

## Open questions

The codebook's `pending` list is the authoritative copy of these; every scoring run prints it.

For the research team:

None open. Answered:

- No post-academy wave was fielded (Álvaro, 2026-10-18): DSA 2026 has the baseline only.
- B19/B20 slider range: 1–10, as implemented. Confirmed from the form definition the platform served (structuredVersion 18), checked 2026-10-18; codebook `range_status: confirmed`.

For Álvaro:

- Old-code answers count as their current codes (decided 2026-10-18; the distribution check had too few answers for a verdict).
- Fatigue subscale: reported as a score only if Cronbach's alpha is at least 0.70, else item by item (decided 2026-10-18; also in the analysis plan).

## Tasks

- [x] Ingest: `ingest_zeitgeist` → items (long) + respondents, flags, QA; golden fixture, synthetic oracle, CLI `ingest-survey`
- [x] Codebook `studies/<id>/survey_codebook.yaml` + loader and validation against the ingested item codes
- [x] Recode: harmonise reversed scales, reverse-key, non-substantive codes (`ZGL_B4_01`, B7 6/7, C16 3, `SYMBOL_2_6/7`) → missing, old → current codes
- [x] Scale scores with a min-items rule; reliability (α/ω) per scale
- [x] Study-ID normalisation + local correction table (code; the team's mapping table has not arrived, see `ongoing/dsa-2026-spine.md`)
- [x] De-duplicate by study ID: keep the most complete submission, flag the rest, account for both in the QA dict
- [x] Record the analyst's decisions (2026-10-18): min-items floor, subscales, B19/B20 as items
- [x] Pre-scoring checks: reverse keys (item-rest) and old codes (distributions), `check-survey`; run on the real export, statuses set, numbers in the private note
- [x] Old-code answers: count as their current codes (Álvaro, 2026-10-18)
- [x] B19/B20 range: 1–10, confirmed from the served form definition (2026-10-18)
- [ ] After the freeze (set 2026-10-19): run `score-survey`, check reliability and dimensionality for the adapted and own scales (R-SWE, B15, C5, B16 add-ons); counts go to the private study notes only
