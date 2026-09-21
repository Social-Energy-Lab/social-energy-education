"""Read a study's public configuration (``studies/<id>/study.yaml`` and siblings).

The toolkit never hard-codes a study. Studies describe themselves in YAML, and this
module turns that description into instrument configs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
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

    def beacon_config(self) -> BeaconConfig:
        section = self.raw["beacons"]
        return BeaconConfig(
            timezone=self.timezone,
            valid_from=_as_date(section["valid_from"]),
            valid_to=_as_date(section["valid_to"]),
            ambiguous_id_cutoff=_as_datetime(section.get("ambiguous_id_cutoff")),
            anchor_tolerance_s=int(section.get("anchor_tolerance_s", 5)),
        )

    def survey_config(self) -> SurveyConfig:
        section = (self.local.get("survey") or {}).get("zeitgeist") or {}
        return SurveyConfig(study_id_item=section.get("study_id_item"))
