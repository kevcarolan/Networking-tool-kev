"""The wall display: a read-only status dashboard for a NOC screen or an engineers' office.

* An admin adds a **display screen** on the Settings page and gets a link with a long random
  key, shown once. The screen's browser keeps the key in the link's #fragment (never sent
  to the web server's logs) and sends it with each request.
* The page (static/display/) asks for ``/api/display/data`` every 30 seconds and shows two
  pages in turn: an overview (backups, firmware compliance, upgrades, server health,
  failing devices, sites) and the upgrades under way with the circuits they affect.
* Installed servers serve the display on its own port (NETOPS_DISPLAY_PORT, 8443), and
  only there: the nginx site refuses /display/ and /api/display/ on the main port, and the
  host firewall decides who reaches the display port.
* The feed holds counts, names and statuses only: never configs, credentials or addresses.
"""

import hashlib
import secrets
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.auth import User, require_admin
from app.core.db import get_db, utcnow
from app.core.models import Device, DisplayScreen

ERROR_LABELS = {"auth": "login failed", "unreachable": "unreachable", "timeout": "timed out",
                "command": "command refused", "setup": "not set up", "error": "error"}
ATTENTION_ROWS = 12
SEEN_EVERY = timedelta(minutes=1)
COMING_UP = timedelta(hours=12)  # planned upgrades shown on the wall


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


# --- admin: the screens ----------------------------------------------------------------

admin_router = APIRouter(prefix="/api/displays", tags=["display"])


def _screen_out(s: DisplayScreen) -> dict:
    return {"id": s.id, "name": s.name, "created_by": s.created_by, "created_at": s.created_at,
            "last_seen_at": s.last_seen_at, "last_seen_from": s.last_seen_from}


@admin_router.get("")
def list_screens(request: Request, db: Session = Depends(get_db),
                 _: User = Depends(require_admin)):
    return {"port": request.app.state.settings.display_port,
            "screens": [_screen_out(s) for s in db.scalars(select(DisplayScreen)
                                                            .order_by(DisplayScreen.name))]}


class ScreenIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)


@admin_router.post("", status_code=201)
def add_screen(body: ScreenIn, db: Session = Depends(get_db),
               user: User = Depends(require_admin)):
    key = secrets.token_urlsafe(32)
    screen = DisplayScreen(name=body.name.strip(), key_hash=_hash(key), created_by=user.username)
    db.add(screen)
    db.flush()
    audit(db, user.username, "display.add", screen.name)
    return {**_screen_out(screen), "key": key}  # the only time the key is shown


@admin_router.delete("/{screen_id}", status_code=204)
def remove_screen(screen_id: int, db: Session = Depends(get_db),
                  user: User = Depends(require_admin)):
    screen = db.get(DisplayScreen, screen_id)
    if screen is None:
        raise HTTPException(404, "Display screen not found")
    db.delete(screen)
    audit(db, user.username, "display.remove", screen.name)


# --- the feed --------------------------------------------------------------------------

router = APIRouter(prefix="/api/display", tags=["display"])


def _screen(request: Request, db: Session, authorization: str) -> DisplayScreen:
    throttle = request.app.state.login_throttle
    where = request.client.host if request.client else "unknown"
    key = f"display|{where}"
    if throttle.blocked(key):
        raise HTTPException(429, "Too many wrong display keys, try again later")
    scheme, _, given = authorization.partition(" ")
    screen = None
    if scheme.lower() == "bearer" and given.strip():
        screen = db.scalar(select(DisplayScreen).where(
            DisplayScreen.key_hash == _hash(given.strip())))
    if screen is None:
        throttle.fail(key)
        raise HTTPException(401, "This display link isn't valid (removed, or copied wrongly)")
    now = utcnow()
    if screen.last_seen_at is None or now - screen.last_seen_at > SEEN_EVERY:
        screen.last_seen_at, screen.last_seen_from = now, where
    return screen


@router.get("/data")
def data(request: Request, db: Session = Depends(get_db),
         authorization: str = Header(default="")):
    screen = _screen(request, db, authorization)
    return {**snapshot(db, request.app.state), "screen": screen.name}


def snapshot(db: Session, state) -> dict:
    now = utcnow()
    settings = state.settings
    devices = {d.id: d for d in db.scalars(select(Device))}
    backups, failing = _backups(db, settings, devices)
    firmware, behind = _firmware(db, state, devices)
    upgrades = _upgrades(db, settings, now)
    return {
        "generated_at": now, "product_name": settings.product_name,
        "site_name": settings.site_name,
        "backups": backups, "attention": failing[:ATTENTION_ROWS],
        "attention_more": max(0, len(failing) - ATTENTION_ROWS),
        "firmware": firmware, "upgrades": upgrades, "server": _server(db),
        "sites": _sites(devices, failing, behind, upgrades),
    }


