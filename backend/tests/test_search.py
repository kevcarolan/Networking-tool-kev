"""The search box (core/search.py), on the demo's data: devices, inventory items, sites,
circuits and MAC/IP addresses from the last scan, each only for people allowed to see it."""

import pytest
from fastapi.testclient import TestClient

from app.core import licence, search
from app.core.auth import User
from app.core.db import session_scope
from app.demo import __main__ as demo
from app.demo import seed


@pytest.fixture(scope="module")
def demo_app(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setattr(seed.time, "sleep", lambda s: None)
    mp.setattr(licence, "DEVELOPMENT", True)
    app, net, _worker = demo.build(tmp_path_factory.mktemp("demo"), 8798, scheduler=False)
    demo.first_run(app, net)
    with TestClient(app) as c:
        c.post("/api/auth/login", json={"username": seed.ADMIN_USER,
                                        "password": seed.ADMIN_PASSWORD})
        yield c
    mp.undo()


def _names(res, group):
    return [i.get("name") or i.get("mac") for i in res["groups"].get(group, {}).get("items", [])]


def test_finds_devices_items_and_sites(demo_app):
    r = demo_app.get("/api/search", params={"q": "branch"}).json()
    assert "Branch North" in _names(r, "sites") and "bn-sw1" in _names(r, "devices")
    r = demo_app.get("/api/search", params={"q": "ups"}).json()
    assert _names(r, "items") and "devices" not in r["groups"]
    d = demo_app.get("/api/search", params={"q": "hq-acc-sw3"}).json()["groups"]["devices"]["items"][0]
    assert d["address"] and d["asset_id"]  # the inventory row, for people without other tabs


def test_finds_a_circuit_and_where_its_mac_is(demo_app):
    circuit = demo_app.get("/api/circuits").json()["circuits"][0]
    mac = circuit["mac"]
    colons = ":".join(mac[i:i + 2] for i in range(0, 12, 2)) if ":" not in mac else mac
    for q in (mac, colons, colons.replace(":", "-").upper()):
        r = demo_app.get("/api/search", params={"q": q}).json()
        assert circuit["device_name"] in _names(r, "circuits"), q
        seen = r["groups"]["network"]["items"][0]
        assert seen["device"] == circuit["switch"] and seen["port"], q
    r = demo_app.get("/api/search", params={"q": circuit["ip"]}).json()
    assert circuit["device_name"] in _names(r, "circuits")


def test_too_short_and_nothing_found(demo_app):
    assert demo_app.get("/api/search", params={"q": "h"}).json()["groups"] == {}
    assert demo_app.get("/api/search", params={"q": "zzz-nothing"}).json()["groups"] == {}
    # % and _ are searched for as themselves, not as wildcards
    assert demo_app.get("/api/search", params={"q": "%%"}).json()["groups"] == {}


def test_only_what_the_person_and_the_licence_allow(demo_app, monkeypatch):
    circuit = demo_app.get("/api/circuits").json()["circuits"][0]
    no_circuits = User("ann", perms={"inventory": "view", "circuits": "none"})
    with session_scope() as db:
        r = search.search(db, no_circuits, circuit["mac"])
        assert "circuits" not in r["groups"] and "network" not in r["groups"]
        viewer = User("bob", perms={"inventory": "view", "circuits": "view"})
        assert "circuits" in search.search(db, viewer, circuit["mac"])["groups"]
        real = licence.status
        monkeypatch.setattr(licence, "status", lambda db: {**real(db), "modules": ["backups"]})
        assert "circuits" not in search.search(db, viewer, circuit["mac"])["groups"]


def test_mac_fragments():
    assert search.mac_fragment("02:00:5e") == "02005e"
    assert search.mac_fragment("aabb") == "aabb"
    assert search.mac_fragment("1234") == ""  # a short number: a port, VLAN or serial
    assert search.mac_fragment("hq-sw1") == ""
