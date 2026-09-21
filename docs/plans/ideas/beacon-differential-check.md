# Beacon ingest: differential check against the delivered `Output/` tables

**Priority:** high

**Goal:** establish whether `social_energy.beacons` reproduces the upstream-derived tables that arrived with the beacon delivery, and explain every disagreement. Until this is settled we do not know which of the two is right, and no analysis should depend on either.

## Context

The full beacon delivery arrived on 2026-09-20 and is imported (see the study's `raw/beacons/IMPORT.md` on the researcher's machine). It contains the raw logger `.log` files for the whole camp, and an `Output/` folder of tables somebody upstream already derived from them: daily `contacts_*.csv` (`ID1,ID2,RSSI,Contact Local Time`), one `self_reports.csv` (`ID,Local Time`) and one `eco_sessions.csv` (`ID,Enter Local Time,Exit Local Time`).

That folder is the first independent implementation of the same transformation our ingest performs. It is a cross-check, not a substitute: it has no readouts table, no boot context, no per-record flags, no QA accounting and no `Status` byte, so storage-full data loss is invisible in it. But where we disagree, one of us is wrong.

The log format itself is confirmed: a census over a real log found all seven record kinds in `KINDS` and no unknown record type, so the parser matches the instrument.

## First result (2026-09-20, one day only)

A first run over a single day's logs, comparing `ok` self-reports against the delivered
`self_reports.csv`, found **two populations**:

- one where we agree with the upstream file **exactly, to the second**;
- one where our timestamp is **many hours** away from any upstream row for the same tag.

Every tag we produced self-reports for does appear upstream, so this is not a missing-device
problem. None of the mismatched records carry `reference_after` or `pre_reboot`. **Our flags do
not catch this.** That is the part that matters: if the disagreement is our bug, `ok` is
currently overconfident.

Exact agreement on some records and a multi-hour offset on others points at uptime-to-wall-clock
resolution across reboots, not at parsing, rounding or timezones. The matches and the mismatches
also separate cleanly by readout sequence.

Counts are in the private half (`dsa-2026/notes/record-findings.md`), per
`docs/decisions/public-private-repo-pair.md`.

## The confound, and why this is not yet a verdict

The run above covered one day in isolation. Two things make that an unfair test:

1. A tag stores records until a base station reads it out, so a record from one day can appear in
   a later day's log. Restricting to one day's logs cuts records off from the anchors that date
   them, and the run left a large share of contacts unplaced in time for exactly that reason.
2. `duplicate` is computed within a single ingest run. Records read out twice across different
   days cannot be detected per-day, so a per-day run can over-count.

Both are fixed by one pass over all the logs. **That is the next step, and it is blocked on
memory**: the delivery is several gigabytes of text and expands to tens of millions of contact
rows, well past the free memory on the machine that ran this.

## Next steps

1. Make a full-camp single-pass run possible. Either convert `ingest_logs` to a streaming/lazy polars pipeline writing parquet per table, or add a two-pass mode that collects clock anchors and reboots from all logs first and then resolves records in chunks. The anchor pass is small and cheap; only contacts are large.
2. Re-run the self-report comparison over the whole camp. Self-reports and eco sessions are the right first targets: small, whole-camp files upstream, and directly meaningful.
3. Only then compare contacts, day by day, against `contacts_*.csv`.
4. Write the resolved disagreement up as a decision record, and turn whichever case broke into a regression test with a synthetic fixture that reproduces it.
5. If ours proves wrong, the flags must be fixed too, not just the arithmetic: these records passed `ok`.

## Notes

- Keep device IDs and person-level counts out of this repo. Aggregates only.
- This check compares device-keyed tables on both sides, which is the right level for it. Anything person-level must first go through the cleaning step in `beacon-device-reuse.md`: tags were reassigned mid-camp, so a beacon ID is not a person.
- Six 13–15 Aug logs are `_cleaned` by an upstream step of unknown content; treat their records as lower confidence until that question in `questions-for-research-team.md` is answered. The upstream repo contains no cleaning script, so it was done by hand or by something unpublished.
