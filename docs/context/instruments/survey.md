# Instrument: structured questionnaire (SurveyJS)

Status: **ingest and scoring built (`social_energy.survey`, `social-energy ingest-survey` / `score-survey`), with the DSA 2026 codebook in `studies/dsa-2026/survey_codebook.yaml`. Scoring has not been run on real data:** scales are scored only after the analysis plan is frozen, and the B19/B20 range waits on the research team. The reverse-keying list has been checked against the data (`social-energy check-survey`, see Pre-scoring checks below). This doc is the spec for them. It describes the **short version implemented in SurveyJS** for DSA 2026 (implementation basis dated 2026-08-05). It lists item codes, response formats and sources. The wording of the study's *own* items (codes `ZGL_*`, `RSWE_*`, `*_GRAD`, `SYMBOL_*`) is unpublished instrument work and stays in the private context library. PISA items are published (PISA 2022 German scale handbook, Müller et al. 2025).

## Design

- **Mode:** SurveyJS online, one sitting, about one hour. Welcome page, 7 thematic pages, submit page (no re-submission). Progress bar on every page.
- **Answering rules:** no pre-selected answers; a slider row counts only after an active choice; one answer per matrix row. Required status was left open (sensitive and open questions not required by default), so **expect item-level missingness**.
- **Wave:** used as the **baseline** before the academy. Items refer to "the school year just finished". A post-academy parallel version is anticipated for several blocks (B1, B7, B11, C9) `[unknown: was a post wave fielded?]`.
- **Linkage:** a typed study ID. The implementation basis names it `ZGL_A0_STUDY_ID`, but on zeitgeist-platform it was asked as a separate question before the interview (see Export below). Typos and swapped IDs are possible, so a local correction table is needed. Which ID it is (beacon-based study ID or the one from the invitation email) is **deferred**: the team will hand over a mapping table later (2026-09-20, Mahdi), and that table, not the typed value, is the authority.
- **Not included:** no peer nominations, no daily diary, no in-academy energy ratings.
- **Page order:** 1 general and school (A2, A3, A4, A6, A5, A1) → 2 school experiences (B1, B2, B11, B12, B7, B18, B3, B4a, B4b) → 3 people and cooperation (B8, B10, B14, C9, C7, C8) → 4 coping and learning (C1a, C1b, C3, C6, C11, C12, C13, C15, C21) → 5 feelings and well-being (B16, B17, B19, B20, B21) → 6 self and future (B15, C5, C18, C16, C17, A14) → 7 family background (A7, A8, A9, A11, A12, A15, A16, A18, A20, A21, A22).

## Blocks

The questionnaire has three blocks with a theoretical role: **A** background and inequality dimensions; **B** the "membrane" (belonging, relationships, climate, well-being: *trust in life*); **C** agency and openness (*lust for life* / self-efficacy). This block logic is the **authoritative construct mapping** for analyses — self-efficacy belongs to lust for life (confirmed 2026-09-20, Mahdi; see `docs/context/theory.md`). Visible headings are neutral; theory terms are never shown to respondents.

Scale abbreviations: **agree4** = 1 strongly disagree … 4 strongly agree; **agree5** = 1 … 5 with 3 = neither; **rev** = scale printed in reverse (1 = most agreement / most frequent). Items to reverse-key follow the PISA 2022 handbook where it lists reversed items and the wording where it is silent, each confirmed by an item-rest check (Recoding below).

### A: Background

