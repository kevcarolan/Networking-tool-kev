"""Where syslog messages are kept: one small SQLite database per day.

    <data>/syslog/2026-10-12.db
    <data>/syslog/2026-10-13.db   (days are UTC, by the time the server received the message)

Why a file per day: searching and filtering by device, severity and time is quick (each
file has indexes), the oldest messages go by deleting whole files (no slow deletes inside
a large database), and the size on disk is simply the size of the folder. A day can be
downloaded as a plain text .log file.

Only the receiver (``receiver.py``, its own service) writes. The web app only reads.
"""

import datetime as dt
import os
import re
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

_DAY_FILE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.db$")
_SCHEMA = """
CREATE TABLE IF NOT EXISTS msg (
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,        -- received, seconds since 1970 (UTC)
    src TEXT NOT NULL,       -- the sender's address
    sev INTEGER NOT NULL,    -- 0 emergency .. 7 debug
    fac INTEGER NOT NULL,
    host TEXT NOT NULL,      -- host name written in the message (not trusted)
    tag TEXT NOT NULL,       -- program or message code
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS msg_ts ON msg (ts);
CREATE INDEX IF NOT EXISTS msg_src ON msg (src, ts);
CREATE INDEX IF NOT EXISTS msg_sev ON msg (sev, ts);
"""


@dataclass
class Record:
    ts: float
    src: str
    sev: int
    fac: int
    host: str
    tag: str
    text: str


@dataclass
class Filter:
    since: float
    until: float
    sources: list[str] | None = None  # None: every sender
    exclude: list[str] | None = None  # senders to leave out (e.g. the known devices)
    severities: list[int] | None = None  # None: every severity
    text: str = ""  # contained in the message or its tag (case-insensitive)

    def where(self) -> tuple[str, list]:
        sql, args = ["ts >= ? AND ts < ?"], [self.since, self.until]
        if self.sources is not None:
            sql.append(f"src IN ({','.join('?' * len(self.sources))})" if self.sources else "0")
            args += self.sources
        if self.exclude:
            sql.append(f"src NOT IN ({','.join('?' * len(self.exclude))})")
            args += self.exclude
        if self.severities is not None:
            sql.append(f"sev IN ({','.join('?' * len(self.severities))})" if self.severities else "0")
            args += self.severities
        if self.text:
            like = "%" + re.sub(r"([\\%_])", r"\\\1", self.text) + "%"
            sql.append("(text LIKE ? ESCAPE '\\' OR tag LIKE ? ESCAPE '\\')")
            args += [like, like]
        return " AND ".join(sql), args


def day_of(ts: float) -> dt.date:
    return dt.datetime.fromtimestamp(ts, dt.UTC).date()


def day_start(day: dt.date) -> float:
    return dt.datetime(day.year, day.month, day.day, tzinfo=dt.UTC).timestamp()


