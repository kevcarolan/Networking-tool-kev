"""The report: how the network and the tools stand, and what happened over a period.

One builder (``build``) for the Report page (Activity › Report, admins) and the
scheduled email (Settings › Email alerts: the day and time, and who gets "Reports").
Each section only appears when the licence unlocks its tool. Names and counts only:
never configs, credentials or config lines.
"""

import time
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import licence
from app.core.auth import User, require_admin
from app.core.db import get_db, utcnow
from app.core.models import Device
from app.core.platforms import uses_ssh
from app.version import VERSION

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
LIST = 15  # names listed per line of the report


def build(db: Session, settings, days: int = 7, now: datetime | None = None) -> dict:
    """Every section of the report, as plain data."""
    now = now or utcnow()
    since = now - timedelta(days=days)
    modules = set(licence.status(db)["modules"])
    devices = list(db.scalars(select(Device).order_by(func.lower(Device.name))))
    out = {"generated_at": now, "since": since, "days": days, "sections": []}
    add = out["sections"].append
    lic = licence.status(db)
    add({"key": "overview", "title": "Overview", "rows": [
        ("Version", VERSION),
        ("Devices managed", len(devices)),
        *_inventory_rows(db),
        ("Licence", lic.get("message") or lic.get("mode", "")),
    ]})
    if "backups" in modules:
        add(_backups(db, devices, since))
        add(_compliance(db))
    if "firmware" in modules:
        add(_firmware(db, devices))
    if "upgrades" in modules:
        add(_upgrades(db, since))
    if "circuits" in modules:
        add(_circuits(db))
    if "syslog" in modules and getattr(settings, "syslog_dir", None):
        add(_syslog(db, settings, since, now))
    return out


def _names(items) -> str:
    items = list(items)
    return ", ".join(items[:LIST]) + (f" and {len(items) - LIST} more" if len(items) > LIST else "")


def _inventory_rows(db) -> list:
    from app.tools.inventory.models import Asset, Site

    return [("Inventory items", db.scalar(select(func.count(Asset.id))) or 0),
            ("Sites", db.scalar(select(func.count(Site.id))) or 0)]


def _backups(db, devices, since) -> dict:
    from app.tools.config_backup.models import SUCCESS, BackupRun, BackupState

    states = {s.device_id: s for s in db.scalars(select(BackupState))}
    failing = [d for d in devices if states.get(d.id) and states[d.id].last_status == "failed"]
    never = [d for d in devices if uses_ssh(d.platform)  # SNMP-only devices have no backups
             and (not states.get(d.id) or states[d.id].last_success is None)]
    runs = list(db.scalars(select(BackupRun).where(BackupRun.changed.is_(True),
                                                   BackupRun.status == SUCCESS,
                                                   BackupRun.finished_at >= since)))
    firsts = {d for (d,) in db.execute(select(BackupRun.device_id).where(
        BackupRun.status == SUCCESS, BackupRun.finished_at < since).distinct())}
    changed = sorted({next((d.name for d in devices if d.id == r.device_id), "?")
                      for r in runs if r.device_id in firsts})
    return {"key": "backups", "title": "Config backups", "rows": [
        ("Backed up OK", sum(1 for d in devices if states.get(d.id) and
                             states[d.id].last_status == SUCCESS)),
        ("Failing", len(failing), _names(f"{d.name} ({states[d.id].last_error_type or 'failed'})"
                                         for d in failing)),
        ("Never backed up", len(never), _names(d.name for d in never)),
        ("Configs changed in the period", len(changed), _names(changed)),
    ], "bad": bool(failing)}


def _compliance(db) -> dict:
    from app.tools.config_backup.models import ComplianceResult, ComplianceRule

    rules = {r.id: r for r in db.scalars(select(ComplianceRule))}
    results = list(db.scalars(select(ComplianceResult)))
    names = dict(db.execute(select(Device.id, Device.name)).all())
    failing = [r for r in results if not r.passed and r.rule_id in rules]
    by_rule: dict[str, list[str]] = {}
    for r in failing:
        by_rule.setdefault(rules[r.rule_id].name, []).append(names.get(r.device_id, "?"))
    critical = sum(1 for r in failing if rules[r.rule_id].severity == "critical")
    rows = [("Rules", len(rules)),
            ("Devices checked", len({r.device_id for r in results})),
            ("Devices failing a rule", len({r.device_id for r in failing})),
            ("Critical failures", critical)]
    rows += [(f"Failing: {rule}", len(devs), _names(sorted(devs)))
             for rule, devs in sorted(by_rule.items(), key=lambda x: -len(x[1]))]
    return {"key": "compliance", "title": "Config compliance", "rows": rows, "bad": bool(critical)}


def _firmware(db, devices) -> dict:
    from app.tools.inventory.api import _status_of_devices

    _b, _f, comp = _status_of_devices(db, [d.id for d in devices])
    behind = [d.name for d in devices if comp.get(d.id) == "behind"]
    return {"key": "firmware", "title": "Firmware", "rows": [
        ("On the standard", sum(1 for v in comp.values() if v == "compliant")),
        ("Behind the standard", len(behind), _names(behind)),
        ("No standard set", sum(1 for v in comp.values() if v == "no_standard")),
        ("Version not known yet", sum(1 for v in comp.values() if v == "unknown")),
    ], "bad": bool(behind)}


