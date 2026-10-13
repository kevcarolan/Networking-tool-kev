"""Config compliance: rules checked against each backed-up config."""

from tests.conftest import SAMPLE_CONFIG

GOOD = SAMPLE_CONFIG.replace("end\n", "ntp server 192.0.2.1\nip ssh version 2\nline vty 0 4\n"
                             " transport input ssh\nend\n")


def _rule(client, **body):
    r = client.post("/api/compliance/rules", json={"name": "r", "lines": "x", **body})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _results(client):
    data = client.get("/api/compliance").json()
    names = {r["id"]: r["name"] for r in data["rules"]}
    return {(x["device"], names[x["rule_id"]]): x for x in data["results"]}


def test_rules_are_checked_on_every_backup(app, admin, device, fetcher):
    fetcher.configs["core-sw1"] = GOOD
    app.state.backup_service.run(device["id"])
    _rule(admin, name="NTP", lines="^ntp server ", regex=True)
    _rule(admin, name="SSH 2", lines="ip ssh version 2", severity="critical")
    _rule(admin, name="No Telnet", kind="must_not", lines="transport input (telnet|all)", regex=True)
    _rule(admin, name="NX-OS only", lines="feature ssh", platforms=["cisco_nxos"])
    res = _results(admin)  # checked straight away, against the stored config
    assert {k[1] for k in res} == {"NTP", "SSH 2", "No Telnet"}  # not the NX-OS rule
    assert all(r["passed"] for r in res.values())

    fetcher.configs["core-sw1"] = GOOD.replace("ip ssh version 2\n", "").replace(
        "transport input ssh", "transport input telnet ssh")
    app.state.backup_service.run(device["id"])
    res = _results(admin)
    assert not res[("core-sw1", "SSH 2")]["passed"] and res[("core-sw1", "SSH 2")]["detail"] == "ip ssh version 2"
    assert res[("core-sw1", "No Telnet")]["detail"] == " transport input telnet ssh"
    assert res[("core-sw1", "NTP")]["passed"] and res[("core-sw1", "SSH 2")]["failing_since"]
    one = admin.get(f"/api/compliance/device/{device['id']}").json()
    assert [x["rule"] for x in one][:2] == ["SSH 2", "No Telnet"]  # failing, critical first
    csv = admin.get("/api/compliance/export.csv").text
    assert "core-sw1,HQ,SSH 2,critical,FAIL" in csv


def test_rules_are_checked_and_scoped(admin, device):
    assert admin.post("/api/compliance/rules", json={"name": "x", "lines": "(", "regex": True}).status_code == 422
    assert admin.post("/api/compliance/rules", json={"name": "x", "lines": " \n "}).status_code == 422
    assert admin.post("/api/compliance/rules", json={"name": "x", "lines": "a", "kind": "maybe"}).status_code == 422
    assert admin.post("/api/compliance/rules", json={"name": "x", "lines": "a", "platforms": ["nope"]}).status_code == 422
    added = admin.post("/api/compliance/examples").json()["added"]
    assert "No Telnet" in added and admin.post("/api/compliance/examples").json()["added"] == []


def test_config_lines_only_for_those_who_may_read_configs(app, admin, device, fetcher):
    from fastapi.testclient import TestClient

    from tests.test_users import _add as add_user
    from tests.test_users import _login

    fetcher.configs["core-sw1"] = GOOD.replace("ntp server 192.0.2.1\n", "snmp-server community public RO\n")
    app.state.backup_service.run(device["id"])
    _rule(admin, name="No public", kind="must_not", lines=r"community public", regex=True)
    add_user(admin, "viewer1", preset="viewer")
    with TestClient(app) as c:
        _login(c, "viewer1")
        [r] = c.get("/api/compliance").json()["results"]
        assert r["passed"] is False and r["detail"] is None
        assert "community" not in c.get("/api/compliance/export.csv").text
        assert c.post("/api/compliance/rules", json={"name": "x", "lines": "y"}).status_code == 403


def test_compliance_alerts(app, admin, device, fetcher):
    from tests.test_alerts import Outbox, _people, _tick

    box = Outbox()
    app.state.alert_service.mailer = box
    _people(admin, ("noc@corp.example", ["compliance"]))
    app.state.backup_service.run(device["id"])
    _rule(admin, name="SSH 2", lines="ip ssh version 2", severity="critical")
    [subject] = _tick(app)
    assert "1 new compliance failure (1 critical): core-sw1" in subject
    assert "core-sw1 (HQ): SSH 2 (critical)" in box[-1].get_content()
    app.state.backup_service.run(device["id"])  # still failing: not again
    assert _tick(app) == []
