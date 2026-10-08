"""First-run setup: the setup code, the admin account, Active Directory, the certificate,
finishing, and installs that are already configured."""

import datetime
import stat

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient

from app.core.auth import User
from app.core.config import Settings
from app.main import create_app
from tests.conftest import ADMIN_PASSWORD, FakeFetcher

PASSWORD = "a-long-setup-pass"


@pytest.fixture
def fresh(tmp_path):
    """A brand-new install: no break-glass admin, no AD, no users."""
    s = Settings(_env_file=None, data_dir=tmp_path / "data", ldap_url="",
                 local_admin_password_hash="", scheduler_enabled=False).prepare()
    app = create_app(s, fetcher=FakeFetcher(), start_scheduler=False)
    with TestClient(app) as c:
        c.code = (s.data_dir / "setup-token").read_text().strip()
        c.settings = s
        yield c


def _h(c, code=None):
    return {"X-Setup-Code": c.code if code is None else code}


def _admin(c):
    r = c.post("/api/setup/admin", headers=_h(c),
               json={"username": "netadmin", "display_name": "Net Admin", "password": PASSWORD})
    assert r.status_code == 200, r.text


# --- the setup code ------------------------------------------------------------------------

def test_new_install_needs_setup_and_a_private_code(fresh):
    assert fresh.get("/api/setup/status").json() == {"needed": True}
    path = fresh.settings.data_dir / "setup-token"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert len(fresh.code) == 24 and fresh.code.count("-") == 4
    assert fresh.post("/api/setup/check-code", headers=_h(fresh)).json() == {"ok": True}
    # lower case and spaces are fine (it's typed by hand)
    assert fresh.post("/api/setup/check-code",
                      headers=_h(fresh, fresh.code.lower())).status_code == 200


def test_steps_need_the_code_and_guessing_is_throttled(fresh):
    body = {"username": "x", "password": PASSWORD}
    assert fresh.post("/api/setup/admin", json=body).status_code == 403  # no code: a wrong guess
    for _ in range(4):
        assert fresh.post("/api/setup/check-code", headers=_h(fresh, "WRONG")).status_code == 403
    # five wrong guesses: even the right code is refused for a while
    assert fresh.post("/api/setup/check-code", headers=_h(fresh)).status_code == 429
    assert fresh.get("/api/setup/ad").status_code == 401  # no code, no login


# --- admin account and finish ------------------------------------------------------------

def test_admin_account_then_finish(fresh):
    r = fresh.post("/api/setup/admin", headers=_h(fresh),
                   json={"username": "netadmin", "password": "short"})
    assert r.status_code == 422
    assert fresh.post("/api/setup/finish", headers=_h(fresh)).status_code == 409  # no admin yet
    _admin(fresh)
    assert fresh.get("/api/setup/status").json() == {"needed": True}  # until Finish
    _admin(fresh)  # repeating the step (e.g. after a typo) replaces it
    assert fresh.post("/api/setup/finish", headers=_h(fresh)).json() == {"ok": True}

    assert fresh.get("/api/setup/status").json() == {"needed": False}
    assert not (fresh.settings.data_dir / "setup-token").exists()
    assert fresh.post("/api/setup/admin", headers=_h(fresh),
                      json={"username": "evil", "password": PASSWORD}).status_code == 409

    me = fresh.post("/api/auth/login", json={"username": "netadmin", "password": PASSWORD})
    assert me.status_code == 200 and me.json()["role"] == "admin"
    acts = [e["action"] for e in fresh.get("/api/audit").json()]
    assert {"setup.admin", "setup.finished"} <= set(acts)


def test_existing_install_never_shows_setup(client, settings):
    assert client.get("/api/setup/status").json() == {"needed": False}
    assert not (settings.data_dir / "setup-token").exists()
    assert client.post("/api/setup/check-code", headers={"X-Setup-Code": "X"}).status_code == 409


# --- Active Directory --------------------------------------------------------------------

AD = {"ldap_url": "ldaps://dc1.corp.local", "ldap_domain": "corp.local",
      "ldap_base_dn": "DC=corp,DC=local", "ldap_admin_group": "CN=NetOps-Admins,DC=corp,DC=local",
      "ldap_viewer_group": "CN=NetOps-Viewers,DC=corp,DC=local", "ldap_upgrader_group": ""}


def test_ad_settings_saved_and_used_for_logins(fresh, monkeypatch):
    assert fresh.put("/api/setup/ad", headers=_h(fresh),
                     json={**AD, "ldap_url": "http://dc1"}).status_code == 422
    r = fresh.put("/api/setup/ad", headers=_h(fresh), json=AD)
    assert r.status_code == 200 and r.json()["values"]["ldap_url"] == "ldaps://dc1.corp.local"
    assert fresh.app.state.authenticator.settings.ldap_base_dn == "DC=corp,DC=local"
    # setup isn't finished by saving AD: it still needs the code
    assert fresh.get("/api/setup/status").json() == {"needed": True}

    seen = {}

    def fake_ldap(self, username, password, groups=True):
        seen["url"] = self.settings.ldap_url
        return User(username="jsmith", role="admin", display_name="J Smith", can_upgrade=True,
                    source="ad-group") if password == "right" else None

    monkeypatch.setattr("app.core.auth.Authenticator._ldap_authenticate", fake_ldap)
    r = fresh.post("/api/setup/ad/test", headers=_h(fresh),
                   json={**AD, "ldap_url": "ldaps://dc2.corp.local", "username": "jsmith",
                         "password": "right"}).json()
    assert r["ok"] and "J Smith: admin" in r["message"] and seen["url"] == "ldaps://dc2.corp.local"
    r = fresh.post("/api/setup/ad/test", headers=_h(fresh),
                   json={**AD, "username": "jsmith", "password": "wrong"}).json()
    assert not r["ok"]


