# Instrument: EDA / heart-rate wearables (Shimmer3R GSR+)

Status: **ingest built** (`social_energy.eda`, `social-energy ingest-eda`). Reads SD-card logs and Shimmer Base calibrated CSV exports, and corrects device clocks from the cards' sync records. **Heart rate from the raw PPG built** (`social_energy.eda.ppg`, `social-energy eda-heart-rate`), on the same corrected clocks.

## What it measures

- Electrodermal activity (skin conductance) from two finger electrodes. *Tonic* level (slow) and *phasic* responses (SCRs, seconds): sympathetic arousal.
- PPG (optical pulse, finger or ear clip), from which heart rate and inter-beat intervals can be derived. Signal quality varies by device and wear, and some sensors show no pulse at all; every heart-rate window carries a quality index (below).
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
  4b. **Box anchors** (`eda.box`). After hand-in, and on some mornings before hand-out, the units lie together in a box and still record, so every bump of the box reaches all of them at one true moment. Per run, the off-skin stretch after its last wear (evening) and before its first (morning) is cut out as accelerometer jerk; every two stretches that overlap are cross-correlated over 5-min windows, and a pair counts when at least three confident windows lie on one line (the lag may drift slowly while a clock is still off in rate). The search runs twice: wide (±2 min) and with each bump widened by 0.5 s on the clocks the records give, then sharp and narrow (±5 s) on the clocks the first search anchored. Per group of pairs, a least-squares solve gives every unit's residual, dropping the worst pair while any misses by more than 0.25 s; the zero is the median of the units whose clock the records measured there. An unmeasured unit gets an **anchor** only if it closes a triangle of pairs and the group has a measured unit; a measured unit more than 1 s off is a **disagreement** and its run is flagged. A fallback run then follows its anchors and the re-set at its start piecewise-linearly (a morning anchor replaces the assumed re-set); a fitted run takes its anchors as knots beyond its records; a master that cannot tell its curve takes the one its anchors agree with. Anchors that disagree by more than 1 s, or that imply a rate no clock has, keep the flag. So does a box-only clock drifting more than 1 s/h: a drifting unit's rate changes within the day, and between the morning re-set and the evening box it strays by seconds (see the validation); its correction is still the box's (`clock_source: box`), only the flag stays.
  4c. **Validation** (`box_loo`): every slave run the records fitted is anchored again with its own records left out, and compared with its record-based clock over the measured part of the run. The pairs are measured once, on the clocks with records, and carried over to the reduced model exactly (a lag is a difference of clock errors), so this tests the anchoring and the re-set-plus-linear-drift assumption, not whether the search would have found the pair on a worse clock. A unit that is the only reference of its day cannot be validated this way.
  5. Where a card and an export both hold a recording, the export's rows are the card's records, one for one. Every 5 minutes of rows, a probe of 32 PPG samples is looked up exactly on the device's SD runs; each row takes the lag (the constant, plus any whole wraps) of its nearest successful probe in the same export clock segment, within 10 minutes, and that run's model applies. Rows between disagreeing probes are flagged; rows no probe reaches keep the export's own clock with the unit's fallback, flagged.
