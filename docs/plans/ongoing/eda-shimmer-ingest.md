# EDA ingest (Shimmer): signals, wear detection, SCR features

**Priority:** high
**Gate:** none
**Next:** EDA enters the exploratory tier (EDA around self-report presses, per-phase arousal, co-present wearers at minute level)

**Goal:** `social_energy.eda` turns Shimmer SD-card logs and Shimmer Base CSV exports into canonical per-device tables (per-second signal, wear bouts, skin-conductance responses) in UTC, flagged not dropped, and resolves them to people through the spine.

## Handoff

- **Branch:** `feat/eda-ingest`.
- **Done:** `social_energy.eda` with `sd` (decoder), `calibration`, `timeline` (tick cleaning, segments, end and start anchors, hidden whole-wrap gaps, drift fit), `export` (clock repaired modulo 512 s), `ingest` (per device and run; byte-level dedupe; SD over export per second), `features` (wear bouts, SCRs, artifact rules after Kleckner et al. 2018 plus fall and notch rules), `person` (person-minutes through the spine, consent and exclusions). `synth.eda` writes SD cards with the real traps; oracle, golden and CLI tests, each shown to fail under a mutation. `social-energy ingest-eda` writes `derived/eda/{files,seconds,scr,wear,person_minutes}.parquet` + `qa.json`. `study.yaml` carries the window, rotation and the measured clock offset of the imported copy.
- **Heart rate from PPG (branch `feat/eda-ppg-heart-rate`):** `eda.ppg` (zero-phase band-pass, Elgendi systolic peaks, plausible intervals, 10-s windows with an Orphanidou-style quality index plus an amplitude floor) and `eda.heart` (cards and exports one run at a time on the shared timeline; one source per device-window, SD first; device-minutes joinable onto `person_minutes`; agreement with the export's own heart rate; usability per device-day). `social-energy eda-heart-rate` writes `derived/eda/hr_*` beside the ingest's tables and touches nothing else; `ingest-eda` now replaces only its own files. Synthetic PPG with known beats and a dead sensor; oracle and unit tests, each shown to fail under a mutation. Run on DSA 2026: agreement with Shimmer's rate on the exports' own samples within a few bpm; PPG unusable on some device-days, not on any whole device. Numbers in the private note `dsa-2026/notes/eda-ppg-2026-10-21.md`. **Re-run `eda-heart-rate` after `feat/eda-clock-sync` merges**: SD heart rate is placed by the current timeline.
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
- Heart rate from the raw PPG on every day (decided 2026-10-21): beat detection after Elgendi et al. (2013), quality after Orphanidou et al. (2015) plus an amplitude floor (5 mV filtered SD) and a 30 % interval-change rule; flagged, never dropped; dependency-free (numpy FFT filter, no scipy or NeuroKit2). A separate table joined on device and minute rather than new `person_minutes` columns, so existing consumers are unchanged. The export's own heart rate stays in `seconds`/`person_minutes` as `hr_bpm`; it is no reference where the PPG is bad (it reports implausibly high rates on noise).
- Thresholds (decided 2026-10-21, ours rather than the research team's): SCR primary rule stays at 0.05 µS trough to peak, 0.5–5 s rise, with the artifact and notch rules; the sensitivity rule is the same detections filtered to amplitude ≥ 0.2 µS. The clean rate (~5.8/min) is above resting norms, but the rate does not follow motion much (stillest fifth of minutes ~4.5/min, most active ~6.9/min), analyses compare a person with their own baseline, and the 0.2 µS filter lands near resting norms (~3.3/min). Wear: contact 0.05 µS, bouts ≥ 300 s, gaps ≤ 60 s bridged, all unchanged.

## Open questions

- `[unknown: are the Shimmer default GSR resistors right for every device, or were any devices calibrated individually?]` The defaults reproduce the export exactly on every overlap checked.
- PPG usability per device-day is now measured (`hr_usability`): no device is dead throughout; whole device-days without a pulse occur on most devices. `[unknown: was the PPG clip attached on the device-days with no pulse, or were clips swapped between devices?]`
- `[unknown: are the PPG quality thresholds (template 0.86, amplitude 5 mV, interval change 30 %) acceptable to the research team?]`
- `[unknown: should cross-device timing be corrected per device-day?]` Device clocks sit up to ~15 s apart on SD-only days; fine for minute-level analyses, not for second-level coupling with beacon presses.
