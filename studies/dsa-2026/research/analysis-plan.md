# Analysis plan: DSA 2026 (draft for the research team)

**Status:** **frozen 2026-10-19** at commit 109bc50, signed by Álvaro for the analysis team, before any survey scale was scored. Drafted 2026-10-17; analysis choices set by Álvaro on 2026-10-18. From here on the confirmatory part is fixed: any change is a reported deviation, and any added analysis is exploratory.

Builds on [`questions.md`](questions.md) (which questions this phase can speak to) and [`constructs.md`](constructs.md) (how the survey blocks map to trust and lust for life). The framing follows [`../../../docs/context/project.md`](../../../docs/context/project.md): we describe interactional, experiential and developmental *signatures* of social energy; we do not claim to measure it.

## Why two tiers

The beacon data has been analysed descriptively already (co-presence by phase, the context of self-reports, beacon health). Whatever those analyses showed can no longer be tested on the same data as if unseen. They are **exploratory** here, and become **confirmatory targets for the next field phases** (START-Stiftung, SUPER YOU), written down before those data exist.

The survey baseline has not been scored. Any hypothesis that links baseline trust or lust for life to what happened during the academy is therefore still blind, and can be **confirmatory on DSA 2026** if it is fixed now.

## Confirmatory hypotheses (fixed before survey scoring)

Unit: one row per participant with beacon and survey consent. Predictors are the baseline survey composites, standardised. Outcomes are computed over the observation window, outside each person's lost windows and exclusion windows.

**Composites** (Álvaro, 2026-10-18). Each composite is the mean of a fixed core set of scale scores, each standardised first; a person needs a valid score on at least four of the six scales. The core sets keep the scales that describe the person's own relationships, stance and well-being, and leave out those that describe the school (climate hindrances B2, bullying B3, diversity practices B4, truancy B18) or are own, unvalidated items (B19, B20, R-SWE). Everything outside the core sets is exploratory.

- **Trust in life (block B):** school belonging B1, trust B8, teacher–student relationship B11, family support B14, positive affect B16, life satisfaction B17.
- **Lust for life (block C):** general self-efficacy C1a, creative self-efficacy C3, proactive learning C6, assertiveness C8, perseverance C12, openness to the unknown C21.

Scale scoring rules (min items, subscales, reverse-keying) are in [`../survey_codebook.yaml`](../survey_codebook.yaml). An own or adapted subscale (the B16 fatigue items) is reported as a score only if Cronbach's alpha is at least 0.70, else item by item.

| # | Hypothesis | Predictor | Outcome | Direction |
|---|---|---|---|---|
| C1 | People who start with more trust in life become more embedded in the academy's interaction network. | trust-in-life composite (block B) | mean daily strength in the close-contact network (minutes within `close_rssi`, contacts of at least `min_minutes`) | positive |
| C2 | People who start with more lust for life / agency reach further across the academy. | lust-for-life composite (block C) | share of close-contact time with people outside one's own course | positive |
| C4 | Being moved is more frequent for those who start more open. | blocks B and C (two tests) | self-reports per exposure hour (presses on wiped tags excluded from both sides of the rate) | positive |

