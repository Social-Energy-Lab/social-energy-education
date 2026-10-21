# Instrument: EDA / heart-rate wearables (Shimmer3R GSR+)

Status: **ingest built** (`social_energy.eda`, `social-energy ingest-eda`). Reads SD-card logs and Shimmer Base calibrated CSV exports.

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
| 0–383 | header. Bytes 0–1: sample-rate divisor, little-endian (32768 / 256 = 128 Hz) |
| 384… | blocks of 503 bytes: 9 bytes `0xFF` filler, then 38 records of 13 bytes |

A full hour is 384 + 12,127 × 503 = 6,100,265 bytes (460,826 samples). Each record, little-endian:

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

- The tick counter wraps every 2²⁴ / 32768 = **512 s**. The Shimmer software mishandles the wrap: **every absolute timestamp it produces (database, CSV export) has spurious whole 512-s periods inserted.** The sensor values are sound.
- On the SD card the counter itself is reliable between records, and the **file modification time** of each chunk is the device's clock when the file was closed. An SD timeline is the tick counter, unwrapped, placed by a fit to the modification times.
- Devices close a chunk and open the next on a fixed wall-clock rotation (an hour). So a chunk closed by rotation also dates its **first** record (modification time minus the rotation), which survives when the chunk lost its tail. Each chunk gives an end anchor (unless truncated) and a start anchor (if rotated).
- A device can stop and resume at a counter value that looks like the next sample, after a whole number of 512-s wraps. The counter cannot see such a gap; the anchors can (their residuals step by k × 512 s), and the segment is split there.
- In an export, the first sample's timestamp is right, and every later one is right **modulo 512 s** (checked sample by sample against SD cards). The ticks are rebuilt from the timestamps and handled like an SD card; a segment after a gap is placed at the smallest gap that agrees modulo 512 s. A real pause beyond the step limit could hide whole wraps, so such segments are flagged `gap_ambiguous`.
- Device clocks are not exactly in step with each other: placing SD data by a device's own modification times, a device can sit some seconds off the synchronised export clock (up to ~15 s on one DSA 2026 device-day). Treat cross-device timing as good to tens of seconds unless corrected against an export.
- FAT stores modification times to 2 s, so devices align with each other to about ±2 s: fine for EDA, not for beat-level or sub-second synchrony.
- **Modification times are metadata, not content.** A plain copy resets them. Copy with `cp -p`, `rsync -a`, or keep the archive. An archive (zip) may store them as naive wall-clock time in some other zone than the device's; measure the offset against an export's first sample before trusting it (see the study config).

## Known traps

| Trap | Handling |
|---|---|
| Session folder names do not date the data | dates from the timeline only |
| Short runs of all-zero records, and bursts of out-of-sequence tick values | flagged `bad_record`, left off the timeline, counted in QA |
| Sampling pauses of ~28.7 s (device busy, likely sync), and single dropped samples | real elapsed time: the counter shows it, the timeline follows it |
| A chunk truncated to a 4 KiB boundary while its modification time still marks the full hour | not used as an anchor; placed by the counter from its neighbours |
| Modification times outside the study (set when a card was read out later, or 1970 from an unset clock) | not used as anchors; segments with no usable anchor are flagged `unanchored` |
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

- `files`: one row per chunk or export file: device, source, run, path, records (bad, unanchored, placed, implausible), start, end, `truncated`, `duplicate` (a byte-identical copy, not read).
- `seconds`: one row per device-second and source (UTC): samples, GSR samples, conductance (mean µS of valid readings), range, motion (mean and SD of |a| in g), PPG mean, heart rate where the export carries it; flags `gap_ambiguous`, `duplicate` (another source covers the second; SD wins), `implausible_time`; `ok`; `contact` (conductance ≥ 0.05 µS) and `worn` (inside a wear bout).
- `wear`: device, start, end (half-open), contact seconds. Contact gaps up to 60 s are bridged; bouts under 5 min dropped.
- `scr`: device, source, onset, peak, amplitude (µS), rise time, `ok`, `worn`. Trough-to-peak on 4 Hz, 1 s smoothing, ≥ 0.05 µS within 0.5–5 s; onset at the last point within 5% of the rise.
- `person_minutes`: after the spine, one row per person-minute with worn seconds, mean and median conductance, motion SD, heart rate, SCR count and summed amplitude, `excluded`. People without EDA consent are not in it.
- Records with no time (bad, unanchored) are counted in `qa.json`, never placed.

The wear and SCR thresholds are conventional defaults `[inferred]`, configurable, for the research team to review.
