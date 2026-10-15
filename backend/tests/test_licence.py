"""Licences: the trial, signed licences (end date, device count, installation), what is
blocked without one, development mode, and the signing tool."""

import datetime
import stat

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app import cli, licence_tool
from app.core import appsettings, licence
from app.core.db import session_scope
from tests.test_upgrade_jobs import _create, env  # noqa: F401  (fixture)

KEY = Ed25519PrivateKey.generate()
TODAY = datetime.date.today()


@pytest.fixture(autouse=True)
def signing_key(monkeypatch):
    monkeypatch.setattr(licence, "public_keys", lambda: [KEY.public_key()])
    monkeypatch.setattr(licence, "DEVELOPMENT", False)


def _lic(customer="Acme Ltd", days=365, devices=100, install_id="", kind="customer", key=KEY,
         modules=None):
    expires = TODAY + datetime.timedelta(days=days) if days is not None else None
    return licence_tool.make(key, customer, expires, devices, install_id, kind, modules)


def _set(**values):
    with session_scope() as db:
        appsettings.save(db, values, "test")


def _end_trial():
    _set(**{licence.TRIAL_STARTED: (TODAY - datetime.timedelta(days=61)).isoformat()})


def _add(admin, name, address):
    return admin.post("/api/devices", json={"name": name, "address": address,
                                            "platform": "cisco_ios"})


def test_a_new_install_runs_a_60_day_trial(admin):
    s = admin.get("/api/licence").json()
    assert s["mode"] == "trial" and s["active"] and s["days_left"] == 60
    assert "60 days left" in s["warning"] and s["max_devices"] is None
    assert len(s["install_id"]) == 19  # XXXX-XXXX-XXXX-XXXX
    # the ID and the trial start don't change on the next start
    assert admin.get("/api/licence").json()["install_id"] == s["install_id"]


def test_after_the_trial_new_work_is_blocked_but_nothing_else(app, admin, device):
    _end_trial()
    s = admin.get("/api/licence").json()
    assert s["mode"] == "trial_ended" and not s["active"]
    assert "backups keep running" in s["warning"]
    r = _add(admin, "sw2", "10.0.0.2")
    assert r.status_code == 403 and "add devices" in r.json()["detail"]
    # viewing, editing and backups still work; nothing is deleted
    assert len(admin.get("/api/devices").json()) == 1
    assert admin.put(f"/api/devices/{device['id']}", json={**device, "site": "DC2"}).status_code == 200
    app.state.backup_service.run(device["id"])
    assert admin.get(f"/api/backup/devices/{device['id']}").json()["backup"]["status"] == "success"
    # a licence switches everything back on
    r = admin.post("/api/licence", json={"text": _lic()})
    assert r.status_code == 200 and r.json()["mode"] == "licensed" and r.json()["active"]
    assert _add(admin, "sw2", "10.0.0.2").status_code == 201
    actions = [e["action"] for e in admin.get("/api/audit").json()]
    assert "licence.install" in actions


def test_upgrades_can_t_be_planned_or_started_but_a_job_can_finish(admin, env):  # noqa: F811
    job = _create(admin, env)
    _end_trial()
    r = admin.post("/api/firmware/jobs", json={"device_id": env["device"]["id"],
                                               "image_id": env["image"]["id"]})
    assert r.status_code == 403 and "plan upgrade jobs" in r.json()["detail"]
    assert admin.post(f"/api/firmware/jobs/{job['id']}/start").status_code == 403
    # the steps before and after the change aren't blocked
    assert admin.post(f"/api/firmware/jobs/{job['id']}/precheck").status_code == 202


def test_device_limit(admin, device):
    assert admin.post("/api/licence", json={"text": _lic(devices=2)}).status_code == 200
    assert _add(admin, "sw2", "10.0.0.2").status_code == 201
    r = _add(admin, "sw3", "10.0.0.3")
    assert r.status_code == 403 and "covers 2 devices" in r.json()["detail"]
    s = admin.get("/api/licence").json()
    assert s["devices"] == 2 and "no more can be added" in s["warning"]


def test_licence_ending_soon_and_ended(admin):
    admin.post("/api/licence", json={"text": _lic(days=10)})
    s = admin.get("/api/licence").json()
    assert s["active"] and s["days_left"] == 10 and "Ask for a renewal" in s["warning"]
    with session_scope() as db:
        later = licence.status(db, today=TODAY + datetime.timedelta(days=11))
    assert later["mode"] == "expired" and not later["active"]
    assert "Acme Ltd ended" in later["message"]


