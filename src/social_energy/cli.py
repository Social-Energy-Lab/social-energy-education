"""Command line entry points. Everything reads and writes under $SOCIAL_ENERGY_DATA.

social-energy init-spine studies/<id>/study.yaml
    Create the local spine templates for a study, seeding locations and
    location-tag assignments from studies/<id>/locations.yaml.

social-energy ingest-beacons studies/<id>/study.yaml
    Parse every .log under $SOCIAL_ENERGY_DATA/<id>/raw/beacons/, one file at a time, into
    $SOCIAL_ENERGY_DATA/<id>/derived/beacons/: readouts, self_reports and eco_sessions parquet,
    contacts/<local day>.parquet, plus qa.json. Refuses (exit 4) while any log names a device
    listed under beacons.purged_devices in the study's private local.yaml.

social-energy purge-device studies/<id>/study.yaml --device N [--dry-run | --apply]
    Count the lines naming device N (as ID or ID2) in every .log under raw/beacons/. With --apply,
    remove them, keep the delivery manifest as SHA256SUMS.as-delivered, recompute SHA256SUMS and
    append the counts to raw/beacons/IMPORT.md. Dry run by default.

social-energy ingest-eda studies/<id>/study.yaml
    Shimmer SD cards under raw/eda/sd-cards/<card>/ and calibrated exports under
    raw/eda/imported/*/ -> derived/eda/: files, seconds, scr and wear parquet, plus
    person_minutes.parquet (through the spine, EDA consent only) and qa.json. One device and
    one run at a time.

social-energy eda-heart-rate studies/<id>/study.yaml
    Heart rate from the raw PPG of the same cards and exports -> derived/eda/: hr_beats,
    hr_windows (10 s, with quality flags), hr_minutes (per device-minute; joins onto
    person_minutes by device and minute), hr_agreement (against the exports' own heart
    rate) and hr_usability (per device-day) parquet, plus hr_qa.json. Reads wear.parquet from
    ingest-eda to flag worn windows; writes nothing else. One device and one run at a time.
social-energy extract-acoustics studies/<id>/study.yaml [--delete-wavs]
    AudioMoth WAVs under raw/audiomoth/<device>/ -> derived/acoustics/<device>/.

social-energy fetch-zeitgeist studies/<id>/study.yaml
    Copy the AI interviews and post-interview survey of every zeitgeist-platform
    agent listed under ai_interviews.zeitgeist.agents in the study's private
    local.yaml (in the data root, never in this repo) into
    $SOCIAL_ENERGY_DATA/<id>/raw/{ai-interviews,survey}/zeitgeist/<agent_name>/.
    Needs ZEITGEIST_DATABASE_URL (read-only login) and `uv sync --extra zeitgeist`.

social-energy explore studies/<id>/study.yaml [--port N] [--no-browser]
    Serve the explorer on http://127.0.0.1:<port> for the bundle in
    $SOCIAL_ENERGY_DATA/<id>/derived/explorer/bundle/ (made by the study's
    analyses/explorer_export.py). Local only; the bundle is pseudonymised data.

social-energy ingest-survey studies/<id>/study.yaml
    Parse raw/survey/zeitgeist/*/responses.jsonl into
    derived/survey/{items,respondents}.parquet plus qa.json.

social-energy score-survey studies/<id>/study.yaml
    Score derived/survey/items.parquet with the codebook named by survey.codebook into
    derived/survey/scoring/{scores,reliability,submissions}.parquet plus qa.json. Refuses
    until survey.analysis_plan_frozen is set: scales are scored only after the analysis
    plan is signed and frozen.

social-energy check-survey studies/<id>/study.yaml
    Run the pre-scoring checks on derived/survey/items.parquet (kept submissions only):
    reverse-keying against item-rest correlations and old form-version codes against their
    current codes. Writes derived/survey/checks/{reverse_keys,versions}.parquet plus
    summary.json. Computes no scale score, so it does not wait for the freeze.

social-energy site-build studies/<id>/study.yaml --out DIR [--data DIR]
    Assemble the public GitHub Pages site in DIR (outside the repo): the app files plus a
    validated data/. With --data DIR the public data prepared elsewhere is copied in; without
    it a synthetic camp is built, which needs no $SOCIAL_ENERGY_DATA.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import yaml

from . import paths, zeitgeist
from .acoustics import AcousticsConfig, extract_directory
from .beacons import (
    BeaconConfig,
    PurgedDeviceError,
    check_purged,
    ingest_with_witnesses,
    purge_devices,
)
from .eda.heart import agreement, heart_rate, usability
from .eda.ingest import ingest_eda
from .eda.person import person_minutes
from .spine import Spine
from .study import StudyConfig
from .survey import (
    ingest_zeitgeist,
    load_codebook,
    load_corrections,
    resolve_submissions,
    reverse_key_check,
    score_survey,
    version_equivalence,
)

SPINE_README = """\
# Local spine (never commit)

