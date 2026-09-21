# Theory: what "social energy" means here, and what could measure it

Background for anyone designing an analysis, in our own words and based on published work. The
team also holds unpublished manuscripts; they are **not** summarised here, and the reading of
them stays in the private context library. Mappings from concept to measurement are proposals
until the research team confirms them, marked `[inferred]`. The research design itself is in
[project.md](project.md).

## The concept

Background for the constructs this repo measures. It stays at the level of Rosa's **published**
work. The detailed reading of the unpublished drafts, which the team has but cannot circulate,
lives in the private context library (`_team/theory-notes.md`) and is deliberately not
reconstructed here.

- **Definition.** Social energy is, loosely, the *capacity to get things done in the world*. It
  cannot be located in individuals and is not the sum of individual energies: it **circulates**
  in interaction. The term follows Greenblatt's "circulation of social energy". Rosa proposes it
  as the missing link between structure and culture.
- **Not input–output, not zero-sum.** After a good meeting, rehearsal or party *everyone* leaves
  energised; after a bad one everyone is drained. It is not that some take energy from others.
- **Lineage.** Durkheim's *collective effervescence* (ritual interaction produces energy beyond
  individual energies) and Collins' *emotional energy* (an outcome of interaction rituals,
  empirically measurable and **unequally distributed**, so it reproduces stratification).
- **Normatively neutral.** Unlike resonance, which Rosa treats as a normative criterion,
  circulating energy can also power destructive movements.
- **Resonance** (Rosa 2016/2019) has four elements: *affection* (being touched),
  *self-efficacious response*, *transformation* (both sides change) and *uncontrollability* (it
  cannot be engineered, predicted or accumulated). **Alienation** is a "relation of
  relationlessness"; in energy terms, a distortion in the flow.
- **Perspectival dualism.** Resonance criteria can be assessed from the 3rd-person perspective,
  but resonance and alienation differ in the *dynamics* of a relationship, which needs the
  1st-person perspective too. This is why the design combines sensors with interviews.
- **Lust for life** (the pull outward, towards the world) and **trust in life** (the readiness to
  let the world in, to be touched and to be able to respond) are the two constructs the survey is
  built around; they are blocks C and B of the questionnaire.

### The empirical gap

Find the conditions under which social energy begins to circulate, and the mechanisms that block
or divert it. That is what the project and this repo address.

## Candidate operationalisations

| Construct | Candidate indicator | Source | Status |
|---|---|---|---|
| A moment of being moved: "something moved me", positive or not | self-report presses (who, when), and what surrounds them (who was near, where, which programme item, physiology) | beacons (+ spine, EDA) | instruction team-defined; indicator `[inferred]` |
| Circulation vs. blockage in a group | co-presence network density, turnover, fragmentation, mixing across courses, over time | beacons | `[inferred]` |
| Embedded vs. peripheral participation | a person's network position (strength, k-core, participation), time without others | beacons | named in paper framing; metrics `[inferred]` |
| Use of spaces and programme (dimension VI) | presence per location/zone per programme item; self-reports per person-hour by zone | beacons + spine events | `[inferred]` |
| Collective moments / effervescence | self-reports clustering in time and space among co-present people; group sound | beacons, AudioMoth | `[inferred]` |
| "Sound of solidarity" (Gregory) | level and spectral features of group sound (singing, clapping, laughter) | AudioMoth | named in ethics application |
| Arousal / engagement | EDA phasic responses (SCRs), tonic level | EDA wearables | named in design; arousal ≠ resonance |
| Physiological synchrony | EDA/heart-rate coupling between co-present wearers | EDA wearables | named in design (cardiac synchrony, Høffding); `[inferred]` for EDA |
| Trust in life (baseline) | belonging, trust, perspective-taking, relationships, well-being, sense of identity | survey block B | the questionnaire's own trust block |
| Lust for life / agency (baseline) | self-efficacy (general and resonance-oriented), openness, proactive learning, cooperation, initiative | survey block C | the questionnaire's own agency block |
| Gradient | "not enough room in my current life for …" items attached to several scales; social-status now vs expected at 30 | survey | scored separately, never inside the parent scale |
| Lived experience, reasons | phenomenological + AI interviews | interviews | qualitative |

## Settled

**Where self-efficacy belongs** (2026-09-20, Mahdi). Analyses follow the **survey's own structure**: block B is *trust in life*, block C is agency and motivation / *lust for life*, and self-efficacy — general, resonance-oriented, creative, academic, social — belongs to **lust for life**. The resonance-oriented scale is grounded in trust in oneself as well as in life, but is scored under C. Gradient items are scored separately, whichever block they hang off.

## Open tensions

1. **Conserved vs. circulating energy.** The thermodynamic framing (energy as a conserved state quantity with a balance) sits uneasily with Rosa's non-zero-sum, non-storable circulating energy. If everyone can gain, a first-law balance does not hold. A system boundary for "the academy" is not defined. Which quantities could serve as state variables, and where the boundary lies, is **part of the research** (2026-09-20, Mahdi) — not a decision waiting on the team.
2. **Arousal is not resonance.** EDA and heart rate cannot tell resonance from stress or overwhelm. The 1st-person perspective has to disambiguate.
3. **Proximity is not interaction.** BLE co-location at the thresholds used is much denser than face-to-face conversation (Génois & Barrat 2018).
4. **Measuring changes the setting.** Asking people to mark resonant moments shapes what they notice; resonance is uncontrollable by definition. The instruction also changed during the first days of the academy. Participants can reasonably wonder who will see their presses, so press counts are never treated as a performance measure and never reported per person.
5. **Selection.** DSA is selective. RQ4 (disadvantaged groups) needs the other settings.
6. **Educational success (H2)** has no indicator in the DSA data yet. A follow-up wave is possible but **not planned** (2026-09-20, Mahdi); the team will revisit it no earlier than November 2026. Until then H2 stays without an indicator.

## Selected references

- Rosa, H. (2013). *Social Acceleration.* · (2016/2019). *Resonance.* · (2020). *The Uncontrollability of the World.* · (2021/2024). "Best Account", in Reckwitz & Rosa, *Late Modernity in Crisis.*
- Rosa, H. (forthcoming). "Acceleration, Resonance, Energy: The Missing Link in Critical Theory", in Gros & Susen (eds.), Penn State UP.
- Brennan, T. (2000). *Exhausting Modernity.* · Ostwald, W. (1909). *Energetische Grundlagen der Kulturwissenschaft.*
- Durkheim, É. (1912). *The Elementary Forms of Religious Life.* · Collins, R. (2004). *Interaction Ritual Chains.* · Greenblatt, S. (1988). *Shakespearean Negotiations.*
- Høffding, S. et al. (2023). Into the Hive-Mind: shared absorption and cardiac interrelations in string quartets. *Music & Science.*
- Lee, V. (2021). Youth engagement during making: EDA and first-person video. *Information and Learning Sciences.*
- Gregory, S. W. — "sound of solidarity" (vocal frequency accommodation in groups).
- Cattuto, C. et al. (2010). *PLoS ONE* · Génois, M. & Barrat, A. (2018). *EPJ Data Science* · Sekara, V. & Lehmann, S. (2014). *PLoS ONE.*
