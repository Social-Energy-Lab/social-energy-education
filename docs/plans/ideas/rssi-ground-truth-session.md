# RSSI ground truth: a calibration session for a future field phase

**Priority:** medium

**Goal:** record a short, deliberate session in which known distances and orientations between two tags are held for known times, so that RSSI can be interpreted rather than only thresholded.

## Why

Nothing of this kind was recorded for DSA 2026 (confirmed 2026-09-20). The firmware threshold was set deliberately low so that everything was stored and **what counts as an interaction stays a preprocessing decision**. That decision is currently made on RSSI values whose relation to distance for this hardware, with a tag worn on a body, is unmeasured. Body shadowing, tag orientation and the wearer's posture all move RSSI by more than the differences we would like to read as "closer".

Without calibration we can still do rank-order and threshold-sweep work: pick a cut, show the results are stable across cuts. With it we could state a distance interpretation and defend one cut.

## Sketch

- Two person tags plus one location tag, normal production firmware and settings.
- Hold a grid of conditions for ~2 minutes each, logged by wall clock in a written protocol: distances (0.5, 1, 2, 3, 5 m), orientations (face to face, back to back, side by side, one tag turned away), and at least one body-blocked condition.
- Repeat once in a different room to get a sense of the environment's contribution.
- Add a static overnight pair at a fixed distance, to separate drift from movement.
- The output is a small table of (condition → RSSI distribution). It belongs with the study's data, not in this repo; the protocol and the derived summary can be public.

## Open

- Whether to run it before or during the next phase (before is cleaner, during captures the real rooms).
- Whether a ground truth from one phase transfers to another (different rooms, possibly different tag revisions). `[inferred]` it transfers for orientation/body effects and not for absolute room propagation.
