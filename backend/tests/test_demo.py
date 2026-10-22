"""Demo mode: the simulated network is filled once, every page has data, an upgrade runs
end to end, a restart keeps what happened, and the demo never touches other data."""

import pytest

from app.core import licence
from app.demo import __main__ as demo
from app.demo import seed


@pytest.fixture
def quick(monkeypatch):
    monkeypatch.setattr(seed.time, "sleep", lambda s: None)  # no real waiting in tests
    monkeypatch.setattr(licence, "DEVELOPMENT", True)


def test_first_run_fills_every_page(tmp_path, quick):
    app, net, _worker = demo.build(tmp_path, 8799, scheduler=False)
    info = demo.first_run(app, net)
    assert len(info["ids"]) == len(seed.DEVICES) + len(seed.SNMP_DEVICES) and info["display_key"]
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        c.post("/api/auth/login", json={"username": seed.ADMIN_USER, "password": seed.ADMIN_PASSWORD})
        assert c.get("/api/auth/me").json()["demo"] is True
        b = c.get("/api/backup/summary").json()
        assert b["failed"] == len(seed.FAILING) and b["success"] == len(seed.DEVICES) - len(seed.FAILING)
        f = c.get("/api/firmware/summary").json()
        assert f["compliant"] and f["behind"] and f["check_failed"] == 0
        circuits = c.get("/api/circuits").json()
        statuses = [r["live_status"] for r in circuits["circuits"]]
        assert statuses.count("moved") == 1 and statuses.count("not_seen") == 1
        wrong = [r["device_name"] for r in circuits["circuits"] if r["rule_problems"]]
        assert wrong == ["CCTV-HQ1-05"]  # the rules: on VLAN 1, the list says 40
        assert circuits["scan"]["last_full"]["devices_failed"] == 0
        assert c.get("/api/licence").json()["mode"] == "development"
        # the SNMP-only devices: no backups, read with SNMP and their sensors
        rows = {r["device"]["name"]: r for r in c.get("/api/backup/devices").json()}
        assert all(rows[n]["backup"] is None for n, _, _ in seed.SNMP_DEVICES)
        ups = c.get(f"/api/monitoring/devices/{info['ids']['hq-ups1']}/health").json()
        assert {r["name"]: r["value"] for r in ups["readings"]}["UPS battery charge"] == 100
        # every address is a documentation address, never routed
        assert all(d["address"].startswith(("192.0.2.", "198.51.100.", "203.0.113."))
                   for d in c.get("/api/devices").json())
    assert demo.first_run(app, net) is None  # only once


def test_a_live_upgrade_runs_and_survives_a_restart(tmp_path, quick):
    app, net, _ = demo.build(tmp_path, 8799, scheduler=False)
    info = demo.first_run(app, net)
    svc = app.state.job_service
    from datetime import timedelta

    from fastapi.testclient import TestClient

    from app.core.db import utcnow

    with TestClient(app) as c:
        c.post("/api/auth/login", json={"username": seed.ADMIN_USER, "password": seed.ADMIN_PASSWORD})
        img = next(i for i in c.get("/api/firmware/images").json() if i["platform"] == "cisco_ios")
        now = utcnow()
        job = c.post("/api/firmware/jobs", json={
            "device_id": info["ids"]["hq-acc-sw3"], "image_id": img["id"], "live": True,
            "planned_start": (now - timedelta(minutes=5)).isoformat(),
            "planned_end": (now + timedelta(hours=1)).isoformat()}).json()
        assert svc.precheck(job["id"], "demo") == "ready"
        assert svc.start(job["id"], "demo") == "completed"
        app.state.firmware_service.check(info["ids"]["hq-acc-sw3"])
    # A restart builds a fresh simulator; it carries on from what the demo did.
    _app, fresh, _ = demo.build(tmp_path, 8799, scheduler=False)
    assert fresh.devices["hq-acc-sw3"].version == "17.09.04a"
    demo.resume(fresh)
    assert fresh.devices["hq-acc-sw3"].version == "17.12.04"


def test_the_demo_only_uses_its_own_folder(tmp_path, quick, monkeypatch):
    real = tmp_path / "real"
    real.mkdir()
    (real / "app.db").write_text("not a demo")
    with pytest.raises(SystemExit, match="already holds other data"):
        demo.main(["--data", str(real)])
    with pytest.raises(SystemExit, match="isn't a demo data folder"):
        demo.main(["--data", str(real), "--reset"])
    assert (real / "app.db").read_text() == "not a demo"


def test_failing_backups_are_on_purpose():
    class T:
        name, address = "bn-sw3", "192.0.2.27"
    with pytest.raises(Exception, match="unreachable"):
        seed.fetcher(T())
    T.name = "hq-acc-sw1"
    assert "hostname hq-acc-sw1" in seed.fetcher(T())

