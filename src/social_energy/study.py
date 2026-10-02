"""Read a study's public configuration (``studies/<id>/study.yaml`` and siblings).

The toolkit never hard-codes a study. Studies describe themselves in YAML, and this
module turns that description into instrument configs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

import yaml

from . import paths
from .beacons import BeaconConfig
from .survey import SurveyConfig

# Sections that name a private deployment: refused in the public study.yaml (see StudyConfig.local).
PRIVATE_KEYS = (("survey", "study_id_item"), ("ai_interviews", "agents"))


def _as_date(value: Any) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def _as_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))


DEFAULT_EXPLORER = {"close_rssi": -65, "min_minutes": 15, "window_minutes": 120}


@dataclass(frozen=True)
class ExplorerConfig:
    """How the explorer presents one study: display names, day rhythm, notes, defaults."""

    courses: dict[str, str] = field(default_factory=dict)
    day_start: str = "00:00"
    phases: list[tuple[str, str]] = field(default_factory=list)
    notes: list[dict[str, str]] = field(default_factory=list)
    shade: list[dict[str, str]] = field(default_factory=list)
    defaults: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_EXPLORER))
    min_group: int = 5

    def phase_of(self, clock: time) -> int:
        """Index of the last phase starting at or before ``clock``, wrapping past midnight."""
        starts = [time.fromisoformat(start) for _, start in self.phases]
        earlier = [i for i, s in enumerate(starts) if s <= clock]
        if earlier:
            return max(earlier, key=lambda i: starts[i])
        return max(range(len(starts)), key=lambda i: starts[i])


@dataclass(frozen=True)
class StudyConfig:
    path: Path
    study_id: str
    timezone: str
    raw: dict[str, Any]
    locations: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> StudyConfig:
        path = Path(path)
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        for section, key in PRIVATE_KEYS:
            if ((raw.get(section) or {}).get("zeitgeist") or {}).get(key) is not None:
                raise ValueError(
                    f"{path}: {section}.zeitgeist.{key} names a private deployment and must "
                    f"live in $SOCIAL_ENERGY_DATA/<study-id>/local.yaml, not in the public repo."
                )
        roster = path.parent / "locations.yaml"
        locations = (
            yaml.safe_load(roster.read_text(encoding="utf-8")) or [] if roster.exists() else []
        )
        return cls(path, raw["study_id"], raw["timezone"], raw, locations)

    @property
    def local(self) -> dict[str, Any]:
        """Private per-study config, read from ``<data root>/<study-id>/local.yaml``.

        It holds what identifies a private deployment — which interview agent to fetch, which
        question carries the typed study ID — so it travels with the data instead of with the
        code. Missing file, or no data root at all (CI), means "no private config".
        """
        try:
            file = paths.study(self.study_id).root / "local.yaml"
        except paths.DataRootError:
            return {}
        if not file.is_file():
            return {}
        return yaml.safe_load(file.read_text(encoding="utf-8")) or {}

    def zeitgeist_agents(self) -> list[dict[str, Any]]:
        section = (self.local.get("ai_interviews") or {}).get("zeitgeist") or {}
        return list(section.get("agents") or [])

    @property
    def arrival(self) -> date | None:
        dates = self.raw.get("dates") or {}
        return _as_date(dates["arrival"]) if "arrival" in dates else None

    def explorer_config(self) -> ExplorerConfig:
        section = self.raw.get("explorer") or {}
        return ExplorerConfig(
            courses={str(k): str(v) for k, v in (section.get("courses") or {}).items()},
            day_start=str(section.get("day_start", "00:00")),
            phases=[(str(n), str(s)) for n, s in section.get("phases") or []],
            notes=list(section.get("notes") or []),
            shade=list(section.get("shade") or []),
            defaults={**DEFAULT_EXPLORER, **(section.get("defaults") or {})},
            min_group=int(section.get("min_group", 5)),
        )

    def beacon_config(self) -> BeaconConfig:
        section = self.raw["beacons"]
        return BeaconConfig(
            timezone=self.timezone,
            valid_from=_as_date(section["valid_from"]),
            valid_to=_as_date(section["valid_to"]),
            ambiguous_id_cutoff=_as_datetime(section.get("ambiguous_id_cutoff")),
            anchor_tolerance_s=int(section.get("anchor_tolerance_s", 5)),
            restart_margin_s=int(section.get("restart_margin_s", 3600)),
            readout_gap_s=int(section.get("readout_gap_s", 60)),
        )

    def survey_config(self) -> SurveyConfig:
        section = (self.local.get("survey") or {}).get("zeitgeist") or {}
        return SurveyConfig(study_id_item=section.get("study_id_item"))
