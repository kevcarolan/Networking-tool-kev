"""Site settings and defaults on the Settings page: saving, checking, netops.env winning,
and the running services picking up a change."""

from fastapi.testclient import TestClient

from app.core import appsettings
from app.core.config import Settings
from app.core.crypto import hash_password
from app.main import create_app
from tests.conftest import ADMIN_PASSWORD, FakeFetcher
from tests.test_upgrade_jobs import _create, env  # noqa: F401  (fixture)


def _opts(client):
    return {o["key"]: o for o in client.get("/api/setup/options").json()}


def test_defaults_are_shown_and_can_be_changed(app, admin):
    opts = _opts(admin)
    assert opts["default_frequency_minutes"]["value"] == 1440
    assert opts["site_name"]["value"] == "" and not opts["site_name"]["locked"]
    r = admin.put("/api/setup/options", json={"site_name": " Acme Ltd - London DC ",
                                              "default_frequency_minutes": 60,
                                              "viewers_can_read_configs": True,
                                              "circuit_scan_schedule": "daily 03:30"})
    assert r.status_code == 200, r.text
    s = app.state.settings
    assert s.site_name == "Acme Ltd - London DC" and s.default_frequency_minutes == 60
    assert s.viewers_can_read_configs is True and s.circuit_scan_schedule == "daily 03:30"
    assert admin.get("/api/auth/me").json()["site_name"] == "Acme Ltd - London DC"
    audit = admin.get("/api/audit").json()[0]
    assert audit["action"] == "settings.options" and "default_frequency_minutes=60" in audit["detail"]


def test_new_devices_get_the_default_backup_frequency(admin, credential):
    admin.put("/api/setup/options", json={"default_frequency_minutes": 120})
    d = admin.post("/api/devices", json={"name": "sw9", "address": "10.0.0.9",
                                         "platform": "cisco_ios"}).json()
    assert admin.get(f"/api/backup/devices/{d['id']}").json()["backup"]["frequency_minutes"] == 120


def test_values_are_checked(admin):
    for body, message in [({"default_frequency_minutes": 1}, "between 15 and 10080"),
                          ({"upgrade_cpu_warn": "high"}, "a whole number"),
                          ({"viewers_can_read_configs": "yes"}, "yes or no"),
                          ({"circuit_scan_schedule": "every day"}, "should look like"),
                          ({"site_name": "x" * 101}, "at most 100"),
                          ({"upgrade_live_platforms": "cisco_ios"}, "Unknown setting")]:
        r = admin.put("/api/setup/options", json=body)
        assert r.status_code == 422 and message in r.json()["detail"], (body, r.text)


def test_netops_env_wins(tmp_path):
    s = Settings(_env_file=None, data_dir=tmp_path / "data", upgrade_cpu_warn=70,
                 scheduler_enabled=False,
                 local_admin_password_hash=hash_password(ADMIN_PASSWORD)).prepare()
    with TestClient(create_app(s, fetcher=FakeFetcher(), start_scheduler=False)) as c:
        c.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD})
        assert _opts(c)["upgrade_cpu_warn"]["locked"] is True
        r = c.put("/api/setup/options", json={"upgrade_cpu_warn": 95, "upgrade_mem_warn": 95})
        assert r.status_code == 200
        assert s.upgrade_cpu_warn == 70 and s.upgrade_mem_warn == 95


def test_saved_values_are_used_after_a_restart_and_by_the_worker(settings, admin):
    admin.put("/api/setup/options", json={"upgrade_backup_max_age_hours": 6,
                                          "history_retention_days": 30})
    worker_settings = Settings(_env_file=None, data_dir=settings.data_dir)
    appsettings.apply(worker_settings)  # what the worker does on each heartbeat
    assert worker_settings.upgrade_backup_max_age_hours == 6
    assert worker_settings.history_retention_days == 30


def test_back_to_the_default(app, admin):
    admin.put("/api/setup/options", json={"firmware_check_minutes": 120})
    admin.put("/api/setup/options", json={"firmware_check_minutes": 1440})
    assert app.state.settings.firmware_check_minutes == 1440


def test_only_admins(client, admin):
    admin.post("/api/users", json={"username": "viewer1", "source": "local",
                                   "password": "a-long-viewer-pass", "permissions": {}})
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"username": "viewer1", "password": "a-long-viewer-pass"})
    assert client.get("/api/setup/options").status_code == 403
    assert client.put("/api/setup/options", json={"site_name": "x"}).status_code == 403


def test_circuit_scan_follows_the_schedule_setting(app, admin):
    scan = app.state.circuit_scan
    admin.put("/api/setup/options", json={"circuit_scan_schedule": ""})
    assert scan.due_trigger() is None and scan.schedule is None
    admin.put("/api/setup/options", json={"circuit_scan_schedule": "daily 02:00"})
    scan.due_trigger()
    assert scan.schedule == (None, 2, 0)


def test_report_names_the_site(admin, env):  # noqa: F811
    job = _create(admin, env)
    admin.put("/api/setup/options", json={"site_name": "Acme <DC>"})
    page = admin.get(f"/api/firmware/jobs/{job['id']}/report.html").text
    assert "Generated by NetCairn for Acme &lt;DC&gt;." in page


def test_signing_in_returns_the_site_name(client, admin):
    admin.put("/api/setup/options", json={"site_name": "Acme Ltd"})
    client.post("/api/auth/logout")
    from tests.conftest import ADMIN_PASSWORD

    r = client.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD})
    assert r.json()["site_name"] == "Acme Ltd" and r.json()["demo"] is False
