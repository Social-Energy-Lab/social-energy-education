# RSSI ↔ distance/orientation calibration for the nRF54L15 tags

**Priority:** low

**Goal:** know what −60/−70/−80 dBm mean in metres and body orientation for these tags when worn as name tags, so that "close contact" thresholds are grounded.

## Context

The firmware stores contacts at ≥ −80 dBm (person tags) and ≥ −100 dBm (location tags). The field log notes −90 dBm at about one tennis court away from an outdoor tag. The study-design notes planned SocioPatterns-style ground-truth sessions (fixed distances 0.1/1/2 m × face-to-face / side-by-side / back-to-back).

## Design / approach

- A short, staged recording with volunteers (not participants), plus a small analysis script in the toolkit that fits a path-loss model and reports threshold → distance tables.
- The result goes into `docs/context/instruments/beacons.md` and informs `presence` thresholds.

## Open questions

- `[unknown: was any ground-truth session recorded at DSA 2026?]`
