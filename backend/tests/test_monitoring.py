"""Monitoring (tools/monitoring/): the poller's up/warning/down logic, restarts and events,
maintenance from the calendar, the store, SNMP profiles and who may change what, the API,
the setup help, and a real SNMP read against a local test agent."""

import asyncio
import datetime as dt
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.platforms import PLATFORMS
from app.demo.monitor import SimMonitor
from app.tools.monitoring import howto
from app.tools.monitoring.poller import Poller
from app.tools.monitoring.snmp import SYS_UPTIME, SnmpTarget
from app.tools.monitoring.store import MonitorStore

PW = "a-long-password-123"


class Clock:
    def __init__(self, t: float | None = None):
        self.t = float(int(time.time()) - 3600) if t is None else t

    def __call__(self) -> float:
        return self.t


def _devices(admin, credential, n=3):
    ids = {}
    for i in range(1, n + 1):
        r = admin.post("/api/devices", json={
            "name": f"sw{i}", "address": f"10.0.0.{i}", "platform": "cisco_ios",
            "site": "HQ" if i < 3 else "Branch", "credential_id": credential["id"]})
        assert r.status_code == 201, r.text
        ids[f"sw{i}"] = r.json()["id"]
    return ids


def _profile(admin, **extra):
    body = {"name": "switches-v3", "version": "3", "username": "netops-mon", "level": "authPriv",
            "auth_protocol": "SHA", "auth_key": "auth-pass-1", "priv_protocol": "AES",
            "priv_key": "priv-pass-1", "is_default": True, **extra}
    r = admin.post("/api/monitoring/profiles", json=body)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def setup(admin, credential, settings):
    ids = _devices(admin, credential)
    _profile(admin)
    clock = Clock()
    net = SimpleNamespace(devices={n: SimpleNamespace(up=True, platform="cisco_ios", version="17.12.04")
                                   for n in ids})
    sim = SimMonitor(net, {n: f"10.0.0.{i}" for i, n in enumerate(ids, 1)}, clock=clock)
    poller = Poller(settings, MonitorStore(settings.monitor_dir), admin.app.state.cipher,
                    snmp=sim, pinger=sim.ping, clock=clock)
    poller.housekeeping()
    return SimpleNamespace(admin=admin, ids=ids, clock=clock, sim=sim, poller=poller, net=net,
                           settings=settings)


def _round(s, seconds=60):
    s.clock.t += seconds
    return asyncio.run(s.poller.run_round())


def _state(s, name):
    return s.poller.store.states()[s.ids[name]]


def _events(s, name=None):
    rows = s.poller.store.events(0, s.clock.t + 1, device_id=s.ids[name] if name else None)
    return [(r["kind"], r["detail"]) for r in reversed(rows)]


def test_up_then_down_after_two_silent_polls_then_back_up(setup):
    s = setup
    assert _round(s) == {"up": 3}
    assert _state(s, "sw1")["sys_name"] == "sw1" and _state(s, "sw1")["rtt_ms"] > 0
    s.sim.down.add("sw2")
    _round(s)
    st = _state(s, "sw2")
    assert st["status"] == "warning" and "1 of 2" in st["reason"] and not _events(s, "sw2")
    _round(s)
    assert _state(s, "sw2")["status"] == "down"
    assert [k for k, _ in _events(s, "sw2")] == ["down"]
    down_at = s.poller.store.events(0, s.clock.t + 1, device_id=s.ids["sw2"])[0]["ts"]
    assert down_at == s.clock.t - 60  # from the first poll without an answer
    _round(s)
    assert [k for k, _ in _events(s, "sw2")] == ["down"]  # once
    s.sim.down.discard("sw2")
    _round(s)
    assert _state(s, "sw2")["status"] == "up"
    kinds = _events(s, "sw2")
    assert kinds[-1][0] == "up" and "after 2 min" in kinds[-1][1]
    assert s.poller.store.availability(1, dt.datetime.fromtimestamp(s.clock.t, dt.UTC).date())[s.ids["sw2"]] == 40.0


