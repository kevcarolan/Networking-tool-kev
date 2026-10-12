"""Email alerts, sent through the customer's own mail server (SMTP).

An admin sets the mail server, the recipients and which alerts to send on the Settings
page (stored in app_settings; the SMTP password encrypted with the credential key). Once a
minute the web app's scheduler looks at the state of things and sends what is new:

* **Backups:** devices whose backup has been failing for longer than N hours (24 by
  default), in one email per check, once per failure.
* **Upgrades:** an upgrade job that has completed, failed, rolled back or needs attention.
* **Licence:** 30 and 7 days before it ends, and when it has ended (or the trial has).
* **Upgrade worker:** stopped for more than 10 minutes.

Every alert sent is recorded in the ``alerts_sent`` table, so it is sent once only; one
that fails to send is tried again at the next check. Only events after alerts were switched
on are sent, so switching them on doesn't send the history.
"""

import logging
import re
import smtplib
import ssl
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
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
        "mail_to", "backup_hours", "upgrades", "licence", "worker")
PASSWORD = PREFIX + "smtp_password_enc"
ENABLED_AT = PREFIX + "enabled_at"
LAST_ERROR = PREFIX + "last_error"
SECURITY = ("starttls", "tls", "none")
WORKER_DOWN = timedelta(minutes=10)
JOB_ALERTS = {"completed": "completed", "completed_overrides": "completed with overrides",
              "failed": "FAILED", "rolled_back": "rolled back",
              "needs_attention": "NEEDS ATTENTION"}
_EMAIL = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")


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


def load(db: Session, cipher=None) -> Config:
    v = appsettings.stored(db)
    get = lambda k, d="": v.get(PREFIX + k, d)  # noqa: E731
    password = ""
    if cipher is not None and v.get(PASSWORD):
        try:
            password = cipher.decrypt(v[PASSWORD])
        except Exception:  # noqa: BLE001 - the credential key was replaced
            password = ""
    return Config(
        enabled=get("enabled") == "true", smtp_host=get("smtp_host"),
        smtp_port=int(get("smtp_port", "587") or 587),
        smtp_security=get("smtp_security", "starttls") or "starttls",
        smtp_user=get("smtp_user"), smtp_password=password, mail_from=get("mail_from"),
        mail_to=tuple(a for a in get("mail_to").split(",") if a),
        backup_hours=int(get("backup_hours", "24") or 24),
        upgrades=get("upgrades", "true") == "true", licence=get("licence", "true") == "true",
        worker=get("worker", "true") == "true",
        enabled_at=datetime.fromisoformat(v[ENABLED_AT]) if v.get(ENABLED_AT) else None)


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


def message(cfg: Config, settings, subject: str, body: str) -> EmailMessage:
    who = settings.product_name + (f" · {settings.site_name}" if settings.site_name else "")
    msg = EmailMessage()
    msg["Subject"] = f"[{who}] {subject}"
    msg["From"] = cfg.mail_from
    msg["To"] = ", ".join(cfg.mail_to)
    msg.set_content(body.rstrip() + f"\n\n-- \nSent by {who}. Alerts are set on the Settings "
                                    "page (admins).\n")
    return msg


# --- what to send ------------------------------------------------------------------------

@dataclass
class Alert:
    keys: list[str]  # recorded once sent
    subject: str
    body: str


def _sent(db: Session) -> set[str]:
    return set(db.scalars(select(AlertSent.key)))


def due(db: Session, cfg: Config, now: datetime | None = None) -> list[Alert]:
    now = now or utcnow()
    since = cfg.enabled_at or now
    done = _sent(db)
    out = []
    if cfg.backup_hours:
        out += _backups(db, cfg, now, done)
    if cfg.upgrades:
        out += _upgrades(db, since, done)
    if cfg.licence:
        out += _licence(db, done)
    if cfg.worker:
        out += _worker(db, now, done)
    return out


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
    return [Alert([k for k, _d, _s in rows],
                  f"{n} device{'s' if n > 1 else ''} not backed up for over {cfg.backup_hours} h",
                  f"These devices' config backups have been failing for more than "
                  f"{cfg.backup_hours} hours:\n\n" + "\n".join(lines) +
                  "\n\nThe reasons are on the Config backups page.")]


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
        out.append(Alert([key], f"{kind} {what}: {' + '.join(names)} "
                                f"{job.from_version or '?'} → {job.target_version}",
                         f"Upgrade job #{job.id} ({'LIVE' if not job.dry_run else 'dry run'}) "
                         f"on {', '.join(names)} has {what.lower()}.\n\n"
                         f"  Versions: {job.from_version or '?'} → {job.target_version}\n"
                         f"  Change: {job.change_ref or '-'}\n"
                         f"  Started by: {job.started_by or '-'}\n\nLatest events:\n" +
                         "\n".join(f"  {e.time:%H:%M} {e.message}" for e in reversed(last)) +
                         "\n\nThe full record and report are on the job (Firmware › Upgrade jobs)."))
    return out


