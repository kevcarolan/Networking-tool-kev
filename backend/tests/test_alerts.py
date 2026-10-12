"""Email alerts: settings, the test email, and each kind of alert sent once."""

from datetime import timedelta

import pytest
from netmiko.exceptions import NetmikoAuthenticationException

from app.core import appsettings
from app.core.db import session_scope, utcnow
from app.core.models import Device
from app.tools.config_backup.models import BackupState
from app.tools.firmware_upgrade.models import JobEvent, UpgradeJob, WorkerStatus
from tests.test_upgrade_jobs import _create, env  # noqa: F401  (fixture)

CONFIG = {"enabled": True, "smtp_host": "smtp.corp.example", "smtp_port": 587,
          "smtp_security": "starttls", "smtp_user": "netops", "smtp_password": "mail-pass",
          "mail_from": "netops@corp.example", "mail_to": "noc@corp.example, oncall@corp.example",
          "backup_hours": 24, "upgrades": True, "licence": True, "worker": True}


class Outbox(list):
    def __call__(self, cfg, msg):
        self.append(msg)


@pytest.fixture
def outbox(app):
    box = Outbox()
    app.state.alert_service.mailer = box
    return box


def _on(admin, **changes):
    r = admin.put("/api/alerts", json={**CONFIG, **changes})
    assert r.status_code == 200, r.text
    return r.json()


def _tick(app):
    return app.state.alert_service.tick()


def test_settings_are_checked_and_the_password_kept_secret(admin):
    assert admin.put("/api/alerts", json={**CONFIG, "mail_to": "not-an-address"}).status_code == 422
    assert admin.put("/api/alerts", json={**CONFIG, "smtp_host": ""}).status_code == 422
    assert admin.put("/api/alerts", json={**CONFIG, "smtp_security": "ssl3"}).status_code == 422
    view = _on(admin)
    assert view["has_password"] and "mail-pass" not in str(view)
    with session_scope() as db:
        stored = appsettings.stored(db)
        assert "mail-pass" not in str(stored) and stored["alerts_smtp_password_enc"]
    # leaving the password out keeps it; an empty one removes it
    assert _on(admin, smtp_password=None)["has_password"]
    assert not _on(admin, smtp_password="")["has_password"]
    assert admin.get("/api/audit").json()[0]["action"] == "settings.alerts"


def test_test_email(app, admin, outbox):
    _on(admin)
    r = admin.post("/api/alerts/test").json()
    assert r["ok"] and len(outbox) == 1
    msg = outbox[0]
    assert msg["To"] == "noc@corp.example, oncall@corp.example"
    assert msg["Subject"] == "[NetOps Tools] Test email"

    def broken(cfg, m):
        raise ConnectionRefusedError("connection refused")
    app.state.alert_service.mailer = broken
    r = admin.post("/api/alerts/test").json()
    assert not r["ok"] and "connection refused" in r["message"]


def test_nothing_is_sent_while_alerts_are_off(app, admin, outbox, device, fetcher):
    _on(admin, enabled=False)
    fetcher.errors["core-sw1"] = NetmikoAuthenticationException("denied")
    app.state.backup_service.run(device["id"])
    assert _tick(app) == [] and outbox == []


def test_failing_backups_once_past_the_limit(app, admin, outbox, device, fetcher):
    _on(admin)
    admin.put("/api/setup/options", json={"site_name": "Acme Ltd"})
    fetcher.errors["core-sw1"] = NetmikoAuthenticationException("denied")
    app.state.backup_service.run(device["id"])
    assert _tick(app) == []  # a new device: not yet failing for 24 hours
    with session_scope() as db:
        db.get(Device, device["id"]).created_at = utcnow() - timedelta(hours=30)
    [subject] = _tick(app)
    assert subject == "[NetOps Tools · Acme Ltd] 1 device not backed up for over 24 h"
    assert "core-sw1 (HQ): auth, never backed up" in outbox[0].get_content()
    assert _tick(app) == []  # once only
    # a device that worked 2 hours ago isn't reported
    with session_scope() as db:
        db.get(BackupState, device["id"]).last_success = utcnow() - timedelta(hours=2)
    assert _tick(app) == []
    # ... but a new failure, after a good backup 30 hours ago, is
    with session_scope() as db:
        db.get(BackupState, device["id"]).last_success = utcnow() - timedelta(hours=30)
    assert len(_tick(app)) == 1


