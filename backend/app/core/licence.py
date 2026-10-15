"""Licences: who may use this install, until when, and for how many devices.

A licence is a short signed text block that the owner makes with ``python -m app.licence_tool``
and an admin pastes on the Settings page. It is checked here against the public keys in
``licence_keys.txt``; only the owner's private key can make one, and nothing is sent anywhere
(air-gapped sites work the same way).

* A new install runs a **60-day trial** with everything switched on.
* With a valid licence, everything works until its end date, for up to its number of devices.
* With **no valid licence** (trial over, or licence expired) the install is read-only for new
  work: nobody can add devices or plan or start upgrade jobs. Everything else keeps working:
  backups, version checks, circuit scans, viewing, and upgrade jobs already under way (they
  can always continue or roll back). Nothing is ever deleted.
* **Modules:** one full install, and the licence says which tools it unlocks (``MODULES``:
  backups, firmware, upgrades, circuits, syslog). A tool that isn't in the licence shows as
  locked; its scheduled work doesn't run. Upgrades always bring Firmware (the image library).
  The trial, licences made before modules existed, and an install without a licence have
  every module, so nothing that ran before stops.
* ``python -m app`` (development and the owner's own testing) is never limited.
"""

import base64
import datetime
import json
import secrets
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import appsettings
from app.core.audit import audit
from app.core.auth import User, current_user, require_admin
from app.core.db import get_db, utcnow


TRIAL_DAYS = 60
WARN_DAYS = 30
KEYS_FILE = Path(__file__).with_name("licence_keys.txt")
BEGIN, END = "-----BEGIN LICENCE-----", "-----END LICENCE-----"

# The tools a licence can unlock. Inventory, users, settings, alerts and the wall display are
# always there.
MODULES = {"backups": "Config backups", "firmware": "Firmware", "upgrades": "Upgrade jobs",
           "circuits": "Circuits", "syslog": "Syslog", "monitoring": "Monitoring"}

# Editions are names for a set of modules (docs/licensing.md); the licence keeps the modules
# themselves, so an edition can be re-bundled without changing licences already sold.
EDITIONS = {
    "essentials": ("Essentials", ["backups", "syslog"]),
    "professional": ("Professional", ["backups", "syslog", "firmware", "upgrades", "circuits"]),
    "complete": ("Complete", list(MODULES)),
}
ADDONS = {"monitoring": "Monitoring add-on"}

# A Cisco Meraki organisation (Monitoring › Meraki) uses this many of the licence's devices,
# unless the licence says otherwise ("meraki_devices").
MERAKI_DEVICES = 25

INSTALL_ID = "install_id"
TRIAL_STARTED = "trial_started_at"
LICENCE = "licence"

# Set by `python -m app` (app/__main__.py): development and testing, no limits.
DEVELOPMENT = False


class LicenceError(ValueError):
    pass


# --- the licence text -------------------------------------------------------------