def test_snmp_trouble_and_no_ping_are_warnings_not_down(setup):
    s = setup
    _round(s)
    s.sim.snmp_error["sw1"] = "Wrong SNMPv3 authentication password or protocol"
    s.sim.no_ping.add("sw3")
    _round(s)
    assert _state(s, "sw1")["status"] == "warning" and "authentication" in _state(s, "sw1")["reason"]
    assert _events(s, "sw1") == [("snmp_failed", "Wrong SNMPv3 authentication password or protocol")]
    assert _state(s, "sw3")["status"] == "warning" and "ping" in _state(s, "sw3")["reason"]
    del s.sim.snmp_error["sw1"]
    _round(s)
    assert _events(s, "sw1")[-1][0] == "snmp_ok"


def test_a_restart_is_noticed_from_the_uptime(setup):
    s = setup
    _round(s)
    first = _state(s, "sw1")["last_restart"]
    _round(s)
    assert not _events(s, "sw1")
    s.sim.boot["sw1"] = s.clock.t + 30  # restarted half a minute into the next minute
    _round(s)
    assert _events(s, "sw1")[0][0] == "restarted"
    assert _state(s, "sw1")["last_restart"] > first
    # the 32-bit uptime counter wrapping after 497 days isn't a restart
    s.sim.boot["sw3"] = s.clock.t + 60 - (2**32 / 100 - 30)  # 30 s before the counter wraps
    _round(s)
    _round(s)
    assert _state(s, "sw3")["uptime"] < 100
    assert not _events(s, "sw3")


def test_maintenance_window_and_switching_monitoring_off(setup):
    s = setup
    now = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    r = s.admin.post("/api/calendar/events", json={
        "title": "Swap sw3", "kind": "maintenance", "start": (now - dt.timedelta(hours=1)).isoformat(),
        "end": (now + dt.timedelta(hours=1)).isoformat(), "sites": ["Branch"], "devices": []})
    assert r.status_code == 201, r.text
    s.poller.housekeeping()
    s.sim.down.add("sw3")
    _round(s)
    _round(s)
    assert _state(s, "sw3")["maintenance"] == 1 and _state(s, "sw3")["status"] == "down"
    ev = s.poller.store.events(0, s.clock.t + 1, device_id=s.ids["sw3"])
    assert ev[0]["kind"] == "down" and ev[0]["maintenance"] == 1
    assert _state(s, "sw1")["maintenance"] == 0
    # switched off: no longer polled, its state forgotten
    r = s.admin.put("/api/monitoring/devices", json={"device_ids": [s.ids["sw3"]], "monitored": False})
    assert r.status_code == 200, r.text
    s.poller.housekeeping()
    _round(s)
    assert s.ids["sw3"] not in s.poller.store.states()


def test_ping_only_when_there_is_no_profile(admin, credential, settings):
    ids = _devices(admin, credential, 1)
    clock = Clock()
    net = SimpleNamespace(devices={"sw1": SimpleNamespace(up=True, platform="cisco_ios", version="1")})
    sim = SimMonitor(net, {"sw1": "10.0.0.1"}, clock=clock)
    poller = Poller(settings, MonitorStore(settings.monitor_dir), admin.app.state.cipher,
                    snmp=sim, pinger=sim.ping, clock=clock)
    poller.housekeeping()
    asyncio.run(poller.run_round())
    st = poller.store.states()[ids["sw1"]]
    assert st["status"] == "up" and "No SNMP profile" in st["reason"] and sim.gets == 0


