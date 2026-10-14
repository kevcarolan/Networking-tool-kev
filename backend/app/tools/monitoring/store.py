"""Where the poller keeps what it finds, in its own folder (not the main database):

    <data>/monitoring/state.db        each device's state now, the events (down, back up,
                                      restarted...), and one row per device per day
                                      (polls, how many answered, response times)
    <data>/monitoring/2026-10-14.db   every poll of that day (UTC): response time and result,
                                      for the graphs; whole days are deleted when too old
    <data>/monitoring/status.json     the poller's heartbeat and counters

Only the poller (``poller.py``, its own service) writes. The web app only reads, like syslog.
"""

import datetime as dt
import json
import os
import re
import sqlite3
import tempfile
import threading
from pathlib import Path

_DAY_FILE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.db$")

_STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS device_state (
    device_id INTEGER PRIMARY KEY,
    status TEXT NOT NULL,          -- up, warning, down, unknown, off
    since REAL NOT NULL,           -- in this status since (seconds since 1970, UTC)
    last_poll REAL,
    rtt_ms REAL,                   -- average ping response time of the last poll
    loss REAL,                     -- share of pings lost in the last poll (0..1)
    ping_ok INTEGER,               -- NULL: ping not used
    snmp_ok INTEGER,               -- NULL: SNMP not used
    reason TEXT NOT NULL DEFAULT '', -- why it isn't up, or what to look at
    fails INTEGER NOT NULL DEFAULT 0, -- polls in a row without an answer
    sys_name TEXT NOT NULL DEFAULT '',
    sys_descr TEXT NOT NULL DEFAULT '',
    sys_object_id TEXT NOT NULL DEFAULT '',
    uptime REAL,                   -- seconds the SNMP agent had been up at last_poll
    last_restart REAL,             -- when the device last started (from the uptime)
    maintenance INTEGER NOT NULL DEFAULT 0  -- in a calendar window or an upgrade now
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,
    device_id INTEGER NOT NULL,
    kind TEXT NOT NULL,            -- down, up, restarted, snmp_failed, snmp_ok
    detail TEXT NOT NULL DEFAULT '',
    maintenance INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS events_ts ON events (ts);
CREATE INDEX IF NOT EXISTS events_device ON events (device_id, ts);
CREATE TABLE IF NOT EXISTS daily (
    device_id INTEGER NOT NULL,
    day TEXT NOT NULL,             -- YYYY-MM-DD (UTC)
    polls INTEGER NOT NULL DEFAULT 0,
    up INTEGER NOT NULL DEFAULT 0, -- polls the device answered
    rtt_sum REAL NOT NULL DEFAULT 0,
    rtt_n INTEGER NOT NULL DEFAULT 0,
    rtt_max REAL,
    PRIMARY KEY (device_id, day)
);
"""
_DAY_SCHEMA = """
CREATE TABLE IF NOT EXISTS s (
    ts REAL NOT NULL,
    device_id INTEGER NOT NULL,
    rtt_ms REAL,                   -- NULL: no ping reply (or ping not used)
    ok INTEGER NOT NULL            -- the device answered (ping or SNMP)
);
CREATE INDEX IF NOT EXISTS s_device ON s (device_id, ts);
"""
STATE_COLUMNS = ("device_id", "status", "since", "last_poll", "rtt_ms", "loss", "ping_ok",
                 "snmp_ok", "reason", "fails", "sys_name", "sys_descr", "sys_object_id",
                 "uptime", "last_restart", "maintenance")
EVENTS_KEPT_DAYS = 400


def day_of(ts: float) -> dt.date:
    return dt.datetime.fromtimestamp(ts, dt.UTC).date()


class MonitorStore:
    def __init__(self, directory: Path):
        self.dir = Path(directory)
        self._state: sqlite3.Connection | None = None
        self._days: dict[dt.date, sqlite3.Connection] = {}
        self._lock = threading.Lock()

    # --- writing (the poller) ----------------------------------------------------------

    def _writer(self) -> sqlite3.Connection:
        if self._state is None:
            self.dir.mkdir(parents=True, exist_ok=True)
            con = sqlite3.connect(self.dir / "state.db", check_same_thread=False)
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA synchronous=NORMAL")
            con.executescript(_STATE_SCHEMA)
            self._state = con
        return self._state

    def _day_writer(self, day: dt.date) -> sqlite3.Connection:
        con = self._days.get(day)
        if con is None:
            self.dir.mkdir(parents=True, exist_ok=True)
            con = sqlite3.connect(self.dir / f"{day.isoformat()}.db", check_same_thread=False)
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA synchronous=NORMAL")
            con.executescript(_DAY_SCHEMA)
            for old in [d for d in self._days if d < day - dt.timedelta(days=1)]:
                self._days.pop(old).close()
            self._days[day] = con
        return con

    def save(self, states: list[dict], events: list[dict], samples: list[tuple]) -> None:
        """One poll round: new states, events, and (ts, device_id, rtt_ms, ok) samples."""
        with self._lock:
            con = self._writer()
            with con:
                if states:
                    cols = ", ".join(STATE_COLUMNS)
                    con.executemany(
                        f"INSERT OR REPLACE INTO device_state ({cols}) VALUES "
                        f"({', '.join('?' * len(STATE_COLUMNS))})",
                        [tuple(s.get(c) for c in STATE_COLUMNS) for s in states])
                if events:
                    con.executemany(
                        "INSERT INTO events (ts, device_id, kind, detail, maintenance) "
                        "VALUES (?,?,?,?,?)",
                        [(e["ts"], e["device_id"], e["kind"], e.get("detail", ""),
                          int(bool(e.get("maintenance")))) for e in events])
                for ts, device_id, rtt, ok in samples:
                    con.execute(
                        "INSERT INTO daily (device_id, day, polls, up, rtt_sum, rtt_n, rtt_max) "
                        "VALUES (?, ?, 1, ?, ?, ?, ?) ON CONFLICT (device_id, day) DO UPDATE SET "
                        "polls = polls + 1, up = up + excluded.up, "
                        "rtt_sum = rtt_sum + excluded.rtt_sum, rtt_n = rtt_n + excluded.rtt_n, "
                        "rtt_max = MAX(COALESCE(rtt_max, 0), COALESCE(excluded.rtt_max, 0))",
                        (device_id, day_of(ts).isoformat(), int(ok), rtt or 0,
                         1 if rtt is not None else 0, rtt))
            by_day: dict[dt.date, list[tuple]] = {}
            for row in samples:
                by_day.setdefault(day_of(row[0]), []).append(row)
            for day, rows in by_day.items():
                dcon = self._day_writer(day)
                with dcon:
                    dcon.executemany("INSERT INTO s (ts, device_id, rtt_ms, ok) VALUES (?,?,?,?)",
                                     [(t, d, r, int(o)) for t, d, r, o in rows])

    def forget(self, keep: set[int]) -> None:
        """Drop the state of devices that are gone (deleted, or not monitored any more)."""
        with self._lock:
            con = self._writer()
            have = {r[0] for r in con.execute("SELECT device_id FROM device_state")}
            gone = have - keep
            if gone:
                with con:
                    con.executemany("DELETE FROM device_state WHERE device_id = ?",
                                    [(g,) for g in gone])

    def days(self) -> list[dt.date]:
        if not self.dir.is_dir():
            return []
        found = []
        for name in os.listdir(self.dir):
            m = _DAY_FILE.match(name)
            if m:
                try:
                    found.append(dt.date.fromisoformat(m.group(1)))
                except ValueError:
                    continue
        return sorted(found)

    def size(self) -> int:
        total = 0
        if self.dir.is_dir():
            for name in os.listdir(self.dir):
                try:
                    total += os.stat(self.dir / name).st_size
                except FileNotFoundError:
                    pass
        return total

    def prune(self, keep_days: int, today: dt.date | None = None) -> list[dt.date]:
        """Delete day files older than ``keep_days`` (the daily summaries stay), and events
        older than about a year."""
        today = today or dt.datetime.now(dt.UTC).date()
        first_kept = today - dt.timedelta(days=max(keep_days, 1) - 1)
        gone = [d for d in self.days() if d < first_kept]
        with self._lock:
            for day in gone:
                con = self._days.pop(day, None)
                if con:
                    con.close()
                for suffix in ("", "-wal", "-shm"):
                    try:
                        os.unlink(self.dir / f"{day.isoformat()}.db{suffix}")
                    except FileNotFoundError:
                        pass
            con = self._writer()
            limit = dt.datetime.combine(today - dt.timedelta(days=EVENTS_KEPT_DAYS),
                                        dt.time(), dt.UTC).timestamp()
            with con:
                con.execute("DELETE FROM events WHERE ts < ?", (limit,))
                con.execute("DELETE FROM daily WHERE day < ?",
                            ((today - dt.timedelta(days=EVENTS_KEPT_DAYS)).isoformat(),))
        return gone

    def write_status(self, status: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.dir, prefix=".status-")
        with os.fdopen(fd, "w") as fh:
            json.dump(status, fh)
        os.replace(tmp, self.dir / "status.json")

    def close(self) -> None:
        with self._lock:
            if self._state is not None:
                self._state.close()
                self._state = None
            for con in self._days.values():
                con.close()
            self._days.clear()

    # --- reading (the web app; also the poller at start) -------------------------------------

    def _read(self, name: str) -> sqlite3.Connection | None:
        path = self.dir / name
        if not path.exists():
            return None
        try:
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
            con.row_factory = sqlite3.Row
            return con
        except sqlite3.Error:
            return None

    def status(self) -> dict | None:
        try:
            return json.loads((self.dir / "status.json").read_text())
        except (OSError, ValueError):
            return None

    def states(self) -> dict[int, dict]:
        con = self._read("state.db")
        if con is None:
            return {}
        try:
            return {r["device_id"]: dict(r) for r in con.execute("SELECT * FROM device_state")}
        except sqlite3.Error:
            return {}
        finally:
            con.close()

    def events(self, since: float, until: float, device_id: int | None = None,
               kinds: list[str] | None = None, limit: int = 200) -> list[dict]:
        """Newest first."""
        con = self._read("state.db")
        if con is None:
            return []
        sql, args = ["ts >= ? AND ts < ?"], [since, until]
        if device_id is not None:
            sql.append("device_id = ?")
            args.append(device_id)
        if kinds:
            sql.append(f"kind IN ({','.join('?' * len(kinds))})")
            args += kinds
        try:
            return [dict(r) for r in con.execute(
                f"SELECT * FROM events WHERE {' AND '.join(sql)} ORDER BY ts DESC, id DESC LIMIT ?",
                [*args, limit])]
        except sqlite3.Error:
            return []
        finally:
            con.close()

    def samples(self, device_id: int, since: float, until: float, buckets: int = 0) -> list[dict]:
        """The polls of one device, oldest first; with ``buckets``, averaged into that many
        slots (each with the worst response time and the share that answered)."""
        rows = []
        first, last = day_of(since), day_of(max(since, until - 0.000001))
        for day in [d for d in self.days() if first <= d <= last]:
            con = self._read(f"{day.isoformat()}.db")
            if con is None:
                continue
            try:
                rows += [tuple(r) for r in con.execute(
                    "SELECT ts, rtt_ms, ok FROM s WHERE device_id = ? AND ts >= ? AND ts < ? "
                    "ORDER BY ts", (device_id, since, until))]
            except sqlite3.Error:
                pass
            finally:
                con.close()
        if not buckets:
            return [{"ts": t, "rtt_ms": r, "ok": bool(o)} for t, r, o in rows]
        width = (until - since) / buckets
        slots: dict[int, list] = {}
        for t, r, o in rows:
            slots.setdefault(min(int((t - since) / width), buckets - 1), []).append((r, o))
        out = []
        for i in sorted(slots):
            vals = slots[i]
            rtts = [r for r, _o in vals if r is not None]
            out.append({"ts": since + (i + 0.5) * width,
                        "rtt_ms": round(sum(rtts) / len(rtts), 2) if rtts else None,
                        "rtt_max": max(rtts) if rtts else None,
                        "ok": sum(o for _r, o in vals) / len(vals)})
        return out

    def daily(self, since: dt.date, until: dt.date, device_id: int | None = None) -> list[dict]:
        """Per device per day: polls, answered, average and worst response time."""
        con = self._read("state.db")
        if con is None:
            return []
        sql, args = "day >= ? AND day <= ?", [since.isoformat(), until.isoformat()]
        if device_id is not None:
            sql += " AND device_id = ?"
            args.append(device_id)
        try:
            return [dict(r) for r in con.execute(f"SELECT * FROM daily WHERE {sql} ORDER BY day", args)]
        except sqlite3.Error:
            return []
        finally:
            con.close()

    def availability(self, days: int, today: dt.date | None = None) -> dict[int, float]:
        """Per device: the share of polls answered over the last ``days`` days, in %."""
        today = today or dt.datetime.now(dt.UTC).date()
        totals: dict[int, list[int]] = {}
        for r in self.daily(today - dt.timedelta(days=days - 1), today):
            t = totals.setdefault(r["device_id"], [0, 0])
            t[0] += r["polls"]
            t[1] += r["up"]
        return {d: round(100 * up / polls, 2) for d, (polls, up) in totals.items() if polls}
