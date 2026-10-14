"""The wall display: a read-only status dashboard for a NOC screen or an engineers' office.

* An admin adds a **display screen** on the Settings page and gets a link with a long random
  key, shown once. The screen's browser keeps the key in the link's #fragment (never sent
  to the web server's logs) and sends it with each request.
* The page (static/display/) asks for ``/api/display/data`` every 30 seconds and shows its
  pages in turn (each screen chooses which, ``PAGES``): an overview (backups, compliance,
  config changes, firmware, upgrades, server health, failing devices), the upgrades under
  way with the circuits they affect, a sites grid, and the network (syslog errors, config
  changes, circuits that moved or went missing), and monitoring (devices down, warnings,
  restarts).
* Installed servers serve the display on its own port (NETOPS_DISPLAY_PORT, 8443), and
  only there: the nginx site refuses /display/ and /api/display/ on the main port, and the
  host firewall decides who reaches the display port.
* The feed holds counts, names and statuses only: never configs, credentials or addresses,
  nor syslog message text (which can hold addresses): a message is its device, severity,
  time and type (the tag, e.g. %LINK-3-UPDOWN).
"""

import hashlib
import json
import secrets
import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta

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
RECENT = timedelta(hours=24)  # config changes and syslog errors shown on the wall
PAGES = {"overview": "Overview", "monitoring": "Monitoring", "upgrades": "Upgrades",
         "sites": "Sites", "network": "Network"}
LIST_ROWS = 10


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


# --- admin: the screens ----------------------------------------------------------------

admin_router = APIRouter(prefix="/api/displays", tags=["display"])


def _pages(s: DisplayScreen) -> list[str]:
    try:
        chosen = [p for p in json.loads(s.pages or "[]") if p in PAGES]
    except ValueError:
        chosen = []
    return chosen or list(PAGES)


def _screen_out(s: DisplayScreen) -> dict:
    return {"id": s.id, "name": s.name, "created_by": s.created_by, "created_at": s.created_at,
            "last_seen_at": s.last_seen_at, "last_seen_from": s.last_seen_from,
            "pages": _pages(s)}


@admin_router.get("")
def list_screens(request: Request, db: Session = Depends(get_db),
                 _: User = Depends(require_admin)):
    return {"port": request.app.state.settings.display_port, "page_names": PAGES,
            "screens": [_screen_out(s) for s in db.scalars(select(DisplayScreen)
                                                            .order_by(DisplayScreen.name))]}


class ScreenIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    pages: list[str] = Field(default_factory=list, max_length=len(PAGES))  # empty: every page


def _check_pages(pages: list[str]) -> str:
    if bad := [p for p in pages if p not in PAGES]:
        raise HTTPException(422, f"Unknown page: {', '.join(bad)}")
    return json.dumps([p for p in PAGES if p in pages])


@admin_router.post("", status_code=201)
def add_screen(body: ScreenIn, db: Session = Depends(get_db),
               user: User = Depends(require_admin)):
    key = secrets.token_urlsafe(32)
    screen = DisplayScreen(name=body.name.strip(), key_hash=_hash(key), created_by=user.username,
                           pages=_check_pages(body.pages))
    db.add(screen)
    db.flush()
    audit(db, user.username, "display.add", screen.name)
    return {**_screen_out(screen), "key": key}  # the only time the key is shown


@admin_router.put("/{screen_id}")
def change_screen(screen_id: int, body: ScreenIn, db: Session = Depends(get_db),
                  user: User = Depends(require_admin)):
    """Rename a screen or choose its pages (its link stays the same)."""
    screen = db.get(DisplayScreen, screen_id)
    if screen is None:
        raise HTTPException(404, "Display screen not found")
    screen.name, screen.pages = body.name.strip(), _check_pages(body.pages)
    audit(db, user.username, "display.change", f"{screen.name}: {', '.join(_pages(screen))}")
    return _screen_out(screen)


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
    return {**snapshot(db, request.app.state), "screen": screen.name, "pages": _pages(screen)}