def test_the_api_lists_devices_and_a_device_detail(setup):
    s = setup
    _round(s)
    s.sim.down.add("sw2")
    _round(s)
    _round(s)
    data = s.admin.get("/api/monitoring/devices").json()
    by = {d["name"]: d for d in data["devices"]}
    assert by["sw2"]["status"] == "down" and by["sw1"]["status"] == "up"
    assert by["sw1"]["profile"] == "switches-v3" and by["sw1"]["profile_is_default"]
    assert data["counts"]["down"] == 1 and data["counts"]["up"] == 2
    d = s.admin.get(f"/api/monitoring/devices/{s.ids['sw2']}").json()
    assert d["events"][0]["kind_label"] == "Down" and d["graph"]
    ev = s.admin.get("/api/monitoring/events", params={"kinds": "down"}).json()["events"]
    assert ev and ev[0]["device"] == "sw2"
    st = s.admin.get("/api/monitoring/status").json()
    assert st["default_profile"] == "switches-v3" and st["running"] is False  # no heartbeat yet
    s.poller.store.write_status(s.poller.status())
    assert s.admin.get("/api/monitoring/status").json()["poller"]["devices"] == 3


def test_profiles_keep_their_secrets_and_need_the_credentials_level(admin, credential):
    p = _profile(admin)
    assert "auth_key" not in p and p["has_auth_key"] and p["has_priv_key"]
    listed = admin.get("/api/monitoring/profiles").json()["profiles"][0]
    assert "priv-pass-1" not in str(listed)
    # bad entries
    for change, msg in [({"auth_key": "short"}, "at least 8"), ({"username": ""}, "user name"),
                        ({"version": "1"}, "2c or 3"), ({"priv_protocol": "ROT13"}, "protocol")]:
        r = admin.post("/api/monitoring/profiles", json={
            "name": "x", "version": "3", "username": "u", "auth_key": "auth-pass-1",
            "priv_key": "priv-pass-1", **change})
        assert r.status_code == 422 and msg in r.text, (change, r.text)
    # changing without the secrets keeps them; a second default replaces the first
    r = admin.put(f"/api/monitoring/profiles/{p['id']}", json={
        "name": "switches-v3", "version": "3", "username": "netops-mon2", "is_default": True})
    assert r.status_code == 200 and r.json()["has_priv_key"]
    v2 = _profile(admin, name="old-v2c", version="2c", community="public-ro")
    names = {x["name"]: x for x in admin.get("/api/monitoring/profiles").json()["profiles"]}
    assert names["old-v2c"]["is_default"] and not names["switches-v3"]["is_default"]
    # a viewer can't change profiles or what is monitored
    admin.post("/api/users", json={"username": "viewer1", "source": "local", "password": PW,
                                   "is_admin": False, "permissions": {"inventory": "view"}})
    viewer = TestClient(admin.app)
    viewer.post("/api/auth/login", json={"username": "viewer1", "password": PW})
    assert viewer.get("/api/monitoring/devices").status_code == 200  # 'view' for users before it
    assert viewer.delete(f"/api/monitoring/profiles/{v2['id']}").status_code == 403
    dev = admin.post("/api/devices", json={"name": "sw9", "address": "10.0.0.9",
                                           "platform": "cisco_ios", "credential_id": credential["id"]}).json()
    assert viewer.put("/api/monitoring/devices", json={"device_ids": [dev["id"]],
                                                       "ping": False}).status_code == 403
    # manage monitoring, but not where secrets go: may switch ping off, not choose a profile
    admin.post("/api/users", json={"username": "noc1", "source": "local", "password": PW,
                                   "is_admin": False,
                                   "permissions": {"inventory": "manage", "monitoring": "manage"}})
    noc = TestClient(admin.app)
    noc.post("/api/auth/login", json={"username": "noc1", "password": PW})
    assert noc.put("/api/monitoring/devices", json={"device_ids": [dev["id"]],
                                                    "ping": False}).status_code == 200
    r = noc.put("/api/monitoring/devices", json={"device_ids": [dev["id"]], "set_profile": True,
                                                 "profile_id": p["id"]})
    assert r.status_code == 403 and "addresses" in r.text
    assert admin.put("/api/monitoring/devices", json={"device_ids": [dev["id"]], "set_profile": True,
                                                      "profile_id": p["id"]}).status_code == 200
    r = admin.delete(f"/api/monitoring/profiles/{p['id']}")
    assert r.json()["devices_moved"] == 1
    acts = [a["action"] for a in admin.get("/api/audit").json()]
    assert {"monitoring.profile_add", "monitoring.profile_change", "monitoring.profile_delete",
            "monitoring.devices"} <= set(acts)


