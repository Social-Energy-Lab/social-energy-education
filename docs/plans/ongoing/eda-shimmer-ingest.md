# EDA ingest (Shimmer): signals, wear detection, SCR features

**Priority:** high
**Gate:** none
**Next:** research team reviews the wear and SCR thresholds and the artifact rules (open questions below); then EDA enters the exploratory tier (EDA around self-report presses, per-phase arousal, co-present wearers at minute level)

**Goal:** `social_energy.eda` turns Shimmer SD-card logs and Shimmer Base CSV exports into canonical per-device tables (per-second signal, wear bouts, skin-conductance responses) in UTC, flagged not dropped, and resolves them to people through the spine.

## Handoff

- **Branch:** `feat/eda-ingest`.
- **Done:** `social_energy.eda` with `sd` (decoder), `calibration`, `timeline` (tick cleaning, segments, end and start anchors, hidden whole-wrap gaps, drift fit), `export` (clock repaired modulo 512 s), `ingest` (per device and run; byte-level dedupe; SD over export per second), `features` (wear bouts, SCRs, artifact rules after Kleckner et al. 2018 plus fall and notch rules), `person` (person-minutes through the spine, consent and exclusions). `synth.eda` writes SD cards with the real traps; oracle, golden and CLI tests, each shown to fail under a mutation. `social-energy ingest-eda` writes `derived/eda/{files,seconds,scr,wear,person_minutes}.parquet` + `qa.json`. `study.yaml` carries the window, rotation and the measured clock offset of the imported copy.
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

## Open questions

- `[unknown: are the Shimmer default GSR resistors right for every device, or were any devices calibrated individually?]` The defaults reproduce the export exactly on every overlap checked.
- `[unknown: is PPG usable per device for heart rate on 19–28 Aug? The research team found it dead on one device]`
- `[unknown: does the research team accept the SCR rule (0.05 µS trough-to-peak, 0.5–5 s rise) and the artifact rules?]` On the real data clean SCRs come out at several per worn minute, above resting norms; amplitudes are kept so a stricter threshold is one filter away.
- `[unknown: should cross-device timing be corrected per device-day?]` Device clocks sit up to ~15 s apart on SD-only days; fine for minute-level analyses, not for second-level coupling with beacon presses.
