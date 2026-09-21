# Beacon tags were reused: device ID is not a person key

**Priority:** high

**Goal:** make it impossible for an analysis to treat a beacon ID as a stable identifier for a person, and add the cleaning step that must run between ingest and any analysis.

## Context

Tags did not stay with one wearer for the whole camp. The field log records replacement tags handed out after a tag was lost or failed, a tag that was lost and later returned to its wearer, and at least one spare tag that sat powered on and unassigned in an office for part of a day. Location tags moved too: some were activated late, some were taken down in the rain and carried around in a pocket before going back up.

Three consequences, in increasing order of how quietly they corrupt a result:

1. **Records with no owner.** A powered-on tag that nobody is wearing still logs contacts. Those records belong to no person and to no room. They are real data about a drawer.
2. **Records attributed to the wrong person.** A tag reassigned mid-camp produces records that belong to one person before the swap and another after. Split at the wrong instant and both people get contaminated.
3. **Two people merged into one.** Any aggregation keyed on the beacon ID rather than the resolved person silently sums two wearers into one row. Nothing errors, nothing looks odd, and the result is wrong. This is the dangerous one, because it survives review — the numbers are plausible.

The default that study IDs equal beacon IDs makes this worse, not better: it is true for most people, so code that conflates the two passes casual inspection and breaks only on the handful of reassigned tags.

This is not a gap in the spine's model. `Assignment` is already a closed interval of `(device, entity, start, end)`, `Spine.validate` already refuses two overlapping assignments for one device and two devices of one kind for one person, and `Spine.resolve` already does a time-windowed join. Transcribing the actual swaps from the field log is `ready/dsa-2026-spine.md`, tasks 2 and 3. **The gap is that nothing forces an analysis to use any of it, and nothing reports what failed to resolve.**

## This is downstream of both implementations

Worth stating plainly, because the two open beacon plans are easy to confuse.

The delivered `Output/` tables have two columns for self-reports (`ID`, `Local Time`) and four for contacts (`ID1`, `ID2`, `RSSI`, `Contact Local Time`). There is no person column anywhere in them. The upstream processing converts record uptime to wall-clock and stops; it never asks who was wearing the tag. Our ingest deliberately stops at the same place, per invariant 4: raw tables speak device IDs, and only the spine resolves identity.

So device reuse is not something the upstream tables get wrong. It is a step neither implementation performs, sitting downstream of both. `beacon-differential-check.md` asks *do the two implementations agree on when a record happened*; this plan asks *whose record is it*. Answering the first does nothing for the second.

They do share a root cause, and it is worth keeping in view. A device's timeline is discontinuous in two independent ways: the tag reboots (battery change, reflash — all tags were reflashed once mid-camp, location tags again later), which resets uptime and breaks the clock; and the wearer changes, which breaks attribution. **The two cut points need not coincide.** A reflash mid-morning and a handover that afternoon are two different splits of the same device's records, and code that handles only one of them will look correct on most tags.

## Design

### 1. Resolution must be loud

`Spine.resolve` currently leaves the output column null when a device has no assignment covering that instant, and says nothing. An analyst who does not check gets silent nulls; one who calls `drop_nulls` throws away the evidence that anything was wrong.

Return a QA dict from resolution, or add a companion function that does, accounting for every row the way ingest already does per invariant 3: rows resolved, rows with no assignment at that time, and rows whose device appears in no assignment at all. The third case is almost always a transcription gap in the spine, not a property of the data, and should be easy to spot.

### 2. Contacts have two sides

A contact resolves twice, observer and observed, and either side can fail. A contact is usable only when both sides resolve and neither is excluded. Resolving one side and forgetting the other produces a half-anonymous edge that looks fine in a table and is meaningless in a network.

Worth checking explicitly: a tag reused across two wearers must never generate an edge between its own two epochs, and a contact between two tags that turn out to be the same device at different times is a bug, not a tie.

### 3. Make the wrong thing hard to write

The cleaning step belongs between ingest and analysis, as a named function that takes canonical tables plus a spine and returns person-keyed tables plus a QA dict. Analyses should start from its output, not from raw ingest output. Add it to the `add-analysis` skill as a required step, and consider a check in `tests/test_architecture.py` in the spirit of the existing toolkit/study rule: an analysis that groups or joins on a device column is a defect.

### 4. Unassigned windows are not exclusions

An exclusion window says "this person's data is not usable here". An unassigned window says "these records are not this person's at all". They need different handling: excluded records stay attributable and are filtered by a visible choice, unresolved records have no owner and cannot enter a person-level table under any filtering choice. Keep the two distinguishable in the output rather than collapsing both into one `ok` column.

## Open questions

- Should resolution be strict by default — raise when any row fails to resolve, with an explicit opt-out — or always permissive with a QA dict? Strict-by-default catches spine gaps early, at the cost of being annoying while the spine is still being transcribed.
- How should a record that falls exactly on a swap instant be assigned? The interval is half-open (`start <= t < end`), so this is already decided by the model; it needs a test rather than a decision.
- Do location tags need the same treatment? A tag carried around in a pocket for an afternoon is a moving "location", which is worse than an unassigned one, because it resolves successfully to a room that the wearer was not in.

## Depends on

`ready/dsa-2026-spine.md` — the actual assignment intervals have to be transcribed from the field log before any of this can be tested against real data. The design work here does not have to wait for that, and the synthetic camp can generate a reused tag to test against.
