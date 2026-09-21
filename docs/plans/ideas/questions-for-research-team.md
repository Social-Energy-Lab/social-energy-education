# Open questions for the research team

**Priority:** high

**Goal:** one place to collect the questions only the research team can answer, so they can be settled in a single conversation and the answers written back into the docs.

## Context

Gathered from the `[unknown: …]` markers across the repo. When a question is answered, write the answer into the doc that asked it, remove the marker there, and delete the line here. Retire this plan once it is empty.

This is the public half: the instrument questions. The working version, with who answers what and with the record-level detail behind each question, is in the private context library (`_team/questions.md`).

## Decided (2026-09-18, Álvaro)

- The research design (hypotheses, RQs, design) may be public: `docs/context/project.md`.
- The survey codebook may be public: item codes, constructs, scales. **No wording** of the study's own items.

## Answered (2026-09-20, Mahdi)

- **Self-efficacy belongs to *lust for life*.** The survey's own block logic is authoritative: B = trust in life, C = agency and motivation / lust for life, self-efficacy in C. Written into `docs/context/theory.md` (Settled), `docs/context/instruments/survey.md`, `studies/dsa-2026/research/constructs.md`.
- **State variables and system boundary** are *part of the research*, not a pending answer. Reframed in `theory.md` open tension 1.
- **Consent needs no reconstruction.** Where data exists with a study ID, consent exists; no consent means no labelled data (usually no data). `project.md` and the spine plan now say so, and `spine.consented()` stays as a guard.
- **Repeated survey submissions:** the same typed study ID on several records is most likely the same person re-submitting after a connection drop. Rule: keep the most complete submission, flag the others, drop nothing silently.
- **Deleted AI interviews are out of scope.** Deleted means not used; don't ingest, don't chase.

## Deferred by the team (no date yet, 2026-09-20)

These are not blocked on a decision but on material Mahdi will hand over.

- The **study-ID list** with roles, and course membership per participant.
- The **EDA device-distribution plan** (Shimmer device → study ID per day).
- The **interview ↔ study-ID mapping table** (not a field log; a purpose-made table). It also decides whether the ID typed before the interview is the beacon-based study ID or the invitation-email one, and places the calls with no platform user row.
- **Educational success (H2):** a follow-up wave is possible but not planned; revisit no earlier than **November 2026**.
- **Staff presses:** probably analysed separately from participants', not decided. Keep the role on every press.
- **The constructs table** (`studies/dsa-2026/research/constructs.md`) still needs the team's review; nothing is `agreed` yet.

## Answered (2026-09-20, from the upstream firmware repo)

Read off <https://github.com/thofbaur/network-beacon_NRF54L15> rather than asked. Written into `docs/context/instruments/beacons.md`.

- **Firmware settings are in the repo.** `Network_Beacon_nrf54/dsa.conf` (build-time), `dsa_runtime.conf` (runtime defaults) and `shared/common_include.h` hold the production values, and the history dates them: production values on 2026-08-08/09, location-tag values 08-12, DSA tag parameters 08-13, eco mode off for one location tag 08-15. What remains to ask is narrower (see below).
- **The delivered `Output/` folder comes from the upstream `postprocessing.py`.** Its default filenames and column headers match the delivery exactly. It dates events from `Current Timer` anchors, retries against the *previous boot's* anchor when the first attempt lands over 600 s in the future under a high-water guard, and skips records it cannot place or whose ID/RSSI is out of range into `sanity_findings.csv`. That retry is the likely explanation of the self-report offsets in `beacon-differential-check.md`, and our ingest has no equivalent.

## Answered (2026-09-20, by the firmware author)

- **Location tags do scan and store contacts, and were read out.** They run a looser RSSI threshold (−100 vs −80 dBm) so they hear more tags. The records are already in the delivery; the mapping to rooms will be written up separately.
- **No RSSI ground-truth session was recorded.** By design: the threshold was set low so everything is stored and what counts as an interaction is decided in preprocessing. A calibration session for a future phase is now `docs/plans/ideas/rssi-ground-truth-session.md`.

## Instruments

1. Beacons: which firmware build went on which tag at camp start (the defaults are in the repo; the per-tag flashing and the control commands sent during the camp are not), and the times of runtime setting changes.
2. Beacons: what is room 0.08 (location tag 115)? Its label is `[unknown]` in `studies/dsa-2026/locations.yaml`.
3. Beacons: what exactly did the `_cleaned` step remove from the six 13–15 Aug logs, which script did it, and do the uncleaned originals still exist? The upstream repo has no cleaning script, so it was done by hand or by something unpublished. (The field log ties the cleaning to the corrupted-logger incident of 15 Aug, so the *why* is settled; the *what* is not.)
4. Beacons: at which commit was the delivered `Output/` produced? The current head is 2026-09-17; if it was an older build, the reboot-backlog retry may not have been in it.
5. EDA: export format and software, channels enabled (GSR, PPG?), sampling rate, absolute timestamps and clock sync.
6. AudioMoth: sample rate and gain, exact schedules per device per day, and do the WAVs still exist? (They must be deleted after feature extraction.)
7. Survey: the **confirmed reverse-keying list**. The candidates in `docs/context/instruments/survey.md` are inferred from wording, and scoring needs the confirmed list.
8. Survey: three form versions (16, 17, 18) were live. What changed between them? Do the old codes map one-to-one onto the new ones (`GRADIENT_variable_C11/C21` → `ZGL_C11_GRAD/ZGL_C21_GRAD`; what were `SWE_05–07_resonance`)? Did B19/B20 run as 1–10 sliders (the export shows only 1–10)?
9. Survey and AI interviews: was a **post-academy wave** fielded (another platform agent), and with which blocks?
10. Interviews: coding tool and export format (only if coded segments will be analysed alongside sensors).
11. Future field phases: which tool will the on-site researcher use for a structured field log (laptop spreadsheet, phone form)?

