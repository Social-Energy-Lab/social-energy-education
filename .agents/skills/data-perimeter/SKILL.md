---
name: data-perimeter
description: "Use before touching anything that could carry research data into this public repo: ingest code, test fixtures, notebooks, study docs, plans, commit messages, or when handling files from $SOCIAL_ENERGY_DATA. Encodes AGENTS.md invariant 1 (no research data, no identifying details, ever)."
---

# Data perimeter

This repo is public. The data comes from young people under an FSU Jena ethics approval that allows publishing **code and anonymised aggregates only**. Git history is permanent. One careless commit is a data breach that cannot be undone.

## Before you write anything

Ask yourself: *could this line, file or number help someone learn something about a real participant?* If yes, or if you are unsure, it does not go in the repo.

| Never in the repo | Where it goes instead |
|---|---|
| raw or derived data files (logs, CSV, parquet, WAV, JSON exports, xlsx) | `$SOCIAL_ENERGY_DATA/<study>/…` |
| names, initials, nicknames, emails, study-ID ↔ person mappings | the encrypted code list (Mahdi only) |
| real device↔person assignments, exclusion windows, field notes | local `spine/` YAML |
| participant quotes, survey free text, interview snippets | local only |
| person-level numbers in docs ("ID 74 had 312 contacts") | nowhere; aggregate, and only for groups large enough to protect anonymity |
| unpublished manuscripts (e.g. Rosa's drafts) | summarise in your own words; never quote or commit |
| notebook outputs | clear outputs before committing (the hook rejects them) |

Allowed: instrument-level facts (firmware behaviour, file formats, thresholds), non-personal study config (dates, rooms, programme types), and **synthetic** data from `social_energy.synth` or hand-written fixtures in `tests/fixtures/`.

## The private context library

Full source documents (field logs, ethics application, consent forms, survey versions, team slides, unpublished manuscripts) are kept as markdown in `$SOCIAL_ENERGY_DATA/<study>/context/`, indexed by its `README.md` with a sensitivity column: **P** personal, **U** unpublished, **I** internal, **R** public reference.

- **P** content: never enters the repo, not even paraphrased at person level. Transcribe it into the local spine, IDs only.
- **U** content: paraphrase the idea, never quote it, and never publish another person's instrument wording or paper strategy.
- **I/R** content: summarise freely. Still no phone numbers or emails of private individuals.

## Fixtures

- Build fixtures from made-up values, never by trimming a real file. Real logs carry real patterns (who was near whom, when).
- Use ID ranges and times that exercise the edge cases. Don't try to make them "realistic".
- Hand-derive expected values in the test docstring so a reviewer can check them.

## Tools

- `python3 scripts/check_perimeter.py --staged`: what the pre-commit hook runs.
- `git config core.hooksPath .githooks`: enable the hook, once per clone.
- `social_energy.paths.study("<id>")`: the only sanctioned way to locate real data.

## If something slipped in

1. Stop. Do not push. If it is already pushed, tell the human immediately. Don't try to fix it quietly.
2. Unpushed: `git reset` the commit and remove the file.
3. Pushed: the history must be rewritten (`git filter-repo`) **and** GitHub support asked to purge cached views. The research lead decides whether it is a reportable data breach (GDPR Art. 33, 72-hour clock).
