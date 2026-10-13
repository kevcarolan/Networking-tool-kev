"""Login and permissions.

Who can sign in, in this order:
  1. the local break-glass admin (NETOPS_LOCAL_ADMIN_*): everything;
  2. a user an admin has added in NetOps (Users page, table ``users``):
     * source "ad": the password is checked against Active Directory,
     * source "local": the password is kept by NetOps (scrypt hash);
     their permissions are exactly what the admin set (permissions.py), and are read
     again on every request, so a change or a disabled account takes effect at once;
  3. any other AD user, from their AD groups (nested groups included), as before:
     * admin  - member of NETOPS_LDAP_ADMIN_GROUP: everything (upgrades, see below),
     * viewer - member of NETOPS_LDAP_VIEWER_GROUP (or any domain user if unset): view only,
     * upgrades - member of NETOPS_LDAP_UPGRADER_GROUP, or every admin when that group
       isn't set: may plan and run upgrade jobs (live included).
"""

import hashlib
import json
import logging
import secrets
import ssl
import threading
import time
from dataclasses import dataclass, field

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core import permissions as pm
from app.core.audit import audit
from app.core.config import Settings
from app.core.crypto import hash_password, verify_password
from app.core.db import get_db, session_scope, utcnow

log = logging.getLogger(__name__)

ADMIN, VIEWER = "admin", "viewer"
_IN_CHAIN = "1.2.840.113556.1.4.1941"  # AD rule that matches nested group membership


@dataclass
class User:
    username: str
    role: str = VIEWER  # "admin" (manages users, reads the activity log) or "viewer"
    display_name: str = ""
    can_upgrade: bool = False  # may plan and run upgrade jobs (derived from perms)
    perms: dict = field(default_factory=dict)  # area -> level (permissions.py)
    source: str = ""  # break-glass / local / ad / ad-group
    user_id: int | None = None  # a user added in NetOps

    def __post_init__(self):
        if not self.perms:  # from a role (AD groups): admin = everything, viewer = view
            base = pm.full() if self.role == ADMIN else dict(pm.PRESETS["viewer"]["perms"])
            base["upgrades"] = "live" if self.can_upgrade else "view"
            self.perms = base
        self.perms = pm.normalise(self.perms)
        self.can_upgrade = pm.at_least(self.perms, "upgrades", "dry_run")

    @property
    def is_admin(self) -> bool:
        return self.role == ADMIN

    def can(self, area: str, level: str) -> bool:
        return pm.at_least(self.perms, area, level)

    def out(self) -> dict:
        return {**self.__dict__, "levels": pm.LEVELS}


def account_key(username: str) -> str:
    """'CORP\\jsmith', 'jsmith@corp.local' and 'JSmith' -> 'jsmith'."""
    return username.strip().split("\\")[-1].split("@")[0].lower()


def user_from_account(acc, display: str = "") -> User:
    perms = pm.full() if acc.is_admin else json.loads(acc.permissions or "{}")
    return User(username=acc.username, role=ADMIN if acc.is_admin else VIEWER,
                display_name=display or acc.display_name or acc.username, perms=perms,
                source=acc.source, user_id=acc.id)


class LoginThrottle:
    """Blocks a username/address pair after repeated failed logins."""

    def __init__(self, max_failures: int = 5, window_seconds: int = 300):
        self.max_failures = max_failures
        self.window = window_seconds
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str) -> list[float]:
        cutoff = time.monotonic() - self.window
        recent = [t for t in self._failures.get(key, []) if t > cutoff]
        self._failures[key] = recent
        return recent

    def blocked(self, key: str) -> bool:
        with self._lock:
            return len(self._recent(key)) >= self.max_failures

    def fail(self, key: str) -> None:
        with self._lock:
            self._recent(key).append(time.monotonic())
            if len(self._failures) > 10000:  # many different names: forget the stale ones
                for k in [k for k in self._failures if not self._recent(k)]:
                    del self._failures[k]

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)


_DUMMY: list[str] = []


def _dummy_hash() -> str:
    if not _DUMMY:
        _DUMMY.append(hash_password(secrets.token_urlsafe(16)))
    return _DUMMY[0]


def _sam_in_domain(username: str, domain: str) -> str:
    """The account name if the user typed no domain or this one (CORP\\jsmith,
    jsmith@corp.local, jsmith); "" for any other domain."""
    domain = domain.lower()
    if "\\" in username:
        typed, sam = username.split("\\", 1)
        ok = typed.lower() in (domain, domain.split(".")[0])
    elif "@" in username:
        sam, typed = username.rsplit("@", 1)
        ok = typed.lower() == domain
    else:
        sam, ok = username, True
    sam = sam.strip()
    return sam if ok and sam and not any(c in sam for c in "\\@") else ""


