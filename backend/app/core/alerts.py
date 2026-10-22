"""Email alerts, sent through the customer's own mail server (SMTP).

An admin sets the mail server, the recipients and which alerts to send on the Settings
page (stored in app_settings; the SMTP password encrypted with the credential key). Once a
minute the web app's scheduler looks at the state of things and sends what is new:

* **Backups:** devices whose backup has been failing for longer than N hours (24 by
  default), in one email per check, once per failure.
* **Upgrades:** an upgrade job that has completed, failed, rolled back or needs attention.
* **Licence:** 30 and 7 days before it ends, and when it has ended (or the trial has).
* **Upgrade worker:** stopped for more than 10 minutes.
* **Monitoring:** devices that went down, came back up or restarted (not those in a
  maintenance window or upgrade), gathered into one email per check.
* **Syslog:** device messages at Critical or worse (the level is a setting), gathered into
  at most one email every few minutes, so a storm of messages is one email, not hundreds.

Each recipient chooses which kinds of alert they get (``recipients``). Alerts nobody
wants aren't looked for.

Every alert sent is recorded in the ``alerts_sent`` table, so it is sent once only; one
that fails to send is tried again at the next check. Only events after alerts were switched
on are sent, so switching them on doesn't send the history.
"""

import json
import logging
import re
import time
import smtplib
import ssl
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import appsettings
from app.core.audit import audit
from app.core.auth import User, require_admin
from app.core.db import get_db, session_scope, utcnow
from app.core.models import AlertSent, Device

log = logging.getLogger(__name__)

PREFIX = "alerts_"
KEYS = ("enabled", "smtp_host", "smtp_port", "smtp_security", "smtp_user", "mail_from",
        "mail_to", "backup_hours", "upgrades", "licence", "worker", "recipients",
        "syslog_level", "syslog_minutes", "changes_diff", "report_day", "report_time",
        "report_days")
KINDS = {"backups": "Backups", "changes": "Config changes", "compliance": "Compliance",
         "upgrades": "Upgrades",
         "licence": "Licence", "worker": "Upgrade worker", "syslog": "Syslog",
         "monitoring": "Devices down or up",
         "circuits": "Circuits moved, missing or on the wrong VLAN",
         "carriers": "Carrier contracts ending",
         "reports": "Report"}
LAST_REPORT = PREFIX + "report_last"  # the last report slot sent
CHANGES_LIMIT = 30  # devices listed in one email
DIFF_LINES = 40  # changed lines shown per device, when the diff is included
# A changed line that may hold a secret is never put in an email.
_SECRET = re.compile(r"secret|passw|key|community|psk|hash|encrypt|private|token|cert", re.I)
# What devices log when someone changes their config (Cisco, Junos, Arista, AlliedWare...)
_WHO = re.compile(r"CONFIG_I|configured from|UI_COMMIT|config(uration)? (was )?(changed|saved)"
                  r"|committed|SYS-5-CONFIG", re.I)
CIRCUITS_SCAN = PREFIX + "circuits_scan"  # the last network scan the circuit rules were checked on
CIRCUITS_LIMIT = 50  # circuits listed in one email
SYSLOG_AFTER = PREFIX + "syslog_after"  # messages received after this time are still to send
SYSLOG_LIMIT = 50  # messages listed in one email
PASSWORD = PREFIX + "smtp_password_enc"
ENABLED_AT = PREFIX + "enabled_at"
LAST_ERROR = PREFIX + "last_error"
SECURITY = ("starttls", "tls", "none")
WORKER_DOWN = timedelta(minutes=10)
JOB_ALERTS = {"completed": "completed", "completed_overrides": "completed with overrides",
              "failed": "FAILED", "rolled_back": "rolled back",
              "needs_attention": "NEEDS ATTENTION"}
_EMAIL = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")


@dataclass(frozen=True)
class Recipient:
    address: str
    kinds: frozenset[str]


@dataclass
class Config:
    enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_security: str = "starttls"
    smtp_user: str = ""
    smtp_password: str = ""
    mail_from: str = ""
    mail_to: tuple[str, ...] = ()
    backup_hours: int = 24
    upgrades: bool = True
    licence: bool = True
    worker: bool = True
    enabled_at: datetime | None = None
    recipients: tuple[Recipient, ...] = ()
    syslog_level: int = 2  # Critical and worse
    syslog_minutes: int = 5
    changes_diff: bool = False  # put the changed lines (secrets left out) in config change emails
    report_day: str = ""  # mon..sun, or "" for no scheduled report
    report_time: str = "07:00"  # UTC
    report_days: int = 7  # the period it covers

    def to(self, kind: str) -> list[str]:
        """Who gets this kind of alert."""
        return [r.address for r in self.recipients if kind in r.kinds]

    def wanted(self, kind: str) -> bool:
        return bool(self.to(kind))


