"""Command line entry points. Everything reads and writes under $SOCIAL_ENERGY_DATA.

social-energy init-spine studies/<id>/study.yaml
    Create the local spine templates for a study, seeding locations and
    location-tag assignments from studies/<id>/locations.yaml.

social-energy ingest-beacons studies/<id>/study.yaml
    Parse $SOCIAL_ENERGY_DATA/<id>/raw/beacons/*.log into
    $SOCIAL_ENERGY_DATA/<id>/derived/beacons/*.parquet plus qa.json.

social-energy extract-acoustics studies/<id>/study.yaml [--delete-wavs]
    AudioMoth WAVs under raw/audiomoth/<device>/ -> derived/acoustics/<device>/.

social-energy fetch-zeitgeist studies/<id>/study.yaml
    Copy the AI interviews and post-interview survey of every zeitgeist-platform
    agent listed under ai_interviews.zeitgeist.agents in the study's private
    local.yaml (in the data root, never in this repo) into
    $SOCIAL_ENERGY_DATA/<id>/raw/{ai-interviews,survey}/zeitgeist/<agent_name>/.
    Needs ZEITGEIST_DATABASE_URL (read-only login) and `uv sync --extra zeitgeist`.

social-energy ingest-survey studies/<id>/study.yaml
    Parse raw/survey/zeitgeist/*/responses.jsonl into
    derived/survey/{items,respondents}.parquet plus qa.json.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

from . import paths, zeitgeist
from .acoustics import AcousticsConfig, extract_directory
from .beacons import ingest_logs
from .study import StudyConfig
from .survey import ingest_zeitgeist

SPINE_README = """\
# Local spine (never commit)

