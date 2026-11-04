# DSA 2026: networks around moments, and whether shared moments last

**Priority:** high — the research team asked for descriptive network analyses to run beside the theory work
**Gate:** decision:the research team reads the private note and says whether a follow-up is wanted (recheck 2026-11-18)
**Next:** take the private note `dsa-2026/notes/moments-networks-2026-11-04.md` to the research team, then retire this plan

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

## Read with care

The near window of shared against solo presses is partly built in: a shared press needs someone close. This was not stated in the rules above and was noticed on reading the output.

## Files

- `src/social_energy/moments.py`: lag sums, windows, cluster-mass sign-flip test, component sizes, eigenvector centrality.
- `tests/test_moments.py`: hand-derived expectations and a planted-effect oracle.
- `studies/dsa-2026/analyses/moments_networks.py`, `tests/test_moments_networks_study.py`.
- Outputs under `$SOCIAL_ENERGY_DATA/dsa-2026/derived/analyses/exploratory/moments-networks/`; results only in the private note `dsa-2026/notes/moments-networks-2026-11-04.md`.

## Tasks

- [x] Toolkit and tests
- [x] Study script and tests
- [x] Run on the real data; write the private note
- [x] Carry the outcome into the reply to the team and check it against the preregistration draft

## Not doing now

- **Generative model:** waits for the team's correction of the rival-mechanisms table (private note `dsa-2026/notes/network-methods-reply-2026-11-04.md`).
- **Community detection and dynamic block models:** a plain version recovers courses and the timetable; it needs a question about groups beyond them.
- **Hidden Markov and Kalman models:** the membrane is measured once before the academy, so a hidden state has little to be checked against. `[unknown: was a post-academy survey wave fielded?]`
- **Membrane distance in B:** whether coming back depends on the gradient waits until B itself shows something.
