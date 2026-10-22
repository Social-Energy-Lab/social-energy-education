# Interviews: the membrane as a self-reported variable

**Priority:** high — target: a first exploratory result for the research-group talk on 2026-11-03
**Gate:** none
**Next:** the interview slide for 2026-11-03; the human check stays open (review sheet ready locally), so results are reported as model-coded

**Goal:** turn the membrane block of the in-person interviews into per-person codes (the state in
everyday life, on arrival and at the interview, change, openers and closers, placed episodes) and
set them beside the sensor and survey measures as a first-person ground truth.

## Handoff

- **Done (2026-10-21):** recordings joined to study IDs in the local spine (`interview:<recording>`
  assignments; method and traps in `docs/context/instruments/qualitative.md`). Codebook draft:
  `studies/dsa-2026/research/membrane-codebook.md`. Counts and per-day rulings are in the private
  note `dsa-2026/notes/interview-membrane-2026-10-21.md`.
- **Done (2026-10-21, later):** every linked interview coded by a model (Claude, raw transcripts,
  Álvaro's decision), a random fifth by an independent second coder; codebook revised once after
  the first 30 (`primed`, `known_elsewhere`, the 4-versus-5 edge) and the earlier files recoded.
  `studies/dsa-2026/analyses/exploratory_membrane.py` runs analyses 0–5; results only in the
  private note.
- **Open:** the codebook is the analyst's draft and needs the project lead's review. Its open
  questions for the team are its `[unknown: …]` marker and the private note's list. The revised
  edge rule leaves almost everyone at the same "now" level, so the change over the academy is
  carried mostly by the arrival code.
- **Done (2026-10-22):** instead of choosing, all three change measures are coded and compared
  (codebook, "Variants under comparison"; Álvaro: "we try everything"). The two new codes reach
  higher coder agreement than the strict one. Results per measure in the private note.
- **Decided (2026-10-22, Álvaro):** primary change measure `D_academy_lenient`, on coder agreement
  (codebook). The human check has not been done; a local review sheet (flagged codes, every
  low-confidence code, a random fifth) is ready under the private `derived/interview-membrane/review/`.

## Why

The confirmatory tier found no link between the survey baseline (trust and lust for life) and
network position or presses. The survey is a baseline taken before the academy. The interviews ask,
in the theory's own terms, how open each person was in everyday life, on arrival and during the
academy. That is the closest thing the study has to a first-person reading of the construct the
sensors are meant to show signatures of.

## Design

- **Unit:** one interview per person. Participants only in the main analyses; staff interviews are
  coded but analysed apart.
- **Consent:** `spine.consented("interview_in_person")`, as for every module. Interviewees the
  roster does not list for the module are left out until the project lead rules (private note).
- **Coding:** as the codebook's Procedure. Coders see the recording key, never the study ID. The join
  to sensor and survey data happens after coding is frozen.
- **Tier:** exploratory. The analysis plan frozen on 2026-10-19 does not cover interviews, so
  nothing here carries error control. A clear result becomes a candidate for the next-phase
  preregistration.

## Exploratory analyses, fixed before coding

Written on 2026-10-21, before any interview is coded. A change after coding is logged with its
reason.

1. **Convergence with the survey:** `M_everyday` against the trust and lust composites (Spearman,
   with bootstrap interval). The question is whether the interview and the questionnaire read the
   same thing.
2. **Opening over the academy and behaviour:** `D_academy` against presses per exposure hour (NB2,
   exposure offset), co-located press pairs per person (collective moments), network strength and
   cross-course share. Interview day enters as a covariate: later interviews have seen more academy.
3. **The academy against everyday life:** `D_vs_everyday` against the survey's gradient items.
4. **Placed episodes:** for opening and closing episodes placed on a day or programme item, the
   person's presses and company in that window against their own other days (within person, as
   in the exploratory company analysis).
5. **Descriptives:** distributions of the state codes, of `direction`, and of opener and closer
   categories. Each is reported only for cells of 5 people or more.

**Changed after coding** (2026-10-21): `opened` (the coded direction is "opened") is added as a
second predictor in analysis 2, because coders reported that the 4-versus-5 rule leaves the
arrival-to-now difference at zero for people who describe opening. Analysis 4 places episodes by
their coded date, and the 24–27 Aug sensitivity drops episodes placed on those days as well as
interviews held on them.

Sensitivities: drop `led` codes; drop `low`-confidence codes; drop interviews on 24–27 Aug, the
days with low beacon coverage, from analyses 2 and 4.

## Tasks

- [x] Join recordings to study IDs (spine), with a beacon check against the researcher's tag
- [x] Codebook draft
- [x] First coder over every linked interview; second coder over a random fifth
- [x] Agreement report (weighted kappa on state codes, per-code agreement on the rest)
- [ ] Human check of `low`-confidence codes and a random fifth
- [x] Analyses 1–5, private note with results
- [ ] Project lead reviews the codebook and the results; decide what enters the preregistration
