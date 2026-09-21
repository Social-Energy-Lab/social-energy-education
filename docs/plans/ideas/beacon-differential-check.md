# Beacon ingest: differential check against the delivered `Output/` tables

**Priority:** high

**Goal:** establish whether `social_energy.beacons` reproduces the upstream-derived tables that arrived with the beacon delivery, and explain every disagreement. Until this is settled we do not know which of the two is right, and no analysis should depend on either.

## Context

The full beacon delivery arrived on 2026-09-20 and is imported (see the study's `raw/beacons/IMPORT.md` on the researcher's machine). It contains 105 raw logger `.log` files for 13–29 Aug, and an `Output/` folder of tables somebody upstream already derived from them: daily `contacts_*.csv` (`ID1,ID2,RSSI,Contact Local Time`), one `self_reports.csv` (`ID,Local Time`) and one `eco_sessions.csv` (`ID,Enter Local Time,Exit Local Time`).

That folder is the first independent implementation of the same transformation our ingest performs. It is a cross-check, not a substitute: it has no readouts table, no boot context, no per-record flags, no QA accounting and no `Status` byte, so storage-full data loss is invisible in it. But where we disagree, one of us is wrong.

The log format itself is confirmed: a census over a real log found all seven record kinds in `KINDS` and no unknown record type, so the parser matches the instrument.

## First result (2026-09-20, one day only)

Ingesting the twelve 29 Aug logs (113 MB, 1.79 M lines) and comparing `ok` self-reports against the whole-camp `self_reports.csv`:

- 52 of our 170 unique `(beacon, time)` pairs match upstream **exactly, to the second**.
- The remaining 118 are **more than an hour** from any upstream row for the same device; median offset about 14.6 hours.
- Every device we produced self-reports for does appear in the upstream file, so this is not a missing-device problem.
- None of the 118 carry `reference_after` or `pre_reboot`. **Our flags do not catch this.** That is the part that matters: if the discrepancy is our bug, `ok` is currently overconfident.
- The 52 matches come from 2 readout sequences; the 118 mismatches from 8.

Exact agreement on some records and a multi-hour offset on others points at uptime-to-wall-clock resolution across reboots, not at parsing, rounding or timezones.

## The confound, and why this is not yet a verdict

The run above covered one day in isolation. Two things make that an unfair test:

1. A tag stores records until a base station reads it out, so a record from 27 Aug can appear in a 29 Aug log. Restricting to one day's logs cuts records off from the anchors that date them. The run reported 164,272 lines before its first clock reference and 350,587 contacts it could not place in time.
2. `duplicate` is computed within a single ingest run. Records read out twice across different days cannot be detected per-day, so a per-day run can over-count.

Both are fixed by one pass over all 105 logs. **That is the next step, and it is blocked on memory**: one day produced 1.79 M contact rows from 113 MB, so the full 3.4 GB is on the order of 55 M rows, and the machine that ran this has about 4 GB free.

## Where the offsets probably come from (2026-09-20, from the upstream repo)

Reading the upstream `postprocessing.py` (see `docs/context/instruments/beacons.md`, "The upstream `Output/` tables") gives a concrete hypothesis for the multi-hour offsets:

- Upstream dates an event against the nearest anchor for that tag, and **retries against the previous boot's anchor** when the first attempt lands more than 600 s in the future *and* the record's timer is a new high for that older boot.
- Our ingest marks `pre_reboot` only from uptime drops seen **inside** a readout. A record stored before a reboot and exported in a later readout has no such drop to detect, so we resolve it against the current boot's anchor and it silently comes out hours off, unflagged. That matches the observation exactly: 118 records off by a median 14.6 h, none carrying `pre_reboot` or `reference_after`.

So the disagreement is likely ours, and the fix is a rule, not arithmetic: when an event resolves into the future beyond tolerance, retry against the previous anchor under a high-water guard, and flag the retry rather than accepting the first answer. Note the direction of the check too: upstream *skips* records it cannot place (`sanity_findings.csv`), where we flag and keep them, so counts will not match even once times do.

This is a hypothesis read off the upstream code, not yet a verified cause. Confirm it on the full-camp run before changing the ingest.

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
