# Explorer: the person view

**Priority:** high — target: in the team's hands before the research-group talk on 2026-11-03
**Gate:** the PR's review by Álvaro
**Next:** Álvaro and Mahdi go through a few people on the real bundle and say which follow-ups matter

**Goal:** an internal dashboard in the local team explorer for going through one person, one
moment and the people around them: the membrane as the survey and the interview describe it,
the person's academy as the sensors saw it, and their special moments, first-person (presses)
and third-person (EDA), with a way to jump to the people who were close and back. It follows
the research team's wish list for a data-exploration dashboard (private source documents).

## Design

- **Local only, one shuffle, study IDs on screen.** The view is a second tab of
  `social-energy explore`; it reads the same bundle, keyed by the same shuffled node index as the
  network view, and names each person by study ID from `person.json` (added 2026-10-29)
  ([`explorer-local-only.md`](../../decisions/explorer-local-only.md)). Its data is `eda.bin` and
  `person.json` (`social_energy.explorer.person`), written only in team (or synthetic) mode.
- **Who is in it.** The bundle's nodes: participants with beacon consent. Each part of a person
  is shown only for its own module's consent (survey, interview, EDA, self-report), outside
  exclusion windows; staff are not in the bundle.
- **Reuse, not re-derive.** `studies/dsa-2026/analyses/explorer_export.py` reads the composites
  from `confirmatory.py`, scale scores and recoded items as the scoring wrote them, the interview
  codes `exploratory_membrane.py` reads, the EDA minutes of `exploratory_eda.build_minutes`, and
  the programme windows of `exploratory_presses.event_windows`.
- **Codes only.** No transcript or field-note text. The writer refuses any membrane value that is
  not a number, a flag, a short token or a date.
- **EDA moments are a working rule**, documented in the view as exploratory: a usable minute
  whose SCR rate is at least 2 SD above the person-day's mean (days with at least 30 usable
  minutes), merged within 2 minutes; either SCR rule. Not movement-adjusted, not validated.
- **Close** is the explorer's own: the pair's strongest reading in the 5-minute bin at or above
  the close-range slider. The view says that beacons cannot tell face-to-face.

## Tasks

- [x] Bundle additions, consent filtering, synthetic person data, `explore --demo` (2026-10-28).
- [x] The view: picker, profile, interview codes, timeline, moment drill-down with breadcrumb,
      special moments per day and phase against the camp (2026-10-28).
- [x] Study IDs in the picker, header, breadcrumb and network tooltip; find by study ID;
      `#person=<study ID>` links (2026-10-29).
- [ ] Review with the research team.

## Follow-ups

- **Interview text.** The view shows codes only. Showing transcript passages at a moment (the
  wish list asks for mentions in the interviews of the people involved) needs a decision on text
  access in team mode first: which passages, behind what consent, and whether text may sit in a
  bundle at all.
- **People without beacon consent** have no node and so no person view, although some consented
  to the survey, the interview or EDA. Including them needs nodes that the network view does not
  draw.
- **EDA moment rule.** Calibrate the threshold with the research team, add movement adjustment
  as in `exploratory_eda.py`, and report how many moments the rule finds per person-day.
- **Post wave.** The schema and view take a second survey wave; none was fielded at DSA 2026.
- **Programme labels** come from the spine verbatim. If a label ever names a person, the export
  should map it to its kind.
