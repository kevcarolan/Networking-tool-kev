"""Meraki through the Dashboard API (tools/monitoring/meraki.py): the client (paging, rate
limits, a wrong key, redirects), the poller's reads and events, who may do what, the
inventory, the calendar, alerts and the wall display. The Dashboard is app.demo.meraki's
pretend one: nothing is sent on the network."""

import datetime as dt
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.demo import meraki as fake
from app.tools.monitoring import meraki as mk
from app.tools.monitoring.poller import Poller
from app.tools.monitoring.store import MonitorStore

PW = "a-long-password-123"
BASE = mk.DEFAULT_BASE


class Clock:
    def __init__(self):
        self.t = float(int(time.time()) - 3600)

    def __call__(self) -> float:
        return self.t


def test_client_reads_every_page_and_waits_out_rate_limits():
    dash = fake.FakeDashboard(page_size=3)
    waits = []
    client = mk.MerakiClient(BASE, fake.KEY, fetch=dash, sleep=waits.append)
    assert client.organizations() == [fake.ORG]
    dash.too_many = 2
    snap = client.snapshot(fake.ORG["id"])
    assert waits == [1.0, 1.0]
    assert len(snap["devices"]) == 10 and snap["networks"] == 3
    assert sum("/devices/statuses" in c for c in dash.calls) == 4  # 10 rows, 3 a page
    rows = {d["name"]: d for d in snap["devices"]}
    assert rows["gal-mr2"]["status"] == "offline" and rows["gal-mr2"]["network"] == "Galway store"
    assert rows["cork-mx1"]["uplinks"][0] == {**rows["cork-mx1"]["uplinks"][0], "interface": "wan1",
                                               "status": "failed"}
    assert rows["dub-mx1"]["public_ip"] == "203.0.113.10" and rows["dub-mr1"]["uplinks"] == []
    upg = {(u["network"], u["product"]): u for u in snap["upgrades"]}
    assert upg[("Dublin store", "appliance")]["next_version"] == "MX 18.211.2"
    assert not upg[("Galway store", "appliance")]["next_time"]
    assert client.snapshot(fake.ORG["id"], upgrades=False)["upgrades"] is None


def test_client_errors_are_plain_words():
    dash = fake.FakeDashboard()
    with pytest.raises(mk.MerakiError, match="API key was refused"):
        mk.MerakiClient(BASE, "wrong", fetch=dash).organizations()
    with pytest.raises(mk.MerakiError, match="organisation ID"):
        mk.MerakiClient(BASE, fake.KEY, fetch=dash).snapshot("999")
    dash.too_many = 10
    with pytest.raises(mk.MerakiError, match="too many requests"):
        mk.MerakiClient(BASE, fake.KEY, fetch=dash, sleep=lambda s: None).organizations()
    with pytest.raises(mk.MerakiError, match="Unknown"):
        mk.MerakiClient("https://evil.example/api/v1", fake.KEY)


def test_the_key_never_leaves_meraki():
    """Redirects and next-page links are followed only to Meraki's own domain."""
    guard = mk._MerakiRedirects("meraki.com")
    for bad in ("https://evil.example/api/v1/organizations", "http://n1.meraki.com/api/v1/x",
                "https://meraki.com.evil.example/x"):
        with pytest.raises(mk.MerakiError):
            guard.redirect_request(None, None, 302, "", {}, bad)

    def sly(url, headers):
        return 200, {"Link": "<https://evil.example/api/v1/next>; rel=next"}, b"[]"
    with pytest.raises(mk.MerakiError, match="another address"):
        mk.MerakiClient(BASE, fake.KEY, fetch=sly).get_all("/organizations/1/devices")
    assert mk.reported_at("2026-10-14T08:00:00.000000Z") == dt.datetime(2026, 10, 14, 8, tzinfo=dt.UTC).timestamp()
    assert mk.reported_at("") is None and mk.reported_at("soon") is None


def _connect(admin, **extra):
    r = admin.post("/api/monitoring/meraki/connections", json={
        "name": "Retail", "api_key": fake.KEY, "org_id": fake.ORG["id"], "org_name": "Demo Retail", **extra})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def mer(admin, settings):
    dash = fake.FakeDashboard()
    admin.app.state.meraki_fetch = dash
    conn = _connect(admin)
    clock = Clock()
    poller = Poller(settings, MonitorStore(settings.monitor_dir), admin.app.state.cipher,
                    clock=clock, meraki_fetch=dash)
    poller.housekeeping()
    return SimpleNamespace(admin=admin, dash=dash, conn=conn, clock=clock, poller=poller, settings=settings)


def _sync(m, seconds=300):
    m.clock.t += seconds
    return m.poller.sync_meraki()


