"""Custom SNMP sensors (tools/monitoring/sensors.py): reading values, rates, states and table
columns; thresholds; the poller making a warning, events and the graph; who may add them;
the Test button; and the wall display, which never shows a row's label or value."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.tools.monitoring import sensors as sn
from app.tools.monitoring.health import CRITICAL, OK, UNKNOWN, WARNING
from tests.test_monitoring import PW, _events, _round, _state, setup  # noqa: F401 - the fixture

UPS = "1.3.6.1.2.1.33.1.2.4.0"
SOURCE = "1.3.6.1.2.1.33.1.4.1.0"
BGP = "1.3.6.1.2.1.15.3.1.2"
ERRS = "1.3.6.1.2.1.2.2.1.14.7"


def _sensor(**kw):
    return {"id": 1, "name": "x", "oid": UPS, "mode": "value", "table": False, "label_oid": "", "unit": "",
            "scale": 1, "warn_above": None, "crit_above": None, "warn_below": None, "crit_below": None,
            "ok_values": "", "warn_values": "", "platform": "", "site": "", "device_ids": [], "enabled": True, **kw}


def test_thresholds_states_and_oids():
    s = _sensor(warn_below=80, crit_below=50)
    assert [sn.judge(s, v) for v in (100, 80, 79, 50, 49, None)] == [OK, OK, WARNING, WARNING, CRITICAL, UNKNOWN]
    s = _sensor(warn_above=27, crit_above=32)
    assert [sn.judge(s, v) for v in (27, 28, 33)] == [OK, WARNING, CRITICAL]
    s = _sensor(mode="state", ok_values="3", warn_values="4")
    assert [sn.judge(s, v) for v in (3, "3", 4, 5, "3.0")] == [OK, OK, WARNING, CRITICAL, OK]
    assert sn.clean_oid(" .1.3.6.1.2.1.1.3.0 ") == "1.3.6.1.2.1.1.3.0"
    for bad in ("sysUpTime.0", "1.3", "1.3.6.1.x", "1.3.6.1.2.1;rm"):
        with pytest.raises(ValueError):
            sn.clean_oid(bad)
    assert sn.codes("2, 3;4") == {"2", "3", "4"}
    assert sn.applies(_sensor(platform="cisco_ios"), 1, "cisco_ios", "HQ")
    assert not sn.applies(_sensor(platform="cisco_ios"), 1, "cisco_asa", "HQ")
    assert sn.applies(_sensor(site="hq"), 1, "x", "HQ") and not sn.applies(_sensor(site="DC1"), 1, "x", "HQ")
    assert sn.applies(_sensor(device_ids=[2]), 2, "x", "") and not sn.applies(_sensor(device_ids=[2]), 1, "x", "")
    assert not sn.applies(_sensor(enabled=False), 1, "x", "")


def test_rates_scale_and_counter_wrap():
    class Client:
        def __init__(self):
            self.v = 0

        async def get(self, t, oids):
            return {o: self.v for o in oids}

    c, prev = Client(), {}
    s = _sensor(mode="rate", oid=ERRS, unit="/s")
    run = lambda now: asyncio.run(sn.read(c, None, [s], now, prev))[0]  # noqa: E731
    c.v = 1000
    first = run(100)
    assert first.value is None and "first read" in first.source and first.status == UNKNOWN
    c.v = 4000
    assert run(400).value == 10.0  # 3000 in 300 s
    c.v = 2**32 - 1000
    run(600)
    c.v = 500  # wrapped at 2^32
    assert run(700).value == 15.0
    c.v = 100  # went back a long way: a restart, not a wrap
    r = run(800)
    assert r.value is None and "went back" in r.source
    s2 = _sensor(oid="1.3.6.1.4.1.9.9.13.1.3.1.3.1", scale=0.1, unit="°C")
    c.v = 235
    assert asyncio.run(sn.read(c, None, [s2], 1, {}))[0].value == 23.5


def _add(admin, **kw):
    r = admin.post("/api/monitoring/sensors", json={"name": "UPS charge", "oid": UPS, "unit": "%",
                                                    "warn_below": 80, "crit_below": 50, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def test_a_sensor_makes_a_warning_an_event_and_a_graph(setup):
    s = setup
    s.settings.monitor_health_seconds = 300
    s.sim.extra["sw1"] = {UPS: 100, BGP + ".192.0.2.1": 6, BGP + ".198.51.100.7": 6}
    _add(s.admin, device_ids=[s.ids["sw1"]])
    _add(s.admin, name="BGP peer", oid=BGP, mode="state", table=True, ok_values="6", warn_below=None,
         crit_below=None, unit="", platform="cisco_ios")
    s.poller.housekeeping()
    _round(s)
    readings = {r["name"]: r for r in s.poller.store.health(s.ids["sw1"])["readings"] if r["kind"] == "sensor"}
    assert readings["UPS charge"]["value"] == 100 and readings["UPS charge"]["status"] == OK
    assert readings["BGP peer 198.51.100.7"]["value"] == 6 and readings["BGP peer 198.51.100.7"]["sensor"] == "BGP peer"
    # sw2 is cisco_ios too but has no BGP: one reading saying so; not the UPS (only sw1)
    sw2 = [r for r in s.poller.store.health(s.ids["sw2"])["readings"] if r["kind"] == "sensor"]
    assert [(r["name"], r["status"]) for r in sw2] == [("BGP peer", UNKNOWN)] and "no rows" in sw2[0]["source"]
    assert _state(s, "sw2")["status"] == "up"  # unknown isn't a problem
    s.sim.extra["sw1"].update({UPS: 45, BGP + ".198.51.100.7": 1})
    _round(s, 300)
    st = _state(s, "sw1")
    assert st["status"] == "warning" and "UPS charge: 45 % (critical)" in st["reason"]
    assert ("health_problem", "BGP peer 198.51.100.7: 1 (critical)") in _events(s, "sw1")
    d = s.admin.get(f"/api/monitoring/devices/{s.ids['sw1']}/health", params={"hours": 1}).json()
    assert d["graph"]["s:UPS charge"][-1]["value"] == 45
    assert next(r for r in d["readings"] if r["name"] == "UPS charge")["kind_label"] == "Sensor"
    # the wall: the sensor's name only, never a row's label (an address) or the value
    key = s.admin.post("/api/displays", json={"name": "NOC"}).json()["key"]
    wall = s.admin.get("/api/display/data", headers={"Authorization": f"Bearer {key}"}).json()["monitoring"]
    hw = next(x for x in wall["hardware"] if x["device"] == "sw1")
    assert hw["problems"] == ["BGP peer critical", "UPS charge critical"]
    assert "198.51" not in str(wall)
    s.sim.extra["sw1"].update({UPS: 100, BGP + ".198.51.100.7": 6})
    _round(s, 300)
    assert _state(s, "sw1")["status"] == "up"
    assert _events(s, "sw1")[-1][0] == "health_ok"


def test_who_may_add_sensors_and_bad_entries(setup):
    s = setup
    a = s.admin
    for name, perms in [("viewer1", {"inventory": "view", "monitoring": "view"}),
                        ("noc1", {"inventory": "view", "monitoring": "manage"})]:
        a.post("/api/users", json={"username": name, "source": "local", "password": PW,
                                   "is_admin": False, "permissions": perms})
    viewer, noc = TestClient(a.app), TestClient(a.app)
    viewer.post("/api/auth/login", json={"username": "viewer1", "password": PW})
    noc.post("/api/auth/login", json={"username": "noc1", "password": PW})
    body = {"name": "UPS charge", "oid": UPS}
    assert viewer.post("/api/monitoring/sensors", json=body).status_code == 403
    x = noc.post("/api/monitoring/sensors", json=body)
    assert x.status_code == 201
    listed = viewer.get("/api/monitoring/sensors").json()
    assert listed["sensors"][0]["devices"] == 3 and listed["examples"]  # every SNMP device
    assert viewer.delete(f"/api/monitoring/sensors/{x.json()['id']}").status_code == 403
    for change, msg in [({"oid": "upsBatteryCharge.0"}, "in numbers"), ({"mode": "guess"}, "value, rate or state"),
                        ({"mode": "state"}, "codes that are fine"), ({"platform": "nokia"}, "platform"),
                        ({"scale": 0}, "scale"), ({"name": ""}, "name")]:
        r = noc.post("/api/monitoring/sensors", json={**body, "name": "y", **change})
        assert r.status_code == 422 and msg in r.text, (change, r.text)
    assert noc.post("/api/monitoring/sensors", json=body).status_code == 409
    r = noc.put(f"/api/monitoring/sensors/{x.json()['id']}", json={**body, "enabled": False, "site": "Branch"})
    assert r.status_code == 200 and not r.json()["enabled"]
    assert noc.delete(f"/api/monitoring/sensors/{x.json()['id']}").json()["ok"]
    acts = {e["action"] for e in a.get("/api/audit").json()}
    assert {"monitoring.sensor_add", "monitoring.sensor_change", "monitoring.sensor_delete"} <= acts


def test_the_test_button_reads_a_device_now(setup):
    s = setup
    s.admin.app.state.snmp_client = s.sim
    s.sim.extra["sw1"] = {SOURCE: 5}
    body = {"name": "UPS on battery", "oid": SOURCE, "mode": "state", "ok_values": "3"}
    r = s.admin.post("/api/monitoring/sensors/test", json={**body, "test_device_id": s.ids["sw1"]}).json()
    assert r["ok"] and r["readings"][0]["value"] == 5 and r["readings"][0]["status"] == CRITICAL
    r = s.admin.post("/api/monitoring/sensors/test", json={**body, "test_device_id": s.ids["sw2"]}).json()
    assert not r["ok"] and "doesn't have this OID" in r["message"]
    s.sim.down.add("sw1")
    r = s.admin.post("/api/monitoring/sensors/test", json={**body, "test_device_id": s.ids["sw1"]}).json()
    assert not r["ok"] and "timed out" in r["message"]


def test_every_example_is_valid(admin):
    for x in sn.EXAMPLES:
        body = {k: v for k, v in x.items() if k not in ("group", "help")}
        r = admin.post("/api/monitoring/sensors", json=body)
        assert r.status_code == 201, (x["name"], r.text)
