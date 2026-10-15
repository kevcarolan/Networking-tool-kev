"""SNMP-only devices (UPS cards, PDUs, probes): added without a credential, never reached
over SSH (no backups, version checks, port scans or upgrades), monitored with ping, SNMP and
the custom sensors for their type."""

import asyncio
from types import SimpleNamespace

from app.core.platforms import PLATFORMS, SNMP_ONLY, uses_ssh
from app.demo.monitor import SimMonitor
from app.tools.monitoring.poller import Poller
from app.tools.monitoring.store import MonitorStore
from tests.test_monitoring import Clock, _profile

UPS_CHARGE = "1.3.6.1.2.1.33.1.2.4.0"


def _ups(admin, **kw):
    r = admin.post("/api/devices", json={"name": "hq-ups1", "address": "10.0.9.1", "platform": "snmp_ups",
                                         "site": "HQ", **kw})
    assert r.status_code == 201, r.text
    return r.json()


def test_the_types():
    assert SNMP_ONLY == {"snmp_ups", "snmp_pdu", "snmp_env", "snmp_other"}
    assert not uses_ssh("snmp_pdu") and uses_ssh("cisco_ios")
    assert all(not PLATFORMS[k].ssh and PLATFORMS[k].vendor == "SNMP only" for k in SNMP_ONLY)


def test_no_backups_version_checks_or_upgrades(admin, credential, fetcher):
    ups = _ups(admin)
    assert ups["credential_id"] is None
    platforms = {p["key"]: p for p in admin.get("/api/platforms").json()}
    assert platforms["snmp_ups"]["ssh"] is False and platforms["cisco_ios"]["ssh"] is True
    sw = admin.post("/api/devices", json={"name": "sw1", "address": "10.0.0.1", "platform": "cisco_ios",
                                          "credential_id": credential["id"]}).json()
    rows = {r["device"]["name"]: r for r in admin.get("/api/backup/devices").json()}
    assert rows["hq-ups1"]["backup"] is None and rows["sw1"]["backup"]["status"] == "never"
    assert admin.get(f"/api/backup/devices/{ups['id']}").json()["backup"] is None
    assert admin.get("/api/backup/summary").json()["total"] == 1
    r = admin.post(f"/api/backup/devices/{ups['id']}/run")
    assert r.status_code == 422 and "SNMP-only" in r.text
    assert admin.put(f"/api/backup/devices/{ups['id']}/settings",
                     json={"frequency_minutes": 60, "enabled": True}).status_code == 422
    sched = admin.app.state.backup_service
    assert sched.due_device_ids() == [sw["id"]]
    assert sched.run(ups["id"]) is None
    r = admin.post(f"/api/firmware/devices/{ups['id']}/check")
    assert r.status_code == 422 and "SNMP-only" in r.text
    assert admin.post("/api/firmware/check-all").json()["queued"] == 1
    fw = admin.app.state.firmware_service
    assert ups["id"] not in fw.due_device_ids() and fw.check(ups["id"]) is None
    assert ups["id"] not in {r["device"]["id"] for r in admin.get("/api/firmware/devices").json()}
    img = admin.put("/api/firmware/images/upload", params={
        "filename": "x.bin", "platform": "cisco_ios", "version": "17.9.5"}, content=b"x" * 2000).json()
    r = admin.post("/api/firmware/jobs", json={"device_id": ups["id"], "image_id": img["id"]})
    assert r.status_code == 422 and "SNMP-only" in r.text
    # the report doesn't count it as never backed up
    rep = admin.get("/api/reports", params={"days": 7}).json()
    backups = {row[0]: row for s in rep["sections"] for row in s["rows"]}
    assert backups["Never backed up"][1] == 1
    # the inventory row is a UPS, its vendor left to the row
    inv = next(x for x in admin.get("/api/inventory/assets").json() if x["values"]["name"] == "hq-ups1")
    assert inv["values"]["type"] == "UPS" and not inv["auto"].get("vendor")
    assert "hq-ups1" not in fetcher.calls


def test_a_device_changed_to_snmp_only_loses_its_schedule(admin, credential):
    sw = admin.post("/api/devices", json={"name": "probe1", "address": "10.0.0.7", "platform": "cisco_ios",
                                          "credential_id": credential["id"]}).json()
    assert admin.get(f"/api/backup/devices/{sw['id']}").json()["backup"]
    r = admin.put(f"/api/devices/{sw['id']}", json={"name": "probe1", "address": "10.0.0.7",
                                                    "platform": "snmp_env", "credential_id": None})
    assert r.status_code == 200
    assert admin.get(f"/api/backup/devices/{sw['id']}").json()["backup"] is None
    assert admin.app.state.backup_service.due_device_ids() == []


def test_monitored_with_ping_snmp_and_the_sensors_for_its_type(admin, settings):
    ups = _ups(admin)
    _profile(admin)
    admin.post("/api/monitoring/sensors", json={"name": "UPS battery charge", "oid": UPS_CHARGE, "unit": "%",
                                                "warn_below": 80, "crit_below": 50, "platform": "snmp_ups"})
    clock = Clock()
    sim = SimMonitor(SimpleNamespace(devices={}), {"hq-ups1": "10.0.9.1"}, clock=clock)
    sim.others["hq-ups1"] = SimpleNamespace(up=True, platform="snmp_ups", version="")
    sim.extra["hq-ups1"] = lambda: {UPS_CHARGE: 45}
    poller = Poller(settings, MonitorStore(settings.monitor_dir), admin.app.state.cipher,
                    snmp=sim, pinger=sim.ping, clock=clock)
    poller.housekeeping()
    clock.t += 60
    asyncio.run(poller.run_round())
    st = poller.store.states()[ups["id"]]
    assert st["status"] == "warning" and "UPS battery charge: 45 % (critical)" in st["reason"]
    rows = {r["name"]: r for r in admin.get("/api/monitoring/devices").json()["devices"]}
    assert rows["hq-ups1"]["snmp"] is True