def load(db: Session, cipher=None) -> Config:
    v = appsettings.stored(db)
    get = lambda k, d="": v.get(PREFIX + k, d)  # noqa: E731
    password = ""
    if cipher is not None and v.get(PASSWORD):
        try:
            password = cipher.decrypt(v[PASSWORD])
        except Exception:  # noqa: BLE001 - the credential key was replaced
            password = ""
    mail_to = tuple(a for a in get("mail_to").split(",") if a)
    upgrades = get("upgrades", "true") == "true"
    lic = get("licence", "true") == "true"
    worker = get("worker", "true") == "true"
    backup_hours = int(get("backup_hours", "24") or 24)
    try:
        recipients = tuple(Recipient(r["address"], frozenset(r["kinds"]) & set(KINDS))
                           for r in json.loads(get("recipients")))
    except (ValueError, KeyError, TypeError):
        # Saved before recipients chose: everyone gets what was switched on.
        kinds = frozenset(k for k, on in (("backups", backup_hours > 0), ("upgrades", upgrades),
                                          ("licence", lic), ("worker", worker)) if on)
        recipients = tuple(Recipient(a, kinds) for a in mail_to)
    return Config(
        enabled=get("enabled") == "true", smtp_host=get("smtp_host"),
        smtp_port=int(get("smtp_port", "587") or 587),
        smtp_security=get("smtp_security", "starttls") or "starttls",
        smtp_user=get("smtp_user"), smtp_password=password, mail_from=get("mail_from"),
        mail_to=tuple(r.address for r in recipients), backup_hours=backup_hours,
        upgrades=any("upgrades" in r.kinds for r in recipients),
        licence=any("licence" in r.kinds for r in recipients),
        worker=any("worker" in r.kinds for r in recipients),
        enabled_at=datetime.fromisoformat(v[ENABLED_AT]) if v.get(ENABLED_AT) else None,
        recipients=recipients, syslog_level=int(get("syslog_level", "2") or 2),
        syslog_minutes=int(get("syslog_minutes", "5") or 5),
        changes_diff=get("changes_diff") == "true", report_day=get("report_day"),
        report_time=get("report_time", "07:00") or "07:00",
        report_days=int(get("report_days", "7") or 7))


# --- sending -----------------------------------------------------------------------------

Mailer = Callable[[Config, EmailMessage], None]


def smtp_send(cfg: Config, msg: EmailMessage) -> None:
    """Send through the configured server. Certificates are always checked."""
    context = ssl.create_default_context()
    if cfg.smtp_security == "tls":
        server = smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, timeout=20, context=context)
    else:
        server = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=20)
    with server:
        if cfg.smtp_security == "starttls":
            server.starttls(context=context)
        if cfg.smtp_user:
            server.login(cfg.smtp_user, cfg.smtp_password)
        server.send_message(msg)


def message(cfg: Config, settings, subject: str, body: str,
            to: list[str] | tuple[str, ...] | None = None) -> EmailMessage:
    who = settings.product_name + (f" · {settings.site_name}" if settings.site_name else "")
    msg = EmailMessage()
    msg["Subject"] = f"[{who}] {subject}"
    msg["From"] = cfg.mail_from
    msg["To"] = ", ".join(to if to is not None else cfg.mail_to)
    msg.set_content(body.rstrip() + f"\n\n-- \nSent by {who}. Alerts are set on the Settings "
                                    "page (admins).\n")
    return msg


# --- what to send ------------------------------------------------------------------------

@dataclass
class Alert:
    keys: list[str]  # recorded once sent
    subject: str
    body: str
    kind: str = "backups"
    save: dict | None = None  # settings to store once it is sent

def _sent(db: Session) -> set[str]:
    return set(db.scalars(select(AlertSent.key)))


def due(db: Session, cfg: Config, now: datetime | None = None, syslog_dir=None,
        configs_dir=None, monitor_dir=None) -> list[Alert]:
    from app.core import licence

    now = now or utcnow()
    since = cfg.enabled_at or now
    done = _sent(db)
    modules = set(licence.status(db)["modules"])  # only the tools the licence unlocks
    out = []
    if cfg.backup_hours and cfg.wanted("backups") and "backups" in modules:
        out += _backups(db, cfg, now, done)
    if cfg.wanted("compliance") and "backups" in modules:
        out += _compliance(db, since, done)
    if cfg.wanted("changes") and "backups" in modules:
        out += _changes(db, cfg, since, done, configs_dir,
                        syslog_dir if "syslog" in modules else None)
    if cfg.wanted("upgrades") and "upgrades" in modules:
        out += _upgrades(db, since, done)
    if cfg.wanted("licence"):
        out += _licence(db, done)
    if cfg.wanted("worker") and "upgrades" in modules:
        out += _worker(db, now, done)
    if monitor_dir is not None and cfg.wanted("monitoring") and "monitoring" in modules:
        out += _monitoring(db, since, now, done, monitor_dir)
        out += _meraki(since, now, done, monitor_dir)
    if cfg.wanted("carriers") and "circuits" in modules:
        out += _carriers(db, now, done)
    if cfg.wanted("circuits") and "circuits" in modules:
        out += _circuits(db, now, done)
    if syslog_dir is not None and "syslog" in modules:
        out += _syslog(db, cfg, syslog_dir)
    return out


def _carriers(db, now, done) -> list[Alert]:
    """Carrier circuit contracts that end within 60 days: one email when each reaches 60
    days and again at 14, so there is time to renew or give notice."""
    from app.tools.circuits.carriers import contract_alert_rows, label

    rows = []
    for c, days in contract_alert_rows(db, now.date()):
        mark = 14 if days <= 14 else 60
        key = f"carrier:{c.id}:{c.contract_end}:{mark}"
        if key not in done:
            rows.append((key, c, days))
    if not rows:
        return []
    lines = [f"  {label(c)}{f' ({c.site})' if c.site else ''}: "
             + (f"ended {-days} day(s) ago" if days < 0 else f"ends {c.contract_end} (in {days} days)")
             + (f". {c.support}" if c.support else "") for _, c, days in rows]
    keys = [k for k, _, _ in rows] + [f"carrier:{c.id}:{c.contract_end}:60" for _, c, d in rows if d <= 14]
    return [Alert(keys, f"Carrier contracts ending: {len(rows)}",
                  "These carrier circuit contracts end soon:\n\n" + "\n".join(lines) +
                  "\n\nRenew them or give notice in time. The list is on the Circuits page "
                  "(Carrier circuits).", kind="carriers")]


