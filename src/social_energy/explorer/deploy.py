"""Deploy the team explorer to a hosted, access-restricted server, and manage who may log in.

The server and its folder name a private deployment, so they are read from the study's
``local.yaml`` (``explorer.deploy.ssh_host`` and ``path``), never from the repo. A deploy builds
one archive of the app (``static/``) and the bundle in memory, streams it over SSH and swaps it in
whole: the server unpacks into ``<path>/.next`` and renames it to ``<path>/current``, which the
web server serves. Nothing is written locally and the previous site is kept as ``<path>/.prev``.

Logins are the web server's own (HTTP basic auth over HTTPS, behind the institute's VPN): one
line per researcher in ``<path>/htpasswd``, with a SHA-512 crypt hash made on this machine. The
password never leaves it in the clear. See ``docs/decisions/explorer-hosted.md``.
"""

from __future__ import annotations

import io
import re
import subprocess
import tarfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .server import STATIC

_SAFE_PATH = re.compile(r"^/[A-Za-z0-9._/-]+$")
_SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_SKIP = ("__pycache__", ".pyc", ".md")

Runner = Callable[[list[str], bytes | None], bytes]


class DeployError(RuntimeError):
    """The deploy cannot go ahead: missing config, no bundle, or an unsafe value."""


@dataclass(frozen=True)
class Target:
    ssh_host: str
    path: str


def target(local: dict) -> Target:
    """Where to deploy, from the study's ``local.yaml``."""
    section = ((local.get("explorer") or {}).get("deploy")) or {}
    host, path = section.get("ssh_host"), section.get("path")
    if not host or not path:
        raise DeployError(
            "No deploy target: set explorer.deploy.ssh_host and explorer.deploy.path in "
            "$SOCIAL_ENERGY_DATA/<study-id>/local.yaml"
        )
    path = str(path).rstrip("/")
    if not _SAFE_PATH.match(path) or path.count("/") < 2 or ".." in path.split("/"):
        raise DeployError(f"Unsafe remote path {path!r}: use an absolute folder like /srv/explorer")
    return Target(str(host), path)


def _add(tar: tarfile.TarFile, file: Path, name: str) -> None:
    info = tar.gettarinfo(str(file), arcname=name)
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    info.mode = 0o644
    with file.open("rb") as fh:
        tar.addfile(info, fh)


def archive(bundle_dir: Path) -> bytes:
    """A gzipped tar of the app with the bundle under ``bundle/``, built in memory."""
    if not (bundle_dir / "meta.json").is_file():
        raise DeployError(f"No explorer bundle at {bundle_dir} (meta.json is missing)")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for file in sorted(STATIC.rglob("*")):
            rel = file.relative_to(STATIC).as_posix()
            if file.is_file() and not any(s in rel for s in _SKIP):
                _add(tar, file, rel)
        for file in sorted(bundle_dir.iterdir()):
            if file.is_file():
                _add(tar, file, f"bundle/{file.name}")
    return buf.getvalue()


def remote_script(path: str) -> str:
    """Shell run on the server: unpack into .next, then swap it for current."""
    return (
        "set -e; umask 022; "
        f"rm -rf {path}/.next; mkdir -p {path}/.next; "
        f"tar -xz --no-same-owner -C {path}/.next; "
        f"rm -rf {path}/.prev; "
        f"if [ -d {path}/current ]; then mv {path}/current {path}/.prev; fi; "
        f"mv {path}/.next {path}/current"
    )


def _ssh(cmd: list[str], data: bytes | None) -> bytes:
    result = subprocess.run(cmd, input=data, capture_output=True, check=False)
    if result.returncode != 0:
        raise DeployError(result.stderr.decode("utf-8", "replace").strip() or "ssh failed")
    return result.stdout


def push(target: Target, bundle_dir: Path, run: Runner = _ssh) -> None:
    """Send the app and the bundle to ``target`` and swap them in."""
    run(["ssh", target.ssh_host, remote_script(target.path)], archive(bundle_dir))


# --- Logins -----------------------------------------------------------------------------------


def password_line(name: str, hashed: str) -> str:
    if not _SAFE_NAME.match(name):
        raise DeployError(f"Bad user name {name!r}: letters, digits, '.', '_' or '-' only")
    return f"{name}:{hashed}\n"


def _lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip()]


def without_user(text: str, name: str) -> str:
    kept = [line for line in _lines(text) if line.split(":", 1)[0] != name]
    return "".join(f"{line}\n" for line in kept)


def with_user(text: str, line: str) -> str:
    return without_user(text, line.split(":", 1)[0]) + line


def hash_password(password: str) -> str:
    """SHA-512 crypt, which nginx checks through the system's crypt()."""
    result = subprocess.run(
        ["openssl", "passwd", "-6", "-stdin"],
        input=password.encode("utf-8"),
        capture_output=True,
        check=True,
    )
    return result.stdout.decode("ascii").strip()


def read_users(target: Target, run: Runner = _ssh) -> str:
    return run(["ssh", target.ssh_host, f"cat {target.path}/htpasswd"], None).decode("utf-8")


def write_users(target: Target, text: str, run: Runner = _ssh) -> None:
    # Overwrite in place so the file keeps the owner and group the setup gave it.
    run(["ssh", target.ssh_host, f"cat > {target.path}/htpasswd"], text.encode("utf-8"))


def user_names(text: str) -> list[str]:
    return [line.split(":", 1)[0] for line in _lines(text)]
