"""Users (added by an admin, with their permissions) and the activity report.

Admins only. Every change is in the audit log (user.*). The activity report is built
from the audit log plus the jobs themselves, so it shows what each person ran and how
it ended: backups they ran, upgrade jobs they planned or started (dry run or live) and
their result, overrides, circuit imports and scans.
"""

import csv
import io
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import permissions as pm
from app.core.audit import audit
from app.core.auth import MIN_PASSWORD, User, account_key, require_admin
from app.core.crypto import hash_password
from app.core.db import get_db, utcnow
from app.core.models import AuditEvent, Device, UserAccount

router = APIRouter(prefix="/api", tags=["users"])

_USERNAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SOURCES = {"ad": "Active Directory", "local": "Local (password kept here)"}


def _out(a: UserAccount) -> dict:
    perms = pm.full() if a.is_admin else pm.normalise(json.loads(a.permissions or "{}"))
    return {"id": a.id, "username": a.username, "source": a.source, "display_name": a.display_name,
            "email": a.email, "enabled": a.enabled, "is_admin": a.is_admin, "permissions": perms,
            "summary": pm.describe(perms, a.is_admin), "notes": a.notes,
            "has_password": bool(a.password_hash), "created_at": a.created_at,
            "created_by": a.created_by, "updated_at": a.updated_at, "updated_by": a.updated_by,
            "last_login": a.last_login, "password_changed_at": a.password_changed_at}


class UserIn(BaseModel):
    display_name: str = Field(default="", max_length=200)
    email: str = Field(default="", max_length=200)
    enabled: bool = True
    is_admin: bool = False
    permissions: dict[str, str] = Field(default_factory=dict)
    preset: str = ""  # viewer / operator / upgrader / admin: fills in the permissions
    notes: str = Field(default="", max_length=2000)


class UserCreate(UserIn):
    username: str = Field(min_length=1, max_length=64)
    source: str = "ad"
    password: str = ""


class PasswordIn(BaseModel):
    password: str


def _apply(acc: UserAccount, body: UserIn) -> None:
    perms, admin = body.permissions, body.is_admin
    if body.preset:
        if body.preset not in pm.PRESETS:
            raise HTTPException(422, f"Unknown preset '{body.preset}'")
        preset = pm.PRESETS[body.preset]
        perms, admin = preset["perms"], preset["admin"]
    for area, level in perms.items():
        if area not in pm.LEVELS or level not in pm.LEVELS[area]:
            raise HTTPException(422, f"'{level}' isn't a level of '{area}'")
    acc.is_admin = admin
    acc.permissions = json.dumps(pm.full() if admin else pm.normalise(perms))
    acc.display_name, acc.email = body.display_name.strip(), body.email.strip()
    acc.enabled, acc.notes = body.enabled, body.notes


def _check_password(pw: str) -> str:
    if len(pw) < MIN_PASSWORD:
        raise HTTPException(422, f"The password needs at least {MIN_PASSWORD} characters")
    return hash_password(pw)


def _changes(before: dict, after: dict) -> str:
    keys = ("enabled", "is_admin", "display_name", "email")
    out = [f"{k}: {before[k]} -> {after[k]}" for k in keys if before[k] != after[k]]
    out += [f"{a}: {before['permissions'][a]} -> {after['permissions'][a]}"
            for a in pm.LEVELS if before["permissions"][a] != after["permissions"][a]]
    return "; ".join(out) or "no change"


def _get(db: Session, user_id: int) -> UserAccount:
    acc = db.get(UserAccount, user_id)
    if acc is None:
        raise HTTPException(404, "User not found")
    return acc


@router.get("/users/meta")
def users_meta(request: Request, _: User = Depends(require_admin)):
    s = request.app.state.settings
    return {"areas": pm.AREAS, "levels": pm.LEVELS,
            "presets": {k: {"label": v["label"], "admin": v["admin"], "perms": v["perms"]}
                        for k, v in pm.PRESETS.items()},
            "sources": SOURCES, "ldap_enabled": bool(s.ldap_url),
            "break_glass_user": s.local_admin_user if s.local_admin_password_hash else "",
            "min_password": MIN_PASSWORD,
            "ad_groups": {"admin": s.ldap_admin_group, "viewer": s.ldap_viewer_group,
                          "upgrader": s.ldap_upgrader_group}}


