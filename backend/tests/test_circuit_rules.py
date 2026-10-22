"""Rules per type of circuit: VLAN checks, and emails when circuits move, go missing or are
on the wrong VLAN."""

import pytest

from app.tools.circuits.rules import parse_vlans
from tests.test_alerts import _people, _tick, outbox  # noqa: F401 - fixture
from tests.test_circuit_live import _scan, switch  # noqa: F401 - fixture
from tests.test_circuits import _upload, make_xlsx

BASE = "/api/circuits/rules"


def _rule(client, **body):
    return client.post(BASE, json=body)


@pytest.fixture
def listed(admin, switch):  # noqa: F811
    imp = _upload(admin, make_xlsx()).json()
    admin.post(f"/api/circuits/imports/{imp['id']}/commit")


def test_parse_vlans():
    assert parse_vlans("10, 20-22 users") == {"10", "20", "21", "22", "users"}
    assert parse_vlans("") == set() and parse_vlans("010") == {"10"}
    for bad in ("30-20", "a/b", "1-9999"):
        with pytest.raises(ValueError):
            parse_vlans(bad)


def test_add_change_delete_and_checks(admin):
    r = _rule(admin, field="device_type", value="CCTV camera", email_moved=True)
    assert r.status_code == 201 and r.json()["label"] == "Device type CCTV camera"
    assert _rule(admin, field="device_type", value="cctv CAMERA").status_code == 409
    assert _rule(admin, field="service", value="CCTV camera").status_code == 201  # another column
    assert _rule(admin, vlans="10").status_code == 422  # VLANs without the check
    assert _rule(admin, check_vlan=True, vlans="10/2").status_code == 422
    assert _rule(admin, email_vlan=True).status_code == 422
    assert _rule(admin, field="model", value="x").status_code == 422
    every = _rule(admin, value="", check_vlan=True).json()
    assert every["label"] == "Every circuit"
    assert _rule(admin, field="service", value="").status_code == 409  # one rule for every circuit
    rid = r.json()["id"]
    changed = admin.put(f"{BASE}/{rid}", json={"field": "device_type", "value": "CCTV camera",
                                               "email_missing": True, "missing_hours": 48})
    assert changed.json()["email_missing"] and not changed.json()["email_moved"]
    assert admin.delete(f"{BASE}/{rid}").status_code == 204
    assert admin.delete(f"{BASE}/{rid}").status_code == 404
    assert len(admin.get(BASE).json()["rules"]) == 2


def test_vlan_check_shows_on_the_list(app, admin, listed, fw_collector):
    _rule(admin, field="service", value="Intercom", check_vlan=True, vlans="40-41")
    _rule(admin, field="device_type", value="DoorCtl 400", check_vlan=True)  # the row's VLAN column
    _scan(app, fw_collector)
    rows = {c["device_name"]: c for c in admin.get("/api/circuits").json()["circuits"]}
    assert rows["IC-SITEA-GF-04"]["rule_problems"] == ["On VLAN 36, expected 40, 41"]
    assert rows["IC-SITEA-GATE-01"]["rule_problems"] == []  # not seen: nothing to check
    assert rows["DC-SITEA-GF-03"]["rule_problems"] == []  # on VLAN 34, as listed
    assert rows["BMS_CP03"]["rule_problems"] == []  # no rule
    data = admin.get(BASE).json()
    by = {r["value"]: r for r in data["rules"]}
    assert by["Intercom"]["circuits"] == 2 and by["Intercom"]["wrong_vlan"] == 1
    assert by["DoorCtl 400"]["circuits"] == 2 and by["DoorCtl 400"]["wrong_vlan"] == 0
    assert "Intercom" in data["types"]["service"] and "DoorCtl 400" in data["types"]["device_type"]


def test_moved_missing_and_vlan_are_emailed_once(app, admin, listed, fw_collector, outbox):  # noqa: F811
    _people(admin, ("noc@corp.example", ["circuits"]))
    assert not any("Circuits" in s for s in _tick(app))  # no scan yet
    _rule(admin, field="device_type", value="DoorCtl 400", email_moved=True)
    _rule(admin, field="service", value="Intercom", email_missing=True, missing_hours=1,
          check_vlan=True, vlans="40", email_vlan=True)
    _scan(app, fw_collector)
    sent = [s for s in _tick(app) if "Circuits:" in s]
    assert len(sent) == 1
    assert "1 moved" in sent[0] and "1 not seen" in sent[0] and "1 on the wrong VLAN" in sent[0]
    body = outbox[-1].get_content()
    assert "DC-SITEA-GF-02 (DoorCtl 400): MOVED to SITEA-ACC-SW01 Gi2/0/14" in body
    assert "IC-SITEA-GATE-01" in body and "never seen" in body
    assert "IC-SITEA-GF-04" in body and "expected 40" in body
    assert "BMS_CP03" not in body and "DC-SITEA-GF-03" not in body
    assert not any("Circuits" in s for s in _tick(app))  # once per scan
    _scan(app, fw_collector)
    assert not any("Circuits" in s for s in _tick(app))  # the same problems: not again

    # A new rule is checked against the last scan straight away
    _rule(admin, field="service", value="BMS", check_vlan=True, vlans="70", email_vlan=True)
    sent = [s for s in _tick(app) if "Circuits:" in s]
    assert sent == [sent[0]] and "1 on the wrong VLAN" in sent[0]
    assert "BMS_CP03" in outbox[-1].get_content()


def test_missing_waits_for_the_hours(app, admin, listed, fw_collector, outbox):  # noqa: F811
    _people(admin, ("noc@corp.example", ["circuits"]))
    _scan(app, fw_collector)
    from tests import firmware_samples as s

    fw_collector.by_command["SITEA-ACC-SW01"]["show mac address-table"] = \
        s.IOS_MAC_TABLE.replace("0200.5e10.c02f", "0200.5e10.ffff")
    app.state.circuit_scan.scan("manual:test")  # DC-SITEA-GF-03 just went
    _rule(admin, field="device_type", value="DoorCtl 400", email_missing=True, missing_hours=24)
    assert not any("Circuits" in s for s in _tick(app))  # seen minutes ago


def test_viewers_read_managers_change(client, app, admin):
    from app.core.auth import VIEWER, User

    _rule(admin, value="CCTV", email_moved=True)
    app.state.authenticator.authenticate = lambda u, p: User(username=u, role=VIEWER)
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"username": "v", "password": "x"})
    assert len(client.get(BASE).json()["rules"]) == 1
    assert _rule(client, value="X").status_code == 403
