# EDA ingest (Shimmer): signals, wear detection, SCR features

**Priority:** high
**Gate:** none
**Next:** re-run the downstream EDA work on the clock-corrected tables (exploratory EDA, PR #19; `social-energy eda-heart-rate`, PR #21), then EDA enters the exploratory tier

**Goal:** `social_energy.eda` turns Shimmer SD-card logs and Shimmer Base CSV exports into canonical per-device tables (per-second signal, wear bouts, skin-conductance responses) in UTC, flagged not dropped, and resolves them to people through the spine.

## Handoff

- **Branch:** `feat/eda-ingest`.
- **Done:** `social_energy.eda` with `sd` (decoder), `calibration`, `timeline` (tick cleaning, segments, end and start anchors, hidden whole-wrap gaps, drift fit), `export` (clock repaired modulo 512 s), `ingest` (per device and run; byte-level dedupe; SD over export per second), `features` (wear bouts, SCRs, artifact rules after Kleckner et al. 2018 plus fall and notch rules), `person` (person-minutes through the spine, consent and exclusions). `synth.eda` writes SD cards with the real traps; oracle, golden and CLI tests, each shown to fail under a mutation. `social-energy ingest-eda` writes `derived/eda/{files,seconds,scr,wear,person_minutes}.parquet` + `qa.json`. `study.yaml` carries the window, rotation and the measured clock offset of the imported copy.
- **Clock correction (branch `feat/eda-clock-sync`, 2026-10-21):** `eda.sd` decodes the header's device clock and the sync records in the block slots; `eda.timeline` places chunks by the header (modification times are a flagged fallback and a counted check); `eda.clock` builds a per-run clock model (reference curves per day from the reference units' records, a robust piecewise-linear error per slave and master run, the unit's rate as a flagged fallback); exports are matched to their card and corrected through its model; exports without a clock are placed from their session's corrected start. New `clock_uncertain` on seconds, scr, wear and person-minutes; `clock` and `comotion` tables; the co-motion residuals in `qa.json`. Forensics, residuals and counts: private notes `dsa-2026/notes/eda-clocks-and-facts-2026-10-21.md` and `eda-clock-sync-2026-10-21.md`.
- **Box anchor (branch `feat/eda-clock-box-anchor`, 2026-10-22):** `eda.box` finds each run's off-skin stretches next to its wear (the evening box, and the morning one where there is one), cross-correlates every overlapping pair of units' accelerometer jerk (a wide smoothed search, then a sharp narrow one), solves the units' residuals jointly per group with closed-triangle checks, zeroed on the measured reference units, and hands the anchors to `eda.clock`: fallback runs follow their anchors and the start re-set (`kind: box`), fitted runs extend through them, an ambiguous master takes the curve they agree with, measured runs the box contradicts are flagged. A box-only clock is trusted only for units drifting under 1 s/h: the leave-one-out validation (`box_loo`) shows drifting units stray by seconds between the re-set and the box. New graded `clock_source` (`sync`, `box`, `rate`) on seconds, scr, wear and person-minutes beside `clock_uncertain`; `box`, `box_pairs`, `box_loo` tables. Counts and validation: private note `dsa-2026/notes/eda-clock-box-anchor-2026-10-22.md`.
- **Run on DSA 2026 (2026-10-21):** the delivery's assignment table is in the local spine (`spine/add_eda_from_assignment.py`, with exclusions from its field comments). Per-day recording and wear spans agree with the field notes' start and stop times. Counts and checks are in the private note `dsa-2026/notes/eda-ingest-2026-10-21.md`.

## Context

The DSA 2026 delivery arrived on 2026-10-20: byte copies of all 15 SD cards plus the Shimmer Base export for the first three days, with the research team's README, a device-assignment table and day notes. Format, timing and traps are in [`docs/context/instruments/eda.md`](../../context/instruments/eda.md).

## Design / approach

- `eda.sd`: decode the binary SD format (fixed header, then 503-byte blocks of filler plus 38 records of 13 bytes).
- `eda.timeline`: drop all-zero and out-of-sequence records (flagged), follow the 24-bit tick counter across files, split runs at gaps the counter cannot bridge, place each segment by a robust fit to the file modification times of complete files only.
- `eda.calibration`: Shimmer's GSR conversion (feedback resistor per auto-range, 12-bit ADC, 8 kΩ floor); accelerometer counts to g.
- `eda.export`: Shimmer Base calibrated CSVs; remove the spurious whole 512-second periods from the export clock; drop byte-identical session duplicates.
- `eda.ingest`: per-second canonical table (`device`, `t`, `source`, conductance, motion, PPG, flags, `ok`), one source per device-second (SD first), a files table and a QA dict that accounts for every record.
- `eda.features`: wear bouts from skin contact, SCRs by trough-to-peak detection, a person-minute table resolved through the spine with consent and exclusions.
- Synthetic SD cards in `social_energy.synth` with ground truth for the oracle test.

## Decided

- Conductance from the raw ADC with Shimmer's default resistors: reproduces the calibrated export exactly wherever both exist.
- One source per device-second: the SD card over the export (it keeps the device's own placement and the raw values).
- Contact threshold 0.05 µS: the real conductance distribution is bimodal with its valley there.
- Heart rate only where the export carries it (15–17 Aug); no PPG beat detection yet.
- Cross-device timing is corrected per run (decided 2026-10-21): several units ran slow by up to a few percent, which shifts minute-level joins by minutes late in the day. The sync records on the cards are the measurement; the reference is the group of units that keep time (`study.yaml`), and UTC is that group's clock (`reference_to_utc_s: 0`), bounded by external events to a few seconds `[inferred]`. Runs the records cannot fit get the unit's typical rate and `clock_uncertain`; analysts filter on it for second-level work. The export's own "synchronised" clock is not used as a reference: it is the device clock plus one constant.
- Box co-motion is a clock anchor, not only a check (decided 2026-10-22): it measures runs without sync records against the units with them, to a few hundredths of a second at the box. It clears `clock_uncertain` only where one anchor can carry the day (units drifting under 1 s/h); for drifting units it improves the correction, marked `clock_source: box`, and the flag stays. `clock_uncertain` keeps its meaning, so existing filters are unchanged.
- Thresholds (decided 2026-10-21, ours rather than the research team's): SCR primary rule stays at 0.05 µS trough to peak, 0.5–5 s rise, with the artifact and notch rules; the sensitivity rule is the same detections filtered to amplitude ≥ 0.2 µS. The clean rate (~5.8/min) is above resting norms, but the rate does not follow motion much (stillest fifth of minutes ~4.5/min, most active ~6.9/min), analyses compare a person with their own baseline, and the 0.2 µS filter lands near resting norms (~3.3/min). Wear: contact 0.05 µS, bouts ≥ 300 s, gaps ≤ 60 s bridged, all unchanged.

## Open questions

- `[unknown: are the Shimmer default GSR resistors right for every device, or were any devices calibrated individually?]` The defaults reproduce the export exactly on every overlap checked.
- `[unknown: is PPG usable per device for heart rate on 19–28 Aug? The research team found it dead on one device]`
- `[unknown: was the laptop that activated the units each morning on network time?]` It fixes the reference group's error against UTC; until then EDA × beacon joins below a few seconds are not justified.
- `[unknown: which unit was the sync master on 16 Aug?]` That day's master is not flagged in any header, so its own data gets the fallback.
- `[unknown: can the research team re-export the two clockless exports from the Shimmer database?]` They are placed from their session's start for now (flagged).
