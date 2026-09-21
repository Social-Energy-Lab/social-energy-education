# Study: DSA 2026, Schwäbisch Gmünd

First field phase of the social-energy PhD project. This file holds context only. **No data, no names, no person-level facts.** The data is under `$SOCIAL_ENERGY_DATA/dsa-2026/`.

## Setting

- **Deutsche SchülerAkademie** (Bildung & Begabung): a residential 16-day academy for highly motivated upper-secondary students, most aged 16–19 (some are minors). About 6 courses of about 16 students, each with two course leaders. There are also an academy leadership team, musicians and guests.
- **Dates:** arrival 2026-08-13, departure 2026-08-29. Timezone Europe/Berlin (CEST).
- **Ethics:** FSU Jena ethics committee. Consent is modular per data module, with guardians' consent for minors. The ID ↔ name code list is deleted no later than 2028-09-30, after which the data are anonymous. Only aggregated or anonymised results may be published. Small groups are merged or suppressed.

## Programme rhythm (typical day)

| Time | Item |
|---|---|
| ~07:30–08:30 | breakfast (dining hall) |
| 08:30 | **plenum** (whole academy, main hall) |
| ~09:00–12:15 | course sessions (course rooms), coffee break mid-morning |
| ~12:15–13:30 | lunch |
| ~13:30–16:30 | cross-course activities (**KüA**) and choirs (main hall); academy team meeting |
| ~16:30–18:30 | course sessions |
| ~18:30 | dinner |
| 19:30 / 21:00 | evening KüAs (music, theatre, sport, games, talks) |
| late night | informal gatherings (music room, lounges, campfire) |

Notable days:

- **18 Aug:** excursion day (no sensors outside the site).
- **21 Aug:** phones collected in the morning plenum.
- **22 Aug:** Rotation day (courses present to each other), then an all-academy sports festival and a party.
- **23 Aug:** workshop concert (reported as emotionally intense).
- **27 Aug:** choir concert in a church in town.
- **28 Aug:** closing show ("Bunter Abend"), party.
- **29 Aug:** departure.

Sundays follow a different schedule (brunch, afternoon plenum). Spontaneous, unplanned gatherings are recorded as events in the local spine.

## Data modules

| Module | What | Who | Status in toolkit |
|---|---|---|---|
| Beacons | contact logs + room presence + self-report button + eco sessions | nearly all participants and staff; ~57 room/zone tags | ingest ✅ (`social_energy.beacons`); full delivery imported 2026-09-20 (13–29 Aug), differential check against the delivered tables open (`docs/plans/ideas/beacon-differential-check.md`) |
| EDA (Shimmer) | skin conductance (+HR?) during daytime sessions, 15–28 Aug | ~13–15 consenting participants | planned |
| Acoustics (AudioMoth ×2) | scheduled recordings in dining hall and main hall | spaces, not persons | features + verified deletion ✅ (`social_energy.acoustics`) |
| Survey (SurveyJS on zeitgeist-platform) | baseline questionnaire, right after the AI interview | 88 respondents after exclusions | download ✅ (`fetch-zeitgeist`), ingest ✅ (`social_energy.survey`); scoring planned |
| Interviews | in-person during (DJI Mic 3); AI voice before (zeitgeist-platform, 99 calls after exclusions) | subsets | AI interviews: download ✅ (`fetch-zeitgeist`); content is qualitative, out of scope for code |
| Observations | course-leader impressions (trust / lust for life) | consenting participants | qualitative |
| Field log | programme, device ledger, instrument changes | — | transcribed locally into the spine |

## Consent (modular)