- Corrected time is the **reference group's** time. Its own error against UTC cannot be seen in the cards; the study config sets it (`reference_to_utc_s`), from the best external events available, with its uncertainty.
- Every corrected time has a **source**, `clock_source`: `sync` (the records or the reference curves), `box` (box anchors), `rate` (the unit's rate, extrapolated; always `clock_uncertain`). `clock_uncertain` stays where the clock is a guess: no record and no anchor, anchors that disagree, or the box contradicting a measured clock.
- **Check:** after hand-in the devices lie together and share every bump. `ingest-eda` cross-correlates their motion in the windows the study config lists, per pair over sub-windows, and reports each device-day's residual (`comotion.parquet`, `qa.json`). Devices lying together agree to a few hundredths of a second; the corrected clocks should agree to about a second. A box-anchored clock passes this check by construction (the same box measured it), so `qa.json` reports it apart; the leave-one-out above is its independent check.
- An export can have **no clock at all** (`-1` in every timestamp). It is placed from the corrected start of the other exports of its session (the units were started together), or from a start set in the study config, by its sample index (pauses in sampling are invisible then), and flagged `clock_uncertain`.

## Known traps

| Trap | Handling |
|---|---|
| Session folder names do not date the data | dates from the timeline only |
| Short runs of all-zero records, and bursts of out-of-sequence tick values | flagged `bad_record`, left off the timeline, counted in QA |
| Sampling pauses of ~28.7 s (device busy, likely sync), and single dropped samples | real elapsed time: the counter shows it, the timeline follows it |
| A chunk truncated to a 4 KiB boundary while its modification time still marks the full hour | placed by its header; its modification time is not an anchor |
| Header or modification times outside the study (a card read out later, a clock never set) | not used as anchors; segments with no usable anchor are flagged `unanchored` |
| Units whose clocks run slow, by up to a few percent | corrected per run from the sync records (`eda.clock`), or from box co-motion with measured units where a run has no records (`eda.box`); `clock_uncertain` where only the unit's typical rate applies |
| A unit started without the base keeps its error (no re-set) | only a morning box anchor can show it; with an evening anchor only, the model assumes the re-set |
| Sync-record lookalikes in corrupt blocks | only records in a good block count; a robust fit per run drops the rest |
| A day with two sync masters (slaves sync to either) | one curve per master; each record is read against the curve it fits |
| Export timestamps all `-1` | placed from the session's corrected start by sample index, flagged `clock_uncertain` |
| Gaps the counter cannot bridge (≥ 1 min between consecutive records) | the run splits into segments, each placed by its own anchors |
| Duplicate run folders from copying (`<DEV>-<run> 2`) | byte-identical chunks dropped; complementary halves kept |
| Byte-identical export files under two session names | dropped as duplicates |
| An export with `-1` in every timestamp (written without a clock) | rows are `bad`, not placed; the SD card covers the same samples |
| A device's `sdlog.cfg` reset to factory values (51.2 Hz, GSR off) while its data is standard 128 Hz | sample rate read from each chunk header, not from `sdlog.cfg` |
| OS files inside `data/` (Spotlight index, `.fseventsd`, copy temporaries) | ignored: only `<DEV>-<run>/<3 digits>` is read |
| The same samples on the SD card and in an export | one source per device-second, SD first |
| Heat raises EDA baselines | context, not a flag |

## Heart rate from PPG

The PPG is sampled with every record (128 Hz, 12-bit, mV = ADC · 3000/4095), on the SD card and in the export alike. Shimmer Base computes a heart rate (`PPGtoHR_CAL`) only into its export; on the SD card there is only the raw pulse. `social_energy.eda.ppg` derives heart rate from the raw pulse wherever it exists:

1. **Cleaning:** a zero-phase band-pass, 0.5–8 Hz (the magnitude of a second-order Butterworth applied forward and backward), per contiguous stretch; stretches split at any step between samples over 0.25 s (the ~28.7 s pauses, run boundaries).
2. **Beats:** systolic peaks by Elgendi et al. (2013): clipped and squared signal, a 111 ms moving average (one systolic peak) above a 667 ms one (one beat) plus 0.02 × the mean energy over 10 s; one peak per block at least 111 ms long; peaks under 0.3 s apart keep the larger.
3. **Inter-beat intervals:** an interval is *plausible* within 40–200 bpm (0.3–1.5 s) and within 30 % of the median of its 9 neighbours.
4. **Windows of 10 s** (aligned to the epoch): heart rate = 60 / median plausible interval. Quality after Orphanidou et al. (2015): rate 40–200 bpm, no gap between beats over 3 s, longest / shortest interval < 2.2, mean correlation of the beats with their average template ≥ 0.86; plus ≥ 8 s of signal, ≥ 3 plausible intervals, and a filtered pulse SD ≥ 5 mV. Each rule is a flag, `quality_ok` their conjunction. Nothing is dropped.

The interval-change limit and the 5 mV amplitude floor are ours `[inferred]`; the rest are the published defaults.

Instrument facts this rests on:

- **Polarity:** the stored PPG rises with each pulse. Beats agree with their template better upright than inverted, and both polarities give the same rate.
- **Dead or unusable PPG:** a sensor that sees no pulse records only noise of ~0.1–3 mV SD (on skin or off), against a pulse of tens to hundreds of mV SD on a working one. On DSA 2026 this was a property of a device-*day*, not of a device: the same unit gave no pulse all day and a normal pulse the next, as if the clip was not on `[inferred]`. The amplitude floor and the template rule flag it; `hr_usability` shows it per device-day.
- **Shimmer's own heart rate is not a reference on a dead sensor:** on noise it reports intermittent, implausibly high values (often near 180–213 bpm). Compare against it only where the PPG itself is good.
- Heart rate is placed exactly as the ingest places its seconds: the same first pass builds the same per-run clock model, SD runs are corrected through it, and exports are matched row for row to their card and corrected through that run's model (Clocks, above). So it is only as well placed as the clock correction is: windows touched by a fallback clock carry `clock_uncertain`. Before the correction, SD windows and export windows of "the same" time on a drifting unit were different moments, and comparing them measured the clock, not the method. The algorithm itself is validated on the export's own samples, where both rates come from the same samples on the same clock.

## Privacy

- The export folders contain a `Data Descriptions.txt` that lists participant names against study ID and device. It is identifying: never copy it out of `raw/`, never read it into a table.
- The device-to-person mapping is a spine fact and lives only in the local spine.

## Canonical tables

`social-energy ingest-eda` writes them to `derived/eda/`:

- `files`: one row per chunk or export file: device, source, run, path, records (bad, unanchored, placed, implausible, placed by modification time), start, end, `truncated`, `duplicate` (a byte-identical copy, not read), `clock_model` (`sync`, `master`, `box`, `rate`; exports `sd-…` when matched to their card), `clock_uncertain`, `clock_correction_s` (median); exports also `clock` (`sync`, `device`, `recovered`, `none`), `export_offset_s` (the measured constant, at the first matched row), `export_rows_matched`, `export_lag_changes` (jumps by whole wraps) and `matched_run`.
- `seconds`: one row per device-second and source (UTC): samples, GSR samples, conductance (mean µS of valid readings), range, motion (mean and SD of |a| in g), PPG mean, heart rate where the export carries it; `clock_correction_s` (corrected minus device time); `clock_source`; flags `gap_ambiguous`, `clock_uncertain`, `duplicate` (another source covers the second; SD wins), `implausible_time`; `ok`; `contact` (conductance ≥ 0.05 µS) and `worn` (inside a wear bout).
- `wear`: device, start, end (half-open), contact seconds, `clock_uncertain` (any second of the bout), `clock_source` (the worst of its seconds). Contact gaps up to 60 s are bridged; bouts under 5 min dropped.
- `clock`: one row per run: the model kind (`sync`, `master`, `box`, `rate`), records and inliers, error rate (s per device hour), error at start and end, `uncertain`, box `anchors` used, `box_disagrees`.
- `comotion`: per device and window where devices lay together, the residual of its corrected clock against the others, the pairs it rests on, `clock_uncertain` and `clock_source` (worst in the window). `qa.json` summarises device-days with at least two pairs, for measured, box-anchored and fallback clocks separately.
- `box`: one row per off-skin stretch with pairs: device, run, position (`head`, `tail`, `whole`), device time, whether the records measured it there (`known`), the record model's error, the box residual against it and the resulting error, pairs kept, `triangle`, group, `status` (`anchor`, `check`, `disagree`, `unchecked`). `box_pairs`: the pairs (lag, windows, device times). `box_loo`: the leave-one-out validation per run (box against records: median and max absolute difference; the fallback's max for comparison; share still flagged).
- `scr`: device, source, onset, peak, amplitude (µS), rise time, `ok`, `worn`, `clock_uncertain`, `clock_source`. Trough-to-peak on 4 Hz, 1 s smoothing, ≥ 0.05 µS within 0.5–5 s; onset at the last point within 5% of the rise.
- `person_minutes`: after the spine, one row per person-minute with worn seconds, mean and median conductance, motion SD, heart rate, SCR count and summed amplitude, `excluded`, `clock_uncertain`. People without EDA consent are not in it.
- Records with no time (bad, unanchored) are counted in `qa.json`, never placed.