def _circuits(db, now, done) -> list[Alert]:
    """What the circuit rules flag (moved, not seen, wrong VLAN), checked once after each
    network scan; each problem is emailed once."""
    from app.tools.circuits.models import CircuitScan
    from app.tools.circuits.rules import problems

    scan = db.scalar(select(CircuitScan.id).where(CircuitScan.finished_at.is_not(None))
                     .order_by(CircuitScan.id.desc()).limit(1))
    if scan is None or appsettings.stored(db).get(CIRCUITS_SCAN) == str(scan):
        return []
    rows = [p for p in problems(db, now) if p[0] not in done]
    if not rows:
        appsettings.save(db, {CIRCUITS_SCAN: str(scan)}, "system")
        return []
    counts = {k: sum(1 for _, kind, _ in rows if kind == k) for k in ("moved", "missing", "vlan")}
    words = {"moved": "moved", "missing": "not seen", "vlan": "on the wrong VLAN"}
    subject = "Circuits: " + ", ".join(f"{n} {words[k]}" for k, n in counts.items() if n)
    lines = [line for _, _, line in rows[:CIRCUITS_LIMIT]]
    more = f"\n  ...and {len(rows) - CIRCUITS_LIMIT} more." if len(rows) > CIRCUITS_LIMIT else ""
    return [Alert([k for k, _, _ in rows], subject,
                  "The last network scan found these circuits breaking their rules:\n\n"
                  + "\n".join(lines) + more + "\n\nThe list and the rules are on the Circuits page.",
                  kind="circuits", save={CIRCUITS_SCAN: str(scan)})]


MONITOR_KINDS = ("down", "up", "restarted", "port_down", "port_up", "health_problem", "health_ok", "failover")
MONITOR_LIMIT = 50  # events listed in one email


def _meraki(since, now, done, monitor_dir) -> list[Alert]:
    """Meraki devices that went offline, alerting or back online (Dashboard API)."""
    from app.tools.monitoring.store import MonitorStore

    start = max(since, now - timedelta(hours=24)).replace(tzinfo=UTC).timestamp()
    rows = [e for e in MonitorStore(monitor_dir).meraki_events(start, now.replace(tzinfo=UTC).timestamp() + 60,
                                                                limit=500)
            if f"mk:{e['id']}" not in done]
    if not rows:
        return []
    rows.sort(key=lambda e: e["ts"])
    label = {"meraki_offline": "OFFLINE", "meraki_alerting": "ALERTING", "meraki_online": "back online"}
    lines = [f"  {datetime.fromtimestamp(e['ts'], UTC):%Y-%m-%d %H:%M} UTC  {e['name']} ({e['network'] or '-'})  "
             f"{label.get(e['kind'], e['kind'])}: {e['detail'][:200]}" for e in rows[:MONITOR_LIMIT]]
    latest = {}
    for e in rows:
        latest[e["serial"]] = e
    bad = sorted(e["name"] for e in latest.values() if e["kind"] != "meraki_online")
    good = sorted(e["name"] for e in latest.values() if e["kind"] == "meraki_online")
    short = lambda xs: ", ".join(xs[:4]) + (" …" if len(xs) > 4 else "")  # noqa: E731
    parts = ([f"{len(bad)} offline or alerting: {short(bad)}"] if bad else []) + \
        ([f"{len(good)} back online: {short(good)}"] if good else [])
    return [Alert([f"mk:{e['id']}" for e in rows], "Meraki: " + "; ".join(parts),
                  "From the Meraki Dashboard API:\n\n" + "\n".join(lines) +
                  "\n\nThe details are on the Monitoring page (Meraki).", kind="monitoring")]


