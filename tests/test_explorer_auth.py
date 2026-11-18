"""The hosted explorer's sign-in service: invites, passwords, sessions, admin rights, limits."""

from __future__ import annotations

import http.client
import threading
import urllib.parse

import pytest

from social_energy.explorer import auth_service as auth


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


@pytest.fixture
def store(tmp_path):
    return auth.Store(str(tmp_path / "auth.db"), clock=Clock())


def test_password_hashes_check_and_differ():
    h = auth.hash_password("correct horse battery")
    assert h.startswith("scrypt$") and "correct" not in h
    assert auth.check_password("correct horse battery", h)
    assert not auth.check_password("wrong", h)
    assert h != auth.hash_password("correct horse battery")  # salted
    assert not auth.check_password("x", None) and not auth.check_password("x", "garbage")


def test_invite_then_choose_password_then_sign_in(store):
    token = store.invite("Anna")
    assert not store.user("anna")["active"]
    assert store.invite_name(token) == "anna"
    store.accept(token, "a long enough pw")
    assert store.invite_name(token) is None  # used up
    sess, csrf = store.login("anna", "a long enough pw", "1.2.3.4")
    assert store.session(sess) == {"name": "anna", "role": "researcher", "csrf": csrf}
    assert store.login("anna", "wrong password!!", "1.2.3.4") is None


def test_short_password_and_bad_names_are_refused(store):
    token = store.invite("ben")
    with pytest.raises(ValueError, match="12"):
        store.accept(token, "short")
    for bad in ["", "a b", "x:y", "../x", "é"]:
        with pytest.raises(ValueError):
            store.invite(bad)


def test_invites_expire_and_a_new_link_kills_the_old(store):
    old = store.invite("cara")
    new = store.invite("cara")
    assert store.invite_name(old) is None and store.invite_name(new) == "cara"
    store.clock.t += auth.INVITE_S + 1
    with pytest.raises(ValueError, match="no longer valid"):
        store.accept(new, "a long enough pw")


def test_sessions_expire_and_end_on_removal_or_logout(store):
    store.accept(store.invite("dan"), "a long enough pw")
    sess, _ = store.login("dan", "a long enough pw", "a")
    store.logout(sess)
    assert store.session(sess) is None
    sess, _ = store.login("dan", "a long enough pw", "a")
    store.clock.t += auth.SESSION_S + 1
    assert store.session(sess) is None
    sess, _ = store.login("dan", "a long enough pw", "a")
    store.remove("dan")
    assert store.session(sess) is None


def test_reset_signs_out_once_the_new_password_is_set(store):
    store.accept(store.invite("eve"), "first password!!")
    sess, _ = store.login("eve", "first password!!", "a")
    link = store.invite("eve")
    assert store.session(sess) is not None  # the old password still works meanwhile
    store.accept(link, "second password!")
    assert store.session(sess) is None
    assert store.login("eve", "first password!!", "a") is None


def test_repeated_failures_are_refused_for_a_while(store):
    store.accept(store.invite("fay"), "a long enough pw")
    for _ in range(auth.MAX_FAILS):
        assert store.login("fay", "nope nope nope", "9.9.9.9") is None
    with pytest.raises(PermissionError):
        store.login("fay", "a long enough pw", "8.8.8.8")  # same name, other address
    store.clock.t += auth.FAIL_WINDOW_S + 1
    assert store.login("fay", "a long enough pw", "8.8.8.8") is not None


@pytest.mark.parametrize(
    ("url", "want"),
    [("/x?bin=3", "/x?bin=3"), ("//evil.example", "/"), ("https://evil.example", "/"),
     ("/\\evil", "/"), ("", "/")],
)  # fmt: skip
def test_next_never_leaves_the_site(url, want):
    assert auth._safe_next(url) == want


# --- Over HTTP ----------------------------------------------------------------------------------


@pytest.fixture
def site(tmp_path):
    server = auth.make_server(str(tmp_path / "auth.db"), 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server
    server.shutdown()


def _req(server, method, path, form=None, cookie=None):
    conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1])
    headers = {"Host": "explorer.test"}
    body = None
    if form is not None:
        body = urllib.parse.urlencode(form)
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if cookie:
        headers["Cookie"] = f"{auth.COOKIE}={cookie}"
    conn.request(method, path, body=body, headers=headers)
    resp = conn.getresponse()
    return resp.status, dict(resp.getheaders()), resp.read().decode()


