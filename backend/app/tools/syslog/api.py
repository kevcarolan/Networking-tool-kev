"""HTTP API for the Syslog page: search, counts, download, the receiver's state, and the
suggested device configs. Read-only: only the receiver service writes messages."""

import datetime as dt
import json
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.auth import User, require
from app.core.db import get_db
from app.tools.syslog import howto
from app.tools.syslog.parse import LABELS, SEVERITIES, body, facility_name
from app.tools.syslog.sources import device_addresses
from app.tools.syslog.store import Filter, SyslogStore

router = APIRouter(prefix="/api/syslog", tags=["syslog"])
SYSLOG_VIEW = require("syslog", "view")

UNKNOWN = "unknown"  # the "device" filter value for senders not in the inventory
MAX_RANGE_DAYS = 400
EXPORT_LIMIT = 200_000


def _store(request: Request) -> SyslogStore:
    return SyslogStore(request.app.state.settings.syslog_dir)


def _ts(value: dt.datetime | None, default: float) -> float:
    if value is None:
        return default
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.UTC)
    return value.timestamp()


def _filter(db: Session, since, until, device: str, source: str, severities: str,
            q: str) -> tuple[Filter, dict[str, tuple[int, str]]]:
    now = time.time()
    f = Filter(since=_ts(since, now - 86400), until=_ts(until, now + 60), text=q.strip()[:200])
    if f.until <= f.since:
        raise HTTPException(422, "The end of the period must be after its start")
    if f.until - f.since > MAX_RANGE_DAYS * 86400:
        raise HTTPException(422, f"Choose a period of at most {MAX_RANGE_DAYS} days")
    addresses = device_addresses(db)
    if device == UNKNOWN:
        f.exclude = list(addresses)
    elif device:
        try:
            dev_id = int(device)
        except ValueError:
            raise HTTPException(422, "Unknown device") from None
        f.sources = [ip for ip, (i, _n) in addresses.items() if i == dev_id]
    if source:
        source = source.strip()
        f.sources = [source] if f.sources is None else [s for s in f.sources if s == source]
    if severities:
        try:
            f.severities = sorted({int(s) for s in severities.split(",") if s.strip()})
        except ValueError:
            raise HTTPException(422, "Severities are numbers 0 to 7") from None
        if any(not 0 <= s <= 7 for s in f.severities):
            raise HTTPException(422, "Severities are numbers 0 to 7")
    return f, addresses


def _row(r: dict, addresses: dict) -> dict:
    dev = addresses.get(r["src"])
    return {**r, "time": dt.datetime.fromtimestamp(r["ts"], dt.UTC).isoformat(),
            "device_id": dev[0] if dev else None, "device": dev[1] if dev else None,
            "severity": SEVERITIES[r["sev"]] if 0 <= r["sev"] < 8 else str(r["sev"]),
            "facility": facility_name(r["fac"]), "message": body(r["text"], r["tag"])}


@router.get("/messages")
def messages(request: Request, since: dt.datetime | None = None, until: dt.datetime | None = None,
             device: str = "", source: str = "", severities: str = "", q: str = "",
             limit: int = Query(200, ge=1, le=1000), before: str = "",
             db: Session = Depends(get_db), _: User = Depends(SYSLOG_VIEW)):
    """Newest first. ``before`` is the ``next`` value of the previous page."""
    f, addresses = _filter(db, since, until, device, source, severities, q)
    cursor = None
    if before:
        try:
            ts, ident = before.split(":")
            cursor = (float(ts), int(ident))
        except ValueError:
            raise HTTPException(422, "Bad page marker") from None
    rows, nxt = _store(request).search(f, limit=limit, before=cursor)
    return {"rows": [_row(r, addresses) for r in rows],
            "next": f"{nxt[0]!r}:{nxt[1]}" if nxt else None}


