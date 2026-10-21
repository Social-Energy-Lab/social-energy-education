# Membrane codebook: in-person interviews, DSA 2026

**Status: draft, proposed by the analyst, not yet agreed by the research team.** Only the research
team moves it to agreed (see [`constructs.md`](constructs.md)). Results coded with this draft are
exploratory.

## What is being coded

From the second week of the academy, the in-person interviews carry a membrane block. The
interviewer introduces the membrane as a metaphor: sometimes we build a thicker, less permeable wall
and withdraw to sort things out alone; sometimes it is thinner and more permeable, and people, but
also nature, music or what we read, reach us. The interviewer then asks, in a varying order and
wording:

1. the person's usual state in everyday life, outside the academy;
2. the state on arrival at the academy;
3. how it developed over the academy, up to the day of the interview;
4. moments in either direction, when it became more permeable or when it hardened;
5. sometimes: what helps when it is thick, and whether the academy's state will carry into life
   afterwards.

Several interviews refer to a lecture on the membrane given to the whole academy shortly before.
Earlier interviews have no membrane block. Both are reasons the codes below are a self-report
*shaped by the setting*, not a neutral measurement. That is recorded per interview (`primed`,
`led`) rather than ignored.

The theory behind it is in [`docs/context/theory.md`](../../../docs/context/theory.md): openness
outward is lust for life, readiness to let the world in is trust in life, and fear or distrust close
the membrane.

## Unit and coder output

One record per interview, for the participant's speech only. Every code carries a **confidence**
(`high` / `medium` / `low`) and **evidence**: the transcript timestamps of the turns it rests on,
never quoted text, so a second coder can check it against the private transcript.

## Codes

### State codes (ordinal)

`M_everyday`, `M_arrival`, `M_now`: the membrane's state in everyday life, on arrival, and at the
time of the interview.

| Value | Meaning |
|---|---|
| 1 | closed: thick, hardly anything gets through, mostly withdrawn |
| 2 | rather closed |
| 3 | in between, or varies so much that no tendency is given |
| 4 | rather open |
| 5 | open: thin or very permeable, easily reached |
| `na` | not asked, or not answered |

Rules:

- Code what the participant says, not the interviewer's offered option. If the participant only
  agrees with a suggestion ("yes, thinner"), code it and set `led` to true for that code.
- "It depends" with a stated usual tendency gets that tendency. With no tendency it is 3, and
  `varies` is true.
- 5 needs the participant to say the barrier is gone or nearly gone, or that they now let almost
  everything and everyone in. A clear opening that the participant qualifies (still careful with
  some, still needs time alone) is 4. When torn between 4 and 5, code 4 and set confidence to
  `medium`. The same edge rule applies at the closed end: 1 only for "hardly anything gets
  through".
- Compare states only within one interview. A 4 here means "rather open, as this person describes
  their own range", not a level comparable across people. Analyses use the changes below, and the
  levels only with this caveat.

### Change codes (derived and checked)

- `D_academy = M_now − M_arrival`: change over the academy.
- `D_vs_everyday = M_now − M_everyday`: the academy against everyday life, a felt gradient.
- `direction`: the participant's own account of the course over the academy: `opened`, `closed`,
  `stable`, `fluctuated` or `na`. It is coded from the narrative, so it can disagree with
  `D_academy`. A disagreement is kept and flagged, not resolved.

### Variants under comparison (added 2026-10-22)

The edge rule above leaves almost everyone at 4 for `M_now`, so the change over the academy rests
mostly on the arrival code. Until the research team picks one, the change is measured three ways,
and the analyses report all three side by side:

1. `D_academy`, as above (strict edge rule).
2. `M_now_lenient`: the state at the interview without the edge rule. 5 is "open: thin or very
   permeable" as the participant describes it, with no need to say the barrier is gone; 4 is a
   clear but modest openness. Same 1–5 scale, same `led`/`confidence`/`evidence`.
   `D_academy_lenient = M_now_lenient − M_arrival`.
3. `change_amount`: how much the participant says the membrane changed over the academy, in their
   own account, whatever the levels: 0 none, 1 slight, 2 clear, 3 strong, or `na`. With
   `direction` it gives `change_signed` (positive when opened, negative when closed, 0 when
   stable; undefined for `fluctuated` and `na`, since the amount carries no sign). Coded with
   `confidence` and `evidence`.

### Selective permeability

`selective`: true if the participant rejects the thick/thin axis for a *what gets through, and
when* account. Examples are open to some people and closed to others, or thick but with people
getting in. Thick and thin are then coded only if the participant also gives them.

### Openers and closers

Multi-label. What the participant says made the membrane more permeable (`openers`) or harder
(`closers`) at the academy. Use these categories; add `other:<short label>` rather than forcing a
fit.

| Openers | Closers |
|---|---|
| `people`: being with others, friendships, belonging | `fatigue`: tiredness, lack of sleep, overload |
| `being_heard`: being listened to, taken seriously, trusted | `withdrawal_need`: needing time alone, social saturation |
| `vulnerability`: others or oneself opening up | `conflict`: tension, exclusion, being left out |
| `course`: course content and work | `pressure`: performance, comparison, expectations |
| `arts`: music, concert, theatre, making things | `safety`: feeling unsafe, discrimination, distrust |
| `nature`: being outside, landscape | `loss`: grief, homesickness, worries from home |
| `programme`: a named programme item (plenum, excursion, sports, evening offers) | `topic`: a hard subject raised in the programme |
| `freedom`: no school pressure, room to be oneself | `end`: the academy ending |

### Episodes

`episodes`: concrete moments the participant describes, each with `direction` (`open` / `close`),
category (from the table above), and a `when` if it can be placed on a day or in a programme item
(`2026-08-24 evening`, `concert`, `excursion day`). Episodes are the bridge to the sensor data. A
placed episode can be compared with the same person's presses and company that day.

### Interview context

- `block`: true if the interview has a membrane block at all.
- `primed`: true only if the academy-wide lecture on the membrane is named, by either side
  ("the talk yesterday", "the lecture", the speaker's name). A vague reference ("the metaphor is
  going around", "you may have heard of it") is not enough.
- `known_elsewhere`: true if the metaphor is said to be known without naming the lecture (it
  circulates, the participant had heard of it before). Never true when `primed` is.
- `led`: per state code, true if the value rests on agreeing with an option the interviewer offered.
- `interview_day`: from the recording, always set. Analyses adjust for it, since later interviews
  see more of the academy.

## Procedure

1. The join of recording to study ID comes from the spine (`interview:<recording>` assignments).
2. A first coder (a model, under the constraint below) proposes codes with evidence and confidence
   per interview.
3. A human checks every `low`-confidence code and a random fifth of all interviews against the
   transcript. Agreement on the state codes is reported as weighted kappa.
4. Disagreements are settled by the human and logged. The codebook is revised only between rounds,
   never mid-round.

**First coder.** The transcripts are not yet cleaned of identifiers, and transcription was kept
local. On 2026-10-21 Álvaro chose a cloud model (Claude) coding the raw transcripts, blind to the
study ID, with an independent second model coding a random fifth for agreement. Confirmed on
2026-10-22: a cloud model may code the raw transcripts.
