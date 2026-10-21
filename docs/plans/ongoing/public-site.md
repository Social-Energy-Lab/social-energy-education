# Public site: DSA 2026 as animations

**Priority:** high — target: live for the research-group talk on 2026-11-03
**Gate:** none to build; uploading the real site data waits on Álvaro's review of a local preview
**Next:** Task 1 of the implementation plan below

**Goal:** a public web page, served by GitHub Pages from this repo, where anyone curious about the
DSA 2026 results — the lab, colleagues, and the participants themselves — can watch the camp as an
animated co-presence network and follow the main results as a short animated story.

Replaces [`explorer-public-mode.md`](../ideas/explorer-public-mode.md) (its follow-ups move to the end of
this file; delete that plan when this one is promoted).

## Why

The results so far live in private notes, static matplotlib figures and an internal video. The
people who took part, and the wider lab, have no way to see what the beacons showed. A page they
can open on a phone turns the study into something they can look at, and it is the natural
companion to the 3 Nov talk.

## Decisions taken

Who decided is noted: **Álvaro** for his decisions in the brainstorm of 2026-10-21, *agent* for
calls made in this design that he can overturn.

| Topic | Decision | By |
|---|---|---|
| Audience | anyone interested: lab, colleagues, participants | Álvaro |
| Individual network in public | allowed; Mahdi approved showing the animated network `[unknown: when and in which channel did Mahdi approve publishing the animated network, and does the approval cover the aggregate result numbers too?]` | Álvaro |
| Residual re-identification risk | accepted (a participant may recognise their own course cluster from size and timing) | Álvaro |
| Data path | release asset feeds the Pages build; real data never enters git (see below) | Álvaro |
| Rendering | live in the browser (canvas + D3), not pre-rendered video | Álvaro |
| Content | all seven chapters, including the confirmatory null | Álvaro |
| Course colours | dots coloured by course; **no course labels**; course→colour and course→ring position shuffled at build time | Álvaro |
| Night | hours 00:00–06:00 local are not shown | Álvaro |
| Language | German by default, English toggle | Álvaro |
| Stack | plain static HTML/JS, the vendored D3, no build step | Álvaro |
| URL | default Pages address `social-energy-lab.github.io/social-energy-education/` | agent |
| Staff | not shown (participants only, as in every analysis) | agent |
| Presses | shown at 5-minute bin resolution, not to the second | agent |
| Tracking | none: no analytics, cookies, external fonts or CDNs — the page makes no third-party request | agent |
| Night in the story chapters | the 00:00–06:00 cut applies to the animation only (it shows individuals); chapters 2–6 are camp-level aggregates and use the existing all-hours outputs, so `site_export.py` re-filters nothing | agent |
| Copy | an agent drafts German and English; Álvaro reviews; Mahdi reads the German before the real-data upload `[inferred]` | agent |
| Citation | "how to cite" points to this repo until a paper exists `[unknown: what should the site ask people to cite once there is a paper or DOI?]` | agent |

## Non-goals and anti-goals

- **No lookup of a person.** No search, no "find yourself", no click-through to a node's history,
  no tooltip with anything about a node.
- **Not team mode.** The explorer's sliders, course filter and zone/room views stay local-only.
- No interviews, survey answers per person, EDA, acoustics per room or field-log text.
- No course-level result anywhere, and no aggregate cell under `min_group` (5) people.
- **Anti-goal:** a site whose git history carries real data, even derived. If the data path below
  cannot work, stop and ask; do not fall back to committing data.
- **Anti-goal:** findings stated in the repo. Every real number lives in the data asset; the copy
  in git uses placeholders (see "Copy").

## Data path

```
researcher's machine                         GitHub
────────────────────                         ──────
analyses (existing) ─► site_export.py ─► $SOCIAL_ENERGY_DATA/dsa-2026/derived/site/
                                              │  zip + `gh release upload site-data-dsa-2026`
                                              ▼
                                         Release asset (deletable)
repo: site code + synthetic fallback ─► pages.yml: build synthetic data, overlay the release
                                         asset if present, validate, deploy-pages
```