def _cookie_of(headers):
    return headers["Set-Cookie"].split(";")[0].split("=", 1)[1]


def _sign_in(site, name, role="researcher"):
    token = site.RequestHandlerClass.store.invite(name, role)
    pw = {"password": "a long enough pw", "again": "a long enough pw"}
    status, headers, _ = _req(site, "POST", f"/auth/invite/{token}", pw)
    assert status == 303
    return _cookie_of(headers)


def test_check_is_401_until_signed_in(site):
    assert _req(site, "GET", "/check")[0] == 401
    cookie = _sign_in(site, "gus")
    assert _req(site, "GET", "/check", cookie=cookie)[0] == 204
    assert _req(site, "GET", "/auth/login?next=/x")[0] == 200
    form = {"name": "gus", "password": "a long enough pw", "next": "/"}
    flags = _req(site, "POST", "/auth/login", form)[1]["Set-Cookie"]
    assert all(f in flags for f in ("HttpOnly", "Secure", "SameSite=Strict"))


def test_login_redirects_only_inside_the_site(site):
    _sign_in(site, "hal")
    form = {"name": "hal", "password": "a long enough pw", "next": "//evil"}
    status, headers, _ = _req(site, "POST", "/auth/login", form)
    assert (status, headers["Location"]) == (303, "/")


def test_admin_page_is_for_admins_only(site):
    researcher = _sign_in(site, "ida")
    assert _req(site, "GET", "/auth/admin", cookie=researcher)[0] == 403
    admin = _sign_in(site, "jo", "admin")
    status, _, body = _req(site, "GET", "/auth/admin", cookie=admin)
    assert status == 200 and "ida" in body


def test_admin_actions_need_the_form_token(site):
    admin = _sign_in(site, "kim", "admin")
    csrf = site.RequestHandlerClass.store.session(admin)["csrf"]
    assert _req(site, "POST", "/auth/admin/invite", {"name": "lea"}, cookie=admin)[0] == 403
    status, _, body = _req(site, "POST", "/auth/admin/invite",
                           {"name": "lea", "csrf": csrf}, cookie=admin)  # fmt: skip
    assert status == 200 and "https://explorer.test/auth/invite/" in body
    assert site.RequestHandlerClass.store.user("lea")["role"] == "researcher"


def test_a_researcher_cannot_invite(site):
    researcher = _sign_in(site, "max")
    csrf = site.RequestHandlerClass.store.session(researcher)["csrf"]
    status = _req(site, "POST", "/auth/admin/invite", {"name": "ned", "csrf": csrf},
                  cookie=researcher)[0]  # fmt: skip
    assert status == 403 and site.RequestHandlerClass.store.user("ned") is None


def test_names_in_pages_are_escaped(site):
    admin = _sign_in(site, "olu", "admin")
    body = _req(site, "GET", "/auth/login?next=/%22%3E%3Cscript%3E")[2]
    assert "<script>" not in body
    assert "<script>" not in _req(site, "GET", "/auth/admin", cookie=admin)[2]


def test_me_says_who_is_signed_in(site):
    assert _req(site, "GET", "/auth/me")[2] == "null"
    cookie = _sign_in(site, "pia", "admin")
    status, headers, body = _req(site, "GET", "/auth/me", cookie=cookie)
    assert (status, body) == (200, '{"name": "pia", "role": "admin"}')
    assert headers["Content-Type"] == "application/json"


def test_logout_asks_then_needs_the_form_token(site):
    cookie = _sign_in(site, "quin")
    assert "Sign out quin" in _req(site, "GET", "/auth/logout", cookie=cookie)[2]
    assert _req(site, "POST", "/auth/logout", {}, cookie=cookie)[0] == 403
    csrf = site.RequestHandlerClass.store.session(cookie)["csrf"]
    assert _req(site, "POST", "/auth/logout", {"csrf": csrf}, cookie=cookie)[0] == 303
    assert _req(site, "GET", "/check", cookie=cookie)[0] == 401
