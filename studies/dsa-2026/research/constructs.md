# Constructs → measures: DSA 2026

A working table linking the theory to concrete, computable measures. Status column: `proposed` (agent/analyst idea), `agreed` (research team confirmed), `rejected` (with reason). Only the research team moves an entry to `agreed`.

| Construct | Measure | Definition sketch | Data | Status |
|---|---|---|---|---|
| Membrane opening (moment) | self-report event | a press (double press = one report) by a consenting participant, outside exclusion windows | beacons | proposed |
| Co-presence | dyadic co-presence minutes (`presence.copresence`) | minutes in which A heard B **or** B heard A at ≥ threshold, per time bin | beacons | proposed |
| Close contact | strong-signal co-presence | co-presence with RSSI ≥ a stricter threshold (calibration needed) | beacons | proposed |
| Place | person's zone per time bin (`presence.room_per_bin`) | strongest location tag heard in the bin, with a minimum-evidence rule | beacons + locations.yaml | proposed |
| Embeddedness | daily network position | strength / k-core / participation across groups in the daily co-presence graph | beacons | proposed |
| Circulation (group) | network turnover and mixing | Jaccard turnover of dyads between bins; cross-course mixing ratio | beacons + course membership | proposed |
| Collective moment | self-report cascade | ≥ k presses within Δt among people co-present in a zone | beacons | proposed |
| Arousal response | SCR rate / amplitude | phasic EDA features per window, wear-filtered | EDA | proposed |
| Synchrony | physiological coupling | windowed cross-correlation of EDA between co-present wearers | EDA + beacons | proposed |
| Group sound | acoustic features | level and spectral features per window in hall/dining hall | AudioMoth | proposed |
| Trust in life (baseline) | survey **block B** scale scores | belonging, trust, relationships, climate, well-being, sense of identity | survey | proposed |
| Lust for life (baseline) | survey **block C** scale scores | self-efficacy (general, resonance-oriented, creative, academic, social), openness, curiosity, proactive learning, self-regulation | survey | proposed |
| Gradient | gradient items | felt distance between current and desired state; scored separately | survey | proposed |

## Notes

- **Self-efficacy sits in lust for life** (block C), following the survey's own block logic (2026-09-20, Mahdi; see `docs/context/theory.md`). Resonance-oriented self-efficacy is grounded theoretically in trust in life but is scored under C.
- **Staff presses** (course and academy leaders) are **provisionally analysed separately** from participants' presses (2026-09-20, Mahdi). Not decided; revisit once there are enough presses to compare. Keep the role from the spine on every press so either choice stays possible.
- **Status of this table:** the research team has not reviewed it yet (2026-09-20, Mahdi: "we'll need to think about this"), so **no entry is `agreed`**. Treat everything here as `proposed` until that review.
- Course membership per participant is not yet available; Mahdi will supply it with the study-ID list (no date yet). Mixing measures wait on it.
