# EDA ingest (Shimmer): signals, wear detection, SCR features

**Priority:** medium

**Goal:** `social_energy.eda` turns Shimmer exports into canonical per-device tables (samples, wear periods, skin-conductance responses) in UTC, flagged not dropped, resolved to people through the spine.

## Context

About 13–15 participants wore Shimmer devices (SH01–SH15) during daytime sessions from 15 to 28 Aug. The session log records many irregularities: devices failing to configure, early stops, restarts, a reused storage folder, a firmware update after the camp, very hot days. See [`docs/context/instruments/eda.md`](../../context/instruments/eda.md).

## Design / approach

- Follow the `add-data-source` skill: instrument doc → golden fixture → ingest → synth → oracle test.
- Wear detection from the signal (flat conductance / temperature), because participants took devices off without pressing anything.
- SCR detection with a standard decomposition (e.g. cvxEDA or a peak-based method); tonic level per window.
- Coupling with beacons: EDA windows around self-reports; synchrony between co-present wearers.

## Open questions

- `[unknown: export format (Consensys CSV? raw .dat?), channels enabled (GSR, PPG?), sampling rate]`
- `[unknown: device → person distribution plan per day]`
- `[unknown: do the exports carry absolute timestamps, and were device clocks synced?]`
