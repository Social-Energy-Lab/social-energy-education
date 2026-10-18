"""Purged devices: find, refuse and remove raw log lines that name a device purged by ruling.

When a device's records must go (for example, collected without consent), the lines are removed
from the raw logs themselves, and the device is listed under ``beacons.purged_devices`` in the
study's private ``local.yaml``. Every ingest then refuses logs that still name it, so a later
re-import of the original delivery cannot restore the records unnoticed.

A line names a device when it carries ``,ID: <n>,`` or ``,ID2: <n>,``. The match is
comma-delimited, so purging 14 leaves 140-147 alone. Before the logger's ID fix, beacon IDs 48-57
were printed as "0"-"9" (``BeaconConfig.ambiguous_id_cutoff``): a purged device in 0-9 or 48-57
needs those early lines checked by hand.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from datetime import date
from pathlib import Path

NAMED_ID = re.compile(rb",ID2?: (\d+)(?=,)")
MANIFEST = "SHA256SUMS"
AS_DELIVERED = "SHA256SUMS.as-delivered"


class PurgedDeviceError(ValueError):
    """Raw logs still name a device listed under ``beacons.purged_devices``."""


def _named(line: bytes) -> set[int]:
    return {int(n) for n in NAMED_ID.findall(line)}


def find_purged_lines(paths: Iterable[Path], devices: Iterable[int]) -> dict[tuple[Path, int], int]:
    """Lines naming each purged device, per file: ``{(path, device): lines}``. Empty if none."""
    devices = {int(d) for d in devices}
    found: dict[tuple[Path, int], int] = {}
    if not devices:
        return found
    for path in paths:
        path = Path(path)
        for line in path.read_bytes().splitlines():
            for device in _named(line) & devices:
                found[(path, device)] = found.get((path, device), 0) + 1
    return found


def check_purged(paths: Iterable[Path], devices: Iterable[int]) -> None:
    """Raise ``PurgedDeviceError`` if any line of ``paths`` names one of ``devices``."""
    found = find_purged_lines(paths, devices)
    if not found:
        return
    parts = []
    for device in sorted({d for _, d in found}):
        files = {p: n for (p, d), n in found.items() if d == device}
        listing = ", ".join(f"{p.name}: {n}" for p, n in sorted(files.items()))
        parts.append(
            f"purged device {device} is named (as ID or ID2) in {sum(files.values())} lines "
            f"in {len(files)} files ({listing})"
        )
    raise PurgedDeviceError(
        "Refusing to ingest: "
        + "; ".join(parts)
        + ". Devices listed under beacons.purged_devices in local.yaml are never dropped "
        "silently at ingest: the raw files themselves must be cleaned. Remove the lines with "
        "`social-energy purge-device <study.yaml> --device <n> --apply` (or by hand, as in "
        "docs/context/data-layout.md), and record the purge in raw/beacons/IMPORT.md. A re-import "
        "of the original delivery restores the lines."
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rewrite_manifest(folder: Path) -> None:
    """Recompute every entry of ``folder/SHA256SUMS`` (same names, same order)."""
    manifest = folder / MANIFEST
    if not manifest.is_file():
        logs = sorted(p for p in folder.rglob("*.log") if p.is_file())
        lines = [f"{_sha256(p)}  {p.relative_to(folder).as_posix()}" for p in logs]
    else:
        lines = []
        for entry in manifest.read_text(encoding="utf-8").splitlines():
            if "  " not in entry and " *" not in entry:
                lines.append(entry)
                continue
            sep = "  " if "  " in entry else " *"
            name = entry.split(sep, 1)[1]
            target = folder / name
            lines.append(f"{_sha256(target)}{sep}{name}" if target.is_file() else entry)
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")


def purge_devices(
    folder: Path, devices: Iterable[int], apply: bool = False, today: date | None = None
) -> dict[str, int]:
    """Count (and with ``apply``, remove) the lines naming ``devices`` in every ``.log`` under
    ``folder``. Returns lines per file, keyed by the path relative to ``folder``.

    With ``apply``: the delivery's manifest is kept once as ``SHA256SUMS.as-delivered`` (never
    overwritten by a later purge), ``SHA256SUMS`` is recomputed for the cleaned files, and the
    purge is appended to ``IMPORT.md``. Other bytes of each file are left exactly as they were.
    """
    folder = Path(folder)
    devices = {int(d) for d in devices}
    logs = sorted(p for p in folder.rglob("*.log") if p.is_file())
    counts: dict[str, int] = {}
    for path, _ in find_purged_lines(logs, devices):
        name = path.relative_to(folder).as_posix()
        if name in counts:
            continue
        counts[name] = sum(1 for line in path.read_bytes().splitlines() if _named(line) & devices)
    counts = dict(sorted(counts.items()))
    if not apply or not counts:
        return counts

    manifest, delivered = folder / MANIFEST, folder / AS_DELIVERED
    if manifest.is_file() and not delivered.exists():
        delivered.write_bytes(manifest.read_bytes())
    for name in counts:
        path = folder / name
        kept = [
            line
            for line in path.read_bytes().splitlines(keepends=True)
            if not _named(line) & devices
        ]
        path.write_bytes(b"".join(kept))
    _rewrite_manifest(folder)

    total = sum(counts.values())
    label = ", ".join(str(d) for d in sorted(devices))
    record = [
        "",
        f"## Purge, {(today or date.today()).isoformat()}: device {label}",
        "",
        f"Removed {total} lines naming device {label} as ID or ID2 "
        "(comma-delimited match, so longer IDs sharing the digits were kept):",
        "",
        *[f"- `{name}`: {n}" for name, n in counts.items()],
        "",
        f"The delivery's manifest is kept as `{AS_DELIVERED}`; `{MANIFEST}` matches the cleaned "
        "files. The device is listed under `beacons.purged_devices` in `local.yaml`, so the ingest "
        "refuses a re-import that restores the lines.",
        "",
        "Ruling: [unknown: who ruled, when, and why]",
        "",
    ]
    with (folder / "IMPORT.md").open("a", encoding="utf-8") as fh:
        fh.write("\n".join(record))
    return counts