| Code | Construct | Items | Response | Source |
|---|---|---|---|---|
| A0 `ZGL_A0_STUDY_ID` | study ID | 1 | text | own |
| A1 `ZGL_A1_1`, `ZGL_A1_2` | state/country (free text); settlement type | 2 | text; 4 options | own |
| A2 `ST003C01TA_DE`, `ST003C02TA_DE` | birth month, year | 2 | dropdown | PISA ST003 |
| A3 `ST004` (+ `ZGL_A3_optional`) | gender (f/m/diverse; "no answer") | 1 | single | PISA ST004, adapted |
| A4 `ZGL_A4_01…09` (+`_09_TEXT`) | school type (9 grouped types) | 1 | single (+ text) | PISA ST002, grouped |
| A5 `ST226` | years at current school | 1 | 5 options | PISA |
| A6 `ST001` | grade (vocational 1–3, grades 7–13) | 1 | 10 options | PISA |
| A7 `ST230` | siblings | 1 | 4 options | PISA |
| A8 `ST005`, A11 `ST007` | mother's / father's school degree | 1+1 | 7 options | PISA |
| A9 `ST006C01…09`, A12 `ST008C01…09` | mother's / father's vocational/academic degrees (C09 "none", own addition) | 9+9 | yes/no | PISA + own |
| A14 `ST259Q01JA`, `Q02JA` | subjective social status: family now; self at 30 | 2 | slider 1–10 | PISA |
| A15 `ST250…` | home possessions (11; video camera dropped) | 11 | yes/no | PISA |
| A16 `ST251…` | family wealth items | 6 | none/1/2/3+ | PISA |
| A18 `ST255` | books at home | 1 | 7 levels | PISA |
| A20 `ST019AC01_DE`, `BC01`, `CC01` | birth country: self, mother, father | 3 | free text | PISA ST019 adapted |
| A21 `ST021C01TA_DE` | age at immigration (only if born outside Germany) | 1 | 20 options | PISA |
| A22 `ST022`, `ZGL_A22_2` | home language; preferred language for personal topics | 2 | free text | PISA + own |

### B: Membrane / trust in life

| Code | Construct | Items | Response | Source | Reverse-key candidates `[inferred]` |
|---|---|---|---|---|---|
| B1 `ST034Q01–06TA` | school belonging | 6 | agree4 **rev** | PISA BELONG | Q01, Q04, Q06 |
| B2 `SC061Q01–11` | hindrances to school climate (principal item → student view) | 11 | 1 not at all … 4 a lot | PISA SC061 adapted | — |
| B3 `ST038Q03–11` | bullying, last 12 months | 9 | 4-pt frequency | PISA BULLIED | — |
| B4a `SC173Q01–06`, `ZGL_B4A_01–02` | school diversity practices | 6+2 | 5-pt frequency + 6 = don't know | PISA SC173 adapted + own | — |
| B4b `ZGL_B4B_01–02` | discrimination experienced / observed | 2 | 4-pt frequency | own | — |
| B7 `ST337Q01–08JA`, `ZGL_B7_01–05` | extracurricular activities at school (+ up to 5 dynamic "other") | 8+4+dyn | 5-pt frequency + 6 not offered / 7 cannot join | PISA CREATAS + own | — |
| B8 `ST315Q01–10JA` | trust | 10 | agree5 | PISA | Q01, Q05, Q07 |
| B10 `ST303Q01–08JA` | perspective-taking | 8 | agree5 | PISA | Q05, Q07 |
| B11 `ST267Q01–08JA` | teacher–student relationship | 8 | agree4 | PISA RELATST | Q04, Q08 |
| B12 `ST270Q01–04JA`, `ZGL_B12_01`, `ZGL_B12_02_Resonanz` | teacher support (+ feedback item, + resonance item) | 4+2 | 1 every lesson … 4 never **rev** | PISA TEACHSUP adapted + own | — |
| B14 `ST300Q01–10JA` | family support | 10 | 5-pt frequency | PISA FAMSUP | — |
| B15 `APSI_1_adjusted, APSI_2_adjusted, APSI_3–5, APSI_6_adjusted, APSI_7–8`, `ZGL_B15_GRAD` | sense of identity (own German translation) + gradient | 8+1 | agree5 | Lounsbury et al. 2005 | APSI_6 |
| B16 `ST826C01–09HA_DE`, `ZGL_B16_10–12` | subjective well-being (+ tired, listless, exhausted) | 9+3 | 1 never … 5 always (PISA uses 4) | PISA ST826 adapted + own | negative affects scored as own subscale |
| B17 `ST016` | life satisfaction, "recent days" | 1 | slider 0–10 | PISA | — |
| B18 `ST062Q01–03TA` | truancy / lateness, last two school weeks | 3 | 4-pt frequency | PISA | — |
| B19 `ZGL_B19_1–7` | fear drivers (item by item, exploratory; no scale score) | 7 | slider **1–10** in implementation (0–10 in the full version) | own | — |
| B20 `ZGL_B20_1–8` | sources of joy (item by item, exploratory; no scale score) | 8 | slider **1–10** in implementation (0–10 in the full version) | own | — |
| B21 `SYMBOL_1`, `SYMBOL_2_1–7`, `SYMBOL_3` | something that gives strength (free text) + how often used / "not applicable" | 3 | text + 7 options | own | `SYMBOL_2_6`, `_2_7` are not frequency levels |