@pytest.mark.parametrize("text, message", [
    ("hello", "isn't a licence"),
    (_lic(days=-1), "ended on"),
    (_lic(install_id="AAAA-BBBB-CCCC-DDDD"), "for installation AAAA-BBBB-CCCC-DDDD"),
    (_lic(key=Ed25519PrivateKey.generate()), "signature isn't valid"),
])
def test_bad_licences_are_refused(admin, text, message):
    r = admin.post("/api/licence", json={"text": text})
    assert r.status_code == 422 and message in r.json()["detail"]
    assert admin.get("/api/licence").json()["mode"] == "trial"
    assert admin.get("/api/audit").json()[0]["action"] == "licence.rejected"


def test_a_changed_licence_is_refused(admin):
    payload = licence.parse(_lic(devices=5))
    forged = licence.encode({**payload, "max_devices": 5000},
                            KEY.sign(licence.signed_bytes(payload)))
    r = admin.post("/api/licence", json={"text": forged})
    assert r.status_code == 422 and "signature" in r.json()["detail"]


def test_licence_tied_to_this_install(admin):
    install_id = admin.get("/api/licence").json()["install_id"]
    assert admin.post("/api/licence", json={"text": _lic(install_id=install_id)}).status_code == 200


def test_internal_licence_has_no_limits(admin):
    r = admin.post("/api/licence", json={"text": _lic(customer="Owner", days=None, devices=None,
                                                      kind="internal")})
    s = r.json()
    assert s["active"] and s["ends"] is None and s["max_devices"] is None
    assert s["licence"]["kind"] == "internal" and s["warning"] == ""


def test_only_admins_add_licences(client, admin):
    admin.post("/api/users", json={"username": "viewer1", "source": "local",
                                   "password": "a-long-viewer-pass", "permissions": {}})
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"username": "viewer1", "password": "a-long-viewer-pass"})
    assert client.get("/api/licence").status_code == 200
    assert client.post("/api/licence", json={"text": _lic()}).status_code == 403


def test_development_mode_is_never_limited(admin, monkeypatch):
    monkeypatch.setattr(licence, "DEVELOPMENT", True)
    _end_trial()
    s = admin.get("/api/licence").json()
    assert s["mode"] == "development" and s["active"]
    assert _add(admin, "sw2", "10.0.0.2").status_code == 201


def test_no_signing_key_built_in(admin, monkeypatch):
    monkeypatch.setattr(licence, "public_keys", lambda: [])
    r = admin.post("/api/licence", json={"text": _lic()})
    assert r.status_code == 422 and "no licence key built in" in r.json()["detail"]


def test_csv_import_stops_at_the_device_limit(admin, settings, tmp_path, monkeypatch, capsys):
    admin.post("/api/licence", json={"text": _lic(devices=2)})
    path = tmp_path / "devices.csv"
    path.write_text("name,address,platform\n" + "".join(
        f"sw{i},10.0.1.{i},cisco_ios\n" for i in range(1, 5)))
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
    assert cli.main(["import-csv", str(path)]) == 0
    assert "Imported 2 device(s), skipped 2" in capsys.readouterr().out
    _end_trial()
    assert cli.main(["import-csv", str(path)]) == 1


def test_signing_tool(tmp_path, monkeypatch, capsys):
    key_file = tmp_path / "signing.key"
    assert licence_tool.main(["keygen", "--out", str(key_file)]) == 0
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
    public_line = capsys.readouterr().out.strip().splitlines()[-1]
    assert licence_tool.main(["keygen", "--out", str(key_file)]) == 1  # never overwrites

    keys_file = tmp_path / "licence_keys.txt"
    keys_file.write_text(f"# comment\n{public_line}\n")
    monkeypatch.setattr(licence, "KEYS_FILE", keys_file)
    monkeypatch.undo()  # back to the real public_keys(), reading keys_file
    monkeypatch.setattr(licence, "KEYS_FILE", keys_file)

    lic = tmp_path / "acme.lic"
    assert licence_tool.main(["sign", "--key", str(key_file), "--customer", "Acme",
                              "--expires", "2030-01-31", "--devices", "50",
                              "--out", str(lic)]) == 0
    capsys.readouterr()
    assert licence_tool.main(["show", str(lic)]) == 0
    out = capsys.readouterr().out
    assert "Acme" in out and "2030-01-31" in out and "50" in out
    assert licence_tool.main(["sign", "--key", str(key_file), "--customer", "Acme"]) == 2
    assert licence_tool.main(["sign", "--key", str(key_file), "--internal"]) == 0
    assert "BEGIN LICENCE" in capsys.readouterr().out



# --- modules: one install, the licence unlocks tools ----------------------------------------