Transcribe the field log here, using IDs only. Schema: social_energy/spine/models.py.
- people.yaml       {id, role, consent: [beacons, self_report, eda, acoustics, survey, ...]}
- assignments.yaml  {device: "beacon:74", entity: "person:74", start, end?}
- exclusions.yaml   {target: "beacon:78" | "person:92", start, end?, reason}
- events.yaml       {id, label, kind, start, end, locations: [...], tags: [...]}
Times are local wall-clock in the study timezone ("2026-08-14 15:40:00").
"""


def init_spine(study: StudyConfig) -> int:
    spine_dir = paths.study(study.study_id).spine
    if spine_dir.exists() and any(spine_dir.iterdir()):
        print(f"{spine_dir} already has files; refusing to overwrite local work.")
        return 1
    spine_dir.mkdir(parents=True, exist_ok=True)
    start = f"{study.arrival.isoformat()} 00:00:00" if study.arrival else None

    def dump(name: str, content) -> None:
        (spine_dir / f"{name}.yaml").write_text(
            yaml.safe_dump(content, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )

    dump("meta", {"study_id": study.study_id, "timezone": study.timezone})
    dump("people", [])
    dump(
        "locations",
        [
            {"id": f"tag-{loc['tag']}", "label": loc["label"], "zone": loc["zone"],
             "kind": loc["kind"]}
            for loc in study.locations
        ],
    )  # fmt: skip
    dump(
        "assignments",
        [
            {"device": f"beacon:{loc['tag']}", "entity": f"location:tag-{loc['tag']}",
             "start": start}
            for loc in study.locations
        ],
    )  # fmt: skip
    dump("events", [])
    dump("exclusions", [])
    (spine_dir / "README.md").write_text(SPINE_README, encoding="utf-8")
    print(f"Spine templates written to {spine_dir} ({len(study.locations)} location tags).")
    return 0


def ingest_beacons(study: StudyConfig) -> int:
    layout = paths.study(study.study_id)
    logs = sorted((layout.raw / "beacons").glob("*.log"))
    if not logs:
        print(f"No .log files in {layout.raw / 'beacons'}")
        return 1
    tables = ingest_logs(logs, study.beacon_config())
    out = layout.derived / "beacons"
    out.mkdir(parents=True, exist_ok=True)
    for name in ("readouts", "contacts", "self_reports", "eco_sessions"):
        getattr(tables, name).write_parquet(out / f"{name}.parquet")
    (out / "qa.json").write_text(json.dumps(tables.qa, indent=2), encoding="utf-8")
    print(json.dumps(tables.qa, indent=2))
    print(f"Wrote {out}")
    return 0


def extract_acoustics(study: StudyConfig, delete_wavs: bool = False) -> int:
    layout = paths.study(study.study_id)
    device_dirs = sorted(p for p in (layout.raw / "audiomoth").glob("*") if p.is_dir())
    if not device_dirs:
        print(f"No device folders in {layout.raw / 'audiomoth'}")
        return 1
    section = study.raw.get("acoustics") or {}
    config = AcousticsConfig(filename_timezone=section.get("filename_timezone", "UTC"))
    failures = 0
    for device_dir in device_dirs:
        manifest = extract_directory(
            device_dir, layout.derived / "acoustics" / device_dir.name, config,
            delete_wavs=delete_wavs,
        )  # fmt: skip
        errors = manifest.filter(manifest["error"] != "")
        failures += errors.height
        print(
            f"{device_dir.name}: {manifest.height} files, "
            f"{int(manifest['deleted'].sum())} deleted, {errors.height} errors"
        )
    return 1 if failures else 0


def fetch_zeitgeist(study: StudyConfig) -> int:
    agents = study.zeitgeist_agents()
    if not agents:
        print(
            f"No ai_interviews.zeitgeist.agents in $SOCIAL_ENERGY_DATA/{study.study_id}/local.yaml"
        )
        return 1
    dsn = os.environ.get(zeitgeist.DSN_ENV_VAR)
    if not dsn:
        print(f"Set {zeitgeist.DSN_ENV_VAR} to the platform's read-only connection string.")
        return 2
    raw_dir = paths.study(study.study_id).raw
    old_umask = os.umask(0o077)  # exported files readable by the owner only
    try:
        for entry in agents:
            export = zeitgeist.fetch(dsn, entry["id"])
            exported_at = datetime.now(UTC).isoformat(timespec="seconds")
            written = zeitgeist.write(export, raw_dir, exported_at=exported_at)
            print(f"{export.agent['agent_name']} ({entry.get('wave', '?')}): {export.qa}")
            print(f"  -> {written['interviews']}\n  -> {written['survey']}")
    finally:
        os.umask(old_umask)
    return 0


def ingest_survey(study: StudyConfig) -> int:
    layout = paths.study(study.study_id)
    exports = sorted((layout.raw / "survey" / "zeitgeist").glob("*/responses.jsonl"))
    if not exports:
        print(f"No */responses.jsonl in {layout.raw / 'survey' / 'zeitgeist'}")
        return 1
    tables = ingest_zeitgeist(exports, study.survey_config())
    out = layout.derived / "survey"
    out.mkdir(parents=True, exist_ok=True)
    tables.items.write_parquet(out / "items.parquet")
    tables.respondents.write_parquet(out / "respondents.parquet")
    (out / "qa.json").write_text(json.dumps(tables.qa, indent=2), encoding="utf-8")
    print(json.dumps(tables.qa, indent=2))
    print(f"Wrote {out}")
    return 0


COMMANDS = {
    "init-spine": init_spine,
    "ingest-beacons": ingest_beacons,
    "extract-acoustics": extract_acoustics,
    "fetch-zeitgeist": fetch_zeitgeist,
    "ingest-survey": ingest_survey,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="social-energy", description=__doc__)
    parser.add_argument("command", choices=sorted(COMMANDS))
    parser.add_argument("study_yaml", type=Path, help="path to studies/<id>/study.yaml")
    parser.add_argument(
        "--delete-wavs", action="store_true", help="extract-acoustics: delete verified WAVs"
    )
    args = parser.parse_args(argv)
    try:
        study = StudyConfig.load(args.study_yaml)
        if args.command == "extract-acoustics":
            return extract_acoustics(study, delete_wavs=args.delete_wavs)
        return COMMANDS[args.command](study)
    except paths.DataRootError as err:
        print(err)
        return 2


if __name__ == "__main__":
    sys.exit(main())
