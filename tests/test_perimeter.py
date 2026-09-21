"""The data perimeter: nothing data-like may be committed (AGENTS.md, invariant 1)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from check_perimeter import MAX_BYTES, find_violations, load_denylist


def _write(root: Path, rel: str, content: str | bytes = "x") -> str:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content)
    return rel


@pytest.mark.parametrize(
    "rel",
    [
        "dsa_20260813_1209.log",
        "studies/dsa-2026/contacts.csv",
        "notes/rooms.xlsx",
        "audio/20260814_083000.WAV",
        "derived/contacts.parquet",
        "export/survey.json",
        "data/anything.txt",
        "studies/dsa-2026/data/spine.yaml",
    ],
)
def test_data_like_files_are_rejected(tmp_path, rel):
    _write(tmp_path, rel)
    assert [v.path for v in find_violations(tmp_path, [rel])] == [rel]


@pytest.mark.parametrize(
    "rel",
    [
        "src/social_energy/beacons/parse.py",
        "docs/context/theory.md",
        "studies/dsa-2026/study.yaml",
        ".claude/settings.json",
        "tests/fixtures/synthetic_camp.log",
        "tests/fixtures/spine/devices.csv",
    ],
)
def test_code_docs_and_synthetic_fixtures_are_allowed(tmp_path, rel):
    _write(tmp_path, rel)
    assert find_violations(tmp_path, [rel]) == []


def test_large_files_are_rejected_even_with_allowed_extension(tmp_path):
    rel = _write(tmp_path, "docs/big.md", b"a" * (MAX_BYTES + 1))
    assert [v.path for v in find_violations(tmp_path, [rel])] == [rel]


def test_notebook_with_outputs_is_rejected_but_clean_notebook_allowed(tmp_path):
    dirty = {"cells": [{"cell_type": "code", "source": "df", "outputs": [{"data": "..."}]}]}
    clean = {"cells": [{"cell_type": "code", "source": "df", "outputs": []}]}
    _write(tmp_path, "studies/x/dirty.ipynb", json.dumps(dirty))
    _write(tmp_path, "studies/x/clean.ipynb", json.dumps(clean))
    found = find_violations(tmp_path, ["studies/x/dirty.ipynb", "studies/x/clean.ipynb"])
    assert [v.path for v in found] == ["studies/x/dirty.ipynb"]


def test_deleted_paths_are_ignored(tmp_path):
    assert find_violations(tmp_path, ["gone.log"]) == []


def test_repository_itself_is_clean():
    root = Path(__file__).resolve().parents[1]
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.split()
    assert find_violations(root, tracked) == []


def test_denylist_rejects_a_denied_string_in_any_text_file(tmp_path):
    """The denylist catches what the file-type checks cannot: a name typed into a doc."""
    rel = _write(tmp_path, "docs/context/project.md", "Supervised by Jane Invented-Name.\n")
    violations = find_violations(tmp_path, [rel], denylist=["jane invented-name"])
    assert [v.path for v in violations] == [rel]
    assert "denied string" in violations[0].reason


def test_denylist_is_case_insensitive_and_matches_inside_words(tmp_path):
    rel = _write(tmp_path, "docs/plans/ideas/x.md", "see agent ABC-123 on the platform\n")
    assert find_violations(tmp_path, [rel], denylist=["abc-123"])


def test_without_a_denylist_clean_text_passes(tmp_path):
    rel = _write(tmp_path, "docs/context/theory.md", "Nothing private here.\n")
    assert find_violations(tmp_path, [rel]) == []
    assert find_violations(tmp_path, [rel], denylist=["something else"]) == []


def test_load_denylist_ignores_comments_and_blank_lines(tmp_path):
    (tmp_path / "_team").mkdir()
    (tmp_path / "_team" / "perimeter-denylist.txt").write_text(
        "# a comment\n\n  Spaced Name  \nsecond\n"
    )
    assert load_denylist(str(tmp_path)) == ["spaced name", "second"]


def test_load_denylist_without_a_data_root_is_empty():
    """CI has no data root, so the denylist half of the check is simply absent there."""
    assert load_denylist(None) == []
    assert load_denylist("/nonexistent/path") == []
