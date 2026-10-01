"""Serve the explorer app and one bundle on 127.0.0.1, and nothing else.

``/bundle/<file>`` maps into the bundle directory; every other path maps into the app's
``static/`` directory. A path that resolves outside its root is a 404, so the server cannot be
used to read anything else on the machine. Requests naming any other host are refused, so a web
page that rebinds its own name to 127.0.0.1 cannot read the bundle. The bundle must live outside
the repository.
"""

from __future__ import annotations

import functools
import posixpath
import urllib.parse
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .. import paths

STATIC = Path(__file__).parent / "static"
HOST = "127.0.0.1"


class _Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, bundle_dir: Path, **kwargs):
        self.bundle_dir = bundle_dir
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def _resolve(self) -> Path | None:
        path = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
        parts = [p for p in posixpath.normpath(path).split("/") if p not in ("", ".")]
        if ".." in path.split("/"):
            return None
        root, rest = (self.bundle_dir, parts[1:]) if parts[:1] == ["bundle"] else (STATIC, parts)
        target = root.joinpath(*rest).resolve() if rest else root.resolve()
        if target != root and root not in target.parents:
            return None
        return target / "index.html" if target.is_dir() else target

    def translate_path(self, path: str) -> str:
        target = self._resolve()
        return str(target) if target is not None else ""

    def send_head(self):
        port = self.server.server_address[1]
        if self.headers.get("Host", "") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            self.send_error(HTTPStatus.BAD_REQUEST, "Unknown host")
            return None
        target = self._resolve()
        if target is None or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return None
        return super().send_head()

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, format: str, *args) -> None:
        pass


def make_server(bundle_dir: Path, port: int = 8765) -> ThreadingHTTPServer:
    """A server for ``bundle_dir`` on 127.0.0.1:``port`` (0 picks a free port)."""
    bundle_dir = paths.refuse_inside_repo(bundle_dir)
    handler = functools.partial(_Handler, bundle_dir=bundle_dir)
    return ThreadingHTTPServer((HOST, port), handler)
