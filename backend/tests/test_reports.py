"""The report: on the Activity page, and emailed on a schedule."""

from datetime import datetime

from app.core import reports
from tests.test_alerts import Outbox, _people


def test_the_report_has_a_section_per_tool(app, admin, device, fetcher):
    app.state.backup_service.run(device["id"])
    r = admin.get("/api/reports", params={"days": 7}).json()
    titles = [s["title"] for s in r["sections"]]
    assert titles[:3] == ["Overview", "Config backups", "Config compliance"]
    assert "Firmware" in titles and "Circuits" in titles
    backups = dict((row[0], row[1]) for row in r["sections"][1]["rows"])
    assert backups["Backed up OK"] == 1 and backups["Failing"] == 0
    text = reports.as_text(r | {"since": datetime.fromisoformat(r["since"]),
                                "generated_at": datetime.fromisoformat(r["generated_at"])})
    assert "CONFIG BACKUPS" in text and "Backed up OK: 1" in text


def test_only_admins_see_the_report(client, admin):
    from app.core.auth import VIEWER, User

    client.app.state.authenticator.authenticate = lambda u, p: User(username=u, role=VIEWER)
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"username": "v", "password": "x"})
    assert client.get("/api/reports").status_code == 403


def test_when_the_report_is_due():
    mon_7 = datetime(2026, 10, 12, 7, 0)  # a Monday
    assert reports.due("mon", "07:00", "", mon_7) == "2026-10-12 07:00"
    assert reports.due("mon", "07:00", "2026-10-12 07:00", mon_7) is None  # sent already
    assert reports.due("mon", "07:00", "", datetime(2026, 10, 12, 6, 59)) is None
    assert reports.due("mon", "07:00", "", datetime(2026, 10, 12, 23, 0)) == "2026-10-12 07:00"
    assert reports.due("mon", "07:00", "", datetime(2026, 10, 14, 7, 0)) is None  # missed: next week
    assert reports.due("", "07:00", "", mon_7) is None


def test_the_report_is_emailed(app, admin, device):
    box = Outbox()
    app.state.alert_service.mailer = box
    _people(admin, ("boss@corp.example", ["reports"]), report_day="mon", report_time="07:00")
    r = admin.post("/api/alerts/report-now").json()
    assert r["ok"] and box[-1]["To"] == "boss@corp.example"
    body = box[-1].get_content()
    assert "CONFIG BACKUPS" in body and "Never backed up: 1" in body
    assert "Report: the last 7 days" in box[-1]["Subject"]
    from tests.test_alerts import CONFIG

    assert admin.put("/api/alerts", json={**CONFIG, "report_time": "25:00"}).status_code == 422
