"""The wall display: screens and their links, the read-only feed, and what it shows."""

import json
from datetime import timedelta

from netmiko.exceptions import NetmikoAuthenticationException

from app.core.db import session_scope, utcnow
from app.core.models import DisplayScreen
from app.tools.firmware_upgrade.models import RUNNING, UpgradeJob
from tests.test_circuits import ROWS, make_xlsx
from tests.test_upgrade_jobs import _create, env  # noqa: F401  (fixture)


def _screen(admin, name="NOC wall 1"):
    r = admin.post("/api/displays", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()


def _feed(client, key):
    return client.get("/api/display/data", headers={"Authorization": f"Bearer {key}"})


def test_a_screen_gets_a_link_once(admin):
    s = _screen(admin)
    assert len(s["key"]) >= 40
    listing = admin.get("/api/displays").json()
    assert listing["port"] == 8443 and [x["name"] for x in listing["screens"]] == ["NOC wall 1"]
    assert "key" not in str(listing["screens"])  # only a hash is kept
    assert admin.get("/api/audit").json()[0]["action"] == "display.add"


def test_the_feed_needs_a_valid_key(client, admin):
    s = _screen(admin)
    client.post("/api/auth/logout")  # the screen never signs in
    assert client.get("/api/display/data").status_code == 401
    assert _feed(client, "not-the-key").status_code == 401
    r = _feed(client, s["key"])
    assert r.status_code == 200 and r.json()["screen"] == "NOC wall 1"
    with session_scope() as db:
        seen = db.query(DisplayScreen).one()
        assert seen.last_seen_at and seen.last_seen_from


def test_guessing_keys_is_throttled(client, admin):
    s = _screen(admin)
    for _ in range(5):
        _feed(client, "guess")
    assert _feed(client, s["key"]).status_code == 429


def test_removing_a_screen_stops_its_link(admin):
    s = _screen(admin)
    assert admin.delete(f"/api/displays/{s['id']}").status_code == 204
    assert _feed(admin, s["key"]).status_code == 401
    assert admin.get("/api/audit").json()[0]["action"] == "display.remove"


def test_only_admins_manage_screens(client, admin):
    admin.post("/api/users", json={"username": "viewer1", "source": "local",
                                   "password": "a-long-viewer-pass", "permissions": {}})
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"username": "viewer1", "password": "a-long-viewer-pass"})
    assert client.get("/api/displays").status_code == 403
    assert client.post("/api/displays", json={"name": "x"}).status_code == 403


def test_overview_counts_and_failing_devices(app, admin, device, fetcher):
    admin.post("/api/devices", json={"name": "edge-sw2", "address": "10.9.9.9",
                                     "platform": "cisco_ios", "site": "Branch"})
    fetcher.errors["core-sw1"] = NetmikoAuthenticationException("denied")
    app.state.backup_service.run(device["id"])
    s = _screen(admin)
    d = _feed(admin, s["key"]).json()
    assert d["backups"] == {"total": 2, "ok": 0, "failing": 1, "never": 1, "disabled": 0}
    assert d["attention"] == [{"device": "core-sw1", "site": "HQ", "reason": "login failed",
                               "since": None, "failures": 1}]
    assert d["firmware"]["total"] == 2 and d["firmware"]["percent"] is None
    assert {x["site"]: x["failing"] for x in d["sites"]} == {"Branch": 0, "HQ": 1}
    assert d["server"]["licence"]["mode"] == "trial" and d["product_name"] == "NetCairn"
    # Names and statuses only: no addresses, configs or credentials
    text = str(d)
    assert "10.0.0.1" not in text and "10.9.9.9" not in text and "s3cret" not in text


