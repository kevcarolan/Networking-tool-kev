"""Carrier circuits: provider lines, their status from monitoring, spreadsheets and the
contract-ending email."""

from datetime import timedelta

from app.core.db import utcnow
from tests.test_alerts import _people, _tick, outbox  # noqa: F401 - fixture
from tests.test_monitoring import _events, _round, setup  # noqa: F401 - fixture

BASE = "/api/circuits/carriers"


def _add(client, **body):
    return client.post(BASE, json={"provider": "Northwire", "circuit_ref": "NW-1", **body})


def test_add_change_delete_and_checks(admin):
    r = _add(admin, service="Internet", bandwidth="1 Gbps", contract_end="2027-03-31")
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["status"] == "no_link" and c["status_label"] == "No router or interface"
    assert c["contract_end"] == "2027-03-31"
    assert _add(admin).status_code == 409  # the same provider and circuit ID
    assert admin.post(BASE, json={"service": "MPLS"}).status_code == 422  # neither name nor ID
    assert _add(admin, circuit_ref="NW-2", device_id=99999).status_code == 422
    r = admin.put(f"{BASE}/{c['id']}", json={"provider": "Northwire", "circuit_ref": "NW-1",
                                               "notes": "renewed", "contract_end": None})
    assert r.status_code == 200 and r.json()["notes"] == "renewed" and r.json()["contract_end"] is None
    assert len(admin.get(BASE).json()["circuits"]) == 1
    assert admin.delete(f"{BASE}/{c['id']}").status_code == 204
    assert admin.get(BASE).json()["circuits"] == []
    assert admin.delete(f"{BASE}/{c['id']}").status_code == 404


def test_status_from_monitoring_and_the_port_is_watched(setup, monkeypatch):  # noqa: F811
    from app.demo.monitor import ports_of

    s = setup
    port = next(p for p in ports_of("sw2", "cisco_ios") if p.kind == "access" and p.up and not p.alias)
    c = _add(s.admin, device_id=s.ids["sw2"], interface=port.port).json()
    assert c["status"] == "not_monitored"  # monitoring hasn't read it yet
    s.poller.housekeeping()  # picks up the carrier circuit's port
    _round(s, 300)
    _round(s, 300)
    row = s.admin.get(BASE).json()["circuits"][0]
    assert row["status"] == "up" and row["in_bps"] is not None
    monkeypatch.setattr(port, "up", False)  # no description on it, but it carries a circuit
    _round(s, 300)
    assert s.admin.get(BASE).json()["circuits"][0]["status"] == "down"
    kind, detail = _events(s, "sw2")[-1]
    assert kind == "port_down" and "carrier circuit Northwire NW-1" in detail
    # an interface the device doesn't have
    s.admin.put(f"{BASE}/{c['id']}", json={"provider": "Northwire", "circuit_ref": "NW-1",
                                            "device_id": s.ids["sw2"], "interface": "Gi9/9/9"})
    assert s.admin.get(BASE).json()["circuits"][0]["status"] == "not_found"
    s.sim.down.add("sw2")
    _round(s)
    _round(s)
    assert s.admin.get(BASE).json()["circuits"][0]["status"] == "device_down"


def test_upload_adds_and_updates(admin, device):
    _add(admin, service="Internet")
    csv = ("Provider,Circuit ID,Service,Router or firewall,Interface,Contract end,Notes\n"
           f"Northwire,NW-1,,{device['name']},Gi0/0,2027-01-31,updated\n"
           "Atlas,AT-7,MPLS,,,31/12/2026,\n"
           "Atlas,AT-8,MPLS,no-such-router,,not a date,\n"
           ",,Internet,,,,\n").encode()
    r = admin.put(f"{BASE}/upload", params={"filename": "lines.csv"}, content=csv)
    assert r.status_code == 200, r.text
    d = r.json()
    assert (d["added"], d["updated"]) == (1, 1)
    assert any("not a date" in p for p in d["problems"]) and any("Provider or Circuit" in p for p in d["problems"])
    rows = {c["circuit_ref"]: c for c in admin.get(BASE).json()["circuits"]}
    assert rows["NW-1"]["service"] == "Internet"  # the empty cell kept it
    assert rows["NW-1"]["device_id"] == device["id"] and rows["NW-1"]["notes"] == "updated"
    assert rows["AT-7"]["contract_end"] == "2026-12-31" and "AT-8" not in rows
    assert admin.put(f"{BASE}/upload", params={"filename": "x.csv"},
                     content=b"a,b\n1,2\n").status_code == 422
    exported = admin.get(f"{BASE}/export.csv").text
    assert "Circuit ID" in exported and "NW-1" in exported
    assert admin.get(f"{BASE}/template.xlsx").status_code == 200


def test_contract_ending_is_emailed_at_60_and_14_days(app, admin, outbox):  # noqa: F811
    _people(admin, ("noc@corp.example", ["carriers"]))
    soon = (utcnow() + timedelta(days=40)).date().isoformat()
    c = _add(admin, contract_end=soon, support="Fault line 0800 000 111").json()
    _add(admin, circuit_ref="NW-2", contract_end=(utcnow() + timedelta(days=300)).date().isoformat())
    assert any("Carrier contracts ending: 1" in x for x in _tick(app))
    body = outbox[-1].get_content()
    assert "Northwire NW-1" in body and "0800 000 111" in body and "NW-2" not in body
    assert not any("Carrier" in s for s in _tick(app))  # once
    admin.put(f"{BASE}/{c['id']}", json={"provider": "Northwire", "circuit_ref": "NW-1",
                                          "contract_end": soon})
    from app.core.db import session_scope
    from app.tools.circuits.models import CarrierCircuit

    with session_scope() as db:
        db.get(CarrierCircuit, c["id"]).contract_end = (utcnow() + timedelta(days=10)).date()
    assert any("Carrier contracts ending: 1" in x for x in _tick(app))  # again at 14 days
    assert not any("Carrier" in s for s in _tick(app))


def test_viewers_read_managers_change(client, app, admin):
    from app.core.auth import VIEWER, User

    _add(admin)
    app.state.authenticator.authenticate = lambda u, p: User(username=u, role=VIEWER)
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"username": "v", "password": "x"})
    assert len(client.get(BASE).json()["circuits"]) == 1
    assert _add(client, circuit_ref="X").status_code == 403
    assert client.put(f"{BASE}/upload", params={"filename": "a.csv"}, content=b"x").status_code == 403


def test_search_finds_a_circuit_id(admin):
    _add(admin, service="Internet", site="Head office")
    groups = admin.get("/api/search", params={"q": "NW-1"}).json()["groups"]
    assert groups["carriers"]["items"][0]["provider"] == "Northwire"
