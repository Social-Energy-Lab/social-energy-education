# Beacon dating: uptime periods from the implied boots, checked against partners

**Priority:** high — wrong boots move a record's time by minutes to hours, under every timing analysis
**Gate:** blocked:the beacon team's reboot list and answer on timer steps; the questions are drafted in the private notes (2026-11-04), not yet known to be sent (recheck 2026-11-21)
**Next:** compare with the beacon team's reboot list and their answer on timer steps when they arrive, then retire this plan

**Goal:** date beacon records from uptime periods that hold up under logger delays of hours, and tell "no data" from "no contact" in every tag-hour.

## Context

The revised processing guide and slides from the beacon team (kept in the private library) and our own checks show three gaps. The findings and counts are in the private notes.

- **The restart margin is the wrong tool.** We call a restart when uptime falls more than an hour behind the wall clock. Logger delays can pass that, so a very late stamp reads as a restart. A lasting step under an hour reads as nothing, and the whole period is then dated from a boot that no longer applies.
- **The earliest stamp needs one clean readout.** A period whose readouts were all late has no clean anchor and is dated late.
- **Our loss accounting only knows restarts.** A readout that vanished in a logger pause leaves a hole inside a period, which analyses can read as no contact.

An earlier check of ours matched each record to its nearest mirror and found little error. That check cannot see this: in a long stay both sides have a record at nearly every moment, so the nearest one is close whatever the error. Use pattern overlap, never nearest-record offsets, to judge dating.

## Approach

1. **Periods from the edge of the implied boots.** Stamps are only ever late, so the boot is the lower edge of the implied boots. A late stamp rises and comes back. A reboot or timer step lifts the edge for good. No margin is needed. A falling timer proves a reboot.
2. **Boots from partners.** A tag's on/off pattern with each partner, slid against the partner's own, overlaps best at the error in its boot. A period's partners are split in two, and the estimate counts only if the halves agree. A boot never moves later than the edge, since a stamp is never early.
3. **Settling the steps.** A step whose records carry on from the previous timer is either late stamps or a timer step. If partners land it on the previous boot it was late stamps and the periods join; if not, it is a `timer_step`.
4. **Coverage table** per tag and hour: recorded, erased by reboot, read out but not logged, not read out, no data. Pair-level estimate of hours recorded by neither side.

## Evidence

The beacon team's reboot count is not a target. Their validation is partly synthetic and their method is not available to us, so we compare afterwards and look into each disagreement. The fit is judged by:

- held-out partners: halves of a period's partners give the same answer;
- injected shifts on real periods are recovered;
- contact-timer continuity across each boundary;
- documented battery changes, whose times come from the field log rather than the logs;
- oracle tests on synthetic data with known boots, late stamps, steps and vanished readouts.

## Rollout

| Step | State |
|---|---|
| Toolkit functions, tests | ✅ |
| Ingest into a separate folder, `derived/beacons/` untouched | ✅ |
| Evidence checks, private note | ✅ |
| Coverage table | ✅ |
| Timing-sensitive analyses rerun, old and new compared, changes reported | ✅ |
| `ingest-beacons` fits boots when the study sets a window | ✅ |
| Replace `derived/beacons/`, rerun the rest (decided by Álvaro, 2026-11-04) | ✅ |
| Publish the site asset from the rerun (Álvaro, 2026-11-04) | ✅ |

## Open

- Analyses still read the fine bins of `derived/beacons/` as they were. Coverage reaches them only through the lost windows until each one chooses to use it.

## Out of scope

- Self-exclusion for ambiguous IDs: mostly single status lines, little to gain, later.
- Recovering fake records from their bytes: very few lines.
- A per-tag drift rate: the differences are small next to boot errors.
