# Preregistration for the next field phases (START-Stiftung, SUPER YOU)

**Priority:** high — it must be frozen before either phase's beacon or survey data are read
**Gate:** decision:the research team agrees which hypotheses become confirmatory for START-Stiftung and SUPER YOU (recheck 2026-11-04)
**Next:** walk through this draft with the research team after the 3 Nov presentation; then copy the agreed part into each phase's `studies/<id>/research/analysis-plan.md` and freeze it there

**Goal:** a confirmatory analysis plan for the next field phases, written before their data exist, that turns the DSA 2026 exploratory leads into tests and repeats the DSA 2026 confirmatory tests as replications.

## Context

The DSA 2026 plan ([`../../../studies/dsa-2026/research/analysis-plan.md`](../../../studies/dsa-2026/research/analysis-plan.md)) was frozen on 2026-10-19. Its confirmatory tier (C1, C2, C4) and its exploratory tier have both run. The results, with every number, are in the private notes (`$SOCIAL_ENERGY_DATA/dsa-2026/notes/confirmatory-2026-10-19.md` and the three `exploratory-*-2026-10-20.md` notes). Nothing from them is repeated here.

What the exploratory tier showed cannot be tested again on the same data. It can be tested on fresh data, if the test is fixed first. This plan does that for the next two phases. Every hypothesis below says which DSA 2026 analysis motivated it; the size of the DSA effect is in the private notes only.

This file is the shared draft. Each phase gets its own frozen copy under `studies/<id>/research/`, with that phase's settings (rooms, groups, days, timetable) filled in from its `study.yaml`. A phase plan may drop a hypothesis before its data are read, never after.

Both phases are contrast settings (RQ4, see [`../../context/project.md`](../../context/project.md)). Their programmes, group structures and ages differ from DSA. The definitions below therefore name roles ("the phase's main group", "special days"), not DSA's rooms or courses.

## Common definitions

These follow the DSA 2026 code (`social_energy.outcomes`, `social_energy.exploratory`, `social_energy.rhythm`), with the phase's own study config.

