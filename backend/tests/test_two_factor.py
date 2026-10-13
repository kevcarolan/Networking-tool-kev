"""Two-factor sign-in (core/totp.py, core/twofactor.py): codes, setting it up, signing in
with a code or a recovery code, being made to set it up, turning it off, an admin's reset,
the break-glass admin, and that a half-finished sign-in opens nothing."""

import base64

import pytest
from fastapi.testclient import TestClient

from app.core import totp
from app.main import create_app
from tests.conftest import ADMIN_PASSWORD, FakeCollector, FakeFetcher

PW = "a-long-password-123"


def _add(admin, username, source="local"):
    r = admin.post("/api/users", json={"username": username, "source": source, "password": PW,
                                       "is_admin": False, "permissions": {"inventory": "view"}})
    assert r.status_code == 201, r.text
    return r.json()


def _login(c, username, password=PW):
    c.post("/api/auth/logout")
    return c.post("/api/auth/login", json={"username": username, "password": password})


def _now_code(secret):
    return totp.code_at(secret.replace(" ", ""), totp.step_now())


def _turn_on(c):
    s = c.post("/api/auth/two-factor/start").json()
    assert s["qr_svg"].startswith("<svg") and s["uri"].startswith("otpauth://totp/")
    r = c.post("/api/auth/two-factor/enable", json={"code": _now_code(s["secret"])})
    assert r.status_code == 200, r.text
    return s["secret"].replace(" ", ""), r.json()["recovery_codes"]


