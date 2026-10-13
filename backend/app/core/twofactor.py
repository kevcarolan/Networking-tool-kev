"""Two-factor sign-in (codes from an authenticator app, totp.py).

Who:
* a user added on the Users page (local or AD) turns it on for themselves; when the admin
  setting ``require_two_factor`` is on, local users must, and set it up at their next
  sign-in;
* the break-glass admin, when ``NETOPS_LOCAL_ADMIN_TOTP_SECRET`` is set in netops.env;
* AD users who are only in an AD group (not on the Users page) can't: add them first.

Signing in: the password first (auth.login); when a code is needed the session only holds
a *pending* sign-in (5 minutes, no access to anything) until ``/api/auth/login/code`` gets a
right code or recovery code. Wrong codes count towards the same lock-out as wrong passwords.
An admin can reset a user's two-factor (a lost phone) on the Users page.
"""

import json
import time

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core import totp
from app.core.audit import audit
from app.core.auth import (LoginThrottle, User, _fingerprint, account_key, current_user,
                           require_admin, signed_in)
from app.core.crypto import verify_password
from app.core.db import get_db, utcnow
from app.core.models import UserAccount

router = APIRouter(tags=["two-factor"])
PENDING_SECONDS = 300
CODE, SETUP = "code", "setup"
_BREAK_GLASS_LAST: dict[str, int] = {}  # secret -> last step used (one process)


def required(settings, acc: UserAccount | None) -> bool:
    return bool(acc is not None and acc.source == "local" and settings.require_two_factor)


def needed(settings, db: Session, user: User) -> str | None:
    """After a right password: CODE (ask for a code), SETUP (must set it up first) or None."""
    if user.source == "break-glass":
        return CODE if settings.local_admin_totp_secret else None
    acc = db.get(UserAccount, user.user_id) if user.user_id else None
    if acc is None:
        return None
    if acc.totp_enabled:
        return CODE
    return SETUP if required(settings, acc) else None


def start_pending(request: Request, user: User, step: str) -> dict:
    request.session.clear()
    request.session["pending"] = {"user": user.__dict__, "at": time.time(), "step": step}
    return {"two_factor": step, "username": user.username}


def _pending(request: Request, step: str | None = None) -> dict:
    p = request.session.get("pending")
    if not p or time.time() - p.get("at", 0) > PENDING_SECONDS:
        request.session.clear()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in again")
    if step and p["step"] != step:
        raise HTTPException(status.HTTP_409_CONFLICT, "Not at that step of signing in")
    return p


def _finish(request: Request, db: Session, user: User, how: str) -> dict:
    """Turn the pending sign-in into a real one (as auth.login does)."""
    request.session.clear()
    request.session["user"] = user.__dict__
    request.session["issued"] = int(time.time())
    settings = request.app.state.settings
    if user.source == "break-glass":
        request.session["bg"] = _fingerprint(settings.local_admin_password_hash)
    client = request.client.host if request.client else "unknown"
    audit(db, user.username, "login",
          f"{'admin' if user.is_admin else 'user'} ({user.source or 'ad-group'}) from {client}, {how}")
    return signed_in(request, user)


def _account(db: Session, user: User) -> UserAccount:
    acc = db.get(UserAccount, user.user_id) if user.user_id else None
    if acc is None:
        raise HTTPException(409, "Two-factor sign-in is for users on the Users page: ask an "
                                 "admin to add you there first")
    if not acc.enabled:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Your account has been disabled")
    return acc


def _check(request: Request, db: Session, acc: UserAccount | None, code: str) -> str | None:
    """'code' or 'recovery code (n left)' when right, else None. Uses the code up."""
    cipher = request.app.state.cipher
    if acc is None:  # the break-glass admin
        secret = request.app.state.settings.local_admin_totp_secret
        step = totp.verify(secret, code, _BREAK_GLASS_LAST.get(secret, -1))
        if step is None:
            return None
        _BREAK_GLASS_LAST[secret] = step
        return "code"
    secret = cipher.decrypt(acc.totp_secret) if acc.totp_secret else ""
    step = totp.verify(secret, code, acc.totp_last_step)
    if step is not None:
        acc.totp_last_step = step
        return "code"
    left = totp.use_recovery(json.loads(acc.recovery_codes or "[]"), code)
    if left is None:
        return None
    acc.recovery_codes = json.dumps(left)
    return f"recovery code ({len(left)} left)"


# --- signing in -----------------------------------------------------------------------

class CodeIn(BaseModel):
    code: str = Field(max_length=40)


@router.post("/api/auth/login/code")
def login_code(body: CodeIn, request: Request, db: Session = Depends(get_db)):
    p = _pending(request, CODE)
    user = User(**{k: v for k, v in p["user"].items() if k in User.__dataclass_fields__})
    throttle: LoginThrottle = request.app.state.login_throttle
    client = request.client.host if request.client else "unknown"
    key = f"{account_key(user.username)}|{client}"
    if throttle.blocked(key):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed logins, try later")
    acc = None if user.source == "break-glass" else _account(db, user)
    how = _check(request, db, acc, body.code)
    if how is None:
        throttle.fail(key)
        audit(db, user.username, "login.failed", f"from {client}: wrong two-factor code")
        db.commit()  # keep the record: raising below rolls the session back
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "That code isn't right (or was used already)")
    throttle.reset(key)
    return _finish(request, db, user, f"two-factor {how}")


