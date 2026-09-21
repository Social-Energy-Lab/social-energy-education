# Co-presence networks over the academy

**Priority:** medium

**Goal:** daily and per-programme-phase co-presence networks, with embeddedness (strength, k-core, participation across courses), turnover and fragmentation, as signatures of circulation and blockage.

## Context

The paper framing contrasts participants who become embedded and activated with those who stay peripheral or blocked (`docs/context/project.md`). The academy's rhythm (formal courses and plenum vs KüA and late-night gatherings; excursion, Rotation, concerts) gives natural phases for comparison.

## Design / approach

- Reusable: `social_energy.networks` builds graphs from `presence.copresence` per time window, with metrics (polars/networkx). Tests on synth.
- Study: phases from spine events; per-person trajectories; formal vs informal settings; model eco-mode missingness explicitly.
- Later joins: baseline survey (trust/lust) × embedding; self-report rates × network position.

## Open questions

- `[unknown: RSSI threshold for "close" vs "co-located"; needs calibration (ideas/rssi-calibration.md)]`
