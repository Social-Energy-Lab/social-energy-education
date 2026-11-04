# DSA 2026: networks around moments, and whether shared moments last

**Priority:** high — the research team asked for descriptive network analyses to run beside the theory work
**Gate:** decision:the research team reads the private notes, corrects the rival-mechanisms table and says what size of gradient effect would matter (recheck 2026-11-18)
**Next:** with the team's answers in hand, decide on the two proposed experiments (gatherings; the same question over days), then retire this plan

**Goal:** describe how a person's company changes in the hour around a self-report, and whether pairs who shared a moment spend more time together on later days than pairs who were equally close and did not share it. Everything here is **exploratory** under the frozen analysis plan (`studies/dsa-2026/research/analysis-plan.md`); leads that hold become candidates for the next-phase preregistration (`../ideas/next-phase-preregistration.md`).

## Why these two

A team supervisor suggested starting from Wu et al. 2025 (*Nature Communications* 16, 3539, Fig. 2h–k): the lagged correlation of rewards with proximity, chance-corrected, with cluster inference over lags. The method carries over; the setting does not:

- their time series run at 20 Hz over rounds of two minutes, ours in 5-minute bins over 16 days;
- their null permutes a series, which here would show the timetable as a result, because the programme drives both company and presses;
- a reward is an outside event, while a press is a self-report that may follow the moment and may be caused by the company. **Before and after are not cleanly before and after, and nothing here is read causally.**

Latent-state models, community detection and generative models wait: see "Not doing now".

## Rules, fixed before any of this ran

Before this plan was written, only exposure and resolution were counted, with no feature set against presses. Company at lag 0 has been seen before (`exploratory_presses.py`), so the near window below is not fresh evidence. The windows before and after it, the asymmetry and the come-back contrast have not been looked at.

- **Split by day.** The EDA second-pass split, extended to the days without wear: **discovery** 15, 17, 20, 22, 24, 26, 28 Aug; **replication** 14, 16, 18, 19, 21, 23, 25, 27 Aug. One special day falls in each half and the 24–27 Aug dip is shared between them. Camp days as in `copresence_by_phase` (from 07:30); the handover morning falls outside both.
- **Verdict per estimate,** as in the EDA second pass (`eda_split.verdict`): replicates, same direction, does not replicate, no lead. Only "replicates" is read as a lead; everything is reported.
- **Unit.** Participants with `beacons` and `self_report` consent. Staff are left out. Press episodes in exposure bins, as in the cascades. Close = strongest reading in the 5-minute bin ≥ −65 dBm; the people counted as company are participants with `beacons` consent. Cells under 5 people are withheld. Nothing per person or per pair is written.

### A. The lag profile

For each press and each lag from −60 to +60 minutes in 5-minute bins (positive = after the press, the opposite sign to the paper), the presser's value of five features, only in that person's own exposure bins:

| Feature | Definition |
|---|---|
| `close` | close others in the bin |
| `gathering` | size of the person's connected component in the bin's close graph; 1 when alone |
| `centrality` | eigenvector centrality in the close graph of the three bins centred on the bin, weighted by close bins, scaled to 1 for the bin's most central person; 0 outside the leading component `[inferred]` |
| `unfamiliar` | close others with whom the person had no tie on any earlier camp day |
| `cross_course` | share of close others from another course; missing when alone |

- **Effect.** Per person with at least 3 presses in the half and per lag: mean over presses minus the mean over shuffles. Summarised over people, with equal weight per person.
- **Nulls (1,000 shuffles each).** Each press moves to a random exposure bin of the same person within (1) day × phase, the cascades null, and (2) day × clock hour. Each keeps the person's rate and the autocorrelation of their company. A window is read as a lead only if it **replicates under both nulls**.
- **Windows, the estimates that get a verdict.** Before (−60 to −10 min), near (−5 to +5), after (+10 to +60), and **asymmetry** (after minus before). Autocorrelated company around any moment gives a symmetric bump; the asymmetry is the directional signal. 95 % intervals resample people, 4,000 draws.
- **Lag curves** come with cluster inference as in the paper: t per lag, |t| over the two-sided 5 % cut, clusters of neighbouring lags of one sign, cluster mass against 10,000 sign flips per person. Clusters describe the shape; verdicts come from the windows.
- **Secondary, by kind of press.** Shared presses (a co-located pair 10 s to 5 min apart) against solo presses, same estimates.
- **Sensitivities,** main null: −70 dBm; without 24–27 Aug.
- **One-minute check.** `close` at 1-minute resolution, ±15 minutes, same two nulls and verdicts: before (−15 to −3), near (−2 to +2), after (+3 to +15), asymmetry. A minute counts only when the person has a record in it and lies in an exposure bin. Reads the ingest again; a sampling check, not a second headline.