def test_upgrade_results(app, admin, outbox, env):  # noqa: F811
    old = _create(admin, env)
    with session_scope() as db:  # finished before alerts were switched on: not sent
        j = db.get(UpgradeJob, old["id"])
        j.status, j.started_at = "completed", utcnow() - timedelta(days=1)
        db.add(JobEvent(job_id=j.id, time=utcnow() - timedelta(days=1), message="done",
                        step="", level="info"))
    _on(admin)
    assert _tick(app) == []
    with session_scope() as db:
        j = db.get(UpgradeJob, old["id"])
        j.status = "failed"  # the same job fails again later (e.g. a re-run post-check)
        db.add(JobEvent(job_id=j.id, time=utcnow(), message="Post-check failed: version",
                        step="", level="error"))
    [subject] = _tick(app)
    assert "Dry run FAILED: core-sw1 17.09.04a → 17.12.04" in subject
    assert "Post-check failed: version" in outbox[0].get_content()
    assert _tick(app) == []


def test_licence_and_worker(app, admin, outbox):
    _on(admin)
    with session_scope() as db:
        appsettings.save(db, {"trial_started_at": (utcnow() - timedelta(days=61)).date()
                              .isoformat()}, "test")
        db.merge(WorkerStatus(id=1, beat_at=utcnow() - timedelta(minutes=20), pid=1, host="x",
                              started_at=utcnow() - timedelta(days=1)))
    subjects = _tick(app)
    assert any("The trial ended on" in s for s in subjects)
    assert any("upgrade worker has stopped" in s for s in subjects)
    assert _tick(app) == []


def test_a_failed_send_is_tried_again(app, admin, outbox):
    _on(admin)
    with session_scope() as db:
        appsettings.save(db, {"trial_started_at": (utcnow() - timedelta(days=61)).date()
                              .isoformat()}, "test")

    def down(cfg, m):
        raise TimeoutError("timed out")
    app.state.alert_service.mailer = down
    assert _tick(app) == []
    assert "timed out" in admin.get("/api/alerts").json()["last_error"]
    app.state.alert_service.mailer = outbox
    assert len(_tick(app)) == 1
    assert admin.get("/api/alerts").json()["last_error"] == ""
    assert admin.get("/api/alerts").json()["recent"]


def test_only_admins(client, admin):
    admin.post("/api/users", json={"username": "viewer1", "source": "local",
                                   "password": "a-long-viewer-pass", "permissions": {}})
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"username": "viewer1", "password": "a-long-viewer-pass"})
    assert client.get("/api/alerts").status_code == 403
    assert client.put("/api/alerts", json=CONFIG).status_code == 403
    assert client.post("/api/alerts/test").status_code == 403


def test_real_smtp_conversation():
    """smtp_send against a tiny local SMTP server (no TLS: the 'none' option)."""
    import socket
    import threading

    from app.core import alerts

    received = {}
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def serve():
        conn, _ = srv.accept()
        f = conn.makefile("rwb")

        def say(line):
            f.write(line.encode() + b"\r\n")
            f.flush()
        say("220 test ESMTP")
        data = False
        lines = []
        for raw in f:
            line = raw.decode().rstrip("\r\n")
            if data:
                if line == ".":
                    received["data"] = "\n".join(lines)
                    data = False
                    say("250 queued")
                else:
                    lines.append(line)
                continue
            cmd = line.split(" ")[0].upper()
            if cmd == "EHLO":
                say("250 test")
            elif cmd in ("MAIL", "RCPT"):
                received.setdefault(cmd, []).append(line)
                say("250 ok")
            elif cmd == "DATA":
                data = True
                say("354 go on")
            elif cmd == "QUIT":
                say("221 bye")
                break
        conn.close()

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    cfg = alerts.Config(smtp_host="127.0.0.1", smtp_port=port, smtp_security="none",
                        mail_from="netops@corp.example", mail_to=("noc@corp.example",))

    class S:
        product_name, site_name = "NetOps Tools", ""
    alerts.smtp_send(cfg, alerts.message(cfg, S(), "Hello", "Body text"))
    t.join(5)
    srv.close()
    assert [m.lower() for m in received["MAIL"]] == ["mail from:<netops@corp.example>"]
    assert [m.lower() for m in received["RCPT"]] == ["rcpt to:<noc@corp.example>"]
    assert "Subject: [NetOps Tools] Hello" in received["data"] and "Body text" in received["data"]


# --- who gets what, and syslog -------------------------------------------------------------

def _people(admin, *recipients, **changes):
    return _on(admin, recipients=[{"address": a, "kinds": k} for a, k in recipients], **changes)