def test_the_poller_reads_meraki_and_notices_changes(mer):
    m = mer
    assert _sync(m) == 1
    assert m.poller.sync_meraki() == 0  # not due again until monitor_meraki_seconds
    data = m.poller.store.meraki()
    assert len(data["devices"]) == 10 and data["state"][m.conn["id"]]["error"] == ""
    off = next(d for d in data["devices"] if d["name"] == "gal-mr2")
    assert off["since"] < m.clock.t - 6 * 3600  # since it last reported, not since the first read
    assert m.poller.store.meraki_events(0, m.clock.t + 1) == []  # the first read is no change
    m.dash.status["Q2KD-CCCC-0003"] = "online"
    m.dash.status["Q2HP-AAAA-0002"] = "offline"
    _sync(m)
    ev = {(e["name"], e["kind"]) for e in m.poller.store.meraki_events(0, m.clock.t + 1)}
    assert ev == {("gal-mr2", "meraki_online"), ("dub-ms1", "meraki_offline")}
    upgrades_read = sum("firmwareUpgrades" in c for c in m.dash.calls)
    _sync(m)
    assert sum("firmwareUpgrades" in c for c in m.dash.calls) == upgrades_read  # hourly, not every read
    # a wrong key: the error is kept, the last devices stay
    m.admin.put(f"/api/monitoring/meraki/connections/{m.conn['id']}", json={
        "name": "Retail", "api_key": "a-wrong-key", "org_id": fake.ORG["id"]})
    m.poller.housekeeping()
    _sync(m)
    state = m.poller.store.meraki()["state"][m.conn["id"]]
    assert "refused" in state["error"] and len(m.poller.store.meraki()["devices"]) == 10
    r = m.admin.get("/api/monitoring/meraki").json()
    assert "refused" in r["connections"][0]["error"]
    # deleted: its devices go
    m.admin.delete(f"/api/monitoring/meraki/connections/{m.conn['id']}")
    m.poller.housekeeping()
    assert m.poller.store.meraki()["devices"] == []


def test_the_page_lists_devices_with_problems_first_and_never_the_key(mer):
    _sync(mer)
    r = mer.admin.get("/api/monitoring/meraki").json()
    assert [d["name"] for d in r["devices"][:2]] == ["gal-mr2", "cork-mx1"]
    assert r["counts"] == {**r["counts"], "online": 8, "offline": 1, "alerting": 1}
    assert len([u for u in r["upgrades"] if u["next_time"]]) == 2
    assert fake.KEY not in str(r) and "api_key_enc" not in str(r)
    assert set(r["bases"]) == set(mk.BASES)


def test_who_may_do_what(mer):
    a = mer.admin
    for name, perms in [("viewer1", {"inventory": "view", "monitoring": "view"}),
                        ("inv1", {"inventory": "manage", "monitoring": "manage"}),
                        ("none1", {"inventory": "view", "monitoring": "none"})]:
        a.post("/api/users", json={"username": name, "source": "local", "password": PW,
                                   "is_admin": False, "permissions": perms})
    users = {}
    for name in ("viewer1", "inv1", "none1"):
        users[name] = TestClient(a.app)
        users[name].post("/api/auth/login", json={"username": name, "password": PW})
    assert users["viewer1"].get("/api/monitoring/meraki").status_code == 200
    assert users["none1"].get("/api/monitoring/meraki").status_code == 403
    # API keys are credentials: only 'inventory: credentials' adds, changes or tests them
    for u in ("viewer1", "inv1"):
        assert users[u].post("/api/monitoring/meraki/connections", json={
            "name": "x", "api_key": "k", "org_id": "1"}).status_code == 403
        assert users[u].post("/api/monitoring/meraki/organizations", json={
            "connection_id": mer.conn["id"]}).status_code == 403
        assert users[u].delete(f"/api/monitoring/meraki/connections/{mer.conn['id']}").status_code == 403
    assert users["viewer1"].post("/api/monitoring/meraki/inventory").status_code == 403
    assert users["inv1"].post("/api/monitoring/meraki/inventory").status_code == 200
    # bad entries
    for body, msg in [({"api_key": ""}, "API key"), ({"base_url": "https://evil.example/api/v1"}, "Dashboard API"),
                      ({"org_id": "1; drop"}, "org_id")]:
        r = a.post("/api/monitoring/meraki/connections", json={"name": "y", "api_key": "k", "org_id": "1", **body})
        assert r.status_code == 422 and msg in r.text, (body, r.text)
    assert a.post("/api/monitoring/meraki/connections", json={
        "name": "Retail", "api_key": "k", "org_id": "1"}).status_code == 409
    acts = {x["action"] for x in a.get("/api/audit").json()}
    assert {"monitoring.meraki_add", "monitoring.meraki_change", "monitoring.meraki_delete"} & acts