def snapshot(db: Session, state) -> dict:
    from app.core import licence

    now = utcnow()
    settings = state.settings
    modules = set(licence.status(db)["modules"])
    devices = {d.id: d for d in db.scalars(select(Device))}
    backups, failing = _backups(db, settings, devices)
    firmware, behind = _firmware(db, state, devices)
    upgrades = _upgrades(db, settings, now)
    out = {
        "generated_at": now, "product_name": settings.product_name,
        "site_name": settings.site_name, "modules": sorted(modules),
        "backups": backups, "attention": failing[:ATTENTION_ROWS],
        "attention_more": max(0, len(failing) - ATTENTION_ROWS),
        "firmware": firmware, "upgrades": upgrades, "server": _server(db),
        "compliance": None, "changes": None, "circuits": None, "syslog": None,
        "monitoring": None,
    }
    failing_rules: dict[int, int] = {}
    if "backups" in modules:
        out["compliance"], failing_rules = _compliance(db, devices)
        out["changes"] = _changes(db, devices, now)
    circuit_problems: dict[str, int] = {}
    if "circuits" in modules:
        out["circuits"], circuit_problems = _circuits(db)
    if "syslog" in modules and getattr(settings, "syslog_dir", None):
        out["syslog"] = _syslog(db, settings)
    down: dict[int, str] = {}
    if "monitoring" in modules and getattr(settings, "monitor_dir", None):
        out["monitoring"], down = _monitoring(db, settings, devices)
    out["sites"] = _sites(db, devices, failing, behind, upgrades, failing_rules, circuit_problems,
                          down)
    return out


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


def _compliance(db: Session, devices: dict) -> tuple[dict, dict[int, int]]:
    """Devices failing compliance rules: counts and rule names (never config lines)."""
    from app.tools.config_backup.models import ComplianceResult, ComplianceRule

    rules = {r.id: r for r in db.scalars(select(ComplianceRule))}
    per_device: dict[int, int] = defaultdict(int)
    per_rule: dict[int, int] = defaultdict(int)
    checked = set()
    critical = 0
    for r in db.scalars(select(ComplianceResult)):
        if r.device_id not in devices or r.rule_id not in rules:
            continue
        checked.add(r.device_id)
        if not r.passed:
            per_device[r.device_id] += 1
            per_rule[r.rule_id] += 1
            critical += rules[r.rule_id].severity == "critical"
    return {"rules": len(rules), "checked": len(checked), "failing": len(per_device),
            "critical": critical,
            "top": [{"rule": rules[k].name, "devices": n, "critical": rules[k].severity == "critical"}
                    for k, n in sorted(per_rule.items(), key=lambda x: -x[1])[:5]]}, per_device


def _changes(db: Session, devices: dict, now: datetime) -> dict:
    """Configs a backup found changed in the last 24 hours (not a device's first backup)."""
    from app.tools.config_backup.models import SUCCESS, BackupRun

    rows = []
    for run in db.scalars(select(BackupRun).where(
            BackupRun.changed.is_(True), BackupRun.status == SUCCESS,
            BackupRun.finished_at >= now - RECENT).order_by(BackupRun.finished_at.desc())):
        d = devices.get(run.device_id)
        first = db.scalar(select(BackupRun.id).where(
            BackupRun.device_id == run.device_id, BackupRun.status == SUCCESS,
            BackupRun.id < run.id).limit(1)) is None
        if d is not None and not first:
            rows.append({"device": d.name, "site": d.site, "at": run.finished_at})
    return {"count": len(rows), "rows": rows[:LIST_ROWS]}