@router.get("/summary")
def summary(request: Request, since: dt.datetime | None = None, until: dt.datetime | None = None,
            device: str = "", source: str = "", severities: str = "", q: str = "",
            buckets: int = Query(60, ge=1, le=240),
            db: Session = Depends(get_db), _: User = Depends(SYSLOG_VIEW)):
    """Counts per severity and per sender, and a timeline, for the same filters."""
    f, addresses = _filter(db, since, until, device, source, severities, q)
    s = _store(request).summary(f, buckets=buckets)
    devices: dict[int, dict] = {}
    unknown = []
    for src, n in s["sources"].items():
        dev = addresses.get(src)
        if dev:
            d = devices.setdefault(dev[0], {"device_id": dev[0], "device": dev[1], "count": 0,
                                            "addresses": []})
            d["count"] += n
            d["addresses"].append(src)
        else:
            unknown.append({"source": src, "count": n})
    return {"since": dt.datetime.fromtimestamp(f.since, dt.UTC).isoformat(),
            "until": dt.datetime.fromtimestamp(f.until, dt.UTC).isoformat(),
            "severity": s["severity"], "labels": LABELS, "bucket_seconds": s["bucket_seconds"],
            "timeline": s["timeline"],
            "devices": sorted(devices.values(), key=lambda d: -d["count"]),
            "unknown": sorted(unknown, key=lambda u: -u["count"])}


@router.get("/export.log")
def export(request: Request, since: dt.datetime | None = None, until: dt.datetime | None = None,
           device: str = "", source: str = "", severities: str = "", q: str = "",
           db: Session = Depends(get_db), user: User = Depends(SYSLOG_VIEW)):
    """The filtered messages as plain text, oldest first (at most 200,000)."""
    f, addresses = _filter(db, since, until, device, source, severities, q)
    rows, _ = _store(request).search(f, limit=EXPORT_LIMIT)
    lines = []
    for r in reversed(rows):
        dev = addresses.get(r["src"])
        when = dt.datetime.fromtimestamp(r["ts"], dt.UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        sev = SEVERITIES[r["sev"]] if 0 <= r["sev"] < 8 else r["sev"]
        lines.append(f"{when} {r['src']} {dev[1] if dev else '-'} {sev} "
                     f"{facility_name(r['fac'])} {r['text']}")
    audit(db, user.username, "syslog.export",
          f"{len(lines)} messages, {dt.datetime.fromtimestamp(f.since, dt.UTC):%Y-%m-%d %H:%M} "
          f"to {dt.datetime.fromtimestamp(f.until, dt.UTC):%Y-%m-%d %H:%M} UTC")
    name = f"syslog-{dt.datetime.fromtimestamp(f.since, dt.UTC):%Y%m%d-%H%M}.log"
    return Response("\n".join(lines) + ("\n" if lines else ""), media_type="text/plain",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/status")
def status(request: Request, _: User = Depends(SYSLOG_VIEW)):
    """Is the receiver running, how much is kept, and the limits."""
    settings = request.app.state.settings
    store = _store(request)
    try:
        receiver = json.loads((store.dir / "status.json").read_text())
    except (OSError, ValueError):
        receiver = None
    running = bool(receiver and time.time() - float(receiver.get("beat", 0)) < 60)
    days = store.days()
    return {"running": running, "receiver": receiver,
            "days": len(days), "oldest": days[0].isoformat() if days else None,
            "bytes": store.size(), "keep_days": settings.syslog_keep_days,
            "max_bytes": settings.syslog_max_gb * 2**30,
            "inventory_only": settings.syslog_inventory_only}


@router.get("/howto")
def setup_help(request: Request, _: User = Depends(SYSLOG_VIEW)):
    """Suggested configs for sending syslog here, per platform; ``{server}`` is the
    address devices use to reach this server."""
    return {"general": howto.GENERAL, "platforms": howto.HOWTO,
            "server": request.url.hostname or "", "udp_port": request.app.state.settings.syslog_udp_port}