### B. Do pairs who shared a moment come back?

- **Unit.** Pair-day: an unordered pair of unit participants on a camp day from 17 to 27 Aug, so that three earlier days and at least one later day exist.
- **Shared.** The pair had a co-located press pair 10 s to 5 min apart that day.
- **Comparison.** One of the two pressed that day while the other was close in the press's bin and exposed in it, and neither pressed within 5 minutes of the other's press that day. Pair-days whose only co-press is under 10 s are dropped (two tags pressed at once).
- **Outcomes.** log(1 + close minutes) over the next three camp days, and tied on any of them (linear probability). No follow-up reaches past 28 Aug.
- **Held fixed.** log(1 + close minutes that day), log(1 + close minutes on earlier days), tied on an earlier day, same course, log(1 + bins in which both were seen in the follow-up), one dummy per person, one per camp day. Whether they were heard together afterwards is not held fixed: it is part of coming back.
- **Intervals.** Node bootstrap over people (`rhythm.node_bootstrap_weights`), 1,000 draws.
- **Split.** By the day of the moment. Follow-up days can cross halves, so the halves are not fully independent here.
- **Placebo: the three days before.** The same contrast on close minutes in the three preceding days, holding fixed that day's minutes, minutes and ties before those three days, same course, seen bins in those days and the dummies. Pairs who share moments may simply be converging already. **A come-back result counts as a lead only if it replicates and the all-days placebo interval includes zero.** Otherwise it is reported as "already converging".
- **Sensitivities.** −70 dBm; including co-presses under 10 s; moment days whose follow-up misses 24–27 Aug (17–20 Aug); cross-course pairs only.

### C. Could A and B have seen an effect?

Added after A and B ran, and before this was. It asks what their "no lead" is worth, so it reports what the analyses find when an effect of known size is put in, and not new evidence about the camp. Fixed here, before running:

- **Background with no real signal.** The effect is planted on pseudo-events, so the real presses and shared moments are not in the data being tested.
  - *A:* pseudo-presses come from one draw of the day × clock-hour shuffle, for the same people in the same hours.
  - *B:* the real shared pair-days are dropped. As many comparison pair-days as the real shared ones in each half become pseudo-shared, drawn within strata of same course × tied earlier × tercile of that day's minutes, in the real shared days' proportions.
- **Planted in A: contacts widen after a moment.** For every pseudo-press, `close` or `unfamiliar` rises by δ in the person's exposure bins from +10 to +60 minutes. δ ∈ {0, 0.1, 0.25, 0.5, 1} people. Other features are not planted. Each run reads the planted grid under 100 shuffles per null, reused across runs.
- **Planted in B: pairs come back.** Close minutes over the follow-up × f for pseudo-shared pair-days, f ∈ {1, 1.25, 1.5, 2, 3}, on the log-minutes outcome. Separately, tied later rises by p ∈ {0, 10, 20, 30} percentage points by turning untied pseudo-shared pair-days into tied ones at random, on the tied outcome. Node bootstrap with 200 draws per run. The placebo is not rerun, because the plant does not touch the days before.
- **Runs.** 100 per level, seeded. A detection rate near 50 % carries about ±10 points.
- **Counts as detected.**
  - *A:* asymmetry and, reported separately, the after window, positive and "replicates" under **both** nulls.
  - *B:* positive and "replicates". Reported beside it: the all-days interval excludes zero, and the median all-days estimate against what was planted.
- **Reading.** The smallest planted size detected in at least 80 % of runs is what the analysis could reliably have seen. Level 0 gives the false-lead rate. Below that size, the "no lead" says little.
- **Limits.** Planted effects are uniform across people and moments, which is the easiest case: uneven real effects would be harder to detect. The gradient analysis (`exploratory_gradients.py`) is not covered here.

### D. Could the gradient analysis have seen an effect?

The same question for `exploratory_gradients.py`, the analysis the gradient theory leans on most. Added after it ran. Fixed here, before running; **it is not new evidence about the camp**.

