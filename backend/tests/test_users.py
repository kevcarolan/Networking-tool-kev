"""Users added by an admin, per-area permissions, and the activity report."""

import pytest

from app.core import permissions as pm
from app.core.auth import User

PW = "a-long-local-password"


def _login(client, username, password=PW):
    client.post("/api/auth/logout")
    return client.post("/api/auth/login", json={"username": username, "password": password})


def _add(admin, username, source="local", password=PW, **body):
    r = admin.post("/api/users", json={"username": username, "source": source,
                                       "password": password, **body})
    assert r.status_code == 201, r.text
    return r.json()


def test_permission_levels_are_ordered():
    p = pm.normalise({"backups": "configs"})
    assert pm.at_least(p, "backups", "run") and pm.at_least(p, "backups", "view")
    assert not pm.at_least(p, "backups", "manage")
    assert p["circuits"] == "none" and p["inventory"] == "view"
    assert pm.normalise({"upgrades": "bogus"})["upgrades"] == "none"


def test_roles_from_ad_groups_map_to_permissions():
    assert User("a", role="admin", can_upgrade=True).perms == pm.full()
    admin_no_upgrades = User("a", role="admin", can_upgrade=False)
    assert admin_no_upgrades.perms["upgrades"] == "view" and not admin_no_upgrades.can_upgrade
    upgrader = User("v", role="viewer", can_upgrade=True)
    assert upgrader.can("upgrades", "live") and not upgrader.can("circuits", "manage")


def test_local_user_login_and_permissions(admin, client, device):
    u = _add(admin, "ops1", preset="operator", display_name="Ops One")
    assert u["permissions"]["backups"] == "run" and not u["is_admin"]
    me = _login(client, "OPS1").json()  # case doesn't matter
    assert me["username"] == "ops1" and me["perms"]["backups"] == "run" and me["source"] == "local"
    assert client.post(f"/api/backup/devices/{device['id']}/run").status_code == 202
    assert client.get(f"/api/backup/devices/{device['id']}/versions").status_code == 403
    assert client.put(f"/api/backup/devices/{device['id']}/settings",
                      json={"frequency_minutes": 60, "enabled": True}).status_code == 403
    assert client.post("/api/devices", json={"name": "x", "address": "10.9.9.9",
                                             "platform": "cisco_ios"}).status_code == 403
    assert client.get("/api/users").status_code == 403
    assert client.get("/api/activity").status_code == 403
    assert _login(client, "ops1", "wrong-password-123").status_code == 401


def test_changes_apply_to_a_signed_in_user_at_once(app, admin, credential):
    from fastapi.testclient import TestClient

    u = _add(admin, "viewer1", preset="viewer")
    with TestClient(app) as other:
        assert _login(other, "viewer1").status_code == 200
        assert other.get("/api/circuits").status_code == 200
        assert other.get("/api/credentials").status_code == 403
        admin.put(f"/api/users/{u['id']}", json={"permissions": {"inventory": "manage",
                                                                 "circuits": "none"}})
        assert other.get("/api/credentials").status_code == 200  # no new sign-in needed
        assert other.get("/api/circuits").status_code == 403
        admin.put(f"/api/users/{u['id']}", json={"enabled": False})
        assert other.get("/api/auth/me").status_code == 401
        assert _login(other, "viewer1").status_code == 401


def test_dry_run_upgrader_cannot_create_live_jobs(admin, client):
    _add(admin, "dry1", permissions={"firmware": "view", "upgrades": "dry_run"})
    _login(client, "dry1")
    r = client.post("/api/firmware/jobs", json={"device_id": 1, "image_id": 1, "live": True})
    assert r.status_code == 403 and "live" in r.json()["detail"]
    r = client.post("/api/firmware/jobs", json={"device_id": 999, "image_id": 999})
    assert r.status_code == 422  # allowed to try a dry run; the device doesn't exist


def test_user_validation(admin, client):
    assert admin.post("/api/users", json={"username": "CORP\\jsmith", "source": "local",
                                          "password": PW}).status_code == 422
    assert admin.post("/api/users", json={"username": "short", "source": "local",
                                          "password": "short"}).status_code == 422
    assert admin.post("/api/users", json={"username": "admin", "source": "local",
                                          "password": PW}).status_code == 409  # break-glass
    r = admin.post("/api/users", json={"username": "jsmith", "source": "ad"})
    assert r.status_code == 422 and "Active Directory" in r.json()["detail"]  # no LDAP here
    _add(admin, "dup")
    assert admin.post("/api/users", json={"username": "DUP", "source": "local",
                                          "password": PW}).status_code == 409
    assert admin.post("/api/users", json={"username": "p1", "source": "local", "password": PW,
                                          "permissions": {"backups": "everything"}}).status_code == 422


