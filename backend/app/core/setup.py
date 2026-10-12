"""First-run setup, and the settings an admin can change later (Settings page).

A new install has no way to sign in, so the first visit shows the setup screen. To stop
whoever reaches the page first from taking over the server, every setup step needs the
**setup code**: a one-time code the app writes to <data dir>/setup-token, readable only
on the server (sudo cat /var/lib/netops/setup-token). It is deleted when setup finishes.

Steps: 1. an admin account (a local user); 2. Active Directory (optional, with a test
login); 3. the certificate (optional): upload one, or have the server make a key and a
certificate request for your CA. The certificate is saved in <data dir>/tls/; a small
root-owned service (deploy/netops-tls.*) checks it and installs it for nginx.

An install that already has a way in (a break-glass admin, AD in netops.env, or an admin
user) counts as set up and never shows the screen.

After setup, admins use the same AD and certificate endpoints from the Settings page.
"""

import datetime
import hmac
import ipaddress
import logging
import os
import re
import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import appsettings
from app.core.audit import audit
from app.core.auth import MIN_PASSWORD, Authenticator, account_key, current_user
from app.core.config import Settings
from app.core.crypto import hash_password
from app.core.db import get_db, session_scope, utcnow

log = logging.getLogger(__name__)
# A DNS name for a certificate: letters, digits, hyphens and dots (a leading "*." for a wildcard)
_DNS_NAME = re.compile(r"(\*\.)?[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*")

_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I/L


# --- is setup needed? -----------------------------------------------------------

def needed(settings: Settings, db: Session) -> bool:
    from app.core.models import UserAccount

    if appsettings.stored(db).get(appsettings.SETUP_DONE):
        return False
    # (an admin made by this setup doesn't count: setup goes on until "Finish")
    has_admin = db.scalar(select(UserAccount.id).where(UserAccount.is_admin.is_(True),
                                                       UserAccount.enabled.is_(True),
                                                       UserAccount.created_by != "setup"))
    if settings.local_admin_password_hash or settings.ldap_url or has_admin:
        # An install from before the setup screen, configured in netops.env
        appsettings.save(db, {appsettings.SETUP_DONE: utcnow().isoformat() + " (existing install)"},
                         "system")
        return False
    return True


def token_file(settings: Settings) -> Path:
    return settings.data_dir / "setup-token"


def ensure_token(settings: Settings) -> None:
    """Called at startup: create the setup code if setup is needed, and say where it is."""
    with session_scope() as db:
        if not needed(settings, db):
            token_file(settings).unlink(missing_ok=True)
            return
    path = token_file(settings)
    if not path.exists():
        code = "-".join("".join(secrets.choice(_CODE_ALPHABET) for _ in range(4))
                        for _ in range(5))
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(code + "\n")
    log.warning("First-run setup is waiting: open the web page and enter the setup code from "
                "%s (on the server: sudo cat %s)", path, path)


def _code_matches(settings: Settings, given: str) -> bool:
    path = token_file(settings)
    if not given or not path.exists():
        return False
    expected = path.read_text().strip().upper()
    given = given.strip().upper().replace(" ", "")
    return hmac.compare_digest(expected.encode(), given.encode())


# --- who may use these endpoints ------------------------------------------------------

def _check_code(request: Request, code: str, db: Session) -> None:
    settings = request.app.state.settings
    throttle = request.app.state.login_throttle
    key = f"setup|{request.client.host if request.client else 'unknown'}"
    if throttle.blocked(key):
        raise HTTPException(429, "Too many wrong setup codes, try again later")
    if not needed(settings, db):
        raise HTTPException(409, "Setup is already finished: sign in instead")
    if not _code_matches(settings, code):
        throttle.fail(key)
        audit(db, "setup", "setup.code_wrong", f"from {key.split('|')[1]}")
        db.commit()  # kept although the request fails
        raise HTTPException(403, "That setup code isn't right")


def setup_only(request: Request, x_setup_code: str = Header(default=""),
               db: Session = Depends(get_db)) -> str:
    """Only while setup isn't finished, with the setup code."""
    _check_code(request, x_setup_code, db)
    return "setup"


def setup_or_admin(request: Request, x_setup_code: str = Header(default=""),
                   db: Session = Depends(get_db)) -> str:
    """The setup code during setup, an admin afterwards. Returns who is acting."""
    if x_setup_code:
        _check_code(request, x_setup_code, db)
        return "setup"
    user = current_user(request)
    if not user.is_admin:
        raise HTTPException(403, "Administrator role required")
    return user.username


router = APIRouter(prefix="/api/setup", tags=["setup"])


