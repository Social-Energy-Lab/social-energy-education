# Instrument: EDA / heart-rate wearables (Shimmer3R GSR+)

Status: **ingest built** (`social_energy.eda`, `social-energy ingest-eda`). Reads SD-card logs and Shimmer Base calibrated CSV exports, and corrects device clocks from the cards' sync records.

## What it measures

- Electrodermal activity (skin conductance) from two finger electrodes. *Tonic* level (slow) and *phasic* responses (SCRs, seconds): sympathetic arousal.
- PPG (optical pulse), from which heart rate and inter-beat intervals can be derived. Signal quality varies by device and wear; check it before relying on heart rate.
- A 3-axis accelerometer in the wrist unit, used for motion and, with skin contact, for wear detection.
- **Arousal is not resonance.** Excitement, stress, heat and movement all raise EDA. Interpretation needs context from self-reports, the programme and interviews.

## Deployment pattern (instrument level)

- Devices `SH01`…`SH15`, handed to a subset of consenting participants for daytime sessions. The device-to-person mapping changes from day to day; it belongs in the spine (`eda:SH07` → `person:<id>`, with time intervals).
- Devices can form **synchronisation groups**: one device is the master (`iammaster`, `center` in `sdlog.cfg`) and the others take their time from it.
- Participants could take a device off without pressing anything. **Non-wear must be detected from the signal.** Button start/stop events, where they exist, mark the researcher docking or starting devices more often than a participant's pause.

## Raw format: SD card

```
<card>/sdlog.cfg                 configuration as last written (may not describe the data, see traps)
<card>/Calibration/calib_*       calibration blobs
<card>/data/<session>_<configtime>/<DEV>-<run>/<chunk>
```

- `<session>_<configtime>`: the session name and the Unix time it was configured. **It does not date the data inside**: devices kept recording under whichever session was last configured.
- `<DEV>-<run>`: one recording run (start to stop). `<chunk>` (`000`, `001`, …): one file per hour of recording.
- Some cards have no session level (`data/<DEV>-<run>/`).

Each chunk file:

| Bytes | Content |
|---|---|
| 0–383 | header (below) |
| 384… | blocks of 503 bytes: a 9-byte sync slot, then 38 records of 13 bytes |

A full chunk is 384 + 12,127 × 503 = 6,100,265 bytes (460,826 samples). Chunks rotate by **sample count**, not wall time: a full chunk is 3600.2 s of the device's own clock.

Header fields used (all other bytes are configuration that is the same on every unit, or zeros; no GSR or inertial calibration is stored per device):

