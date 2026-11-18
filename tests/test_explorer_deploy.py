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


def test_archive_carries_a_gzip_copy_of_each_bundle_file(tmp_path):
    import gzip
    import io
    import tarfile

    bundle = _bundle(tmp_path)
    with tarfile.open(fileobj=io.BytesIO(deploy.archive(bundle)), mode="r:gz") as tar:
        names = set(tar.getnames())
        assert "bundle/pairs.bin.gz" in names and "bundle/meta.json.gz" not in names
        packed = tar.extractfile("bundle/pairs.bin.gz").read()
        assert gzip.decompress(packed) == (bundle / "pairs.bin").read_bytes()
        assert tar.extractfile("bundle/compressed.json").read() == b'{"gzip": true}'


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
    (cmd, data), (svc_cmd, svc) = calls
    assert cmd[:2] == ["ssh", "box"]
    assert "bundle/meta.json" in _names(data)
    assert "/srv/x/service/auth_service.py" in svc_cmd[2] and b"def make_server" in svc


@pytest.mark.parametrize("name", ["", "a b", "a:b", "a;b", "x" * 65])
def test_bad_user_names_are_refused(name):
    with pytest.raises(deploy.DeployError, match="name"):
        deploy.invite(deploy.Target("box", "/srv/x"), name, run=lambda c, d: b"")


def test_invite_runs_the_service_on_the_server_and_returns_the_link():
    calls = []

    def run(cmd, data):
        calls.append(cmd)
        return b"https://site.test/auth/invite/abc\n"

    target = deploy.Target("box", "/srv/x", "https://site.test")
    assert deploy.invite(target, "Anna", admin=True, run=run) == "https://site.test/auth/invite/abc"
    (cmd,) = calls
    assert cmd[:2] == ["ssh", "box"]
    assert cmd[2] == ("python3 /srv/x/service/auth_service.py invite anna --base "
                      "https://site.test --admin --db /srv/x/auth.db")  # fmt: skip


def test_bad_site_url_is_refused():
    with pytest.raises(deploy.DeployError, match="url"):
        deploy.target(
            {"explorer": {"deploy": {"ssh_host": "b", "path": "/srv/x", "url": "http://x"}}}
        )
