# Local data layout

How research data is organised on a researcher's machine. Follow this exactly on every machine that holds data, so the toolkit, the study configs and the agents find the same files in the same places.

The data itself **never** enters this repository (AGENTS.md, invariant 1). This file describes the structure only. The same folder is also the **private repo**: it version-controls the text layer (source documents, team notes, private config) while the data, the field logs and the spine stay out of git entirely. Setting up a machine from both repos is in [onboarding.md](onboarding.md).

## Setting up a machine

1. Pick a folder outside the repo, on a disk with room for the raw audio (DSA 2026 interview audio alone is ~40 GB). On WSL, check the **Windows** drive that holds the WSL virtual disk too: the Linux `df` hides that the `ext4.vhdx` grows on `C:`.
2. Point the toolkit at it, in your shell profile:
   ```bash
   export SOCIAL_ENERGY_DATA=~/research-data/social-energy
   ```
   `social_energy.paths` refuses a root inside the repo.
3. Clone the private repo into it, or create the skeleton by hand:
   ```bash
   mkdir -p "$SOCIAL_ENERGY_DATA"/<study-id>/{context/sources,context/personal,notes,raw,spine,derived}
   chmod -R go-rwx "$SOCIAL_ENERGY_DATA"
   ```
4. Store it on an encrypted disk. The ethics approval requires encrypted storage with access limited to the project lead and explicitly authorised staff.

## The tree

```
$SOCIAL_ENERGY_DATA/              the data root, and the private repo
  _team/                          notes that apply to every study (private repo)
    theory-notes.md               reading of the unpublished manuscripts (U)
    questions.md                  open questions for the team, with names (I)
    perimeter-denylist.txt        strings the public repo's hook must refuse
  <study-id>/                     e.g. dsa-2026
    local.yaml                    private per-study config: platform identifiers, purged devices
    notes/                        our findings about this study's records (I)
    context/                      private context library (see below)
      README.md                   index: document, sensitivity (P/U/I/R), how far read
      sources/                    source documents converted to markdown (U/I/R)
      personal/                   field logs, rosters (study IDs only), anything tracking
                                  people (P); git-ignored, handed over only as an encrypted
                                  archive. The name <-> study-ID code list never goes here:
                                  it stays with the project lead (see Rules below)
    raw/                          instrument data exactly as delivered, one folder per instrument
      beacons/                    logger files
      eda/                        wearable exports
      audiomoth/<device>/         ambient WAVs (temporary: features, then deletion)
      interview-audio/<kit>/<tx>/ in-person interview audio (temporary: transcripts, then deletion)
      ai-interviews/<platform>/<agent>/   AI interview exports (one folder per interview agent / wave)
      survey/<platform>/<agent>/          survey exports
    spine/                        IDs only: consent, assignments, locations, events, exclusions (YAML)
    derived/                      everything the toolkit produces; always regenerable from raw/ + spine/
      <instrument>/               canonical tables (parquet) + QA/manifest
      analyses/<slug>/            analysis outputs
```

## Getting each source

| Source | How it reaches `raw/` | Lands in |
|---|---|---|
| Beacons | copy the raw logger files as delivered (the unmodified ones, if a delivery has several versions); keep other versions outside `raw/beacons/`, since the ingest reads every `.log` under it | `raw/beacons/` |
| EDA | wearable export `[unknown: export format]` | `raw/eda/` |
| AudioMoth | copy each card as it is, one folder per device | `raw/audiomoth/<device>/` |
| In-person interviews | copy each transmitter's volume, keeping the original folders (see [`instruments/qualitative.md`](instruments/qualitative.md)) | `raw/interview-audio/<kit>/<tx>/` |
| AI interviews + survey | `social-energy fetch-zeitgeist studies/<id>/study.yaml` (below) | `raw/ai-interviews/zeitgeist/<agent>/`, `raw/survey/zeitgeist/<agent>/` |
| Context documents | convert the shared documents to markdown and index them | `context/sources/`, or `context/personal/` if they name or track people |

**zeitgeist-platform** (AI interviews and the survey delivered after them). The agents to fetch are listed under `ai_interviews.zeitgeist.agents` in `$SOCIAL_ENERGY_DATA/<study-id>/local.yaml`: they identify a private deployment, so they live with the data and `study.yaml` refuses them. The connection string is a personal **read-only** login from the platform team. It is a secret: keep it in your shell or a password manager, never in the repo, a plan or a commit message.

```bash
uv sync --extra zeitgeist
export ZEITGEIST_DATABASE_URL='postgresql://<user>:<password>@<host>/<db>?sslmode=require'
uv run social-energy fetch-zeitgeist studies/<id>/study.yaml
```

The command only reads. It drops test calls, pilot testers and empty users, and never selects identity columns. It writes `EXPORT.md` (row counts for everything dropped) and `SHA256SUMS` in each folder. Re-running it overwrites the export with the platform's current state, so check the counts in `EXPORT.md` against the previous run.