- Consent was given per module. For leaders the final (Aug 2026) form lists QL-1 in-person interviews, QL-2 AI interviews, QL-3 questionnaire and QA-1 beacons. See [`docs/context/project.md`](../../docs/context/project.md#data-modules-as-approved).
- **Participants kept the April module scheme.** The team's own consent record, a roster handed over on 20 Sep 2026, has one column per module: QA-1 smart button, QA-2 EDA, QA-3 acoustics, QA-4 badges, QA-5 body cameras. So the scheme was dropped for leaders, not for participants. QA-5 was collected as a consent answer but the module never ran: there were no body cameras.
- QA-1 and QA-4 are recorded as **two different modules with different counts**, and some people who wore a tag consented to one but not the other. Until the research team says what separates them, the spine reads QA-1 as the button (`self_report`) and QA-4 as the proximity tag (`beacons`), and a co-presence analysis must filter on `spine.consented("beacons")` rather than on "a tag exists". `[unknown: what QA-4 "badges" covers that QA-1 does not]`
- The local spine records each person's consent as `social_energy.spine.Module` values. For leaders: QL-1 → `interview_in_person`, QL-2 → `interview_ai`, QL-3 → `survey`, QA-1 → `beacons` + `self_report` (their form has one beacon module) `[inferred]`. For participants: QL-1 → `interview_in_person`, QL-2 → `interview_ai`, QL-3 → `survey`, QA-1 → `self_report`, QA-2 → `eda`, QA-3 → `acoustics`, QA-4 → `beacons`.
- Withdrawals and early departures are recorded only in the local spine (exclusion windows), never here.

## The self-report button

- **Instruction as given at the academy:** press when a moment has *moved you, done something to you*. **It does not have to be positive**; overwhelm counts. The research lead's gloss is that the membrane became more (or less) permeable, and/or agency became possible.
- The instruction evolved:
  - A pre-academy presentation described "shaking the name tag" for special, energising moments.
  - At the academy participants were told to **press once for ~3 s, until the tag glows red**, and — if they had pressed by accident — **to press again for ~3 s to take it back**.
  - The "not necessarily positive" clarification was given in the plenum on 14 Aug (08:45) and repeated on 15 Aug (09:00).
- Treat presses before 14 Aug 08:45 separately.
- **A second press shortly after a first one is a retraction, not a duplicate.** The pair cancels: drop both, flag them, and never merge them into one report. An earlier version of the field log said participants were told to press twice; the 20 Sep re-export corrects that, and the two readings imply opposite cleaning rules, so the correction matters. `[unknown: how long "directly afterwards" is — the instruction gives no window; the firmware's own repeat behaviour on a held button is a separate effect]`
- Instrument-level caveats noted in the field log:
  - reactivity: concern that individual press counts might become visible to others;
  - accidental presses were reported;
  - long "energy moments" are hard to mark with a single press;
  - a few buttons broke and were replaced (the device ledger is in the local spine).

## Instrument timeline (instrument-level facts; person-level ledger is local)

Machine-readable in [`study.yaml`](study.yaml). In short:

- **13 Aug 11:30:** all person and location tags installed as participants arrive.
- **14 Aug ~10:20:** the logger failed to write for a few minutes (data stayed on the tags).
- **14 Aug 21:00:** all tags reflashed to enable eco mode, which had been missing before.
- **15 Aug ~01:30–11:45:** several outdoor tags found inactive and activated.
- **15 Aug:** logger script updated after corrupted output was noticed.
- **15 Aug 17:45:** main-hall and hall–dining-corridor location tags reflashed **without** eco mode and with the accelerometer off.
- **15 Aug 20:17:** upstream logger fix for the ID 48–57 bug.
- **16 Aug:** outdoor tags wrapped or removed for rain at times.
- **18 Aug 16:10:** a location tag added to a course room that had none before (room 2.01).
- **~18–20 Aug:** one outdoor tag failed from water ingress and was removed. Another was moved.
- **20 Aug 12:02:** a new outdoor tag at the tennis/basketball courts.
- **21 Aug 03:36:** some tags suspected of not logging properly in one lounge; a base-station read-all mode was used.
- Battery changes throughout, each taking a tag out of use for minutes to hours. These are recorded in the local ledger.
- **29 Aug:** all location tags collected, 15:40–18:15.

## Identity conventions

- **Study ID = the participant's first beacon ID.** After an email mix-up, the beacon ID was declared the authoritative study ID.
- A study ID whose tag was never issued leaves that number free, so the tag numbers below the person range that appear in the logs are location tags or spares, never people. The local spine is the only place that says which.
- Replacement tags map to the same study ID over time (spine `assignments.yaml`).
- Location tags: IDs 114–170, plus a few low IDs and movable outdoor tags. See [`locations.yaml`](locations.yaml).

## Open questions for the research team

Consent is now recorded per person and module in the team's roster (20 Sep 2026), which the local spine follows. The one consent question left is what separates QA-1 from QA-4 (above); the rest of the open items live with the data, in the spine's `open_questions.md`.

- `[unknown: firmware commit + settings flashed at arrival; exact list of setting changes]`
- `[unknown: were location tags read out, and do they hold contact data?]`
- `[unknown: survey post-wave fielded?]`
- `[unknown: EDA export format]` (the device-distribution plan per day is coming from Mahdi, no date yet)
- `[unknown: AudioMoth schedules per day; do WAVs still exist?]`