def test_each_recipient_chooses_what_they_get(app, admin, outbox):
    view = _people(admin, ("noc@corp.example", ["licence", "worker"]),
                   ("boss@corp.example", ["licence"]))
    assert view["recipients"][1] == {"address": "boss@corp.example", "kinds": ["licence"]}
    with session_scope() as db:
        appsettings.save(db, {"trial_started_at": (utcnow() - timedelta(days=61)).date()
                              .isoformat()}, "test")
        db.merge(WorkerStatus(id=1, beat_at=utcnow() - timedelta(minutes=20), pid=1, host="x",
                              started_at=utcnow() - timedelta(days=1)))
    _tick(app)
    to = {m["Subject"].split("] ", 1)[1][:24]: m["To"] for m in outbox}
    assert any(v == "noc@corp.example, boss@corp.example" for k, v in to.items() if "trial" in k)
    assert any(v == "noc@corp.example" for k, v in to.items() if "worker" in k)


def test_recipients_are_checked(admin):
    bad = [([("noc@corp.example", ["backups"]), ("NOC@corp.example", ["worker"])], "twice"),
           ([("noc@corp.example", ["fax"])], "Unknown alert kind"),
           ([("not-an-address", ["backups"])], "isn't an email address")]
    for people, words in bad:
        r = admin.put("/api/alerts", json={**CONFIG, "recipients": [
            {"address": a, "kinds": k} for a, k in people]})
        assert r.status_code == 422 and words in r.text


def test_settings_saved_before_recipients_chose_still_work(admin):
    view = _on(admin, upgrades=False)  # the old form: one list, switches for everyone
    assert view["recipients"] == [
        {"address": "noc@corp.example", "kinds": ["backups", "licence", "worker"]},
        {"address": "oncall@corp.example", "kinds": ["backups", "licence", "worker"]}]


def _syslog(settings, *messages):
    import time

    from app.tools.syslog.store import Record, SyslogStore

    s = SyslogStore(settings.syslog_dir)
    s.write([Record(time.time() + i * 0.001, src, sev, 23, "", tag, f"{tag}: {text}")
             for i, (src, sev, tag, text) in enumerate(messages)])
    s.close()


def test_critical_syslog_is_gathered_into_one_email(app, admin, outbox, device, settings):
    _people(admin, ("noc@corp.example", ["syslog"]), ("backups@corp.example", ["backups"]))
    _syslog(settings, ("10.0.0.1", 2, "%OLD-2-X", "before alerts were on"))
    assert _tick(app) == []  # switching on doesn't send the history
    _syslog(settings, ("10.0.0.1", 2, "%PLATFORM-2-PS_FAIL", "Power supply 2 failed"),
            ("10.0.0.1", 3, "%LINK-3-UPDOWN", "Gi1/0/1 down"),  # Error: below the level
            ("192.0.2.250", 0, "%TEMP-0-SHUT", "shutting down"))
    [subject] = _tick(app)
    assert "2 syslog messages at Critical or worse (worst: Emergency): 192.0.2.250, core-sw1" in subject
    msg = outbox[-1]
    assert msg["To"] == "noc@corp.example"
    body = msg.get_content()
    assert "core-sw1 (10.0.0.1)  Critical\n    %PLATFORM-2-PS_FAIL: Power supply 2 failed" in body
    assert "Gi1/0/1" not in body and "before alerts" not in body
    _syslog(settings, ("10.0.0.1", 1, "%X-1-Y", "soon after"))
    assert _tick(app) == []  # at most one email every 5 minutes: kept for the next one
    with session_scope() as db:
        from app.core.models import AlertSent

        for row in db.query(AlertSent).filter(AlertSent.key.like("syslog:%")):
            row.sent_at = utcnow() - timedelta(minutes=6)
    [later] = _tick(app)
    assert "1 syslog message at Critical or worse" in later and "soon after" in outbox[-1].get_content()


def test_syslog_level_and_nobody_wanting_it(app, admin, outbox, device, settings):
    _people(admin, ("noc@corp.example", ["backups"]), syslog_level=3)
    _tick(app)
    _syslog(settings, ("10.0.0.1", 3, "%LINK-3-UPDOWN", "Gi1/0/1 down"))
    assert _tick(app) == []  # nobody chose syslog
    _people(admin, ("noc@corp.example", ["syslog"]), syslog_level=3)
    assert _tick(app) == []  # what came before they chose it isn't sent
    _syslog(settings, ("10.0.0.1", 3, "%LINK-3-UPDOWN", "Gi1/0/2 down"))
    [subject] = _tick(app)
    assert "at Error or worse" in subject and "Gi1/0/2" in outbox[-1].get_content()