def test_profile_test_button(setup):
    s = setup
    s.admin.app.state.snmp_client = s.sim
    pid = s.admin.get("/api/monitoring/profiles").json()["profiles"][0]["id"]
    r = s.admin.post(f"/api/monitoring/profiles/{pid}/test", json={"device_id": s.ids["sw1"]}).json()
    assert r["ok"] and r["sys_name"] == "sw1" and r["uptime"] > 0
    s.sim.snmp_error["sw1"] = "The device doesn't know this SNMPv3 user"
    r = s.admin.post(f"/api/monitoring/profiles/{pid}/test", json={"device_id": s.ids["sw1"]}).json()
    assert not r["ok"] and "doesn't know" in r["message"]


def test_monitoring_is_a_licence_module(admin):
    from app.core import licence

    assert "monitoring" in licence.MODULES
    assert admin.get("/api/monitoring/devices").status_code == 200  # the trial unlocks everything


def test_setup_help_covers_every_platform(admin):
    covered = {h["platform"] for h in howto.HOWTO}
    assert set(PLATFORMS) <= covered, set(PLATFORMS) - covered
    for h in howto.HOWTO:
        assert "{server}" in h["text"] or h["kind"] == "gui" or "access" in h["notes"].lower() \
            or h["platform"] in ("aruba_aos8", "aruba_aoscx", "fortinet_fortios", "checkpoint_gaia",
                                 "juniper_junos", "", "allied_awplus", "aruba_osswitch",
                                 "cisco_smb", "dell_os10", "extreme_exos", "ubiquiti_edgeos")
        assert "write" not in h["text"].replace("write memory", "").replace("write-access=no", "")
    r = admin.get("/api/monitoring/howto").json()
    assert r["user"] == howto.USER and len(r["platforms"]) == len(howto.HOWTO)


# --- the real SNMP client against a local agent (pysnmp's own responder) -----------------------

def _agent(port: int):
    from pysnmp.carrier.asyncio.dgram import udp
    from pysnmp.entity import config, engine
    from pysnmp.entity.rfc3413 import cmdrsp, context

    eng = engine.SnmpEngine()
    config.add_transport(eng, udp.DOMAIN_NAME, udp.UdpTransport().open_server_mode(("127.0.0.1", port)))
    config.add_v1_system(eng, "ro-area", "test-community")
    config.add_v3_user(eng, "netops-mon", config.USM_AUTH_HMAC96_SHA, "auth-pass-1",
                       config.USM_PRIV_CFB128_AES, "priv-pass-1")
    config.add_vacm_user(eng, 2, "ro-area", "noAuthNoPriv", (1, 3, 6, 1, 2, 1))
    config.add_vacm_user(eng, 3, "netops-mon", "authPriv", (1, 3, 6, 1, 2, 1))
    ctx = context.SnmpContext(eng)
    mib = ctx.get_mib_instrum().get_mib_builder()
    mib.load_modules("__SNMPv2-MIB")
    (sys_name,) = mib.import_symbols("__SNMPv2-MIB", "sysName")
    sys_name.syntax = sys_name.syntax.clone("lab-sw1")
    for responder in (cmdrsp.GetCommandResponder, cmdrsp.NextCommandResponder,
                      cmdrsp.BulkCommandResponder):
        responder(eng, ctx)
    return eng


