# Instrument: ambient acoustics (AudioMoth)

Status: **feature extraction built** (`social_energy.acoustics`, CLI `extract-acoustics`).

```bash
uv run social-energy extract-acoustics studies/<id>/study.yaml               # features only
uv run social-energy extract-acoustics studies/<id>/study.yaml --delete-wavs # + verified deletion
```

Expected raw layout: `$SOCIAL_ENERGY_DATA/<id>/raw/audiomoth/<device>/*.WAV`. Output goes to
`derived/acoustics/<device>/<wav-stem>.parquet` plus `manifest.parquet`, the audit trail of
file, SHA-256, windows, deleted and error.

Features per window (default 1 s): `rms_dbfs`, `peak_dbfs`, zero-crossing rate,
spectral centroid, spectral flatness, and energy in 4–6 wide bands (`band_<lo>_<hi>_db`).
Recording time comes from the AudioMoth ICMT comment (`Recorded at HH:MM:SS DD/MM/YYYY (UTC±h)`),
falling back to the filename in `acoustics.filename_timezone` (default UTC).

## What it is for

The "sound of solidarity" (Stanford Gregory): group sound such as singing together, clapping, laughter and applause has a spectral and level signature. Recorders sit in shared spaces (e.g. the plenum hall and dining hall) and record on a schedule.

## Ethics constraint (hard requirement)

The approved ethics application says the WAV files are **temporary**. They are used only to extract **frequency and level features** and are then deleted. **No transcription and no content analysis of speech.** So the toolkit must provide:

1. a feature extractor that streams WAVs and writes only aggregate features (e.g. per 1 s / 10 s window: RMS level, band energies, spectral centroid/flatness, and optionally MFCC summary statistics that cannot be inverted to intelligible speech `[inferred]`);
2. a verification step (features complete and checksummed);
3. an explicit, logged deletion of the WAVs, run by the data owner.

Features that allow speech reconstruction (fine-grained spectrograms) must not be stored.

## Deployment pattern

- AudioMoth devices on scheduled recording windows (e.g. meal times, plenum, singing, evening programme). **Schedules changed during a study.** Record them per device in `study.yaml`.
- Files are named by the device's clock (`YYYYMMDD_HHMMSS.WAV`) `[inferred: standard AudioMoth naming, confirm]`. The device clock is set at configuration time. Check drift against known loud events (applause at a noted time).

## Open questions

- `[unknown: sample rate, gain, and whether the WAVs still exist or were already reduced]`
- `[unknown: exact recording schedule per device per day]`
