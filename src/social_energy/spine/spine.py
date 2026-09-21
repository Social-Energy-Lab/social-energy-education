"""Load, validate and query a study spine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import polars as pl
import yaml
from pydantic import ValidationError

from .models import Assignment, Event, Exclusion, Interval, Location, Module, Person

SPINE_FILES = ("people", "locations", "assignments", "events", "exclusions")


class SpineError(ValueError):
    pass


def _to_utc(value: Any, tz: ZoneInfo) -> Any:
    """Naive datetimes in spine files are wall-clock time in the study's timezone."""
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=tz)
        return value.astimezone(ZoneInfo("UTC"))
    return value


def _read_list(directory: Path, name: str) -> list[dict]:
    path = directory / f"{name}.yaml"
    if not path.exists():
        return []
    return yaml.safe_load(path.read_text(encoding="utf-8")) or []


@dataclass(frozen=True)
class Spine:
    study_id: str
    timezone: str
    people: tuple[Person, ...]
    locations: tuple[Location, ...]
    assignments: tuple[Assignment, ...]
    events: tuple[Event, ...]
    exclusions: tuple[Exclusion, ...]

    # ---- loading ---------------------------------------------------------

    @classmethod
    def load(cls, directory: Path) -> Spine:
        directory = Path(directory)
        meta = yaml.safe_load((directory / "meta.yaml").read_text(encoding="utf-8"))
        tz = ZoneInfo(meta["timezone"])

        def build(model, name, time_fields=("start", "end")):
            items = []
            for raw in _read_list(directory, name):
                data = {k: (_to_utc(v, tz) if k in time_fields else v) for k, v in raw.items()}
                try:
                    items.append(model(**data))
                except ValidationError as err:
                    raise SpineError(f"{name}.yaml: invalid entry {raw!r}: {err}") from err
            return tuple(items)

        spine = cls(
            study_id=meta["study_id"],
            timezone=meta["timezone"],
            people=build(Person, "people"),
            locations=build(Location, "locations"),
            assignments=build(Assignment, "assignments"),
            events=build(Event, "events"),
            exclusions=build(Exclusion, "exclusions"),
        )
        spine.validate()
        return spine

    def validate(self) -> None:
        known = {p.ref for p in self.people} | {loc.ref for loc in self.locations}
        for a in self.assignments:
            if a.entity not in known:
                raise SpineError(f"assignment of {a.device} refers to unknown {a.entity}")
            if a.end is not None and a.end <= a.start:
                raise SpineError(f"assignment of {a.device} to {a.entity} ends before it starts")
        for e in self.exclusions:
            if e.target.startswith(("person:", "location:")) and e.target not in known:
                raise SpineError(f"exclusion refers to unknown {e.target}")

        def no_overlap(key, label):
            groups: dict[str, list[Assignment]] = {}
            for a in self.assignments:
                if (k := key(a)) is not None:
                    groups.setdefault(k, []).append(a)
            for k, items in groups.items():
                items.sort(key=lambda a: a.start)
                for prev, nxt in pairwise(items):
                    if prev.overlaps(nxt):
                        raise SpineError(
                            f"{label} {k}: overlapping assignments starting "
                            f"{prev.start.isoformat()} and {nxt.start.isoformat()}"
                        )

        no_overlap(lambda a: a.device, "device")
        # A person may wear a beacon and an EDA sensor at once, never two of one kind.
        no_overlap(
            lambda a: f"{a.entity} ({a.device_kind})" if a.entity.startswith("person:") else None,
            "entity",
        )

    # ---- scalar queries --------------------------------------------------

    def entity_for(self, device: str, t: datetime) -> str | None:
        for a in self.assignments:
            if a.device == device and a.contains(t):
                return a.entity
        return None

    def consented(self, module: Module | str) -> set[str]:
        module = Module(module)
        return {p.id for p in self.people if module in p.consent}

    # ---- vectorised queries ------------------------------------------------

    def _intervals_frame(self, items: list[Interval], columns: dict[str, list]) -> pl.DataFrame:
        return pl.DataFrame(
            {
                **columns,
                "_start": [i.start for i in items],
                "_end": [i.end for i in items],
            },
            schema_overrides={
                "_start": pl.Datetime("us", "UTC"),
                "_end": pl.Datetime("us", "UTC"),
            },
        )

    def resolve(
        self, df: pl.DataFrame, *, device_col: str, time_col: str, kind: str, out: str
    ) -> pl.DataFrame:
        """Add column ``out`` with the entity wearing ``kind:<device_col>`` at ``time_col``."""
        items = [a for a in self.assignments if a.device_kind == kind]
        table = self._intervals_frame(
            items,
            {
                "_key": [a.device.split(":", 1)[1] for a in items],
                out: [a.entity for a in items],
            },
        )
        keyed = df.with_row_index("_row").with_columns(
            pl.col(device_col).cast(pl.String).alias("_key")
        )
        matched = (
            keyed.select("_row", "_key", time_col)
            .join(table, on="_key", how="inner")
            .filter(
                (pl.col(time_col) >= pl.col("_start"))
                & (pl.col("_end").is_null() | (pl.col(time_col) < pl.col("_end")))
            )
            .select("_row", out)
        )
        return keyed.join(matched, on="_row", how="left").sort("_row").drop("_row", "_key")

    def flag_excluded(
        self,
        df: pl.DataFrame,
        *,
        device_col: str,
        time_col: str,
        kind: str,
        out: str = "excluded",
    ) -> pl.DataFrame:
        """Add boolean ``out``: the device, or whoever wore it, is in an exclusion window.

        For contacts, call it once per side (observer and observed) with different ``out``.
        """
        resolved = self.resolve(
            df, device_col=device_col, time_col=time_col, kind=kind, out="_entity"
        ).with_columns((pl.lit(f"{kind}:") + pl.col(device_col).cast(pl.String)).alias("_dev"))
        table = self._intervals_frame(
            list(self.exclusions), {"_target": [e.target for e in self.exclusions]}
        )
        rows = resolved.with_row_index("_row")
        hits = pl.concat(
            [
                rows.select("_row", time_col, pl.col(col).alias("_target"))
                .join(table, on="_target", how="inner")
                .filter(
                    (pl.col(time_col) >= pl.col("_start"))
                    & (pl.col("_end").is_null() | (pl.col(time_col) < pl.col("_end")))
                )
                .select("_row")
                for col in ("_dev", "_entity")
            ]
        ).unique()
        return rows.with_columns(pl.col("_row").is_in(hits["_row"].implode()).alias(out)).drop(
            "_row", "_entity", "_dev"
        )