def _circuits(db: Session) -> tuple[dict, dict[str, int]]:
    """Circuits by where the network found them; moved and missing ones by name only."""
    from app.tools.circuits import live
    from app.tools.circuits.api import _export_rows

    rows = _export_rows(db)
    counts = defaultdict(int)
    problems, per_site = [], defaultdict(int)
    for r in rows:
        counts[r["live_status"] or "not_scanned"] += 1
        if r["live_status"] in (live.MOVED, live.NOT_SEEN):
            problems.append({"name": r["device_name"] or r["service"] or "(no name)",
                             "service": r["service"], "status": r["live_status_label"],
                             "site": r["site_name"] or r["site_text"]})
            per_site[(r["site_name"] or r["site_text"] or "-").lower()] += 1
    return {"total": len(rows), "matches": counts[live.MATCHES], "moved": counts[live.MOVED],
            "not_seen": counts[live.NOT_SEEN], "found": counts[live.FOUND],
            "problems": problems[:LIST_ROWS], "problems_more": max(0, len(problems) - LIST_ROWS)
            }, per_site


def _syslog(db: Session, settings) -> dict:
    """Error-or-worse messages of the last 24 hours: counts, and the latest by device,
    severity and type only (message text can hold addresses, so it isn't shown)."""
    from app.tools.syslog.parse import LABELS
    from app.tools.syslog.sources import device_addresses
    from app.tools.syslog.store import Filter, SyslogStore

    now = time.time()
    f = Filter(since=now - RECENT.total_seconds(), until=now, severities=[0, 1, 2, 3])
    try:
        store = SyslogStore(settings.syslog_dir)
        summary = store.summary(f, buckets=1)
        rows, _ = store.search(f, limit=LIST_ROWS)
    except Exception:  # noqa: BLE001 - no syslog files yet
        return {"counts": [0, 0, 0, 0], "latest": [], "top": []}
    names = device_addresses(db)
    name = lambda src: names[src][1] if src in names else "a sender not in the inventory"  # noqa: E731
    top = sorted(summary["sources"].items(), key=lambda x: -x[1])[:5]
    return {"counts": summary["severity"][:4],
            "latest": [{"device": name(r["src"]), "severity": LABELS[r["sev"]], "sev": r["sev"],
                        "at": datetime.fromtimestamp(r["ts"], UTC).replace(tzinfo=None)
                        .isoformat(timespec="seconds"),
                        "type": (r["tag"] or "")[:60]} for r in rows],
            "top": [{"device": name(src), "count": n} for src, n in top]}


