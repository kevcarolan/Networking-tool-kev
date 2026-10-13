"""Site layout (buildings, floors, rooms) and rack elevations."""

import pytest

from tests.test_inventory_assets import _add as add_item
from tests.test_inventory_assets import _by_name
from tests.test_sites import _add as add_site


def _loc(client, site, kind, name, parent=None):
    r = client.post(f"/api/sites/{site}/locations", json={"kind": kind, "name": name, "parent_id": parent})
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture
def hq(admin):
    site = add_site(admin, name="Head office", code="HQ")
    b = _loc(admin, site, "building", "Main building")
    f = _loc(admin, site, "floor", "Ground floor", b)
    room = _loc(admin, site, "room", "Comms 1", f)
    return {"site": site, "building": b, "floor": f, "room": room}


def _move(client, asset, rack, position=None, face="front"):
    return client.post("/api/racks/move", json={"asset_id": asset, "rack_id": rack,
                                                 "position": position, "face": face})


def test_the_tree_and_what_is_in_it(admin, hq):
    s = hq["site"]
    assert admin.post(f"/api/sites/{s}/locations", json={"kind": "floor", "name": "x"}).status_code == 422
    assert admin.post(f"/api/sites/{s}/locations", json={"kind": "building", "name": "main BUILDING"}).status_code == 409
    _loc(admin, s, "room", "Plant room", hq["building"])  # a room straight in a building
    add_item(admin, name="R01", type="rack", site="hq", building="Main building",
             floor="ground floor", room="comms 1", rack_units=42)
    add_item(admin, name="ups1", type="UPS", site="HQ", rack="R01")         # in the rack
    add_item(admin, name="ahu1", type="other", site="HQ", building="Main building", room="Plant room")
    add_item(admin, name="old", type="other", site="HQ", building="Annexe", floor="1")  # not in the tree
    data = admin.get(f"/api/sites/{s}/layout").json()
    main = data["tree"][0]
    assert (main["name"], main["items"], main["racks"]) == ("Main building", 3, 1)
    rooms = {c["name"]: c["items"] for c in main["children"]}
    assert rooms == {"Ground floor": 2, "Plant room": 1}
    assert main["children"][0]["children"][0]["items"] == 2  # Comms 1: the rack and the UPS in it
    assert data["missing"] == [{"path": ["Annexe"], "kind": "building", "items": 1}]
    added = admin.post(f"/api/sites/{s}/layout/from-inventory").json()["added"]
    assert added == ["Annexe", "Annexe / 1"]
    assert admin.get(f"/api/sites/{s}/layout").json()["missing"] == []


def test_renaming_carries_to_the_items_and_deleting_keeps_them(admin, hq):
    add_item(admin, name="R01", type="rack", site="HQ", building="Main building",
             floor="Ground floor", room="Comms 1")
    r = admin.put(f"/api/locations/{hq['room']}", json={"name": "Comms room 1"})
    assert r.json()["renamed_on"] == 1 and _by_name(admin, "R01")["values"]["room"] == "Comms room 1"
    assert admin.delete(f"/api/locations/{hq['building']}").status_code == 204
    data = admin.get(f"/api/sites/{hq['site']}/layout").json()
    assert data["tree"] == [] and data["missing"][0]["path"] == ["Main building"]
    assert _by_name(admin, "R01")["values"]["building"] == "Main building"


def test_rack_elevation_and_moves(admin, hq):
    rack = add_item(admin, name="R01", type="rack", site="HQ", building="Main building",
                    floor="Ground floor", room="Comms 1", rack_units=10)
    sw = add_item(admin, name="sw1", type="switch", site="HQ", rack="R01", rack_position=10, rack_units=1)
    srv = add_item(admin, name="srv1", type="server", rack_units=2)  # elsewhere, no site
    patch = add_item(admin, name="pp1", type="patch panel", site="HQ", rack="R01", rack_position=9,
                     rack_units=1, rack_depth="half")
    pdu = add_item(admin, name="pdu1", type="PDU", site="HQ", rack="R01", rack_units=0)
    racks = admin.get("/api/racks", params={"site_id": hq["site"], "location_id": hq["room"]}).json()
    r = racks["racks"][0]
    assert (r["name"], r["height"], r["used_u"], r["free_u"]) == ("R01", 10, 2, 8)
    assert [i["name"] for i in r["items"]] == ["sw1", "pp1"] and r["zero_u"][0]["id"] == pdu
    assert r["path"][-1]["name"] == "Comms 1" and r["problems"] == []

    assert _move(admin, srv, rack, 10).status_code == 409          # past the top (2U)
    m = _move(admin, srv, rack, 8)                                  # U8-U9: pp1 is at U9
    assert m.status_code == 409 and "taken by pp1" in m.json()["detail"]
    assert _move(admin, srv, rack, 4).status_code == 200
    moved = _by_name(admin, "srv1")["values"]
    assert (moved["rack"], moved["rack_position"], moved["site"], moved["room"]) == ("R01", 4, "HQ", "Comms 1")
    assert _move(admin, patch, rack, 4, "rear").status_code == 409  # srv1 is full depth
    admin.put(f"/api/inventory/assets/{srv}", json={"values": {"rack_depth": "half"}})
    assert _move(admin, patch, rack, 4, "rear").status_code == 200  # half-depth front and rear
    assert _move(admin, srv, None).status_code == 200
    assert _by_name(admin, "srv1")["values"]["rack"] == ""
    assert "rack R01, U4 rear" in admin.get("/api/audit").json()[1]["detail"]
    loc = admin.get(f"/api/racks/locate/{sw}").json()
    assert loc == {"site_id": hq["site"], "location_id": hq["room"], "rack_id": rack}


def test_problems_are_listed_and_racks_carry_their_items(admin, hq):
    rack = add_item(admin, name="R01", type="rack", site="HQ", building="Main building",
                    floor="Ground floor", room="Comms 1")
    add_item(admin, name="a", type="switch", site="HQ", rack="R01", rack_position=5, rack_units=2)
    add_item(admin, name="b", type="switch", site="HQ", rack="R01", rack_position=6)
    add_item(admin, name="c", type="switch", site="HQ", rack="R02", rack_position=1)
    data = admin.get("/api/racks", params={"site_id": hq["site"]}).json()
    probs = data["racks"][0]["problems"]
    assert "Height not set: drawn as 42U" in probs and "a and b overlap" in probs
    assert "b: height not set, drawn as 1U" in probs and data["unknown_racks"] == ["R02"]
    # Renaming the rack, or moving it to another room, takes its items along.
    _loc(admin, hq["site"], "room", "Comms 2", hq["floor"])
    admin.put(f"/api/inventory/assets/{rack}", json={"values": {"name": "R10", "room": "Comms 2"}})
    a = _by_name(admin, "a")["values"]
    assert (a["rack"], a["room"]) == ("R10", "Comms 2")


def test_viewers_see_but_dont_move(app, admin, hq):
    from fastapi.testclient import TestClient

    from tests.test_users import _add as add_user
    from tests.test_users import _login

    rack = add_item(admin, name="R01", type="rack", site="HQ")
    sw = add_item(admin, name="sw1", type="switch", site="HQ")
    add_user(admin, "viewer1", preset="viewer")
    with TestClient(app) as c:
        _login(c, "viewer1")
        assert c.get(f"/api/sites/{hq['site']}/layout").status_code == 200
        assert c.get("/api/racks", params={"site_id": hq["site"]}).status_code == 200
        assert _move(c, sw, rack, 1).status_code == 403
        assert c.post(f"/api/sites/{hq['site']}/locations", json={"name": "x"}).status_code == 403