def test_a_licence_unlocks_only_its_tools(admin, device):
    r = admin.post("/api/licence", json={"text": _lic(modules=["backups", "syslog"])})
    assert r.status_code == 200 and r.json()["modules"] == ["backups", "syslog"]
    for path in ("/api/firmware/devices", "/api/firmware/jobs", "/api/circuits"):
        r = admin.get(path)
        assert r.status_code == 403 and "isn't in your licence" in r.json()["detail"], path
    assert admin.get("/api/syslog/messages").status_code == 200
    assert admin.get(f"/api/backup/devices/{device['id']}/runs").status_code == 200


def test_without_backups_the_devices_can_still_be_managed(admin, device):
    admin.post("/api/licence", json={"text": _lic(modules=["syslog"])})
    assert admin.get("/api/backup/devices").status_code == 200  # the device list
    assert admin.post("/api/devices", json={"name": "sw2", "address": "10.0.0.2",
                                            "platform": "cisco_ios"}).status_code == 201
    for r in (admin.post(f"/api/backup/devices/{device['id']}/run"),
              admin.get(f"/api/backup/devices/{device['id']}/config")):
        assert r.status_code == 403 and "Config backups isn't in your licence" in r.json()["detail"]


def test_upgrades_bring_firmware(admin):
    s = admin.post("/api/licence", json={"text": _lic(modules=["upgrades"])}).json()
    assert s["modules"] == ["firmware", "upgrades"]
    assert admin.get("/api/firmware/devices").status_code == 200


def test_the_trial_older_licences_and_internal_ones_have_everything(admin):
    assert admin.get("/api/licence").json()["modules"] == list(licence.MODULES)
    from app.licence_tool import make

    old = licence.parse(make(KEY, "Old", None, None))
    old.pop("modules")  # made before modules existed
    assert licence.licensed_modules(old) == list(licence.MODULES)
    internal = admin.post("/api/licence", json={"text": _lic(kind="internal", days=None, devices=None,
                                                            modules=["syslog"])}).json()
    assert internal["modules"] == list(licence.MODULES)


def test_scheduled_work_follows_the_licence(app, admin, device, settings):
    from app.tools.syslog.receiver import Receiver
    from app.tools.syslog.store import SyslogStore

    admin.post("/api/licence", json={"text": _lic(modules=["firmware"])})
    assert app.state.backup_service.tick() == 0
    assert app.state.circuit_scan.tick() is False
    rx = Receiver(settings, SyslogStore(settings.syslog_dir))
    rx.housekeeping()
    rx.accept(b"<10>not kept", "10.0.0.1")
    assert rx.full == "Syslog isn't in the licence" and rx.counts["dropped_full"] == 1


def test_the_signing_tool_picks_modules(tmp_path, capsys, monkeypatch):
    from cryptography.hazmat.primitives import serialization

    key_file = tmp_path / "k.pem"
    key_file.write_bytes(KEY.private_bytes(serialization.Encoding.PEM,
                                           serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    lic = tmp_path / "a.lic"
    args = ["sign", "--key", str(key_file), "--customer", "Acme", "--expires", "2030-01-31",
            "--devices", "50", "--out", str(lic)]
    assert licence_tool.main([*args, "--modules", "backups,upgrades"]) == 0
    capsys.readouterr()
    assert licence_tool.main(["show", str(lic)]) == 0
    assert "modules      backups, firmware, upgrades" in capsys.readouterr().out
    assert licence_tool.main([*args, "--modules", "backups,fax"]) == 2
    assert licence_tool.main([*args]) == 0  # default: every module
    assert licence.parse(lic.read_text())["modules"] == list(licence.MODULES)


def test_alerts_follow_the_licence(app, admin):
    from app.core.db import utcnow
    from app.tools.firmware_upgrade.models import WorkerStatus
    from tests.test_alerts import CONFIG, Outbox

    app.state.alert_service.mailer = box = Outbox()
    admin.post("/api/licence", json={"text": _lic(modules=["backups"])})
    admin.put("/api/alerts", json=CONFIG)
    with session_scope() as db:
        db.merge(WorkerStatus(id=1, beat_at=utcnow() - datetime.timedelta(minutes=20), pid=1,
                              host="x", started_at=utcnow() - datetime.timedelta(days=1)))
    app.state.alert_service.tick()
    assert not any("upgrade worker" in m["Subject"] for m in box)  # Upgrades isn't licensed


def test_the_shipped_signing_key_loads():
    # The owner's public key ships in every bundle; a broken line would refuse every licence.
    assert len(licence.public_keys()) >= 1