class SyslogStore:
    def __init__(self, directory: Path):
        self.dir = Path(directory)
        self._writers: dict[dt.date, sqlite3.Connection] = {}
        self._lock = threading.Lock()

    # --- files ---------------------------------------------------------------------

    def path(self, day: dt.date) -> Path:
        return self.dir / f"{day.isoformat()}.db"

    def days(self) -> list[dt.date]:
        """The days that have a file, oldest first."""
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

    def size(self, day: dt.date | None = None) -> int:
        """Bytes on disk, of one day or of all of them."""
        days = [day] if day else self.days()
        total = 0
        for d in days:
            for suffix in ("", "-wal", "-shm"):
                try:
                    total += os.stat(f"{self.path(d)}{suffix}").st_size
                except FileNotFoundError:
                    pass
        return total

    # --- writing (the receiver) --------------------------------------------------------

    def _writer(self, day: dt.date) -> sqlite3.Connection:
        con = self._writers.get(day)
        if con is None:
            self.dir.mkdir(parents=True, exist_ok=True)
            con = sqlite3.connect(self.path(day), check_same_thread=False)
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA synchronous=NORMAL")
            con.executescript(_SCHEMA)
            self._writers[day] = con
        return con

    def write(self, records: list[Record]) -> None:
        by_day: dict[dt.date, list[Record]] = {}
        for r in records:
            by_day.setdefault(day_of(r.ts), []).append(r)
        with self._lock:
            for day, rows in by_day.items():
                con = self._writer(day)
                with con:
                    con.executemany(
                        "INSERT INTO msg (ts, src, sev, fac, host, tag, text) VALUES (?,?,?,?,?,?,?)",
                        [(r.ts, r.src, r.sev, r.fac, r.host, r.tag, r.text) for r in rows])
            self._close_old(max(by_day, default=None))

    def _close_old(self, newest: dt.date | None) -> None:
        """Close days that are over (a late message can still reopen them)."""
        if newest is None:
            return
        for day in [d for d in self._writers if d < newest - dt.timedelta(days=1)]:
            self._writers.pop(day).close()

    def close(self) -> None:
        with self._lock:
            for con in self._writers.values():
                con.close()
            self._writers.clear()

    def prune(self, keep_days: int, max_bytes: int, today: dt.date | None = None) -> list[dt.date]:
        """Delete whole days: those older than ``keep_days``, then the oldest until the
        folder is under ``max_bytes``. Today is never deleted. Returns the days deleted."""
        today = today or day_of(dt.datetime.now(dt.UTC).timestamp())
        first_kept = today - dt.timedelta(days=max(keep_days, 1) - 1)
        deleted = []
        days = self.days()
        for day in [d for d in days if d < first_kept]:
            self._delete(day)
            deleted.append(day)
        days = [d for d in days if d >= first_kept]
        sizes = {d: self.size(d) for d in days}
        total = sum(sizes.values())
        for day in days:
            if total <= max_bytes or day >= today:
                break
            self._delete(day)
            deleted.append(day)
            total -= sizes[day]
        return deleted

    def _delete(self, day: dt.date) -> None:
        with self._lock:
            con = self._writers.pop(day, None)
            if con:
                con.close()
            for suffix in ("", "-wal", "-shm"):
                try:
                    os.unlink(f"{self.path(day)}{suffix}")
                except FileNotFoundError:
                    pass

    # --- reading (the web app) -----------------------------------------------------------

    def _reader(self, day: dt.date) -> sqlite3.Connection | None:
        path = self.path(day)
        if not path.exists():
            return None
        try:
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
            con.execute("SELECT 1 FROM msg LIMIT 1")
        except sqlite3.Error:
            return None  # being created, or deleted meanwhile
        return con

    def _days_in(self, f: Filter) -> list[dt.date]:
        first, last = day_of(f.since), day_of(max(f.since, f.until - 0.000001))
        return [d for d in self.days() if first <= d <= last]

    def search(self, f: Filter, limit: int = 200, before: tuple[float, int] | None = None
               ) -> tuple[list[dict], tuple[float, int] | None]:
        """Newest first. ``before`` is the (ts, id) of the last row already shown; returns
        the rows and the cursor for the next page (None at the end)."""
        rows: list[dict] = []
        days = self._days_in(f)
        if before:
            days = [d for d in days if d <= day_of(before[0])]
        for day in reversed(days):
            con = self._reader(day)
            if con is None:
                continue
            where, args = f.where()
            if before and day == day_of(before[0]):
                where += " AND (ts < ? OR (ts = ? AND id < ?))"
                args += [before[0], before[0], before[1]]
            try:
                cur = con.execute(
                    f"SELECT id, ts, src, sev, fac, host, tag, text FROM msg WHERE {where} "
                    "ORDER BY ts DESC, id DESC LIMIT ?", [*args, limit - len(rows)])
                rows += [{"id": r[0], "ts": r[1], "src": r[2], "sev": r[3], "fac": r[4],
                          "host": r[5], "tag": r[6], "text": r[7]} for r in cur]
            finally:
                con.close()
            if len(rows) >= limit:
                break
        cursor = (rows[-1]["ts"], rows[-1]["id"]) if len(rows) >= limit else None
        return rows, cursor

    def summary(self, f: Filter, buckets: int = 60) -> dict:
        """Counts for the filter: per severity, per sender, and a timeline."""
        width = max((f.until - f.since) / max(buckets, 1), 1.0)
        severity = [0] * 8
        sources: dict[str, int] = {}
        timeline = [[0] * 8 for _ in range(buckets)]
        for day in self._days_in(f):
            con = self._reader(day)
            if con is None:
                continue
            where, args = f.where()
            try:
                for b, sev, n in con.execute(
                        f"SELECT CAST((ts - ?) / ? AS INTEGER), sev, COUNT(*) FROM msg "
                        f"WHERE {where} GROUP BY 1, 2", [f.since, width, *args]):
                    if 0 <= sev < 8:
                        severity[sev] += n
                        if 0 <= b < buckets:
                            timeline[b][sev] += n
                for src, n in con.execute(f"SELECT src, COUNT(*) FROM msg WHERE {where} "
                                          "GROUP BY src", args):
                    sources[src] = sources.get(src, 0) + n
            finally:
                con.close()
        return {"severity": severity, "sources": sources, "bucket_seconds": width,
                "timeline": timeline}
