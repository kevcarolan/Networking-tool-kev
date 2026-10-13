"""The topology map (tools/circuits/topology.py): neighbours read at the network scan, one
line per link even when both ends report it, other sites and unmanaged neighbours, phones
and access points left out unless asked for, and saved box positions."""

import pytest
from fastapi.testclient import TestClient

from app.core import licence
from app.demo import __main__ as demo
from app.demo import samples as s
from app.demo import seed
from app.demo import vendor_samples as v
from app.tools.circuits import live


@pytest.fixture(scope="module")
def demo_app(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setattr(seed.time, "sleep", lambda s: None)
    mp.setattr(licence, "DEVELOPMENT", True)
    app, net, _worker = demo.build(tmp_path_factory.mktemp("demo"), 8797, scheduler=False)
    demo.first_run(app, net)
    with TestClient(app) as c:
        c.post("/api/auth/login", json={"username": seed.ADMIN_USER,
                                        "password": seed.ADMIN_PASSWORD})
        yield c
    mp.undo()


def _site(c, name):
    data = c.get("/api/sites/index").json()
    return next(x["id"] for x in data if x["name"] == name)


def _names(t):
    keys = {n["key"]: n["name"] for n in t["nodes"]}
    return {tuple(sorted((keys[e["a"]], keys[e["b"]]))): e["links"] for e in t["edges"]}


def test_neighbour_readers():
    cdp = live.parse_neighbors_cdp(s.CDP_DETAIL)
    assert [(n.local_port, n.name, n.remote_port, n.address) for n in cdp][0] == (
        "GigabitEthernet1/0/1", "SITEA-CORE-01", "TwentyFiveGigE1/0/1", "10.20.0.1")
    os10 = live.parse_neighbors_lldp(v.OS10_LLDP)  # 'Local Port ID' mid-block
    assert [(n.local_port, n.name, n.remote_port) for n in os10] == [
        ("ethernet1/1/49", "spine1", "Ethernet1")]
    cx = live.parse_neighbors_lldp(v.AOSCX_LLDP)
    assert [(n.name, n.infra) for n in cx] == [("core1", True), ("ap-floor1", False)]
    junos = live.parse_neighbors_lldp_table(v.JUNOS_LLDP)
    assert ("ge-0/0/47", "spine1", "Ethernet1") in [(n.local_port, n.name, n.remote_port) for n in junos]
    assert not next(n for n in junos if n.name == "phone-101").infra
    mt = live.parse_neighbors_mikrotik(v.ROUTEROS_NEIGHBORS)
    assert (mt[0].local_port, mt[0].name, mt[0].address) == ("ether1", "core1", "10.0.0.1")
    # CDP and LLDP saying the same thing: one neighbour
    read = live.read_device({"cdp": s.CDP_DETAIL, "lldp": s.LLDP_DETAIL})
    assert sum(1 for n in read.neighbors if n.name == "SITEA-CORE-01") == 1
    assert live.read_device({"mac": ""}).neighbors is None  # no neighbour table read


def test_site_map_shows_each_link_once(demo_app):
    t = demo_app.get("/api/topology", params={"site_id": _site(demo_app, "Head office")}).json()
    links = _names(t)
    # both cores report the two links between them: still two, not four
    assert [(x["a_port"], x["b_port"]) for x in links[("hq-core1", "hq-core2")]] == [
        ("Ethernet1/49", "Ethernet1/49"), ("Ethernet1/50", "Ethernet1/50")]
    assert links[("hq-acc-sw3", "hq-core1")] == [{"a_port": "GigabitEthernet1/1/1",
                                                  "b_port": "Ethernet1/3"}]
    kinds = {n["name"]: n["kind"] for n in t["nodes"]}
    assert kinds["dc1-spine1"] == "other_site" and kinds["hq-wan-rtr"] == "unmanaged"
    assert kinds["hq-fw1"] == "device"  # found from the cores' side (the ASA reports none)
    assert "hq-ap-01" not in kinds  # phones and access points: counted, not drawn
    assert next(n for n in t["nodes"] if n["name"] == "hq-acc-sw1")["endpoints"] == 1
    t = demo_app.get("/api/topology", params={"site_id": _site(demo_app, "Head office"),
                                              "endpoints": True}).json()
    assert {n["name"]: n["kind"] for n in t["nodes"]}["hq-ap-01"] == "endpoint"


def test_every_site_map(demo_app):
    t = demo_app.get("/api/topology").json()
    kinds = {n["name"]: n["kind"] for n in t["nodes"]}
    assert kinds["dc1-spine1"] == "device" and "other_site" not in kinds.values()
    assert ("dc1-spine1", "hq-core1") in _names(t) and t["last_scan"]


def test_positions_are_saved_for_everyone_by_managers(demo_app):
    site = _site(demo_app, "Branch North")
    body = {"site_id": site, "positions": {"d:1": {"x": 10, "y": 20}, "n:isp-north-ce": {"x": 5, "y": 5}}}
    assert demo_app.put("/api/topology/positions", json=body).status_code == 200
    assert demo_app.get("/api/topology", params={"site_id": site}).json()["positions"]["d:1"] == {
        "x": 10, "y": 20}
    bad = {"site_id": site, "positions": {"x:1": {"x": 1, "y": 1}}}
    assert demo_app.put("/api/topology/positions", json=bad).status_code == 422
    assert demo_app.delete("/api/topology/positions", params={"site_id": site}).status_code == 200
    assert demo_app.get("/api/topology", params={"site_id": site}).json()["positions"] == {}
    assert demo_app.get("/api/topology", params={"site_id": 99999}).status_code == 404


def test_viewers_see_but_dont_move(demo_app):
    r = demo_app.post("/api/users", json={"username": "map-viewer", "source": "local",
                                          "password": "a-long-password-123", "is_admin": False,
                                          "permissions": {"inventory": "view", "circuits": "view"}})
    assert r.status_code in (200, 201), r.text
    viewer = TestClient(demo_app.app)
    viewer.post("/api/auth/login", json={"username": "map-viewer", "password": "a-long-password-123"})
    assert viewer.get("/api/topology").status_code == 200
    assert viewer.put("/api/topology/positions", json={"site_id": 0, "positions": {}}).status_code == 403
