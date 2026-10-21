"""Refuse anything non-public before deploy: the last check between the data dir and the site."""

from __future__ import annotations

import json
from pathlib import Path

from .aggregates import AGGREGATE_SECTIONS, NUMBER_KEYS, NUMBERS, SCALES, is_number
from .public import PUBLIC_COLUMNS, PUBLIC_META_KEYS


class SiteDataError(ValueError):
    """The data directory holds something the public site must not serve."""


def _check_meta(meta: dict) -> None:
    if meta.get("mode") != "public":
        raise SiteDataError(f"meta mode must be 'public', got {meta.get('mode')!r}")
    extra = sorted(set(meta) - PUBLIC_META_KEYS)
    if extra:
        raise SiteDataError(f"meta has keys outside the public set: {', '.join(extra)}")
    for i, node in enumerate(meta.get("nodes", [])):
        if not isinstance(node, dict) or set(node) != {"course"}:
            raise SiteDataError(f"meta nodes[{i}] may carry only 'course'")
    files = meta.get("files", {})
    for name in sorted(set(files) - set(PUBLIC_COLUMNS)):
        raise SiteDataError(f"meta files has a table outside the public set: {name}")
    for name, cols in PUBLIC_COLUMNS.items():
        if name not in files:
            raise SiteDataError(f"meta files lacks table {name}")
        got = [tuple(c) for c in files[name].get("columns", [])]
        if got != [tuple(c) for c in cols]:
            raise SiteDataError(f"table {name} columns {got} differ from the public columns")


def _check_aggregates(agg: object, min_group: int) -> None:
    if not isinstance(agg, dict):
        raise SiteDataError("aggregates.json must be an object")
    for section, rows in agg.items():
        if section == NUMBERS:
            if not isinstance(rows, dict):
                raise SiteDataError("aggregates numbers must be an object")
            for key, value in rows.items():
                if key not in NUMBER_KEYS:
                    raise SiteDataError(f"aggregates numbers has unknown key {key}")
                if not is_number(value):
                    raise SiteDataError(f"aggregates numbers {key} is not a number")
            continue
        if section not in AGGREGATE_SECTIONS:
            raise SiteDataError(f"aggregates has unknown section {section}")
        allowed = AGGREGATE_SECTIONS[section]
        if not isinstance(rows, list):
            raise SiteDataError(f"aggregates section {section} must be a list")
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                raise SiteDataError(f"aggregates {section}[{i}] must be an object")
            extra = sorted(set(row) - set(allowed))
            if extra:
                raise SiteDataError(f"aggregates {section}[{i}] has unknown key {extra[0]}")
            people = row.get("people")
            if not is_number(people) or people < min_group:
                raise SiteDataError(
                    f"aggregates {section}[{i}] people {people!r} is below {min_group}"
                )
            if section == "confirmatory" and row.get("scale") not in SCALES:
                raise SiteDataError(f"aggregates confirmatory[{i}] scale must be one of {SCALES}")


def validate_site_data(data_dir: Path, min_group: int = 5) -> dict:
    """Check ``data_dir`` is a public bundle plus aggregates; return its meta or raise."""
    data_dir = Path(data_dir)
    try:
        meta = json.loads((data_dir / "meta.json").read_text(encoding="utf-8"))
        agg = json.loads((data_dir / "aggregates.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        raise SiteDataError(f"cannot read site data: {err}") from err
    _check_meta(meta)
    stray = sorted(p.name for p in data_dir.glob("*.bin") if p.stem not in PUBLIC_COLUMNS)
    if stray:
        raise SiteDataError(f"unexpected file {stray[0]}")
    _check_aggregates(agg, min_group)
    return meta
