# DSA 2026: first analyses of co-presence, self-reports and beacon health

**Priority:** high
**Gate:** none
**Next:** repair the logger ID bug against power cycles instead of single anchors (late stamps defeat the 5 s match), then compare with the beacon team's hand split once the original logs are in

**Goal:** first descriptive results from the beacon data for the research team, and a clear account of every setting and instrument behaviour they rest on, so that each number can be traced and each choice revisited.

## Handoff

- **Branch:** `main`
- **Done:** three analyses under `studies/dsa-2026/analyses/` (`copresence_by_phase.py`, `self_report_context.py`, `beacon_diagnostics.py`); firmware answers from the beacon team written into [`../../context/instruments/beacons.md`](../../context/instruments/beacons.md); a meeting deck and two question docs built from the outputs (kept outside the repo). Numbers are in the private half: `dsa-2026/notes/beacon-analyses-2026-10-01.md`.
- **Waiting elsewhere (not on Next):** sign-off on the analysis choices below by the research team; firmware documentation from the beacon team, which decides the previous-boot rule.
- **Consent:** the beacon-consent ruling of 2026-09-22 was applied to the spine on 2026-10-01, and every analysis was rerun with it.
- **Handoff:** run `copresence_by_phase.py build` once, then `report`, `self_report_context.py` and `beacon_diagnostics.py` in any order (`uv run --extra analysis python …`). All read through the spine and write only under `$SOCIAL_ENERGY_DATA/dsa-2026/derived/analyses/`.

## Settings in use

Each is a choice, not a fact, until the research team signs it off. They are named constants at the top of the scripts.

| Setting | Current value | Why | Status |
|---|---|---|---|
| Contact source | upstream `Output/` tables | our full ingest of contacts does not fit in memory for the whole camp yet | until our ingest streams per day; `Output/` keeps resent copies and late stamps |
| Press source | our ingest, `ok` records | dated from the power cycle start; resent copies flagged `duplicate`, which `Output/` counts twice | rule, validated 2026-10-02 |
| Window | tag deployment on 13 Aug to the handover on 29 Aug 09:00 | after the handover tags lay together on benches | the handover window is not yet a spine exclusion |
| Comparison days | 14–23 Aug | arrival day is atypical; restarts and battery fade weigh more late | `[inferred]` |
| Exclusions | applied to both sides of every contact | a tag's partners hold half the data about its wearer | rule |
| Who | participants with the module's consent; staff later, separately | asked by the research team: separate first, then relate | agreed 2026-10-01 |
| Close | strongest reading in a 5-minute bin at −65 dBm or stronger | the firmware threshold (−80) ties nearly everyone every day | `[inferred]`, uncalibrated |
| Tie | close for at least one hour in one camp day (07:30–07:30) | a plausible size of a day's circle; results hold at −60/30 min and −70/60 min | `[inferred]` |
| Parts of the day | clock blocks from 07:30, 12:30, 14:00, 18:30, 19:30, 22:30, 02:00 | most programme events have no end time | `[inferred]` |
| Cross-course baseline | share expected if people mixed at random, from course sizes among those present | a raw share means nothing without it | rule |
| Accidental presses | a chain of presses each under 20 s apart, lasting 60 s or holding 8 presses | one event per press of at least 3 s, no cooldown (v1.0.0 source); a long run is a tag pressed over and over in a bag | thresholds `[inferred]` |
| One press | presses under 60 s apart are one episode | the firmware does not repeat a held press, so two events are two presses; merging them treats a quick re-press, or a cancel press, as one moment | `[inferred]`; revisit with the cancel-press decision |
| Cancel press | not applied; folded into the episode merge | participants were told a second press cancels a mistaken one; the firmware has no such notion, so a cancel pair is two ordinary events seconds apart | research-team decision, now sharper: count a quick pair as one moment, as none, or as two |
| Lost presses | presses held in RAM at a restart are accepted as lost; press exposure leaves each tag's lost windows out | they cannot be recovered from any other tag | agreed 2026-10-01 |
| A tie lasts | the pair is tied again on any of the next three days | separates a one-off encounter from repeated time together | `[inferred]` |
| Room placement | the room tag heard most often in the bin, at least two hits | room tags barely pass walls | a stronger cut is open with the beacon team |

## What the data showed (no numbers here)

- **Courses form the day's circles; the programme breaks them.** Ties cross courses far less than random mixing would give; the excursion and rotation day push cross-course and brand-new ties up sharply. Evening and late time mixes courses more than course time.
- **Presses happen in company**, with more people close and less time alone than ordinarily, in every part of the day, and a hint that companions press together.
- **Tags restart often, mostly while worn.** A restart loses what was held in RAM since the last readout (part of the data is already in flash). Readouts came roughly twice a day per tag, so a lost window often spans hours. Detection and the lost window come from the clock anchors (see the instrument doc).
- **Redundancy recovers most co-presence.** While one tag is wiped its partners still log it, so co-presence counted from either side survives; only pair-time with both tags wiped is gone. Presses and two-sided measures cannot be recovered.
- **Readout timestamps run late; tag clocks do not.** The PC stamp on a readout is minutes late, more after long transfers; dating each record from its power cycle's earliest anchor halves the typical mirrored offset. Per-tag clock bias against partners is seconds. Apparent offsets of minutes between mirrored records come from sparse sampling in eco mode, not from clocks.
- **Battery voltage fades slowly** and matters less than restarts.
- **The mixing on special days rarely sticks.** Ties first made on the excursion or rotation day come back on the following days far less often than ties made on ordinary days. This measures repeated time together, not acquaintance.

## Next steps

- [x] Ingest: date records as (power cycle's earliest implied start + uptime); previous-boot records must precede the restart (else `implausible_time`); headerless readouts are their own readouts; presses compared against `Output/` and switched to our ingest.
- [ ] Ingest: repair the logger ID bug against power cycles; check against the beacon team's hand split.
- [ ] Ingest contacts per day for the whole camp, then move co-presence to our ingest.
- [x] Press rates: remove each tag's lost windows from the exposure, since a press on a wiped tag cannot be recovered.
- [x] Flag lost windows per tag in a table the analyses can join (`lost_windows.parquet`), so one-sided measures can be restricted to unaffected time.
- [x] Rerun everything once the beacon-consent ruling is in the spine.
- [x] Check whether ties first made on the excursion or rotation day persist on later days.
- [x] Lost windows start at the last readout that delivered records, including readouts that arrived without their header; validated against the tag's own rows versus its partners' (`read_deliveries`).
- [ ] Persistence with shorter contacts, and self-reports between people who first met on a special day.
- [x] Move the instrument rules into the toolkit with hand-derived tests: power cycles, restarts and lost windows (`social_energy.beacons.cycles`), press episodes and accidental runs (`social_energy.beacons.presses`). The analyses call them; outputs unchanged on the real data.
- [ ] End-to-end run of the three analyses on `social_energy.synth` in CI (`add-analysis` skill). Blocked on shape: they read the upstream `Output/` tables, which the generator does not write; either the generator writes them or the analyses switch to our ingest after the dating fix.

## Open questions

Questions that only matter for the next field phase live in [`../ideas/next-field-phase-beacon-practice.md`](../ideas/next-field-phase-beacon-practice.md).


- `[unknown: is the PC time on a readout stamped after the transfer rather than when the timer was read?]`
- `[unknown: which RSSI from a room tag means "inside this room"?]`
- `[unknown: was the eco scan period changed from its 300 s default by control command during DSA 2026?]`
