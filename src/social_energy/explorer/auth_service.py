"""Sign-in and user admin for the hosted team explorer. Standard library only, one file.

It runs on the server next to the web server, which asks it, before serving any page of the
explorer, whether the request carries a valid session (``GET /check``: 204 or 401; nginx
``auth_request``). Everything else it serves lives under ``/auth/``:

- ``/auth/login``: the sign-in form. A session cookie (HttpOnly, Secure, SameSite=Strict) lasts
  12 hours. Repeated failures for one name or one address are refused for 15 minutes.
- ``/auth/invite/<token>``: a one-time link, valid 7 days, on which an invited researcher chooses
  their own password. A reset is a new invite for the same name, so nobody else ever knows it.
- ``/auth/admin``: admins only. The users, their last sign-in, and invite, reset and remove.
- ``/auth/logout`` and ``/auth/me`` (who is signed in, for the explorer's header).

Passwords are stored as scrypt hashes; session and invite tokens only as SHA-256 hashes, so the
database alone signs nobody in. Forms carry a per-session token against cross-site requests.

Run: ``python3 auth_service.py serve --db auth.db --port 8790`` (behind nginx, on 127.0.0.1), and
``python3 auth_service.py invite NAME [--admin]`` on the server to print a first invite link.
The service restarts itself when this file changes, so a deploy needs no admin rights.

Decision: ``docs/decisions/explorer-hosted.md``.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import html
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SESSION_S = 12 * 3600
INVITE_S = 7 * 24 * 3600
FAIL_WINDOW_S = 15 * 60
MAX_FAILS = 5
MIN_PASSWORD = 12
COOKIE = "see_session"
NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
SCRYPT = {"n": 2**14, "r": 8, "p": 1}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  name TEXT PRIMARY KEY, role TEXT NOT NULL CHECK (role IN ('admin', 'researcher')),
  password TEXT, created REAL NOT NULL, last_login REAL);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY, name TEXT NOT NULL REFERENCES users(name) ON DELETE CASCADE,
  csrf TEXT NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS invites (
  token_hash TEXT PRIMARY KEY, name TEXT NOT NULL REFERENCES users(name) ON DELETE CASCADE,
  expires REAL NOT NULL);
"""


# --- Storage and rules (no HTTP here) ----------------------------------------------------------


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, dklen=32, **SCRYPT)
    return f"scrypt${SCRYPT['n']}${SCRYPT['r']}${SCRYPT['p']}${_b64(salt)}${_b64(digest)}"


def check_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        _, n, r, p, salt, digest = stored.split("$")
        got = hashlib.scrypt(
            password.encode("utf-8"), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
            dklen=32,
        )  # fmt: skip
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, base64.b64decode(digest))


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii", "replace")).hexdigest()