def _monitoring(db, since, now, done, monitor_dir) -> list[Alert]:
    """Devices that went down, came back or restarted since the last check (at most a day
    back). Events in a maintenance window are recorded, not sent."""
    from app.tools.monitoring.store import MonitorStore

    start = max(since, now - timedelta(hours=24)).replace(tzinfo=UTC).timestamp()
    rows = [e for e in MonitorStore(monitor_dir).events(start, now.replace(tzinfo=UTC).timestamp() + 60,
                                                         kinds=list(MONITOR_KINDS), limit=1000)
            if f"mon:{e['id']}" not in done]
    if not rows:
        return []
    keys = [f"mon:{e['id']}" for e in rows]
    rows = [e for e in rows if not e["maintenance"]]
    if not rows:
        return [Alert(keys, "", "", kind="monitoring")]  # maintenance only: nothing to send
    rows.sort(key=lambda e: e["ts"])
    names = {d.id: d for d in db.scalars(select(Device))}
    label = {"down": "DOWN", "up": "back up", "restarted": "restarted", "port_down": "PORT DOWN",
             "port_up": "port back up", "health_problem": "HARDWARE", "health_ok": "hardware OK",
             "failover": "FAILOVER"}
    lines = []
    for e in rows[:MONITOR_LIMIT]:
        d = names.get(e["device_id"])
        who = f"{d.name} ({d.site or '-'})" if d else f"device {e['device_id']}"
        lines.append(f"  {datetime.fromtimestamp(e['ts'], UTC):%Y-%m-%d %H:%M} UTC  {who}  "
                     f"{label[e['kind']]}: {e['detail'][:200]}")
    latest: dict[int, dict] = {}
    for e in rows:
        if e["kind"] in ("down", "up"):
            latest[e["device_id"]] = e
    still_down = sorted(names[i].name for i, e in latest.items() if e["kind"] == "down" and i in names)
    back = sorted(names[i].name for i, e in latest.items() if e["kind"] == "up" and i in names)
    restarted = sorted({names[e["device_id"]].name for e in rows
                        if e["kind"] == "restarted" and e["device_id"] in names})
    short = lambda xs: ", ".join(xs[:4]) + (" …" if len(xs) > 4 else "")  # noqa: E731
    parts = []
    if still_down:
        parts.append(f"{len(still_down)} down: {short(still_down)}")
    if back:
        parts.append(f"{len(back)} back up: {short(back)}")
    if restarted and not still_down and not back:
        parts.append(f"{len(restarted)} restarted: {short(restarted)}")
    elif restarted:
        parts.append(f"{len(restarted)} restarted")
    failed_over = sorted({names[e["device_id"]].name for e in rows
                          if e["kind"] == "failover" and e["device_id"] in names})
    if failed_over:
        parts.append(f"failover: {short(failed_over)}")
    hardware = sorted({names[e["device_id"]].name for e in rows
                       if e["kind"] == "health_problem" and e["device_id"] in names})
    if hardware:
        parts.append(f"hardware: {short(hardware)}")
    ports_down = [e for e in rows if e["kind"] == "port_down"]
    if ports_down:
        parts.append(f"{len(ports_down)} port{'s' if len(ports_down) > 1 else ''} down")
    elif any(e["kind"] == "port_up" for e in rows) and not parts:
        parts.append("ports back up")
    if not parts and any(e["kind"] == "health_ok" for e in rows):
        parts.append("hardware back to normal")
    more = f"\n\n...and {len(rows) - MONITOR_LIMIT} more." if len(rows) > MONITOR_LIMIT else ""
    return [Alert(keys, "Monitoring: " + "; ".join(parts), "What changed:\n\n" + "\n".join(lines)
                  + more + "\n\nThe details and response times are on the Monitoring page.",
                  kind="monitoring")]


def _backups(db, cfg, now, done) -> list[Alert]:
    from app.tools.config_backup.models import BackupState

    limit = now - timedelta(hours=cfg.backup_hours)
    rows = []
    for d, s in db.execute(select(Device, BackupState)
                           .join(BackupState, BackupState.device_id == Device.id)
                           .where(Device.enabled.is_(True), BackupState.enabled.is_(True),
                                  BackupState.last_status == "failed")):
        if s.last_success and s.last_success > limit:
            continue  # failing, but not for long enough yet
        if s.last_success is None and (s.last_attempt is None or
                                       d.created_at and d.created_at > limit):
            continue  # a new device: give it the same time
        key = f"backup:{d.id}:{s.last_success.isoformat() if s.last_success else 'never'}"
        if key not in done:
            rows.append((key, d, s))
    if not rows:
        return []
    lines = [f"  {d.name} ({d.site or '-'}): {s.last_error_type or 'failed'}, "
             f"last good backup {s.last_success:%Y-%m-%d %H:%M} UTC" if s.last_success else
             f"  {d.name} ({d.site or '-'}): {s.last_error_type or 'failed'}, never backed up"
             for _key, d, s in rows]
    n = len(rows)
    return [Alert([k for k, _d, _s in rows], kind="backups", **_text(
                  f"{n} device{'s' if n > 1 else ''} not backed up for over {cfg.backup_hours} h",
                  f"These devices' config backups have been failing for more than "
                  f"{cfg.backup_hours} hours:\n\n" + "\n".join(lines) +
                  "\n\nThe reasons are on the Config backups page."))]