`social-energy eda-heart-rate` (after `ingest-eda`, whose `wear.parquet` it reads) adds, beside them and touching nothing else:

- `hr_beats`: one row per detected beat: device, source, run, `t`, `ibi_ms` (from the previous beat of the same stretch), `plausible`, `ok`, `clock_uncertain` and `clock_source` (its window's).
- `hr_windows`: one row per device, source, run and 10-s window: covered seconds, beats, plausible intervals, `hr_bpm`, `ibi_ms`, filtered pulse SD, template correlation, one flag per quality rule and `quality_ok`; for exports also Shimmer's mean `hr_export_bpm`; `gap_ambiguous`, `clock_uncertain`, `clock_source` (worst of its samples) (any sample's clock is the fallback), `clock_model` (the run's, as in `files`), `duplicate` (one source per device-window, SD first), `implausible_time`, `ok`, `worn` (the window's midpoint is inside a wear bout).
- `hr_minutes`: per device-minute over `ok` windows: `hr_bpm` (median of the good windows), `hr_quality` (good windows / 6), window counts, `worn`, `clock_uncertain`, `clock_source`. It joins onto `person_minutes` by device and minute (`eda.heart.with_heart_rate` adds `hr_ppg_bpm`, `hr_quality`, `hr_clock_uncertain` and `hr_clock_source`); `person_minutes` itself is unchanged.
- `hr_agreement`: per device and local day, our rate minus Shimmer's in windows where ours is good and the export has one: n, bias, SD, Bland–Altman limits, MAE, share within 5 bpm; once on the export's own samples (the algorithms compared) and once on the SD card's samples of the same windows.
- `hr_usability`: per device and local day over worn windows: their number, the share with good heart rate, the share with a pulse above the floor, medians of template correlation, pulse SD and heart rate.

The wear and SCR thresholds are conventional defaults, configurable; we chose them, with a stricter SCR sensitivity rule (amplitude ≥ 0.2 µS), in [`decisions/eda-ingest.md`](../../decisions/eda-ingest.md).