### C: Agency / lust for life

| Code | Construct | Items | Response | Source | Reverse-key candidates `[inferred]` |
|---|---|---|---|---|---|
| C1a `SWE_01–10`, `ZGL_C1A_GRAD` | general self-efficacy + gradient | 10+1 | 1 not true … 4 exactly true | Schwarzer & Jerusalem 1999 | — |
| C1b `RSWE_01–06`, `RSWE_GRAD` | **resonance-oriented self-efficacy** (exploratory, unvalidated) + gradient | 6+1 | same as SWE | own, after Rosa | — |
| C3 `ST334Q01–10JA` | creative self-efficacy | 10 | 4-pt confidence | PISA CREATEFF | — |
| C5 `ST836C01–10JA_DE` | feelings about the future (context changed from maths → exploratory) | 10 | 5-pt frequency | PISA ST836 adapted | negative feelings as a subscale |
| C6 `ST293Q01–09JA` | proactive learning (maths → all lessons) | 9 | 5-pt frequency | PISA ST293 adapted | Q04, Q07 |
| C7 `ST343Q01–10JA` | cooperation | 10 | agree5 | PISA COOPAGR | Q02, Q04, Q05, Q07, Q10 |
| C8 `ST305Q01JA, Q02JA_adjusted, Q03–10JA`, `ZGL_C08_GRAD` | assertiveness / initiative + gradient | 10+1 | agree5 | PISA ASSERAGR adapted | Q04, Q07, Q08 |
| C9 `ST336Q01, Q03–07JA` | creative peer/family environment | 6 | agree4 | PISA CREATFAM | — |
| C11 `ST355Q03–08JA`, `GRADIENT_variable_C11` | self-directed learning + gradient (separate agree4 question) | 6+1 | 4-pt confidence | PISA SDLEFF adapted | — |
| C12 `ST307Q01–10JA` | perseverance | 10 | agree5 | PISA PERSEVAGR | Q04, Q06, Q07, Q10 |
| C13 `ST313Q01–10JA` | emotional control | 10 | agree5 | PISA EMOCOAGR | Q02–04, Q06, Q08–10 |
| C15 `ST309Q01–10JA` | impulsivity / reflection | 10 | agree5 | PISA ST309 | Q02, Q03, Q07, Q09 |
| C16 `ST327C02–11JA_DE` | expected degrees | 10 | yes / no / don't know | PISA | — |
| C17 `ST329` | expected occupation at ~30 (free text, for ISCO coding) | 1 | text | PISA | — |
| C18 `ST324Q02, 04, 05, 07, 10–14JA` | education-path expectations | 9 | agree4 | PISA ST324 | Q02, Q05, Q07, Q10, Q11 |
| C21 `ST140_a–h`, `GRADIENT_variable_C21` | openness to the unknown + gradient | 8+1 | agree4 | PISA ST140 | b, e, h |

**Long version only** (not implemented at DSA 2026): parental occupation (A10/A13), digital devices (A17), types of books (A19), creative school climate (B5), classroom discipline (B6), empathy (B9), teacher feedback (B13), growth mindset (C2), creativity by domain (C4), stress resistance (C14), curiosity (C20).

## Scoring spec (`social_energy.survey`)

