# Structured, name-free field log for future field phases

**Priority:** medium

**Goal:** a template (spreadsheet or simple form) that captures device handouts and swaps, exclusions, programme events and instrument changes as ID-only rows, which import directly into the spine.

## Context

At DSA 2026 the ground truth was written as prose with names. It is rich but must be transcribed by hand and cannot leave the researcher's machine. START-Stiftung and SUPER YOU are next. Capturing the same facts in a structured, ID-only form removes both problems.

## Design / approach

- Four sheets matching the spine files: assignments, exclusions, events, instrument changes. Dropdowns for device IDs, locations, reasons. Local wall-clock times.
- `social-energy import-fieldlog <xlsx>` validates and writes spine YAML.
- Keep a free-text "observations" column that is **never** imported (qualitative notes stay with the researcher).

## Open questions

- `[unknown: which tool the researcher will have on site (laptop spreadsheet, phone form)?]`