def test_admin_cannot_lock_themself_out(admin, client):
    a = _add(admin, "boss", preset="admin")
    _login(client, "boss")
    assert client.put(f"/api/users/{a['id']}", json={"preset": "viewer"}).status_code == 409
    assert client.delete(f"/api/users/{a['id']}").status_code == 409
    assert client.get("/api/users").status_code == 200


def test_password_reset_and_own_change(admin, client):
    u = _add(admin, "loc1", preset="viewer")
    assert admin.post(f"/api/users/{u['id']}/password",
                      json={"password": "another-long-password"}).status_code == 200
    assert _login(client, "loc1").status_code == 401
    assert _login(client, "loc1", "another-long-password").status_code == 200
    assert client.post("/api/auth/password", json={"current": "nope", "new": PW}).status_code == 403
    assert client.post("/api/auth/password", json={"current": "another-long-password",
                                                   "new": "x"}).status_code == 422
    assert client.post("/api/auth/password", json={"current": "another-long-password",
                                                   "new": PW}).status_code == 200
    assert _login(client, "loc1").status_code == 200


def test_ad_user_added_in_netops_uses_ad_password(app, settings, admin, client, monkeypatch):
    from app.core.db import session_scope
    from app.core.models import UserAccount

    with session_scope() as db:
        db.add(UserAccount(username="jsmith", source="ad", permissions='{"circuits": "manage"}'))
    auth = app.state.authenticator
    auth.settings.ldap_url = "ldaps://dc.example"
    seen = {}

    def fake_ldap(username, password, groups=True):
        seen["groups"] = groups
        return User(username="jsmith", display_name="J Smith", source="ad") if password == "ad-pw" else None

    monkeypatch.setattr(auth, "_ldap_authenticate", fake_ldap)
    assert _login(client, "CORP\\jsmith", "wrong").status_code == 401
    me = _login(client, "CORP\\jsmith", "ad-pw").json()
    assert seen["groups"] is False  # NetOps decides the permissions, not the AD groups
    assert me["perms"]["circuits"] == "manage" and me["perms"]["upgrades"] == "none"
    assert me["display_name"] == "J Smith"


def test_activity_report(admin, client, device, credential):
    _add(admin, "ops2", preset="operator")
    _login(client, "ops2")
    client.post(f"/api/backup/devices/{device['id']}/run")
    _login(client, "admin", "correct-horse-battery")
    data = client.get("/api/activity").json()
    by_user = {s["username"]: s for s in data["summary"]}
    assert by_user["ops2"]["backups_run"] == 1 and by_user["ops2"]["logins"] == 1
    assert by_user["admin"]["changes"] >= 3  # credential, device, user
    assert any(b["by"] == "ops2" for b in data["backups"])
    only = client.get("/api/activity", params={"user": "ops2", "area": "backups"}).json()
    assert [e["action"] for e in only["events"]] == ["backup.run"]
    csv = client.get("/api/activity.csv", params={"user": "ops2"}).text
    assert csv.splitlines()[0] == "Time (UTC),User,Area,Action,Detail" and "backup.run" in csv


def test_users_meta(admin):
    meta = admin.get("/api/users/meta").json()
    assert set(meta["presets"]) == {"viewer", "operator", "upgrader", "admin"}
    assert meta["levels"]["upgrades"] == ["none", "view", "dry_run", "live"]
    assert meta["break_glass_user"] == "admin" and meta["ldap_enabled"] is False


@pytest.mark.parametrize("path", ["/api/circuits", "/api/firmware/jobs", "/api/backup/devices",
                                  "/api/firmware/devices"])
def test_no_access_level_blocks_reading(admin, client, path):
    _add(admin, "nobody", permissions={a: lv[0] for a, lv in pm.LEVELS.items()})
    _login(client, "nobody")
    assert client.get(path).status_code == 403
    assert client.get("/api/devices").status_code == 200  # everyone sees the device list