def _monitoring(db: Session, settings, devices: dict) -> tuple[dict, dict[int, str]]:
    """Devices down or with a warning, the last day's events, and the busiest ports and
    those with errors: names, sites, port names and numbers only (a reason or a port's
    description can hold an address, so neither is shown). Hardware problems name the part
    as the device names it (e.g. "PowerSupply-2 failed")."""
    from app.tools.monitoring.api import EVENT_LABELS
    from app.tools.monitoring.store import MonitorStore

    store = MonitorStore(settings.monitor_dir)
    status = store.status() or {}
    running = bool(status) and time.time() - float(status.get("beat") or 0) < max(
        3 * settings.monitor_poll_seconds, 120)
    states = {k: v for k, v in store.states().items() if k in devices}
    counts = {"up": 0, "warning": 0, "down": 0, "unknown": 0, "maintenance": 0}
    down_rows, warn_rows, down = [], [], {}
    for device_id, st in states.items():
        d = devices[device_id]
        counts[st["status"]] = counts.get(st["status"], 0) + 1
        counts["maintenance"] += bool(st["maintenance"])
        row = {"device": d.name, "site": d.site, "maintenance": bool(st["maintenance"]),
               "since": datetime.fromtimestamp(st["since"], UTC).replace(tzinfo=None)
               .isoformat(timespec="seconds")}
        if st["status"] == "down":
            down_rows.append(row)
            down[device_id] = d.site
        elif st["status"] == "warning":
            problem = ("hardware problem" if (st["reason"] or "").startswith("Hardware") else
                       "SNMP not answering" if st["snmp_ok"] == 0 else
                       "no reply to ping" if st["ping_ok"] == 0 and st["snmp_ok"] else
                       "missed a check")
            warn_rows.append({**row, "problem": problem})
    down_rows.sort(key=lambda r: (r["maintenance"], r["since"]))
    warn_rows.sort(key=lambda r: r["since"])
    now = time.time()
    events = [{"device": devices[e["device_id"]].name, "kind": e["kind"],
               "label": EVENT_LABELS.get(e["kind"], e["kind"]), "maintenance": bool(e["maintenance"]),
               "at": datetime.fromtimestamp(e["ts"], UTC).replace(tzinfo=None).isoformat(timespec="seconds")}
              for e in store.events(now - RECENT.total_seconds(), now + 60, limit=LIST_ROWS * 3)
              if e["device_id"] in devices][:LIST_ROWS]
    ports = [r for r in store.interfaces() if r["device_id"] in devices and r["admin"] == 1
             and r["oper"] == 1]
    util = lambda r: max([u for u in (r["in_util"], r["out_util"]) if u is not None], default=None)  # noqa: E731
    busiest = sorted((r for r in ports if util(r) is not None), key=lambda r: -util(r))[:6]
    errors = sorted((r for r in ports if (r["errors"] or 0) + (r["discards"] or 0) > 0),
                    key=lambda r: -((r["errors"] or 0) * 10 + (r["discards"] or 0)))[:6]
    port = lambda r: {"device": devices[r["device_id"]].name, "port": r["name"] or r["descr"]}  # noqa: E731
    hardware = []
    for device_id, h in (store.health() or {}).items():
        if h["problems"] and device_id in devices and device_id in states:
            hardware.append({"device": devices[device_id].name, "site": devices[device_id].site,
                             "critical": h["status"] == "critical",
                             "problems": sorted(h["problems"].values())[:3]})
    hardware.sort(key=lambda r: (not r["critical"], r["device"]))
    counts["hardware"] = len(hardware)
    return {"running": running, "counts": counts, "monitored": len(states),
            "hardware": hardware[:LIST_ROWS],
            "busiest": [{**port(r), "util": round(util(r), 3)} for r in busiest],
            "port_errors": [{**port(r), "errors": r["errors"] or 0, "discards": r["discards"] or 0}
                            for r in errors],
            "down": down_rows[:LIST_ROWS], "down_more": max(0, len(down_rows) - LIST_ROWS),
            "warnings": warn_rows[:LIST_ROWS], "warnings_more": max(0, len(warn_rows) - LIST_ROWS),
            "events": events}, down


def _sites(db: Session, devices: dict, failing: list, behind: set, upgrades: dict,
           failing_rules: dict[int, int], circuit_problems: dict[str, int],
           down: dict[int, str] | None = None) -> list[dict]:
    """One tile per site: the site list's sites (by name or code), and any other Site value
    the devices use."""
    from app.tools.inventory.models import Site
    from app.tools.inventory.sites import _index

    index = _index(list(db.scalars(select(Site))))

    def site_of(text: str) -> str:
        s = index.get((text or "").strip().lower())
        return s.name if s else (text or "-")

    sites = defaultdict(lambda: {"devices": 0, "failing": 0, "behind": 0, "upgrading": 0,
                                 "compliance": 0, "circuits": 0, "down": 0, "listed": False})
    for s in index.values():
        sites[s.name]["listed"] = True
    for d in devices.values():
        name = site_of(d.site)
        sites[name]["devices"] += 1
        sites[name]["behind"] += d.id in behind
        sites[name]["compliance"] += 1 if failing_rules.get(d.id) else 0
    for f in failing:
        sites[site_of(f["site"])]["failing"] += 1
    for j in upgrades["under_way"]:
        sites[site_of(j["site"])]["upgrading"] += 1
    for key, n in circuit_problems.items():
        sites[site_of(key)]["circuits"] += n
    for site in (down or {}).values():
        sites[site_of(site)]["down"] += 1
    return [{"site": name, **v} for name, v in sorted(sites.items(), key=lambda x: x[0].lower())]