def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def encode(payload: dict, signature: bytes) -> str:
    """The licence as text: the payload and its signature, wrapped at 64 characters."""
    body = _b64(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    blob = f"{body}.{_b64(signature)}"
    lines = [blob[i:i + 64] for i in range(0, len(blob), 64)]
    return "\n".join([BEGIN, *lines, END]) + "\n"


def signed_bytes(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def public_keys() -> list[Ed25519PublicKey]:
    """The keys licences are signed with (one per line in licence_keys.txt, # for comments)."""
    keys = []
    if KEYS_FILE.exists():
        for line in KEYS_FILE.read_text().splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                keys.append(Ed25519PublicKey.from_public_bytes(_unb64(line)))
    return keys


def parse(text: str) -> dict:
    """Check a licence's signature and return what it says. Raises LicenceError."""
    text = text.strip()
    if BEGIN not in text or END not in text:
        raise LicenceError("That isn't a licence: paste everything from "
                           f"{BEGIN} to {END}")
    blob = "".join(text.split(BEGIN, 1)[1].split(END, 1)[0].split())
    try:
        body, sig = blob.split(".")
        data = _unb64(body)
        signature = _unb64(sig)
        payload = json.loads(data)
    except (ValueError, json.JSONDecodeError):
        raise LicenceError("The licence text is damaged: copy it again in full") from None
    keys = public_keys()
    if not keys:
        raise LicenceError("This copy of the software has no licence key built in, so it "
                           "can't check licences")
    for key in keys:
        try:
            key.verify(signature, data)
            break
        except InvalidSignature:
            continue
    else:
        raise LicenceError("The licence signature isn't valid: it was changed, or it is "
                           "not for this software")
    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise LicenceError("This licence is for a newer version of the software")
    return payload


def licensed_modules(payload: dict) -> list[str]:
    """The modules a licence unlocks (every one for licences made before modules)."""
    wanted = payload.get("modules")
    if wanted is None or payload.get("kind") == "internal":
        return list(MODULES)
    found = {m for m in wanted if m in MODULES}
    if "upgrades" in found:
        found.add("firmware")  # upgrade jobs need the image library
    return [m for m in MODULES if m in found]


def _date(value) -> datetime.date | None:
    return datetime.date.fromisoformat(value) if value else None


# --- the install's state ----------------------------------------------------------

def ensure_install(db: Session) -> None:
    """Give the install its ID and start the trial (once, at the first start)."""
    values = appsettings.stored(db)
    new = {}
    if not values.get(INSTALL_ID):
        new[INSTALL_ID] = "-".join(secrets.token_hex(2).upper() for _ in range(4))
    if not values.get(TRIAL_STARTED):
        new[TRIAL_STARTED] = utcnow().date().isoformat()
    if new:
        appsettings.save(db, new, "system")


def _device_count(db: Session) -> int:
    from app.core.models import Device

    return db.scalar(select(func.count(Device.id))) or 0


def _meraki_count(db: Session) -> int:
    """Meraki organisations being read (each uses a block of the licence's devices)."""
    try:
        from app.tools.monitoring.models import MerakiOrg
    except ImportError:  # pragma: no cover
        return 0
    return db.scalar(select(func.count(MerakiOrg.id)).where(MerakiOrg.enabled.is_(True))) or 0


def edition_label(payload: dict) -> str:
    """'Professional + Monitoring add-on', from the licence's edition and modules."""
    if payload.get("kind") == "internal":
        return "Internal use"
    name = EDITIONS.get(payload.get("edition") or "", (None, None))[0]
    if not name:
        return "Custom" if payload.get("modules") is not None else "Complete"
    mods = set(licensed_modules(payload))
    extra = [ADDONS[a] for a in ADDONS if a in mods and a not in EDITIONS[payload["edition"]][1]]
    return " + ".join([name, *extra])


def status(db: Session, today: datetime.date | None = None) -> dict:
    """Where the install stands. ``active`` is False when new work is blocked."""
    today = today or utcnow().date()
    ensure_install(db)
    values = appsettings.stored(db)
    meraki = _meraki_count(db)
    out = {"mode": "", "active": True, "message": "", "warning": "", "devices": 0,
           "physical_devices": _device_count(db), "meraki_orgs": meraki,
           "meraki_devices_each": MERAKI_DEVICES, "edition": None,
           "max_devices": None, "ends": None, "days_left": None, "licence": None,
           "install_id": values[INSTALL_ID], "development": DEVELOPMENT,
           "modules": list(MODULES), "module_labels": MODULES}

    licence = None
    if values.get(LICENCE):
        try:
            licence = parse(values[LICENCE])
            if licence.get("install_id") and licence["install_id"] != values[INSTALL_ID]:
                raise LicenceError(f"The licence is for installation {licence['install_id']}, "
                                   f"not this one ({values[INSTALL_ID]})")
        except LicenceError as exc:
            out["warning"] = f"The installed licence can't be used: {exc}"
            licence = None

    if licence and licence.get("meraki_devices") is not None:
        out["meraki_devices_each"] = int(licence["meraki_devices"])
    out["devices"] = devices = out["physical_devices"] + meraki * out["meraki_devices_each"]

    if DEVELOPMENT:
        out.update(mode="development", message="Development mode: no licence needed")
        return out

    if licence:
        ends = _date(licence.get("expires"))
        out.update(mode="licensed", licence=_summary(licence), max_devices=licence.get("max_devices"),
                   ends=ends.isoformat() if ends else None, modules=licensed_modules(licence),
                   edition=edition_label(licence))
        who = licence.get("customer") or "?"
        if ends is None:
            out["message"] = f"Licensed to {who}, no end date"
        elif today <= ends:
            left = (ends - today).days
            out.update(days_left=left, message=f"Licensed to {who} until {ends:%d %b %Y}")
            if left <= WARN_DAYS:
                out["warning"] = (f"The licence ends on {ends:%d %b %Y} ({left} days). "
                                  f"Ask for a renewal; an admin adds it on the Settings page.")
        else:
            out.update(mode="expired", active=False,
                       message=f"The licence for {who} ended on {ends:%d %b %Y}")
    else:
        started = _date(values[TRIAL_STARTED])
        ends = started + datetime.timedelta(days=TRIAL_DAYS)
        out["ends"] = ends.isoformat()
        if today < ends:
            left = (ends - today).days
            out.update(mode="trial", days_left=left,
                       message=f"Trial: {left} days left (ends {ends:%d %b %Y})")
            out["warning"] = out["warning"] or (
                f"Trial: {left} days left. An admin adds a licence on the Settings page.")
        else:
            out.update(mode="trial_ended", active=False,
                       message=f"The trial ended on {ends:%d %b %Y}")

    if not out["active"]:
        out["warning"] = (f"{out['message']}. You can still view everything and backups keep "
                          f"running, but you can't add devices or start upgrades until an "
                          f"admin adds a licence on the Settings page.")
    elif out["max_devices"] is not None and devices >= out["max_devices"]:
        out["warning"] = out["warning"] or (
            f"The licence covers {out['max_devices']} devices and {devices} are in use: "
            f"no more can be added.")
    return out


def _summary(p: dict) -> dict:
    return {**{k: p.get(k) for k in ("id", "customer", "issued", "expires", "max_devices",
                                     "install_id", "kind")}, "modules": licensed_modules(p),
            "edition": edition_label(p)}


# --- checks used by the tools -----------------------------------------------------

def require_active(db: Session, what: str) -> None:
    """Refuse new work (``what``, e.g. "add devices") without a valid licence."""
    s = status(db)
    if not s["active"]:
        raise HTTPException(403, f"{s['message']}: you can't {what} until an admin adds a "
                                 f"licence on the Settings page")


def room_for(db: Session, adding: int = 1) -> int | None:
    """How many more devices may be added, or None for no limit. Raises if none."""
    s = status(db)
    if not s["active"]:
        raise HTTPException(403, f"{s['message']}: you can't add devices until an admin "
                                 f"adds a licence on the Settings page")
    if s["max_devices"] is None:
        return None
    room = s["max_devices"] - s["devices"]
    if room < adding:
        meraki = (f" (including {s['meraki_orgs']} Meraki organisation(s) at "
                  f"{s['meraki_devices_each']} each)") if s["meraki_orgs"] else ""
        raise HTTPException(403, f"The licence covers {s['max_devices']} devices and "
                                 f"{s['devices']} are in use{meraki}; this needs {adding} more")
    return room


def meraki_room(db: Session) -> None:
    """Room for one more Meraki organisation (a block of devices). Raises if not."""
    room_for(db, status(db)["meraki_devices_each"])


def has_module(module: str, db: Session | None = None) -> bool:
    """Is the tool unlocked? (For scheduled work; opens its own session if needed.)"""
    if db is None:
        from app.core.db import session_scope

        with session_scope() as own:
            return has_module(module, own)
    return module in status(db)["modules"]


def not_licensed(module: str) -> HTTPException:
    return HTTPException(403, f"{MODULES[module]} isn't in your licence. Ask your supplier to add "
                              f"it; an admin adds the new licence on the Settings page.")


def module(name: str):
    """Dependency for a tool's endpoints: refused unless the licence unlocks it."""
    def check(db: Session = Depends(get_db)) -> None:
        if not has_module(name, db):
            raise not_licensed(name)
    return check


# --- API --------------------------------------------------------------------------

router = APIRouter(prefix="/api/licence", tags=["licence"])


@router.get("")
def get_status(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return status(db)


class LicenceIn(BaseModel):
    text: str = Field(min_length=1, max_length=10000)


@router.post("")
def install(body: LicenceIn, db: Session = Depends(get_db),
            user: User = Depends(require_admin)):
    try:
        payload = parse(body.text)
        install_id = appsettings.stored(db).get(INSTALL_ID)
        if payload.get("install_id") and payload["install_id"] != install_id:
            raise LicenceError(f"This licence is for installation {payload['install_id']}; "
                               f"this one is {install_id}")
        ends = _date(payload.get("expires"))
        if ends and ends < utcnow().date():
            raise LicenceError(f"This licence ended on {ends:%d %b %Y}")
    except LicenceError as exc:
        audit(db, user.username, "licence.rejected", str(exc))
        db.commit()  # kept although the request fails
        raise HTTPException(422, str(exc)) from None
    appsettings.save(db, {LICENCE: body.text.strip()}, user.username)
    audit(db, user.username, "licence.install",
          f"{payload.get('id')} for {payload.get('customer')}, until "
          f"{payload.get('expires') or 'no end date'}, "
          f"{payload.get('max_devices') or 'any number of'} devices, {edition_label(payload)}, "
          f"modules {', '.join(licensed_modules(payload))}")
    return status(db)
