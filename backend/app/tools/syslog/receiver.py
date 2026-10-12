"""The syslog receiver: listens on UDP and TCP 514 and writes what it receives to the
store (one file per day, ``store.py``).

    python -m app.tools.syslog         (systemd: netops-syslog.service)

It is its own small service, so restarting or upgrading the web app never loses
messages. It runs as the netops account with only the right to listen on port 514.
Every 10 seconds it writes its counters to ``<data>/syslog/status.json`` for the web app.

Protections:
* the sender is the packet's source address (the host firewall decides who may send);
* each sender may send ``syslog_rate_per_source`` messages a second, the rest are counted
  and dropped, so one chatty device can't drown the others;
* messages are cut at 8 KB, TCP lines at 64 KB; at most 500 TCP connections, closed after
  10 minutes of silence;
* storing stops (and is counted) while the disk is nearly full or the newest day alone is
  over the size limit; the oldest days are deleted to stay under the limits.
"""

import asyncio
import datetime as dt
import json
import logging
import os
import shutil
import signal
import tempfile
import time

from app.core.config import Settings
from app.tools.syslog.parse import parse
from app.tools.syslog.sources import normalise
from app.tools.syslog.store import Record, SyslogStore

log = logging.getLogger("netops.syslog")

MAX_LINE = 65536
MAX_CONNECTIONS = 500
IDLE_SECONDS = 600


def split_frames(buf: bytes) -> tuple[list[bytes], bytes]:
    """TCP syslog: octet counting ("57 <34>1 ...", RFC 6587) or one message per line.
    Returns the complete messages and what is left over."""
    out = []
    while buf:
        head, sep, _ = buf[:8].partition(b" ")
        if sep and head.isdigit() and buf[:1] != b"0" and int(head) <= MAX_LINE:
            n, start = int(head), len(head) + 1
            if len(buf) < start + n:
                break
            out.append(buf[start:start + n])
            buf = buf[start + n:]
            continue
        nl = buf.find(b"\n")
        if nl < 0:
            if len(buf) > MAX_LINE:  # no end in sight: take what there is
                out.append(buf[:MAX_LINE])
                buf = buf[MAX_LINE:]
                continue
            break
        out.append(buf[:nl])
        buf = buf[nl + 1:]
    return [m for m in (f.strip(b"\r\n\x00 ") for f in out) if m], buf