Transcribe the field log here, using IDs only. Schema: social_energy/spine/models.py.
- people.yaml       {id, role, consent: [beacons, self_report, eda, acoustics, survey, ...],
                     course?, age?, gender?}
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


def ingest_beacons(
    study: StudyConfig, config: BeaconConfig | None = None, out: Path | None = None
) -> int:
    """Ingest every raw log into ``derived/beacons/`` with the study's own settings.

    A sensitivity analysis passes ``config`` (the study's settings with one change) and ``out``, a
    folder of its own under ``derived/``; ``derived/beacons/`` only ever holds the study's settings,
    so a changed config without its own ``out`` is refused (exit 2).
    """
    layout = paths.study(study.study_id)
    main_out = layout.derived / "beacons"
    out = main_out if out is None else Path(out)
    if config is not None and out.resolve() == main_out.resolve():
        print(f"A changed beacon config needs its own output folder, not {main_out}.")
        return 2
    if not out.resolve().is_relative_to(layout.derived.resolve()):
        print(f"The ingest writes under {layout.derived}, not {out}.")
        return 2
    logs = sorted((layout.raw / "beacons").rglob("*.log"))
    if not logs:
        print(f"No .log files under {layout.raw / 'beacons'}")
        return 1
    config = study.beacon_config() if config is None else config
    try:
        check_purged(logs, config.purged_devices)  # before derived/ is touched
    except PurgedDeviceError as err:
        print(err)
        return 4
    if out.exists():
        shutil.rmtree(out)
    qa = ingest_with_witnesses(logs, config, out)
    (out / "qa.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")
    print(json.dumps(qa, indent=2))
    print(f"Wrote {out}")
    return 0


def purge_device(study: StudyConfig, devices: list[int], apply: bool = False) -> int:
    folder = paths.study(study.study_id).raw / "beacons"
    if not devices:
        print("Name the device to purge with --device N.")
        return 2
    if not folder.is_dir():
        print(f"No {folder}")
        return 1
    label = ", ".join(str(d) for d in devices)
    counts = purge_devices(folder, devices, apply=apply)
    if not counts:
        print(f"No line under {folder} names device {label}.")
        return 0
    verb = "Removed" if apply else "Dry run: would remove"
    print(f"{verb} {sum(counts.values())} lines naming device {label} (as ID or ID2):")
    for name, n in counts.items():
        print(f"  {name}: {n}")
    if not apply:
        print("Nothing changed. Re-run with --apply to clean the files.")
        return 0
    print(f"Kept the delivery manifest as SHA256SUMS.as-delivered; recomputed SHA256SUMS; "
          f"recorded the purge in {folder / 'IMPORT.md'} (fill in the ruling).")  # fmt: skip
    missing = sorted(set(devices) - set(study.purged_devices()))
    if missing:
        print(
            f"Add {', '.join(map(str, missing))} to beacons.purged_devices in "
            f"$SOCIAL_ENERGY_DATA/{study.study_id}/local.yaml so a re-import is refused."
        )
    return 0


INGEST_EDA_OUTPUTS = tuple(
    f"{n}.parquet" for n in ("files", "seconds", "scr", "wear", "person_minutes")
)


def _eda_inputs(raw: Path) -> tuple[list[Path], list[Path]]:
    cards = sorted(p for p in (raw / "sd-cards").glob("*") if p.is_dir())
    exports = sorted((raw / "imported").glob("*/*_Calibrated_SD.csv"))
    return cards, exports


