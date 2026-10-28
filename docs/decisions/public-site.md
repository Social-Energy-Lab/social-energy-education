# The public site shows the animated network from a release asset

**Date:** 2026-10-21 · **Status:** adopted

## Context

[explorer-local-only.md](explorer-local-only.md) kept the co-presence network on the team's
machines because removing IDs is pseudonymisation, not anonymisation. The people who took part,
and the wider lab, still have no way to see what the beacons showed. A public page serves them,
and the research-group talk on 2026-11-03 is the occasion.

Álvaro and Mahdi approved showing the animated network publicly. Álvaro accepted the residual
re-identification risk: a participant may recognise their own course cluster from its size and
timing. `[unknown: when and in which channel did Mahdi approve publishing the animated network, and does the approval cover the aggregate result numbers too?]`

## Decision

- **What is published** is the public bundle (`social_energy.site.write_public_bundle`): nodes as
  shuffled indices with a shuffled course index (no course keys or names), pairs pre-filtered to
  the analysis close-range threshold with no RSSI, seen counts, presses at 5-minute bin
  resolution, no night bins (00:00-06:00 local), and meta with days, phases and special-day labels.
  Plus story-chapter aggregates, with every cell under 5 people dropped.
- **Never published:** study IDs or any mapping to people, staff, rooms or location labels,
  course names, QA flags, notes, seconds-resolution presses, interviews, survey answers per
  person, EDA, per-room acoustics, any course-level result, any lookup of a person.
- **Release-asset route.** The study's `site_export.py` builds the asset locally; it is validated
  (`validate_site_data`: `mode: public`, no field outside the public schema) and uploaded as the
  GitHub release `site-data-dsa-2026`. `pages.yml` overlays it on the synthetic build and
  validates again. The asset never enters git, not even in derived form.
- **Takedown.** Delete the release and re-run the workflow: the page returns to the synthetic
  demo. This limits further exposure; it cannot recall copies already made.
- **Copy rule.** The findings' numbers live only in the asset. The copy in git uses placeholders.
- **Team mode stays local**, unchanged.
- **The team-meeting deck** (`/deck/`, added 2026-10-28, proposed: holds until Álvaro has
  reviewed its real-data preview) is part of the same site and the same asset. It widens what is
  published by camp-level aggregates only: records in and kept per source, EDA around presses
  (one series, shuffled-press band), share of interviewees naming each membrane opener or closer,
  and the gradient analysis's pair correlations and co-press shares. Every row carries its people
  and the small-cell rule applies; per-person EDA, interview codes or survey answers stay
  unpublished. Its numbers follow the copy rule above.

## Consequences

- The site asset is the only sanctioned route for derived data to reach the public.
- Anyone holding the asset or a saved page holds the public bundle; takedown cannot undo that.
- Álvaro reviews a local preview of the real-data build before the first upload.
