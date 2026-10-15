"""Stacks, HA pairs, optics and PoE (tools/monitoring/health.py): the readers, the problems
they make, failovers as events and alerts, and optics on ports that are down."""

import asyncio
import datetime as dt

from app.tools.monitoring import health as hw
from app.tools.monitoring.poller import failovers
from tests.test_monitoring import _events, _round, _state, setup  # noqa: F401 - the fixture

STACK = "1.3.6.1.4.1.9.9.500.1.2.1.1"
ENT_NAME = "1.3.6.1.2.1.47.1.1.1.1.7"
SENSOR, THRESHOLD = "1.3.6.1.4.1.9.9.91.1.1.1.1", "1.3.6.1.4.1.9.9.91.1.2.1.1"
ASA = "1.3.6.1.4.1.9.9.147.1.2.1.1.1"


class Table:
    """A device answering only these OIDs (GET and walk)."""

    def __init__(self, values: dict):
        self.values = values

    async def get(self, t, oids):
        return {o: self.values.get(o) for o in oids}

    async def walk(self, t, oid, max_rows=2000):
        rows = [(o, v) for o, v in self.values.items() if o.startswith(oid + ".")]
        return sorted(rows, key=lambda r: [int(x) for x in r[0].split(".")])


def _stack(active=1, states=(4, 4)):
    v = {}
    for n, st in enumerate(states, 1):
        k = 1000 * n
        v |= {f"{STACK}.1.{k}": n, f"{STACK}.3.{k}": 1 if n == active else 2, f"{STACK}.6.{k}": st}
    return v


def _read(probe, values):
    return asyncio.run(hw.PROBES[probe](Table(values), None))


def test_stack_members_and_their_state():
    r = _read("cisco_stack", _stack())
    assert [(x.name, x.unit, x.status) for x in r] == [("Switch 1", "active", "ok"), ("Switch 2", "member", "ok")]
    r = _read("cisco_stack", _stack(states=(4, 11)))
    assert hw.problems(r) == {"stack:switch 2": "Stack member Switch 2: removed from the stack"}
    r = _read("cisco_stack", _stack(states=(4, 6)))
    assert r[1].status == hw.CRITICAL and "version mismatch" in r[1].note
    assert _read("cisco_stack", {f"{STACK}.6.1000": 4}) == []  # a stack of one isn't shown


def test_ha_pairs():
    r = _read("asa_failover", {f"{ASA}.3.6": 9, f"{ASA}.3.7": 10, f"{ASA}.4.6": "Active unit"})
    assert [(x.name, x.unit, x.status) for x in r] == [("Primary unit", "active", "ok"),
                                                       ("Secondary unit", "standby", "ok")]
    r = _read("asa_failover", {f"{ASA}.3.6": 9, f"{ASA}.3.7": 3, f"{ASA}.4.7": "Failed"})
    assert hw.problems(r) == {"ha:secondary unit": "HA Secondary unit: failover peer down (Failed)"}
    assert _read("asa_failover", {f"{ASA}.3.6": 3, f"{ASA}.3.7": 3, f"{ASA}.4.6": "Failover Off"}) == []
    forti = "1.3.6.1.4.1.12356.101.13"
    pair = {f"{forti}.1.1.0": 3, f"{forti}.2.1.1.2.1": "FGT1", f"{forti}.2.1.1.2.2": "FGT2",
            f"{forti}.2.1.1.11.1": "fw-a", f"{forti}.2.1.1.11.2": "fw-b", f"{forti}.2.1.1.12.1": 1,
            f"{forti}.2.1.1.12.2": 0, f"{forti}.2.1.1.16.1": "FGT1", f"{forti}.2.1.1.16.2": "FGT1"}
    r = _read("fortinet_ha", pair)
    assert [(x.name, x.unit, x.status) for x in r] == [("fw-a", "primary", "ok"), ("fw-b", "secondary", "warning")]
    one = {k: v for k, v in pair.items() if not k.endswith(".2")}
    assert hw.problems(_read("fortinet_ha", one)) == {"ha:ha peer": "HA HA peer: the cluster has only one member"}
    assert _read("fortinet_ha", {f"{forti}.1.1.0": 1}) == []  # standalone
    pan = "1.3.6.1.4.1.25461.2.1.2.1"
    r = _read("panos_ha", {f"{pan}.13.0": "active-passive", f"{pan}.11.0": "active", f"{pan}.12.0": "unknown"})
    assert [(x.name, x.unit, x.status) for x in r] == [("This unit", "active", "ok"), ("HA peer", "unknown", "critical")]
    assert _read("panos_ha", {f"{pan}.13.0": "disabled"}) == []


