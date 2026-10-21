# Public site: DSA 2026 as animations

**Priority:** high — target: live for the research-group talk on 2026-11-03
**Gate:** none to build; uploading the real site data waits on Álvaro's review of a local preview
**Next:** write the implementation plan from this design

**Goal:** a public web page, served by GitHub Pages from this repo, where anyone curious about the
DSA 2026 results — the lab, colleagues, and the participants themselves — can watch the camp as an
animated co-presence network and follow the main results as a short animated story.

Replaces [`explorer-public-mode.md`](explorer-public-mode.md) (its follow-ups move to the end of
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