- `pages.yml` runs on `workflow_dispatch` and on pushes to `main` that touch the site code. It uses
  `actions/upload-pages-artifact` + `actions/deploy-pages` (Pages source: GitHub Actions). Pages is
  not enabled yet; enabling it is one `gh api` call, in the plan.
- **Synthetic fallback:** without the release asset (PRs, forks, after a takedown) the workflow
  builds the site from `social_energy.explorer.synthetic` plus synthetic aggregates, and the page
  shows a "synthetic demo" banner. CI therefore always builds a working site with no real data.
- **Validation before deploy:** the workflow refuses an asset whose `meta.json` is not
  `mode: public`, or that carries any field the public schema does not list (course keys or names,
  location labels, `qa`, notes text, seconds-resolution presses).
- **Takedown:** delete the release, re-run the workflow; the page goes back to synthetic. Write
  this in the decision record — anyone may already have a copy, so it limits exposure, it does not
  recall it.
- **Publishing:** a documented command sequence in `docs/context/onboarding.md` (build, preview
  locally, zip, `gh release upload --clobber`, dispatch the workflow). Uploading is always a
  person's deliberate act, never automatic.

## The public bundle

A new `mode: "public"` in `social_energy.explorer.write_bundle` (or a sibling writer), applied at
export, so the browser can never see more than this:

| Table | Public form |
|---|---|
| nodes | participants with `beacons` consent; shuffled indices (as now) and a shuffled course *index* only; no course keys or names |
| pairs | pre-filtered to the analysis close-range threshold (−65 dBm, `cp.CLOSE_RSSI`); RSSI column dropped |
| seen | as now |
| presses | bin index (u16) instead of seconds; `self_report` consent |
| rooms | not exported |
| bins | as now, minus night bins (00:00–06:00 local) — dropped from every table; the player jumps the gap with a "night" card |
| meta | days, phases, special-day labels (excursion, rotation — already public in `study.yaml`), the 24–27 Aug shading relabelled "records missing"; no `qa`, no location labels |

- Course shuffle: one permutation from OS entropy at export decides both colour and ring position.
  The mapping is not written anywhere.
- Target size under 3 MB before Pages' gzip; if pre-filtering is not enough, aggregate pairs to
  15-minute bins.

## Aggregates for the story chapters

`studies/dsa-2026/analyses/site_export.py` (study code; the toolkit stays generic) reads the
existing outputs under `derived/analyses/` and writes `aggregates.js`-style data into the asset
(not `.json` in the repo — `check_perimeter.py` refuses `.json`; inside the asset any format is
fine). Camp-level only; every row with fewer than 5 people is suppressed, and the exporter asserts
there is no course-level row. Sources:

| Chapter | Source (all under `derived/analyses/`) |
|---|---|
| 2 A day at the academy | `copresence-by-phase/day_phase.csv` |
| 3 Circles and special days | `exploratory/rhythm_daily_mixing.csv`, `rhythm_mixing_contrast.csv`, `rhythm_persistence_rates.csv`, `copresence-by-phase/daily_network.csv` |
| 4 Shared moments | `exploratory/cascades.csv`, `exploratory/cascades/` (latency and group-size tables) |
| 5 Where moved moments happen | `exploratory/places_setting.csv` |
| 6 What we did not find | `confirmatory/results.csv` |

Only the rows a chart draws are exported. Synthetic aggregates for the fallback come from a small
generator in the toolkit with the same schema.

## The page

One scrolling page, German first, plus a full-screen "play the camp" mode.

1. **Das Camp atmet / The camp breathes** — hero. The network over 16 days: each course has a home
   on a ring, ties pull dots away from it, white lines cross courses, a dot glows when its wearer
   pressed the button. Play/pause, a scrubber, speed, a day picker. Port the force layout from
   `camp_breathes.py` to JS; reuse `explorer/static/model.js` for windows and ties (sliding
   2-hour window, ≥ 15 close minutes — the camp-breathes settings).
2. **A day at the academy** — day × phase heatmap: how many are close to someone, how many alone,
   presses.
3. **Courses form circles, special days break them** — cross-course share per day against the
   random-mixing line; the hero's ring visibly loosening on 18 and 22 Aug; ties from special days
   coming back less often.