def test_netops_env_wins_over_the_gui(tmp_path):
    s = Settings(_env_file=None, data_dir=tmp_path / "data", ldap_url="ldaps://env-dc",
                 ldap_domain="env.local", ldap_base_dn="DC=env", local_admin_user="admin",
                 local_admin_password_hash="", scheduler_enabled=False).prepare()
    app = create_app(s, fetcher=FakeFetcher(), start_scheduler=False)
    with TestClient(app) as c:
        assert c.get("/api/setup/status").json() == {"needed": False}  # AD set in netops.env
        from app.core import appsettings
        from app.core.db import session_scope
        with session_scope() as db:
            appsettings.save(db, {"ldap_url": "ldaps://gui-dc", "ldap_admin_group": "CN=G"}, "t")
        eff = app.state.authenticator.settings
        assert eff.ldap_url == "ldaps://env-dc" and eff.ldap_admin_group == "CN=G"


# --- certificate --------------------------------------------------------------------------

def _ca():
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Corp Issuing CA")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(1)
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    return key, cert


def _sign(ca, csr_or_key, days=365, start=-1):
    ca_key, ca_cert = ca
    now = datetime.datetime.now(datetime.timezone.utc)
    if isinstance(csr_or_key, x509.CertificateSigningRequest):
        subject, pub = csr_or_key.subject, csr_or_key.public_key()
        san = csr_or_key.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    else:
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "netops.corp.local")])
        pub, san = csr_or_key.public_key(), x509.SubjectAlternativeName(
            [x509.DNSName("netops.corp.local")])
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(ca_cert.subject)
            .public_key(pub).serial_number(x509.random_serial_number())
            .not_valid_before(now + datetime.timedelta(days=start))
            .not_valid_after(now + datetime.timedelta(days=days))
            .add_extension(san, critical=False).sign(ca_key, hashes.SHA256()))
    return (cert.public_bytes(serialization.Encoding.PEM)
            + ca_cert.public_bytes(serialization.Encoding.PEM)).decode()


def test_certificate_from_a_request(fresh):
    ca = _ca()
    r = fresh.post("/api/setup/certificate/request", headers=_h(fresh),
                   json={"names": ["netops.corp.local", "10.0.0.5"]})
    assert r.status_code == 200, r.text
    csr = x509.load_pem_x509_csr(r.json()["request"].encode())
    tls = fresh.settings.data_dir / "tls"
    assert stat.S_IMODE((tls / "pending.key").stat().st_mode) == 0o600
    assert fresh.get("/api/setup/certificate", headers=_h(fresh)).json()["request_pending"]

    r = fresh.post("/api/setup/certificate", headers=_h(fresh), json={"certificate": _sign(ca, csr)})
    assert r.status_code == 200, r.text
    info = r.json()
    assert info["names"] == ["netops.corp.local", "10.0.0.5"] and info["chain_length"] == 2
    assert not info["self_signed"]
    assert stat.S_IMODE((tls / "netops.key").stat().st_mode) == 0o600
    assert (tls / "netops.crt").read_text().count("BEGIN CERTIFICATE") == 2
    assert not (tls / "pending.key").exists()


def test_certificate_with_its_own_key_and_the_checks(fresh):
    ca = _ca()
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key_pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()).decode()
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    post = lambda body: fresh.post("/api/setup/certificate", headers=_h(fresh), json=body)  # noqa: E731
    assert post({"certificate": "nonsense", "key": key_pem}).status_code == 422
    assert "doesn't belong" in post({"certificate": _sign(ca, other), "key": key_pem}).text
    assert "expired" in post({"certificate": _sign(ca, key, days=-1, start=-30),
                              "key": key_pem}).text
    assert "Paste the private key" in post({"certificate": _sign(ca, key)}).text
    assert post({"certificate": _sign(ca, key), "key": key_pem}).status_code == 200


def test_after_setup_only_admins_change_settings(fresh):
    _admin(fresh)
    fresh.post("/api/setup/finish", headers=_h(fresh))
    assert fresh.get("/api/setup/ad").status_code == 401
    fresh.post("/api/auth/login", json={"username": "netadmin", "password": PASSWORD})
    assert fresh.get("/api/setup/ad").status_code == 200
    assert fresh.put("/api/setup/ad", json=AD).status_code == 200
    # a non-admin can't
    fresh.post("/api/users", json={"username": "viewer1", "source": "local",
                                   "password": PASSWORD, "preset": "viewer"})
    fresh.post("/api/auth/logout")
    fresh.post("/api/auth/login", json={"username": "viewer1", "password": PASSWORD})
    assert fresh.get("/api/setup/ad").status_code == 403


def test_configured_install_still_signs_in(client):
    assert ADMIN_PASSWORD  # the conftest admin still signs in on configured installs
    assert client.post("/api/auth/login", json={"username": "admin",
                                                "password": ADMIN_PASSWORD}).status_code == 200


def test_certificate_shows_what_the_root_service_reported(fresh):
    tls = fresh.settings.data_dir / "tls"
    tls.mkdir(parents=True, exist_ok=True)
    (tls / "apply-status").write_text("2026-10-08T10:00:00Z refused: the certificate has expired\n")
    r = fresh.get("/api/setup/certificate", headers=_h(fresh)).json()
    assert r["applied"].endswith("refused: the certificate has expired")