- **Export (DSA 2026):** the survey ran inside zeitgeist-platform right after the AI interview. Local file: `$SOCIAL_ENERGY_DATA/<id>/raw/survey/zeitgeist/<agent_name>/responses.jsonl` (downloaded together with the interviews by `social-energy fetch-zeitgeist`), one object per respondent, keyed by the platform user UUID. Each object carries two views of the answers:
  - `responses`: flat `{item_code: value}`. Matrix rows are already flattened to `BLOCK_SCALE.ITEM` keys (e.g. `B1_ST034.ST034Q01TA`). Standalone items use their bare code (`ST004`, `ZGL_A1_1`).
  - `surveys_resolved`: a list of about 330 items per respondent with `question_id`, `type` (`single_choice`, `number`, `text`, `multiple_choice`), `phase` (`pre` = the one question asked before the interview, `post` = the survey), `required`, `value_raw`, `value_label` and `value_numeric`. Prefer this view for scoring, since it carries both code and label.
  - Codes seen in the export that differ from the implementation basis: `ZGL_A0_ID` (not `ZGL_A0_STUDY_ID`, present for only a handful of respondents) and `*_resonance` variants of some SWE items. `[inferred]` The study ID is mostly captured by the platform's pre-interview question, not by A0.
  - **Three form versions were live** (`responses.__survey_version` 16, 17 and 18; most respondents saw 18). Items that exist only in an older version (e.g. `GRADIENT_variable_C11/C21` before `ZGL_C11_GRAD/ZGL_C21_GRAD`, `SWE_05–07_resonance`) appear **only in the flat `responses`**, not in `surveys_resolved`. Neither view is complete alone: merge them, taking type, scale and labels from `surveys_resolved` where present.
  - **Unanswered items are absent** from a respondent's record, not stored as empty.
  - **Repeated submissions.** One typed study ID can appear on two respondent records. This is most likely the same person filling the survey twice after their connection dropped (2026-09-20, Mahdi). Rule: **keep the most complete submission** per study ID (most answered items; ties go to the later `surveys_resolved_at`), flag the rest `duplicate_submission`, and never drop a record silently — the QA dict accounts for it.
  - `value_numeric` is null when the chosen option is a code, not a number: `ZGL_B4_01` (the "don't know" option in B4a), `ZGL_A3_optional` (the extra A3 option), the `ZGL_A4_0n` school types and the `SYMBOL_2_n` / `SYMBOL_3_n` options. `value_label` and `label` are `{de, en}` objects. `scale_max` is the highest option code. It is absent for `number` and `text` items.
  - The one `pre` item is a `number` item with a platform-generated question ID, holding the study ID typed before the interview. The study names it in `study.yaml` (`survey.zeitgeist.study_id_item`).
  - `surveys_resolved_at` is ISO 8601 with a UTC offset. **It is not a submission time.** In the DSA 2026 export every respondent carries the same value to within a few seconds, weeks after the survey ran, which is the signature of a bulk rewrite on the platform. The real answering times are not in the export. Treat a survey record as untimed: resolve it to a person through its account, never by timestamp, and never use it to order respondents or to place an answer inside the programme. `[unknown: can the platform still supply the original submission times?]`
  - Ingest: `social-energy ingest-survey` → `derived/survey/{items,respondents}.parquet` + `qa.json` (`social_energy.survey`). Scoring goes through an explicit codebook (below).
