"""The explorer server: localhost only, app and bundle only, nothing else on disk."""

import threading
import urllib.error
import urllib.request

import pytest

from social_energy import cli
from social_energy.explorer import make_server
from social_energy.paths import REPO_ROOT, DataRootError


@pytest.fixture
def server(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "meta.json").write_text('{"version": 1}', encoding="utf-8")
    (tmp_path / "secret.txt").write_text("outside", encoding="utf-8")
    srv = make_server(bundle, port=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()


def _get(srv, path: str) -> tuple[int, bytes]:
    host, port = srv.server_address[:2]
    try:
        with urllib.request.urlopen(f"http://{host}:{port}{path}") as r:
            return r.status, r.read()
    except urllib.error.HTTPError as err:
        return err.code, b""


def test_binds_to_loopback_only(server):
    assert server.server_address[0] == "127.0.0.1"


def test_serves_the_app(server):
    status, body = _get(server, "/")
    assert status == 200 and b"<html" in body.lower()


def test_serves_the_bundle(server):
    assert _get(server, "/bundle/meta.json") == (200, b'{"version": 1}')


@pytest.mark.parametrize(
    "path", ["/bundle/../secret.txt", "/bundle/%2e%2e/secret.txt", "/../../etc/passwd"]
)
def test_paths_outside_app_and_bundle_are_404(server, path):
    status, body = _get(server, path)
    assert status == 404 and b"outside" not in body


def test_bundle_inside_repo_is_refused():
    with pytest.raises(DataRootError):
        make_server(REPO_ROOT / "docs", port=0)


def test_explore_without_bundle_says_how_to_make_one(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SOCIAL_ENERGY_DATA", str(tmp_path))
    rc = cli.main(["explore", str(REPO_ROOT / "studies" / "dsa-2026" / "study.yaml")])
    assert rc == 2
    assert "explorer_export.py" in capsys.readouterr().out