@router.get("/users")
def list_users(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return [_out(a) for a in db.scalars(select(UserAccount).order_by(UserAccount.username))]


@router.post("/users", status_code=201)
def create_user(body: UserCreate, request: Request, db: Session = Depends(get_db),
                user: User = Depends(require_admin)):
    s = request.app.state.settings
    name = account_key(body.username)
    if not _USERNAME.match(name) or name != body.username.strip().lower():
        raise HTTPException(422, "Use the plain username (letters, digits, . _ -), e.g. jsmith "
                                 "- no domain")
    if body.source not in SOURCES:
        raise HTTPException(422, "Source must be 'ad' or 'local'")
    if s.local_admin_password_hash and name == s.local_admin_user.lower():
        raise HTTPException(409, f"'{name}' is the break-glass admin account")
    if db.scalar(select(UserAccount).where(UserAccount.username == name)):
        raise HTTPException(409, f"User '{name}' already exists")
    if body.source == "ad" and not s.ldap_url:
        raise HTTPException(422, "Active Directory isn't set up on this server "
                                 "(NETOPS_LDAP_URL) - add a local user instead")
    acc = UserAccount(username=name, source=body.source, created_by=user.username,
                      updated_by=user.username)
    if body.source == "local":
        acc.password_hash, acc.password_changed_at = _check_password(body.password), utcnow()
    _apply(acc, body)
    db.add(acc)
    db.flush()
    out = _out(acc)
    audit(db, user.username, "user.create",
          f"{name} ({body.source}){'' if acc.enabled else ' disabled'}: {out['summary']}")
    return out


@router.put("/users/{user_id}")
def update_user(user_id: int, body: UserIn, db: Session = Depends(get_db),
                user: User = Depends(require_admin)):
    acc = _get(db, user_id)
    before = _out(acc)
    _apply(acc, body)
    if acc.id == user.user_id and (not acc.enabled or not acc.is_admin):
        raise HTTPException(409, "You can't remove your own admin rights or disable yourself")
    acc.updated_by, acc.updated_at = user.username, utcnow()
    after = _out(acc)
    audit(db, user.username, "user.update", f"{acc.username}: {_changes(before, after)}")
    return after


@router.post("/users/{user_id}/password")
def reset_password(user_id: int, body: PasswordIn, db: Session = Depends(get_db),
                   user: User = Depends(require_admin)):
    acc = _get(db, user_id)
    if acc.source != "local":
        raise HTTPException(409, "AD users' passwords are managed in Active Directory")
    acc.password_hash, acc.password_changed_at = _check_password(body.password), utcnow()
    acc.updated_by = user.username
    audit(db, user.username, "user.password", f"reset the password of {acc.username}")
    return _out(acc)


@router.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    acc = _get(db, user_id)
    if acc.id == user.user_id:
        raise HTTPException(409, "You can't delete your own account")
    db.delete(acc)
    audit(db, user.username, "user.delete", acc.username)
    return Response(status_code=204)


# --- activity report ---------------------------------------------------------

AREA_OF = (  # action prefix -> report area
    ("firmware.job.", "upgrades"), ("firmware.", "firmware"), ("backup.", "backups"),
    ("circuits.", "circuits"), ("device.", "inventory"), ("credential.", "inventory"),
    ("user.", "users"), ("login", "logins"),
)
ACTIVITY_AREAS = {"upgrades": "Upgrade jobs", "firmware": "Firmware", "backups": "Config backups",
                  "circuits": "Circuits", "inventory": "Devices and credentials",
                  "users": "Users", "logins": "Sign-ins", "other": "Other"}

# What the summary counts, per user: (column, label, action or prefix)
COUNTS = (
    ("logins", "Sign-ins", "login"),
    ("backups_run", "Backups run", "backup.run"),
    ("configs_viewed", "Configs viewed", "backup.view_config"),
    ("version_checks", "Version checks", ("firmware.check", "firmware.check_all")),
    ("jobs_planned", "Upgrade jobs planned", "firmware.job.create"),
    ("job_starts", "Upgrade starts", "firmware.job.start"),
    ("rollbacks", "Roll backs", "firmware.job.rollback"),
    ("overrides", "Check overrides", "firmware.job.override"),
    ("cancels", "Jobs cancelled", "firmware.job.cancel"),
    ("circuit_imports", "Circuit lists made live", "circuits.import.commit"),
    ("scans", "Network scans", "circuits.scan"),
    ("changes", "Device/credential/user changes", ("device.", "credential.", "user.")),
)


def area_of(action: str) -> str:
    return next((a for prefix, a in AREA_OF if action.startswith(prefix)), "other")


def _counts(action: str, spec) -> bool:
    specs = spec if isinstance(spec, tuple) else (spec,)
    return any(action == s or (s.endswith(".") and action.startswith(s)) for s in specs)


def _range(since: datetime | None, until: datetime | None) -> tuple[datetime, datetime]:
    until = until or utcnow()
    return since or until - timedelta(days=30), until


def _events(db: Session, user: str, area: str, since: datetime, until: datetime,
            limit: int) -> list[AuditEvent]:
    q = select(AuditEvent).where(AuditEvent.timestamp >= since, AuditEvent.timestamp <= until)
    if user:
        q = q.where(AuditEvent.username == user)
    rows = db.scalars(q.order_by(AuditEvent.id.desc()).limit(50000)).all()
    if area:
        rows = [r for r in rows if area_of(r.action) == area]
    return rows[:limit]


@router.get("/activity")
def activity(user: str = "", area: str = "", since: datetime | None = None,
             until: datetime | None = None, limit: int = Query(1000, le=5000),
             db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """Who did what: the events, a summary per user, and the jobs they ran with their
    result. Defaults to the last 30 days."""
    from app.tools.config_backup.models import BackupRun
    from app.tools.firmware_upgrade.models import UpgradeJob

    since, until = _range(since, until)
    events = _events(db, user, area, since, until, limit)
    all_events = _events(db, user, "", since, until, 50000)
    per_user: dict[str, Counter] = defaultdict(Counter)
    last: dict[str, datetime] = {}
    for e in all_events:
        if e.action == "login.failed":
            per_user[e.username]["failed_logins"] += 1
            continue
        for col, _label, spec in COUNTS:
            if _counts(e.action, spec):
                per_user[e.username][col] += 1
        last[e.username] = max(last.get(e.username, e.timestamp), e.timestamp)
    names = dict(db.execute(select(Device.id, Device.name)).all())

    jq = select(UpgradeJob).where(UpgradeJob.created_at >= since, UpgradeJob.created_at <= until)
    if user:
        jq = jq.where((UpgradeJob.created_by == user) | (UpgradeJob.started_by == user))
    jobs = [{"id": j.id, "device": names.get(j.device_id, "?"), "dry_run": j.dry_run,
             "status": j.status, "from_version": j.from_version, "target_version": j.target_version,
             "change_ref": j.change_ref, "created_by": j.created_by, "created_at": j.created_at,
             "started_by": j.started_by, "started_at": j.started_at, "finished_at": j.finished_at}
            for j in db.scalars(jq.order_by(UpgradeJob.id.desc()).limit(1000))]
    for j in jobs:
        per_user[j["created_by"]]["dry_jobs" if j["dry_run"] else "live_jobs"] += 1

    bq = select(BackupRun).where(BackupRun.started_at >= since, BackupRun.started_at <= until,
                                 BackupRun.trigger.like("manual:%"))
    if user:
        bq = bq.where(BackupRun.trigger == f"manual:{user}")
    backups = [{"id": b.id, "device": names.get(b.device_id, "?"), "by": b.trigger[7:],
                "started_at": b.started_at, "finished_at": b.finished_at, "status": b.status,
                "changed": b.changed, "message": b.message}
               for b in db.scalars(bq.order_by(BackupRun.id.desc()).limit(1000))]
    for b in backups:
        per_user[b["by"]]["backups_" + ("ok" if b["status"] == "success" else "failed")] += 1

    summary = [{"username": u, "last_activity": last.get(u), **dict(c)}
               for u, c in sorted(per_user.items())]
    return {"since": since, "until": until, "areas": ACTIVITY_AREAS,
            "columns": [{"key": k, "label": label} for k, label, _ in COUNTS]
            + [{"key": "dry_jobs", "label": "Dry-run jobs"}, {"key": "live_jobs", "label": "Live jobs"},
               {"key": "failed_logins", "label": "Failed sign-ins"}],
            "summary": summary, "jobs": jobs, "backups": backups,
            "events": [{"timestamp": e.timestamp, "username": e.username, "action": e.action,
                        "area": area_of(e.action), "detail": e.detail} for e in events],
            "users": sorted({e.username for e in all_events} | set(per_user))}


@router.get("/activity.csv")
def activity_csv(user: str = "", area: str = "", since: datetime | None = None,
                 until: datetime | None = None, db: Session = Depends(get_db),
                 _: User = Depends(require_admin)):
    since, until = _range(since, until)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Time (UTC)", "User", "Area", "Action", "Detail"])
    for e in _events(db, user, area, since, until, 50000):
        w.writerow([f"{e.timestamp:%Y-%m-%d %H:%M:%S}", e.username,
                    ACTIVITY_AREAS.get(area_of(e.action), ""), e.action, e.detail])
    return Response(out.getvalue(), media_type="text/csv", headers={
        "Content-Disposition": f'attachment; filename="netops-activity-{since:%Y%m%d}-{until:%Y%m%d}.csv"'})