def _changes(db, cfg: Config, since, done, configs_dir=None, syslog_dir=None) -> list[Alert]:
    """Configs that changed (found by a backup) since alerts were switched on. A device's
    first backup isn't a change. Says who changed it when the device's syslog says so."""
    from app.tools.config_backup.models import SUCCESS, BackupRun, BackupState

    runs = [r for r in db.scalars(select(BackupRun).where(
        BackupRun.changed.is_(True), BackupRun.status == SUCCESS,
        BackupRun.finished_at >= since).order_by(BackupRun.finished_at).limit(500))
        if f"change:{r.id}" not in done]
    if not runs:
        return []
    keys, entries = [], []
    for run in runs:
        keys.append(f"change:{run.id}")
        before = db.scalar(select(BackupRun).where(
            BackupRun.device_id == run.device_id, BackupRun.status == SUCCESS,
            BackupRun.id < run.id).order_by(BackupRun.id.desc()).limit(1))
        device = db.get(Device, run.device_id)
        if before is None or device is None:
            continue  # the first backup of a device: nothing to compare with
        entries.append((run, before, device))
    if not entries:
        return [Alert(keys, "", "", kind="changes")]  # recorded, nothing to send
    store = None
    if configs_dir is not None:
        from app.tools.config_backup.storage import GitConfigStore

        store = GitConfigStore(configs_dir)
    blocks = []
    for run, before, device in entries[:CHANGES_LIMIT]:
        state = db.get(BackupState, device.id)
        head = (f"  {device.name} ({device.site or '-'}): changed between "
                f"{before.finished_at:%Y-%m-%d %H:%M} and {run.finished_at:%Y-%m-%d %H:%M} UTC")
        lines = [head]
        lines += [f"    {w}" for w in _who_changed(db, device, before.finished_at,
                                                    run.finished_at, syslog_dir)]
        diff = _run_diff(store, state, run) if store and state else None
        if diff is not None:
            changed = [ln for ln in diff if ln[:1] in "+-" and ln[:3] not in ("+++", "---")
                       and ln[1:].strip()]  # blank lines don't count
            added = [ln for ln in changed if ln.startswith("+")]
            removed = [ln for ln in changed if ln.startswith("-")]
            lines.append(f"    {len(added)} line(s) added, {len(removed)} removed")
            if cfg.changes_diff:
                shown = changed
                for ln in shown[:DIFF_LINES]:
                    text = ln[0] + " (a line that may hold a secret: see the backup)" \
                        if _SECRET.search(ln) else ln.rstrip()
                    lines.append(f"      {text[:200]}")
                if len(shown) > DIFF_LINES:
                    lines.append(f"      ... and {len(shown) - DIFF_LINES} more")
        blocks.append("\n".join(lines))
    n = len(entries)
    names = [d.name for _r, _b, d in entries]
    more = f"\n\n...and {n - CHANGES_LIMIT} more." if n > CHANGES_LIMIT else ""
    subject = (f"Config changed on {n} device{'s' if n > 1 else ''}: "
               f"{', '.join(names[:4])}{' …' if n > 4 else ''}")
    body = ("A config backup found these changes:\n\n" + "\n\n".join(blocks) + more +
            "\n\nSee each change on Config backups (History › compare versions).")
    return [Alert(keys, subject, body, kind="changes")]


def _compliance(db, since, done) -> list[Alert]:
    """Devices that started failing a compliance rule. Config lines are never included."""
    from app.tools.config_backup.models import ComplianceResult, ComplianceRule

    rows = []
    for res, rule, device in db.execute(
            select(ComplianceResult, ComplianceRule, Device)
            .join(ComplianceRule, ComplianceRule.id == ComplianceResult.rule_id)
            .join(Device, Device.id == ComplianceResult.device_id)
            .where(ComplianceResult.passed.is_(False), ComplianceResult.failing_since >= since)):
        key = f"compliance:{device.id}:{rule.id}:{res.failing_since.isoformat()}"
        if key not in done:
            rows.append((key, rule, device))
    if not rows:
        return []
    rows.sort(key=lambda x: (x[1].severity != "critical", x[2].name.lower()))
    lines = [f"  {d.name} ({d.site or '-'}): {r.name}"
             f"{' (critical)' if r.severity == 'critical' else ''}" for _k, r, d in rows[:100]]
    n = len(rows)
    devices = sorted({d.name for _k, _r, d in rows})
    critical = sum(1 for _k, r, _d in rows if r.severity == "critical")
    return [Alert([k for k, _r, _d in rows], kind="compliance", **_text(
        f"{n} new compliance failure{'s' if n > 1 else ''}"
        f"{f' ({critical} critical)' if critical else ''}: {', '.join(devices[:4])}"
        f"{' …' if len(devices) > 4 else ''}",
        "These devices' configs now fail a compliance rule:\n\n" + "\n".join(lines) +
        (f"\n\n...and {n - 100} more." if n > 100 else "") +
        "\n\nThe details are on Config backups › Compliance."))]


def _run_diff(store, state, run) -> list[str] | None:
    """The diff of the version a run saved against the one before it."""
    if not run.commit or not state.config_path:
        return None
    try:
        versions = store.history(state.config_path)
        idx = next(i for i, v in enumerate(versions) if v["commit"] == run.commit)
        if idx + 1 >= len(versions):
            return None
        old, new = versions[idx + 1], versions[idx]
        return store.diff((old["path"], old["commit"]), (new["path"], new["commit"])).splitlines()
    except Exception:  # noqa: BLE001 - history pruned or the repository moved: no diff
        return None


def _who_changed(db, device, start, end, syslog_dir) -> list[str]:
    """What the device logged about config changes between two backups (up to 3 lines)."""
    if syslog_dir is None:
        return []
    from app.tools.syslog.parse import body
    from app.tools.syslog.sources import device_addresses
    from app.tools.syslog.store import Filter, SyslogStore

    sources = [ip for ip, (dev_id, _n) in device_addresses(db).items() if dev_id == device.id]
    if not sources:
        return []
    try:
        rows, _ = SyslogStore(syslog_dir).search(Filter(
            since=start.replace(tzinfo=UTC).timestamp(), until=end.replace(tzinfo=UTC).timestamp(),
            sources=sources), limit=500)
    except Exception:  # noqa: BLE001 - no syslog files yet
        return []
    said = [r for r in rows if _WHO.search(r["text"] or "") or _WHO.search(r["tag"] or "")]
    return [f"Device log {datetime.fromtimestamp(r['ts'], UTC):%Y-%m-%d %H:%M} UTC: "
            f"{body(r['text'], r['tag'])[:200]}" for r in reversed(said[:3])]


