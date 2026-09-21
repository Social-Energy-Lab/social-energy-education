#!/usr/bin/env python3
"""Refuse to commit anything that looks like research data.

This repo is public and the data concerns young people under an ethics approval.
This check is the enforced half of AGENTS.md invariant 1. `.gitignore` is the
convenience half: anyone can bypass it with `git add -f`, but they can't bypass this.

Usage:
    check_perimeter.py            # check every tracked file (CI)
    check_perimeter.py --staged   # check staged files (pre-commit hook)

Only synthetic fixtures under `tests/fixtures/` may use data-like formats.

If $SOCIAL_ENERGY_DATA is set, `_team/perimeter-denylist.txt` under it adds a content check for
names and private identifiers. That list stays outside this repo, so CI runs without it.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

MAX_BYTES = 1_000_000

DATA_SUFFIXES = frozenset(
    {
        ".log", ".csv", ".tsv", ".parquet", ".feather", ".arrow",
        ".xlsx", ".xls", ".ods", ".sav", ".dta", ".rds", ".rdata",
        ".json", ".jsonl", ".ndjson", ".h5", ".hdf5", ".mat", ".npz", ".npy",
        ".wav", ".flac", ".mp3", ".m4a", ".mp4", ".mov",
        ".zip", ".gz", ".tar", ".7z", ".db", ".sqlite",
        ".docx", ".pptx", ".pdf",
    }
)  # fmt: skip

# Exact paths that are data-like by extension but are configuration.
ALLOWED_PATHS = frozenset({".claude/settings.json"})
FIXTURES = PurePosixPath("tests/fixtures")


@dataclass(frozen=True)
class Violation:
    path: str
    reason: str


def _is_fixture(path: PurePosixPath) -> bool:
    return path.parts[: len(FIXTURES.parts)] == FIXTURES.parts


def _notebook_has_outputs(file: Path) -> bool:
    try:
        cells = json.loads(file.read_text(encoding="utf-8")).get("cells", [])
    except (json.JSONDecodeError, UnicodeDecodeError):
        return True  # unreadable notebook: treat as unsafe
    return any(cell.get("outputs") for cell in cells)


def load_denylist(data_root: str | None) -> list[str]:
    """Strings the repo must never contain, kept in the private context library.

    The list itself holds names and private identifiers, so it lives outside this repo and is
    only available to someone who has the data. CI has no data root and therefore no list: the
    file-type checks are the public half, this is the local half.
    """
    if not data_root:
        return []
    file = Path(data_root).expanduser() / "_team" / "perimeter-denylist.txt"
    if not file.is_file():
        return []
    entries = []
    for line in file.read_text(encoding="utf-8").splitlines():
        entry = line.strip()
        if entry and not entry.startswith("#"):
            entries.append(entry.casefold())
    return entries


def _denied_strings(file: Path, denylist: list[str]) -> list[str]:
    if not denylist:
        return []
    try:
        text = file.read_text(encoding="utf-8").casefold()
    except (UnicodeDecodeError, OSError):
        return []  # binary or unreadable: the file-type checks cover it
    return [entry for entry in denylist if entry in text]


def find_violations(
    root: Path, paths: list[str], denylist: list[str] | None = None
) -> list[Violation]:
    denylist = denylist or []
    violations: list[Violation] = []
    for rel in paths:
        file = root / rel
        if not file.is_file():
            continue  # deleted or renamed away
        path = PurePosixPath(rel)
        for denied in _denied_strings(file, denylist):
            violations.append(Violation(rel, f"contains a denied string: {denied!r}"))
        if _is_fixture(path) or rel in ALLOWED_PATHS:
            pass
        elif "data" in path.parts[:-1]:
            violations.append(Violation(rel, "inside a data/ directory"))
            continue
        elif path.suffix.lower() in DATA_SUFFIXES:
            violations.append(Violation(rel, f"data-like file type {path.suffix}"))
            continue
        elif path.suffix == ".ipynb" and _notebook_has_outputs(file):
            violations.append(Violation(rel, "notebook with outputs (clear them first)"))
            continue
        if file.stat().st_size > MAX_BYTES:
            violations.append(Violation(rel, f"larger than {MAX_BYTES} bytes"))
    return violations


def _git_paths(root: Path, staged: bool) -> list[str]:
    cmd = (
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"]
        if staged
        else ["git", "ls-files"]
    )
    out = subprocess.run(cmd, cwd=root, capture_output=True, text=True, check=True).stdout
    return [line for line in out.splitlines() if line]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--staged", action="store_true", help="check staged files only")
    args = parser.parse_args(argv)

    root = Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True
        ).stdout.strip()
    )
    denylist = load_denylist(os.environ.get("SOCIAL_ENERGY_DATA"))
    violations = find_violations(root, _git_paths(root, args.staged), denylist)
    if not violations:
        return 0
    print("Data perimeter violation: this repo must never contain research data.\n")
    for v in violations:
        print(f"  {v.path}: {v.reason}")
    print(
        "\nKeep data under $SOCIAL_ENERGY_DATA (outside the repo). Synthetic test data "
        "belongs in tests/fixtures/. See AGENTS.md, invariant 1."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
