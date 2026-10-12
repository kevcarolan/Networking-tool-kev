"""Fixes from the security review: sign-in limits, sessions, the AD domain rule, safe
exports, upload limits, and licence and certificate checks."""

import csv
import datetime
import io
import time
import zipfile

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.core import appsettings, auth, exports, licence
from app.core.crypto import hash_password
from app.core.db import session_scope
from app.tools.circuits.importer import CircuitImportError, parse_workbook
from app.tools.firmware_upgrade.images import ImageError, ImageWriter
from tests.conftest import ADMIN_PASSWORD


def _login(client, username, password=ADMIN_PASSWORD):
    return client.post("/api/auth/login", json={"username": username, "password": password})


# --- sign-in -----------------------------------------------------------------------

def test_spelling_the_name_differently_does_not_reset_the_count(client):
    for name in ("admin", " admin", "ADMIN", "corp\\admin", "admin@corp.local"):
        assert _login(client, name, "wrong").status_code == 401
    assert _login(client, "admin").status_code == 429  # even with the right password


def test_one_address_trying_many_names_is_stopped(app, client):
    app.state.address_throttle.max_failures = 6
    for i in range(6):
        assert _login(client, f"user{i}", "wrong").status_code == 401
    assert _login(client, "admin").status_code == 429


def test_the_throttle_forgets_stale_names_when_it_gets_large():
    t = auth.LoginThrottle(window_seconds=0)
    for i in range(10001):
        t.fail(f"name{i}")
    t.fail("one-more")
    assert len(t._failures) <= 1


@pytest.mark.parametrize("typed, sam", [
    ("jsmith", "jsmith"), ("CORP\\jsmith", "jsmith"), ("corp.local\\jsmith", "jsmith"),
    ("jsmith@corp.local", "jsmith"), ("JSmith@CORP.LOCAL", "JSmith"),
    ("OTHER\\jsmith", ""), ("jsmith@other.local", ""), ("jsmith@corp", ""),
    ("a@b@corp.local", ""), ("CORP\\a\\b", ""), (" ", ""),
])
def test_only_the_configured_domain_is_accepted(typed, sam):
    assert auth._sam_in_domain(typed, "corp.local") == sam


# --- sessions ----------------------------------------------------------------------

class _Later:
    """time, moved forward."""

    def __init__(self, hours):
        self.offset = hours * 3600

    def time(self):
        return time.time() + self.offset

    def monotonic(self):
        return time.monotonic()


def test_a_session_ends_after_the_maximum_age_however_busy(admin, monkeypatch, settings):
    assert admin.get("/api/auth/me").status_code == 200
    monkeypatch.setattr(auth, "time", _Later(settings.session_max_age_hours - 1))
    assert admin.get("/api/auth/me").status_code == 200
    monkeypatch.setattr(auth, "time", _Later(settings.session_max_age_hours + 1))
    r = admin.get("/api/auth/me")
    assert r.status_code == 401 and "expired" in r.json()["detail"]
    monkeypatch.undo()
    assert admin.get("/api/auth/me").status_code == 401  # the cookie was cleared


def test_changing_the_break_glass_password_signs_its_sessions_out(app, admin):
    assert admin.get("/api/auth/me").status_code == 200
    app.state.settings.local_admin_password_hash = hash_password("a-new-password-1")
    assert admin.get("/api/auth/me").status_code == 401
    assert _login(admin, "admin", "a-new-password-1").status_code == 200
    assert admin.get("/api/auth/me").status_code == 200


def test_removing_the_break_glass_password_signs_its_sessions_out(app, admin):
    app.state.settings.local_admin_password_hash = ""
    assert admin.get("/api/auth/me").status_code == 401


# --- exports -----------------------------------------------------------------------

@pytest.mark.parametrize("value, out", [
    ("=HYPERLINK(\"http://x\")", "'=HYPERLINK(\"http://x\")"), ("+1+cmd", "'+1+cmd"),
    ("@SUM(A1)", "'@SUM(A1)"), ("-2+3", "'-2+3"), ("\tx", "'\tx"),
    ("-", "-"), ("-12", "-12"), ("+3.5", "+3.5"), ("core-sw1", "core-sw1"), (42, 42), (None, None),
])
def test_formula_like_text_is_kept_as_text(value, out):
    assert exports.safe(value) == out


