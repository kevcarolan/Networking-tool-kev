"""Reads the MAC and ARP tables of every device: weekly at night, or when an admin asks.

It logs in with each device's backup account (read-only "show" commands only) and
keeps the result with store.save_read. Upgrade jobs read the same tables for their own
device during the pre-checks and post-checks (firmware_upgrade/jobs.py).
"""

import logging
import re
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from sqlalchemy import select

from app.core.config import Settings
from app.core.crypto import CredentialCipher
from app.core.db import session_scope, utcnow
from app.core.models import Device
from app.core.ssh import Target, classify_error, run_commands, target_for
from app.tools.circuits import live, store
from app.tools.circuits.models import CircuitScan

log = logging.getLogger(__name__)

Collector = Callable[[Target, tuple[str, ...]], list[str]]
_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
CATCH_UP = timedelta(hours=6)  # a scan missed (server off) runs only if this late at most


def parse_schedule(text: str) -> tuple[int | None, int, int] | None:
    """'sun 02:00' -> (6, 2, 0); 'daily 02:00' -> (None, 2, 0); '' -> None (off)."""
    t = (text or "").strip().lower()
    if not t:
        return None
    m = re.fullmatch(r"(mon|tue|wed|thu|fri|sat|sun|daily)\w*\s+(\d{1,2}):(\d{2})", t)
    if not m or int(m.group(2)) > 23 or int(m.group(3)) > 59:
        raise ValueError(f"Circuit scan schedule '{text}' should look like 'sun 02:00' "
                         "or 'daily 02:00'")
    day = None if m.group(1) == "daily" else _DAYS.index(m.group(1))
    return day, int(m.group(2)), int(m.group(3))


def last_slot(schedule: tuple[int | None, int, int], now: datetime) -> datetime:
    """The most recent scheduled time at or before now (server local time)."""
    day, hour, minute = schedule
    slot = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if slot > now:
        slot -= timedelta(days=1)
    if day is not None:
        slot -= timedelta(days=(slot.weekday() - day) % 7)
    return slot


class CircuitScanService:
    def __init__(self, settings: Settings, cipher: CredentialCipher,
                 collector: Collector = run_commands, clock: Callable[[], datetime] = datetime.now):
        self.settings = settings
        self.cipher = cipher
        self.collector = collector
        self.clock = clock  # server local time, for the schedule
        self._schedule_text = settings.circuit_scan_schedule
        self.schedule = parse_schedule(self._schedule_text)
        self._busy = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # --- scheduling ---------------------------------------------------------

    def start(self) -> None:
        # Always runs: the schedule can be switched on later on the Settings page.
        self._thread = threading.Thread(target=self._loop, name="circuit-scan", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - keep the scheduler alive
                log.exception("Circuit scan tick failed")
            self._stop.wait(self.settings.scheduler_tick_seconds)

    def due_trigger(self) -> str | None:
        """'schedule:<slot>' when a scheduled scan is due, else None."""
        if self.settings.circuit_scan_schedule != self._schedule_text:  # changed on Settings
            self._schedule_text = self.settings.circuit_scan_schedule
            try:
                self.schedule = parse_schedule(self._schedule_text)
            except ValueError:
                log.warning("Ignoring circuit scan schedule %r", self._schedule_text)
        if self.schedule is None:
            return None
        now = self.clock()
        slot = last_slot(self.schedule, now)
        if now - slot > CATCH_UP:
            return None
        trigger = f"schedule:{slot:%Y-%m-%d %H:%M}"
        with session_scope() as db:
            done = db.scalar(select(CircuitScan.id).where(CircuitScan.trigger == trigger))
        return None if done else trigger

    def tick(self) -> bool:
        trigger = self.due_trigger()
        return bool(trigger) and self.scan(trigger) is not None

    @property
    def running(self) -> bool:
        return self._busy.locked()

    def scan_in_background(self, trigger: str, device_ids: list[int] | None = None) -> bool:
        """Start a scan in a thread. False if one is already running."""
        if self.running:
            return False
        threading.Thread(target=self.scan, args=(trigger, device_ids), name="circuit-scan-now",
                         daemon=True).start()
        return True

    # --- one scan -----------------------------------------------------------

    def scan(self, trigger: str, device_ids: list[int] | None = None) -> int | None:
        """Read every enabled device (or the given ones). Returns the scan id, or None if
        another scan is running."""
        if not self._busy.acquire(blocking=False):
            return None
        try:
            with session_scope() as db:
                q = select(Device.id).where(Device.enabled.is_(True))
                if device_ids:
                    q = select(Device.id).where(Device.id.in_(device_ids))
                ids = [i for i in db.scalars(q)
                       if live.commands_for(db.get(Device, i).platform)]
                run = CircuitScan(trigger=trigger[:200])
                db.add(run)
                db.flush()
                scan_id = run.id
            log.info("Circuit scan %s (%s): %d device(s)", scan_id, trigger, len(ids))
            with ThreadPoolExecutor(max_workers=max(1, self.settings.circuit_scan_workers),
                                    thread_name_prefix="circuit-scan") as pool:
                results = list(pool.map(self.read_device, ids))
            with session_scope() as db:
                run = db.get(CircuitScan, scan_id)
                run.finished_at = utcnow()
                run.devices_ok = sum(1 for _, err in results if not err)
                run.devices_failed = sum(1 for _, err in results if err)
                run.errors = "\n".join(f"{name}: {err}" for name, err in results if err)[:20000]
            return scan_id
        finally:
            self._busy.release()

    def read_device(self, device_id: int) -> tuple[str, str]:
        """Read one device and keep the result. Returns (device name, error or '')."""
        with session_scope() as db:
            device = db.get(Device, device_id)
            name, platform = device.name, device.platform
            commands = live.commands_for(platform)
            try:
                target = target_for(device, self.cipher, self.settings.ssh_timeout,
                                    self.settings.command_timeout)
            except Exception as exc:  # noqa: BLE001
                error = classify_error(exc)[1]
                store.save_failure(db, device_id, error)
                return name, error
        try:
            outputs = self.collector(target, tuple(commands.values()))
            read = live.read_device(dict(zip(commands.keys(), outputs)), platform)
        except Exception as exc:  # noqa: BLE001
            error = classify_error(exc)[1]
            with session_scope() as db:
                store.save_failure(db, device_id, error)
            return name, error
        with session_scope() as db:
            if read.macs is None and read.arps is None:
                error = "the device didn't accept the MAC or ARP table commands"
                store.save_failure(db, device_id, error)
                return name, error
            store.save_read(db, device_id, read)
        return name, ""
