# Beacons at the next field phase: what DSA 2026 taught us

**Priority:** medium

**Goal:** a checklist to agree with the beacon team before START-Stiftung or SUPER YOU, so that the losses and ambiguities met at DSA 2026 are designed out rather than repaired afterwards. Rules only; the evidence is in [`../../context/instruments/beacons.md`](../../context/instruments/beacons.md) and the private notes.

The hypotheses planned for those phases, and which of the points below each one depends on, are in [`next-phase-preregistration.md`](next-phase-preregistration.md) (section "Instrument and procedure changes that would help").

## Firmware and logging

- **Flush to flash often.** Records reach flash only when the RAM ring is nearly full, so a restart loses everything since the last readout. A periodic flush (or a much lower threshold) would turn hours of loss into minutes.
- **Stop clearing contact flash at boot.** A firmware bug wipes it, so a restart loses contacts that had already reached flash. This and the flush above decide how much each restart costs.
- **Log the reset reason** at boot (the SoC exposes it), and export it at the next readout, so that power cuts, brown-outs and crashes can be told apart.
- **Stamp the PC time when `Current Timer` is read**, not after the transfer, so that readout anchors are not minutes late.
- **Keep the logger reading while it works.** No postprocessing in the capture loop. A pause there lost whole readouts for good, because the base had already confirmed them. Do it offline, or in a separate process.
- **Confirm only what the PC has stored,** or add flow control on the serial line, so that a stalled logger delays data rather than losing it.
- **Give the logger a heartbeat,** so that an outage can be told from a quiet spell, and have it reject a data message whose records are incomplete.
- **Fix the logger ID formatting before deployment** and test it on IDs 48–57.
- **Freeze and record the build.** Note the firmware commit flashed on each tag, and log every control command sent during the camp (eco on or off, scan period, thresholds) with its time.

## Hardware and handling

- **Find what cuts power to a worn tag** (battery holder, contacts) and fix it before the next phase.
- **Check the motion sensor at handout.** A tag whose accelerometer fails at boot never enters eco mode, so it samples more densely than its neighbours.

## Field procedure

- **Check the logger every evening:** its delay and the readouts per tag. A growing delay is visible while it can still be fixed.
- **Read out more often**, ideally at fixed times every day, since every restart loses back to the last readout.
- **Log battery swaps, tags taken off, lost tags and the handover** as ID-only rows ([`structured-field-log.md`](structured-field-log.md)).
- **Settle the button instruction with the firmware.** The firmware has no cancel press, so either drop the instruction or give the cancel a distinct gesture the firmware can record.
- **Record an RSSI ground truth session** ([`rssi-ground-truth-session.md`](rssi-ground-truth-session.md)), including what a room tag reads through a wall.

## Next

- [ ] Walk through this list with the beacon team and the research team; turn the agreed points into a pre-deployment checklist in the study's folder.
