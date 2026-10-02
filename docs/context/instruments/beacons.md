# Instrument: BLE proximity beacons (nRF54L15 tags)

Wearable name-tag beacons that log who was near whom, which room people were in, and when a wearer pressed the self-report button. Firmware, base station and logger are by Tobias Hofbaur: <https://github.com/thofbaur/network-beacon_NRF54L15>. That repo has no licence, so we **reimplement from this spec and never copy code**. Toolkit: `social_energy.beacons`.

## System

```
tags (worn / fixed in rooms) ──BLE──► base station (nRF54L15 DK) ──UART──► dsa_logger.py ──► .log text files
```

- **Person tags** advertise as `DSA`. **Location tags** advertise as `DSL`, and the firmware uses a looser threshold for them. Configuration commands come from a control board as `DSZ`.
- Every tag scans for known tags (accept-list filter) and stores a **contact record** `(other_id, uptime_s, rssi)` for each advertisement heard at or above the RSSI threshold.
- A readout happens when the base station connects to a tag. The tag exports everything it has stored and deletes what the base acknowledged. Since 2026-08-12, commit happens only after a base acknowledgement.
- Tag IDs are one byte, assigned from BLE addresses in the firmware's `radio_ids.c`. The mapping from ID to person or room is study data and lives in the spine.

## Measurement parameters (firmware defaults at the time of writing)

| Parameter | Value | Consequence |
|---|---|---|
| RSSI threshold, person tags | −80 dBm | only "close" contacts stored, roughly a few metres; weaker signals never recorded |
| RSSI threshold, location tags | −100 dBm | room presence is permissive, but the signal passes walls very poorly (firmware team, 2026-10-01): several room tags heard at once points to an open space, a corridor or outdoors rather than to a neighbouring room |
| Scan window / interval (normal) | 120 ms every 7 s | each nearby tag sampled at most once per ~7 s; one advertisement per window, occasionally two |
| Advertising interval | 90–120 ms | |
| Eco mode (after 30 min without motion, if enabled) | 100 ms scan burst every 300 s (`CONFIG_DSA_ECO_SCAN_INTERVAL_MS`; runtime-adjustable as `P_ECO_SCAN_PERIOD_S`). Off by default (`CONFIG_DSA_MOTION_DEFAULT_ACTIVE=n`), switched on by control command. It needs the accelerometer: a tag whose status byte has bit 5 set never enters eco mode in that boot and keeps scanning every 7 s | the tag **still advertises normally**, so others keep hearing it; only its own scanning drops. A still tag's contacts become one-sided: it is heard but barely hears (firmware team, 2026-10-01) |
| TX power | 0 dBm | |
| Time resolution | 1 s (uptime seconds, 24-bit in records; wraps after ~194 days) | |
| Self-report | **one** event per press, once the button has been held for 3 s | read from the v1.0.0 source (`self_report.c`): the 3 s timer starts on press and is cancelled on release, and it does not repeat while held. A press shorter than 3 s leaves nothing; a press held for minutes leaves one event; the event's time is about 3 s after the press began. No cooldown, so several events mean several separate presses, which fits the 4–9 s spacing seen in runs (3 s hold plus release and press again). A long dense run is something pressing the tag over and over (a tag in a bag) and is accidental. There is no firmware notion of a cancelling second press, so an instructed cancel press is an ordinary second event |

Per-study deviations (e.g. when eco mode was switched on or off) belong in `studies/<id>/study.yaml`.

## Log format (`dsa_logger.py` output)

One line per decoded record: `<PC local time>,ID: <beacon>,<record>`

```
2026-08-14 12:00:00,ID: 37,Status: 0                        radio/storage fault bits (1 = fault)
2026-08-14 12:00:00,ID: 37,Current Timer: 7200              tag uptime (s) at readout → clock reference
2026-08-14 12:00:00,ID: 37,Contact Count: 3
2026-08-14 12:00:00,ID: 37,Voltage: 3100                    mV
2026-08-14 12:00:00,ID: 37,Self-report time: 7000           uptime (s) of the press
2026-08-14 12:00:00,ID: 37,Eco Session Enter: 100, Leave: 400
2026-08-14 12:00:00,ID: 37,ID2: 28, Timer: 6000, RSSI: -73  tag 37 heard tag 28
2026-08-14 12:00:05,ID: 37,Transfer complete. Disconnecting (other status text: ignored, counted)
```

- **Event time** = readout PC time − (Current Timer − record uptime).
- Status byte bits: 0 scan error · 1 NUS (readout) error · 2 storage full (**data loss**) · 3 parameter save error · 4 storage error · 5 motion sensor unavailable · 6 motion probe timeout (only meaningful with bit 5).
- PC time is the logging laptop's local wall clock, with no timezone in the file.