| Bytes | Field |
|---|---|
| 0–1 | sample-rate divisor, little-endian (32768 / 256 = 128 Hz) |
| 16 | `0x37` sync master, `0x35` slave |
| 17 | bit 0: sync on |
| 44–51 | clock origin, ticks, big-endian (the same on every unit) |
| 52–55 | configuration time, Unix seconds, big-endian (the session folder's number) |
| 251–255 | **device clock at the chunk's first record**: 40-bit tick count (byte 251 the high byte, 252–255 little-endian). Device time = (count + origin) / 32768 s; its low 24 bits are the record's tick counter |

The sync slot is `0xFF` except, about once an hour on a unit in a sync group, for a **sync record**: a sign byte (0 +, 1 −) and an 8-byte little-endian tick count, the unit's clock minus the sync master's at that block. Corrupt blocks hold lookalikes: a record counts only if its block's first record is good, and the clock model screens the rest.

Each record, little-endian:

| Bytes | Field |
|---|---|
| 0–2 | tick counter, uint24, 32768 Hz; +256 per sample at 128 Hz |
| 3–8 | accelerometer X, Y, Z, int16, 8192 counts per g (±4 g) |
| 9–10 | PPG, 12-bit ADC |
| 11–12 | GSR: bits 15–14 auto-range index, bits 13–0 ADC value |

## Raw format: Shimmer Base CSV export

`<session>_Session<n>_<DEV>_Calibrated_SD.csv`. Line 1 `"sep=<c>"` names the separator (comma or tab), line 2 the column names (prefixed with the device), line 3 the units. Calibrated columns: `TimestampSync_Unix_CAL` (ms), accelerometer (m/s²), `GSR_Range_CAL`, `GSR_Skin_Conductance_CAL` (µS), `GSR_Skin_Resistance_CAL` (kΩ), `PPG_A1_CAL` (mV), `PPG_IBI_CAL` (ms), `PPGtoHR_CAL` (BPM). `-1` marks no IBI/HR. The uncalibrated export writes `0.0` for conductance and resistance, so it cannot be converted.

## Calibration

GSR (verified exact against the calibrated export, sample by sample):

```
R_skin [kΩ] = R_f[range] / (ADC · 6/4095 − 1),   R_f = 40.2, 287, 1000, 3300 kΩ for ranges 0–3
R_skin < 8 kΩ is clamped to 8 kΩ (125 µS);  conductance [µS] = 1000 / R_skin
```

An ADC value of 0 or above 4095 is not a valid reading (12-bit converter): flagged, no conductance. An open circuit (electrodes off skin) reads as a very low conductance on the highest range.

PPG mV = ADC · 3000/4095.

## Clock

### Placement on the device's clock

- The tick counter wraps every 2²⁴ / 32768 = **512 s**. The Shimmer software mishandles the wrap: **every absolute timestamp it produces (database, CSV export) has spurious whole 512-s periods inserted.** The sensor values are sound.
- On the SD card the counter is reliable between records, and the **chunk header** holds the device's full clock at the chunk's first record, to the tick. An SD timeline is the tick counter, unwrapped and placed by the headers. The header dates even a chunk that lost its tail, and places runs whose modification times are useless.
- The **file modification time** (the device's clock when the file closed, stored to 2 s) is a fallback for a segment without a usable header, flagged, and a plausibility check otherwise (disagreements are counted in QA). Modification times are metadata, not content: a plain copy resets them (copy with `cp -p`, `rsync -a`, or keep the archive), and an archive may store them as naive wall-clock time in another zone (see the study config).
- A device can stop and resume at a counter value that looks like the next sample, after a whole number of 512-s wraps. The counter cannot see such a gap; the anchors can (their residuals step by k × 512 s), and the segment is split there.
- In an export, the first sample's timestamp is right, and every later one is right **modulo 512 s**. The ticks are rebuilt from the timestamps and handled like an SD card; a segment after a gap is placed at the smallest gap that agrees modulo 512 s. A real pause beyond the step limit could hide whole wraps, so such segments are flagged `gap_ambiguous`.

### Device clocks drift, and the sync records measure it

- **Some units run slow while they record**, by a rate roughly fixed per unit, up to a few percent (minutes per working day); units that keep time agree to under a second. The error grows within a run; the clocks are usually **re-set when a unit is started** from the base [inferred], so it does not build up over days, but not always (a unit started without the base keeps its error). The model assumes a re-set only where it has no records. A slow clock also samples slowly, so anything measured in seconds on such a unit (SCR rise time, intervals) is scaled by the same fraction.
- File rotation runs on the same clock, so neither the headers nor the modification times can show the drift. The **sync records** can: in a sync group, each slave writes its offset to the master about hourly. The master can itself be slow, and a day can have more than one master.
- **The export's "synchronised" clock does not correct drift.** Shimmer Base writes the device's clock minus one sync offset per file (or none). Treat an export's clock as its device's clock plus an unknown constant. After the 512-s repair, a segment that follows a long gap can still be off by whole wraps (the repair only knows the gap modulo 512 s), so the constant holds per clock segment, not per file.
- `eda.clock` corrects every run (`social-energy ingest-eda`):
  1. Per local day, the **reference units** (`study.yaml`: units known to keep time) give the master's curve, reference minus master, followed piecewise-linearly through their records. A day with several masters can have several curves.
  2. A slave's record gives its error against the reference: its offset minus the curve, read at the reference time. Per run, a robust line keeps the records that agree (choosing, per record, the curve it fits), and the error is followed through them, extrapolated with the run's fitted rate.
  3. The master's error is minus its curve. A master run started after the curve's last record (re-set then) is not described by it.
  4. A run with no usable record (sync off, a unit that never synced, a day without reference records) gets its **unit's typical rate** from the start of the run, or a rate set in the study config, and is flagged `clock_uncertain`; so are times more than 3 h from the records of a drifting unit's run.
  5. Where a card and an export both hold a recording, the export's rows are the card's records, one for one. Each export clock segment is matched to the SD run of its device by exact PPG sample sequences; its lag (the constant, plus any whole wraps) is removed before the run's model applies. A segment the card does not hold takes its nearest matched segment's lag, flagged; an export with no match keeps its own clock with the unit's fallback, flagged.
- Corrected time is the **reference group's** time. Its own error against UTC cannot be seen in the cards; the study config sets it (`reference_to_utc_s`), from the best external events available, with its uncertainty.
- **Check:** after hand-in the devices lie together and share every bump. `ingest-eda` cross-correlates their motion in the windows the study config lists, per pair over sub-windows, and reports each device-day's residual (`comotion.parquet`, `qa.json`). Devices lying together agree to a few hundredths of a second; the corrected clocks should agree to about a second.
- An export can have **no clock at all** (`-1` in every timestamp). It is placed from the corrected start of the other exports of its session (the units were started together), or from a start set in the study config, by its sample index (pauses in sampling are invisible then), and flagged `clock_uncertain`.

## Known traps

| Trap | Handling |
|---|---|
| Session folder names do not date the data | dates from the timeline only |
| Short runs of all-zero records, and bursts of out-of-sequence tick values | flagged `bad_record`, left off the timeline, counted in QA |
| Sampling pauses of ~28.7 s (device busy, likely sync), and single dropped samples | real elapsed time: the counter shows it, the timeline follows it |
| A chunk truncated to a 4 KiB boundary while its modification time still marks the full hour | placed by its header; its modification time is not an anchor |
| Header or modification times outside the study (a card read out later, a clock never set) | not used as anchors; segments with no usable anchor are flagged `unanchored` |
| Units whose clocks run slow, by up to a few percent | corrected per run from the sync records (`eda.clock`); `clock_uncertain` where only the unit's typical rate applies |
| Sync-record lookalikes in corrupt blocks | only records in a good block count; a robust fit per run drops the rest |
| A day with two sync masters (slaves sync to either) | one curve per master; each record is read against the curve it fits |
| Export timestamps all `-1` | placed from the session's corrected start by sample index, flagged `clock_uncertain` |
| Gaps the counter cannot bridge (≥ 1 min between consecutive records) | the run splits into segments, each placed by its own anchors |
| Duplicate run folders from copying (`<DEV>-<run> 2`) | byte-identical chunks dropped; complementary halves kept |
| Byte-identical export files under two session names | dropped as duplicates |
| A device's `sdlog.cfg` reset to factory values (51.2 Hz, GSR off) while its data is standard 128 Hz | sample rate read from each chunk header, not from `sdlog.cfg` |
| OS files inside `data/` (Spotlight index, `.fseventsd`, copy temporaries) | ignored: only `<DEV>-<run>/<3 digits>` is read |
| The same samples on the SD card and in an export | one source per device-second, SD first |
| Heat raises EDA baselines | context, not a flag |

## Privacy

- The export folders contain a `Data Descriptions.txt` that lists participant names against study ID and device. It is identifying: never copy it out of `raw/`, never read it into a table.
- The device-to-person mapping is a spine fact and lives only in the local spine.

## Canonical tables

`social-energy ingest-eda` writes them to `derived/eda/`:

- `files`: one row per chunk or export file: device, source, run, path, records (bad, unanchored, placed, implausible, placed by modification time), start, end, `truncated`, `duplicate` (a byte-identical copy, not read), `clock_model` (`sync`, `master`, `rate`; exports `sd-…` when matched to their card), `clock_uncertain`, `clock_correction_s` (median); exports also `clock` (`sync`, `device`, `recovered`, `none`), `export_offset_s` (the measured constant, at the first matched segment), `export_segments_matched`, `export_segments_off_by_wraps` and `matched_run`.
- `seconds`: one row per device-second and source (UTC): samples, GSR samples, conductance (mean µS of valid readings), range, motion (mean and SD of |a| in g), PPG mean, heart rate where the export carries it; `clock_correction_s` (corrected minus device time); flags `gap_ambiguous`, `clock_uncertain`, `duplicate` (another source covers the second; SD wins), `implausible_time`; `ok`; `contact` (conductance ≥ 0.05 µS) and `worn` (inside a wear bout).
- `wear`: device, start, end (half-open), contact seconds, `clock_uncertain` (any second of the bout). Contact gaps up to 60 s are bridged; bouts under 5 min dropped.
- `clock`: one row per run: the model kind, records and inliers, error rate (s per device hour), error at start and end, `uncertain`.
- `comotion`: per device and window where devices lay together, the residual of its corrected clock against the others, the pairs it rests on, and `clock_uncertain`. `qa.json` summarises device-days with at least two pairs, for measured and fallback clocks separately.
- `scr`: device, source, onset, peak, amplitude (µS), rise time, `ok`, `worn`, `clock_uncertain`. Trough-to-peak on 4 Hz, 1 s smoothing, ≥ 0.05 µS within 0.5–5 s; onset at the last point within 5% of the rise.
- `person_minutes`: after the spine, one row per person-minute with worn seconds, mean and median conductance, motion SD, heart rate, SCR count and summed amplitude, `excluded`, `clock_uncertain`. People without EDA consent are not in it.
- Records with no time (bad, unanchored) are counted in `qa.json`, never placed.

The wear and SCR thresholds are conventional defaults `[inferred]`, configurable, for the research team to review.