class Authenticator:
    def __init__(self, settings: Settings):
        self.base_settings = settings

    @property
    def settings(self) -> Settings:
        """netops.env plus the AD settings made in the GUI (appsettings.py)."""
        from app.core import appsettings
        return appsettings.effective(self.base_settings)

    def authenticate(self, username: str, password: str) -> User | None:
        # An empty password would be an anonymous (always successful) LDAP bind.
        if not username or not password:
            return None
        s = self.settings
        if s.local_admin_password_hash and username == s.local_admin_user:
            if verify_password(password, s.local_admin_password_hash):
                return User(username=username, role=ADMIN, display_name="Local administrator",
                            can_upgrade=True, source="break-glass")
            return None
        from app.core.models import UserAccount

        with session_scope() as db:
            acc = db.query(UserAccount).filter(UserAccount.username == account_key(username)).first()
            if acc is not None:
                if not acc.enabled:
                    return None
                if acc.source == "local":
                    display = acc.display_name if acc.password_hash and verify_password(
                        password, acc.password_hash) else None
                else:
                    display = self._ldap_safe(username, password, groups=False)
                    display = display.display_name if display else None
                if display is None:
                    return None
                acc.last_login = utcnow()
                return user_from_account(acc, display)
        if s.ldap_url:
            return self._ldap_safe(username, password, groups=True)
        verify_password(password, _dummy_hash())  # same time as for a real local user
        return None

    def _ldap_safe(self, username: str, password: str, groups: bool) -> User | None:
        if not self.settings.ldap_url:
            return None
        try:
            return self._ldap_authenticate(username, password, groups)
        except Exception:  # noqa: BLE001 - never leak LDAP errors to the client
            log.exception("LDAP authentication error for %s", username)
            return None

    def _ldap_authenticate(self, username: str, password: str, groups: bool = True) -> User | None:
        """Bind as the user. groups=False: only check the password and read the display
        name (a user added in NetOps); True: the role from the AD groups."""
        from ldap3 import NONE, SIMPLE, Connection, Server, Tls
        from ldap3.utils.conv import escape_filter_chars

        s = self.settings
        tls = Tls(validate=ssl.CERT_REQUIRED, ca_certs_file=s.ldap_ca_file or None)
        server = Server(
            s.ldap_url, use_ssl=s.ldap_url.lower().startswith("ldaps://"),
            tls=tls, get_info=NONE, connect_timeout=5,
        )
        sam = _sam_in_domain(username, s.ldap_domain)
        if not sam:
            return None  # another domain: never bind there (a trusted domain's jsmith
            # would otherwise be signed in as this domain's jsmith)
        principal = f"{sam}@{s.ldap_domain}"
        conn = Connection(server, user=principal, password=password,
                          authentication=SIMPLE, receive_timeout=10)
        conn.open()
        if not s.ldap_url.lower().startswith("ldaps://"):
            conn.start_tls()  # never send passwords in clear text
        if not conn.bind():
            return None
        try:
            user_filter = f"(&(objectClass=user)(sAMAccountName={escape_filter_chars(sam)}))"

            def in_group(group_dn: str) -> bool:
                flt = (f"(&{user_filter}"
                       f"(memberOf:{_IN_CHAIN}:={escape_filter_chars(group_dn)}))")
                conn.search(s.ldap_base_dn, flt, attributes=["sAMAccountName"])
                return bool(conn.entries)

            conn.search(s.ldap_base_dn, user_filter, attributes=["displayName"])
            if not conn.entries:
                return None
            display = str(conn.entries[0].displayName or sam)
            if not groups:
                return User(username=sam.lower(), display_name=display, source="ad")

            is_admin = bool(s.ldap_admin_group) and in_group(s.ldap_admin_group)
            # Upgrades: members of the upgrader group; if no group is set, admins.
            can_upgrade = (in_group(s.ldap_upgrader_group) if s.ldap_upgrader_group
                           else is_admin)
            if is_admin:
                return User(username=sam, role=ADMIN, display_name=display,
                            can_upgrade=can_upgrade, source="ad-group")
            if not s.ldap_viewer_group or in_group(s.ldap_viewer_group) or can_upgrade:
                return User(username=sam, role=VIEWER, display_name=display,
                            can_upgrade=can_upgrade, source="ad-group")
            return None
        finally:
            conn.unbind()


# --- FastAPI dependencies -------------------------------------------------

def _fingerprint(password_hash: str) -> str:
    return hashlib.sha256(password_hash.encode()).hexdigest()[:16]