def test_finding_organisations_with_a_new_or_saved_key(mer):
    a = mer.admin
    r = a.post("/api/monitoring/meraki/organizations", json={"api_key": fake.KEY}).json()
    assert r["ok"] and r["organizations"] == [fake.ORG]
    r = a.post("/api/monitoring/meraki/organizations", json={"connection_id": mer.conn["id"]}).json()
    assert r["ok"]
    r = a.post("/api/monitoring/meraki/organizations", json={"api_key": "nope"}).json()
    assert not r["ok"] and "refused" in r["message"]
    assert a.post("/api/monitoring/meraki/organizations", json={}).status_code == 422
    # changing a connection without a key keeps the saved one
    r = a.put(f"/api/monitoring/meraki/connections/{mer.conn['id']}", json={
        "name": "Retail stores", "org_id": fake.ORG["id"]})
    assert r.status_code == 200 and r.json()["has_key"]
    assert a.post("/api/monitoring/meraki/organizations", json={"connection_id": mer.conn["id"]}).json()["ok"]


def test_meraki_devices_go_into_the_inventory_by_serial(mer, credential):
    a = mer.admin
    _sync(mer)
    r = a.post("/api/monitoring/meraki/inventory").json()
    assert r == {"added": 10, "updated": 0, "total": 10}
    assert a.post("/api/monitoring/meraki/inventory").json()["updated"] == 0  # nothing new
    rows = {x["values"]["name"]: x["values"] for x in a.get("/api/inventory/assets").json()
            if x["values"]["manufacturer"] == "Cisco Meraki"}
    assert rows["dub-mx1"]["type"] == "firewall" and rows["dub-mr1"]["type"] == "access point"
    assert rows["cork-ms1"]["serial"] == "Q2HP-BBBB-0002" and rows["cork-ms1"]["site"] == "Cork store"
    # new firmware in Meraki: the row is brought up to date, not doubled
    fake.DEVICES[0] = fake.DEVICES[0][:5] + ("MX 18.211.2",)
    try:
        _sync(mer)
        r = a.post("/api/monitoring/meraki/inventory").json()
    finally:
        fake.DEVICES[0] = fake.DEVICES[0][:5] + ("MX 18.107.10",)
    assert r == {"added": 0, "updated": 1, "total": 10}
    rows = [x["values"] for x in a.get("/api/inventory/assets").json() if x["values"]["name"] == "dub-mx1"]
    assert len(rows) == 1 and rows[0]["version"] == "MX 18.211.2"


def test_meraki_upgrades_are_on_the_calendar(mer):
    _sync(mer)
    now = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    r = mer.admin.get("/api/calendar", params={"start": now.isoformat(),
                                               "end": (now + dt.timedelta(days=10)).isoformat()}).json()
    items = [x for x in r["items"] if x["source"] == "meraki"]
    assert sorted(x["title"] for x in items) == ["Cork store MR → MR 30.7", "Dublin store MX → MX 18.211.2"]
    assert all(x["kind"] == "meraki" and x["sites"] for x in items)
    ics = mer.admin.get("/api/calendar/export.ics").text
    assert "Dublin store MX" in ics


def test_meraki_alerts_and_the_wall(mer):
    from app.core import alerts, appsettings
    from app.core.db import session_scope

    a = mer.admin
    box = []
    a.app.state.alert_service.mailer = lambda cfg, msg: box.append(msg)
    a.put("/api/alerts", json={"enabled": True, "smtp_host": "smtp.corp.example", "mail_from": "noc@corp.example",
                               "recipients": [{"address": "oncall@corp.example", "kinds": ["monitoring"]}]})
    with session_scope() as db:
        appsettings.save(db, {alerts.ENABLED_AT: (dt.datetime.now(dt.UTC).replace(tzinfo=None)
                                                  - dt.timedelta(hours=1, minutes=5)).isoformat()}, "t")
    _sync(mer)
    mer.dash.status["Q2HP-AAAA-0002"] = "offline"
    _sync(mer)
    a.app.state.alert_service.tick()
    assert len(box) == 1 and "Meraki" in box[0]["Subject"] and "dub-ms1" in box[0].get_content()
    a.app.state.alert_service.tick()
    assert len(box) == 1  # once
    key = a.post("/api/displays", json={"name": "NOC"}).json()["key"]
    d = a.get("/api/display/data", headers={"Authorization": f"Bearer {key}"}).json()
    mk_feed = d["monitoring"]["meraki"]
    assert mk_feed["counts"]["offline"] == 2
    assert {x["device"] for x in mk_feed["problems"]} == {"gal-mr2", "dub-ms1", "cork-mx1"}
    assert "203.0.113" not in str(d) and "10.2" not in str(mk_feed) and fake.KEY not in str(d)
    assert "monitoring" in d["pages"]
