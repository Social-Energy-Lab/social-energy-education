# The explorer runs locally, on an ID-free bundle

**Date:** 2026-10-01 · **Status:** adopted · amended 2026-10-21 by [public-site.md](public-site.md)
and on 2026-10-29 (study IDs in the person view, below)

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
- **The network files carry no identifiers.** `write_bundle` writes shuffled node indices,
  shuffled from OS entropy so the order cannot be recomputed from this public code. It is written
  only under `$SOCIAL_ENERGY_DATA`; `.bin` is a data suffix for the perimeter check. The one place
  a study ID appears is the person view's `person.json` (see Consequences).
- **Filters happen once, at export**, in study code (`studies/<id>/analyses/explorer_export.py`),
  with the same consent and exclusion filters as the analyses. The browser chooses within data
  already allowed and cannot widen it.

## Consequences

- Each collaborator who uses team mode needs the data root on their own machine.
- Screens and screenshots of team mode are pseudonymised data and are handled as such.
- Since the person view (2026-10-28), a team bundle also holds one person's whole record under the
  shuffled index: survey scales and items, interview codes, EDA and heart rate per minute, age and
  gender, and the programme's labels. That makes a person easier to recognise than the network
  alone, so the rules above matter more, not less. Each module is filtered by its own consent at
  export and again in `write_bundle`; interview codes pass only as codes (free text is refused);
  person data is written only in team mode, and the public writer and the site's checks never
  carry it.
- Since 2026-10-29, Álvaro asked to see the actual study IDs in the internal dashboard, so the
  team can find a participant and check them against the spine. `person.json` carries each
  node's study ID (no names, no device IDs); the person view and the network tooltip show it, and
  `#person=<study ID>` opens that person. The `.bin` files and `meta.json` stay ID-free, and the
  public bundle never reads `person.json`. Team mode was already pseudonymised data on the
  researcher's own machine; the IDs make it the same data as the spine, which is where it lives.

The amendment changes nothing here: team mode stays local. The public route is the site, built
from the public bundle and a release asset ([public-site.md](public-site.md)).