class Store:
    """The users, sessions and invites, in one SQLite file."""

    def __init__(self, path: str, clock=time.time):
        self.clock = clock
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)
        self.lock = threading.Lock()
        self.fails: dict[str, list[float]] = {}

    def _q(self, sql: str, *args):
        with self.lock:
            return self.db.execute(sql, args).fetchall()

    # Users
    def users(self) -> list[dict]:
        rows = self._q("SELECT name, role, password IS NOT NULL, created, last_login FROM users "
                       "ORDER BY role, name")  # fmt: skip
        return [
            dict(zip(("name", "role", "active", "created", "last_login"), r, strict=True))
            for r in rows
        ]

    def user(self, name: str) -> dict | None:
        found = [u for u in self.users() if u["name"] == name]
        return found[0] if found else None

    def invite(self, name: str, role: str = "researcher") -> str:
        """A new one-time link token for ``name``, creating the user if new. Old links die."""
        name = name.strip().lower()
        if not NAME.match(name):
            raise ValueError("A name is lower-case letters, digits, '.', '_' or '-'")
        if role not in ("admin", "researcher"):
            raise ValueError("role must be admin or researcher")
        token = secrets.token_urlsafe(32)
        now = self.clock()
        with self.lock:
            self.db.execute("BEGIN")
            self.db.execute(
                "INSERT INTO users (name, role, created) VALUES (?, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET role = excluded.role",
                (name, role, now),
            )
            self.db.execute("DELETE FROM invites WHERE name = ?", (name,))
            self.db.execute(
                "INSERT INTO invites VALUES (?, ?, ?)", (_token_hash(token), name, now + INVITE_S)
            )
            self.db.execute("COMMIT")
        return token

    def remove(self, name: str) -> None:
        self._q("DELETE FROM users WHERE name = ?", name)

    def admins(self) -> int:
        return self._q("SELECT count(*) FROM users WHERE role = 'admin' AND password IS NOT NULL")[
            0
        ][0]

    # Invites
    def invite_name(self, token: str) -> str | None:
        rows = self._q("SELECT name FROM invites WHERE token_hash = ? AND expires > ?",
                       _token_hash(token), self.clock())  # fmt: skip
        return rows[0][0] if rows else None

    def accept(self, token: str, password: str) -> str:
        """Set the password of the invite's user; the link is used up. Returns the name."""
        if len(password) < MIN_PASSWORD:
            raise ValueError(f"Use at least {MIN_PASSWORD} characters")
        name = self.invite_name(token)
        if name is None:
            raise ValueError("This link is no longer valid: ask an admin for a new one")
        with self.lock:
            self.db.execute("BEGIN")
            self.db.execute(
                "UPDATE users SET password = ? WHERE name = ?", (hash_password(password), name)
            )
            self.db.execute("DELETE FROM invites WHERE name = ?", (name,))
            self.db.execute("DELETE FROM sessions WHERE name = ?", (name,))
            self.db.execute("COMMIT")
        return name

    # Sign-in
    def _failed_recently(self, key: str) -> bool:
        cutoff = self.clock() - FAIL_WINDOW_S
        recent = [t for t in self.fails.get(key, []) if t > cutoff]
        self.fails[key] = recent
        return len(recent) >= MAX_FAILS

    def login(self, name: str, password: str, address: str) -> tuple[str, str] | None:
        """(session token, csrf token) on success; None on a wrong name or password."""
        name = name.strip().lower()
        keys = (f"name:{name}", f"addr:{address}")
        with self.lock:
            if any(self._failed_recently(k) for k in keys):
                raise PermissionError("Too many failed attempts: try again in 15 minutes")
        user = self._q("SELECT password FROM users WHERE name = ?", name)
        ok = check_password(password, user[0][0] if user else None)
        if not user:
            check_password(password, hash_password("x" * MIN_PASSWORD))  # same timing
        if not ok:
            with self.lock:
                for k in keys:
                    self.fails.setdefault(k, []).append(self.clock())
            return None
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(16)
        now = self.clock()
        self._q("DELETE FROM sessions WHERE expires <= ?", now)
        self._q("INSERT INTO sessions VALUES (?, ?, ?, ?)", _token_hash(token), name, csrf,
                now + SESSION_S)  # fmt: skip
        self._q("UPDATE users SET last_login = ? WHERE name = ?", now, name)
        return token, csrf

    def session(self, token: str | None) -> dict | None:
        if not token:
            return None
        rows = self._q(
            "SELECT s.name, u.role, s.csrf FROM sessions s JOIN users u ON u.name = s.name "
            "WHERE s.token_hash = ? AND s.expires > ? AND u.password IS NOT NULL",
            _token_hash(token), self.clock())  # fmt: skip
        return dict(zip(("name", "role", "csrf"), rows[0], strict=True)) if rows else None

    def logout(self, token: str | None) -> None:
        if token:
            self._q("DELETE FROM sessions WHERE token_hash = ?", _token_hash(token))


# --- Pages -------------------------------------------------------------------------------------

STYLE = """
:root { --bg:#f6f5f2; --card:#fff; --ink:#1d2433; --muted:#5d6675; --rule:#d9dce2; --accent:#2a78d6;
  --bad:#b3261e; color-scheme: light; }
@media (prefers-color-scheme: dark) { :root { --bg:#14171d; --card:#1d2129; --ink:#e7e9ee;
  --muted:#a1a8b5; --rule:#353b46; --accent:#5a9ef0; --bad:#f2867d; color-scheme: dark; } }
body { margin:0; background:var(--bg); color:var(--ink); font:15px/1.5 system-ui, sans-serif; }
main { max-width: 720px; margin: 8vh auto; padding: 0 16px; }
.card { background:var(--card); border:1px solid var(--rule); border-radius:10px; padding:24px; }
h1 { font-size:20px; margin:0 0 4px; } p.muted, .muted { color:var(--muted); font-size:13px; }
label { display:block; margin:14px 0 4px; font-weight:600; font-size:13px; }
input, select { font:inherit; padding:7px 9px; border:1px solid var(--rule); border-radius:6px;
  background:var(--bg); color:var(--ink); width:100%; box-sizing:border-box; }
button { font:inherit; padding:7px 14px; border-radius:6px; border:1px solid var(--accent);
  background:var(--accent); color:#fff; cursor:pointer; margin-top:16px; }
button.plain { background:transparent; color:var(--accent); margin:0; padding:3px 9px; }
.err { color:var(--bad); }
table { width:100%; border-collapse:collapse; margin-top:12px; font-size:14px; }
th, td { text-align:left; padding:7px 6px; border-bottom:1px solid var(--rule);
  vertical-align:middle; }
td form { display:inline; } .row { display:flex; gap:10px; align-items:end; flex-wrap:wrap; }
.row > div { flex:1 1 160px; } .link { word-break:break-all; background:var(--bg); padding:10px;
  border-radius:6px; border:1px dashed var(--accent); font-family:ui-monospace, monospace;
  font-size:13px; }
nav { display:flex; gap:14px; justify-content:flex-end; font-size:13px; margin-bottom:10px; }
a { color:var(--accent); }
"""


