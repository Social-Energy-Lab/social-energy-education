# Beacons at the next field phase: what DSA 2026 taught us

**Priority:** medium

**Goal:** a checklist to agree with the beacon team before START-Stiftung or SUPER YOU, so that the losses and ambiguities met at DSA 2026 are designed out rather than repaired afterwards. Rules only; the evidence is in [`../../context/instruments/beacons.md`](../../context/instruments/beacons.md) and the private notes.

## Firmware and logging

- **Flush to flash often.** Records reach flash only when the RAM ring is nearly full, so a restart loses everything since the last readout. A periodic flush (or a much lower threshold) would turn hours of loss into minutes.
- **Log the reset reason** at boot (the SoC exposes it), and export it at the next readout, so that power cuts, brown-outs and crashes can be told apart.
- **Stamp the PC time when `Current Timer` is read**, not after the transfer, so that readout anchors are not minutes late.
- **Fix the logger ID formatting before deployment** and test it on IDs 48–57.
- **Freeze and record the build.** Note the firmware commit flashed on each tag, and log every control command sent during the camp (eco on or off, scan period, thresholds) with its time.

## Hardware and handling

- **Find what cuts power to a worn tag** (battery holder, contacts) and fix it before the next phase.
- **Check the motion sensor at handout.** A tag whose accelerometer fails at boot never enters eco mode, so it samples more densely than its neighbours.

## Field procedure

- **Read out more often**, ideally at fixed times every day, since every restart loses back to the last readout.
- **Log battery swaps, tags taken off, lost tags and the handover** as ID-only rows ([`structured-field-log.md`](structured-field-log.md)).
- **Settle the button instruction with the firmware.** The firmware has no cancel press, so either drop the instruction or give the cancel a distinct gesture the firmware can record.
- **Record an RSSI ground truth session** ([`rssi-ground-truth-session.md`](rssi-ground-truth-session.md)), including what a room tag reads through a wall.

## Next

- [ ] Walk through this list with the beacon team and the research team; turn the agreed points into a pre-deployment checklist in the study's folder.
