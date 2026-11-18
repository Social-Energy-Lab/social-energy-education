"""Deploying the team explorer to a hosted server: what is sent, where, and who may log in.

The server and its path are a private deployment's identifiers, so they come from local.yaml.
The archive holds the app and the bundle and nothing else; the remote side swaps it in whole.
"""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest

from social_energy.explorer import deploy


def _bundle(tmp_path: Path) -> Path:
    bundle = tmp_path / "data" / "bundle"
    bundle.mkdir(parents=True)
    (bundle / "meta.json").write_text("{}", encoding="utf-8")
    (bundle / "pairs.bin").write_bytes(b"\x00\x01")
    return bundle


def _names(archive: bytes) -> set[str]:
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        return set(tar.getnames())


def test_target_comes_from_local_config():
    target = deploy.target({"explorer": {"deploy": {"ssh_host": "box", "path": "/srv/x"}}})
    assert target == deploy.Target("box", "/srv/x")


@pytest.mark.parametrize(
    "local",
    [{}, {"explorer": {}}, {"explorer": {"deploy": {"ssh_host": "box"}}}],
)
def test_missing_target_is_refused(local):
    with pytest.raises(deploy.DeployError, match=r"local\.yaml"):
        deploy.target(local)


@pytest.mark.parametrize("path", ["relative/x", "/", "/srv/x y", "/srv/x;rm"])
def test_unsafe_remote_path_is_refused(path):
    with pytest.raises(deploy.DeployError, match="path"):
        deploy.target({"explorer": {"deploy": {"ssh_host": "box", "path": path}}})


def test_archive_holds_the_app_and_the_bundle(tmp_path):
    names = _names(deploy.archive(_bundle(tmp_path)))
    assert {"index.html", "app.js", "bundle/meta.json", "bundle/pairs.bin"} <= names
    assert not any(n.endswith((".pyc", ".md")) or "__pycache__" in n for n in names)


def test_archive_refuses_a_folder_without_a_bundle(tmp_path):
    empty = tmp_path / "data" / "bundle"
    empty.mkdir(parents=True)
    with pytest.raises(deploy.DeployError, match=r"meta\.json"):
        deploy.archive(empty)


def test_remote_script_swaps_the_new_site_in_whole():
    script = deploy.remote_script("/srv/x")
    assert script.index("tar -xz") < script.index("mv /srv/x/.next /srv/x/current")
    assert "set -e" in script


def test_push_sends_the_archive_to_the_host(tmp_path):
    calls = []

    def run(cmd, data):
        calls.append((cmd, data))

    deploy.push(deploy.Target("box", "/srv/x"), _bundle(tmp_path), run=run)
    ((cmd, data),) = calls
    assert cmd[:2] == ["ssh", "box"]
    assert "bundle/meta.json" in _names(data)


@pytest.mark.parametrize("name", ["", "a b", "a:b", "a\nb", "x" * 65])
def test_bad_user_names_are_refused(name):
    with pytest.raises(deploy.DeployError, match="name"):
        deploy.password_line(name, "$6$hash")


def test_password_line_replaces_an_existing_user():
    old = "anna:$6$old\nben:$6$b\n"
    new = deploy.with_user(old, deploy.password_line("anna", "$6$new"))
    assert new == "ben:$6$b\nanna:$6$new\n"


def test_removing_a_user_keeps_the_others():
    assert deploy.without_user("anna:$6$a\nben:$6$b\n", "anna") == "ben:$6$b\n"
