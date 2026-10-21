# EDA ingest (Shimmer): signals, wear detection, SCR features

**Priority:** high
**Gate:** none
**Next:** build `social_energy.eda` (decoder, timeline, calibration, export ingest, per-second table, wear, SCR, person-minutes) test-first, then run it on the DSA 2026 delivery

**Goal:** `social_energy.eda` turns Shimmer SD-card logs and Shimmer Base CSV exports into canonical per-device tables (per-second signal, wear bouts, skin-conductance responses) in UTC, flagged not dropped, and resolves them to people through the spine.

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

## Open questions

- `[unknown: are the Shimmer default GSR resistors right for every device, or were any devices calibrated individually?]` The defaults reproduce the export exactly on the overlap checked so far.
- `[unknown: is PPG usable per device? The research team found it dead on one device]`