def _upgrades(db, since, done) -> list[Alert]:
    from app.tools.firmware_upgrade.models import JobEvent, JobUnit, UpgradeJob

    out = []
    for job in db.scalars(select(UpgradeJob).where(UpgradeJob.status.in_(JOB_ALERTS),
                                                   UpgradeJob.started_at.is_not(None))):
        key = f"job:{job.id}:{job.status}"
        changed = db.scalar(select(func.max(JobEvent.time)).where(JobEvent.job_id == job.id))
        if key in done or (changed or job.started_at) < since:
            continue
        names = [db.get(Device, u.device_id).name for u in db.scalars(
            select(JobUnit).where(JobUnit.job_id == job.id).order_by(JobUnit.position))] or \
            [db.get(Device, job.device_id).name]
        what = JOB_ALERTS[job.status]
        kind = "Upgrade" if job.dry_run is False else "Dry run"
        last = db.scalars(select(JobEvent).where(JobEvent.job_id == job.id)
                          .order_by(JobEvent.id.desc()).limit(3)).all()
        out.append(Alert([key], kind="upgrades", **_text(f"{kind} {what}: {' + '.join(names)} "
                                f"{job.from_version or '?'} → {job.target_version}",
                         f"Upgrade job #{job.id} ({'LIVE' if not job.dry_run else 'dry run'}) "
                         f"on {', '.join(names)} has {what.lower()}.\n\n"
                         f"  Versions: {job.from_version or '?'} → {job.target_version}\n"
                         f"  Change: {job.change_ref or '-'}\n"
                         f"  Started by: {job.started_by or '-'}\n\nLatest events:\n" +
                         "\n".join(f"  {e.time:%H:%M} {e.message}" for e in reversed(last)) +
                         "\n\nThe full record and report are on the job (Firmware › Upgrade jobs).")))
    return out


def _licence(db, done) -> list[Alert]:
    from app.core import licence

    s = licence.status(db)
    if s["mode"] in ("expired", "trial_ended"):
        key = f"licence:ended:{s['ends']}"
        if key not in done:
            return [Alert([key], s["message"], s["warning"], kind="licence")]
    elif s["days_left"] is not None and s["mode"] == "licensed":
        for days in (7, 30):
            key = f"licence:ending:{s['ends']}:{days}"
            if s["days_left"] <= days and key not in done:
                return [Alert([key, *([f"licence:ending:{s['ends']}:30"] if days == 7 else [])],
                              f"The licence ends in {s['days_left']} days",
                              f"{s['message']}.\n\nAsk for a renewal and add it on the Settings "
                              f"page. Without a licence, nobody can add devices or start upgrades "
                              f"(backups keep running).", kind="licence")]
    return []


def _worker(db, now, done) -> list[Alert]:
    from app.tools.firmware_upgrade import jobs as jb

    w = jb.worker_status(db)
    if w["alive"] or w.get("beat_at") is None or now - w["beat_at"] < WORKER_DOWN:
        return []
    key = f"worker:down:{w['beat_at'].isoformat()}"
    if key in done:
        return []
    return [Alert([key], "The upgrade worker has stopped",
                  f"The upgrade worker (netops-worker) hasn't been seen since "
                  f"{w['beat_at']:%Y-%m-%d %H:%M} UTC. Upgrade jobs can't run until it is back.\n\n"
                  "On the server: systemctl status netops-worker; journalctl -u netops-worker -n 50",
                  kind="worker")]


def _text(subject: str, body: str) -> dict:
    return {"subject": subject, "body": body}


def _syslog(db, cfg: Config, syslog_dir) -> list[Alert]:
    """Device messages at the chosen level or worse, received since the last syslog email
    (at most one every ``syslog_minutes``)."""
    from app.tools.syslog.parse import LABELS, body
    from app.tools.syslog.sources import device_addresses
    from app.tools.syslog.store import Filter, SyslogStore

    now = time.time()
    stored = appsettings.stored(db)
    after = float(stored.get(SYSLOG_AFTER) or 0)
    if not cfg.wanted("syslog") or not after:
        appsettings.save(db, {SYSLOG_AFTER: repr(now)}, "system")  # no history when switched on
        return []
    last = db.scalar(select(func.max(AlertSent.sent_at)).where(AlertSent.key.like("syslog:%")))
    if last and utcnow() - last < timedelta(minutes=cfg.syslog_minutes):
        return []  # gather more first
    store = SyslogStore(syslog_dir)
    f = Filter(since=after, until=now, severities=list(range(cfg.syslog_level + 1)))
    total = sum(store.summary(f, buckets=1)["severity"])
    if not total:
        appsettings.save(db, {SYSLOG_AFTER: repr(now)}, "system")
        return []
    rows, _ = store.search(f, limit=SYSLOG_LIMIT)
    names = device_addresses(db)
    devices = sorted({names[r["src"]][1] if r["src"] in names else r["src"] for r in rows})
    lines = []
    for r in reversed(rows):
        who = f"{names[r['src']][1]} ({r['src']})" if r["src"] in names else r["src"]
        when = datetime.fromtimestamp(r["ts"], UTC).strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"  {when} UTC  {who}  {LABELS[r['sev']]}\n    {body(r['text'], r['tag'])[:300]}")
    worst = LABELS[min(r["sev"] for r in rows)]
    more = f"\n\n...and {total - len(rows)} more." if total > len(rows) else ""
    level = LABELS[cfg.syslog_level]
    subject = (f"{total} syslog message{'s' if total > 1 else ''} at {level} or worse "
               f"(worst: {worst}): {', '.join(devices[:4])}{' …' if len(devices) > 4 else ''}")
    text = (f"The devices sent {total} message{'s' if total > 1 else ''} at {level} or worse "
            f"since {datetime.fromtimestamp(after, UTC):%Y-%m-%d %H:%M} UTC:\n\n" + "\n".join(lines)
            + more + "\n\nSee them all on the Syslog page (choose 'Errors and worse').")
    return [Alert([f"syslog:{now:.3f}"], subject, text, kind="syslog",
                  save={SYSLOG_AFTER: repr(now)})]


