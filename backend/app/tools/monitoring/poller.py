"""The monitoring poller: every minute (``monitor_poll_seconds``) it pings each monitored
device and reads its SNMP system values (name, description, uptime), then records what it
found in its own files (store.py).

    python -m app.tools.monitoring        (systemd: netops-monitor.service)

A device is:
* **up** when it answers;
* **warning** when it answers but something needs a look: SNMP fails (wrong community or
  user, an access list), or it doesn't answer ping but SNMP works, or it missed a poll;
* **down** when neither ping nor SNMP has answered for ``monitor_down_after`` polls in a row.

It also notes restarts (the SNMP uptime went back to near zero) and when SNMP stops or
starts working. Each change is an **event**; the web app's alerts email them. A device in
a calendar window (change, maintenance, outage) or with an upgrade under way is marked
**maintenance**: its events are kept but not emailed.

Read-only towards the devices: ICMP echo, and SNMP GET (never SET). Its own service, so it
keeps polling while the web app restarts; it runs as the netops account with no extra rights.
"""

import asyncio
import json
import logging
import os
import signal
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.tools.monitoring import ping as pinging
from app.tools.monitoring.snmp import (SYS_DESCR, SYS_NAME, SYS_OBJECT_ID, SYS_UPTIME, SYSTEM,
                                       SnmpClient, SnmpError, SnmpTarget)
from app.tools.monitoring.store import MonitorStore

log = logging.getLogger("netops.monitor")

UP, WARNING, DOWN, UNKNOWN = "up", "warning", "down", "unknown"
UPTIME_WRAP = 2**32 / 100  # sysUpTime counts hundredths of a second in 32 bits (497 days)
MAINTENANCE_KINDS = ("change", "maintenance", "outage")


@dataclass
class Job:
    """One device to poll."""
    device_id: int
    name: str
    address: str
    site: str
    ping: bool
    snmp: SnmpTarget | None
    snmp_note: str = ""  # why SNMP isn't used, when it isn't
    maintenance: bool = False


def target_for(profile, address: str, cipher) -> SnmpTarget:
    """An SNMP profile and an address as an SnmpTarget (secrets decrypted)."""
    dec = lambda v: cipher.decrypt(v) if v else ""  # noqa: E731
    return SnmpTarget(address=address, port=profile.port, version=profile.version,
                      community=dec(profile.community_enc), username=profile.username,
                      level=profile.level, auth_protocol=profile.auth_protocol,
                      auth_key=dec(profile.auth_key_enc), priv_protocol=profile.priv_protocol,
                      priv_key=dec(profile.priv_key_enc), timeout=profile.timeout,
                      retries=profile.retries)


def maintenance_now(db: Session, now: datetime | None = None) -> set[int]:
    """Devices in a calendar window (change, maintenance or outage, by device or by site;
    one with neither is everywhere) or in an upgrade job that is under way."""
    from app.core.models import Device
    from app.tools.calendar.api import _Sites
    from app.tools.calendar.models import CalendarEvent
    from app.tools.firmware_upgrade.models import CLOSED_STATES, JobUnit, UpgradeJob

    now = now or datetime.now(UTC).replace(tzinfo=None)
    devices = list(db.scalars(select(Device)))
    sites = _Sites(db)
    site_of = {d.id: sites.name(d.site).lower() for d in devices}
    out: set[int] = set()
    for e in db.scalars(select(CalendarEvent).where(CalendarEvent.start <= now,
                                                    CalendarEvent.end > now,
                                                    CalendarEvent.kind.in_(MAINTENANCE_KINDS))):
        ids = set(json.loads(e.devices or "[]"))
        names = {s.lower() for s in json.loads(e.sites or "[]")}
        if not ids and not names:
            return {d.id for d in devices}
        out |= ids
        out |= {i for i, s in site_of.items() if s and s in names}
    for job in db.scalars(select(UpgradeJob).where(UpgradeJob.status.not_in(CLOSED_STATES))):
        under_way = job.started_at is not None or (
            job.planned_start and job.planned_end and job.planned_start <= now < job.planned_end)
        if under_way:
            units = list(db.scalars(select(JobUnit.device_id).where(JobUnit.job_id == job.id)))
            out |= set(units) or {job.device_id}
    return out