## Known traps (each is a flag or a test in `social_energy.beacons`)

| Trap | What happens | Handling |
|---|---|---|
| **Logger ID bug** (fixed upstream in commit `2e1f52d`, 2026-08-15 20:17 local) | Before the fix, the readout header printed IDs 48–57 as the characters `0`–`9`, colliding with real IDs 0–9. Contact `ID2` values were unaffected. | `ambiguous_id_cutoff`. Repaired by matching clock anchors with unambiguous readouts; otherwise `id_status = "ambiguous"`. |
| **Reboots** | Uptime restarts at 0. A readout after a reboot can carry records from the previous boot, which must be dated against the previous boot's anchor. | Uptime drops inside a readout mark boot segments. The previous boot is resolved with the previous readout's anchor (`pre_reboot`); older boots get `t = null`. |
| **Resends** | An interrupted transfer can re-export already acknowledged records (checkpointing is deferred to save flash writes). | `duplicate`: same record already seen in an earlier readout. |
| **Corrupt trailing records** | Occasional garbage records with absurd timers or IDs. | `implausible_time` (outside the study window or after the readout); out-of-roster IDs don't resolve in the spine. |
| **Direction** | A→B and B→A are separate observations; asymmetry is informative (body shadowing, eco mode, a wiped or dead tag). | We keep `beacon` (observer) and `observed`; the upstream tables keep it as `ID1`/`ID2`. |
| **Eco-mode missingness** | Stillness → sparse sampling. | `eco_sessions` table; analyses must model it. |
| **Tags not worn** | Lost, lying in a box, taken off for sport, battery out. The tag keeps recording where it lies. | Spine exclusion windows (from field notes). |
| **Tag swaps** | A replacement tag carries a different ID for the same person. | Spine assignments over time. |
| **Logger gaps** | Logger failed to write for some minutes; records that stayed on the tag appear in a later readout. | Covered by the clock reference. Records deleted before a later readout are lost silently. |
| **Restarts wipe unread data** | Records go to a RAM ring first and move to flash only when the ring is nearly full: contacts at 23,700 of 24,000, self-reports at 254 of 256, eco sessions at 63 of 64 (`dsa.conf`). A readout drains flash and RAM. So between two readouts nearly everything sits in RAM, and a restart loses it, and uptime starts again from zero (firmware team, 2026-10-01; v1.0.0 source). Presses practically never reach flash before a readout. The firmware records no reset reason and runs no watchdog. Battery swaps are restarts. At DSA 2026 restarts were frequent and mostly happened while tags were worn, and readouts came only a few times a day, so a lost window often spans hours. Nothing in `Output/` shows the loss. | Detect a restart from the `Current Timer` anchors: uptime falls behind elapsed wall time by more than an hour. The lost window runs from the last readout that delivered records to the restart. It is close to exact unless more than about 23,700 contacts piled up since that readout. Inside such a window the tag stops appearing as the observer while its partners keep logging it, which confirms the loss. Co-presence counted from either side survives one wiped tag; presses on a wiped tag and two-sided measures do not. Motion-sensor fault bits (5, 6) in the status byte appear after genuine power-cycles, not after debugger resets (firmware `DECISIONS.md`, 2026-08-11), so restarts that come with them were probably power interruptions `[inferred]`. `[unknown: what interrupts power on a worn tag: battery contact, battery holder, or something else?]` |
| **Headerless readouts** | A readout can reach the log without its `Status`/`Current Timer`/`Count`/`Voltage` lines: a block of the tag's contacts and presses, stamped with the same PC second as neighbouring blocks. It still drained the tag. Conversely, a lone `Status` line is a connection that failed before any transfer and drained nothing. | Our ingest cannot date such a block from its own anchor and leaves it unplaced; `Output/` dates it from a neighbouring anchor, which after a restart can be the wrong boot. A lost window starts at the last delivery of records (`read_deliveries`), not only at the last anchor. |
| **Late readout stamps** | Within one power cycle, readout PC time minus uptime should be constant. It is not: it sits minutes above its minimum, more after long transfers, and never below it. Records dated from a late anchor are dated late by the same amount. | Date every record as (the power cycle's earliest implied start + uptime). On DSA 2026 this halves the typical offset between mirrored records (A hears B vs B hears A). Tag clocks themselves are accurate to seconds against their partners. Mirrored records minutes apart are mostly sparse sampling in eco mode, not clock error. `[unknown: is the PC time on the Current Timer line taken after the transfer rather than when the timer was read?]` |

## Excluding a tag excludes half of it

Proximity is recorded from both sides, so a tag's own records are only half the data about whoever wore it. Every contact it made is mirrored in the partner tag's records, and those rows sit in the partner's data, not in its own. In one DSA 2026 day, a single tag was the observer in about 26,000 rows and the observed party in about the same number, logged by more than a hundred other tags.

So an exclusion window on a tag does **not** remove that person from the dataset. Their whereabouts and their company stay reconstructible from everyone else's records. This matters most in exactly the case where exclusion is not a matter of data quality but of consent — a tag worn by someone who never agreed to take part, a withdrawal, a window in which someone asked not to be recorded.

`Spine.flag_excluded` must therefore be called **once per side** for contacts, with `device_col="beacon"` and again with `device_col="observed"`, writing to different output columns. Its docstring says so, and an analysis that filters only the observer side will look correct and silently keep the person in. When the reason for an exclusion is consent rather than quality, treat dropping both sides as the requirement, not as good practice.

## Canonical tables (`ingest_logs`)

- `readouts`: one row per connection: `beacon`, `header_id`, `id_status`, `pc_time`, `current_timer`, `anchor`, `reboot_before`, voltage, status byte, provenance.
- `contacts`: `beacon`, `observed`, `rssi`, `t` (UTC), `uptime_s`, flags `pre_reboot · reference_after · implausible_time · duplicate · id_ambiguous · ok`, provenance.
- `self_reports`: `beacon`, `t`, same flags.
- `eco_sessions`: `beacon`, `t_enter`, `t_leave`, same flags.
- `qa`: counts accounting for every input line.

## The upstream `Output/` tables

The `Output/` folder that arrives with a delivery is produced by the upstream repo's own `postprocessing.py` (`Network_Log+Postprocessing/`). Its defaults and column headers match the delivered files exactly: daily `contacts_YYYYMMDD.csv` (`ID1,ID2,RSSI,Contact Local Time`), `self_reports.csv` (`ID,Local Time`), `eco_sessions.csv` (`ID,Enter Local Time,Exit Local Time`), plus `beacon_summary.csv`, `measurements.csv`, `current_issues.csv`, `sanity_findings.csv` and `transfer_mislabel.md`. Times are local wall clock, to the second.

How it resolves uptime to wall clock, in our words:

- Each readout's `Current Timer` line is an anchor. An event is dated by offsetting from the nearest anchor for that tag, preferring a preceding one and falling back to a following one (counted, not dropped).
- If that lands implausibly in the future (tolerance 600 s past the log line), it **retries against the previous boot's anchor**, but only when the record's timer exceeds every timer already seen in that older boot. This is its reboot-backlog path: records stored before a reboot and exported after it.
- Records it still cannot place, or whose ID/RSSI falls outside the fielded ranges (IDs 1–170 plus 252–254, RSSI −110..−10), are **skipped** and counted in `sanity_findings.csv`.
- Direction survives in the contact tables: `ID1` is the tag that heard, `ID2` the tag it heard (checked on DSA 2026: a tag whose memory was wiped stops appearing as `ID1` while others keep logging it as `ID2`). There is no readout table, no boot context, no per-record flags and no `Status` byte, so storage-full loss is invisible in it.

Treat it as an independent implementation to check ours against, not as ground truth. `[unknown: at which commit was the delivered Output/ produced?]`

## Open questions

- `[unknown: which firmware commit was flashed on each tag at camp start, and exactly when did runtime settings change?]` The firmware defaults are readable from the upstream repo (`dsa.conf`, `dsa_runtime.conf`, `shared/common_include.h`) and its history dates the production values to 2026-08-08..15. What the repo cannot say is which build went on which tag and which control commands were sent during the camp.
- `[unknown: what is room 0.08 (location tag 115)?]` Its label is `[unknown]` in `studies/dsa-2026/locations.yaml`.

Settled since (2026-10-02, firmware team and the v1.0.0 release):

- The `_cleaned` logs are the 13–15 Aug logs with the logger ID bug undone by hand: the firmware team split the readouts printed as `0`–`9` into real 0–9 and 48–57, mainly by comparing each readout's implied start (zero time), with restarts making some cases a matter of deduction from later readouts. The bug affected only the readout header (`ID1`), never `ID2`. The uncleaned originals exist and were delivered separately. Our own repair (anchor matching) can be checked against their split.
- The full source of the system as fielded is the repo's `v1.0.0` release. Self-report timing, flash flushing, eco scanning and the status byte above are read from it.

Settled since (2026-09-20):

- Location tags **do** scan and store contacts, and they were read out. They use the looser threshold so they hear more tags; the records are in the delivery. Mapping location-tag records to rooms is described in `studies/dsa-2026/`.
- No RSSI ↔ distance/orientation ground-truth session was recorded for this phase. The threshold was deliberately set low so that everything was stored and **what counts as an interaction is a preprocessing decision**, not a firmware one. A calibration session is planned for a future field phase: `docs/plans/ideas/rssi-ground-truth-session.md`.