- **Close.** A 5-minute bin is close for a pair when its strongest reading is at least the phase's `close_rssi` (main −65 dBm unless an RSSI ground-truth session at that phase says otherwise, see [`rssi-ground-truth-session.md`](rssi-ground-truth-session.md)). The value is fixed in the phase plan before the data are read.
- **Tie.** A pair is tied on a camp day (the phase's day boundary) when its close minutes reach `min_minutes` (main 60).
- **Main group.** The unit the programme sorts people into for most of the day: a course, a class or a workshop group. Taken from the spine.
- **Special days.** Days the timetable marks, before the phase starts, as suspending the main group (an excursion, a rotation day, a joint project day). Listed in the phase plan with their dates. A phase with none drops H-MIX-1 and H-MIX-2.
- **Phase of day.** The phase's clock blocks, taken from its timetable before the data are read.
- **Press episode.** As at DSA: presses under 60 s apart merged, accidental runs removed. Only episodes in an exposure bin count.
- **Exposure bin.** A 5-minute bin in which the person's tag was seen, outside that tag's lost and unsettled windows and the person's exclusion windows, from the press instruction to the handover.
- **Co-located pair.** Two press episodes by different participants within a stated gap, at close range in the bin of either press.
- **Day-bootstrap.** Resample camp days with replacement, recompute the statistic, 2,000 draws, percentile interval. It needs at least 8 camp days with presses.
- **Seeds and shuffles.** Every Monte Carlo test uses 10,000 shuffles and a seed written in the phase plan.
- **Unit.** Participants with the consents each test needs. Staff are left out of every test and reported separately, descriptively.
- **Reporting.** Aggregates only, no cell under 5 people, no result for a group small enough to identify people.

## Family A: new confirmatory hypotheses

Holm correction at α = 0.05 over the hypotheses of this family that the phase plan keeps. All tests are one-sided in the stated direction. Every result is reported with its effect size and interval, whether or not it passes.

### H-CASC-1: collective moments

*Motivation:* the DSA 2026 exploratory analysis of cascades (`studies/dsa-2026/analyses/exploratory_cascades.py`) found presses clustering in time among co-located people beyond each person's own timing. Numbers in the private notes.

- **Hypothesis.** Self-reports cluster in time among co-located participants beyond what each person's own timing predicts.
- **Unit.** Press episodes of participants with beacon and self-report consent, in exposure bins.
- **Definition.** A co-located pair is two episodes 10 s to 5 min apart. Pairs under 10 s are left out of the primary test, which guards against two tags pressed at once in a bag.
- **Null.** Each episode is moved to a uniformly drawn exposure bin of the same person, on the same camp day and in the same phase of day, at a uniform offset in the bin.
- **Statistic.** R = observed co-located pairs / mean of the null.
- **Test.** Monte Carlo p = (1 + shuffles ≥ observed) / (1 + shuffles). Supported when p passes Holm **and** the day-bootstrap 95% interval of R lies above 1.
- **Minimum sample.** At least 40 participants with both consents, 8 camp days with presses, 800 press episodes in exposure, and a null mean of at least 40 co-located pairs. Below any of these the test is reported as descriptive. The null-mean floor is set so that R = 1.5 sits well above the null's spread at one-sided α = 0.05; the DSA null's spread that sized it is in the private notes.
- **Sensitivities.** −70 and −75 dBm; dropping the 5 person pairs with the most co-located pairs (from observed and null alike); including pairs under 10 s; the null drawn within day × phase × setting, once settings come from the timetable.

### H-CASC-2: a shared moment, not a delayed prompt

*Motivation:* in the same DSA 2026 analysis, the excess was largest at the shortest gaps and decayed within about a minute. Numbers in the private notes.

- **Hypothesis.** Among co-located pairs up to 15 min apart, the excess over the null is larger at short gaps than at long ones.
- **Statistic.** R_short / R_long, where R_short covers gaps of 10–60 s and R_long gaps of 2–15 min, each against the same null as H-CASC-1.
- **Test.** The day-bootstrap one-sided 95% lower bound of the ratio exceeds 1, and the Monte Carlo p of the ratio passes Holm.
- **Minimum sample.** As H-CASC-1, plus a null mean of at least 15 pairs in the 10–60 s band.
- **Sensitivities.** As H-CASC-1, and the short band starting at 30 s (above any plausible clock disagreement).

What it cannot settle: a press visible to a neighbour within seconds looks the same as a shared moment. A support for H-CASC-2 argues against delayed prompting only.

### H-COMP-1: moved moments happen in company

*Motivation:* the DSA 2026 within-person analysis of company at presses (`studies/dsa-2026/analyses/exploratory_presses.py`) found more close others around at presses than in the same person's other moments of the same day and phase, an excess that shrank when matched to the clock hour. Numbers in the private notes.

- **Hypothesis.** A person has more participants at close range when they press than at their own other moments of the same camp day and phase of day.
- **Unit.** Participants with beacon and self-report consent and at least 5 press episodes in exposure bins for which they have company data.
- **Statistic.** For each press bin, the number of other participants at close range. For each person, the mean over their press bins minus the mean over their own exposure bins in the same day × phase strata, weighted by the person's presses per stratum. D is the mean of these differences over people.
- **Null.** The same shuffle as H-CASC-1 (each press moved within the person's own day × phase exposure bins). Monte Carlo p as above.
- **Test.** Supported when p passes Holm and the 95% bootstrap interval of D over people lies above 0.
- **Minimum sample.** At least 40 eligible people.
- **Secondary, reported beside it, not tested.** The share of press bins with nobody close against matched bins; the same contrast matched to day × clock hour, which separates company from finer timing.
- **Sensitivities.** −70 and −75 dBm; matching to day × hour; days with low own-record coverage removed.

### H-MIX-1: special days mix the camp

*Motivation:* the DSA 2026 analysis of the programme's rhythm (`studies/dsa-2026/analyses/exploratory_rhythm.py`) found a large within-person rise in cross-course mixing on the excursion and rotation days. Numbers in the private notes.

- **Hypothesis.** On special days a person's tie minutes cross their main group more than on ordinary days, above what random mixing among those present would give.
- **Unit.** Participants with beacon consent and a main group, present (tag seen for at least an hour) on at least one special day and three ordinary days.
- **Statistic.** For each person and day, the cross-group share of tie minutes minus the share expected under random mixing among those present that day. The person's mean over special days minus their mean over ordinary days, pooled over special days. D is the mean over people.
- **Test.** One-sided paired t on the per-person differences, with the Wilcoxon signed-rank test as a check. Supported when the t-test passes Holm.
- **Minimum sample.** At least 30 eligible people.
- **Sensitivities.** −70 dBm; `min_minutes` 30; ordinary days with low own-record coverage removed; lost windows on both sides.

### H-MIX-2: ties made on special days persist less

*Motivation:* in the same analysis, ties first made on the special days came back on later days less often than ties first made on ordinary days. The estimate was precise for one special day and not for the other. Numbers in the private notes.

- **Hypothesis.** A pair's first tie made on a special day is less likely to recur on a later day than a first tie made on an ordinary day.
- **Unit.** Pairs of participants with beacon consent whose first tie falls after the burn-in (the phase's first two camp days).
- **Model.** Logistic regression of "tied again" on each later day where both partners are present, with special day of first tie as the predictor, terms for follow-up day and lag. Interval from resampling people (a pair is kept when either partner is drawn, as in `social_energy.rhythm`).
- **Test.** The one-sided 95% upper bound of the odds ratio (special against ordinary) is below 1 and the bootstrap p passes Holm.
- **Minimum sample.** At least 150 new ties formed on special days in total. Below that it is reported as descriptive.
- **Sensitivities.** Cross-group new ties only; lags 1–3 only; −70 dBm; `min_minutes` 30.

What it measures: repeated time together, not acquaintance.

### Not proposed as confirmatory

These stay exploratory at the next phases, run with the same code:

- **Who presses first** (baseline trust and lust): weak and fragile on DSA.
- **Tie-strength gradient of cascades:** the DSA intervals overlap.
- **Places and settings** (plenum, course blocks, evenings): the DSA settings were our own classification of a field log, not a timetable. Once a phase has a timetable with end times, a setting contrast fixed in its plan can become a confirmatory secondary at the phase after.
- **Background and cross-group mixing** (RQ3): a weak DSA pattern among many comparisons. Worth repeating where the background range is wider, which is the point of the contrast settings.
- **Acoustics:** the one DSA lead (camp-wide presses when the main hall is louder than usual for the hour) is small. Repeat it as exploratory with the same within-hour model.

## Family B: replications of the DSA 2026 confirmatory tests

C1, C2 and C4 (twice, trust and lust), with the definitions, models, sensitivities and fragility rule of the frozen DSA plan, unchanged except for the phase's settings. Holm at α = 0.05 over these four, separately from family A. On DSA 2026 none of them was supported; the estimates and intervals are in the private notes.

- **Composites.** Same core scales, if the phase's survey carries them. Where an instrument was adapted for the phase's age group, the composite is built from the scales that survived, and the phase plan lists them before scoring. Scoring stays gated on the freeze (`survey.analysis_plan_frozen`).
- **Minimum sample.** At least 40 people in the unit. Below that, report as descriptive.
- **Power.** With 40–100 people only associations of about |r| ≥ 0.3 are reliably detectable. A null is weak evidence of no effect.
- **Pooled estimate (secondary, not tested).** A fixed-effect meta-analysis of the standardised estimates across DSA 2026 and the phases that ran, with phase heterogeneity reported. All phases' estimates are confirmatory, so pooling them is allowed. Its interval answers "how large could the effect be", which no single phase can.

## Instrument and procedure changes that would help

Agreed with the beacon team through [`next-field-phase-beacon-practice.md`](next-field-phase-beacon-practice.md) and logged through [`structured-field-log.md`](structured-field-log.md). Each one names the hypothesis it serves.

- **Own-record readouts every day, and a frequent flush to flash.** Lost windows remove presses from both sides of every press test; fewer of them raises the sample of H-CASC and H-COMP and removes the low-coverage days.
- **A timetable with start and end times, in the spine before the phase.** Settings, phases of day and special days then come from the programme rather than from clock blocks or a field log. Needed for the setting sensitivity of H-CASC-1 and for any setting contrast.
- **Room tags in every room where the programme happens,** including group rooms and common spaces, with a through-wall check in the ground-truth session. Raises the share of placed exposure.
- **Press time precision.** Stamp the press start and keep tag clocks within about a second; the 10–60 s band of H-CASC-2 and any "who first" analysis depend on it.
- **A distinct cancel gesture,** or no cancel instruction, so that a cancel is not counted as a press.
- **Log announcements and researchers' reminders to press** (time, place) as ID-free events. A prompted press in a plenum is otherwise indistinguishable from a moved one.
- **Group lists for special days** (who went where on an excursion), ID-only. They let H-MIX separate a group's own mixing from the day's.
- **Staff consent and a short staff survey,** if staff are to be more than a descriptive side group.
- **A post wave of the survey.** DSA had only a baseline. A post wave turns developmental signatures from inference into a measured change.
- **An RSSI ground-truth session** at each phase ([`rssi-ground-truth-session.md`](rssi-ground-truth-session.md)), so `close_rssi` is chosen on that phase's devices and rooms.

## Open questions

- `[unknown: what are the dates and programme of START-Stiftung and SUPER YOU, and which days suspend the main group?]`
- `[unknown: will both phases use the same beacon firmware and the same press instruction as DSA 2026?]`
- `[unknown: which survey scales are kept or adapted for the SUPER YOU age group?]`
- `[unknown: does the research team want family A and family B as separate Holm families, or one?]`
- `[unknown: should H-MIX-2 be confirmatory at all, given its sample floor?]`