def load_jobs(db: Session, cipher) -> list[Job]:
    """The devices to poll, with their SNMP profile (their own, else the default)."""
    from app.core.models import Device
    from app.tools.monitoring.models import MonitorTarget, SnmpProfile

    profiles = {p.id: p for p in db.scalars(select(SnmpProfile))}
    default = next((p for p in profiles.values() if p.is_default), None)
    choices = {t.device_id: t for t in db.scalars(select(MonitorTarget))}
    in_maintenance = maintenance_now(db)
    jobs = []
    for d in db.scalars(select(Device).order_by(Device.name)):
        t = choices.get(d.id)
        if not d.enabled or (t is not None and not t.monitored):
            continue
        use_ping = t.ping if t is not None else True
        use_snmp = t.snmp if t is not None else True
        snmp, note = None, ""
        if use_snmp:
            profile = profiles.get(t.profile_id) if t is not None and t.profile_id else default
            if profile is None:
                note = "No SNMP profile: add one (SNMP profiles) or choose one for this device"
            else:
                try:
                    snmp = target_for(profile, d.address.strip(), cipher)
                except Exception:  # noqa: BLE001 - the credential key was replaced
                    note = f"Can't read the secrets of SNMP profile '{profile.name}': enter them again"
        else:
            note = "SNMP is off for this device"
        if not use_ping and snmp is None:
            note = note or "Ping and SNMP are both off"
        jobs.append(Job(d.id, d.name, d.address.strip(), d.site, use_ping, snmp, note,
                        d.id in in_maintenance))
    return jobs