def _backups(db: Session, settings, devices: dict) -> tuple[dict, list]:
    from app.tools.config_backup.models import BackupState
    from app.tools.config_backup.service import ensure_states

    ensure_states(db, settings.default_frequency_minutes)
    counts = {"total": 0, "ok": 0, "failing": 0, "never": 0, "disabled": 0}
    failing = []
    for s in db.scalars(select(BackupState)):
        d = devices.get(s.device_id)
        if d is None:
            continue
        counts["total"] += 1
        if not (d.enabled and s.enabled):
            counts["disabled"] += 1
        elif s.last_status == "failed":
            counts["failing"] += 1
            failing.append({"device": d.name, "site": d.site,
                            "reason": ERROR_LABELS.get(s.last_error_type or "",
                                                       s.last_error_type or "failed"),
                            "since": s.last_success, "failures": s.consecutive_failures})
        elif s.last_status == "never":
            counts["never"] += 1
        else:
            counts["ok"] += 1  # success, or running right now
    # Longest-failing first (never succeeded counts as longest)
    failing.sort(key=lambda r: (r["since"] is not None, r["since"] or datetime.min))
    return counts, failing


def _firmware(db: Session, state, devices: dict) -> tuple[dict, set]:
    from app.tools.firmware_upgrade.api import _rows
    from app.tools.firmware_upgrade.facts import AHEAD, BEHIND, COMPLIANT, NO_STANDARD

    counts = {"total": 0, "on_standard": 0, "behind": 0, "ahead": 0, "no_standard": 0,
              "unknown": 0}
    names = {COMPLIANT: "on_standard", BEHIND: "behind", AHEAD: "ahead",
             NO_STANDARD: "no_standard"}
    behind = set()
    for r in _rows(db, state.firmware_service):
        counts["total"] += 1
        counts[names.get(r.compliance, "unknown")] += 1
        if r.compliance == BEHIND:
            behind.add(r.device.id)
    checked = counts["on_standard"] + counts["behind"] + counts["ahead"]
    counts["percent"] = round(100 * counts["on_standard"] / checked) if checked else None
    return counts, behind


def _upgrades(db: Session, settings, now: datetime) -> dict:
    from app.tools.firmware_upgrade import jobs as jb
    from app.tools.firmware_upgrade.jobs_api import job_detail
    from app.tools.firmware_upgrade.models import (BLOCKED, CLOSED_STATES, PLANNED, READY,
                                                   UpgradeJob)

    under_way, coming_up = [], []
    horizon = now + COMING_UP
    for job in db.scalars(select(UpgradeJob).where(UpgradeJob.status.not_in(CLOSED_STATES))
                          .order_by(UpgradeJob.planned_start, UpgradeJob.id)):
        waiting = job.status in (PLANNED, BLOCKED, READY) and job.started_at is None
        if waiting:
            if job.planned_start and job.planned_start <= horizon and (
                    job.planned_end is None or job.planned_end >= now):
                coming_up.append(_job_row(db, job, settings, job_detail, jb, circuits=False))
        else:
            under_way.append(_job_row(db, job, settings, job_detail, jb, circuits=True))
    return {"under_way": under_way, "coming_up": coming_up}


def _job_row(db, job, settings, job_detail, jb, circuits: bool) -> dict:
    d = job_detail(db, job, settings)
    steps, at = d["steps"], d["step_index"] or 0
    row = {"id": d["id"], "status": d["status"], "live": not d["dry_run"],
           "devices": [u["name"] for u in d["units"]] or [d["device"]["name"]],
           "site": d["device"]["site"], "platform": d["device"]["platform_label"],
           "from_version": d["from_version"], "target_version": d["target_version"],
           "change_ref": d["change_ref"], "planned_start": d["planned_start"],
           "planned_end": d["planned_end"], "started_at": d["started_at"],
           "step": at, "steps": len(steps),
           "step_label": steps[at]["label"] if 0 <= at < len(steps) else d["current_step"],
           "busy": d["busy"]}
    if circuits:
        c = d["circuits"].get("started") or d["circuits"].get("planned")
        row["circuits"] = {"count": c["count"] if c else 0,
                           "groups": [{"service": g["service"], "vlan": g["vlan"],
                                       "count": len(g["circuits"])}
                                      for g in (c["groups"] if c else [])]}
    return row


def _server(db: Session) -> dict:
    from app.core import licence
    from app.tools.firmware_upgrade import jobs as jb

    lic = licence.status(db)
    return {"worker": jb.worker_status(db)["alive"],
            "licence": {"mode": lic["mode"], "active": lic["active"], "message": lic["message"],
                        "days_left": lic["days_left"]}}


def _sites(devices: dict, failing: list, behind: set, upgrades: dict) -> list[dict]:
    sites = defaultdict(lambda: {"devices": 0, "failing": 0, "behind": 0, "upgrading": 0})
    for d in devices.values():
        sites[d.site or "-"]["devices"] += 1
        if d.id in behind:
            sites[d.site or "-"]["behind"] += 1
    for f in failing:
        sites[f["site"] or "-"]["failing"] += 1
    for j in upgrades["under_way"]:
        sites[j["site"] or "-"]["upgrading"] += 1
    return [{"site": name, **v} for name, v in sorted(sites.items())]
