# The explorer runs locally, on an ID-free bundle

**Date:** 2026-10-01 · **Status:** adopted

## Context

The research team wanted an interactive view of a study's co-presence network, places and
self-reports, with the analysis parameters as live controls. The data describes minors at
individual level.

Removing study IDs does not make a co-presence network anonymous. In a camp of a few dozen people
whose course and time of day are known, a participant can recognise themselves and others from
the pattern alone: who is always on the edge, who was with whom late at night. Course labels make
that easier. Removing IDs is pseudonymisation, and the ethics approval allows pseudonymised data
only to authorised research staff, on access-restricted systems, and only aggregated or fully
anonymised data in publications.

## Decision

- **Team mode is local.** `social-energy explore` serves the app on `127.0.0.1` only and refuses
  requests naming any other host, so neither the network nor a web page rebinding its own name can
  read the bundle. Nothing is hosted.
- **The bundle carries no identifiers.** `write_bundle` writes shuffled node indices, shuffled from
  OS entropy so the order cannot be recomputed from this public code, and never writes the mapping
  back to the spine. It is written only under `$SOCIAL_ENERGY_DATA`; `.bin` is a data suffix for
  the perimeter check.
- **Filters happen once, at export**, in study code (`studies/<id>/analyses/explorer_export.py`),
  with the same consent and exclusion filters as the analyses. The browser chooses within data
  already allowed and cannot widen it.
- **A public mode is a separate step**: aggregate views only, or a synthetic camp, once the project
  lead and the data protection office have said what counts as fully anonymised
  (`docs/plans/ideas/explorer-public-mode.md`).

## Consequences

- Each collaborator who uses team mode needs the data root on their own machine.
- Screens and screenshots of team mode are pseudonymised data and are handled as such.