def _upgrades(db, since) -> dict:
    from app.tools.firmware_upgrade.models import UpgradeJob

    jobs = list(db.scalars(select(UpgradeJob).where(UpgradeJob.finished_at >= since,
                                                    UpgradeJob.dry_run.is_(False))))
    names = dict(db.execute(select(Device.id, Device.name)).all())
    by = {}
    for j in jobs:
        by.setdefault(j.status, []).append(f"{names.get(j.device_id, '?')} → {j.target_version}")
    rows = [("Live upgrades finished in the period", len(jobs))]
    rows += [(status.replace("_", " ").capitalize(), len(v), _names(v)) for status, v in sorted(by.items())]
    return {"key": "upgrades", "title": "Upgrade jobs", "rows": rows,
            "bad": any(s in by for s in ("failed", "rolled_back", "needs_attention"))}


def _circuits(db) -> dict:
    from app.tools.circuits import live
    from app.tools.circuits.api import _export_rows

    rows = _export_rows(db)
    count = lambda st: [r for r in rows if r["live_status"] == st]  # noqa: E731
    moved, missing = count(live.MOVED), count(live.NOT_SEEN)
    return {"key": "circuits", "title": "Circuits", "rows": [
        ("Circuits in the list", len(rows)),
        ("Where the list says", len(count(live.MATCHES))),
        ("Moved", len(moved), _names(r["device_name"] or r["mac"] for r in moved)),
        ("Not seen on the network", len(missing), _names(r["device_name"] or r["mac"] for r in missing)),
    ], "bad": bool(moved or missing)}


def _syslog(db, settings, since, now) -> dict:
    from app.tools.syslog.parse import LABELS
    from app.tools.syslog.sources import device_addresses
    from app.tools.syslog.store import Filter, SyslogStore

    f = Filter(since=since.replace(tzinfo=UTC).timestamp(), until=now.replace(tzinfo=UTC).timestamp())
    try:
        s = SyslogStore(settings.syslog_dir).summary(f, buckets=1)
        bad = SyslogStore(settings.syslog_dir).summary(
            Filter(f.since, f.until, severities=[0, 1, 2, 3]), buckets=1)
    except Exception:  # noqa: BLE001 - no syslog files yet
        return {"key": "syslog", "title": "Syslog", "rows": [("Messages", 0)]}
    names = device_addresses(db)
    top = sorted(bad["sources"].items(), key=lambda x: -x[1])[:5]
    return {"key": "syslog", "title": "Syslog", "rows": [
        ("Messages in the period", sum(s["severity"])),
        *[(f"{LABELS[i]}", n) for i, n in enumerate(s["severity"][:4]) if n],
        ("Most errors and worse", len(top), _names(f"{names[src][1] if src in names else src} ({n})"
                                                    for src, n in top)),
    ], "bad": bool(sum(s["severity"][:3]))}


# --- text for the email ----------------------------------------------------------------------

def as_text(report: dict) -> str:
    lines = [f"From {report['since']:%Y-%m-%d %H:%M} to {report['generated_at']:%Y-%m-%d %H:%M} UTC "
             f"({report['days']} days).", ""]
    for sec in report["sections"]:
        lines.append(sec["title"].upper() + ("  (needs a look)" if sec.get("bad") else ""))
        for row in sec["rows"]:
            label, value, *more = row
            lines.append(f"  {label}: {value}" + (f"\n      {more[0]}" if more and more[0] else ""))
        lines.append("")
    lines.append("The full picture is on each page; this report is on Activity › Report.")
    return "\n".join(lines)


def due(schedule_day: str, schedule_time: str, last_sent: str, now: datetime | None = None
        ) -> str | None:
    """The slot to send now ("2026-10-12 07:00"), or None. Sent once per slot, at or after the
    chosen day and time (UTC)."""
    if schedule_day not in DAYS or not schedule_time:
        return None
    now = now or utcnow()
    try:
        hh, mm = (int(x) for x in schedule_time.split(":"))
    except ValueError:
        return None
    days_back = (now.weekday() - DAYS.index(schedule_day)) % 7
    slot = (now - timedelta(days=days_back)).replace(hour=hh, minute=mm, second=0, microsecond=0)
    if slot > now:
        slot -= timedelta(days=7)
    if now - slot > timedelta(days=1):
        return None  # missed by more than a day (server off): wait for the next one
    key = f"{slot:%Y-%m-%d %H:%M}"
    return None if key == last_sent else key


# --- API ----------------------------------------------------------------------------------------

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("")
def report(request: Request, days: int = Query(7, ge=1, le=90), db: Session = Depends(get_db),
           _: User = Depends(require_admin)):
    started = time.monotonic()
    out = build(db, request.app.state.settings, days)
    out["took_ms"] = int((time.monotonic() - started) * 1000)
    return out

