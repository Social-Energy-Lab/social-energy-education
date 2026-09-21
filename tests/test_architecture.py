"""The toolkit must stay study-agnostic (AGENTS.md, invariant 2)."""

import ast
from pathlib import Path

TOOLKIT = Path(__file__).resolve().parents[1] / "src" / "social_energy"


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_toolkit_never_imports_from_studies():
    offenders = {
        str(path.relative_to(TOOLKIT)): sorted(n for n in _imports(path) if "studies" in n)
        for path in TOOLKIT.rglob("*.py")
    }
    assert {k: v for k, v in offenders.items() if v} == {}


def test_toolkit_has_no_study_specific_literals():
    # Study facts (dates, IDs, cutoffs) belong in studies/<id>/, not in the toolkit.
    for path in TOOLKIT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "dsa-2026" not in text.lower(), path
        assert "schwäbisch" not in text.lower(), path