def page(title: str, body: str) -> bytes:
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<meta name='robots' content='noindex'><title>{html.escape(title)}</title>"
        f"<style>{STYLE}</style></head><body><main>{body}</main></body></html>"
    ).encode()


def _e(s) -> str:
    return html.escape(str(s), quote=True)


def _when(t: float | None) -> str:
    return time.strftime("%d %b %Y %H:%M", time.localtime(t)) if t else "never"


def login_page(next_url: str, error: str = "") -> bytes:
    return page(
        "Sign in",
        f"""<div class="card"><h1>Social Energy Explorer</h1>
      <p class="muted">Research team only. Pseudonymised data about minors: keep what you see to
      the team.</p>{f'<p class="err">{_e(error)}</p>' if error else ""}
      <form method="post" action="/auth/login">
      <input type="hidden" name="next" value="{_e(next_url)}">
      <label for="u">Name</label>
      <input id="u" name="name" autocomplete="username" required autofocus>
      <label for="p">Password</label><input id="p" name="password" type="password"
        autocomplete="current-password" required>
      <button type="submit">Sign in</button></form></div>""",
    )


def invite_page(name: str, token: str, error: str = "") -> bytes:
    return page(
        "Choose a password",
        f"""<div class="card"><h1>Welcome, {_e(name)}</h1>
      <p class="muted">Choose your password for the Social Energy Explorer: at least
      {MIN_PASSWORD} characters. Only you will know it.</p>
      {f'<p class="err">{_e(error)}</p>' if error else ""}
      <form method="post" action="/auth/invite/{_e(token)}">
      <input type="text" name="name" value="{_e(name)}" autocomplete="username" hidden readonly>
      <label for="p">New password</label><input id="p" name="password" type="password"
        autocomplete="new-password" minlength="{MIN_PASSWORD}" required autofocus>
      <label for="q">Again</label><input id="q" name="again" type="password"
        autocomplete="new-password" minlength="{MIN_PASSWORD}" required>
      <button type="submit">Set password and sign in</button></form></div>""",
    )


def admin_page(store: Store, me: dict, base: str, notice: str = "", link: str = "") -> bytes:
    csrf = f'<input type="hidden" name="csrf" value="{_e(me["csrf"])}">'
    rows = []
    for u in store.users():
        status = "active" if u["active"] else "invited, no password yet"
        actions = (
            ""
            if u["name"] == me["name"]
            else f"""
          <form method="post" action="/auth/admin/reset">{csrf}<input type="hidden" name="name"
            value="{_e(u["name"])}"><button class="plain" title="Make a new link on which they
            choose a new password">new link</button></form>
          <form method="post" action="/auth/admin/remove" onsubmit="return confirm('Remove
            {_e(u["name"])}? They are signed out at once.')">{csrf}<input type="hidden"
            name="name" value="{_e(u["name"])}"><button class="plain">remove</button></form>"""
        )
        rows.append(
            f"<tr><td><b>{_e(u['name'])}</b></td><td>{_e(u['role'])}</td>"
            f"<td>{status}</td><td>{_when(u['last_login'])}</td><td>{actions}</td></tr>"
        )
    shown = (
        f"""<p><b>Send this link to the person</b> (e.g. by e-mail or a private message).
      It works once, for 7 days; on it they choose their own password.</p>
      <p class="link">{_e(link)}</p>"""
        if link
        else ""
    )
    return page(
        "Explorer admin",
        f"""<nav><a href="/">← Explorer</a><form method="post"
      action="/auth/logout" style="display:inline">{csrf}<button class="plain">Sign out
      {_e(me["name"])}</button></form></nav><div class="card"><h1>Who can sign in</h1>
      <p class="muted">Only researchers the project lead names. Everyone also needs the
      institute VPN.</p>{f"<p>{_e(notice)}</p>" if notice else ""}{shown}
      <table><thead><tr><th>Name</th><th>Role</th><th>Status</th><th>Last sign-in</th><th></th>
      </tr></thead><tbody>{"".join(rows)}</tbody></table>
      <h1 style="margin-top:28px">Invite someone</h1>
      <form method="post" action="/auth/admin/invite">{csrf}<div class="row">
      <div><label for="n">Name (short, lower case, e.g. mahdi)</label><input id="n" name="name"
        required pattern="[a-z0-9][a-z0-9._-]*"></div>
      <div><label for="r">Role</label><select id="r" name="role"><option value="researcher">
        researcher: can view</option><option value="admin">admin: can also manage users</option>
        </select></div></div><button type="submit">Make invite link</button></form></div>""",
    )