def test_the_activity_export_neutralises_a_typed_formula(admin, client):
    _login(client, "=cmd|' /C calc'!A0", "x")
    _login(admin, "admin")
    rows = list(csv.reader(io.StringIO(admin.get("/api/activity.csv").text)))
    assert any(c.startswith("'=cmd") for r in rows for c in r)
    assert not any(c.startswith("=") for r in rows for c in r)


def test_xlsx_cells_stay_text():
    wb = Workbook()
    ws = wb.active
    exports.append_row(ws, ["=1+1", "plain", 5])
    assert [c.data_type for c in ws[1]] == ["s", "s", "n"]


# --- uploads -----------------------------------------------------------------------

def test_a_workbook_that_unpacks_huge_is_refused():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("xl/worksheets/sheet1.xml", b"0" * (501 * 2**20))
    assert len(buf.getvalue()) < 2 * 2**20  # small on the wire
    with pytest.raises(CircuitImportError, match="unpacks to more than"):
        parse_workbook(buf.getvalue())


def test_a_file_that_is_not_a_workbook_is_refused():
    with pytest.raises(CircuitImportError, match="Not a readable"):
        parse_workbook(b"not a zip")


def test_an_image_upload_stops_before_the_disk_fills(tmp_path, monkeypatch):
    from app.tools.firmware_upgrade import images

    free = {"bytes": 3 * 2**30}
    monkeypatch.setattr(images.shutil, "disk_usage",
                        lambda p: type("U", (), {"free": free["bytes"]})())
    w = ImageWriter(tmp_path, "img.bin", 4 * 2**30, keep_free=2 * 2**30)
    w.write(b"x" * 2**20)
    free["bytes"] = 2 * 2**30 + 2**19  # the disk filled from somewhere else
    w.write(b"x" * 63 * 2**20)  # checked again only every 64 MB
    with pytest.raises(ImageError, match="free disk space"):
        w.write(b"x" * 2**20)
    w.abort()
    assert list(tmp_path.iterdir()) == []


def test_the_web_server_lets_circuit_lists_through():
    from pathlib import Path

    conf = (Path(__file__).parents[2] / "deploy" / "nginx-netops.conf").read_text()
    block = conf.split("location = /api/circuits/imports/upload", 1)[1].split("}", 1)[0]
    assert "client_max_body_size 30m" in block


# --- licence and certificate -------------------------------------------------------

def test_without_a_licence_a_device_cannot_be_turned_into_another(admin, device, monkeypatch):
    monkeypatch.setattr(licence, "DEVELOPMENT", False)
    with session_scope() as db:
        appsettings.save(db, {licence.TRIAL_STARTED: (
            datetime.date.today() - datetime.timedelta(days=61)).isoformat()}, "test")
    for change in ({"address": "10.9.9.9"}, {"name": "other-sw"}):
        r = admin.put(f"/api/devices/{device['id']}", json={**device, **change})
        assert r.status_code == 403 and "licence" in r.json()["detail"]
    r = admin.put(f"/api/devices/{device['id']}", json={**device, "site": "DC2"})
    assert r.status_code == 200  # other details can still be kept up to date


@pytest.mark.parametrize("name", ["a" * 70 + ".example.com", "bad_name.local", "naïve.local",
                                  "-x.local", "a..b"])
def test_a_certificate_request_for_a_bad_name_is_a_clear_error(admin, name):
    r = admin.post("/api/setup/certificate/request", json={"names": [name]})
    assert r.status_code == 422, r.text


def test_a_wildcard_certificate_request_is_allowed(admin):
    r = admin.post("/api/setup/certificate/request", json={"names": ["*.corp.local"]})
    assert r.status_code == 200, r.text


def test_the_client_sees_no_server_errors_for_odd_sign_ins(app):
    with TestClient(app, raise_server_exceptions=False) as c:
        for name in ("\\", "@", "\\\\", "a@", "\x00"):
            assert _login(c, name, "x").status_code == 401