def _licence(db, done) -> list[Alert]:
    from app.core import licence

    s = licence.status(db)
    if s["mode"] in ("expired", "trial_ended"):
        key = f"licence:ended:{s['ends']}"
        if key not in done:
            return [Alert([key], s["message"], s["warning"])]
    elif s["days_left"] is not None and s["mode"] == "licensed":
        for days in (7, 30):
            key = f"licence:ending:{s['ends']}:{days}"
            if s["days_left"] <= days and key not in done:
                return [Alert([key, *([f"licence:ending:{s['ends']}:30"] if days == 7 else [])],
                              f"The licence ends in {s['days_left']} days",
                              f"{s['message']}.\n\nAsk for a renewal and add it on the Settings "
                              f"page. Without a licence, nobody can add devices or start upgrades "
                              f"(backups keep running).")]
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
                  "On the server: systemctl status netops-worker; journalctl -u netops-worker -n 50")]


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
            alerts = due(db, cfg)
        sent, error = [], ""
        for a in alerts:
            msg = message(cfg, self.settings, a.subject, a.body)
            try:
                self.mailer(cfg, msg)
            except Exception as exc:  # noqa: BLE001 - tried again at the next check
                error = f"{utcnow():%Y-%m-%d %H:%M} UTC: {type(exc).__name__}: {exc}"[:500]
                log.warning("Email alert not sent: %s", error)
                break
            with session_scope() as db:
                for key in a.keys:
                    db.merge(AlertSent(key=key, subject=msg["Subject"][:300]))
            sent.append(msg["Subject"])
            log.info("Email alert sent: %s", msg["Subject"])
        with session_scope() as db:
            if error or appsettings.stored(db).get(LAST_ERROR):
                appsettings.save(db, {LAST_ERROR: error}, "system")
        return sent


# --- API (Settings page) ---------------------------------------------------------------------

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


def _view(db: Session) -> dict:
    cfg = load(db)
    v = appsettings.stored(db)
    recent = db.scalars(select(AlertSent).order_by(AlertSent.sent_at.desc()).limit(10))
    return {"enabled": cfg.enabled, "smtp_host": cfg.smtp_host, "smtp_port": cfg.smtp_port,
            "smtp_security": cfg.smtp_security, "smtp_user": cfg.smtp_user,
            "has_password": bool(v.get(PASSWORD)), "mail_from": cfg.mail_from,
            "mail_to": ", ".join(cfg.mail_to), "backup_hours": cfg.backup_hours,
            "upgrades": cfg.upgrades, "licence": cfg.licence, "worker": cfg.worker,
            "last_error": v.get(LAST_ERROR, ""),
            "recent": [{"sent_at": r.sent_at, "subject": r.subject} for r in recent]}


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
    to = _addresses(body.mail_to)
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
               "backup_hours")}
    values |= {PREFIX + k: "true" if getattr(body, k) else "false"
               for k in ("enabled", "upgrades", "licence", "worker")}
    values[PREFIX + "mail_to"] = ",".join(to)
    if body.smtp_password is not None:
        values[PASSWORD] = (request.app.state.cipher.encrypt(body.smtp_password)
                            if body.smtp_password else "")
    if body.enabled and not before.enabled:
        values[ENABLED_AT] = utcnow().isoformat()  # from now on: no history
    appsettings.save(db, values, user.username)
    audit(db, user.username, "settings.alerts",
          f"{'on' if body.enabled else 'off'}, server {body.smtp_host or '-'}, "
          f"to {', '.join(to) or '-'}")
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
