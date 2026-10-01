# Explorer: public mode, and follow-ups from the team-mode review

**Priority:** low — team mode works; this waits on answers from the research team.

**Goal:** a version of the explorer that may be shown outside the research team or published next
to a paper, plus the small follow-ups the team-mode review deferred.

## Context

Team mode (`social_energy.explorer`, `docs/decisions/explorer-local-only.md`) shows individual,
unlabelled participants and runs only on a researcher's machine. A public version must show only
aggregated or fully anonymised data. What counts as fully anonymised for this data is not ours to
decide `[unknown: which explorer views may be published, and in what form?]`. Who may run team
mode on real data is the project lead's call
`[unknown: may the beacon developer run team mode on real data?]`. The course display names in
`studies/dsa-2026/study.yaml` are numbered placeholders
`[unknown: what are the official course titles for DSA 2026?]`.

## Proposal

- **Public bundle:** a `mode: public` bundle with aggregates only (course mixing, zone shares,
  press rates by phase), small groups suppressed everywhere; the app hides the network in that mode.
- **Synthetic demo:** `explorer.synthetic.synthetic_inputs` already feeds a synthetic camp through
  `write_bundle`; a hosted demo on synthetic data shows the method without showing anyone.

## Follow-ups deferred from the review

- Gate the SVG views on a changed bin while playing; they rebuild every frame.
- Unknown-course ties count as cross-course in `model.js`; the Python analysis drops them.
- "Reset to analysis defaults": the window and minimum time are the explorer's own, not the
  analysis's per-day tie; rename or explain.
- Collapse duplicate `(bin, a, b)` pair rows in `write_bundle` (keep the strongest RSSI).
- Drop location labels from `meta.json` (unused by the app; data minimisation).
- Range-check the `u8` day index; resolve the static path in `server.py`; catch a busy port with a
  message; derive the initial playhead from the bin size.
- Light-theme glow is close to course 4's colour.
- Oracle test: assert room counts per location label against `room_per_bin`.
