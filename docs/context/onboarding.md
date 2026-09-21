# Onboarding: setting up a machine

For a researcher, or an agent working on their behalf, who is starting from nothing. It assumes
the repo pair described in [AGENTS.md](../../AGENTS.md#the-private-half): this **public** repo
with the methods, and a **private** repo that is also the data root.

Read [AGENTS.md](../../AGENTS.md) first, in full. It is short and it is binding.

## 1. The public repo (this one)

```bash
git clone <this repo> && cd social-energy-education
uv sync
git config core.hooksPath .githooks    # the data-perimeter pre-commit hook
uv run pytest                          # everything runs on synthetic data
```

All 97 tests must pass before you change anything. They need no data.

## 2. The private repo (context and data root)

Ask the project lead for access. Then:

```bash
git clone <private repo> ~/research-data/social-energy
cd ~/research-data/social-energy && git config core.hooksPath .githooks
echo 'export SOCIAL_ENERGY_DATA=~/research-data/social-energy' >> ~/.bashrc
chmod -R go-rwx ~/research-data/social-energy
```

Put it on an **encrypted disk**: the ethics approval requires encrypted storage with access
limited to the project lead and explicitly authorised staff.

The private repo carries the text layer only. The data itself, the field logs and the spine are
**not** in it: ask the project lead for the encrypted archive, unpack it into the same tree, and
verify it with `sha256sum -c` in each folder before deleting the source. The layout is in
[data-layout.md](data-layout.md).

With the data root set, the perimeter check gains its content half: it will refuse a commit that
contains a name or private identifier listed in `_team/perimeter-denylist.txt`.

## 3. Working rules worth repeating

- **Write in the private half by default.** Anything you are unsure about is private. This repo
  gets methods, instrument facts and the rules derived from findings — never the findings
  themselves, never a person, never a count from the real data.
- **Never** `git commit --no-verify`, in either repo.
- Before claiming done: `uv run ruff check . && uv run ruff format --check . && uv run pytest`.
- New instrument or export format: the [`add-data-source`](../../.agents/skills/add-data-source/SKILL.md)
  skill. New analysis: [`add-analysis`](../../.agents/skills/add-analysis/SKILL.md). Anything near
  real data: [`data-perimeter`](../../.agents/skills/data-perimeter/SKILL.md).

## 4. Publishing this repo

The public repo is published from a **clean history**: it was squashed to a single commit before
its first push, because earlier commits contained material that is now in the private half. If
you are moving the repo to a new home (for example a university organisation):

```bash
# 1. Verify the working tree, with the data root set so the denylist applies.
uv run ruff check . && uv run ruff format --check . && uv run pytest
python3 scripts/check_perimeter.py

# 2. Check the whole history, not just the tip: every commit is published.
git log --oneline
git log -p | grep -nEi '<name>|<identifier>'   # entries from _team/perimeter-denylist.txt

# 3. Push.
git remote add <name> <url> && git push -u <name> main
```

If step 2 finds anything, **do not push**. Rewrite the history first (squash, or
`git filter-repo`), because a public git history cannot be recalled. If something has already
been pushed, tell the project lead immediately rather than fixing it quietly: the research lead
decides whether it is a reportable data breach (GDPR Art. 33, 72-hour clock).

Before the first publication of a new study's material, re-read
[`data-perimeter`](../../.agents/skills/data-perimeter/SKILL.md) and check the study's
`README.md` and plans for counts, anecdotes and names that belong in the private half.