**Survey ingest and scoring.** `social-energy ingest-survey` writes `derived/survey/{items,respondents}.parquet` and `qa.json`. `social-energy score-survey` reads them with the codebook named by `survey.codebook` in `study.yaml` and writes `derived/survey/scoring/{scores,reliability,submissions}.parquet` and `qa.json`. It refuses until `survey.analysis_plan_frozen` is set in `study.yaml`. The team's study-ID correction table is a CSV with the columns `respondent,typed,study_id` (each row sets `respondent`, the platform user UUID, or `typed`, the typed value). It lives under the study's data root and `local.yaml` names it, relative to that root:

```yaml
survey:
  study_id_corrections: spine/survey-study-id-corrections.csv
```

## Rules

- **`raw/` is read-only once imported.** Never edit, rename or clean files inside it. Keep the original file and folder names: they carry device clocks and sequence numbers. Junk (OS files, accidental sub-minute recordings with no speech) may be left out at import, but only after checking it and listing each excluded file, with its checksum and the reason, in `IMPORT.md`. Nothing is removed silently, and nothing is removed later without the same record.
- **Purging a device is the one edit allowed inside `raw/`,** and only by ruling of the project lead (for example, records collected without consent). See [Purging a device](#purging-a-device) below.
- **One folder per instrument, then per device.** Name folders after the instrument and device (`interview-audio/dji-mic3/TX01/`), never after where the data came from (`card-E`, `usb-stick`). Drive letters differ between machines.
- **Every import gets an `IMPORT.md`** in its instrument folder. It records the source (device, card, export), the date, who imported it, what was excluded (OS junk such as `._*`, `.Spotlight-V100`, `System Volume Information`) and a `SHA256SUMS` file for every file kept. Platform exports use `EXPORT.md` in the same way.
- **Verify before wiping a source.** Compare the checksums against the original card or export before anything is deleted from it.
- **Temporary audio has an end date.** AudioMoth WAVs and interview audio may only be kept until their features or transcripts are produced and verified (ethics approval). The deletion is explicit and logged in the manifest.
- **Identity lives in `spine/` only.** Raw and derived tables use device IDs, session IDs or platform UUIDs. The mapping to people is made only in the spine, and the name ↔ study-ID code list stays with the project lead and never enters this tree.
- **`context/` is for reading.** What you learn is written down *here* by default — in `notes/` or `_team/`. The public repo gets only what may be published: methods, instrument behaviour, and the rules a finding produced, never the finding itself. Follow the data-perimeter skill.
- **`personal/`, `spine/`, `raw/` and `derived/` are in no repo at all**, private or public. They are git-ignored and refused by the private repo's pre-commit hook, and they move between researchers as an encrypted archive.

## Purging a device

When the project lead rules that a beacon's records must go, remove them from the raw logs themselves, not at ingest, and list the device in the study's private `local.yaml`:

```yaml
beacons:
  purged_devices: [<n>]      # device IDs, integers
```

`study.yaml` refuses this key: which device was purged is a fact about a person's consent. With the device listed, `social-energy ingest-beacons` (and `ingest_logs`, `ingest_logs_to`, `ingest_with_witnesses`) **refuses** any log that still names it, giving the device and the number of lines, and exits non-zero. So a later re-import of the original delivery cannot quietly restore the records.

The purge itself:

1. Remove every line naming the device as `ID` or `ID2`: lines containing `,ID: <n>,` or `,ID2: <n>,`. The match is comma-delimited, so purging 14 leaves 140–147 alone.
2. Keep the delivery's manifest as `SHA256SUMS.as-delivered` (once: a later purge never overwrites it), then regenerate `SHA256SUMS` for the cleaned files.
3. Record it in `raw/beacons/IMPORT.md`: date, device, lines removed per file, and the ruling.

`social-energy purge-device studies/<id>/study.yaml --device <n>` does all three. It is a dry run by default (it prints the lines per file and changes nothing); `--apply` cleans the files, keeps the manifest, regenerates `SHA256SUMS` and appends the counts to `IMPORT.md`, leaving the ruling for you to fill in. By hand, per log:

```bash
grep -cE ',ID2?: <n>,' file.log                                 # count first
grep -vE ',ID2?: <n>,' file.log > file.log.tmp && mv file.log.tmp file.log
```

Before the logger's ID fix, beacon IDs 48–57 were printed as `0`–`9` (`beacons.ambiguous_id_cutoff`). A purged device in 0–9 or 48–57 needs those early lines checked by hand: neither the purge nor the guard can tell which device such a line named.

## Moving data between researchers

Give the receiver access to the private repo, then hand over what git does not carry — `raw/`, `spine/`, `derived/` and `context/personal/` — encrypted in transit (an encrypted archive or the university's storage), with its `SHA256SUMS` files. The receiver sets `SOCIAL_ENERGY_DATA`, then runs `sha256sum -c` in each instrument folder. Once `raw/` and `spine/` are in place, `derived/` can be rebuilt with the CLI commands in the README.
