"""Deploy the team explorer to a hosted, access-restricted server, and manage who may log in.

The server and its folder name a private deployment, so they are read from the study's
``local.yaml`` (``explorer.deploy.ssh_host`` and ``path``), never from the repo. A deploy builds
one archive of the app (``static/``) and the bundle in memory, streams it over SSH and swaps it in
whole: the server unpacks into ``<path>/.next`` and renames it to ``<path>/current``, which the
web server serves. Nothing is written locally and the previous site is kept as ``<path>/.prev``.

Sign-in is the explorer's own service (``auth_service.py``, standard library only), shipped with
every deploy to ``<path>/service/`` and restarting itself when it changes. Researchers are invited
by name and choose their own password on a one-time link; admins manage them in the browser at
``/auth/admin``. ``explorer-user`` here only bootstraps or scripts that, over SSH. The site's
address for the links is ``explorer.deploy.url``. See ``docs/decisions/explorer-hosted.md``.
"""

from __future__ import annotations

import gzip
import io
import re
import subprocess
import tarfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .server import STATIC

SERVICE = Path(__file__).with_name("auth_service.py")

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
    url: str = "https://localhost"


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
    url = str(section.get("url") or "https://localhost").rstrip("/")
    if not re.match(r"^https://[A-Za-z0-9.-]+(:[0-9]+)?$", url):
        raise DeployError(f"Bad url {url!r}: use https://<host name>")
    return Target(str(host), path, url)


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
                if file.name != "meta.json":
                    _add_bytes(tar, gzip.compress(file.read_bytes(), 6, mtime=0),
                               f"bundle/{file.name}.gz")  # fmt: skip
        # The web server sends .bin files uncompressed, about 11 MB on DSA 2026 and 12 s over
        # the VPN; the app reads the .gz copies (a fifth of that) when this marker is there.
        _add_bytes(tar, b'{"gzip": true}', "bundle/compressed.json")
    return buf.getvalue()


def _add_bytes(tar: tarfile.TarFile, data: bytes, name: str) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = 0o644
    tar.addfile(info, io.BytesIO(data))


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
    """Send the app and the bundle to ``target`` and swap them in, then the sign-in service."""
    run(["ssh", target.ssh_host, remote_script(target.path)], archive(bundle_dir))
    svc = f"{target.path}/service"
    run(
        ["ssh", target.ssh_host,
         f"set -e; umask 022; mkdir -p {svc}; cat > {svc}/auth_service.py.new; "
         f"if ! cmp -s {svc}/auth_service.py.new {svc}/auth_service.py; then "
         f"mv {svc}/auth_service.py.new {svc}/auth_service.py; "
         f"else rm {svc}/auth_service.py.new; fi"],
        SERVICE.read_bytes(),
    )  # fmt: skip


# --- Users, through the service's own command line on the server ------------------------------


def _service(target: Target, *args: str) -> list[str]:
    cmd = f"python3 {target.path}/service/auth_service.py " + " ".join(args)
    return ["ssh", target.ssh_host, f"{cmd} --db {target.path}/auth.db"]


def _name(name: str) -> str:
    if not _SAFE_NAME.match(name):
        raise DeployError(f"Bad user name {name!r}: letters, digits, '.', '_' or '-' only")
    return name.lower()


def invite(target: Target, name: str, admin: bool = False, run: Runner = _ssh) -> str:
    """A one-time link on which ``name`` chooses a password (a reset, if they exist)."""
    args = ["invite", _name(name), "--base", target.url] + (["--admin"] if admin else [])
    return run(_service(target, *args), None).decode("utf-8").strip()


def remove(target: Target, name: str, run: Runner = _ssh) -> None:
    run(_service(target, "remove", _name(name)), None)


def users(target: Target, run: Runner = _ssh) -> str:
    return run(_service(target, "users"), None).decode("utf-8")
