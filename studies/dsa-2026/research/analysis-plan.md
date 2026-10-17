# Analysis plan: DSA 2026 (draft for the research team)

**Status:** draft proposal, 2026-10-17. Nothing here is agreed until the research team signs it off: `[inferred]` throughout. Once agreed, the plan is frozen (date and commit recorded below) **before the survey scales are scored**.

Builds on [`questions.md`](questions.md) (which questions this phase can speak to) and [`constructs.md`](constructs.md) (how the survey blocks map to trust and lust for life). The framing follows [`../../../docs/context/project.md`](../../../docs/context/project.md): we describe interactional, experiential and developmental *signatures* of social energy; we do not claim to measure it.

## Why two tiers

The beacon data has been analysed descriptively already (co-presence by phase, the context of self-reports, beacon health). Whatever those analyses showed can no longer be tested on the same data as if unseen. They are **exploratory** here, and become **confirmatory targets for the next field phases** (START-Stiftung, SUPER YOU), written down before those data exist.

The survey baseline has not been scored. Any hypothesis that links baseline trust or lust for life to what happened during the academy is therefore still blind, and can be **confirmatory on DSA 2026** if it is fixed now.

## Confirmatory hypotheses (fixed before survey scoring)

Unit: one row per participant with beacon and survey consent. Predictors are the baseline survey composites (block codes in [`constructs.md`](constructs.md)), standardised. Outcomes are computed over the observation window, outside each person's lost windows and exclusion windows.

| # | Hypothesis | Predictor | Outcome | Direction |
|---|---|---|---|---|
| C1 | People who start with more trust in life become more embedded in the academy's interaction network. | trust-in-life composite (block B) | mean daily strength in the close-contact network (minutes within `close_rssi`, contacts of at least `min_minutes`) | positive |
| C2 | People who start with more lust for life / agency reach further across the academy. | lust-for-life composite (block C) | share of close-contact time with people outside one's own course | positive |
| C3 | Lust for life also shows as more new ties. | block C composite | new close ties per day after the first two days | positive |
| C4 | Being moved is more frequent for those who start more open. | blocks B and C (two tests) | self-reports per exposure hour (presses on wiped tags excluded from both sides of the rate) | positive |

**How the outcomes are computed.** The definitions are code: `social_energy.outcomes` (toolkit, with hand-derived tests) and [`../analyses/outcomes.py`](../analyses/outcomes.py) (this study's settings and variants), which writes one row per participant and variant to `derived/analyses/outcomes/`. It reads beacon data only and never touches the survey. Operational choices the hypotheses above leave open, all `[inferred]` until signed:

- *Close and tie.* A 5-minute bin is close when the pair's strongest reading in it is at least `close_rssi` (main −65 dBm); a pair is tied on a camp day (07:30–07:30) when its close minutes reach `min_minutes` (main 60). The minimum applies per pair and day. Ties are between participants with beacon consent only; staff are left out.
- *Days.* Camp days 13–28 Aug; the 29 Aug stub (07:30–09:00) is left out. A day counts for a person when their tag was seen for at least an hour; ties on other days do not count for that person, so a tag that went silent does not read as an isolated day.
- *C1* is the person's tie minutes per present day, averaged over present days (weighted degree, in minutes).
- *C2* uses the same ties: tie minutes with participants of another course over tie minutes with participants whose course is known. It is reported next to the share expected if everyone present mixed at random, `(N − n_course) / (N − 1)` over the participants present on any day, and their difference. Course comes from the spine (`Spine.people_frame()`).
- *C3* counts a pair's first tie, on a present day after the first two camp days (13 and 14 Aug, which set the baseline), for each side; divided by the person's present days after them.
- *C4* counts press episodes (merged and accidental runs dropped as in the first analyses) per exposure hour, from the instruction (14 Aug 08:45) to the handover. Exposure is a 5-minute bin in which the tag was seen; bins in a lost window or an unsettled window leave both the presses and the hours, and a press counts only in an exposure bin. It needs both beacon and self-report consent, since the exposure comes from the beacon data.
- *Lost windows* for C1–C3: a pair bin survives one partner's lost window when the other partner logged it (main); sensitivity 5 drops it for both.

**Model.** Linear regression of each outcome on its predictor, with age and gender as covariates and standard errors clustered by course (network outcomes are not independent within a course). As a check that does not rest on those assumptions, a permutation test that shuffles survey rows across people within course.

**Error control.** The confirmatory family is the five tests above (C4 counts twice). Holm correction at α = 0.05. Report every result, with standardised effect sizes and 95% intervals, whether or not it passes.

**Power, honestly.** With fewer than a hundred people, only moderate to large associations (|r| around 0.3 or more) can be detected reliably. A null result is weak evidence of no effect, and will be reported as such.

## Exploratory analyses (no error control, labelled as exploratory)

- **Moved moments in company:** presses happen with more close others around than ordinary moments of the same person (already seen descriptively). Within-person comparison against the same person's other moments.
- **The programme's rhythm:** cross-course mixing on special days (excursion, rotation) and whether those ties persist.
- **Collective moments:** presses clustered in time among co-located people (cascades).
- **Places and programme items:** self-report density by zone and event type; formal (courses, plenum) against informal (KüA, late evening) settings.
- **Background and embedding (RQ3, within DSA only):** family-background items (block A) against network position. Two-sided, descriptive. DSA is a selective setting, so this is no answer to RQ4; the contrast settings are.
- **Acoustics:** room loudness and spectral activity (dining hall, main hall) against press density at the same times.
- **EDA:** arousal around presses, once the data and the device-distribution plan are in.

## Pre-specified sensitivity analyses

Every confirmatory result is rerun with:

1. the observation window from arrival (13 Aug 11:30) instead of 18:00;
2. the readouts our ID repair leaves ambiguous filled from the beacon team's hand split;
3. no drift correction;
4. close-contact thresholds of −70 and −75 dBm, and minimum durations of 15 and 30 minutes;
5. lost windows treated as missing for both partners rather than recovered from the partner's side.

A result that flips under one of these is reported as fragile. Variants 4 and 5 are computed by [`../analyses/outcomes.py`](../analyses/outcomes.py) (one change at a time: −70, −75 dBm at 60 min; 15, 30 min at −65 dBm; lost windows on both sides). Variants 1–3 need the beacon ingest rebuilt with a different window, the hand-split fill or no drift correction, and are not computed yet.

## Reporting

- Aggregates only, never a single person. Cells with fewer than five people are suppressed `[inferred: the ethics approval forbids reporting small groups; the threshold is our proposal]`.
- No course-level result for a course small enough to identify people.
- Figures show distributions, not individuals.

## What has to be in place first

| Needed for | Item | Owner | State |
|---|---|---|---|
| C1–C4 | Survey composites: reverse-keying list, B19/B20 slider range | research team | `[unknown: open, see the survey-scoring plan]` |
| C1–C4 | Spine: remaining open questions (return times, lost tags) | research team | open |
| C2 | Course membership per participant | — | in the spine (`people.yaml`, `Spine.people_frame()`) |
| sensitivity 1 | Whether 13 Aug 11:30–18:00 is usable | beacon team | `[unknown: asked 2026-10-17]` |
| EDA | Device data and distribution plan | research team | open |

## Sign-off

- Agreed by: `[unknown: research team sign-off]`
- Frozen at: `[unknown: date and commit]`