class Poller:
    def __init__(self, settings: Settings, store: MonitorStore, cipher=None, snmp=None,
                 pinger=pinging.ping, clock=time.time):
        self.settings = settings
        self.store = store
        self.cipher = cipher
        self.snmp = snmp or SnmpClient()
        self.pinger = pinger
        self.clock = clock
        self.jobs: list[Job] = []
        self.prev: dict[int, dict] = store.states()  # carries on after a restart
        self.first_fail: dict[int, float] = {}
        self.ping_allowed = True
        self.licensed = True
        self.started = clock()
        self.last_round = 0.0
        self.round_seconds = 0.0
        self.last_error = ""
        self._stop = asyncio.Event()

    # --- one device ------------------------------------------------------------------

    async def poll(self, job: Job, now: float) -> tuple[dict, list[dict], tuple]:
        prev = self.prev.get(job.device_id) or {}
        result, ping_note = None, ""
        if job.ping and self.ping_allowed:
            try:
                result = await self.pinger(job.address)
            except pinging.PingNotAllowed as exc:
                self.ping_allowed = False
                ping_note = str(exc)
            except OSError:
                result = pinging.PingResult(1, 0, None)  # the name doesn't resolve
                ping_note = f"Can't look up {job.address}"
        values, snmp_ok, snmp_error = {}, None, ""
        if job.snmp is not None:
            try:
                values = await self.snmp.get(job.snmp, SYSTEM)
                snmp_ok = True
            except SnmpError as exc:
                snmp_ok, snmp_error = False, str(exc)
        pinged = result is not None
        answered = bool((pinged and result.ok) or snmp_ok)
        polled = pinged or snmp_ok is not None
        fails = 0 if answered or not polled else int(prev.get("fails") or 0) + 1
        down_after = max(self.settings.monitor_down_after, 1)

        if not polled:
            status = UNKNOWN
            reason = job.snmp_note or ping_note or "Nothing to poll it with"
            if ping_note and job.snmp_note:
                reason = f"{ping_note}, and {job.snmp_note[0].lower()}{job.snmp_note[1:]}"
        elif answered:
            status, reason = UP, ""
            if snmp_ok is False:
                status, reason = WARNING, f"SNMP: {snmp_error}"
            elif pinged and not result.ok:
                status, reason = WARNING, ("No reply to ping, but SNMP answers. If it never "
                                           "answers ping, switch ping off for it")
            elif job.snmp is None and job.snmp_note:
                reason = job.snmp_note
            elif pinged and result.loss > 0:
                reason = f"{result.sent - result.received} of {result.sent} pings lost"
        elif fails >= down_after or prev.get("status") == DOWN:
            status = DOWN
            reason = "No answer to ping or SNMP" if pinged and job.snmp else \
                "No answer to ping" if pinged else f"No answer to SNMP ({snmp_error})"
        else:
            status = WARNING
            reason = f"No answer ({fails} of {down_after} polls before it counts as down)"
        if not answered and polled:
            self.first_fail.setdefault(job.device_id, now)
        else:
            self.first_fail.pop(job.device_id, None)

        events = []

        def event(kind: str, detail: str = "", at: float = now):
            events.append({"ts": at, "device_id": job.device_id, "kind": kind, "detail": detail,
                           "maintenance": job.maintenance})

        before = prev.get("status")
        if status == DOWN and before != DOWN:
            since = self.first_fail.get(job.device_id, now)
            event("down", reason + f" since {datetime.fromtimestamp(since, UTC):%H:%M} UTC", since)
        elif before == DOWN and status != DOWN:
            gone = now - float(prev.get("since") or now)
            event("up", f"Answering again after {_duration(gone)}")
        if answered and before not in (None, DOWN, UNKNOWN):
            if prev.get("snmp_ok") == 1 and snmp_ok is False:
                event("snmp_failed", snmp_error)
            elif prev.get("snmp_ok") == 0 and snmp_ok:
                event("snmp_ok", "SNMP answers again")

        uptime = values.get(SYS_UPTIME)
        uptime = uptime / 100 if isinstance(uptime, int) else None
        last_restart = prev.get("last_restart")
        if uptime is not None:
            started_at = now - uptime
            old_uptime, old_poll = prev.get("uptime"), prev.get("last_poll")
            if old_uptime is not None and old_poll and uptime + 1 < old_uptime + (now - old_poll) - 5:
                wrapped = old_uptime + (now - old_poll) >= UPTIME_WRAP - 5
                if not wrapped:
                    event("restarted", f"Started {datetime.fromtimestamp(started_at, UTC):%Y-%m-%d %H:%M} "
                                       f"UTC ({_duration(uptime)} ago)", started_at)
                    last_restart = started_at
            elif last_restart is None or old_uptime is None:
                last_restart = started_at

        state = {
            "device_id": job.device_id, "status": status,
            "since": now if status != before else float(prev.get("since") or now),
            "last_poll": now, "rtt_ms": result.rtt_ms if pinged else None,
            "loss": round(result.loss, 3) if pinged else None,
            "ping_ok": int(result.ok) if pinged else None,
            "snmp_ok": None if snmp_ok is None else int(snmp_ok), "reason": reason[:300],
            "fails": fails,
            "sys_name": str(values.get(SYS_NAME) or prev.get("sys_name") or "")[:200],
            "sys_descr": str(values.get(SYS_DESCR) or prev.get("sys_descr") or "")[:500],
            "sys_object_id": str(values.get(SYS_OBJECT_ID) or prev.get("sys_object_id") or "")[:200],
            "uptime": uptime if uptime is not None else None,
            "last_restart": last_restart, "maintenance": int(job.maintenance),
        }
        sample = (now, job.device_id, result.rtt_ms if pinged else None, answered)
        return state, events, sample

    # --- a round of every device ---------------------------------------------------------------

    async def run_round(self) -> dict:
        """Poll every device once; returns counts per status."""
        start = self.clock()
        jobs = list(self.jobs)
        limit = asyncio.Semaphore(max(self.settings.monitor_workers, 1))

        async def one(job):
            async with limit:
                try:
                    return await self.poll(job, self.clock())
                except Exception:  # noqa: BLE001 - one bad device never stops the round
                    log.exception("Polling %s failed", job.name)
                    return None

        results = [r for r in await asyncio.gather(*(one(j) for j in jobs)) if r]
        states = [r[0] for r in results]
        events = [e for r in results for e in r[1]]
        samples = [r[2] for r in results if r[0]["status"] != UNKNOWN]
        await asyncio.get_running_loop().run_in_executor(
            None, self.store.save, states, events, samples)
        for s in states:
            self.prev[s["device_id"]] = s
        for e in events:
            log.info("%s: %s %s", next((j.name for j in jobs if j.device_id == e["device_id"]), "?"),
                     e["kind"], e["detail"])
        self.last_round = start
        self.round_seconds = round(self.clock() - start, 2)
        counts: dict[str, int] = {}
        for s in states:
            counts[s["status"]] = counts.get(s["status"], 0) + 1
        return counts

    # --- housekeeping -------------------------------------------------------------------------

    def housekeeping(self) -> None:
        """Settings from the Settings page, the licence, the devices and their profiles."""
        from app.core import appsettings, licence
        from app.core.db import session_scope

        appsettings.apply(self.settings)
        self.licensed = licence.has_module("monitoring")
        with session_scope() as db:
            self.jobs = load_jobs(db, self.cipher) if self.licensed else []
        keep = {j.device_id for j in self.jobs}
        self.store.forget(keep)
        self.prev = {k: v for k, v in self.prev.items() if k in keep}

    def prune(self) -> None:
        gone = self.store.prune(self.settings.monitor_keep_days)
        if gone:
            log.info("Deleted monitoring days %s", ", ".join(d.isoformat() for d in gone))

    def status(self) -> dict:
        counts: dict[str, int] = {}
        for s in self.prev.values():
            counts[s["status"]] = counts.get(s["status"], 0) + 1
        return {"pid": os.getpid(), "started": self.started, "beat": self.clock(),
                "last_round": self.last_round or None, "round_seconds": self.round_seconds,
                "interval": self.settings.monitor_poll_seconds, "devices": len(self.jobs),
                "counts": counts, "ping_allowed": self.ping_allowed, "licensed": self.licensed,
                "last_error": self.last_error}

    # --- the service --------------------------------------------------------------------------

    async def serve(self) -> None:
        loop = asyncio.get_running_loop()
        log.info("Monitoring poller started, storing in %s", self.store.dir)
        last_house = last_prune = float("-inf")
        next_round = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            try:
                if now - last_house >= 60:
                    await loop.run_in_executor(None, self.housekeeping)
                    last_house = now
                if now - last_prune >= 3600:
                    await loop.run_in_executor(None, self.prune)
                    last_prune = now
                if now >= next_round:
                    next_round = now + max(self.settings.monitor_poll_seconds, 10)
                    await self.run_round()
                self.last_error = ""
            except Exception as exc:  # noqa: BLE001 - keep polling
                log.exception("Monitoring round failed")
                self.last_error = f"{type(exc).__name__}: {exc}"[:300]
            try:
                await loop.run_in_executor(None, self.store.write_status, self.status())
            except OSError:
                log.exception("Could not write the monitoring status")
            try:
                await asyncio.wait_for(self._stop.wait(), max(1.0, min(10.0, next_round - time.monotonic())))
            except TimeoutError:
                pass
        self.store.write_status({**self.status(), "beat": 0})
        self.store.close()
        log.info("Monitoring poller stopped")

    def stop(self, *_args) -> None:
        self._stop.set()


def _duration(seconds: float) -> str:
    seconds = max(int(seconds), 0)
    if seconds < 90:
        return f"{seconds} s"
    if seconds < 5400:
        return f"{round(seconds / 60)} min"
    if seconds < 172800:
        return f"{seconds / 3600:.1f} h"
    return f"{seconds / 86400:.1f} days"


def main() -> None:
    from app.core.config import get_settings
    from app.core.crypto import CredentialCipher
    from app.core.db import init_engine

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    init_engine(settings.database_url)
    poller = Poller(settings, MonitorStore(settings.monitor_dir),
                    CredentialCipher(settings.credential_key_file))

    async def run():
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, poller.stop)
        await poller.serve()

    asyncio.run(run())