# --- the scheduler -------------------------------------------------------------------------

class AlertService:
    def __init__(self, settings, cipher, mailer: Mailer = smtp_send):
        self.settings, self.cipher, self.mailer = settings, cipher, mailer
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="alerts", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.wait(60):
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - keep the scheduler alive
                log.exception("Alert check failed")

    def tick(self) -> list[str]:
        """Send what is due; returns the subjects sent."""
        with session_scope() as db:
            cfg = load(db, self.cipher)
            if not (cfg.enabled and cfg.smtp_host and cfg.mail_to):
                return []
            alerts = due(db, cfg, syslog_dir=self.settings.syslog_dir,
                         configs_dir=self.settings.configs_dir,
                         monitor_dir=self.settings.monitor_dir)
        sent, error = [], ""
        for a in alerts:
            to = cfg.to(a.kind)
            if not to:
                continue
            if not a.subject:  # nothing to say (e.g. first backups): just remember them
                with session_scope() as db:
                    for key in a.keys:
                        db.merge(AlertSent(key=key, subject="(nothing to send)"))
                continue
            msg = message(cfg, self.settings, a.subject, a.body, to)
            try:
                self.mailer(cfg, msg)
            except Exception as exc:  # noqa: BLE001 - tried again at the next check
                error = f"{utcnow():%Y-%m-%d %H:%M} UTC: {type(exc).__name__}: {exc}"[:500]
                log.warning("Email alert not sent: %s", error)
                break
            with session_scope() as db:
                for key in a.keys:
                    db.merge(AlertSent(key=key, subject=msg["Subject"][:300]))
                if a.save:
                    appsettings.save(db, a.save, "system")
            sent.append(msg["Subject"])
            log.info("Email alert sent: %s", msg["Subject"])
        if not error and cfg.wanted("reports"):
            error = self._report(cfg, sent)
        with session_scope() as db:
            if error or appsettings.stored(db).get(LAST_ERROR):
                appsettings.save(db, {LAST_ERROR: error}, "system")
        return sent

    def _report(self, cfg: Config, sent: list[str], force: bool = False) -> str:
        """Send the scheduled report when its day and time have come (once per slot)."""
        from app.core import reports

        with session_scope() as db:
            slot = reports.due(cfg.report_day, cfg.report_time,
                               appsettings.stored(db).get(LAST_REPORT, ""))
            if slot is None and not force:
                return ""
            data = reports.build(db, self.settings, cfg.report_days)
        subject = (f"Report: the last {cfg.report_days} days"
                   + ("" if not any(s.get("bad") for s in data["sections"]) else
                      " (" + ", ".join(s["title"] for s in data["sections"] if s.get("bad"))
                      + " need a look)"))
        msg = message(cfg, self.settings, subject, reports.as_text(data), cfg.to("reports"))
        try:
            self.mailer(cfg, msg)
        except Exception as exc:  # noqa: BLE001 - tried again at the next check
            return f"{utcnow():%Y-%m-%d %H:%M} UTC: report: {type(exc).__name__}: {exc}"[:500]
        if slot:
            with session_scope() as db:
                appsettings.save(db, {LAST_REPORT: slot}, "system")
        sent.append(msg["Subject"])
        return ""


# --- API (Settings page) ---------------------------------------------------------------------

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


def _view(db: Session) -> dict:
    cfg = load(db)
    v = appsettings.stored(db)
    recent = db.scalars(select(AlertSent).where(AlertSent.subject != "(nothing to send)")
                        .order_by(AlertSent.sent_at.desc()).limit(10))
    return {"enabled": cfg.enabled, "smtp_host": cfg.smtp_host, "smtp_port": cfg.smtp_port,
            "smtp_security": cfg.smtp_security, "smtp_user": cfg.smtp_user,
            "has_password": bool(v.get(PASSWORD)), "mail_from": cfg.mail_from,
            "mail_to": ", ".join(cfg.mail_to), "backup_hours": cfg.backup_hours,
            "upgrades": cfg.upgrades, "licence": cfg.licence, "worker": cfg.worker,
            "recipients": [{"address": r.address, "kinds": sorted(r.kinds)} for r in cfg.recipients],
            "kinds": KINDS, "syslog_level": cfg.syslog_level, "syslog_minutes": cfg.syslog_minutes,
            "changes_diff": cfg.changes_diff, "report_day": cfg.report_day,
            "report_time": cfg.report_time, "report_days": cfg.report_days,
            "last_error": v.get(LAST_ERROR, ""),
            "recent": [{"sent_at": r.sent_at, "subject": r.subject} for r in recent]}


class RecipientIn(BaseModel):
    address: str = Field(max_length=200)
    kinds: list[str] = Field(default_factory=list, max_length=len(KINDS))


