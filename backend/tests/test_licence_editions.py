"""Editions, the Meraki device block, and the licence ledger (licence_tool, docs/selling.md)."""

import csv
import datetime

import pytest
from cryptography.hazmat.primitives import serialization

from app import licence_tool
from app.core import licence
from app.demo import meraki as fake
from tests.test_licence import KEY, TODAY, _lic, _set, signing_key  # noqa: F401 - fixture


def _install(admin, text):
    r = admin.post("/api/licence", json={"text": text})
    assert r.status_code == 200, r.text
    return r.json()


def test_editions_and_add_ons():
    assert licence.EDITIONS["essentials"][1] == ["backups", "syslog"]
    assert set(licence.EDITIONS["complete"][1]) == set(licence.MODULES)
    p = licence_tool.make_payload("Acme", TODAY, 250, modules=licence.EDITIONS["professional"][1] + ["monitoring"],
                                  edition="professional")
    assert licence.edition_label(p) == "Professional + Monitoring add-on"
    assert licence.edition_label({"modules": ["backups"]}) == "Custom"
    assert licence.edition_label({}) == "Complete" and licence.edition_label({"kind": "internal"}) == "Internal use"


def test_a_meraki_organisation_uses_a_block_of_devices(admin, credential):
    admin.app.state.meraki_fetch = fake.FakeDashboard()
    for i in range(1, 6):
        assert admin.post("/api/devices", json={"name": f"sw{i}", "address": f"10.0.0.{i}", "platform": "cisco_ios",
                                                "credential_id": credential["id"]}).status_code == 201
    _install(admin, _lic(devices=40))
    body = {"name": "Retail", "api_key": fake.KEY, "org_id": fake.ORG["id"]}
    assert admin.post("/api/monitoring/meraki/connections", json=body).status_code == 201
    s = admin.get("/api/licence").json()
    assert (s["devices"], s["physical_devices"], s["meraki_orgs"], s["meraki_devices_each"]) == (30, 5, 1, 25)
    r = admin.post("/api/monitoring/meraki/connections", json={**body, "name": "Second"})
    assert r.status_code == 403 and "Meraki organisation(s) at 25 each" in r.json()["detail"]
    # 10 left: a device still fits, then another Meraki block doesn't
    assert admin.post("/api/devices", json={"name": "sw9", "address": "10.0.0.9", "platform": "snmp_ups"}).status_code == 201
    # switched off, it no longer counts; switching it on again needs the room
    conn = admin.get("/api/monitoring/meraki").json()["connections"][0]
    admin.put(f"/api/monitoring/meraki/connections/{conn['id']}", json={**body, "enabled": False})
    assert admin.get("/api/licence").json()["devices"] == 6
    # a licence can set its own block size
    _install(admin, licence_tool.make(KEY, "Acme", TODAY + datetime.timedelta(days=30), 40, meraki_devices=10))
    r = admin.put(f"/api/monitoring/meraki/connections/{conn['id']}", json={**body, "enabled": True})
    assert r.status_code == 200 and admin.get("/api/licence").json()["devices"] == 16


def test_settings_shows_the_edition(admin):
    s = _install(admin, licence_tool.make(KEY, "Acme", TODAY + datetime.timedelta(days=30), 50,
                                          modules=["backups", "syslog", "monitoring"], edition="essentials"))
    assert s["edition"] == "Essentials + Monitoring add-on" and s["licence"]["edition"] == s["edition"]
    assert "monitoring" in s["modules"] and "firmware" not in s["modules"]


@pytest.fixture
def key_file(tmp_path):
    path = tmp_path / "signing.key"
    path.write_bytes(KEY.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    return path


def test_ledger_records_every_licence_and_renews_from_it(tmp_path, key_file, capsys, monkeypatch):
    ledger = tmp_path / "OneDrive" / "NetCairn" / "licences.csv"
    monkeypatch.setenv("NETCAIRN_LEDGER", str(ledger))
    out = tmp_path / "acme.lic"
    assert licence_tool.main(["sign", "--key", str(key_file), "--customer", "=Acme Ltd", "--edition", "professional",
                              "--add", "monitoring", "--devices", "250", "--expires", "2027-10-31",
                              "--install-id", "1A2B-3C4D-5E6F-7A8B", "--email", "it@acme.example",
                              "--stripe", "cus_123", "--out", str(out)]) == 0
    first = licence.parse(out.read_text())
    assert first["edition"] == "professional" and first["max_devices"] == 250
    assert set(first["modules"]) == {"backups", "syslog", "firmware", "upgrades", "circuits", "monitoring"}
    rows = list(csv.DictReader(ledger.open()))
    assert rows[0]["customer"] == "'=Acme Ltd"  # formula-like text stays text in Excel
    assert rows[0]["plan"] == "Professional + Monitoring add-on" and rows[0]["stripe"] == "cus_123"
    # renewal: a new end date and more devices, everything else from the ledger
    out2 = tmp_path / "acme-2028.lic"
    assert licence_tool.main(["sign", "--key", str(key_file), "--from", first["id"].lower(),
                              "--expires", "2028-10-31", "--devices", "unlimited", "--out", str(out2)]) == 0
    second = licence.parse(out2.read_text())
    assert second["max_devices"] is None and second["install_id"] == "1A2B-3C4D-5E6F-7A8B"
    assert set(second["modules"]) == set(first["modules"]) and second["customer"] == "=Acme Ltd"
    rows = licence_tool.read_ledger(ledger)
    assert rows[1]["replaces"] == first["id"] and rows[1]["email"] == "it@acme.example"
    capsys.readouterr()
    assert licence_tool.main(["ledger", "--customer", "acme"]) == 0
    listing = capsys.readouterr().out
    assert f"{first['id']}" in listing and "(replaced)" in listing and "unlimited" in listing
    # mistakes are refused
    assert licence_tool.main(["sign", "--key", str(key_file), "--from", "NOPE", "--expires", "2028-01-01"]) == 2
    assert licence_tool.main(["sign", "--key", str(key_file), "--customer", "X", "--edition", "gold",
                              "--devices", "5", "--expires", "2028-01-01"]) == 2
    assert licence_tool.main(["sign", "--key", str(key_file), "--customer", "X", "--add", "coffee",
                              "--devices", "5", "--expires", "2028-01-01"]) == 2
    assert licence_tool.main(["sign", "--key", str(key_file), "--customer", "X", "--devices", "-3",
                              "--expires", "2028-01-01"]) == 2