# --- HTTP --------------------------------------------------------------------------------------


def _safe_next(url: str) -> str:
    """Only paths on this site, never another host."""
    return url if url.startswith("/") and not url.startswith("//") and "\\" not in url else "/"


class Handler(BaseHTTPRequestHandler):
    store: Store
    server_version = "explorer-auth"
    sys_version = ""

    def log_message(self, format, *args):  # quiet: nginx logs requests
        pass

    # helpers
    def _cookie(self) -> str | None:
        for part in self.headers.get("Cookie", "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE:
                return v
        return None

    def _address(self) -> str:
        return self.headers.get("X-Real-IP") or self.client_address[0]

    def _base(self) -> str:
        return f"https://{self.headers.get('Host', 'localhost')}"

    def _send(self, status, body=b"", headers=None):
        self.send_response(status)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        if body:
            self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)

    def _redirect(self, where: str, cookie: str | None = None):
        headers = {"Location": where}
        if cookie is not None:
            headers["Set-Cookie"] = cookie
        self._send(HTTPStatus.SEE_OTHER, headers=headers)

    def _form(self) -> dict[str, str]:
        length = min(int(self.headers.get("Content-Length") or 0), 10_000)
        data = self.rfile.read(length).decode("utf-8", "replace")
        return {k: v[0] for k, v in urllib.parse.parse_qs(data, keep_blank_values=True).items()}

    def _me(self) -> dict | None:
        return self.store.session(self._cookie())

    # routes
    def do_GET(self):
        path = urllib.parse.urlsplit(self.path)
        query = dict(urllib.parse.parse_qsl(path.query))
        me = self._me()
        if path.path == "/check":
            return self._send(HTTPStatus.NO_CONTENT if me else HTTPStatus.UNAUTHORIZED)
        if path.path == "/auth/me":
            body = f'{{"name": "{me["name"]}", "role": "{me["role"]}"}}' if me else "null"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body.encode())
        if path.path == "/auth/login":
            if me:
                return self._redirect(_safe_next(query.get("next", "/")))
            return self._send(HTTPStatus.OK, login_page(_safe_next(query.get("next", "/"))))
        if path.path.startswith("/auth/invite/"):
            token = path.path.rsplit("/", 1)[1]
            name = self.store.invite_name(token)
            if not name:
                return self._send(HTTPStatus.NOT_FOUND, page("Link not valid", '<div class="card">'
                    "<h1>This link is no longer valid</h1><p>It was used already or is older than "
                    "7 days. Ask an admin for a new one.</p></div>"))  # fmt: skip
            return self._send(HTTPStatus.OK, invite_page(name, token))
        if path.path == "/auth/logout":
            if not me:
                return self._redirect("/auth/login")
            csrf = f'<input type="hidden" name="csrf" value="{_e(me["csrf"])}">'
            return self._send(
                HTTPStatus.OK,
                page(
                    "Sign out",
                    f"""<div class="card">
              <h1>Sign out {_e(me["name"])}?</h1><form method="post" action="/auth/logout">
              {csrf}<button type="submit">Sign out</button></form>
              <p><a href="/">Back to the explorer</a></p></div>""",
                ),
            )
        if path.path == "/auth/admin":
            if not me:
                return self._redirect("/auth/login?next=/auth/admin")
            if me["role"] != "admin":
                body = '<div class="card"><h1>Admins only</h1><p><a href="/">Back</a></p></div>'
                return self._send(HTTPStatus.FORBIDDEN, page("Admins only", body))
            return self._send(HTTPStatus.OK, admin_page(self.store, me, self._base()))
        return self._send(HTTPStatus.NOT_FOUND, page("Not found", "<p>Not found</p>"))

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        form = self._form()
        if path == "/auth/login":
            nxt = _safe_next(form.get("next", "/"))
            try:
                got = self.store.login(
                    form.get("name", ""), form.get("password", ""), self._address()
                )
            except PermissionError as err:
                return self._send(HTTPStatus.TOO_MANY_REQUESTS, login_page(nxt, str(err)))
            if not got:
                return self._send(
                    HTTPStatus.UNAUTHORIZED, login_page(nxt, "Wrong name or password")
                )
            return self._redirect(nxt, self._session_cookie(got[0]))
        if path.startswith("/auth/invite/"):
            token = path.rsplit("/", 1)[1]
            name = self.store.invite_name(token)
            if not name:
                return self._redirect(f"/auth/invite/{token}")
            if form.get("password") != form.get("again"):
                return self._send(HTTPStatus.BAD_REQUEST, invite_page(name, token,
                                  "The two passwords differ"))  # fmt: skip
            try:
                self.store.accept(token, form.get("password", ""))
            except ValueError as err:
                return self._send(HTTPStatus.BAD_REQUEST, invite_page(name, token, str(err)))
            got = self.store.login(name, form["password"], self._address())
            return self._redirect("/", self._session_cookie(got[0]) if got else None)

        me = self._me()
        if not me or not hmac.compare_digest(form.get("csrf", ""), me["csrf"]):
            return self._send(
                HTTPStatus.FORBIDDEN, page("Refused", "<p>Refused: sign in again.</p>")
            )
        if path == "/auth/logout":
            self.store.logout(self._cookie())
            return self._redirect(
                "/auth/login", f"{COOKIE}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Strict"
            )
        if me["role"] != "admin" or not path.startswith("/auth/admin/"):
            return self._send(HTTPStatus.FORBIDDEN, page("Admins only", "<p>Admins only</p>"))
        name = form.get("name", "").strip().lower()
        notice, link = "", ""
        try:
            if path == "/auth/admin/invite" or path == "/auth/admin/reset":
                user = self.store.user(name)
                role = form.get("role") or (user["role"] if user else "researcher")
                if path == "/auth/admin/invite" and user:
                    raise ValueError(f"{name} exists already: use 'new link' in the list")
                token = self.store.invite(name, role)
                link = f"{self._base()}/auth/invite/{token}"
                notice = (
                    f"Invited {name}."
                    if path.endswith("invite")
                    else f"New link for {name}: their old password still works until they use it."
                )
            elif path == "/auth/admin/remove":
                if name == me["name"]:
                    raise ValueError("You cannot remove yourself")
                self.store.remove(name)
                notice = f"Removed {name}; they are signed out."
        except ValueError as err:
            notice = str(err)
        return self._send(HTTPStatus.OK, admin_page(self.store, me, self._base(), notice, link))

    @staticmethod
    def _session_cookie(token: str) -> str:
        return f"{COOKIE}={token}; Path=/; Max-Age={SESSION_S}; HttpOnly; Secure; SameSite=Strict"


