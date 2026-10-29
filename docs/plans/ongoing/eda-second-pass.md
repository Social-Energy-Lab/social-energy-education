# DSA 2026: EDA second pass (social dose, pair synchrony, onset synchrony, HRV, person profiles)

**Priority:** high
**Gate:** none
**Next:** build analyses A, C, D, E (one script and PR each), then G on their outputs; results in the private note

**Goal:** look at the EDA and heart-rate data in ways the first exploratory pass (`studies/dsa-2026/analyses/exploratory_eda.py`: presses, settings, minute-level synchrony) did not, and keep only what holds on days it was not found on. Everything here is **exploratory** under the frozen analysis plan (`studies/dsa-2026/research/analysis-plan.md`); leads that hold become candidates for the next-phase preregistration (`../ideas/next-phase-preregistration.md`).

## Handoff

- **Branches:** `feat/eda2-social-dose` (A), `feat/eda2-pair-sync` (C), `feat/eda2-onset-sync` (D), `feat/eda2-hrv` (E), `feat/eda2-person-profiles` (G). One script each under `studies/dsa-2026/analyses/`, named `eda2_<slug>.py`; outputs under `$SOCIAL_ENERGY_DATA/dsa-2026/derived/analyses/exploratory/eda2/<slug>/`.
- **Results:** only in the private half, one note per analysis `dsa-2026/notes/eda2-<slug>-2026-10-29.md`, gathered in `dsa-2026/notes/eda2-summary-2026-10-29.md`.
- **Decided 2026-10-29 (Álvaro):** analyses A, C, D, E, G; split-half rule below; B (room-entry events), F (acoustic events) and H (unsupervised states) not now.

## Rules shared by every analysis

Fixed before any of these analyses ran.

- **Split by day.** The 13 camp days with EDA wear (camp day 04:00–04:00 local, as in the EDA ingest), alternated in date order: **discovery** 15, 17, 20, 22, 24, 26, 28 Aug; **replication** 16, 19, 21, 23, 25, 27 Aug. Helper: `studies/dsa-2026/analyses/eda_split.py`. Every estimate is reported three times: discovery, replication, all days.
- **Verdict per estimate,** from the two halves: **replicates** when the discovery 95 % interval excludes zero and the replication estimate has the same sign with its 95 % interval excluding zero; **same direction** when the discovery interval excludes zero and the replication estimate has the same sign but its interval includes zero; **does not replicate** when the discovery interval excludes zero and the replication estimate has the other sign; **no lead** when the discovery interval includes zero. Only "replicates" is read as a lead; everything is reported.
- **Inherited from the first pass** (`exploratory_eda.py`, reused, not redefined): usable minute, SCR rules (main and ≥ 0.2 µS), within-person-day standardisation, movement residualisation, the method rule that any setting contrast holds clock hour and wear time fixed, HR minute definition, clock variants (`all` primary, `certain` sensitivity), cells under 5 people withheld, intervals by bootstrap over people (pairs: node bootstrap).
- **Beacon side:** close = strongest reading in the 5-min bin ≥ −65 dBm (`copresence_by_phase`); EDA minutes join beacon bins by the bin containing the minute. EDA and beacon clocks agree to about 5 s (checked 2026-10-29), so anything at minute resolution needs no shift; second-level work against beacon events allows ±10 s.

## The analyses

- **A. Social dose** (`eda2_social_dose.py`). Within person-day fixed effects, minute level: SCR (both rules), tonic level, HR against (1) number of close participants in the bin (0, 1, 2–3, 4–7, 8+; and log(1+n) as a slope), (2) among minutes with company, the share of close partners already tied on an earlier camp day (familiar vs new), (3) the share from another course. Models: movement + clock hour + wear time; the same plus setting (plenum, course block, meal, other daytime). Heard-only bins kept as their own level.
- **C. Which pairs synchronise, and does it last** (`eda2_pair_sync.py`). Per pair-day with ≥ 20 close minutes and ≥ 30 common usable minutes: lag-0 synchrony of tonic change, SCR ≥ 0.2 µS and HR (as in the first pass). (1) Determinants: same course, tied before that day, survey similarity (absolute difference of the trust and lust composites). (2) Consequence: does a pair-day's synchrony predict the pair being tied on any of the next three camp days, holding that day's close minutes, prior tie and same course fixed (logit; node bootstrap over people).
- **D. Onset synchrony in seconds** (`eda2_onset_sync.py`). Clock-certain device pairs only (both devices measured; median 0.09 s between units). SCR onsets ≥ 0.2 µS (and main rule as sensitivity). For pairs worn at the same time: share of A's onsets with a B onset within ±3 s, against circular shifts of B by 30–300 s within the overlap; excess ratio by close / heard / apart (5-min bin), and the lag profile at 1-s resolution from −20 to +20 s. Movement check: the same for accelerometer jerk peaks.
- **E. Heart-rate variability** (`eda2_hrv.py`). RMSSD per minute from `hr_beats` (`ok` and `plausible` beats, successive intervals within 20 % of each other, ≥ 30 intervals), only in still minutes (movement below the person-day median); log RMSSD, within person-day standardised and adjusted for HR and movement. Contrasts as in the first pass (setting, with clock hour and wear time) and as in A (social dose, familiar vs new). PPG-derived HRV is noisy: report coverage and an agreement check against export-sample beats where both exist.
- **G. Person profiles** (`eda2_person_profiles.py`, after A, C, E). Per person, separately on discovery and replication days: SCR social-dose slope (A), mean pair synchrony (C), mean HRV level and HRV social-dose slope (E), SCR rate variability. Split-half reliability (Spearman–Brown); only profiles with reliability ≥ 0.5 are related (Spearman, bootstrap) to the survey composites (trust, lust), the primary membrane measure (`D_academy_lenient`) and close-contact degree. Here the split is the reliability check, not the verdict rule.

## Not doing now

- B, room-entry events from beacons: 5-min bins make the entry moment fuzzy.
- F, acoustic loudness events: acoustics were null in-room in the first pass.
- H, unsupervised physiological states: open-ended and easy to over-read.