4. **Shared moments** — presses by people near each other within seconds; the latency curve drawn
   on scroll (spike at 0–10 s); excess by group size.
5. **Where moved moments happen** — press rates by setting.
6. **What we did not find** — the confirmatory test as a forest plot, with one paragraph on what a
   null with n = 75 does and does not mean.
7. **How this works** — beacons and the button, what was not recorded, privacy (no names, courses
   shuffled, night hidden), the two tiers (confirmatory vs exploratory leads), link to this repo,
   how to cite.

- **Copy:** strings in `de` and `en` modules in the repo, with placeholders for every number
  (`{cascade_excess}`), filled from the asset at runtime. The words are public; the numbers are not
  in git. Framing follows the talk: *signatures*, not a measurement; exploratory results are leads.
- Accessible: keyboard play/pause, `prefers-reduced-motion` starts paused, every chart has a text
  summary, colour palette passes contrast in light and dark.
- Phone first: canvas sized to the viewport; the hero must run smoothly on a mid-range phone.
- Link preview image (`og:image`): rendered in the workflow from whatever data it deployed, never
  committed.

## Where the code goes

- Toolkit (`src/social_energy/`): the public bundle mode, the synthetic aggregates, the static
  page engine. Suggested `src/social_energy/site/` with `static/` sharing `model.js` and the
  vendored D3 with the explorer (by import or one copy step in the build — builder's call).
- Study (`studies/dsa-2026/`): `analyses/site_export.py`, and the chapter config if the chapters
  turn out to be study-specific. Invariant 2 holds: the toolkit imports nothing from `studies/`.
- CLI: `social-energy site build studies/dsa-2026/study.yaml [--synthetic]` writes the assembled
  site to a directory outside the repo; `social-energy site preview` serves it on 127.0.0.1.

## Records to change

- New `docs/decisions/public-site.md`: what is published, why (Mahdi's approval, with the
  `[unknown: …]` above until filled), the accepted residual risk, the release-asset path, takedown.
- `docs/decisions/explorer-local-only.md`: status "amended by public-site.md"; team mode stays local.
- `AGENTS.md`, Invariant 1: one sentence — the site data asset, built locally and published as a
  release asset under `public-site.md`, is the only sanctioned route for derived data to leave a
  researcher's machine for the public; it never enters git.
- `camp_breathes.py` and `explorer_export.py` docstrings: the internal video and team bundle stay
  internal; the public route is the site.
- `docs/context/onboarding.md`: the publishing steps.
- The `data-perimeter` skill: mention the site asset and its validation.

## Verification

- Tests (synthetic): public bundle carries no course keys, no location labels, no seconds, no night
  bins, no staff; validator rejects a team-mode bundle; aggregates exporter suppresses cells < 5;
  site builds from synthetic data alone.
- `scripts/check_perimeter.py` and the denylist pass on every commit; CI deploys the synthetic site.
- Before the first upload: Álvaro reviews the real-data build in a local preview, on desktop and a
  phone; the frame-by-frame look of 18 and 22 Aug and of the 24–27 Aug shading is checked.
- After deploy: the live page loads with no third-party requests (browser network tab).

## Build order and what slips first (agent's call)

3 Nov is a target, not a hard gate. Build in this order, so each step leaves a showable site:

1. Public bundle mode, validator, synthetic fallback, `pages.yml` — the synthetic site is live.
2. Hero chapter with play/scrub — preview with real data locally.
3. Chapters 4 (shared moments) and 6 (the null), then 3, 2, 5, 7.
4. Polish, English, link preview image.

If 3 Nov arrives before Álvaro has reviewed the real-data build, show the local preview at the talk
and keep the synthetic site live; the upload waits.

## Left to the builder

- Exact file layout under `src/social_energy/site/`, the scrollytelling mechanics, chart forms
  within each chapter, visual design (start from the camp-breathes look: dark, warm glow).
- Whether pairs need 15-minute aggregation to meet the size target.
- Whether the hero uses canvas only or canvas + SVG overlay.

## Follow-ups carried over from the explorer review

- Gate the SVG views on a changed bin while playing; they rebuild every frame.
- Unknown-course ties count as cross-course in `model.js`; the Python analysis drops them.
- "Reset to analysis defaults": the window and minimum time are the explorer's own, not the
  analysis's per-day tie; rename or explain.
- Collapse duplicate `(bin, a, b)` pair rows in `write_bundle` (keep the strongest RSSI).
- Range-check the `u8` day index; resolve the static path in `server.py`; catch a busy port with a
  message; derive the initial playhead from the bin size.
- Light-theme glow is close to course 4's colour.
- Oracle test: assert room counts per location label against `room_per_bin`.

---

# Implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** the public page above, deployed by GitHub Pages from a synthetic build in CI, with real
data arriving only as a release asset built on a researcher's machine.

**Architecture:** a toolkit package `social_energy.site` writes the public data (bundle +
aggregates), validates it, and assembles a static site (copy of `site/static/` + `data/`). The
study script `site_export.py` fills it from DSA 2026's existing outputs. A Pages workflow builds the
synthetic site and overlays the release asset when one exists.

**Tech stack:** Python 3.12, polars, numpy, pytest; plain ES modules + vendored D3 (no npm, no
bundler); Node's built-in test runner for pure JS (`tests/js/*.test.mjs`, run by pytest).

**Spec:** the design above in this file.

## Global constraints

- No research data in git, ever. Site data is written only outside the repo
  (`paths.refuse_inside_repo`); the workflow's real data comes from release `site-data-dsa-2026`.
- Files committed under `src/` must pass `scripts/check_perimeter.py`: no `.json`, no data
  suffixes, nothing over 1 MB. Strings and config in the static site are `.js` modules.
- Public meta carries no course keys or names, no location labels, no `qa`, no free-text notes
  except special-day labels; presses at bin resolution; night 00:00–06:00 local removed from
  pairs, seen and presses; staff never nodes.
- Aggregates: camp-level rows only; any row with `people < 5` is dropped by the exporter and
  refused by the validator.
- The page makes no third-party request: D3 from `explorer/static/vendor/`, system fonts.
- German is the default language, English via toggle; every number in copy is a placeholder.
- Toolkit never imports from `studies/` (`tests/test_architecture.py`).
- Before every commit: `uv run ruff check . && uv run ruff format --check . && uv run pytest`.

## Review focus

1. **A bundle with a course key, a seconds column or a location label reaching the validator** —
   it must refuse, naming the field. Test in Task 2.
2. **Night bins at the boundary (05:55 and 06:00 local, and DST-free Berlin summer time)** — 05:55
   is dropped, 06:00 kept. Test in Task 1.
3. **No release asset (PRs, forks, after takedown)** — the workflow must still deploy the
   synthetic site with the banner, not fail. Covered in Task 7 by the "asset missing" branch.
4. **A phone with `prefers-reduced-motion`** — the hero starts paused and every chart still
   renders its final state. Test (pure JS) in Task 4.
5. **Aggregates row with `people` missing or `suppressed: true`** — exporter drops it, validator
   refuses it if present. Test in Task 2.

## File structure

| Path | Responsibility |
|---|---|
| `src/social_energy/site/__init__.py` | exports below |
| `src/social_energy/site/public.py` | `write_public_bundle`, public meta schema constants |
| `src/social_energy/site/aggregates.py` | aggregates schema, `check_aggregates`, `synthetic_aggregates` |
| `src/social_energy/site/validate.py` | `validate_site_data` (bundle + aggregates) |
| `src/social_energy/site/build.py` | `build_site`, `synthetic_site_data` |
| `src/social_energy/site/static/` | `index.html`, `style.css`, `app.js`, `data.js`, `layout.js`, `player.js`, `i18n.js`, `strings/de.js`, `strings/en.js`, `chapters/{day,circles,moments,places,null,how}.js` |
| `src/social_energy/cli.py` | `site-build` command |
| `studies/dsa-2026/analyses/site_export.py` | DSA 2026 → `$SOCIAL_ENERGY_DATA/dsa-2026/derived/site/data/` |
| `.github/workflows/pages.yml` | build + deploy |
| `tests/test_site_public.py`, `tests/test_site_aggregates.py`, `tests/test_site_build.py`, `tests/js/layout.test.mjs`, `tests/js/site.test.mjs` | tests |
| `docs/decisions/public-site.md`, `AGENTS.md`, `docs/decisions/explorer-local-only.md`, `docs/context/onboarding.md`, `.agents/skills/data-perimeter/SKILL.md`, docstrings of `camp_breathes.py` and `explorer_export.py` | records |

## Tasks

### Task 1: Public bundle writer

**Files:** create `src/social_energy/site/{__init__,public}.py`, `tests/test_site_public.py`.

**Interfaces:**
- Consumes: `explorer.BundleInput`, `study.ExplorerConfig`, `explorer.bundle._write`/`DTYPES` (import, do not copy).
- Produces:
  - `PUBLIC_COLUMNS = {"pairs": [("bin","u16"),("a","u16"),("b","u16")], "seen": [("bin","u16"),("node","u16")], "presses": [("bin","u16"),("node","u16")], "bins": [("phase","u8"),("day","u8"),("shown","u8")]}`
  - `PUBLIC_META_KEYS = {"version","mode","synthetic","timezone","t0","bin_seconds","n_bins","nodes","n_courses","phases","days","special_days","shade","files"}`
  - `write_public_bundle(inp: BundleInput, out_dir: Path, config: ExplorerConfig, *, timezone: str, close_rssi: int = -65, night: tuple[str, str] = ("00:00", "06:00"), special_days: list[dict] = (), shade_label: str = "records missing", synthetic: bool = False, seed: int | None = None) -> dict`
    — returns meta; `meta["mode"] == "public"`; `nodes = [{"course": int}]` with course indices
    permuted once (OS entropy unless `seed`); `-1` stays `-1`; `special_days` entries
    `{"start_bin","end_bin","label"}`; `shade` entries `{"start_bin","end_bin","label": shade_label}`.

- [ ] **Step 1: Failing tests** in `tests/test_site_public.py`, reusing the golden world pattern from `tests/test_explorer_bundle.py` with `T0 = 2026-08-14 03:30 UTC` (05:30 Berlin):
  - `test_public_meta_has_only_public_keys`: `set(meta) <= PUBLIC_META_KEYS`; `"courses" not in meta`, `"locations" not in meta`, `"qa" not in meta`; every node dict has exactly `{"course"}`.
  - `test_pairs_filtered_to_close_range_and_rssi_dropped`: pair at −70 absent, −65 present; `pairs` columns are `bin,a,b`.
  - `test_presses_at_bin_resolution`: press at 05:58:20 Berlin lands in the bin of 05:55, column `bin`.
  - `test_night_removed_at_the_boundary`: bin starting 05:55 has `shown == 0` and no pairs/seen/presses; bin 06:00 has `shown == 1` and keeps its rows.
  - `test_course_indices_permuted_consistently`: with `seed=3`, nodes sharing a course share an index; the set of indices equals `range(n_courses)`; `None` → `-1`.
  - `test_refuses_inside_repo`: `out_dir=REPO_ROOT/"x"` raises `DataRootError`.
- [ ] **Step 2:** `uv run pytest tests/test_site_public.py -v` → fails (module missing).
- [ ] **Step 3:** implement `write_public_bundle`; night test is on local clock of the bin start.
- [ ] **Step 4:** tests pass; full check passes.
- [ ] **Step 5:** commit `feat(site): public bundle, no course keys, presses per bin, no night`.

### Task 2: Aggregates schema and validator

**Files:** create `src/social_energy/site/{aggregates,validate}.py`, `tests/test_site_aggregates.py`.

**Interfaces:**
- Produces:
  - `AGGREGATE_SECTIONS` — dict section → allowed row keys:
    - `day_phase`: `day, phase, people, others, share_no_one`
    - `daily_mixing`: `day, kind, people, cross_share, expected`
    - `persistence`: `origin, people, new_ties, share, lo, hi`
    - `moments_latency`: `band, people, ratio, ratio_lo, ratio_hi`
    - `moments_size`: `size, people, ratio, ratio_lo, ratio_hi`
    - `moments_headline`: `people, observed, null_mean, ratio, lo, hi`
    - `places`: `setting, people, rate, lo, hi`
    - `confirmatory`: `test, label, people, estimate, lo, hi, scale` (`scale` ∈ `"sd"`, `"rr"`)
    - `numbers`: flat dict of named numbers used by copy placeholders (no `people` rule; values must be numbers)
  - `check_aggregates(agg: dict, min_group: int = 5) -> dict` — returns a copy with rows whose `people` is missing or `< min_group` dropped, and any row key outside its section removed.
  - `synthetic_aggregates(seed: int = 0) -> dict` — every section populated with plausible random values, `people >= 5`.
  - `validate_site_data(data_dir: Path, min_group: int = 5) -> dict` — reads `meta.json`, the `.bin` files and `aggregates.json`; raises `SiteDataError(ValueError)` naming the first offending field; returns meta.
- [ ] **Step 1: Failing tests:**
  - `test_check_drops_small_and_missing_people` (rows with `people` 4 and absent are gone; 5 stays).
  - `test_check_strips_unknown_keys` (a `course` key in a `places` row is removed).
  - `test_validator_refuses_team_bundle` (a `write_bundle(..., mode="team")` dir → error mentioning `mode`).
  - `test_validator_refuses_extra_meta_key` (`courses` → error naming `courses`).
  - `test_validator_refuses_seconds_presses` (presses columns `sec,node` → error naming `presses`).
  - `test_validator_refuses_small_row` (aggregates row `people: 3` → error naming the section).
  - `test_validator_accepts_public_bundle_with_synthetic_aggregates`.
- [ ] **Step 2:** run, fails. **Step 3:** implement. **Step 4:** pass + full check.
- [ ] **Step 5:** commit `feat(site): aggregates schema with small-cell rule, site data validator`.

### Task 3: Site builder and CLI

**Files:** create `src/social_energy/site/build.py`, `tests/test_site_build.py`; modify `src/social_energy/cli.py`; placeholder `src/social_energy/site/static/index.html` (replaced in Task 4).

**Interfaces:**
- Consumes: Task 1, Task 2, `explorer.synthetic.synthetic_inputs`, `synth.CampSpec`, `synth.generate`.
- Produces:
  - `synthetic_site_data(out_dir: Path, *, seed: int = 0) -> Path` — generates a `CampSpec(hours=72, seed=seed)` camp in a temp dir, writes a public bundle with `synthetic=True` and `synthetic_aggregates(seed)` as `aggregates.json`.
  - `build_site(out: Path, data_dir: Path | None) -> Path` — copies `site/static/` to `out`, copies `explorer/static/vendor/d3.min.js` to `out/vendor/` and `explorer/static/model.js` to `out/model.js`, copies or synthesises `out/data/`, then `validate_site_data(out/"data")`. `out` must be outside the repo.
  - CLI: `social-energy site-build <study.yaml> --out DIR [--data DIR]`; without `--data` it builds synthetic. It must not need `$SOCIAL_ENERGY_DATA` when `--data` is absent.
- [ ] **Step 1: Failing tests:** `test_build_synthetic_site` (`index.html`, `vendor/d3.min.js`, `model.js`, `data/meta.json` exist; meta `synthetic` true); `test_build_with_data_dir_copies_and_validates` (a team-mode data dir raises `SiteDataError`); `test_cli_site_build_without_data_root` (monkeypatch env without `SOCIAL_ENERGY_DATA`, exit 0).
- [ ] **Step 2–4:** fail, implement, pass.
- [ ] **Step 5:** commit `feat(site): build the static site from public data or a synthetic camp`.

### Task 4: Page shell, i18n and the hero player

**Files:** create the static files listed in the file structure except `chapters/*`; `tests/js/layout.test.mjs`, `tests/js/site.test.mjs`; extend `tests/test_explorer_model.py` glob is already `*.test.mjs` (no change).

**Interfaces:**
- `data.js`: `export async function loadSite(base = "data/") -> {meta, b, agg}` (uses `model.decode`).
- `layout.js` (pure, no DOM): `export function homes(nodeCourse: Int16Array|number[], nCourses: number, seed: number) -> Float32Array` (x,y pairs; ring radius 0.85, start angle π/2, per-node jitter σ 0.1 from a seeded PRNG); `export class Sim { constructor(home: Float32Array, seed: number); step(weights: Map<string, number>, visible: Uint8Array, substeps = 4): void; pos: Float32Array }` — the force constants exactly as `camp_breathes.Simulation` (spring 0.6 to rest length 0.12; repulsion 0.0012/max(d,0.04)², ×0.1 when either is unseen; gravity 0.03 seen / 0.08 unseen; velocity `(v + 0.25 F) * 0.7`, speed cap 0.03).
- `player.js`: `export function shownBins(bins) -> Uint32Array` (indices with `shown==1`); `export function startPaused(matchMedia) -> boolean` (true under reduced motion); canvas hero: window 24 bins (2 h), edge when ≥ 3 close bins, glow 8 bins after a press; play/pause, scrubber over shown bins, speed 1/3/6 h per second, day picker; night gap shows a "Nacht/night" card for 1 s.
- `i18n.js`: `export function fill(template: string, numbers: object, lang: "de"|"en") -> string` — `{name}` → number formatted with `Intl.NumberFormat(lang)`, at most 2 decimals; unknown placeholder → `"–"`. `export function t(key)`; language from `?lang=`, then `navigator.language`, default `de`; toggle stores choice in `localStorage` inside try/catch.
- `strings/de.js`, `strings/en.js`: `export default { key: "text {placeholder}" }` — hero, banner (`synthetic`), all chapter titles and bodies, method/privacy text. Framing: *Signaturen sozialer Energie*, not a measurement; exploratory = leads.
- `style.css`: dark default, light via `prefers-color-scheme`, colour tokens on `:root`, six course colours from the explorer's palette.
- [ ] **Step 1: Failing JS tests:** `homes` puts course 0's mean at angle π/2 ± 0.15 with `n` nodes; same seed → same output; `Sim.step` with one weighted pair brings the two closer; `shownBins` skips `shown==0`; `startPaused({matches:true})` true; `fill("x {a}", {a: 2.064}, "de") === "x 2,06"`; unknown placeholder → `–`.
- [ ] **Step 2:** `uv run pytest tests/test_explorer_model.py -v` → fails.
- [ ] **Step 3:** implement; page runs the hero on synthetic data with a visible "synthetic demo" banner when `meta.synthetic`.
- [ ] **Step 4:** tests pass; `uv run social-energy site-build studies/dsa-2026/study.yaml --out /tmp/…/site` then `python3 -m http.server -b 127.0.0.1 -d <out>`; check in a browser (desktop + narrow viewport) that the hero plays, scrubs and switches language.
- [ ] **Step 5:** commit `feat(site): page shell, German and English, the camp-breathes hero`.

### Task 5: Chapters 4 and 6 (shared moments, the null)

**Files:** `static/chapters/moments.js`, `static/chapters/null.js`; extend `tests/js/site.test.mjs`.

**Interfaces:** each chapter exports `render(el: HTMLElement, agg: object, t: Function, opts: {reduced: boolean}) -> void`. Pure helpers exported for tests: `latencyBars(rows) -> [{band, ratio, lo, hi}]` sorted by band start; `forestRows(rows) -> [{label, estimate, lo, hi, scale, crossesNull: boolean}]` (null is 0 for `sd`, 1 for `rr`).
- Moments: headline sentence from `numbers`; latency bars that grow on scroll-in (IntersectionObserver; instantly when reduced); group-size bars; a reference line at 1×.
- Null: forest plot, `sd` and `rr` on separate axes, interval lines, one paragraph from strings.
- [ ] Steps: failing helper tests (`crossesNull` true for `lo<0<hi` on `sd`, `lo<1<hi` on `rr`; band order) → implement → pass → browser check on synthetic → commit `feat(site): shared moments and the confirmatory null`.

### Task 6: Chapters 2, 3, 5, 7

**Files:** `static/chapters/{day,circles,places,how}.js`; extend `tests/js/site.test.mjs`.

- Day: heatmap day × phase of `share_no_one` and `others`, toggle between the two.
- Circles: cross-course share per day as a line with the `expected` line and special days marked; persistence bars by origin; a button "show me on the network" that moves the hero's playhead to 18 Aug 15:00 and scrolls up.
- Places: rate per setting, sorted, with intervals.
- How: static text from strings, link to the repo, citation line.
- Pure helper tests: `heatCells(rows, value)` drops rows with missing value; `markSpecial(days, special_days)`.
- [ ] Steps as Task 5. Commit `feat(site): day rhythm, circles, places, how this works`.

### Task 7: Pages workflow

**Files:** `.github/workflows/pages.yml`.

- Triggers: `workflow_dispatch`; `push` to `main` with paths `src/social_energy/site/**`, `src/social_energy/explorer/static/**`, `.github/workflows/pages.yml`.
- Permissions `contents: read, pages: write, id-token: write`; concurrency group `pages`.
- Steps: checkout → setup-uv → `uv sync --locked` → `gh release download site-data-dsa-2026 -p site-data.zip -D $RUNNER_TEMP` (continue on missing; `GH_TOKEN: ${{ github.token }}`) → unzip to `$RUNNER_TEMP/data` if present → `uv run social-energy site-build studies/dsa-2026/study.yaml --out $RUNNER_TEMP/site [--data $RUNNER_TEMP/data]` → `actions/upload-pages-artifact@v3` → `actions/deploy-pages@v4`.
- [ ] **Step 1:** write the workflow; `python3 scripts/check_perimeter.py` passes.
- [ ] **Step 2:** commit `ci(site): build and deploy the public site to Pages`, push.
- [ ] **Step 3:** enable Pages: `gh api -X POST repos/Social-Energy-Lab/social-energy-education/pages -f build_type=workflow`; dispatch the workflow; open the URL; the synthetic banner shows and the network plays; the browser network tab shows only same-origin requests.

### Task 8: DSA 2026 export and local preview (private, no commit of data)

**Files:** `studies/dsa-2026/analyses/site_export.py`.

- Inputs exactly as `explorer_export.py` (participants with `beacons` consent; presses with `self_report` consent); `write_public_bundle` with `close_rssi=cp.CLOSE_RSSI`, special days from `study.yaml` notes (excursion, rotation), shade from `study.yaml` shade relabelled.
- Aggregates mapped from the CSVs in the design's table: ordinary-variant rows only (`variant == "main"` or the scripts' primary variant), `kind`/`category` renamed to the schema; `numbers` filled with the copy's placeholders (cascade excess, latency 0–10 s ratio, mixing on special days, n). Pass through `check_aggregates`.
- Writes `$SOCIAL_ENERGY_DATA/dsa-2026/derived/site/data/` and `site-data.zip` beside it; prints node count, size, dropped rows.
- [ ] **Step 1:** implement; run `uv run --extra analysis python studies/dsa-2026/analyses/site_export.py`; `validate_site_data` passes; zip under 3 MB (else aggregate pairs to 15-minute bins in the export).
- [ ] **Step 2:** `site-build --data …` into `$SOCIAL_ENERGY_DATA/dsa-2026/derived/site/preview`, serve on 127.0.0.1, check 18 Aug, 22 Aug and 24–27 Aug and every chapter's numbers against the private notes.
- [ ] **Step 3:** commit the script only: `feat(dsa-2026): export the public site data`.
- [ ] **Step 4 (gate):** stop; Álvaro reviews the preview (desktop + phone). Nothing is uploaded before he says so.

### Task 9: Records

- `docs/decisions/public-site.md` (new), `explorer-local-only.md` (status amended), `AGENTS.md` Invariant 1 sentence, `onboarding.md` § "Publishing the site" (export → preview → zip → `gh release create/upload site-data-dsa-2026 site-data.zip --clobber` → `gh workflow run pages.yml`; takedown: `gh release delete site-data-dsa-2026 --yes` then run the workflow), `data-perimeter` skill paragraph, docstrings of `camp_breathes.py` and `explorer_export.py`; delete `docs/plans/ideas/explorer-public-mode.md` (its follow-ups live above).
- [ ] Commit `docs(site): decision record, publishing steps, perimeter rule for the site asset`.

### Task 10: Publish (only after Álvaro's OK in Task 8)

- [ ] Link preview image (`og:image`) is deferred: v1 ships without one.
- [ ] Run the onboarding steps; check the live page shows real data, no banner, and only same-origin requests; update this plan's `Next`.