def test_upgrades_under_way_with_their_circuits_and_coming_up(admin, env):  # noqa: F811
    rows = [[*r[:15], "core-sw1", *r[16:]] for r in ROWS]
    imp = admin.put("/api/circuits/imports/upload", params={"filename": "c.xlsx"},
                    content=make_xlsx(rows=rows)).json()
    admin.post(f"/api/circuits/imports/{imp['id']}/commit")
    running = _create(admin, env)
    with session_scope() as db:
        job = db.get(UpgradeJob, running["id"])
        job.status, job.started_at, job.step_index = RUNNING, utcnow(), 2
        job.plan = json.dumps({"mode": "upgrade", "steps": [
            {"id": f"s{i}", "kind": k, "label": label} for i, (k, label) in enumerate(
                [("backup", "Back up the config"), ("copy", "Copy the image"),
                 ("install", "Install and reload"), ("postcheck", "Post-checks")])]})
    other = admin.post("/api/devices", json={"name": "acc-sw2", "address": "10.0.0.2",
                                             "platform": "cisco_ios", "site": "HQ"}).json()
    soon = utcnow() + timedelta(minutes=30)
    r = admin.post("/api/firmware/jobs", json={
        "device_id": other["id"], "image_id": env["image"]["id"],
        "planned_start": soon.isoformat(), "planned_end": (soon + timedelta(hours=1)).isoformat()})
    assert r.status_code == 201, r.text
    s = _screen(admin)
    d = _feed(admin, s["key"]).json()
    [j] = d["upgrades"]["under_way"]
    assert j["devices"] == ["core-sw1"] and j["status"] == "running" and not j["live"]
    assert j["step"] == 2 and j["steps"] == 4 and j["step_label"] == "Install and reload"
    assert j["from_version"] == "17.09.04a" and j["target_version"] == "17.12.04"
    assert j["circuits"]["count"] == 5
    assert sum(g["count"] for g in j["circuits"]["groups"]) == 5
    assert all(set(g) == {"service", "vlan", "count"} for g in j["circuits"]["groups"])
    assert [p["devices"] for p in d["upgrades"]["coming_up"]] == [["acc-sw2"]]
    assert {x["site"]: x["upgrading"] for x in d["sites"]}["HQ"] == 1


def test_the_display_page_is_served(client):
    r = client.get("/display/")
    assert r.status_code == 200 and "display.js" in r.text
    assert client.get("/display/display.js").status_code == 200


def test_each_screen_chooses_its_pages(admin):
    key = _screen(admin)["key"]
    screen = admin.get("/api/displays").json()["screens"][0]
    assert screen["pages"] == ["overview", "monitoring", "upgrades", "sites", "network"]  # all by default
    r = admin.put(f"/api/displays/{screen['id']}", json={"name": "NOC wall 1", "pages": ["network", "sites"]})
    assert r.status_code == 200 and r.json()["pages"] == ["sites", "network"]
    assert _feed(admin, key).json()["pages"] == ["sites", "network"]
    assert admin.put(f"/api/displays/{screen['id']}", json={"name": "x", "pages": ["nope"]}).status_code == 422


def test_compliance_changes_syslog_circuits_and_sites_without_addresses(app, admin, device, fetcher, settings):
    from tests.test_alerts import _syslog
    from tests.test_circuits import _upload

    key = _screen(admin)["key"]
    admin.post("/api/sites", json={"values": {"name": "Head office", "code": "HQ"}})
    app.state.backup_service.run(device["id"])
    admin.post("/api/compliance/rules", json={"name": "SSH 2", "lines": "ip ssh version 2", "severity": "critical"})
    from tests.conftest import SAMPLE_CONFIG

    fetcher.configs["core-sw1"] = SAMPLE_CONFIG.format(name="core-sw1", address="10.0.0.1").replace(
        "end\n", "ntp server 192.0.2.1\nend\n")
    app.state.backup_service.run(device["id"])
    _syslog(settings, ("10.0.0.1", 2, "%PLATFORM-2-PS_FAIL", "Power supply 2 failed at 10.0.0.1"),
            ("192.0.2.250", 3, "%LINK-3-UPDOWN", "Gi1/0/1 down"))
    imp = _upload(admin, make_xlsx()).json()
    admin.post(f"/api/circuits/imports/{imp['id']}/commit")
    d = _feed(admin, key).json()
    assert d["compliance"]["failing"] == 1 and d["compliance"]["top"][0] == {"rule": "SSH 2", "devices": 1, "critical": True}
    assert d["changes"]["count"] == 1 and d["changes"]["rows"][0]["device"] == "core-sw1"
    assert d["syslog"]["counts"][2] == 1 and d["syslog"]["counts"][3] == 1
    latest = {m["type"]: m for m in d["syslog"]["latest"]}
    assert latest["%PLATFORM-2-PS_FAIL"]["device"] == "core-sw1"
    assert latest["%LINK-3-UPDOWN"]["device"] == "a sender not in the inventory"
    assert d["circuits"]["total"] == 5
    hq = next(s for s in d["sites"] if s["site"] == "Head office")
    assert hq["listed"] and hq["devices"] == 1 and hq["compliance"] == 1
    text = json.dumps(d)
    assert "10.0.0.1" not in text and "192.0.2.250" not in text and "Power supply" not in text
    assert "ntp server" not in text
