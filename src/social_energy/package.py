"""One encrypted archive of a study's data, laid out as we keep it.

The study says what goes in through ``studies/<id>/package.yaml``: a title, then one entry per
folder or file under the data root, each with a sentence on what it holds and optional exclude
globs. :func:`build` copies those files into an AES-256 zip with the same paths, plus a
``README.md`` (one row per entry: files, size, what it is) and a ``SHA256SUMS`` of every file.
The archive is written outside the repository; this module never reads data it was not told to.
"""

from __future__ import annotations

import fnmatch
import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import yaml

from . import paths


class PackageError(RuntimeError):
    pass


@dataclass(frozen=True)
class Entry:
    path: str
    about: str
    exclude: tuple[str, ...] = ()


@dataclass(frozen=True)
class PackageSpec:
    archive: str
    title: str
    intro: str
    entries: tuple[Entry, ...]
    exclude: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def load(cls, path: Path) -> PackageSpec:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        entries = tuple(
            Entry(str(e["path"]).strip("/"), str(e["about"]).strip(), tuple(e.get("exclude", ())))
            for e in raw.get("entries") or []
        )
        if not entries:
            raise PackageError(f"{path}: no entries")
        return cls(
            archive=str(raw["archive"]),
            title=str(raw["title"]),
            intro=str(raw.get("intro", "")).strip(),
            entries=entries,
            exclude=tuple(raw.get("exclude", ())),
        )


@dataclass(frozen=True)
class PackedFile:
    arcname: str
    source: Path
    size: int
    sha256: str


def _excluded(rel: str, patterns: tuple[str, ...]) -> bool:
    # fnmatch's * also matches "/", so "*-pre-*" drops a whole folder named like that.
    name = rel.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(name, p) for p in patterns)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def collect(root: Path, spec: PackageSpec) -> dict[str, list[PackedFile]]:
    """Every file each entry contributes, by entry path. A missing entry is an error."""
    found: dict[str, list[PackedFile]] = {}
    for entry in spec.entries:
        base = root / entry.path
        if base.is_file():
            candidates = [base]
        elif base.is_dir():
            candidates = sorted(p for p in base.rglob("*") if p.is_file())
        else:
            raise PackageError(f"{entry.path} does not exist under {root}")
        patterns = spec.exclude + entry.exclude
        files = []
        for source in candidates:
            arcname = source.relative_to(root).as_posix()
            inner = source.relative_to(base).as_posix() if base.is_dir() else source.name
            if _excluded(inner, patterns):
                continue
            files.append(PackedFile(arcname, source, source.stat().st_size, _sha256(source)))
        found[entry.path] = files
    names = [f.arcname for files in found.values() for f in files]
    if len(names) != len(set(names)):
        raise PackageError("two entries include the same file; make the entries disjoint")
    return found


def _human(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    raise AssertionError


def readme(spec: PackageSpec, found: dict[str, list[PackedFile]], built_at: str) -> str:
    lines = [f"# {spec.title}", "", f"Built {built_at}.", ""]
    if spec.intro:
        lines += [spec.intro, ""]
    lines += ["| Path | Files | Size | What it is |", "|---|---|---|---|"]
    for entry in spec.entries:
        files = found[entry.path]
        about = " ".join(entry.about.split()).replace("|", "\\|")
        size = _human(sum(f.size for f in files))
        lines.append(f"| `{entry.path}` | {len(files)} | {size} | {about} |")
    check = "Check the files with `sha256sum -c SHA256SUMS` from the archive's top folder."
    lines += ["", check, ""]
    return "\n".join(lines)


def build(root: Path, spec: PackageSpec, out_dir: Path, password: str) -> Path:
    """Write ``<out_dir>/<archive>.zip`` (AES-256) and return its path."""
    import pyzipper

    if len(password) < 12:
        raise PackageError("the password must be at least 12 characters")
    out_dir = paths.refuse_inside_repo(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    found = collect(Path(root), spec)
    built_at = datetime.now(UTC).isoformat(timespec="seconds")
    target = out_dir / f"{spec.archive}.zip"
    partial = target.with_suffix(".zip.partial")
    sums = "".join(f"{f.sha256}  {f.arcname}\n" for files in found.values() for f in files)
    with pyzipper.AESZipFile(
        partial, "w", compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES
    ) as archive:
        archive.setpassword(password.encode("utf-8"))
        archive.setencryption(pyzipper.WZ_AES, nbits=256)
        archive.writestr("README.md", readme(spec, found, built_at))
        archive.writestr("SHA256SUMS", sums)
        for files in found.values():
            for f in files:
                archive.write(f.source, f.arcname)
    with pyzipper.AESZipFile(partial) as archive:
        archive.setpassword(password.encode("utf-8"))
        bad = archive.testzip()
    if bad is not None:
        raise PackageError(f"{partial}: {bad} failed its check after writing")
    partial.replace(target)
    return target


def new_password() -> str:
    return secrets.token_urlsafe(18)