class Receiver:
    def __init__(self, settings: Settings, store: SyslogStore, clock=time.time):
        self.settings = settings
        self.store = store
        self.clock = clock
        self.queue: list[Record] = []
        self.allowed: set[str] | None = None  # None: anyone the firewall lets through
        self.full = ""  # why storing has stopped, or ""
        self.connections = 0
        self.started = clock()
        self.last_message = 0.0
        self.counts = {"received": 0, "stored": 0, "dropped_rate": 0, "dropped_unknown": 0,
                       "dropped_full": 0}
        self._buckets: dict[str, list[float]] = {}  # sender -> [tokens, last time]
        self._stop = asyncio.Event()

    # --- one message -----------------------------------------------------------------

    def accept(self, data: bytes, address: str) -> None:
        src = normalise(address)
        self.counts["received"] += 1
        if self.full:
            self.counts["dropped_full"] += 1
            return
        if self.allowed is not None and src not in self.allowed:
            self.counts["dropped_unknown"] += 1
            return
        if not self._take_token(src):
            self.counts["dropped_rate"] += 1
            return
        m = parse(data)
        now = self.clock()
        self.last_message = now
        self.queue.append(Record(now, src, m.severity, m.facility, m.host, m.tag, m.text))

    def _take_token(self, src: str) -> bool:
        rate = max(self.settings.syslog_rate_per_source, 1)
        now = time.monotonic()
        bucket = self._buckets.get(src)
        if bucket is None:
            if len(self._buckets) > 20000:
                self._buckets.clear()
            bucket = self._buckets[src] = [float(rate), now]
        bucket[0] = min(rate, bucket[0] + (now - bucket[1]) * rate)
        bucket[1] = now
        if bucket[0] < 1:
            return False
        bucket[0] -= 1
        return True

    # --- storing and housekeeping ----------------------------------------------------------

    def flush(self) -> int:
        batch, self.queue = self.queue, []
        if batch:
            try:
                self.store.write(batch)
                self.counts["stored"] += len(batch)
            except Exception:  # noqa: BLE001 - e.g. disk full: count it, keep running
                log.exception("Could not store %d syslog messages", len(batch))
                self.counts["dropped_full"] += len(batch)
        return len(batch)

    def check_space(self) -> None:
        s = self.settings
        free = shutil.disk_usage(self.store.dir if self.store.dir.exists() else
                                 self.store.dir.parent).free
        today = self.store.size(dt.datetime.now(dt.UTC).date())
        if free < s.syslog_keep_free_mb * 2**20:
            reason = f"less than {s.syslog_keep_free_mb} MB of disk is free"
        elif today > s.syslog_max_gb * 2**30:
            reason = f"today's messages alone are over the {s.syslog_max_gb} GB limit"
        else:
            reason = ""
        if reason != self.full:
            (log.warning if reason else log.info)(
                "Syslog storing %s", f"stopped: {reason}" if reason else "resumed")
        self.full = reason

    def housekeeping(self) -> None:
        """Settings from the Settings page, the inventory's addresses, the limits."""
        from app.core import appsettings
        from app.core.db import session_scope
        from app.tools.syslog.sources import device_addresses

        appsettings.apply(self.settings)
        if self.settings.syslog_inventory_only:
            with session_scope() as db:
                self.allowed = set(device_addresses(db))
        else:
            self.allowed = None
        gone = self.store.prune(self.settings.syslog_keep_days, self.settings.syslog_max_gb * 2**30)
        if gone:
            log.info("Deleted syslog days %s", ", ".join(d.isoformat() for d in gone))
        self.check_space()

    def status(self) -> dict:
        s = self.settings
        return {"pid": os.getpid(), "started": self.started, "beat": self.clock(),
                "udp_port": s.syslog_udp_port, "tcp_port": s.syslog_tcp_port,
                "last_message": self.last_message or None, "stopped_reason": self.full,
                "connections": self.connections, **self.counts}

    def write_status(self) -> None:
        self.store.dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.store.dir, prefix=".status-")
        with os.fdopen(fd, "w") as fh:
            json.dump(self.status(), fh)
        os.replace(tmp, self.store.dir / "status.json")

    # --- network ----------------------------------------------------------------------------

    async def _tcp_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        peer = writer.get_extra_info("peername")
        address = peer[0] if peer else "unknown"
        if self.connections >= MAX_CONNECTIONS:
            writer.close()
            return
        self.connections += 1
        buf = b""
        try:
            while True:
                chunk = await asyncio.wait_for(reader.read(65536), IDLE_SECONDS)
                if not chunk:
                    break
                frames, buf = split_frames(buf + chunk)
                for frame in frames:
                    self.accept(frame, address)
            if buf.strip():
                self.accept(buf, address)
        except (TimeoutError, ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            self.connections -= 1
            writer.close()

    async def serve(self) -> None:
        loop = asyncio.get_running_loop()
        s = self.settings
        servers, transports = [], []
        if s.syslog_udp_port:
            receiver = self

            class Udp(asyncio.DatagramProtocol):
                def datagram_received(self, data, addr):
                    receiver.accept(data, addr[0])

            transport, _ = await loop.create_datagram_endpoint(
                Udp, local_addr=(s.syslog_bind, s.syslog_udp_port))
            transports.append(transport)
        if s.syslog_tcp_port:
            servers.append(await asyncio.start_server(self._tcp_client, s.syslog_bind,
                                                      s.syslog_tcp_port, limit=MAX_LINE))
        log.info("Syslog receiver listening on %s (UDP %s, TCP %s), storing in %s",
                 s.syslog_bind, s.syslog_udp_port or "off", s.syslog_tcp_port or "off",
                 self.store.dir)
        last_house = float("-inf")
        while not self._stop.is_set():
            try:
                await loop.run_in_executor(None, self.flush)
                now = time.monotonic()
                if now - last_house >= 60:
                    await loop.run_in_executor(None, self.housekeeping)
                    last_house = now
                elif int(now) % 10 == 0:
                    await loop.run_in_executor(None, self.check_space)
                if int(now) % 10 == 0:
                    await loop.run_in_executor(None, self.write_status)
            except Exception:  # noqa: BLE001 - keep receiving
                log.exception("Syslog receiver housekeeping error")
            try:
                await asyncio.wait_for(self._stop.wait(), 1)
            except TimeoutError:
                pass
        for t in transports:
            t.close()
        for srv in servers:
            srv.close()
        self.flush()
        self.write_status()
        self.store.close()
        log.info("Syslog receiver stopped")

    def stop(self, *_args) -> None:
        self._stop.set()


def main() -> None:
    from app.core.config import get_settings
    from app.core.db import init_engine

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    init_engine(settings.database_url)
    receiver = Receiver(settings, SyslogStore(settings.syslog_dir))

    async def run():
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, receiver.stop)
        await receiver.serve()

    asyncio.run(run())