def current_user(request: Request) -> User:
    data = request.session.get("user")
    if not data:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not logged in")
    settings = request.app.state.settings
    # The cookie is renewed on every request, so it would never expire while in use:
    # a sign-in lasts at most session_max_age_hours, however busy.
    issued = request.session.get("issued", 0)
    if time.time() - issued > settings.session_max_age_hours * 3600:
        request.session.clear()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Your session has expired: sign in again")
    if data.get("source") == "break-glass" and (
            not settings.local_admin_password_hash
            or request.session.get("bg") != _fingerprint(settings.local_admin_password_hash)):
        request.session.clear()  # the break-glass password was changed or removed
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in again")
    if data.get("user_id"):
        # A user added in NetOps: read their permissions again, so a change (or a
        # disabled or deleted account) applies straight away.
        from app.core.models import UserAccount

        with session_scope() as db:
            acc = db.get(UserAccount, data["user_id"])
            if acc is None or not acc.enabled or acc.username != data.get("username"):
                request.session.clear()
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Your account has been disabled")
            return user_from_account(acc, data.get("display_name", ""))
    data = {k: v for k, v in data.items() if k in User.__dataclass_fields__}
    return User(**data)


def require_admin(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator role required")
    return user


def require(area: str, level: str):
    """Dependency: the user has at least this level in this area (permissions.py)."""
    label = pm.AREAS[area]["levels"][level]

    def check(user: User = Depends(current_user)) -> User:
        if not user.can(area, level):
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                f"Not allowed: needs {pm.AREAS[area]['label']} - {label.lower()}")
        return user
    check.__name__ = f"require_{area}_{level}"
    return check


require_upgrader = require("upgrades", "dry_run")


# --- Routes ----------------------------------------------------------------

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    authenticator: Authenticator = request.app.state.authenticator
    throttle: LoginThrottle = request.app.state.login_throttle
    client = request.client.host if request.client else "unknown"
    # One count per account however the name is written (admin, " admin", CORP\admin,
    # admin@x), and one per address across all names (password spraying).
    key = f"{account_key(body.username)}|{client}"
    by_address = f"address|{client}"
    if throttle.blocked(key) or request.app.state.address_throttle.blocked(by_address):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed logins, try later")
    user = authenticator.authenticate(body.username.strip(), body.password)
    if user is None:
        throttle.fail(key)
        request.app.state.address_throttle.fail(by_address)
        audit(db, body.username.strip()[:200], "login.failed", f"from {client}")
        db.commit()  # keep the record: raising below rolls the session back
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    throttle.reset(key)
    from app.core import twofactor

    step = twofactor.needed(authenticator.settings, db, user)
    if step:  # the password was right: now a code (or setting it up) before anything else
        audit(db, user.username, "login.password_ok", f"from {client}: two-factor {step} next")
        return twofactor.start_pending(request, user, step)
    request.session.clear()
    request.session["user"] = user.__dict__
    request.session["issued"] = int(time.time())
    if user.source == "break-glass":
        request.session["bg"] = _fingerprint(authenticator.settings.local_admin_password_hash)
    audit(db, user.username, "login",
          f"{'admin' if user.is_admin else 'user'} ({user.source or 'ad-group'}) from {client}")
    return signed_in(request, user)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


def signed_in(request: Request, user: User) -> dict:
    """The signed-in user, as the page needs it after signing in and on every reload."""
    return {**user.out(), "site_name": request.app.state.settings.site_name,
            "demo": getattr(request.app.state, "demo", False)}


@router.get("/me")
def me(request: Request, user: User = Depends(current_user)):
    return signed_in(request, user)


class PasswordChange(BaseModel):
    current: str
    new: str


MIN_PASSWORD = 12


@router.post("/password")
def change_password(body: PasswordChange, request: Request, db: Session = Depends(get_db),
                    user: User = Depends(current_user)):
    """A local NetOps user changes their own password (AD users change it in AD)."""
    from app.core.models import UserAccount

    acc = db.get(UserAccount, user.user_id) if user.user_id else None
    if acc is None or acc.source != "local":
        raise HTTPException(409, "Only local accounts have a password here; "
                                 "AD users change theirs in Active Directory")
    if not verify_password(body.current, acc.password_hash or ""):
        raise HTTPException(403, "The current password is wrong")
    if len(body.new) < MIN_PASSWORD:
        raise HTTPException(422, f"Use at least {MIN_PASSWORD} characters")
    acc.password_hash, acc.password_changed_at = hash_password(body.new), utcnow()
    audit(db, user.username, "user.password", "changed own password")
    return {"ok": True}
