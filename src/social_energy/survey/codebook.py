"""The survey codebook: which export codes form which scale, and how to recode them.

A codebook is public study config (``studies/<id>/survey_codebook.yaml``, named by
``survey.codebook`` in ``study.yaml``). It holds item codes, scale keys, ranges and recoding
rules, and never the wording of an item.

Each **group** is a set of items recoded the same way:

* ``kind: scale``: averaged into a scale score (with a minimum-items rule) and checked for
  reliability;
* ``kind: gradient``: a gradient item, scored on its own and never inside its ``parent`` scale;
* ``kind: items``: recoded but not averaged (single items, categorical sets).

Recoding order: non-substantive codes and out-of-range values become missing; a scale printed
in reverse (``printed_reversed``) is flipped so that high means more of the construct; then
each item in ``reverse`` (worded against the construct) is flipped. Both flips are
``min + max - x``.

Minimum items: a scale score needs ``max(min_items_floor, ceil(min_share x k))`` valid items,
capped at ``k`` (the items in the scale), unless the group sets ``min_items``.

Statuses: ``confirmed`` (by the research team), ``decided`` (an analyst's decision, recorded
with who and when under ``decisions``; it can be revised), ``confirmed_by_check`` (a rule that
an empirical check in ``social_energy.survey.checks`` agreed with), ``inferred`` (from
documents) and ``unknown``. The first three are settled; ``Codebook.pending()`` lists the
others so a scoring run can say it is provisional.
"""

from __future__ import annotations

import fnmatch
import math
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

Status = Literal["confirmed", "decided", "confirmed_by_check", "inferred", "unknown"]
SETTLED: frozenset[str] = frozenset({"confirmed", "decided", "confirmed_by_check"})
Kind = Literal["scale", "gradient", "items"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Rename(_Strict):
    """An item code from an older form version and the current code it stands for."""

    to: str
    status: Status
    note: str | None = None


class Group(_Strict):
    block: Literal["A", "B", "C"]
    role: str
    kind: Kind
    concept: str
    source: str | None = None
    prefix: str = ""
    items: list[str] = Field(min_length=1)
    range: tuple[int, int]
    range_status: Status = "confirmed"
    printed_reversed: bool = False
    reverse: list[str] = Field(default_factory=list)
    reverse_status: Status | None = None
    reverse_source: str | None = None
    missing_codes: list[str] = Field(default_factory=list)
    code_values: dict[str, int] = Field(default_factory=dict)
    min_items: int | None = None
    parent: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Group:
        lo, hi = self.range
        if lo >= hi:
            raise ValueError(f"range {self.range} must run from low to high")
        unknown = sorted(set(self.reverse) - set(self.items))
        if unknown:
            raise ValueError(f"reverse lists items outside the group: {unknown}")
        if self.kind == "scale" and self.reverse_status is None:
            raise ValueError("a scale needs a reverse_status, even when nothing is reversed")
        if (self.kind == "gradient") != (self.parent is not None):
            raise ValueError("a gradient names its parent scale, and only a gradient does")
        if self.min_items is not None and not 1 <= self.min_items <= len(self.items):
            raise ValueError(f"min_items {self.min_items} outside 1..{len(self.items)}")
        return self

    @property
    def codes(self) -> list[str]:
        """Full export codes of the items, in codebook order."""
        return [self.prefix + item for item in self.items]

    @property
    def reverse_codes(self) -> set[str]:
        return {self.prefix + item for item in self.reverse}

    def min_items_required(self, min_share: float, floor: int = 1) -> int:
        """``min_items`` if set, else ``max(floor, ceil(min_share x k))`` capped at ``k``."""
        if self.min_items is not None:
            return self.min_items
        k = len(self.items)
        return min(k, max(floor, math.ceil(min_share * k)))

    def statuses(self) -> dict[str, Status | None]:
        return {"range_status": self.range_status, "reverse_status": self.reverse_status}


class Codebook(_Strict):
    title: str
    version: int
    roles: dict[str, str]
    min_share: float = Field(gt=0, le=1)
    min_share_status: Status
    min_items_floor: int = Field(default=1, ge=1)
    decisions: list[str] = Field(default_factory=list)
    renames: dict[str, Rename] = Field(default_factory=dict)
    groups: dict[str, Group]
    unscored: dict[str, list[str]] = Field(default_factory=dict)
    pending_questions: list[str] = Field(default_factory=list, alias="pending")

    @model_validator(mode="after")
    def _consistent(self) -> Codebook:
        owner: dict[str, str] = {}
        for key, group in self.groups.items():
            expected = self.roles.get(group.block)
            if expected is not None and group.role != expected:
                raise ValueError(f"{key}: block {group.block} has role {expected!r}")
            if group.parent is not None:
                parent = self.groups.get(group.parent)
                if parent is None or parent.kind != "scale":
                    raise ValueError(f"{key}: parent {group.parent!r} is not a scale")
            for code in group.codes:
                if code in owner:
                    raise ValueError(f"{code} is in more than one group ({owner[code]}, {key})")
                owner[code] = key
        for old, rename in self.renames.items():
            if rename.to not in owner:
                raise ValueError(f"rename {old} -> {rename.to}: target is in no group")
            if old in owner:
                raise ValueError(f"rename {old}: the old code is still in group {owner[old]}")
        return self

    def group_of(self, code: str) -> str | None:
        for key, group in self.groups.items():
            if code in group.codes:
                return key
        return None

    def item_index(self) -> dict[str, str]:
        return {code: key for key, group in self.groups.items() for code in group.codes}

    def unscored_patterns(self) -> list[str]:
        return [pattern for patterns in self.unscored.values() for pattern in patterns]

    def knows(self, code: str) -> bool:
        if code in self.renames or self.group_of(code) is not None:
            return True
        return any(fnmatch.fnmatchcase(code, p) for p in self.unscored_patterns())

    def entries(self) -> list[str]:
        """Every code or pattern the codebook names: group items, rename sources, unscored."""
        return [*self.item_index(), *self.renames, *self.unscored_patterns()]

    def pending(self) -> list[str]:
        """Entries not settled (see the module docstring), as ``path: status`` strings."""
        out = []
        if self.min_share_status not in SETTLED:
            out.append(f"min_share_status: {self.min_share_status}")
        for old, rename in self.renames.items():
            if rename.status not in SETTLED:
                out.append(f"renames.{old}: {rename.status}")
        for key, group in self.groups.items():
            for field, status in group.statuses().items():
                if status is not None and status not in SETTLED:
                    out.append(f"groups.{key}.{field}: {status}")
        return out

    def is_provisional(self, key: str) -> bool:
        """True when a group's score rests on an entry that is not settled."""
        group = self.groups[key]
        if (
            self.min_share_status not in SETTLED
            and group.min_items is None
            and group.kind == "scale"
        ):
            return True
        if any(s is not None and s not in SETTLED for s in group.statuses().values()):
            return True
        return any(r.status not in SETTLED for r in self.renames.values() if r.to in group.codes)

    def min_items_for(self, key: str) -> int:
        """Valid items a score of group ``key`` needs (see the module docstring)."""
        return self.groups[key].min_items_required(self.min_share, self.min_items_floor)


def load_codebook(path: Path) -> Codebook:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return Codebook.model_validate(raw)
