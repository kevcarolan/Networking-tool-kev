"""The maintenance calendar (tools/calendar/api.py): changes people add, upgrade job windows,
clashes, who may change it, and the .ics export."""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core import licence
from app.demo import __main__ as demo
from app.demo import seed
from app.tools.calendar.api import _clashes


@pytest.fixture(scope="module")
def demo_app(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setattr(seed.time, "sleep", lambda s: None)
    mp.setattr(licence, "DEVELOPMENT", True)
    app, net, _worker = demo.build(tmp_path_factory.mktemp("demo"), 8796, scheduler=False)
    demo.first_run(app, net)
    with TestClient(app) as c:
        c.post("/api/auth/login", json={"username": seed.ADMIN_USER,
                                        "password": seed.ADMIN_PASSWORD})
        yield c
    mp.undo()


def _item(key, kind, start, hours, sites=(), devices=()):
    s = datetime(2026, 11, 2) + timedelta(hours=start)
    return {"key": key, "kind": kind, "start": s, "end": s + timedelta(hours=hours),
            "sites": list(sites), "devices": [{"id": d} for d in devices]}


def test_clash_rules():
    items = [
        _item("a", "change", 20, 2, ["HQ"], [1]),
        _item("b", "upgrade", 21, 1, ["HQ"], [1]),       # same device, overlapping
        _item("c", "change", 21, 1, ["Branch"], [9]),    # elsewhere: no clash
        _item("d", "change", 22, 1, ["HQ"], [2]),        # same site, after a ends: none
        _item("f", "freeze", 0, 48, []),                 # a freeze everywhere
        _item("g", "freeze", 10, 4, ["Branch"]),         # two freezes never clash
    ]
    _clashes(items)
    by = {i["key"]: set(i["clashes"]) for i in items}
    assert by["a"] == {"b", "f"} and by["b"] == {"a", "f"}
    assert by["c"] == {"f"} and by["d"] == {"f"}
    assert by["f"] == {"a", "b", "c", "d"} and by["g"] == set()
    # the same site at the same time clashes even on different devices
    two = [_item("x", "change", 1, 2, ["HQ"], [1]), _item("y", "maintenance", 2, 2, ["HQ"], [5])]
    _clashes(two)
    assert two[0]["clashes"] == ["y"]


def test_demo_calendar_has_the_upgrade_and_its_clash(demo_app):
    items = demo_app.get("/api/calendar").json()["items"]
    job = next(x for x in items if x["source"] == "upgrade")
    assert job["kind"] == "dry_run" and job["devices"][0]["name"] == "hq-acc-sw6"
    vlans = next(x for x in items if x["title"].startswith("New VLANs"))
    assert job["key"] in vlans["clashes"] and vlans["key"] in job["clashes"]
    warehouse = next(x for x in items if x["title"].startswith("Warehouse"))
    freeze = next(x for x in items if x["kind"] == "freeze")
    assert freeze["key"] in warehouse["clashes"]
    # filtered to one site: that site's items and the ones for every site
    only = demo_app.get("/api/calendar", params={"site": "Branch North"}).json()["items"]
    assert {x["title"] for x in only} == {"ISP line work (provider)", "Month-end change freeze"}


def test_add_edit_delete(demo_app):
    start = (datetime.now() + timedelta(days=20)).replace(microsecond=0)
    body = {"title": "Replace UPS batteries", "kind": "maintenance", "start": start.isoformat(),
            "end": (start + timedelta(hours=2)).isoformat(), "sites": ["HQ"], "devices": [],
            "change_ref": "CHG1", "notes": "Bring the battery trolley"}
    r = demo_app.post("/api/calendar/events", json=body)
    assert r.status_code == 201, r.text
    eid = r.json()["id"]
    q = {"start": start.isoformat(), "end": (start + timedelta(days=1)).isoformat()}
    got = next(x for x in demo_app.get("/api/calendar", params=q).json()["items"] if x["id"] == eid)
    assert got["sites"] == ["Head office"]  # a site code is stored as the site's name
    assert demo_app.put(f"/api/calendar/events/{eid}", json={**body, "kind": "outage"}).status_code == 200
    got = next(x for x in demo_app.get("/api/calendar", params=q).json()["items"] if x["id"] == eid)
    assert got["kind"] == "outage"
    assert demo_app.delete(f"/api/calendar/events/{eid}").status_code == 200
    assert demo_app.delete(f"/api/calendar/events/{eid}").status_code == 404
    acts = [a["action"] for a in demo_app.get("/api/audit").json()]
    assert {"calendar.add", "calendar.edit", "calendar.delete"} <= set(acts)


@pytest.mark.parametrize("change, message", [
    ({"kind": "party"}, "kind"),
    ({"end": "2026-11-01T00:00:00"}, "ends before"),
    ({"devices": [99999]}, "Unknown device"),
    ({"title": ""}, ""),
])
def test_bad_entries_are_refused(demo_app, change, message):
    body = {"title": "x", "kind": "change", "start": "2026-11-02T20:00:00",
            "end": "2026-11-02T21:00:00", **change}
    r = demo_app.post("/api/calendar/events", json=body)
    assert r.status_code == 422 and message in r.text


def test_viewers_see_it_but_cannot_change_it_and_only_see_upgrades_they_may(demo_app):
    demo_app.post("/api/users", json={"username": "cal-viewer", "source": "local",
                                      "password": "a-long-password-123", "is_admin": False,
                                      "permissions": {"inventory": "view", "upgrades": "none"}})
    viewer = TestClient(demo_app.app)
    viewer.post("/api/auth/login", json={"username": "cal-viewer", "password": "a-long-password-123"})
    items = viewer.get("/api/calendar").json()["items"]
    assert items and not any(x["source"] == "upgrade" for x in items)
    body = {"title": "x", "kind": "change", "start": "2026-11-02T20:00:00", "end": "2026-11-02T21:00:00"}
    assert viewer.post("/api/calendar/events", json=body).status_code == 403


def test_ics_export(demo_app):
    r = demo_app.get("/api/calendar/export.ics")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar")
    text = r.text
    assert text.startswith("BEGIN:VCALENDAR\r\n") and text.endswith("END:VCALENDAR\r\n")
    assert text.count("BEGIN:VEVENT") == text.count("END:VEVENT") >= 6
    assert "SUMMARY:Change freeze: Month-end change freeze" in text
    assert all(len(line.encode()) <= 75 for line in text.split("\r\n"))
    assert demo_app.get("/api/calendar", params={"start": "2026-01-01T00:00:00",
                                                 "end": "2028-01-01T00:00:00"}).status_code == 422