- **Codebook:** `studies/<id>/survey_codebook.yaml`, named by `survey.codebook` in `study.yaml`. It groups export codes (matrix rows as `BLOCK_SCALE.ITEM`) into **scales** (averaged), **gradients** (scored alone, with a parent scale) and **item sets** (recoded, not averaged). Each group has a block and role (A background, B trust in life, C lust for life), a range, whether it is printed in reverse, its reverse-keyed items, its non-substantive codes and coded values. Old form-version codes map to current ones under `renames`. Known codes that are not scored (background, free text) are listed under `unscored`. It holds **no item wording**. Every entry carries a status: `confirmed` (research team), `decided` (an analyst's decision, listed with who and when under `decisions`), `confirmed_by_check` (agreed with a pre-scoring check), `inferred` or `unknown`. Every scoring run lists the entries that are `inferred` or `unknown`, and every score row resting on one says it is `provisional`.
- **Validation:** `validate_against` reports export codes the codebook does not know and codebook entries never seen in the export. In the DSA 2026 export both lists are empty, apart from the private study-ID question.
- **Recoding**, in this order:
  - map non-substantive codes to missing (B4a "don't know", which arrives as the code `ZGL_B4_01`, not 6; B7 = 6/7; C16 = 3; `SYMBOL_2_6` and `_7`). Out-of-range values are also missing, and are counted in the QA;
  - coded options become numbers where they are levels (`SYMBOL_2` is one item whose options arrive as the codes `SYMBOL_2_1`…`_7`, with 1–5 as frequency levels);
  - harmonise reversed scales (B1, B12, and the B12 add-ons) so that high = more of the construct;
  - reverse-key negatively worded items. The reverse list is judged **after** harmonising. The candidates in the tables above agree with the reversed items the PISA 2022 scale handbook lists for B1, B8, B10, B11, C6, C7, C8, C12, C13 and C21. For B1 the handbook names the complementary items against the printed order, which is the same recoding. For B12 it reverses all four items, which is the harmonising flip. C15, C18 and B15 (`APSI_6`) rest on wording alone, because the handbook scales no index for them. Decided (Álvaro, 2026-10-18): follow the handbook where it lists reversed items, the wording where it is silent, and confirm both with the item-rest check (below). On the DSA 2026 export the check agreed for every scale;
  - structural skips (A21, A4 text, B21 frequency) are not missing-at-random.
- **Subscales** (decided, Álvaro, 2026-10-18): B16 is scored as positive affect, negative affect (the handbook's reversed items) and a fatigue subscale of the three own add-ons; if the fatigue subscale's reliability is poor, its three items are reported one by one instead. C5 is scored as positive and negative feelings. Neither gets the PISA single index. B19 and B20 are item sets, read item by item and never part of a scale score or composite.
- **Old codes:** `GRADIENT_variable_C11/C21` → `ZGL_C11_GRAD/ZGL_C21_GRAD`, and `SWE_05–07_resonance` → `SWE_05–07` `[inferred]`. The old codes appear only on form version 16, and only on a few of its records: most version-16 records already carry the current codes. Never both on one record. Rule (decided, Álvaro, 2026-10-18): an old code counts as its current code if its answer distribution matches the current code's; on the DSA 2026 export too few old-code answers exist for the check to give a verdict, so the renames stay `[inferred]`. If a record ever carries both codes, the current one wins and the QA counts a conflict.
- **Scale scores:** the item mean, valid only from max(3, ceil(0.5 × k)) valid answers, capped at k (the scale's items), unless a group sets `min_items` (decided, Álvaro, 2026-10-18; codebook `min_items_floor`, `min_share`). PISA scales its indices from three valid answers. One row per respondent per scale and gradient, with `n_items` used. Report reliability (Cronbach's α, and McDonald's ω from a one-factor principal-axis model of the correlations, which can differ slightly from a CFA ω). Both are computed on complete cases of the kept submissions. Check dimensionality for adapted and own scales (R-SWE, B15, C5, B16 add-ons) before using a score. PISA indices are IRT-scaled (WLE) in PISA itself, so our means are **not** comparable to published PISA indices.
- **Gradient items** (`ZGL_B15_GRAD`, `ZGL_C1A_GRAD`, `RSWE_GRADIENT`, `ZGL_C08_GRAD`, `ZGL_C11_GRAD`, `ZGL_C21_GRAD`) are scored separately, never inside the parent scale. A14 (now vs at 30) gives a mobility/aspiration gradient; C16/C17 make it concrete.
- **Study IDs:** whitespace is removed and letters are upper-cased. A local correction table, kept in the private data root and never in the repo, overrides a record's ID by respondent or by typed value (see `docs/context/data-layout.md`). For repeat submissions, ties after `surveys_resolved_at` go to the later line of the export.
- **Pre-scoring checks** (`social-energy check-survey`, `social_energy.survey.checks`): survey-internal, no score computed, so not gated. On the kept submissions:
  - `reverse_key_check`: per item of every scale, the correlation of the item, before reverse-keying, with the sum of the scale's other items keyed as the codebook says. A reversed item must be negative and any other item non-negative; an item with no variance gives no verdict. The rest summed unreversed is reported alongside, but it mixes directions and is not the criterion.
  - `version_equivalence`: per old/new code pair, the answer counts, a chi-square test of homogeneity and a Mann-Whitney U test; "equivalent" when neither rejects at 0.05, no verdict when either code has fewer than five answers.
  - Outputs go to `derived/survey/checks/`; results with numbers go to the private study notes only.
- **Gate:** `score-survey` refuses until `survey.analysis_plan_frozen` is set in `study.yaml`. Scales are scored only after the analysis plan is signed and frozen.
- **Known inconsistencies to resolve:**
  - B19/B20 slider range (1–10 implemented vs 0–10 in the full version). The export holds 1–10 only, which fits either;
  - the R-SWE gradient is `RSWE_GRAD` in the implementation basis and `RSWE_GRADIENT` in the export (the codebook uses the export's code);
  - B12 resonance item code (`ZGL_B12_02_Resonanz` in the implementation vs `_01_` in the full version);
  - `GRADIENT_variable` without suffix in the long-version C20;
  - "none" exclusivity in A9/A12;
  - normalisation of A20 free-text countries for the A21 skip logic.

## Privacy

Never store in the repo, fixtures or logs:
- free text (A1_1, A4 text, A20, A22, B7 other, B21 `SYMBOL_1`, C17);
- the quasi-identifier combination birth month + year + gender + state;
- person-level bullying, discrimination or fear items;
- the study ID itself.

Synthetic fixtures use invented values only. Report only aggregates, with small cells suppressed.
