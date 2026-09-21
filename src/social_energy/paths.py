"""Where research data lives: always outside this repository.

All toolkit code that touches real data finds it through this module, so the
"never inside the repo" rule (AGENTS.md, invariant 1) is enforced in one place.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ENV_VAR = "SOCIAL_ENERGY_DATA"
REPO_ROOT = Path(__file__).resolve().parents[2]


class DataRootError(RuntimeError):
    pass


def data_root() -> Path:
    raw = os.environ.get(ENV_VAR)
    if not raw:
        raise DataRootError(
            f"Set {ENV_VAR} to the local folder holding research data (outside this repo)."
        )
    root = Path(raw).expanduser().resolve()
    if root == REPO_ROOT or REPO_ROOT in root.parents:
        raise DataRootError(
            f"{ENV_VAR}={root} is inside the repository; research data must live outside it."
        )
    return root


@dataclass(frozen=True)
class StudyLayout:
    root: Path

    @property
    def raw(self) -> Path:
        return self.root / "raw"

    @property
    def spine(self) -> Path:
        return self.root / "spine"

    @property
    def derived(self) -> Path:
        return self.root / "derived"


def study(study_id: str) -> StudyLayout:
    return StudyLayout(data_root() / study_id)