def make_server(db: str, port: int, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    store = Store(db)
    handler = type("BoundHandler", (Handler,), {"store": store})
    return ThreadingHTTPServer((host, port), handler)


def _restart_on_change() -> None:
    """Re-exec when this file is replaced by a deploy, so no admin rights are needed for it."""
    me = os.path.abspath(__file__)
    seen = os.stat(me).st_mtime
    while True:
        time.sleep(10)
        try:
            now = os.stat(me).st_mtime
        except FileNotFoundError:
            continue
        if now != seen:
            os.execv(sys.executable, [sys.executable, me, *sys.argv[1:]])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--db", required=True)
    s.add_argument("--port", type=int, default=8790)
    i = sub.add_parser("invite", help="print a one-time invite link for NAME")
    i.add_argument("name")
    i.add_argument("--admin", action="store_true")
    i.add_argument("--db", required=True)
    i.add_argument("--base", default="https://localhost")
    r = sub.add_parser("remove", help="remove NAME; they are signed out at once")
    r.add_argument("name")
    r.add_argument("--db", required=True)
    u = sub.add_parser("users", help="list who can sign in")
    u.add_argument("--db", required=True)
    args = parser.parse_args(argv)
    if args.cmd == "invite":
        user = Store(args.db).user(args.name.strip().lower())
        role = "admin" if args.admin else (user["role"] if user else "researcher")
        token = Store(args.db).invite(args.name, role)
        print(f"{args.base.rstrip('/')}/auth/invite/{token}")
        return 0
    if args.cmd == "remove":
        Store(args.db).remove(args.name.strip().lower())
        return 0
    if args.cmd == "users":
        for x in Store(args.db).users():
            state = "active" if x["active"] else "invited"
            print(f"{x['name']}\t{x['role']}\t{state}\tlast sign-in {_when(x['last_login'])}")
        return 0
    os.umask(0o077)
    server = make_server(args.db, args.port)
    threading.Thread(target=_restart_on_change, daemon=True).start()
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