def ingest_eda_command(study: StudyConfig) -> int:
    layout = paths.study(study.study_id)
    raw = layout.raw / "eda"
    cards, exports = _eda_inputs(raw)
    if not cards and not exports:
        print(f"No SD cards or calibrated exports under {raw}")
        return 1
    tables = ingest_eda(cards, exports, study.eda_config())
    out = layout.derived / "eda"
    out.mkdir(parents=True, exist_ok=True)
    # Only this command's own outputs are replaced (eda-heart-rate writes beside them).
    for name in (*INGEST_EDA_OUTPUTS, "qa.json"):
        (out / name).unlink(missing_ok=True)
    for name in ("files", "seconds", "scr", "wear"):
        getattr(tables, name).write_parquet(out / f"{name}.parquet")
    qa = {"ingest": tables.qa}
    if (layout.spine / "meta.yaml").exists():
        minutes, minutes_qa = person_minutes(tables, Spine.load(layout.spine))
        minutes.write_parquet(out / "person_minutes.parquet")
        qa["person_minutes"] = minutes_qa
    (out / "qa.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")
    print(json.dumps(qa, indent=2))
    print(f"Wrote {out}")
    return 0


def eda_heart_rate_command(study: StudyConfig) -> int:
    layout = paths.study(study.study_id)
    raw = layout.raw / "eda"
    cards, exports = _eda_inputs(raw)
    if not cards and not exports:
        print(f"No SD cards or calibrated exports under {raw}")
        return 1
    out = layout.derived / "eda"
    wear_path = out / "wear.parquet"
    wear = pl.read_parquet(wear_path) if wear_path.exists() else None
    if wear is None:
        print(f"No {wear_path} (run ingest-eda first): worn will be null")
    tables = heart_rate(cards, exports, study.eda_config(), wear=wear)
    out.mkdir(parents=True, exist_ok=True)
    tables.beats.write_parquet(out / "hr_beats.parquet")
    tables.windows.write_parquet(out / "hr_windows.parquet")
    tables.minutes.write_parquet(out / "hr_minutes.parquet")
    agree = agreement(tables.windows, study.timezone)
    agree.write_parquet(out / "hr_agreement.parquet")
    usability(tables.windows, study.timezone).write_parquet(out / "hr_usability.parquet")
    overall = agree.filter(pl.col("device") == "all").drop("device", "day").to_dicts()
    qa = {"heart_rate": tables.qa, "agreement_all_devices": overall}
    (out / "hr_qa.json").write_text(json.dumps(qa, indent=2, default=str), encoding="utf-8")
    print(json.dumps(qa, indent=2, default=str))
    print(f"Wrote the hr_* tables to {out}")
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


def score_survey_command(study: StudyConfig) -> int:
    config = study.survey_scoring_config()
    if not config.analysis_plan_frozen:
        print(
            "Refusing to score: survey.analysis_plan_frozen is not set in study.yaml. Scales "
            "are scored only after the analysis plan is signed and frozen."
        )
        return 3
    if config.codebook is None or not config.codebook.is_file():
        print(f"No codebook: set survey.codebook in {study.path} (found {config.codebook}).")
        return 1
    layout = paths.study(study.study_id)
    source = layout.derived / "survey"
    if not (source / "items.parquet").is_file():
        print(f"No {source / 'items.parquet'}: run ingest-survey first.")
        return 1
    items = pl.read_parquet(source / "items.parquet")
    respondents = pl.read_parquet(source / "respondents.parquet")
    corrections = load_corrections(config.corrections) if config.corrections else None
    ignore = tuple(i for i in [study.survey_config().study_id_item] if i)
    tables = score_survey(items, respondents, load_codebook(config.codebook), corrections, ignore)
    out = source / "scoring"
    out.mkdir(parents=True, exist_ok=True)
    tables.scores.write_parquet(out / "scores.parquet")
    tables.reliability.write_parquet(out / "reliability.parquet")
    tables.submissions.write_parquet(out / "submissions.parquet")
    (out / "qa.json").write_text(json.dumps(tables.qa, indent=2, default=str), encoding="utf-8")
    if tables.qa["pending"]:
        print("Provisional: the codebook has unconfirmed entries:")
        for entry in tables.qa["pending"]:
            print(f"  {entry}")
    print(f"Wrote {out}")
    return 0


