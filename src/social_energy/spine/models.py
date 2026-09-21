"""The study spine: who and what exists in a study, and who wore which device when.

References are typed strings so every table can join on them unambiguously:

* devices:  ``"<kind>:<key>"``  e.g. ``beacon:7``, ``eda:SH07``, ``audiomoth:mensa``
* entities: ``"person:<id>"`` or ``"location:<id>"``

Time intervals are half-open ``[start, end)``; ``end=None`` means "until the study ends".
All datetimes are timezone-aware UTC once loaded.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Role(StrEnum):
    participant = "participant"
    course_leader = "course_leader"
    academy_leader = "academy_leader"
    musician = "musician"
    researcher = "researcher"
    guest = "guest"


class Module(StrEnum):
    """Consent is modular: each person agrees to data collection per module."""

    beacons = "beacons"
    self_report = "self_report"
    eda = "eda"
    acoustics = "acoustics"
    survey = "survey"
    interview_in_person = "interview_in_person"
    interview_ai = "interview_ai"
    observations = "observations"


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Person(_Model):
    id: str
    role: Role
    consent: frozenset[Module] = Field(default_factory=frozenset)

    @property
    def ref(self) -> str:
        return f"person:{self.id}"


class Location(_Model):
    id: str
    label: str
    zone: str
    kind: str = "room"  # room | outdoor | transit | ...

    @property
    def ref(self) -> str:
        return f"location:{self.id}"


class Interval(_Model):
    start: datetime
    end: datetime | None = None

    def contains(self, t: datetime) -> bool:
        return self.start <= t and (self.end is None or t < self.end)

    def overlaps(self, other: Interval) -> bool:
        return (other.end is None or self.start < other.end) and (
            self.end is None or other.start < self.end
        )


class Assignment(Interval):
    """``device`` was attached to ``entity`` (worn by a person, or fixed in a location)."""

    device: str
    entity: str

    @property
    def device_kind(self) -> str:
        return self.device.split(":", 1)[0]


class Event(Interval):
    """A programme item: plenum, course, KüA, meal, excursion, concert, ..."""

    id: str
    label: str
    kind: str
    locations: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()


class Exclusion(Interval):
    """Data from ``target`` (a device or a person) in this window must not be used."""

    target: str
    reason: str