def test_optics_judged_by_their_own_thresholds_and_poe():
    v = {f"{SENSOR}.1.7": 14, f"{SENSOR}.2.7": 9, f"{SENSOR}.3.7": 1, f"{SENSOR}.4.7": -151, f"{SENSOR}.5.7": 1,
         f"{ENT_NAME}.7": "Te1/1/1 Receive Power Sensor",
         f"{THRESHOLD}.2.7.1": 10, f"{THRESHOLD}.5.7.1": 1, f"{THRESHOLD}.2.7.2": 20, f"{THRESHOLD}.5.7.2": 2}
    r = _read("cisco_entity_sensor", v)
    assert (r[0].kind, r[0].name, r[0].value, r[0].unit, r[0].status) == ("optic", "Te1/1/1 receive", -15.1, "dBm", "warning")
    r = _read("cisco_entity_sensor", v | {f"{THRESHOLD}.5.7.2": 1})
    assert r[0].status == "critical" and "alarm" in r[0].note
    assert _read("entity_sensor", {"1.3.6.1.2.1.99.1.1.1.1.7": 14}) == []  # only Cisco's copy has dBm
    poe = "1.3.6.1.2.1.105.1.3.1.1"
    r = _read("poe", {f"{poe}.2.1": 740, f"{poe}.3.1": 1, f"{poe}.4.1": 690, f"{poe}.5.1": 0})
    assert (r[0].value, r[0].unit, r[0].status, r[0].note) == (690, "W of 740 W", "warning", "93% of the budget used")
    r = _read("poe", {f"{poe}.2.1": 740, f"{poe}.3.1": 3, f"{poe}.4.1": 0, f"{poe}.5.1": 80})
    assert r[0].status == "critical" and r[0].note == "power supply faulty"
    assert "poe" in hw.GENERIC and "cisco_stack" in hw.probes_for("cisco_ios")


def test_failover_detection():
    before = {"stack:Switch 1": "active", "stack:Switch 2": "member"}
    assert failovers(before, before) == []
    ev = failovers(before, {"stack:Switch 1": "member", "stack:Switch 2": "active"})
    assert ev == [{"kind": "failover", "detail": "Stack failover: Switch 2 is now active (was Switch 1)"}]
    assert failovers({"ha:Primary unit": "active"}, {"ha:Primary unit": "standby", "ha:Secondary unit": "active"})
    assert failovers({}, {"ha:Primary unit": "active"}) == []  # the first read


def test_the_poller_reports_a_failover_and_ignores_optics_on_down_ports(setup):
    s = setup
    s.settings.monitor_health_seconds = 300
    s.sim.extra["sw1"] = _stack(active=1)
    _round(s)
    assert [r for r in s.poller.store.health(s.ids["sw1"])["readings"] if r["kind"] == "stack"]
    s.sim.extra["sw1"] = _stack(active=2)
    _round(s, 300)
    assert ("failover", "Stack failover: Switch 2 is now active (was Switch 1)") in _events(s, "sw1")
    labels = {e["kind"]: e["kind_label"] for e in s.admin.get(f"/api/monitoring/devices/{s.ids['sw1']}").json()["events"]}
    assert labels["failover"] == "Failover"
    # an optic warning on a port that is down isn't a problem; on a port that is up it is
    from app.demo.monitor import ports_of

    ports = [p for p in ports_of("sw2", "cisco_ios") if p.kind == "access"]
    up = next(p.name for p in ports if p.up)
    down = next(p.name for p in ports if not p.up)
    optic = {}
    for k, port in ((7, up), (8, down)):
        optic |= {f"{SENSOR}.1.{k}": 14, f"{SENSOR}.2.{k}": 9, f"{SENSOR}.3.{k}": 1, f"{SENSOR}.4.{k}": -300,
                  f"{SENSOR}.5.{k}": 1, f"{ENT_NAME}.{k}": f"{port} Receive Power Sensor",
                  f"{THRESHOLD}.2.{k}.1": 20, f"{THRESHOLD}.5.{k}.1": 1}
    s.sim.extra["sw2"] = optic
    s.poller.health[s.ids["sw2"]]["discovered"] = 0  # try every reader again (the daily retry)
    _round(s, 300)
    optics = {r["name"].split()[0]: r for r in s.poller.store.health(s.ids["sw2"])["readings"] if r["kind"] == "optic"}
    assert optics[up]["status"] == "critical"
    assert optics[down]["status"] == "unknown" and optics[down]["note"] == "port down"
    assert "Optic" in _state(s, "sw2")["reason"]


def test_failover_alert(setup):
    s = setup
    from app.core import alerts, appsettings
    from app.core.db import session_scope

    box = []
    s.admin.app.state.alert_service.mailer = lambda cfg, msg: box.append(msg)
    s.admin.put("/api/alerts", json={"enabled": True, "smtp_host": "smtp.corp.example", "mail_from": "noc@corp.example",
                                     "recipients": [{"address": "oncall@corp.example", "kinds": ["monitoring"]}]})
    with session_scope() as db:
        appsettings.save(db, {alerts.ENABLED_AT: (dt.datetime.now(dt.UTC).replace(tzinfo=None)
                                                  - dt.timedelta(hours=1, minutes=5)).isoformat()}, "t")
    s.settings.monitor_health_seconds = 300
    s.sim.extra["sw3"] = _stack(active=1)
    _round(s)
    s.sim.extra["sw3"] = _stack(active=2)
    _round(s, 300)
    s.admin.app.state.alert_service.tick()
    assert box and "failover: sw3" in box[0]["Subject"] and "FAILOVER" in box[0].get_content()