def check_survey(study: StudyConfig) -> int:
    config = study.survey_scoring_config()
    if config.codebook is None or not config.codebook.is_file():
        print(f"No codebook: set survey.codebook in {study.path} (found {config.codebook}).")
        return 1
    layout = paths.study(study.study_id)
    source = layout.derived / "survey"
    if not (source / "items.parquet").is_file():
        print(f"No {source / 'items.parquet'}: run ingest-survey first.")
        return 1
    items = pl.read_parquet(source / "items.parquet")
    respondents = pl.read_parquet(source / "respondents.parquet")
    corrections = load_corrections(config.corrections) if config.corrections else None
    submissions = resolve_submissions(respondents, items, corrections)
    codebook = load_codebook(config.codebook)
    keys = reverse_key_check(items, codebook, submissions)
    versions = version_equivalence(items, codebook, submissions)
    out = source / "checks"
    out.mkdir(parents=True, exist_ok=True)
    keys.write_parquet(out / "reverse_keys.parquet")
    versions.write_parquet(out / "versions.parquet")
    summary = {
        "kept_submissions": int((~submissions["duplicate_submission"]).sum()),
        "reverse_keys": {
            "items": keys.height,
            "undefined": int(keys["agrees"].null_count()),
            "disagree": keys.filter(pl.col("agrees") == False)  # noqa: E712
            .select("group", "item", "finding")
            .to_dicts(),
        },
        "versions": {
            row["old"]: {"new": row["new"], "equivalent": row["equivalent"]}
            for row in versions.iter_rows(named=True)
        },
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"Wrote {out}")
    return 0


COMMANDS = {
    "init-spine": init_spine,
    "ingest-beacons": ingest_beacons,
    "ingest-eda": ingest_eda_command,
    "eda-heart-rate": eda_heart_rate_command,
    "extract-acoustics": extract_acoustics,
    "fetch-zeitgeist": fetch_zeitgeist,
    "ingest-survey": ingest_survey,
    "score-survey": score_survey_command,
    "check-survey": check_survey,
}


def explore(study: StudyConfig, port: int = 8765, open_browser: bool = True) -> int:
    from .explorer import make_server

    bundle = paths.study(study.study_id).derived / "explorer" / "bundle"
    if not (bundle / "meta.json").is_file():
        print(
            f"No explorer bundle at {bundle}. Make one first with\n"
            "    uv run --extra analysis python "
            f"studies/{study.study_id}/analyses/explorer_export.py"
        )
        return 2
    server = make_server(bundle, port=port)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(
        f"Explorer on {url} (Ctrl+C to stop). Pseudonymised data: do not share the screen widely."
    )
    if open_browser:
        import webbrowser

        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def site_build(study: StudyConfig, out: Path | None, data: Path | None = None) -> int:
    from .site import SiteDataError
    from .site.build import build_site

    if out is None:
        print("site-build needs --out DIR")
        return 2
    try:
        site = build_site(
            out, data, config=study.explorer_config(), timezone=study.timezone, seed=0
        )
    except SiteDataError as err:
        print(f"Refused: {err}")
        return 1
    print(f"Site built in {site}" + (" from a synthetic camp" if data is None else ""))
    return 0


COMMANDS["explore"] = explore
COMMANDS["site-build"] = site_build
COMMANDS["purge-device"] = purge_device


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="social-energy", description=__doc__)
    parser.add_argument("command", choices=sorted(COMMANDS))
    parser.add_argument("study_yaml", type=Path, help="path to studies/<id>/study.yaml")
    parser.add_argument(
        "--delete-wavs", action="store_true", help="extract-acoustics: delete verified WAVs"
    )
    parser.add_argument("--port", type=int, default=8765, help="explore: port on 127.0.0.1")
    parser.add_argument("--no-browser", action="store_true", help="explore: do not open a browser")
    parser.add_argument("--out", type=Path, help="site-build: output directory (outside the repo)")
    parser.add_argument("--data", type=Path, help="site-build: public data directory to publish")
    parser.add_argument(
        "--device", type=int, action="append", default=[], help="purge-device: device ID"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run", action="store_true", help="purge-device: only count lines (the default)"
    )
    mode.add_argument("--apply", action="store_true", help="purge-device: remove the lines")
    args = parser.parse_args(argv)
    try:
        study = StudyConfig.load(args.study_yaml)
        if args.command == "extract-acoustics":
            return extract_acoustics(study, delete_wavs=args.delete_wavs)
        if args.command == "purge-device":
            return purge_device(study, args.device, apply=args.apply)
        if args.command == "explore":
            return explore(study, port=args.port, open_browser=not args.no_browser)
        if args.command == "site-build":
            return site_build(study, args.out, args.data)
        return COMMANDS[args.command](study)
    except paths.DataRootError as err:
        print(err)
        return 2


if __name__ == "__main__":
    sys.exit(main())
