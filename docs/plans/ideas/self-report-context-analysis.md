# First analysis: what surrounds a self-report?

**Priority:** medium

**Goal:** `studies/dsa-2026/analyses/self_report_context.py` describes the moments participants marked as "moved me": where, with whom, during which programme item, and whether presses cluster among people who were together.

## Context

The self-report button is the most direct 1st-person signal in the sensor data (a membrane opening or closing, positive or not). `social_energy.presence.event_context` already gives who and where per press. This analysis adds programme context and clustering.

## Design / approach

- Filters, stated at the top of the script: `ok` records, no exclusion windows, `self_report` consent. Presses before 14 Aug 08:45 are analysed separately; double presses within ~10 s are collapsed `[inferred]`.
- Per press: location zone, programme event (spine events), number of co-present people, their courses (mixing), and whether it happened in an eco-mode window.
- Rates: presses per person-hour by zone and event type, against exposure (time spent there).
- Cascades: presses by ≥ k co-present people within Δt, compared with a time-shuffled null model.
- Output: aggregate tables and figures only, written under `$SOCIAL_ENERGY_DATA/dsa-2026/derived/analyses/`. Small cells suppressed.

## Open questions

- `[unknown: is course membership per participant available for the spine?]`
- `[unknown: are presses by staff analysed together with participants' presses, or separately?]`
