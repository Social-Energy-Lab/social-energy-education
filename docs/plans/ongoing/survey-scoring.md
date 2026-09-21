# Survey ingest and scoring (SurveyJS → scale scores)

**Goal:** `social_energy.survey` flattens a SurveyJS export into one row per respondent and computes validated scale scores from a public codebook.

## Status

- **Updated:** 2026-09-20
- **Priority:** high
- **Stage:** ingest done; next is the codebook, then scoring
- **Branch:** `main`
- **Done:** `social_energy.survey.ingest_zeitgeist` + `social-energy ingest-survey` (golden fixture, synthetic oracle, CLI test). The real DSA 2026 export ingests cleanly across three form versions, with no empty, out-of-range or mismatched rows; the counts are in the private study notes.
- **Next:** write `studies/dsa-2026/survey_codebook.yaml` from `docs/context/instruments/survey.md` (codes and scales only, no own-item wording), including how old-version codes map to current ones (`GRADIENT_variable_C11` → `ZGL_C11_GRAD`, `SWE_0n_resonance` → ?).
- **Blockers:** confirmed reverse-keying list; B19/B20 slider range (the export shows 1–10 in use)
- **Handoff:** raw export via `fetch-zeitgeist` (see `docs/context/data-layout.md`); `ingest-survey` writes `derived/survey/{items,respondents}.parquet` + `qa.json`. Rows are keyed by platform user UUID; joining to people waits on the ID linking in `ongoing/dsa-2026-spine.md`.

## Context

The baseline questionnaire is the 1st-person anchor for trust in life / lust for life. The full spec is in [`docs/context/instruments/survey.md`](../../context/instruments/survey.md). The export has been seen and ingested (2026-09-18); its format and traps are in the instrument doc.

## Design / approach

- `studies/dsa-2026/survey_codebook.yaml` records item code → block, construct, scale range, direction, reverse flag, non-substantive codes and gradient flag. It contains **no own-item wording**. PISA and SWE items can be referenced by code.
- `social_energy.survey`: `flatten(export) -> DataFrame` (codes, not labels); `score(df, codebook) -> DataFrame` (means with a min-items rule); `reliability(df, codebook)` (α/ω per scale); a QA dict covering missingness per item and out-of-range values.
- Study-ID normalisation (case/whitespace) plus a local correction table (swaps, typos). Join to the spine only through the study ID.
- Synthetic export generator for tests (invented answers).

## Decided

- Export shape resolved: matrices arrive flattened, values as codes, with labels alongside (see the instrument doc).

- The codebook may be public (item codes, constructs, scales; no wording of own items). Álvaro, 2026-09-18.

- Block C (self-efficacy, self-regulation, motivation) is scored under **lust for life**, block B under **trust in life**, following the questionnaire's own block logic. Mahdi, 2026-09-20.
- **Repeated submissions:** the same typed study ID on several respondent records is the same person re-submitting after a connection drop. Keep the most complete submission per study ID (ties → later `surveys_resolved_at`), flag the others `duplicate_submission`, drop nothing silently. Mahdi, 2026-09-20.

## Open questions

- `[unknown: was a post-academy wave fielded, and with which blocks?]`
- `[unknown: which B19/B20 slider range went live (1–10 or 0–10)?]` The export only shows values 1–10 `[inferred: 1–10]`.
- `[unknown: confirmed reverse-keying list from the PISA handbook]`

## Tasks

- [x] Ingest: `ingest_zeitgeist` → items (long) + respondents, flags, QA; golden fixture, synthetic oracle, CLI `ingest-survey`
- [ ] Codebook `studies/<id>/survey_codebook.yaml` + loader and validation against the ingested item codes
- [ ] Recode: harmonise reversed scales, reverse-key, non-substantive codes (`ZGL_B4_01`, B7 6/7, C16 3, `SYMBOL_2_7`) → missing
- [ ] Scale scores with a min-items rule; reliability (α/ω) per scale
- [ ] Study-ID normalisation + local correction table (depends on the spine linking; the team's mapping table is the authority and has not arrived yet)
- [ ] De-duplicate by study ID: keep the most complete submission, flag the rest, account for both in the QA dict
