"""Refuse anything non-public before deploy: the last check between the data dir and the site.

Keys alone are not enough: every value must be a number, or a string from a fixed set, so no
free text (a name, a course, a note) can ride along in a field the schema allows.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np

from ..explorer.bundle import DTYPES
from .aggregates import (
    AGGREGATE_SECTIONS,
    NUMBER_KEYS,
    NUMBERS,
    SAFE_NAME,
    bad_field,
    is_number,
)
from .public import (
    PUBLIC_COLUMNS,
    PUBLIC_DAY_KEYS,
    PUBLIC_META_KEYS,
    PUBLIC_SPAN_KEYS,
    SHADE_LABELS,
    SPECIAL_DAY_LABELS,
)

#: ``meta.days[].label`` as the writer formats it ("Thu 13 Aug").
DAY_LABEL = re.compile(r"[A-Z][a-z]{2} \d{2} [A-Z][a-z]{2}")
UTC_STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
TIMEZONE = re.compile(r"[A-Za-z_]+(/[A-Za-z_+\-0-9]+){0,2}")


class SiteDataError(ValueError):
    """The data directory holds something the public site must not serve."""


def _is_int(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _check_spans(meta: dict, field: str, labels: tuple[str, ...]) -> None:
    spans = meta.get(field, [])
    if not isinstance(spans, list):
        raise SiteDataError(f"meta {field} must be a list")
    for i, span in enumerate(spans):
        if not isinstance(span, dict) or set(span) != PUBLIC_SPAN_KEYS:
            raise SiteDataError(f"meta {field}[{i}] may carry only {sorted(PUBLIC_SPAN_KEYS)}")
        if not (_is_int(span["start_bin"]) and _is_int(span["end_bin"])):
            raise SiteDataError(f"meta {field}[{i}] bins must be integers")
        if span["label"] not in labels:
            raise SiteDataError(f"meta {field}[{i}] label must be one of {labels}")


def _check_meta(meta: dict) -> None:
    if not isinstance(meta, dict):
        raise SiteDataError("meta.json must be an object")
    if meta.get("mode") != "public":
        raise SiteDataError(f"meta mode must be 'public', got {meta.get('mode')!r}")
    extra = sorted(set(meta) - PUBLIC_META_KEYS)
    if extra:
        raise SiteDataError(f"meta has keys outside the public set: {', '.join(extra)}")
    for key in ("version", "bin_seconds", "n_bins", "n_courses"):
        if not _is_int(meta.get(key)) or meta[key] < 0:
            raise SiteDataError(f"meta {key} must be a non-negative integer")
    if not isinstance(meta.get("synthetic"), bool):
        raise SiteDataError("meta synthetic must be true or false")
    if not isinstance(meta.get("t0"), str) or not UTC_STAMP.fullmatch(meta["t0"]):
        raise SiteDataError("meta t0 must be a UTC timestamp")
    if not isinstance(meta.get("timezone"), str) or not TIMEZONE.fullmatch(meta["timezone"]):
        raise SiteDataError("meta timezone must be a zone name")
    for i, node in enumerate(meta.get("nodes", [])):
        if not isinstance(node, dict) or set(node) != {"course"}:
            raise SiteDataError(f"meta nodes[{i}] may carry only 'course'")
        if not _is_int(node["course"]) or not -1 <= node["course"] < meta["n_courses"]:
            raise SiteDataError(f"meta nodes[{i}] course must be an index or -1")
    phases = meta.get("phases", [])
    if not isinstance(phases, list) or not all(
        isinstance(p, str) and SAFE_NAME.fullmatch(p) for p in phases
    ):
        raise SiteDataError("meta phases must be lowercase words")
    days = meta.get("days", [])
    if not isinstance(days, list):
        raise SiteDataError("meta days must be a list")
    for i, day in enumerate(days):
        if not isinstance(day, dict) or set(day) != PUBLIC_DAY_KEYS:
            raise SiteDataError(f"meta days[{i}] may carry only {sorted(PUBLIC_DAY_KEYS)}")
        if not (_is_int(day["index"]) and _is_int(day["start_bin"])):
            raise SiteDataError(f"meta days[{i}] index and start_bin must be integers")
        if not isinstance(day["label"], str) or not DAY_LABEL.fullmatch(day["label"]):
            raise SiteDataError(f"meta days[{i}] label must be a date like 'Thu 13 Aug'")
    _check_spans(meta, "special_days", SPECIAL_DAY_LABELS)
    _check_spans(meta, "shade", SHADE_LABELS)
    files = meta.get("files", {})
    for name in sorted(set(files) - set(PUBLIC_COLUMNS)):
        raise SiteDataError(f"meta files has a table outside the public set: {name}")
    for name, cols in PUBLIC_COLUMNS.items():
        if name not in files:
            raise SiteDataError(f"meta files lacks table {name}")
        if set(files[name]) != {"count", "columns"} or not _is_int(files[name]["count"]):
            raise SiteDataError(f"meta files {name} must hold only an integer count and columns")
        got = [tuple(c) for c in files[name].get("columns", [])]
        if got != [tuple(c) for c in cols]:
            raise SiteDataError(f"table {name} columns {got} differ from the public columns")


def _read_tables(data_dir: Path, meta: dict) -> dict[str, dict[str, np.ndarray]]:
    """Each table's columns; the file's size must be exactly count x row width."""
    tables = {}
    for name, cols in PUBLIC_COLUMNS.items():
        count = meta["files"][name]["count"]
        dtypes = [np.dtype(DTYPES[d]).newbyteorder("<") for _, d in cols]
        raw = (data_dir / f"{name}.bin").read_bytes()
        width = sum(d.itemsize for d in dtypes)
        if len(raw) != count * width:
            raise SiteDataError(
                f"{name}.bin holds {len(raw)} bytes, not {count} rows of {width} bytes"
            )
        out, at = {}, 0
        for (col, _), dt in zip(cols, dtypes, strict=True):
            out[col] = np.frombuffer(raw, dtype=dt, count=count, offset=at)
            at += count * dt.itemsize
        tables[name] = out
    return tables


def _check_tables(data_dir: Path, meta: dict) -> None:
    tables = _read_tables(data_dir, meta)
    n_bins, n_nodes = meta["n_bins"], len(meta.get("nodes", []))
    if meta["files"]["bins"]["count"] != n_bins:
        raise SiteDataError(f"bins.bin has {meta['files']['bins']['count']} rows, not n_bins")
    shown = tables["bins"]["shown"]
    if not np.isin(shown, (0, 1)).all():
        raise SiteDataError("bins.bin shown must be 0 or 1")
    for name in ("pairs", "seen", "presses"):
        k = tables[name]["bin"].astype(np.int64)
        if (k >= n_bins).any():
            raise SiteDataError(f"{name}.bin has a bin index past n_bins")
        if (shown[k] != 1).any():
            raise SiteDataError(f"{name}.bin has a row in a bin that is not shown")
        for col in ("a", "b", "node"):
            if col in tables[name] and (tables[name][col] >= n_nodes).any():
                raise SiteDataError(f"{name}.bin has a node index past the nodes")


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
            bad = bad_field(row, allowed)
            if bad is not None:
                raise SiteDataError(
                    f"aggregates {section}[{i}] {bad} holds a value the site may not show"
                )


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
    try:
        _check_tables(data_dir, meta)
    except OSError as err:
        raise SiteDataError(f"cannot read site data: {err}") from err
    _check_aggregates(agg, min_group)
    return meta
