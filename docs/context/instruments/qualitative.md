# Instruments: interviews, observations and field log

These are the qualitative and contextual sources. The code here does not analyse their content. It uses their **structure**: timestamps, locations and participation, so that sensor data can be put in context.

## Interviews

- **In-person phenomenological interviews** during a programme. Audio is recorded, transcribed, stripped of direct identifiers, then deleted.
  - **Recorder (DSA 2026): DJI Mic 3**, two clip-on transmitters (`TX01`, `TX02`) linked to one receiver. Each transmitter writes to its own internal memory, which appears as a separate FAT32 volume when plugged in.
  - Files: `TX_MICnnn_<YYYYMMDD_HHMMSS>/TXnn_MICnnn_<YYYYMMDD_HHMMSS>_orig.wav`. The folder is a storage chunk: the device starts a new one from time to time `[inferred: after a power cycle or reconnect]`, and file numbering restarts in each folder. **Folders do not correspond to sessions or people.**
  - BWF WAV (`bext` + `iXML` chunks, originator "MIC 3"), 48 kHz mono, 32-bit float (a few early files are 24-bit PCM). A recording is split into files of at most 30 minutes.
  - **The unit is a pair.** Both transmitters start and stop together, so a conversation is two files with identical start timestamps and lengths, one per mic. Both voices are audible on both files. Each mic hears its wearer loudest, so the wearer is found by comparing levels across the pair, not from which voice happens to be heard on one file.
  - The filename timestamp is **UTC** (confirmed by the research team). Convert to the study's time zone for matching against the programme. The clock was unset for the first few test files.
  - Junk to expect: sub-second to few-second accidental recordings, tests before the programme, and macOS `._*` / `.Spotlight-V100` files if the volume was ever mounted on a Mac. Unpaired long files (one transmitter only) also occur.
  - Local layout: `$SOCIAL_ENERGY_DATA/<id>/raw/interview-audio/dji-mic3/{TX01,TX02}/<original folders>/`, plus `IMPORT.md` and `SHA256SUMS` (see [`../data-layout.md`](../data-layout.md)).
  - Transcription runs **locally only** (faster-whisper large-v3, German, word timestamps). No audio goes to a cloud service. Each channel is transcribed on its own, and every word is kept only from the channel that is loudest while it is spoken. That attributes speech to the wearer without voice diarisation, and it removes the duplicate that the other mic picks up. Output: `derived/interview-audio/transcripts/<UTC start>.{json,md}` plus `sessions.csv`. The processing script is kept next to the outputs. Transcripts must then be cleaned of direct identifiers before the audio is deleted.
- **AI voice/chat interviews** before and after a programme. Only pseudonymised transcripts are stored.
  - DSA 2026 ran them on **zeitgeist-platform** (voice over the web, German, one agent per wave). The same platform session then delivered the structured survey (see [`survey.md`](survey.md)). The platform keeps the raw and cleaned transcript per call, its own LLM summaries and question/answer segments, and a test-call flag. Test calls and calls deleted on the platform are excluded on export.
  - Download: `social-energy fetch-zeitgeist studies/<id>/study.yaml` (agents listed in `study.yaml`, read-only login in `ZEITGEIST_DATABASE_URL`; see [`../data-layout.md`](../data-layout.md#getting-each-source)).
  - Local layout: `$SOCIAL_ENERGY_DATA/<id>/raw/ai-interviews/zeitgeist/<agent_name>/` with `interviews.jsonl`, `summaries.jsonl`, `qa_pairs.jsonl`, `participants.jsonl` (platform user ID → pre-interview answers), `agent.json` + `system_prompt.md` (agent configuration), `EXPORT.md` (provenance, row counts, exclusions) and `SHA256SUMS`. Rows are keyed by the platform's user UUID. Linking it to a study ID happens only locally.
  - **Linking accounts to people.** The only link in the export is the study ID a person types before the interview, so the platform account is the unit of identity, not the person. Expect one person to hold several accounts: someone whose call fails registers again and redoes it, which shows up as the same typed ID on accounts minutes to hours apart. Treat those as one person, keep them all, and order them in time so that each call still resolves to the account that made it. Where the same typed ID appears on accounts *days* apart, and each completed a full interview, the retry reading no longer holds: one of them may be a mistyped ID belonging to somebody else. Link both and exclude both until a human resolves it, because excluding one at random silently attributes an interview to the wrong person.
  - **Aborted calls.** Some calls last seconds and carry no transcript. They are failed attempts, not interviews, and are excluded by a visible flag rather than deleted — a person whose only call is one of these has no AI interview at all, which is a fact an analysis needs to see.
  - **Where the platform gates the interview on consent, the interview is the consent record.** zeitgeist-platform will not start a call until the person has accepted the consent text, so a call that exists proves they accepted it. There is no consent field to fetch and nothing to infer: the data cannot exist without it. A consent list kept anywhere else can only disagree by being out of date, and where it does, it loses. (The gate is what carries the argument, so check that every route into a call passes it. Here the only route that does not is an admin test call, and those are dropped on export.) None of this transfers to a worn sensor: a tag records whether or not anyone agreed to wear it, so for those modules the signed form stays the only record.
  - **Calls whose user row is gone.** An account deleted on the platform takes its typed study ID with it while its calls remain in the export. Nothing in the data can place them: by design the agent does not ask for the study ID during the interview. They are excluded. Deletion may itself be a withdrawal, so ask the team before treating such calls as merely unlinked.
- Transcripts are qualitative data. They are coded by the researchers and never processed or quoted in this repo. If structured codes are later exported (code × segment × study ID), they can be ingested like any other table `[unknown: coding tool and export format]`.

## Course-leader observations

Course leaders and academy leaders give structured impressions of consenting participants: *trust in life* and *lust for life* at the start, notable developments over the programme, and which moments triggered them. They also describe group-level dynamics. These are person-level qualitative data and stay local.

## Field log

The researcher on site keeps a running log. It is the ground truth that turns sensor data into interpretable data:

- **Programme timeline**: plenum, courses, meals, cross-course activities (with room and time), excursion, special events. It also records spontaneous gatherings that were not on the plan.
- **Device ledger**: who received which device when, replacements, battery changes, lost and found devices, devices taken off (e.g. for sport or water games), people leaving early or withdrawing, ID corrections.
- **Instrument changes**: firmware or settings flashed, recorder schedules changed, location tags added, moved, removed or damaged, logger failures.

In practice the field log is prose that mentions names, so it is never committed. Its content is transcribed locally, **IDs only**, into the spine:

| Field-log content | Spine file |
|---|---|
| device handed out / swapped / returned | `assignments.yaml` |
| device lost, not worn, broken, battery out; person absent or withdrawn | `exclusions.yaml` |
| programme items and spontaneous events | `events.yaml` |
| location tags and zones | `locations.yaml` |
| instrument/setting changes | `studies/<id>/study.yaml` (instrument-level, no persons) |

**For future field phases:** keep the field log directly in this structured form (a template spreadsheet or form with ID-only fields). This avoids the transcription step and keeps names out of the log altogether.