class AlertsIn(BaseModel):
    enabled: bool = False
    smtp_host: str = Field(default="", max_length=200, pattern=r"^[A-Za-z0-9.:_-]*$")
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_security: str = "starttls"
    smtp_user: str = Field(default="", max_length=200)
    smtp_password: str | None = Field(default=None, max_length=500)  # None = keep
    mail_from: str = Field(default="", max_length=200)
    mail_to: str = Field(default="", max_length=2000)
    backup_hours: int = Field(default=24, ge=0, le=720)  # 0 = no backup alerts
    upgrades: bool = True
    licence: bool = True
    worker: bool = True
    # Each recipient's choice (the GUI); without it, everyone in mail_to gets what is on above
    recipients: list[RecipientIn] | None = Field(default=None, max_length=20)
    syslog_level: int = Field(default=2, ge=0, le=3)  # 0 emergency .. 3 error, and worse
    syslog_minutes: int = Field(default=5, ge=1, le=60)
    changes_diff: bool = False
    report_day: str = Field(default="", pattern=r"^(mon|tue|wed|thu|fri|sat|sun)?$")
    report_time: str = Field(default="07:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    report_days: int = Field(default=7, ge=1, le=90)


def _addresses(text: str) -> list[str]:
    return [a.strip() for a in re.split(r"[,;\s]+", text) if a.strip()]


@router.get("")
def get_alerts(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return _view(db)


@router.put("")
def save_alerts(body: AlertsIn, request: Request, db: Session = Depends(get_db),
                user: User = Depends(require_admin)):
    if body.smtp_security not in SECURITY:
        raise HTTPException(422, "Security must be STARTTLS, TLS or none")
    if body.recipients is not None:
        recipients = [RecipientIn(address=r.address.strip(), kinds=sorted(set(r.kinds)))
                      for r in body.recipients if r.address.strip()]
        for r in recipients:
            if bad := set(r.kinds) - set(KINDS):
                raise HTTPException(422, f"Unknown alert kind: {', '.join(sorted(bad))}")
    else:
        kinds = [k for k, on in (("backups", body.backup_hours > 0), ("upgrades", body.upgrades),
                                 ("licence", body.licence), ("worker", body.worker)) if on]
        recipients = [RecipientIn(address=a, kinds=kinds) for a in _addresses(body.mail_to)]
    to = [r.address for r in recipients]
    if len(set(a.lower() for a in to)) != len(to):
        raise HTTPException(422, "A recipient is listed twice")
    for a in [*to, *([body.mail_from] if body.mail_from else [])]:
        if not _EMAIL.match(a):
            raise HTTPException(422, f"'{a}' isn't an email address")
    if len(to) > 20:
        raise HTTPException(422, "At most 20 recipients")
    if body.enabled and not (body.smtp_host and body.mail_from and to):
        raise HTTPException(422, "To switch alerts on, fill in the mail server, the From "
                                 "address and at least one recipient")
    before = load(db)
    values = {PREFIX + k: str(getattr(body, k)) for k in
              ("smtp_host", "smtp_port", "smtp_security", "smtp_user", "mail_from",
               "backup_hours", "syslog_level", "syslog_minutes", "report_day", "report_time",
               "report_days")}
    values |= {PREFIX + k: "true" if getattr(body, k) else "false"
               for k in ("enabled", "upgrades", "licence", "worker", "changes_diff")}
    values[PREFIX + "mail_to"] = ",".join(to)
    values[PREFIX + "recipients"] = json.dumps([r.model_dump() for r in recipients])
    if body.smtp_password is not None:
        values[PASSWORD] = (request.app.state.cipher.encrypt(body.smtp_password)
                            if body.smtp_password else "")
    if body.enabled and not before.enabled:
        values[ENABLED_AT] = utcnow().isoformat()  # from now on: no history
    appsettings.save(db, values, user.username)
    audit(db, user.username, "settings.alerts",
          f"{'on' if body.enabled else 'off'}, server {body.smtp_host or '-'}, "
          "to " + ("; ".join(f"{r.address} ({', '.join(r.kinds) or 'nothing'})"
                              for r in recipients) or "-"))
    return _view(db)


@router.post("/test")
def test_alerts(request: Request, db: Session = Depends(get_db),
                user: User = Depends(require_admin)):
    """Send a test email with the saved settings."""
    cfg = load(db, request.app.state.cipher)
    if not (cfg.smtp_host and cfg.mail_from and cfg.mail_to):
        raise HTTPException(422, "Save the mail server, the From address and a recipient first")
    settings = request.app.state.settings
    msg = message(cfg, settings, "Test email",
                  f"This is a test from the Settings page, sent by {user.username}. "
                  "Alerts reach you this way.")
    try:
        request.app.state.alert_service.mailer(cfg, msg)
    except Exception as exc:  # noqa: BLE001
        audit(db, user.username, "settings.alerts_test", f"failed: {exc}"[:500])
        return {"ok": False, "message": f"{type(exc).__name__}: {exc}"}
    audit(db, user.username, "settings.alerts_test", f"sent to {', '.join(cfg.mail_to)}")
    return {"ok": True, "message": f"Sent to {', '.join(cfg.mail_to)}"}


@router.post("/report-now")
def report_now(request: Request, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    """Send the report to its recipients now (outside the schedule)."""
    cfg = load(db, request.app.state.cipher)
    if not (cfg.smtp_host and cfg.mail_from and cfg.to("reports")):
        raise HTTPException(422, "Save the mail server, the From address and at least one "
                                 "recipient who gets Report first")
    sent: list[str] = []
    error = request.app.state.alert_service._report(cfg, sent, force=True)
    audit(db, user.username, "settings.report_sent",
          f"to {', '.join(cfg.to('reports'))}" + (f": failed: {error}" if error else ""))
    if error:
        return {"ok": False, "message": error}
    return {"ok": True, "message": f"Sent to {', '.join(cfg.to('reports'))}"}