def test_codes():
    secret = base64.b32encode(b"12345678901234567890").decode()  # RFC 6238 test key
    assert totp.code_at(secret, 59 // 30) == "287082"
    assert totp.code_at(secret, 1111111109 // 30) == "081804"
    s = totp.new_secret()
    step = totp.step_now()
    assert totp.verify(s, totp.code_at(s, step)) == step
    assert totp.verify(s, totp.code_at(s, step - 1)) == step - 1  # the clock drifted a little
    assert totp.verify(s, totp.code_at(s, step - 3)) is None  # too old
    assert totp.verify(s, totp.code_at(s, step), last_step=step) is None  # used already
    assert totp.verify(s, "12345") is None
    hashes = [totp.hash_code(c) for c in ["aaaa-bbbb-cccc", "dddd-eeee-ffff"]]
    assert totp.use_recovery(hashes, " AAAA-bbbb-cccc ") == hashes[1:]
    assert totp.use_recovery(hashes, "zzzz-zzzz-zzzz") is None


def test_turn_on_and_sign_in_with_a_code_or_a_recovery_code(admin):
    client = TestClient(admin.app)
    _add(admin, "jsmith")
    assert _login(client, "jsmith").json()["username"] == "jsmith"
    assert client.get("/api/auth/two-factor").json() == {
        "available": True, "enabled": False, "required": False, "since": None, "recovery_left": 0}
    secret, codes = _turn_on(client)
    assert len(codes) == 10

    r = _login(client, "jsmith")
    assert r.json() == {"two_factor": "code", "username": "jsmith"}
    assert client.get("/api/auth/me").status_code == 401  # not signed in yet
    assert client.get("/api/devices").status_code == 401
    assert client.post("/api/auth/login/code", json={"code": "000000"}).status_code == 401
    # the code that turned it on was used: the next step's code (or a recovery code) works
    r = client.post("/api/auth/login/code", json={"code": codes[0]})
    assert r.status_code == 200 and r.json()["username"] == "jsmith"
    assert client.get("/api/auth/two-factor").json()["recovery_left"] == 9

    _login(client, "jsmith")
    assert client.post("/api/auth/login/code", json={"code": codes[0]}).status_code == 401  # once
    acts = [a for a in admin.get("/api/audit").json() if a["username"] == "jsmith"]
    assert any("recovery code (9 left)" in a["detail"] for a in acts)
    assert any(a["action"] == "user.two_factor_on" for a in acts)
    assert admin.get("/api/users").json()[0]["two_factor"] is True


def test_wrong_codes_lock_the_account_like_wrong_passwords(admin):
    client = TestClient(admin.app)
    _add(admin, "kate")
    _login(client, "kate")
    _turn_on(client)
    _login(client, "kate")
    for _ in range(5):
        client.post("/api/auth/login/code", json={"code": "111111"})
    assert client.post("/api/auth/login/code", json={"code": "222222"}).status_code == 429


def test_required_for_local_users_means_setting_it_up_at_sign_in(admin):
    client = TestClient(admin.app)
    _add(admin, "lee")
    r = admin.put("/api/setup/options", json={"require_two_factor": True})
    assert r.status_code == 200, r.text
    assert _login(client, "lee").json()["two_factor"] == "setup"
    assert client.get("/api/devices").status_code == 401
    assert client.post("/api/auth/login/code", json={"code": "123456"}).status_code == 409
    s = client.post("/api/auth/two-factor/start").json()
    r = client.post("/api/auth/two-factor/enable", json={"code": _now_code(s["secret"])})
    assert r.status_code == 200 and r.json()["user"]["username"] == "lee"  # signed in now
    assert client.get("/api/devices").status_code == 200
    st = client.get("/api/auth/two-factor").json()
    assert st["required"] and st["enabled"]
    r = client.post("/api/auth/two-factor/disable", json={"password": PW, "code": "123456"})
    assert r.status_code == 409  # can't be turned off while required


def test_turning_it_off_needs_the_password_and_a_code(admin):
    client = TestClient(admin.app)
    _add(admin, "max")
    _login(client, "max")
    secret, codes = _turn_on(client)
    assert client.post("/api/auth/two-factor/disable",
                       json={"password": "wrong-password-xx", "code": codes[0]}).status_code == 403
    assert client.post("/api/auth/two-factor/disable",
                       json={"password": PW, "code": codes[1]}).status_code == 200
    assert _login(client, "max").json()["username"] == "max"  # straight in again


def test_admin_reset_for_a_lost_phone(admin):
    client = TestClient(admin.app)
    u = _add(admin, "nia")
    _login(client, "nia")
    _turn_on(client)
    assert admin.post(f"/api/users/{u['id']}/two-factor/reset").status_code == 200
    assert _login(client, "nia").json()["username"] == "nia"
    assert client.post(f"/api/users/{u['id']}/two-factor/reset").status_code == 403  # admins only


def test_a_pending_sign_in_runs_out(admin, monkeypatch):
    client = TestClient(admin.app)
    from app.core import twofactor

    _add(admin, "olu")
    _login(client, "olu")
    _turn_on(client)
    _login(client, "olu")
    monkeypatch.setattr(twofactor, "PENDING_SECONDS", -1)
    r = client.post("/api/auth/login/code", json={"code": "123456"})
    assert r.status_code == 401 and "Sign in again" in r.text


def test_break_glass_admin_with_a_secret_in_netops_env(settings):
    secret = totp.new_secret()
    settings.local_admin_totp_secret = secret
    app = create_app(settings, fetcher=FakeFetcher(), start_scheduler=False,
                     fw_collector=FakeCollector())
    with TestClient(app) as c:
        r = c.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD})
        assert r.json()["two_factor"] == "code"
        assert c.get("/api/users").status_code == 401
        r = c.post("/api/auth/login/code", json={"code": _now_code(secret)})
        assert r.status_code == 200 and r.json()["role"] == "admin"
        assert c.get("/api/users").status_code == 200
        st = c.get("/api/auth/two-factor").json()
        assert st["available"] is False and st["enabled"] is True


@pytest.mark.parametrize("path", ["/api/auth/two-factor/start", "/api/auth/two-factor/enable"])
def test_nothing_to_set_up_without_signing_in(client, path):
    assert client.post(path, json={"code": "123456"}).status_code == 401
