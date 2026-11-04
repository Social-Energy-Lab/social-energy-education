# Cross-group mixing is read outside timetabled group hours

**Date:** 2026-11-04 · **Status:** adopted

## Context

We measured cross-course mixing over the whole camp day and compared special days with ordinary ones. The beacon team asked whether class time was in that figure. It was. Courses sit together in class by design, so a whole-day share partly reads the timetable, and a day without class gains on it automatically.

## Decision

Any comparison of cross-group mixing between days also reports it outside the group's timetabled hours, from a timetable set per day (`course_hours` in `study.yaml`). The whole-day figure stays beside it. A contrast that holds only on the whole day is described as a timetable effect, not a change in how people mix when free to choose.

Room neighbours are checked as a second step. Sleeping rooms stay in the private roster: read at run time, never stored, only aggregates written.

## Consequences

- `exploratory_mixing_outside_class.py` reports both, for mixing and for whether new ties come back. The findings are in the private notes.
- The frozen confirmatory test C2 is unchanged; it is not a comparison between days.
- Next-phase hypothesis H-MIX-1 counts only hours outside group sessions.