# --- setting it up ----------------------------------------------------------------------

def _who(request: Request) -> tuple[User, bool]:
    """The signed-in user, or the one part-way through signing in who must set it up."""
    if request.session.get("user"):
        return current_user(request), False
    p = _pending(request, SETUP)
    return User(**{k: v for k, v in p["user"].items() if k in User.__dataclass_fields__}), True


@router.post("/api/auth/two-factor/start")
def setup_start(request: Request, db: Session = Depends(get_db)):
    """A new secret for the authenticator app (not on until a code from it is entered)."""
    user, _pending_setup = _who(request)
    acc = _account(db, user)
    if acc.totp_enabled:
        raise HTTPException(409, "Two-factor sign-in is already on: turn it off first")
    secret = totp.new_secret()
    acc.totp_secret = request.app.state.cipher.encrypt(secret)
    link = totp.uri(secret, acc.username, request.app.state.settings.product_name)
    return {"secret": " ".join(secret[i:i + 4] for i in range(0, len(secret), 4)),
            "uri": link, "qr_svg": totp.qr_svg(link)}


@router.post("/api/auth/two-factor/enable")
def setup_enable(body: CodeIn, request: Request, db: Session = Depends(get_db)):
    user, pending_setup = _who(request)
    acc = _account(db, user)
    if acc.totp_enabled or not acc.totp_secret:
        raise HTTPException(409, "Start the set-up first")
    step = totp.verify(request.app.state.cipher.decrypt(acc.totp_secret), body.code)
    if step is None:
        raise HTTPException(422, "That code isn't right: check the phone's time and try the next one")
    codes = totp.recovery_codes()
    acc.totp_enabled, acc.totp_last_step, acc.totp_enabled_at = True, step, utcnow()
    acc.recovery_codes = json.dumps([totp.hash_code(c) for c in codes])
    audit(db, user.username, "user.two_factor_on", acc.username)
    out = {"recovery_codes": codes}
    if pending_setup:
        out["user"] = _finish(request, db, user, "two-factor set up")
    return out


class OffIn(BaseModel):
    password: str = Field("", max_length=500)
    code: str = Field(max_length=40)


@router.post("/api/auth/two-factor/disable")
def setup_disable(body: OffIn, request: Request, db: Session = Depends(get_db),
                  user: User = Depends(current_user)):
    acc = _account(db, user)
    if not acc.totp_enabled:
        raise HTTPException(409, "Two-factor sign-in is off")
    if required(request.app.state.settings, acc):
        raise HTTPException(409, "Your admin requires two-factor sign-in for local users")
    if acc.source == "local" and not verify_password(body.password, acc.password_hash or ""):
        raise HTTPException(403, "The password is wrong")
    if _check(request, db, acc, body.code) is None:
        raise HTTPException(403, "That code isn't right")
    _clear(acc)
    audit(db, user.username, "user.two_factor_off", acc.username)
    return {"ok": True}


@router.post("/api/auth/two-factor/recovery-codes")
def new_recovery_codes(body: CodeIn, request: Request, db: Session = Depends(get_db),
                       user: User = Depends(current_user)):
    """Ten new recovery codes (the old ones stop working)."""
    acc = _account(db, user)
    if not acc.totp_enabled or _check(request, db, acc, body.code) is None:
        raise HTTPException(403, "That code isn't right")
    codes = totp.recovery_codes()
    acc.recovery_codes = json.dumps([totp.hash_code(c) for c in codes])
    audit(db, user.username, "user.two_factor_codes", "new recovery codes")
    return {"recovery_codes": codes}


@router.get("/api/auth/two-factor")
def status_of(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    acc = db.get(UserAccount, user.user_id) if user.user_id else None
    settings = request.app.state.settings
    if user.source == "break-glass":
        return {"available": False, "enabled": bool(settings.local_admin_totp_secret),
                "note": "The break-glass admin's two-factor is set in netops.env"}
    if acc is None:
        return {"available": False, "enabled": False,
                "note": "Ask an admin to add you on the Users page to use two-factor sign-in"}
    return {"available": True, "enabled": acc.totp_enabled, "required": required(settings, acc),
            "since": acc.totp_enabled_at,
            "recovery_left": len(json.loads(acc.recovery_codes or "[]")) if acc.totp_enabled else 0}


def _clear(acc: UserAccount) -> None:
    acc.totp_enabled, acc.totp_secret, acc.totp_last_step = False, "", 0
    acc.totp_enabled_at, acc.recovery_codes = None, "[]"


@router.post("/api/users/{user_id}/two-factor/reset")
def admin_reset(user_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """An admin turns a user's two-factor off (a lost phone); they set it up again."""
    acc = db.get(UserAccount, user_id)
    if acc is None:
        raise HTTPException(404, "User not found")
    _clear(acc)
    audit(db, admin.username, "user.two_factor_reset", acc.username)
    return {"ok": True}