def test_real_snmp_v2c_and_v3_against_a_local_agent():
    from app.tools.monitoring.snmp import SYS_NAME, SnmpClient, SnmpError

    port = 16161 + (id(object()) % 1000)

    async def run():
        _agent(port)
        client = SnmpClient()
        v2 = await client.get(SnmpTarget("127.0.0.1", port, "2c", community="test-community"),
                              [SYS_NAME, SYS_UPTIME])
        v3 = await client.get(SnmpTarget("127.0.0.1", port, "3", username="netops-mon",
                                         auth_key="auth-pass-1", priv_key="priv-pass-1"), [SYS_NAME])
        walked = await client.walk(SnmpTarget("127.0.0.1", port, "2c", community="test-community"),
                                   "1.3.6.1.2.1.1")
        errors = []
        for bad in (SnmpTarget("127.0.0.1", port, "3", username="netops-mon", auth_key="wrong-pass-1",
                               priv_key="priv-pass-1", timeout=1, retries=0),
                    SnmpTarget("127.0.0.1", port, "3", username="nobody", auth_key="auth-pass-1",
                               priv_key="priv-pass-1", timeout=1, retries=0),
                    SnmpTarget("127.0.0.1", port, "2c", community="wrong", timeout=1, retries=0)):
            try:
                await client.get(bad, [SYS_NAME])
                errors.append(None)
            except SnmpError as exc:
                errors.append(str(exc))
        return v2, v3, walked, errors

    v2, v3, walked, errors = asyncio.run(run())
    assert v2[SYS_NAME] == "lab-sw1" and isinstance(v2[SYS_UPTIME], int)
    assert v3[SYS_NAME] == "lab-sw1"
    assert any(o == SYS_NAME and v == "lab-sw1" for o, v in walked)
    assert "authentication password" in errors[0]
    assert "doesn't know this SNMPv3 user" in errors[1]
    assert "timed out" in errors[2]


def test_email_alerts_for_down_up_and_restart_but_not_in_maintenance(setup):
    s = setup
    box = []
    s.admin.app.state.alert_service.mailer = lambda cfg, msg: box.append(msg)
    r = s.admin.put("/api/alerts", json={
        "enabled": True, "smtp_host": "smtp.corp.example", "mail_from": "noc@corp.example",
        "recipients": [{"address": "oncall@corp.example", "kinds": ["monitoring"]}]})
    assert r.status_code == 200, r.text
    from app.core import alerts, appsettings
    from app.core.db import session_scope

    with session_scope() as db:  # switched on an hour ago (the test clock is an hour behind)
        appsettings.save(db, {alerts.ENABLED_AT: (dt.datetime.now(dt.UTC).replace(tzinfo=None)
                                                  - dt.timedelta(hours=1, minutes=5)).isoformat()}, "t")
    _round(s)
    s.sim.down.add("sw2")
    _round(s)
    _round(s)
    s.admin.app.state.alert_service.tick()
    assert len(box) == 1 and "1 down: sw2" in box[0]["Subject"]
    assert "sw2 (HQ)  DOWN" in box[0].get_content()
    s.admin.app.state.alert_service.tick()
    assert len(box) == 1  # once
    s.sim.down.discard("sw2")
    _round(s)
    s.admin.app.state.alert_service.tick()
    assert "1 back up: sw2" in box[1]["Subject"]
    # in a maintenance window: recorded, not sent
    now = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    s.admin.post("/api/calendar/events", json={
        "title": "Reload sw1", "kind": "change", "start": (now - dt.timedelta(hours=1)).isoformat(),
        "end": (now + dt.timedelta(hours=3)).isoformat(), "devices": [s.ids["sw1"]]})
    s.poller.housekeeping()
    s.sim.down.add("sw1")
    _round(s)
    _round(s)
    s.admin.app.state.alert_service.tick()
    assert len(box) == 2