**How the outcomes are computed.** The definitions are code: `social_energy.outcomes` (toolkit, with hand-derived tests) and [`../analyses/outcomes.py`](../analyses/outcomes.py) (this study's settings and variants), which writes one row per participant and variant to `derived/analyses/outcomes/`. It reads beacon data only and never touches the survey. Operational choices the hypotheses above leave open, all `[inferred]` until signed:

- *Close and tie.* A 5-minute bin is close when the pair's strongest reading in it is at least `close_rssi` (main −65 dBm); a pair is tied on a camp day (07:30–07:30) when its close minutes reach `min_minutes` (main 60). The minimum applies per pair and day. Ties are between participants with beacon consent only; staff are left out.
- *Days.* Camp days 13–28 Aug; the 29 Aug stub (07:30–09:00) is left out. A day counts for a person when their tag was seen for at least an hour; ties on other days do not count for that person, so a tag that went silent does not read as an isolated day.
- *C1* is the person's tie minutes per present day, averaged over present days (weighted degree, in minutes).
- *C2* uses the same ties: tie minutes with participants of another course over tie minutes with participants whose course is known. It is reported next to the share expected if everyone present mixed at random, `(N − n_course) / (N − 1)` over the participants present on any day, and their difference. Course comes from the spine (`Spine.people_frame()`).
- *C3, stability rule* (Álvaro, 2026-10-18). The first definition (new ties per day) ranked people very differently under the threshold variants of sensitivity 4. A C3 definition stays confirmatory only if, across people, every pre-specified variant correlates at least 0.7 (Spearman) with the main one. If no candidate passes before the freeze, C3 moves to the exploratory tier and the confirmatory family shrinks to four tests. **Applied 2026-10-18:** neither candidate passed (distinct partners first tied after the burn-in, which on these data equals the first definition person by person; and distinct partners over the whole camp), so C3 is exploratory (see below). The numbers are in the private half.
- *C3, first definition (kept for comparison)* counts a pair's first tie, on a present day after the first two camp days (13 and 14 Aug, which set the baseline), for each side; divided by the person's present days after them.
- *C4* counts press episodes (merged and accidental runs dropped as in the first analyses) per exposure hour, from the instruction (14 Aug 08:45) to the handover. Exposure is a 5-minute bin in which the tag was seen; bins in a lost window or an unsettled window leave both the presses and the hours, and a press counts only in an exposure bin. It needs both beacon and self-report consent, since the exposure comes from the beacon data.
- *Lost windows* for C1–C3: a pair bin survives one partner's lost window when the other partner logged it (main); sensitivity 5 drops it for both.

**Model** (Álvaro, 2026-10-18). For C1 and C2, linear regression of the outcome on its predictor with **course fixed effects** and HC3 robust standard errors; covariates age and gender, gender as one indicator (female vs not), since a category held by one person can neither be estimated nor reported. Clustered standard errors were the first idea, but six courses are too few clusters for them to be trusted, and fixed effects also absorb course size, which drives C2's expected share. For C4, a negative binomial model of the press count with log exposure hours as offset and the same covariates and fixed effects: presses are overdispersed counts over unequal exposure, and a plain rate gives short exposures too much weight. As a check that does not rest on these assumptions, a permutation test that shuffles survey rows across people within course.

**Error control.** The confirmatory family is the four tests above: C1, C2 and C4 (which counts twice). C3 left it on 2026-10-18 under the stability rule. Holm correction at α = 0.05. Report every result, with standardised effect sizes and 95% intervals, whether or not it passes.

**Power, honestly.** With fewer than a hundred people, only moderate to large associations (|r| around 0.3 or more) can be detected reliably. A null result is weak evidence of no effect, and will be reported as such.

## Exploratory analyses (no error control, labelled as exploratory)

- **New ties (former C3):** lust for life against new close partners after the first two days, reported with all its threshold variants side by side, since its ranking of people depends on them.
- **Moved moments in company:** presses happen with more close others around than ordinary moments of the same person (already seen descriptively). Within-person comparison against the same person's other moments.
- **The programme's rhythm:** cross-course mixing on special days (excursion, rotation) and whether those ties persist.
- **Collective moments:** presses clustered in time among co-located people (cascades).
- **Places and programme items:** self-report density by zone and event type; formal (courses, plenum) against informal (KüA, late evening) settings.
- **Background and embedding (RQ3, within DSA only):** family-background items (block A) against network position. Two-sided, descriptive. DSA is a selective setting, so this is no answer to RQ4; the contrast settings are.
- **Acoustics:** room loudness and spectral activity (dining hall, main hall) against press density at the same times.
- **EDA:** arousal around presses, once the data and the device-distribution plan are in.

## Pre-specified sensitivity analyses

Every confirmatory result is rerun with:

1. ~~the observation window from arrival (13 Aug 11:30)~~ dropped (2026-10-19): tags were handed out until ~17:30, and before then a worn tag cannot be told from one at the desk (beacon team);
2. the readouts our ID repair leaves ambiguous filled from the beacon team's hand split;
3. no drift correction;
4. close-contact thresholds of −70 and −75 dBm, and minimum durations of 15 and 30 minutes;
5. lost windows treated as missing for both partners rather than recovered from the partner's side;
6. for C4, exposure as the time the tag was assigned to the person (minus exclusion, lost and unsettled windows) instead of the time it was heard;
7. for C4, accidental runs defined as the beacon team described them, repeated pressing for about seven minutes, instead of 60 s or 8 presses.

A result that flips under one of these is reported as fragile. Variants 4 and 5 are computed by [`../analyses/outcomes.py`](../analyses/outcomes.py) (one change at a time: −70, −75 dBm at 60 min; 15, 30 min at −65 dBm; lost windows on both sides). Variants 2 and 3 change the ingest itself: [`../analyses/sensitivity_ingests.py`](../analyses/sensitivity_ingests.py) rebuilds it into a folder of its own (`derived/sensitivity/<variant>/`, the main ingest untouched) with that one setting changed, and everything downstream on it (pairs, present days, lost and unsettled windows, presses); `outcomes.py` then adds the rows `hand_split_fill` and `no_drift` with the main settings otherwise. For 2, the hand label of each readout comes from the beacon team's relabelled copy of the 13–15 Aug logs, matched line by line, and is used only where clock anchors and witnesses both leave the readout ambiguous; readouts the hand split did not label stay out, as in the main run. For 3, records are dated with a clock rate of 0 instead of the study's, and lost windows follow the same rate.

## Reporting

- Aggregates only, never a single person. Cells with fewer than five people are suppressed `[inferred: the ethics approval forbids reporting small groups; the threshold is our proposal]`.
- No course-level result for a course small enough to identify people.
- Figures show distributions, not individuals.

## What has to be in place first

| Needed for | Item | Owner | State |
|---|---|---|---|
| C1–C4 | Survey composites | — | ready to score once the plan is frozen; nothing open on the survey side except the freeze (reverse keys checked against the data, B19/B20 range confirmed, 2026-10-18) |
| C1–C4 | Spine: remaining open questions (return times, lost tags) | research team | open |
| C2 | Course membership per participant | — | in the spine (`people.yaml`, `Spine.people_frame()`) |
| sensitivity 1 | Whether 13 Aug 11:30–18:00 is usable | beacon team | answered 2026-10-19: no; sensitivity 1 dropped |
| EDA | Device data and distribution plan | research team | open |

## Sign-off

- Agreed by: Álvaro (analysis team), 2026-10-19
- Frozen at: 2026-10-19, commit 109bc50 (the plan's text as of that commit; this sign-off block is the only later edit)
