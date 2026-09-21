# Instrument: EDA / heart-rate wearables (Shimmer)

Status: **ingest not built yet.** The export format is still to be confirmed.

## What it measures

- Electrodermal activity (skin conductance). *Tonic* level (slow) and *phasic* responses (SCRs, seconds): sympathetic arousal.
- Heart rate / PPG, where the device was configured for it `[unknown: which channels were enabled]`.
- **Arousal is not resonance.** Excitement, stress, heat and movement all raise EDA. Interpretation needs context from self-reports, the programme and interviews.

## Deployment pattern (instrument level)

- Wrist or hand-worn devices with IDs like `SH01`…`SH15`, handed to a subset of consenting participants for daytime sessions. Devices are docked and configured at the start of each session and stopped at the end.
- The device-to-person mapping changes between sessions. It belongs in the spine (`eda:SH07` → `person:<id>`, with time intervals).
- Participants were told not to switch devices off. They could take a device off without pressing anything, or press its button to mark a longer pause. So **non-wear periods must be detected from the signal**, and button presses may mark pauses.

## Known traps (for the future ingest)

- Configuration failures: devices that never started, stopped early, or were restarted several times in one session.
- Firmware updates happened after the study. Check that export timestamps weren't shifted.
- Sessions stored under one reused session folder, with a subfolder per device. Don't assume one folder = one day.
- Heat affects EDA baselines (very hot days were noted).
- Device clocks must be checked against wall time. The docking/start time is the anchor `[unknown: does the export contain absolute UTC timestamps?]`.

## Planned canonical tables

- `eda_samples` (device, t, conductance µS, flags), possibly downsampled.
- `eda_wear` (device, start, end, worn: bool).
- `eda_scr` (device, t_onset, amplitude, rise time).

## Open questions

- `[unknown: export format and software (Consensys CSV? raw .dat?) and sampling rate]`
- `[unknown: where is the device-distribution plan (device → study ID per day)?]`
