# Derived tables say which ingest they came from, and a stale one is refused

**Priority:** medium — one silent mix of old and new data already reached reruns (e7c8840), and the public site asset is built from a hand-run chain that nothing checks
**Gate:** decision:Should an analysis or an export stop, naming the command to rerun, when a table it reads was built from an older ingest, spine or study.yaml (recommended), or only print a warning?

**Goal:** every folder under `derived/` carries a small stamp naming the inputs it was built from, readers compare it with what is on disk now, and one command lists what is out of date — so a stale table is caught before a result or the public site is built from it, not found by accident.

## Context

As of `6dad9b6` (2026-11-21).

- **The fix that exists covers two caches.** `e7c8840 fix(dsa-2026): rebuild contact caches after a new ingest, and repair camp_breathes` added `cache_is_current` in `studies/dsa-2026/analyses/copresence_by_phase.py`. Its two callers are `exploratory_rhythm.own_record_bins` and `moments_networks.minute_tables`. The commit message states the failure: a rerun on a new ingest "quietly mixed old dating in".
- **The tables everything else reads have no check.** `copresence_by_phase.build` writes `pairs_<day>`, `seen_<day>` and `rooms_<day>` parquet files; 18 other scripts under `studies/dsa-2026/analyses/` read them through `cp.load_all`, among them `outcomes.py` (the confirmatory outcomes), `site_export.py` (the public site's data asset) and `explorer_export.py`. `load_all` globs whatever is in the folder. `social-energy ingest-beacons` deletes and rewrites `derived/beacons/` (`cli.py`, `shutil.rmtree(out)`) and leaves `derived/analyses/` as it was, and `build` never clears day files a new ingest no longer produces. The other checks in the chain only ask whether a file exists (`outcomes.removed_bins` and `outcomes.ingest_built`, `site_export.read_sound`).
- **The order lives in prose.** The `Handoff` and `Both tiers` lines of `docs/plans/ongoing/dsa-2026-first-analyses.md` list a run order of about fifteen steps by hand ("then …, then …, rerun it after a spine change"). `docs/plans/ongoing/beacon-time-sync.md` records the last full pass as two rows: "Replace `derived/beacons/`, rerun the rest" and "Publish the site asset from the rerun". Nothing verifies that "the rest" was all of it.
- **What `cache_is_current` compares, and misses.** It compares file modification times against `derived/beacons/qa.json` and every file in the spine. It does not see:
  - `study.yaml`: `build` reads `beacons.rssi_threshold_dbm` when it runs, and `site_export.py` and `explorer_export.py` read the same key again at export time as `rssi_floor`, so an export can state a floor its tables were not built with;
  - constants a cache depends on (`minute_tables` filters on `CLOSE_RSSI`);
  - a sensitivity variant's own ingest: it always looks at the main `derived/beacons/qa.json`. Its two callers read only the main ingest today, so this bites the day a variant cache is added;
  - file times that did not survive a copy. `docs/context/data-layout.md` hands `derived/` over as an encrypted archive, and open PR #29 builds that archive as a zip; whether times survive depends on the tool that unpacks it.
- **No ingest writes an identity.** The beacon, EDA and survey commands write `qa.json` (counts that account for every input line, Invariant 3), `eda-heart-rate` writes `hr_qa.json`, and `extract-acoustics` writes no QA file but a `manifest.parquet` per device with a checksum per WAV; and `raw/` folders carry `SHA256SUMS` (`beacons/purge.py`, `zeitgeist.py`). None says "this is ingest X", and no analysis output says which one it read. After the fact, nobody can tell which ingest a figure or the published asset came from.
- **Reruns are compared by eye.** `56cb2d2 fix(dsa-2026): keep pair-day rows in a fixed order, so reruns match exactly` fixed an order that changed from run to run; that reruns match is asserted for that one function, not observable for an output folder.
- `tests/test_analysis_cache.py` holds one test, on file times.

## Design

One study-agnostic toolkit module, `social_energy.provenance` (Invariant 2: it knows folders and digests, no study facts). Illustrative signatures, not final:

```python
write_stamp(folder, *, inputs: dict[str, str], params: dict | None = None) -> Stamp
read_stamp(folder) -> Stamp | None
digest_files(files) -> str                      # sha256 over sorted relative names + contents
check(folder, *, expected: dict[str, str]) -> Verdict   # current | stale(<which input>) | unstamped
status(derived_root) -> list[Row]               # one row per stamped or unstamped folder
```

- **The stamp** is `stamp.json` beside the outputs, under `$SOCIAL_ENERGY_DATA/<study>/derived/…` only. It holds: an `id` (a digest of the folder's output files), the `inputs` it was built from as name → id (`beacons`, `spine`, `study`, or another analysis folder's id), the `params` the script declares (thresholds and constants a table depends on), the repo commit and whether the tree was dirty, and a UTC time. Hex digests, folder names, numbers: **no rows, no device or person identifiers** (Invariant 1). It never enters the repo, the site asset or the explorer bundle.
- **Ingests stamp themselves.** Each ingest command writes a stamp as its last step (after `qa.json` where it writes one). Two layouts need a rule the builder settles first: `derived/eda/` is written by two commands (`ingest-eda` and `eda-heart-rate`, each replacing only its own files), and `derived/survey/scoring/` sits inside `derived/survey/`. So a stamp covers a named list of files, not "everything in the folder", and its file name carries the command where two share a folder. Because the id is a digest of what was written, an ingest that reproduces the same files keeps its id and invalidates nothing downstream; if parquet bytes turn out not to be stable between identical runs, the only cost is a rebuild that was not needed — the safe direction. The builder checks this on a synthetic camp first.
- **Analyses stamp what they write and check what they read.** `copresence_by_phase.build` stamps its folder with the ids of the ingest, the spine and `study.yaml` it used, and clears day files before writing. `cp.load_all` — the one door 18 scripts already go through — checks that stamp against the current ids, per variant (`derived_root(variant)`). `cache_is_current` keeps its name and its two callers and compares ids and declared `params` in place of file times. `outcomes.py`, `site_export.py` and `explorer_export.py` check every folder they read before they write anything.
- **Refusal.** A stale folder stops the run with the folder, the input that moved, and the command to rerun, in the style `outcomes.removed_bins` already uses ("run … first"). `--allow-stale` on the script turns the stop into a printed warning for a deliberate comparison. The two exports take no such flag for the main ingest.
- **Rollout without a forced rerun.** Every folder on disk today is unstamped. Unstamped is reported, not refused, until the next full rerun; after it, the builder flips unstamped to refused in one line.
- **One listing.** `uv run python -m social_energy.provenance studies/<id>/study.yaml` prints each folder as current, stale (and why) or unstamped. It replaces rereading the hand-off prose to know what to rerun; two stamps of the same folder from two runs show whether a rerun matched. It is a module entry point, not a `social-energy` subcommand, so it does not touch `cli.py` while PR #29 is open; wiring it into the CLI can follow.
- **Order with related plans.** None builds first. Stamping goes through `load_all` and explicit calls in the scripts that write tables others read. A shared harness for the analysis scripts (one `out_dir` for all of them) was looked at in the same pass and not filed; if it is ever built, stamping moves into that one function.

**Alternatives considered:**
- *Widen the file-time check to every reader.* Smallest change, but it cannot see `study.yaml` or constants unless they are files to compare, does not survive a copy that resets times, and still cannot say afterwards which ingest an output came from.
- *A pipeline tool (Snakemake, DVC, make).* It would give ordering and staleness together, but adds a dependency and a second description of the chain beside scripts that import each other, and DVC's tracking files put digests of real data in a public repo, against the spirit of Invariant 1.
- *Stamp the public asset with the ingest id.* Useful for "which run is published", but what the public site carries is governed by `docs/decisions/public-site.md`; left out.

**Testing strategy:** `tests/test_provenance.py` (new) on temporary folders with hand-written files: same files → same id; one byte changed → stale, naming the input; missing stamp → unstamped; a stamp holds only the allowed keys (a test that fails if a row or an entity string could get in). `tests/test_analysis_cache.py` is rewritten on ids and params, replacing the file-time test, not layered on it. One end-to-end test on a synthetic camp: ingest, build, re-ingest with one setting changed, and `load_all` refuses until `build` runs again. Each test gets its deliberate mutation, as the working rules ask.

## Paths

As of 2026-11-21.

- `src/social_energy/provenance.py` (new)
- `src/social_energy/cli.py` — one call per ingest command, as its last step (open PR #29 edits this file: rebase over it)
- `studies/dsa-2026/analyses/copresence_by_phase.py` — `build`, `load_all`, `cache_is_current`
- `studies/dsa-2026/analyses/moments_networks.py`, `exploratory_rhythm.py` — declare the params of their caches
- `studies/dsa-2026/analyses/sensitivity_ingests.py` — it calls `cli.ingest_beacons` and `cp.build(variant)`, so a stamp written inside those two covers each variant; here only the `params` of the variant's changed setting, and a test
- `studies/dsa-2026/analyses/outcomes.py`, `site_export.py`, `explorer_export.py` — check before writing
- `tests/test_provenance.py` (new), `tests/test_analysis_cache.py`
- `docs/context/data-layout.md` — `stamp.json` in the layout, and the listing command in the hand-over section
- `.agents/skills/add-analysis/SKILL.md` — the `## Caches` paragraph (open PR #45 edits this file: rebase over it)
- `docs/plans/ongoing/dsa-2026-first-analyses.md` — the hand-off line points to the listing

## Approval

**Needs your yes** — the `Gate` question; recommended answer: stop, because the failure this prevents is silent by nature and a warning scrolls past in a long run, while a stop costs one rerun and `--allow-stale` covers the deliberate case. `AGENTS.md` has no `## Approval` section, and this changes what a researcher sees: a script that ran yesterday may refuse today.

## Out of scope

- Running the chain automatically or in order; this only says what is stale.
- Anything in the public asset or the explorer bundle.
- Shared scaffolding for the analysis scripts (one `out_dir`, one figure style): looked at in the same pass, not filed.
- Checking `raw/` against its `SHA256SUMS`; `sha256sum -c` and `purge-device` already cover it.
- Byte-for-byte reproducibility of every analysis; the stamp only makes a difference between two runs visible.