@router.get("/status")
def status(request: Request, db: Session = Depends(get_db)):
    """Public: only says whether the setup screen should show."""
    return {"needed": needed(request.app.state.settings, db)}


@router.post("/check-code")
def check_code(who: str = Depends(setup_only)):
    return {"ok": True}


# --- step 1: the admin account -------------------------------------------------------

class AdminIn(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    display_name: str = Field(default="", max_length=200)
    password: str = Field(max_length=200)


@router.post("/admin")
def create_admin(body: AdminIn, db: Session = Depends(get_db), who: str = Depends(setup_only)):
    from app.core.models import UserAccount
    from app.core.users import _USERNAME

    name = account_key(body.username)
    if not _USERNAME.match(name):
        raise HTTPException(422, "Use a plain username: letters, digits, . _ -")
    if len(body.password) < MIN_PASSWORD:
        raise HTTPException(422, f"Use at least {MIN_PASSWORD} characters")
    acc = db.scalar(select(UserAccount).where(UserAccount.username == name))
    if acc is not None and acc.created_by != "setup":
        raise HTTPException(409, f"User '{name}' already exists")
    if acc is None:  # (setup may be repeated before it is finished, e.g. a typo)
        acc = UserAccount(username=name, source="local", is_admin=True, created_by="setup")
        db.add(acc)
    acc.display_name = body.display_name.strip() or name
    acc.password_hash, acc.password_changed_at = hash_password(body.password), utcnow()
    acc.enabled, acc.is_admin, acc.updated_by = True, True, "setup"
    audit(db, "setup", "setup.admin", f"local admin {name}")
    return {"username": name}


# --- step 2: Active Directory --------------------------------------------------------------

class AdIn(BaseModel):
    ldap_url: str = Field(default="", max_length=300)
    ldap_domain: str = Field(default="", max_length=200)
    ldap_base_dn: str = Field(default="", max_length=500)
    ldap_admin_group: str = Field(default="", max_length=500)
    ldap_viewer_group: str = Field(default="", max_length=500)
    ldap_upgrader_group: str = Field(default="", max_length=500)
    ca_pem: str = Field(default="", max_length=100_000)  # empty: keep the one saved before


class AdTest(AdIn):
    username: str = Field(max_length=200)
    password: str = Field(max_length=200)


def _ad_view(settings: Settings, db: Session) -> dict:
    eff = appsettings.effective(settings, db)
    return {"values": {k: getattr(eff, k) for k in appsettings.LDAP_KEYS},
            "from_env": sorted(appsettings.from_env(settings)),
            "ca_saved": (settings.data_dir / "ad-ca.pem").exists()}


@router.get("/ad")
def get_ad(request: Request, db: Session = Depends(get_db), who: str = Depends(setup_or_admin)):
    return _ad_view(request.app.state.settings, db)


def _validate_ad(body: AdIn) -> None:
    url = body.ldap_url.strip().lower()
    if url and not url.startswith(("ldaps://", "ldap://")):
        raise HTTPException(422, "The server must start with ldaps:// (or ldap://, which "
                                 "is upgraded with StartTLS)")
    if url and not (body.ldap_domain.strip() and body.ldap_base_dn.strip()):
        raise HTTPException(422, "Fill in the domain and the base DN too")
    if body.ca_pem.strip():
        from cryptography import x509
        try:
            x509.load_pem_x509_certificates(body.ca_pem.encode())
        except ValueError:
            raise HTTPException(422, "The CA certificate isn't a PEM certificate") from None


def _candidate(settings: Settings, body: AdIn, ca_file: str) -> Settings:
    values = {k: getattr(body, k).strip() for k in appsettings.LDAP_KEYS if k != "ldap_ca_file"}
    values["ldap_ca_file"] = ca_file
    locked = appsettings.from_env(settings)
    return settings.model_copy(update={k: v for k, v in values.items() if k not in locked})


@router.put("/ad")
def save_ad(body: AdIn, request: Request, db: Session = Depends(get_db),
            who: str = Depends(setup_or_admin)):
    settings: Settings = request.app.state.settings
    _validate_ad(body)
    ca_path = settings.data_dir / "ad-ca.pem"
    if body.ca_pem.strip():
        ca_path.write_text(body.ca_pem.strip() + "\n")
    values = {k: getattr(body, k).strip() for k in appsettings.LDAP_KEYS if k != "ldap_ca_file"}
    values["ldap_ca_file"] = str(ca_path) if ca_path.exists() else ""
    locked = appsettings.from_env(settings)
    appsettings.save(db, {k: v for k, v in values.items() if k not in locked}, who)
    audit(db, who, "settings.ad", f"server {body.ldap_url.strip() or '(none)'}, "
                                  f"admin group {body.ldap_admin_group.strip() or '(none)'}")
    return _ad_view(settings, db)


# --- site and defaults --------------------------------------------------------------

def _options_view(settings: Settings) -> list[dict]:
    locked = settings.record_env()
    default = Settings.model_fields
    return [{"key": o.key, "label": o.label, "kind": o.kind.__name__, "low": o.low,
             "high": o.high, "help": o.help, "value": getattr(settings, o.key),
             "default": default[o.key].default, "locked": o.key in locked}
            for o in appsettings.OPTIONS]


@router.get("/options")
def get_options(request: Request, db: Session = Depends(get_db),
                who: str = Depends(setup_or_admin)):
    settings: Settings = request.app.state.settings
    appsettings.apply(settings, db)
    return _options_view(settings)


@router.put("/options")
def save_options(body: dict, request: Request, db: Session = Depends(get_db),
                 who: str = Depends(setup_or_admin)):
    settings: Settings = request.app.state.settings
    locked = settings.record_env()
    by_key = {o.key: o for o in appsettings.OPTIONS}
    values, changed = {}, []
    for key, value in body.items():
        option = by_key.get(key)
        if option is None:
            raise HTTPException(422, f"Unknown setting '{key}'")
        if key in locked:
            continue  # netops.env wins; the GUI shows it as locked
        try:
            values[key] = appsettings.check_option(option, value)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        if values[key] != appsettings.check_option(option, getattr(settings, key)):
            changed.append(f"{key}={values[key]}")
    appsettings.save(db, values, who)
    db.flush()
    appsettings.apply(settings, db)
    if changed:
        audit(db, who, "settings.options", ", ".join(changed))
    return _options_view(settings)


@router.post("/ad/test")
def test_ad(body: AdTest, request: Request, who: str = Depends(setup_or_admin)):
    """Sign in to AD with these settings (not saved yet) and show what the user would get."""
    settings: Settings = request.app.state.settings
    _validate_ad(body)
    ca_file = ""
    if body.ca_pem.strip():
        tmp = settings.data_dir / "ad-ca.test.pem"
        tmp.write_text(body.ca_pem.strip() + "\n")
        ca_file = str(tmp)
    elif (settings.data_dir / "ad-ca.pem").exists():
        ca_file = str(settings.data_dir / "ad-ca.pem")
    candidate = _candidate(settings, body, ca_file)
    if not candidate.ldap_url:
        raise HTTPException(422, "Enter the AD server first")
    try:
        user = Authenticator(candidate)._ldap_authenticate(body.username.strip(), body.password)
    except Exception as exc:  # noqa: BLE001 - shown to the admin setting it up
        return {"ok": False, "message": f"Could not sign in: {type(exc).__name__}: {exc}"[:500]}
    if user is None:
        return {"ok": False, "message": "AD refused the login, or the user isn't in an allowed "
                                        "group (check the base DN and the group DNs)"}
    return {"ok": True, "message": f"Signed in as {user.display_name}: "
                                   f"{'admin' if user.is_admin else 'viewer'}"
                                   f"{', may run upgrades' if user.can_upgrade else ''}"}


# --- step 3: the certificate ------------------------------------------------------------

def tls_dir(settings: Settings) -> Path:
    return settings.data_dir / "tls"


def _write_private(path: Path, data: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)


def _cert_info(pem: bytes) -> dict:
    from cryptography import x509

    chain = x509.load_pem_x509_certificates(pem)
    leaf = chain[0]
    try:
        san = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        names = [str(n) for n in san.get_values_for_type(x509.DNSName)] + \
                [str(n) for n in san.get_values_for_type(x509.IPAddress)]
    except x509.ExtensionNotFound:
        names = []
    return {"subject": leaf.subject.rfc4514_string(), "issuer": leaf.issuer.rfc4514_string(),
            "names": names, "not_before": leaf.not_valid_before_utc.isoformat(),
            "not_after": leaf.not_valid_after_utc.isoformat(),
            "self_signed": leaf.issuer == leaf.subject, "chain_length": len(chain)}


@router.get("/certificate")
def get_certificate(request: Request, who: str = Depends(setup_or_admin)):
    d = tls_dir(request.app.state.settings)
    crt = d / "netops.crt"
    status_file = request.app.state.settings.tls_status_file  # by the root service
    return {"certificate": _cert_info(crt.read_bytes()) if crt.exists() else None,
            "applied": status_file.read_text().strip()[:500] if status_file.exists() else "",
            "request_pending": (d / "pending.key").exists(),
            "request": (d / "pending.csr").read_text() if (d / "pending.csr").exists() else ""}


class CsrIn(BaseModel):
    names: list[str] = Field(min_length=1, max_length=10)  # DNS names or IP addresses


@router.post("/certificate/request")
def make_request(body: CsrIn, request: Request, db: Session = Depends(get_db),
                 who: str = Depends(setup_or_admin)):
    """Make a private key on the server (it never leaves it) and a request for the CA."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    names = [n.strip().lower() for n in body.names if n.strip()]
    if not names:
        raise HTTPException(422, "Enter the server's DNS name")
    alt = []
    for n in names:
        try:
            alt.append(x509.IPAddress(ipaddress.ip_address(n)))
        except ValueError:
            if not _DNS_NAME.fullmatch(n) or not all(len(p) < 64 for p in n.split(".")):
                raise HTTPException(422, f"'{n}' isn't a valid DNS name") from None
            alt.append(x509.DNSName(n))
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    try:
        csr = (x509.CertificateSigningRequestBuilder()
               .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, names[0])]))
               .add_extension(x509.SubjectAlternativeName(alt), critical=False)
               .sign(key, hashes.SHA256()))
    except ValueError as exc:  # e.g. a first name over 64 characters, or not plain ASCII
        raise HTTPException(422, f"Can't make a request for these names: {exc}") from None
    d = tls_dir(request.app.state.settings)
    _write_private(d / "pending.key", key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    pem = csr.public_bytes(serialization.Encoding.PEM)
    _write_private(d / "pending.csr", pem, 0o640)
    audit(db, who, "settings.certificate_request", ", ".join(names))
    return {"request": pem.decode(), "names": names}


class CertIn(BaseModel):
    certificate: str = Field(max_length=200_000)  # the certificate, then any intermediates
    key: str = Field(default="", max_length=20_000)  # empty: the key made with the request


@router.post("/certificate")
def install_certificate(body: CertIn, request: Request, db: Session = Depends(get_db),
                        who: str = Depends(setup_or_admin)):
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization

    d = tls_dir(request.app.state.settings)
    try:
        chain = x509.load_pem_x509_certificates(body.certificate.strip().encode())
    except ValueError:
        raise HTTPException(422, "That isn't a PEM certificate (-----BEGIN CERTIFICATE-----)") from None
    if body.key.strip():
        key_pem = body.key.strip().encode() + b"\n"
    elif (d / "pending.key").exists():
        key_pem = (d / "pending.key").read_bytes()
    else:
        raise HTTPException(422, "Paste the private key too, or make a request first")
    try:
        key = serialization.load_pem_private_key(key_pem, password=None)
    except (ValueError, TypeError):
        raise HTTPException(422, "The private key can't be read (it must be PEM and not "
                                 "password-protected)") from None
    leaf = chain[0]
    pub = serialization.PublicFormat.SubjectPublicKeyInfo
    if leaf.public_key().public_bytes(serialization.Encoding.PEM, pub) != \
            key.public_key().public_bytes(serialization.Encoding.PEM, pub):
        raise HTTPException(422, "The certificate doesn't belong to this private key")
    now = datetime.datetime.now(datetime.timezone.utc)
    if leaf.not_valid_after_utc <= now:
        raise HTTPException(422, "The certificate has expired")
    if leaf.not_valid_before_utc > now:
        raise HTTPException(422, "The certificate isn't valid yet (check the server's clock)")
    pem_chain = b"".join(c.public_bytes(serialization.Encoding.PEM) for c in chain)
    _write_private(d / "netops.key", key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    _write_private(d / "netops.crt", pem_chain, 0o640)  # written last: it triggers the install
    for f in ("pending.key", "pending.csr"):
        (d / f).unlink(missing_ok=True)
    info = _cert_info(pem_chain)
    audit(db, who, "settings.certificate", f"{info['subject']}, valid until {info['not_after']}")
    return info


# --- finish -----------------------------------------------------------------------------

@router.post("/finish")
def finish(request: Request, db: Session = Depends(get_db), who: str = Depends(setup_only)):
    from app.core.models import UserAccount

    if not db.scalar(select(UserAccount.id).where(UserAccount.is_admin.is_(True),
                                                  UserAccount.enabled.is_(True))):
        raise HTTPException(409, "Create the admin account first (step 1)")
    appsettings.save(db, {appsettings.SETUP_DONE: utcnow().isoformat()}, "setup")
    token_file(request.app.state.settings).unlink(missing_ok=True)
    audit(db, "setup", "setup.finished", "")
    return {"ok": True}