- **Background with no real signal.** Each run permutes the membranes within course, the analysis's own null, which breaks any real link between membrane and contact while keeping the real contact and the real co-presses.
- **Noisy measurement.** The theory speaks of membranes, and we observe survey scores. In each run a person's true score on each column is the observed standardised score × √r plus noise × √(1 − r), with r the column's Cronbach's alpha from `confirmatory/reliability.csv`, so that the plant follows the true distance and the test sees the measured one. A single-item scale has no alpha and takes the median of the other scales' `[inferred]`. Everything is also run with r = 1, to show what the survey's noise costs.
- **Planted, opposites attract (H-a).** log(1 + close minutes) rises by log(1 + g) per SD of the true distance, g ∈ {0, 5, 10, 20, 40 %}. All pairs and within-course pairs, person dummies and the other controls as in the analysis.
- **Planted, high gradients make flow more probable (H-b).** A close partner's chance of co-pressing moves with the true distance, odds ratio per SD ∈ {1, 1.25, 1.5, 2, 3}, by flipping individual partner moments so that the overall share stays about the same.
- **Measures.** `trust`, `lust`, `trust_scales`, `all_scales`, one at a time.
- **Test.** The analysis's statistic against its node-permutation null, within course, 500 permutations per run. Detected: positive, and at least as extreme as observed in at most 5 % of the null, two-sided. Only the node null is replayed: the time-shuffle null moves the presses, which a plant on partner moments cannot follow.
- **Runs.** 100 per level, seeded.
- **Reading.** As in C: the smallest planted size detected in at least 80 % of runs. Level 0 gives the false-positive rate.
- **Limits.** One test per run, while the analysis scanned many measures, samples and outcomes, so this flatters it. Plants are uniform over pairs and independent across partner moments, the easiest case. Membrane scores are treated as stable over the camp.

## Read with care

Two method points came out of section C and bind later analyses around presses. The clock-hour null also absorbs a real effect lasting about an hour, because shuffled presses land in the same hour and read the raised bins, so its estimates are not effect sizes. And with few shared pair-days per half, the split-half verdict on coming back is underpowered, so the all-days interval is the informative number there. The all-days interval of B's node bootstrap is also wider than it should be: at planted size zero it excluded zero less often than 5 %.

The near window of shared against solo presses is partly built in: a shared press needs someone close. This was not stated in the rules above and was noticed on reading the output.

## Files

- `src/social_energy/moments.py`: lag sums, windows, cluster-mass sign-flip test, component sizes, eigenvector centrality.
- `tests/test_moments.py`: hand-derived expectations and a planted-effect oracle.
- `studies/dsa-2026/analyses/moments_networks.py`, `tests/test_moments_networks_study.py`.
- `studies/dsa-2026/analyses/moments_sensitivity.py`, `tests/test_moments_sensitivity_study.py` (section C).
- `studies/dsa-2026/analyses/gradient_sensitivity.py`, `tests/test_gradient_sensitivity_study.py` (section D); `dyads.true_scores` and `dyads.flip_towards`.
- Outputs under `$SOCIAL_ENERGY_DATA/dsa-2026/derived/analyses/exploratory/moments-networks/`; results only in the private note `dsa-2026/notes/moments-networks-2026-11-04.md`.

## Tasks

- [x] Toolkit and tests
- [x] Study script and tests
- [x] Run on the real data; write the private note
- [x] Carry the outcome into the reply to the team and check it against the preregistration draft
- [x] C: script and tests; run; private note `dsa-2026/notes/moments-sensitivity-2026-11-04.md`
- [x] D: script and tests; run; private note `dsa-2026/notes/gradient-sensitivity-2026-11-04.md`

## Not doing now

- **Which gatherings produce shared moments, and the same question over days in both directions:** proposed, and waiting for the team's correction of the rival-mechanisms table, which may change the features.
- **Generative model:** waits for the team's correction of the rival-mechanisms table (private note `dsa-2026/notes/network-methods-reply-2026-11-04.md`).
- **Community detection and dynamic block models:** a plain version recovers courses and the timetable; it needs a question about groups beyond them.
- **Hidden Markov and Kalman models:** the membrane is measured once before the academy, so a hidden state has little to be checked against. `[unknown: was a post-academy survey wave fielded?]`
- **Membrane distance in B:** whether coming back depends on the gradient waits until B itself shows something.
