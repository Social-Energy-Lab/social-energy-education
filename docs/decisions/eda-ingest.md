# EDA ingest: sources, clocks and thresholds

**Date:** 2026-10-22 · **Status:** adopted

## Context

The DSA 2026 Shimmer delivery holds SD-card copies of all units and, for the first three days, Shimmer Base calibrated exports. Several units turned out to run slow while recording, by up to a few percent, which shifts minute-level joins by minutes late in the day. The method is documented in [`instruments/eda.md`](../context/instruments/eda.md); this records the choices behind it.

## Decision

- **The SD card is the source; the export is a second copy.** One source per device-second, SD first: the card keeps the raw ADC and the device's own clock. Conductance comes from the raw ADC with Shimmer's default resistors, which reproduce the calibrated export exactly.
- **Clocks are corrected per run from the cards' sync records.** The reference is the group of units that keep time (study config), and UTC is that group's clock. The export's "synchronised" clock is not a reference: it is the device clock plus one constant.
- **Box co-motion is an anchor, and a check.** It measures runs without records, but clears `clock_uncertain` only for units drifting under 1 s/h; a drifting unit's box-anchored clock keeps the flag (`clock_source: box`). Analyses run on all minutes, with clock-certain minutes as a sensitivity; second-level coupling uses certain minutes only.
- **Thresholds are ours.** Skin contact 0.05 µS (the valley of a bimodal distribution). SCR 0.05 µS trough to peak in 0.5–5 s with artifact and notch rules; sensitivity rule amplitude ≥ 0.2 µS. Every result is reported under both.
- **Heart rate is a separate table.** PPG beats (Elgendi), a quality index (Orphanidou) with an amplitude floor, flagged not dropped, on the same per-run clocks; joined on device and minute so existing consumers are unchanged.

## Rejected

- **The export's clock as ground truth.** It carries the device's drift.
- **Fixed per-unit rates as the correction.** Rates change within a day; they remain the flagged fallback only.
- **Waiting for the research team to set thresholds.** Within-person comparisons make the absolute SCR rate secondary, and the stricter rule bounds the choice.

## What this binds

Any EDA analysis reads `derived/eda/` through these flags (`ok`, `worn`, `artifact`, `clock_uncertain`, `clock_source`) and reports both SCR rules. Future field phases reuse the decoder and the clock model; the field protocol should add a shared timing event (box tap, clap at the recorder) and bench-test unit clocks before deployment.

## Revisit when

The research team answers the open EDA questions in [`questions-for-research-team.md`](../plans/ideas/questions-for-research-team.md), or a new field phase uses different hardware or firmware.