def test_the_service_is_installed_without_privileges_and_the_firewall_allows_snmp():
    from pathlib import Path

    root = Path(__file__).parents[2]
    unit = (root / "deploy" / "netops-monitor.service").read_text()
    assert "python -m app.tools.monitoring" in unit and "User=netops" in unit
    assert "CapabilityBoundingSet=\n" in unit and "NoNewPrivileges=yes" in unit
    install = (root / "deploy" / "airgap" / "install.sh").read_text()
    assert "netops-monitor.service" in install and "restart netops-monitor" in install
    nft = (root / "deploy" / "hardening" / "nftables.conf").read_text()
    assert "udp dport 161 ip daddr $DEVICE_NETS accept" in nft
    assert "pysnmp" in (root / "backend" / "requirements.txt").read_text()


def test_the_wall_display_shows_who_is_down_without_addresses(setup):
    s = setup
    _round(s)
    s.sim.down.add("sw2")
    s.sim.snmp_error["sw1"] = "Can't look up 10.0.0.1"
    _round(s)
    _round(s)
    key = s.admin.post("/api/displays", json={"name": "NOC"}).json()["key"]
    d = s.admin.get("/api/display/data", headers={"Authorization": f"Bearer {key}"}).json()
    m = d["monitoring"]
    assert m["counts"]["down"] == 1 and m["down"][0]["device"] == "sw2"
    assert m["warnings"][0] == {**m["warnings"][0], "device": "sw1", "problem": "SNMP not answering"}
    assert "10.0.0." not in str(m)
    assert next(x for x in d["sites"] if x["site"] == "HQ")["down"] == 1
    assert "monitoring" in d["pages"]


# --- interfaces (phase 2) ----------------------------------------------------------------------

def test_counters_become_rates():
    from app.tools.monitoring import ifaces as ifm

    cols = {"name": [(f"{ifm.IF_NAME}.1", "Gi1/0/1"), (f"{ifm.IF_NAME}.2", "Gi1/0/2")],
            "type": [(f"{ifm.IF_TYPE}.1", 6), (f"{ifm.IF_TYPE}.2", 6)],
            "high_speed": [(f"{ifm.IF_HIGH_SPEED}.1", 1000), (f"{ifm.IF_HIGH_SPEED}.2", 1000)],
            "in": [(f"{ifm.IF_IN_OCTETS}.1", 100), (f"{ifm.IF_IN_OCTETS}.2", 2**32 - 1000)],
            "hc_in": [(f"{ifm.IF_HC_IN}.1", 10**12)]}
    one, two = ifm.from_walks(cols)
    assert one.hc and one.counters["in"] == 10**12 and not two.hc and two.speed == 10**9
    # 32-bit wrap: 1000 bytes before the top, 4000 after it, 8 s later
    two_later = ifm.Iface(2, counters={"in": 3000}, speed=10**9)
    assert ifm.rates(two_later, {"in": 2**32 - 1000}, 8)["in_bps"] == 4000 * 8 / 8
    # a 64-bit counter going backwards is a reset: no rate
    one_later = ifm.Iface(1, counters={"in": 5}, hc=True, speed=10**9)
    assert ifm.rates(one_later, {"in": 10**12, "hc": True}, 300)["in_bps"] is None
    # more than the port can carry is a bad reading
    assert ifm.rates(ifm.Iface(1, counters={"in": 10**12}, hc=True, speed=10**9),
                     {"in": 0, "hc": True}, 300)["in_bps"] is None
    r = ifm.rates(ifm.Iface(1, counters={"in": 375 * 10**6, "in_err": 30}, speed=10**9),
                  {"in": 0, "in_err": 0}, 60)
    assert r["in_bps"] == 50_000_000 and r["in_util"] == 0.05 and r["errors"] == 30


def test_interfaces_are_read_graphed_and_rolled_up(setup):
    s = setup
    _round(s)  # the first read keeps the counters only
    sw1 = s.ids["sw1"]
    first = s.admin.get(f"/api/monitoring/devices/{sw1}/interfaces").json()["interfaces"]
    assert first and all(i["in_bps"] is None for i in first)
    for _ in range(5):
        _round(s)  # five minutes later: the second read
    data = s.admin.get(f"/api/monitoring/devices/{sw1}/interfaces").json()
    ports = {i["name"]: i for i in data["interfaces"]}
    assert ports["Gi1/0/1"]["speed"] == 10**9 and "Loopback0" in ports
    busy = [i for i in data["interfaces"] if i["in_bps"]]
    assert busy and all(0 < i["util"] <= 1 for i in busy)
    top = s.admin.get("/api/monitoring/ports").json()
    assert top["busiest"][0]["device"] in ("sw1", "sw2", "sw3")
    g = s.admin.get(f"/api/monitoring/devices/{sw1}/interfaces/{busy[0]['if_index']}",
                    params={"hours": 2}).json()
    assert g["detail"] and any(p["in_bps"] for p in g["graph"])
    # hourly averages for longer periods
    s.clock.t += 2 * 3600
    _round(s)
    assert s.poller.store.rollup(s.clock.t) == 0  # the round already rolled the finished hours
    g = s.admin.get(f"/api/monitoring/devices/{sw1}/interfaces/{busy[0]['if_index']}",
                    params={"hours": 24 * 30}).json()
    assert not g["detail"] and any(p["in_bps"] for p in g["graph"])
    # the map asks for the load at the ends of its lines, by the names neighbours use
    r = s.admin.post("/api/monitoring/link-load", json={"ports": [
        {"device_id": sw1, "port": "GigabitEthernet1/0/1"}, {"device_id": sw1, "port": "Te9/9"}]}).json()
    assert [p["port"] for p in r["ports"]] == ["GigabitEthernet1/0/1"]


def test_a_described_port_going_down_is_an_event(setup, monkeypatch):
    from app.demo.monitor import ports_of

    s = setup
    port = next(p for p in ports_of("sw2", "cisco_ios") if p.kind == "access" and p.up)
    monkeypatch.setattr(port, "alias", "uplink to the lab")
    _round(s, 300)
    _round(s, 300)
    monkeypatch.setattr(port, "up", False)
    _round(s, 300)
    kinds = _events(s, "sw2")
    assert kinds[-1][0] == "port_down" and "uplink to the lab" in kinds[-1][1]
    undescribed = next(p for p in ports_of("sw2", "cisco_ios") if p.kind == "access" and p.up and p is not port)
    monkeypatch.setattr(undescribed, "up", False)  # an access port without a description: no event
    _round(s, 300)
    assert [k for k, _ in _events(s, "sw2")].count("port_down") == 1


def test_wall_shows_busiest_ports_without_descriptions(setup, monkeypatch):
    from app.demo.monitor import ports_of

    s = setup
    for p in ports_of("sw3", "cisco_ios"):
        monkeypatch.setattr(p, "alias", "circuit 4471 to 192.0.2.99")
    _round(s, 300)
    _round(s, 300)
    key = s.admin.post("/api/displays", json={"name": "NOC"}).json()["key"]
    m = s.admin.get("/api/display/data", headers={"Authorization": f"Bearer {key}"}).json()["monitoring"]
    assert m["busiest"] and set(m["busiest"][0]) == {"device", "port", "util"}
    assert "192.0.2.99" not in str(m) and "4471" not in str(m)


def test_old_interface_files_are_deleted(tmp_path):
    store = MonitorStore(tmp_path)
    store.save_interfaces(1, [], [(dt.datetime(2026, 1, 1, tzinfo=dt.UTC).timestamp(), 1, 1.0, 1.0, 0, 0)])
    (tmp_path / "ifh-2024-01.db").write_bytes(b"")
    gone = store.prune_interfaces(7, today=dt.date(2026, 3, 1))
    assert gone == ["ifd-2026-01-01.db", "ifh-2024-01.db"]
