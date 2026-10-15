"""HTTP API for the Monitoring page: which devices are up or down, a device's response
times, restarts and events, what is monitored and how (SNMP profiles), and the suggested
device configs.

What the poller found is only read here (its own files, store.py). The one thing that
talks to a device from the web app is a profile's Test button: a single SNMP read of the
system values, by someone who may manage SNMP profiles.
"""

import datetime as dt
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.auth import User, require
from app.core.db import get_db
from app.core.models import Device
from app.tools.monitoring import health as hw
from app.tools.monitoring import howto
from app.tools.monitoring import ifaces as ifm
from app.tools.monitoring.models import LEVELS, VERSIONS, MonitorTarget, SnmpProfile
from app.tools.monitoring.snmp import (AUTH_PROTOCOLS, PRIV_PROTOCOLS, SYS_DESCR, SYS_NAME, SYS_UPTIME, SnmpError,
                                       read_system)
from app.tools.monitoring.store import MonitorStore

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])
VIEW = require("monitoring", "view")
MANAGE = require("monitoring", "manage")
PROFILES = require("inventory", "credentials")  # the SNMP secrets, like device passwords

OFF, WAITING = "off", "waiting"
STATUS_LABELS = {"up": "Up", "warning": "Warning", "down": "Down", "unknown": "Can't check",
                 OFF: "Not monitored", WAITING: "Waiting for the first check"}
EVENT_LABELS = {"down": "Down", "up": "Back up", "restarted": "Restarted",
                "snmp_failed": "SNMP stopped answering", "snmp_ok": "SNMP answers again",
                "port_down": "Port down", "port_up": "Port back up",
                "health_problem": "Hardware or sensor problem", "health_ok": "Hardware or sensor back to normal"}
TOP_ROWS = 10
MAX_RANGE_DAYS = 400


def store_of(request: Request) -> MonitorStore:
    return MonitorStore(request.app.state.settings.monitor_dir)


def poller_status(request: Request) -> dict:
    """Is the poller running (its heartbeat in the last few minutes), and its counters."""
    settings = request.app.state.settings
    s = store_of(request).status()
    beat = float((s or {}).get("beat") or 0)
    running = bool(s) and time.time() - beat < max(3 * settings.monitor_poll_seconds, 120)
    return {"running": running, "poller": s}


def _sites(db: Session):
    from app.tools.calendar.api import _Sites

    return _Sites(db)


def _profiles(db: Session) -> tuple[dict[int, SnmpProfile], SnmpProfile | None]:
    profiles = {p.id: p for p in db.scalars(select(SnmpProfile))}
    return profiles, next((p for p in profiles.values() if p.is_default), None)


def device_rows(db: Session, store: MonitorStore, running: bool) -> list[dict]:
    """Every device with its monitoring choices and what the poller last found."""
    profiles, default = _profiles(db)
    choices = {t.device_id: t for t in db.scalars(select(MonitorTarget))}
    states = store.states()
    healths = store.health() or {}
    week = store.availability(7)
    sites = _sites(db)
    rows = []
    for d in db.scalars(select(Device).order_by(Device.name)):
        t = choices.get(d.id)
        monitored = d.enabled and (t is None or t.monitored)
        own = profiles.get(t.profile_id) if t is not None and t.profile_id else None
        uses_snmp = t.snmp if t is not None else True
        profile = (own or default) if uses_snmp else None
        st = states.get(d.id) if monitored else None
        status = (st["status"] if st else WAITING) if monitored else OFF
        reason = (st or {}).get("reason", "")
        if not monitored:
            reason = "Disabled in the inventory" if not d.enabled else "Switched off for this device"
        rows.append({
            "id": d.id, "name": d.name, "address": d.address, "platform": d.platform,
            "site": sites.name(d.site), "monitored": monitored,
            "ping": t.ping if t is not None else True, "snmp": uses_snmp,
            "profile_id": t.profile_id if t is not None else None,
            "profile": profile.name if profile else None, "profile_is_default": own is None,
            "status": status, "status_label": STATUS_LABELS.get(status, status),
            "reason": reason, "since": (st or {}).get("since"),
            "last_poll": (st or {}).get("last_poll"), "rtt_ms": (st or {}).get("rtt_ms"),
            "loss": (st or {}).get("loss"), "uptime": (st or {}).get("uptime"),
            "last_restart": (st or {}).get("last_restart"),
            "maintenance": bool((st or {}).get("maintenance")),
            "sys_name": (st or {}).get("sys_name", ""), "availability_7d": week.get(d.id),
            "stale": bool(st) and not running,
            **_health_summary(healths.get(d.id) if monitored and uses_snmp else None),
        })
    return rows


def _health_summary(h: dict | None) -> dict:
    if not h or not h.get("ts"):
        return {"health": None, "cpu": None, "memory": None, "hardware_problems": []}
    first = lambda kind: next((r["value"] for r in h["readings"] if r["kind"] == kind and r["value"] is not None), None)  # noqa: E731
    cpu = [r["value"] for r in h["readings"] if r["kind"] == "cpu" and r["value"] is not None]
    return {"health": h["status"], "cpu": max(cpu) if cpu else None, "memory": first("memory"),
            "hardware_problems": sorted(h["problems"].values())}


def counts_of(rows: list[dict]) -> dict:
    counts = {k: 0 for k in STATUS_LABELS}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    counts["maintenance"] = sum(1 for r in rows if r["maintenance"] and r["monitored"])
    counts["hardware"] = sum(1 for r in rows if r["hardware_problems"])
    return counts


@router.get("/status")
def status(request: Request, db: Session = Depends(get_db), _: User = Depends(VIEW)):
    s = request.app.state.settings
    store = store_of(request)
    profiles, default = _profiles(db)
    days = store.days()
    return {**poller_status(request), "interval": s.monitor_poll_seconds,
            "down_after": s.monitor_down_after, "keep_days": s.monitor_keep_days,
            "profiles": len(profiles), "default_profile": default.name if default else None,
            "bytes": store.size(), "oldest": days[0].isoformat() if days else None}


@router.get("/devices")
def devices(request: Request, db: Session = Depends(get_db), _: User = Depends(VIEW)):
    running = poller_status(request)["running"]
    rows = device_rows(db, store_of(request), running)
    return {"devices": rows, "counts": counts_of(rows), "labels": STATUS_LABELS,
            "running": running}


def _event_out(e: dict, names: dict[int, str]) -> dict:
    return {**e, "device": names.get(e["device_id"], f"device {e['device_id']}"),
            "kind_label": EVENT_LABELS.get(e["kind"], e["kind"]),
            "time": dt.datetime.fromtimestamp(e["ts"], dt.UTC).isoformat()}


@router.get("/devices/{device_id}")
def device_detail(device_id: int, request: Request,
                  hours: int = Query(24, ge=1, le=MAX_RANGE_DAYS * 24),
                  db: Session = Depends(get_db), _: User = Depends(VIEW)):
    d = db.get(Device, device_id)
    if d is None:
        raise HTTPException(404, "Device not found")
    store = store_of(request)
    running = poller_status(request)["running"]
    row = next(r for r in device_rows(db, store, running) if r["id"] == device_id)
    st = store.states().get(device_id) or {}
    now = time.time()
    since = now - hours * 3600
    today = dt.datetime.now(dt.UTC).date()
    avail = {f"{n}d": store.availability(n, today).get(device_id) for n in (1, 7, 30, 365)}
    if hours <= 24 * request.app.state.settings.monitor_keep_days:
        graph = store.samples(device_id, since, now, buckets=min(240, max(24, hours * 6)))
    else:  # older than the polls kept: one point a day
        graph = [{"ts": dt.datetime.fromisoformat(r["day"]).replace(tzinfo=dt.UTC).timestamp() + 43200,
                  "rtt_ms": round(r["rtt_sum"] / r["rtt_n"], 2) if r["rtt_n"] else None,
                  "rtt_max": r["rtt_max"], "ok": r["up"] / r["polls"] if r["polls"] else None}
                 for r in store.daily(today - dt.timedelta(days=hours // 24), today, device_id)]
    events = store.events(now - 90 * 86400, now + 60, device_id=device_id, limit=100)
    return {**row, "sys_descr": st.get("sys_descr", ""), "sys_object_id": st.get("sys_object_id", ""),
            "fails": st.get("fails"), "ping_ok": st.get("ping_ok"), "snmp_ok": st.get("snmp_ok"),
            "availability": avail, "hours": hours, "since_ts": since, "until_ts": now,
            "graph": graph, "events": [_event_out(e, {device_id: d.name}) for e in events]}


@router.get("/events")
def events(request: Request, hours: int = Query(24, ge=1, le=MAX_RANGE_DAYS * 24),
           device_id: int | None = None, kinds: str = "",
           limit: int = Query(200, ge=1, le=2000),
           db: Session = Depends(get_db), _: User = Depends(VIEW)):
    now = time.time()
    wanted = [k for k in kinds.split(",") if k.strip()] or None
    if wanted and any(k not in EVENT_LABELS for k in wanted):
        raise HTTPException(422, "Unknown kind of event")
    rows = store_of(request).events(now - hours * 3600, now + 60, device_id=device_id,
                                    kinds=wanted, limit=limit)
    names = dict(db.execute(select(Device.id, Device.name)).all())
    return {"events": [_event_out(e, names) for e in rows], "labels": EVENT_LABELS}


# --- hardware health -------------------------------------------------------------------------

@router.get("/devices/{device_id}/health")
def device_health(device_id: int, request: Request,
                  hours: int = Query(24, ge=1, le=MAX_RANGE_DAYS * 24),
                  db: Session = Depends(get_db), _: User = Depends(VIEW)):
    """CPU, memory, temperatures, fans and power supplies as last read, and over time."""
    d = db.get(Device, device_id)
    if d is None:
        raise HTTPException(404, "Device not found")
    s = request.app.state.settings
    store = store_of(request)
    h = store.health(device_id) or {}
    now = time.time()
    since = now - hours * 3600
    order = {"cpu": 0, "memory": 1, "psu": 2, "fan": 3, "temperature": 4}
    readings = sorted(h.get("readings") or [], key=lambda r: (order.get(r["kind"], 9), r["name"]))
    return {"device": d.name, "platform": d.platform, "read_at": h.get("ts"),
            "status": h.get("status"), "error": h.get("error", ""),
            "readings": [{**r, "kind_label": hw.KINDS.get(r["kind"], r["kind"])} for r in readings],
            "problems": sorted((h.get("problems") or {}).values()), "sources": h.get("sources") or [],
            "interval": s.monitor_health_seconds, "cpu_warn": s.monitor_cpu_warn,
            "mem_warn": s.monitor_mem_warn, "hours": hours, "since_ts": since, "until_ts": now,
            "detail": hours <= s.monitor_interface_keep_days * 24,
            "graph": store.health_samples(device_id, since, now, buckets=min(288, max(24, hours * 4)),
                                          detail_days=s.monitor_interface_keep_days)}


@router.get("/hardware")
def hardware(request: Request, db: Session = Depends(get_db), _: User = Depends(VIEW)):
    """Every device with a hardware problem now."""
    names = {d.id: d for d in db.scalars(select(Device))}
    rows = []
    for device_id, h in (store_of(request).health() or {}).items():
        if h["problems"] and device_id in names:
            rows.append({"device_id": device_id, "device": names[device_id].name,
                         "site": names[device_id].site, "status": h["status"],
                         "problems": sorted(h["problems"].values()), "read_at": h["ts"]})
    rows.sort(key=lambda r: (r["status"] != hw.CRITICAL, r["device"]))
    return {"devices": rows}


# --- interfaces ------------------------------------------------------------------------------

def _iface_out(r: dict) -> dict:
    util = [u for u in (r.get("in_util"), r.get("out_util")) if u is not None]
    return {**r, "oper_label": ifm.OPER.get(r.get("oper") or 0, "unknown"),
            "admin_up": r.get("admin") == 1, "util": max(util) if util else None,
            "watched": bool((r.get("alias") or "").strip()) or r.get("type") == ifm.LAG,
            "graphed": r.get("admin") == 1 and r.get("type") != ifm.LOOPBACK}


@router.get("/devices/{device_id}/interfaces")
def interfaces(device_id: int, request: Request, db: Session = Depends(get_db),
               _: User = Depends(VIEW)):
    if db.get(Device, device_id) is None:
        raise HTTPException(404, "Device not found")
    status = store_of(request).status() or {}
    rows = [_iface_out(r) for r in store_of(request).interfaces(device_id)]
    return {"interfaces": rows, "error": (status.get("interface_errors") or {}).get(str(device_id), ""),
            "interval": request.app.state.settings.monitor_interface_seconds,
            "read_at": max((r["ts"] or 0 for r in rows), default=None)}


@router.get("/devices/{device_id}/interfaces/{if_index}")
def interface_graph(device_id: int, if_index: int, request: Request,
                    hours: int = Query(24, ge=1, le=MAX_RANGE_DAYS * 24),
                    db: Session = Depends(get_db), _: User = Depends(VIEW)):
    d = db.get(Device, device_id)
    if d is None:
        raise HTTPException(404, "Device not found")
    store = store_of(request)
    row = next((r for r in store.interfaces(device_id) if r["if_index"] == if_index), None)
    if row is None:
        raise HTTPException(404, "Interface not found")
    now = time.time()
    since = now - hours * 3600
    keep = request.app.state.settings.monitor_interface_keep_days
    return {"device": d.name, "interface": _iface_out(row), "hours": hours, "since_ts": since,
            "until_ts": now, "detail": hours <= keep * 24,
            "graph": store.iface_samples(device_id, if_index, since, now,
                                         buckets=min(288, max(24, hours * 4)), detail_days=keep)}


@router.get("/ports")
def ports(request: Request, limit: int = Query(TOP_ROWS, ge=1, le=100),
          db: Session = Depends(get_db), _: User = Depends(VIEW)):
    """The busiest ports, and the ports with errors or discards, as last read."""
    names = dict(db.execute(select(Device.id, Device.name)).all())
    rows = [_iface_out(r) for r in store_of(request).interfaces() if r["device_id"] in names
            and r.get("admin") == 1 and r.get("oper") == 1]
    for r in rows:
        r["device"] = names[r["device_id"]]
    busiest = sorted((r for r in rows if r["util"] is not None), key=lambda r: -r["util"])[:limit]
    errors = sorted((r for r in rows if (r.get("errors") or 0) + (r.get("discards") or 0) > 0),
                    key=lambda r: -((r.get("errors") or 0) * 10 + (r.get("discards") or 0)))[:limit]
    return {"busiest": busiest, "errors": errors}


class LinkPort(BaseModel):
    device_id: int
    port: str = Field(max_length=100)


class LinkLoadIn(BaseModel):
    ports: list[LinkPort] = Field(max_length=4000)


@router.post("/link-load")
def link_load(body: LinkLoadIn, request: Request, _: User = Depends(VIEW)):
    """Traffic on the ports at the ends of the network map's lines (by port name)."""
    from app.tools.circuits.importer import normalize_port

    by_device: dict[int, dict[str, dict]] = {}
    for r in store_of(request).interfaces():
        names = by_device.setdefault(r["device_id"], {})
        for n in (r.get("name"), r.get("descr")):
            if n:
                names.setdefault(normalize_port(n), r)
    out = []
    for p in body.ports:
        r = by_device.get(p.device_id, {}).get(normalize_port(p.port))
        if r is None:
            continue
        x = _iface_out(r)
        out.append({"device_id": p.device_id, "port": p.port, "in_bps": x["in_bps"],
                    "out_bps": x["out_bps"], "util": x["util"], "speed": x["speed"],
                    "oper": x["oper_label"], "errors": x["errors"], "discards": x["discards"]})
    return {"ports": out}


# --- what is monitored, and how ---------------------------------------------------------------

class ChoiceIn(BaseModel):
    device_ids: list[int] = Field(min_length=1, max_length=5000)
    monitored: bool | None = None
    ping: bool | None = None
    snmp: bool | None = None
    profile_id: int | None = None  # with set_profile: None = the default profile
    set_profile: bool = False


@router.put("/devices")
def set_choices(body: ChoiceIn, db: Session = Depends(get_db), user: User = Depends(MANAGE)):
    """Change what is monitored for one or more devices (only the fields given)."""
    if body.set_profile:
        if not user.can("inventory", "addresses"):
            # The profile's secrets go to the device's address: as for credential profiles.
            raise HTTPException(403, "Choosing a device's SNMP profile needs the 'addresses' "
                                     "level for Devices and credentials")
        if body.profile_id is not None and db.get(SnmpProfile, body.profile_id) is None:
            raise HTTPException(422, "Unknown SNMP profile")
    devices = {d.id: d for d in db.scalars(select(Device).where(Device.id.in_(body.device_ids)))}
    if missing := [i for i in body.device_ids if i not in devices]:
        raise HTTPException(422, f"Unknown device(s): {missing[:5]}")
    changes = []
    for key in ("monitored", "ping", "snmp"):
        if getattr(body, key) is not None:
            changes.append(f"{key} {'on' if getattr(body, key) else 'off'}")
    if body.set_profile:
        p = db.get(SnmpProfile, body.profile_id) if body.profile_id else None
        changes.append(f"SNMP profile {p.name if p else 'the default'}")
    if not changes:
        raise HTTPException(422, "Nothing to change")
    for device_id in body.device_ids:
        t = db.get(MonitorTarget, device_id)
        if t is None:
            t = MonitorTarget(device_id=device_id, monitored=True, ping=True, snmp=True)
            db.add(t)
        for key in ("monitored", "ping", "snmp"):
            if getattr(body, key) is not None:
                setattr(t, key, getattr(body, key))
        if body.set_profile:
            t.profile_id = body.profile_id
        t.updated_by = user.username
    names = sorted(devices[i].name for i in body.device_ids)
    audit(db, user.username, "monitoring.devices",
          f"{', '.join(names[:10])}{' …' if len(names) > 10 else ''}: {', '.join(changes)}")
    return {"ok": True, "changed": len(body.device_ids)}


# --- SNMP profiles ----------------------------------------------------------------------------

def _profile_out(p: SnmpProfile, used: int) -> dict:
    return {"id": p.id, "name": p.name, "version": p.version, "username": p.username,
            "level": p.level, "auth_protocol": p.auth_protocol, "priv_protocol": p.priv_protocol,
            "port": p.port, "timeout": p.timeout, "retries": p.retries, "is_default": p.is_default,
            "has_community": bool(p.community_enc), "has_auth_key": bool(p.auth_key_enc),
            "has_priv_key": bool(p.priv_key_enc), "devices": used, "updated_at": p.updated_at,
            "updated_by": p.updated_by}


def _usage(db: Session) -> tuple[dict[int, int], int]:
    """Devices per profile chosen for them, and devices on the default."""
    own = dict(db.execute(select(MonitorTarget.profile_id, func.count()).where(
        MonitorTarget.profile_id.is_not(None)).group_by(MonitorTarget.profile_id)).all())
    total = db.scalar(select(func.count()).select_from(Device)) or 0
    return own, total - sum(own.values())


@router.get("/profiles")
def list_profiles(db: Session = Depends(get_db), _: User = Depends(VIEW)):
    own, on_default = _usage(db)
    out = []
    for p in db.scalars(select(SnmpProfile).order_by(SnmpProfile.name)):
        out.append(_profile_out(p, own.get(p.id, 0) + (on_default if p.is_default else 0)))
    return {"profiles": out, "versions": VERSIONS, "levels": LEVELS, "auth": list(AUTH_PROTOCOLS),
            "priv": list(PRIV_PROTOCOLS)}


class ProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    version: str = "3"
    community: str | None = Field(default=None, max_length=200)  # None on update = keep
    username: str = Field(default="", max_length=100)
    level: str = "authPriv"
    auth_protocol: str = "SHA"
    auth_key: str | None = Field(default=None, max_length=200)
    priv_protocol: str = "AES"
    priv_key: str | None = Field(default=None, max_length=200)
    port: int = Field(default=161, ge=1, le=65535)
    timeout: int = Field(default=2, ge=1, le=30)
    retries: int = Field(default=1, ge=0, le=5)
    is_default: bool = False


def _apply_profile(db: Session, p: SnmpProfile, body: ProfileIn, cipher, user: User) -> None:
    if body.version not in VERSIONS:
        raise HTTPException(422, "Version must be 2c or 3")
    if body.level not in LEVELS:
        raise HTTPException(422, f"Security level must be one of {', '.join(LEVELS)}")
    if body.auth_protocol not in AUTH_PROTOCOLS or body.priv_protocol not in PRIV_PROTOCOLS:
        raise HTTPException(422, "Unknown authentication or encryption protocol")
    have = lambda new, old: bool(new) if new is not None else bool(old)  # noqa: E731
    if body.version == "2c":
        if not have(body.community, p.community_enc):
            raise HTTPException(422, "Enter the community")
    else:
        if not body.username.strip():
            raise HTTPException(422, "Enter the SNMPv3 user name")
        for key, old, needed, label in (
                ("auth_key", p.auth_key_enc, body.level != "noAuthNoPriv", "authentication"),
                ("priv_key", p.priv_key_enc, body.level == "authPriv", "encryption")):
            new = getattr(body, key)
            if needed and not have(new, old):
                raise HTTPException(422, f"Enter the {label} password")
            if new is not None and new and len(new) < 8:
                raise HTTPException(422, f"The {label} password must be at least 8 characters")
    p.name, p.version, p.username = body.name.strip(), body.version, body.username.strip()
    p.level, p.auth_protocol, p.priv_protocol = body.level, body.auth_protocol, body.priv_protocol
    p.port, p.timeout, p.retries = body.port, body.timeout, body.retries
    for key, attr in (("community", "community_enc"), ("auth_key", "auth_key_enc"),
                      ("priv_key", "priv_key_enc")):
        value = getattr(body, key)
        if value is not None:
            setattr(p, attr, cipher.encrypt(value) if value else "")
    if body.version == "2c":
        p.auth_key_enc = p.priv_key_enc = ""
    else:
        p.community_enc = ""
    if body.is_default:
        for other in db.scalars(select(SnmpProfile).where(SnmpProfile.is_default.is_(True))):
            other.is_default = False
    p.is_default = body.is_default
    p.updated_by = user.username


def _describe(p: SnmpProfile) -> str:
    if p.version == "2c":
        return f"{p.name}: v2c{', the default' if p.is_default else ''}"
    return (f"{p.name}: v3 user {p.username}, {p.level} {p.auth_protocol}/{p.priv_protocol}"
            f"{', the default' if p.is_default else ''}")


@router.post("/profiles", status_code=201)
def add_profile(body: ProfileIn, request: Request, db: Session = Depends(get_db),
                user: User = Depends(PROFILES)):
    p = SnmpProfile()
    _apply_profile(db, p, body, request.app.state.cipher, user)
    db.add(p)
    try:
        db.flush()
    except IntegrityError:
        raise HTTPException(409, "An SNMP profile with that name already exists") from None
    audit(db, user.username, "monitoring.profile_add", _describe(p))
    return _profile_out(p, 0)


def _get_profile(db: Session, profile_id: int) -> SnmpProfile:
    p = db.get(SnmpProfile, profile_id)
    if p is None:
        raise HTTPException(404, "SNMP profile not found")
    return p


@router.put("/profiles/{profile_id}")
def change_profile(profile_id: int, body: ProfileIn, request: Request,
                   db: Session = Depends(get_db), user: User = Depends(PROFILES)):
    p = _get_profile(db, profile_id)
    _apply_profile(db, p, body, request.app.state.cipher, user)
    try:
        db.flush()
    except IntegrityError:
        raise HTTPException(409, "An SNMP profile with that name already exists") from None
    audit(db, user.username, "monitoring.profile_change", _describe(p))
    return _profile_out(p, 0)


@router.delete("/profiles/{profile_id}")
def delete_profile(profile_id: int, db: Session = Depends(get_db), user: User = Depends(PROFILES)):
    p = _get_profile(db, profile_id)
    moved = db.scalar(select(func.count()).select_from(MonitorTarget).where(
        MonitorTarget.profile_id == p.id)) or 0
    for t in db.scalars(select(MonitorTarget).where(MonitorTarget.profile_id == p.id)):
        t.profile_id = None
    db.delete(p)
    audit(db, user.username, "monitoring.profile_delete",
          f"{p.name}{f' ({moved} device(s) back on the default)' if moved else ''}")
    return {"ok": True, "devices_moved": moved}


class TestIn(BaseModel):
    device_id: int


@router.post("/profiles/{profile_id}/test")
def test_profile(profile_id: int, body: TestIn, request: Request, db: Session = Depends(get_db),
                 user: User = Depends(PROFILES)):
    """Read the system values of one device with this profile, now."""
    from app.tools.monitoring.poller import target_for

    p = _get_profile(db, profile_id)
    d = db.get(Device, body.device_id)
    if d is None:
        raise HTTPException(404, "Device not found")
    try:
        target = target_for(p, d.address.strip(), request.app.state.cipher)
    except Exception:  # noqa: BLE001
        raise HTTPException(422, "Can't read this profile's secrets: enter them again") from None
    try:
        values = read_system(target, request.app.state.snmp_client)
    except SnmpError as exc:
        audit(db, user.username, "monitoring.profile_test", f"{p.name} on {d.name}: failed: {exc}")
        return {"ok": False, "message": str(exc)}
    uptime = values.get(SYS_UPTIME)
    audit(db, user.username, "monitoring.profile_test", f"{p.name} on {d.name}: answered")
    return {"ok": True, "message": f"{d.name} answered", "sys_name": values.get(SYS_NAME) or "",
            "sys_descr": (values.get(SYS_DESCR) or "")[:300],
            "uptime": uptime / 100 if isinstance(uptime, int) else None}


# --- Meraki (Dashboard API) ------------------------------------------------------------------

def _meraki_out(o, state: dict | None) -> dict:
    from app.tools.monitoring import meraki as mk

    st = state or {}
    return {"id": o.id, "name": o.name, "base_url": o.base_url,
            "base_label": mk.BASES.get(o.base_url, o.base_url), "org_id": o.org_id,
            "org_name": o.org_name, "enabled": o.enabled, "has_key": bool(o.api_key_enc),
            "updated_at": o.updated_at, "updated_by": o.updated_by, "read_at": st.get("ts"),
            "error": st.get("error", ""), "devices": st.get("devices"), "networks": st.get("networks")}


@router.get("/meraki")
def meraki(request: Request, db: Session = Depends(get_db), _: User = Depends(VIEW)):
    """The Meraki organisations, their devices and status, and scheduled firmware upgrades."""
    from app.tools.monitoring import meraki as mk
    from app.tools.monitoring.models import MerakiOrg

    data = store_of(request).meraki()
    orgs = list(db.scalars(select(MerakiOrg).order_by(MerakiOrg.name)))
    names = {o.id: o.name for o in orgs}
    devices = [{**d, "org": names.get(d["org_ref"], ""),
                "status_label": mk.STATUSES.get(d["status"], d["status"].capitalize())}
               for d in data["devices"] if d["org_ref"] in names]
    counts = {k: 0 for k in mk.STATUSES}
    for d in devices:
        counts[d["status"]] = counts.get(d["status"], 0) + 1
    order = {"offline": 0, "alerting": 1, "online": 3, "dormant": 4}
    devices.sort(key=lambda d: (order.get(d["status"], 2), d["network"], d["name"]))
    return {"connections": [_meraki_out(o, data["state"].get(o.id)) for o in orgs],
            "devices": devices, "counts": counts, "bases": mk.BASES,
            "upgrades": [u for u in data["upgrades"] if u["org_ref"] in names],
            "interval": request.app.state.settings.monitor_meraki_seconds}


class MerakiIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    base_url: str = "https://api.meraki.com/api/v1"
    api_key: str | None = Field(default=None, max_length=200)  # None on change = keep
    org_id: str = Field(min_length=1, max_length=50, pattern=r"^[A-Za-z0-9_-]+$")
    org_name: str = Field(default="", max_length=200)
    enabled: bool = True


def _apply_meraki(o, body: MerakiIn, cipher, user: User) -> None:
    from app.tools.monitoring import meraki as mk

    if body.base_url not in mk.BASES:
        raise HTTPException(422, "Choose one of the Dashboard API addresses")
    if body.api_key is not None and not body.api_key.strip() or (not o.api_key_enc and not body.api_key):
        raise HTTPException(422, "Enter the API key")
    o.name, o.base_url, o.org_id = body.name.strip(), body.base_url, body.org_id.strip()
    o.org_name, o.enabled, o.updated_by = body.org_name.strip(), body.enabled, user.username
    if body.api_key:
        o.api_key_enc = cipher.encrypt(body.api_key.strip())


@router.post("/meraki/connections", status_code=201)
def add_meraki(body: MerakiIn, request: Request, db: Session = Depends(get_db),
               user: User = Depends(PROFILES)):
    from app.tools.monitoring.models import MerakiOrg

    o = MerakiOrg()
    _apply_meraki(o, body, request.app.state.cipher, user)
    db.add(o)
    try:
        db.flush()
    except IntegrityError:
        raise HTTPException(409, "A Meraki connection with that name already exists") from None
    audit(db, user.username, "monitoring.meraki_add", f"{o.name}: organisation {o.org_id} at {o.base_url}")
    return _meraki_out(o, None)


def _get_meraki(db: Session, conn_id: int):
    from app.tools.monitoring.models import MerakiOrg

    o = db.get(MerakiOrg, conn_id)
    if o is None:
        raise HTTPException(404, "Meraki connection not found")
    return o


@router.put("/meraki/connections/{conn_id}")
def change_meraki(conn_id: int, body: MerakiIn, request: Request, db: Session = Depends(get_db),
                  user: User = Depends(PROFILES)):
    o = _get_meraki(db, conn_id)
    _apply_meraki(o, body, request.app.state.cipher, user)
    try:
        db.flush()
    except IntegrityError:
        raise HTTPException(409, "A Meraki connection with that name already exists") from None
    audit(db, user.username, "monitoring.meraki_change",
          f"{o.name}: organisation {o.org_id}, {'on' if o.enabled else 'off'}"
          f"{', new API key' if body.api_key else ''}")
    return _meraki_out(o, None)


@router.delete("/meraki/connections/{conn_id}")
def delete_meraki(conn_id: int, db: Session = Depends(get_db), user: User = Depends(PROFILES)):
    o = _get_meraki(db, conn_id)
    db.delete(o)
    audit(db, user.username, "monitoring.meraki_delete", o.name)
    return {"ok": True}


class MerakiOrgsIn(BaseModel):
    base_url: str = "https://api.meraki.com/api/v1"
    api_key: str | None = Field(default=None, max_length=200)
    connection_id: int | None = None  # use that connection's saved key


@router.post("/meraki/organizations")
def meraki_organizations(body: MerakiOrgsIn, request: Request, db: Session = Depends(get_db),
                         user: User = Depends(PROFILES)):
    """The organisations an API key can read (the connection form's Test button)."""
    from app.tools.monitoring import meraki as mk

    key = (body.api_key or "").strip()
    base = body.base_url
    if not key and body.connection_id:
        o = _get_meraki(db, body.connection_id)
        base = body.base_url or o.base_url
        try:
            key = request.app.state.cipher.decrypt(o.api_key_enc)
        except Exception:  # noqa: BLE001
            raise HTTPException(422, "Can't read the saved API key: enter it again") from None
    if not key:
        raise HTTPException(422, "Enter the API key")
    try:
        orgs = mk.MerakiClient(base, key, fetch=request.app.state.meraki_fetch).organizations()
    except mk.MerakiError as exc:
        audit(db, user.username, "monitoring.meraki_test", f"{base}: failed: {exc}")
        return {"ok": False, "message": str(exc), "organizations": []}
    audit(db, user.username, "monitoring.meraki_test", f"{base}: {len(orgs)} organisation(s)")
    return {"ok": True, "message": f"The key reads {len(orgs)} organisation(s)", "organizations": orgs}


@router.post("/meraki/inventory")
def meraki_to_inventory(request: Request, db: Session = Depends(get_db),
                        user: User = Depends(require("inventory", "manage"))):
    """Add the Meraki devices to the inventory, or bring their rows up to date (by serial
    number). Only the columns Meraki knows are written; the rest are left as they are."""
    from app.tools.inventory.models import Asset
    from app.tools.monitoring import meraki as mk
    from app.tools.monitoring.models import MerakiOrg

    orgs = {o.id for o in db.scalars(select(MerakiOrg))}
    devices = [d for d in store_of(request).meraki()["devices"] if d["org_ref"] in orgs and d["serial"]]
    existing = {a.serial.upper(): a for a in db.scalars(select(Asset).where(Asset.serial != ""))}
    added = updated = 0
    for d in devices:
        a = existing.get(d["serial"].upper())
        values = {"name": d["name"][:200], "type": mk.PRODUCT_TYPES.get(d["product_type"], "other"),
                  "manufacturer": "Cisco Meraki", "model": d["model"][:100], "serial": d["serial"][:100],
                  "version": d["firmware"][:100], "mgmt_ip": d["lan_ip"][:255], "mac": d["mac"][:50],
                  "site": d["network"][:100]}
        if a is None:
            db.add(Asset(**values, status="in service"))
            added += 1
        else:
            changed = False
            for k, v in values.items():
                if k == "name" and a.device_id:
                    continue  # a managed device keeps its own name
                if v and getattr(a, k) != v:
                    setattr(a, k, v)
                    changed = True
            updated += changed
    audit(db, user.username, "monitoring.meraki_inventory", f"{added} added, {updated} brought up to date")
    return {"added": added, "updated": updated, "total": len(devices)}


# --- custom SNMP sensors ---------------------------------------------------------------------

class SensorIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    oid: str = Field(min_length=1, max_length=200)
    mode: str = "value"
    table: bool = False
    label_oid: str = Field(default="", max_length=200)
    unit: str = Field(default="", max_length=20)
    scale: float = Field(default=1.0, gt=-1e9, lt=1e9)
    warn_above: float | None = None
    crit_above: float | None = None
    warn_below: float | None = None
    crit_below: float | None = None
    ok_values: str = Field(default="", max_length=100)
    warn_values: str = Field(default="", max_length=100)
    platform: str = Field(default="", max_length=50)
    site: str = Field(default="", max_length=100)
    device_ids: list[int] = Field(default_factory=list, max_length=1000)
    notes: str = Field(default="", max_length=2000)
    enabled: bool = True


def _check_sensor(body: SensorIn) -> dict:
    """The sensor as the poller uses it; 422 with plain words when something is wrong."""
    from app.core.platforms import PLATFORMS
    from app.tools.monitoring import sensors as sn

    try:
        oid = sn.clean_oid(body.oid)
        label = sn.clean_oid(body.label_oid) if body.label_oid.strip() else ""
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    if body.mode not in sn.MODES:
        raise HTTPException(422, "Choose value, rate or state")
    if body.mode == "state" and not sn.codes(body.ok_values):
        raise HTTPException(422, "A state sensor needs the codes that are fine (e.g. 1)")
    if body.platform and body.platform not in PLATFORMS:
        raise HTTPException(422, "Unknown platform")
    if body.scale == 0:
        raise HTTPException(422, "The scale can't be 0 (1 keeps the value as it is)")
    return {**body.model_dump(), "name": body.name.strip(), "oid": oid, "label_oid": label,
            "unit": body.unit.strip(), "site": body.site.strip(), "id": 0}


def _sensor_out(x, counts: dict) -> dict:
    import json

    return {"id": x.id, "name": x.name, "oid": x.oid, "mode": x.mode, "table": x.table,
            "label_oid": x.label_oid, "unit": x.unit, "scale": x.scale, "warn_above": x.warn_above,
            "crit_above": x.crit_above, "warn_below": x.warn_below, "crit_below": x.crit_below,
            "ok_values": x.ok_values, "warn_values": x.warn_values, "platform": x.platform,
            "site": x.site, "device_ids": json.loads(x.device_ids or "[]"), "notes": x.notes,
            "enabled": x.enabled, "devices": counts.get(x.id, 0), "updated_by": x.updated_by}


def _apply_sensor(x, v: dict, user: User) -> None:
    import json

    for k in ("name", "oid", "mode", "table", "label_oid", "unit", "scale", "warn_above", "crit_above",
              "warn_below", "crit_below", "ok_values", "warn_values", "platform", "site", "notes", "enabled"):
        setattr(x, k, v[k])
    x.device_ids = json.dumps(sorted(set(v["device_ids"])))
    x.updated_by = user.username


@router.get("/sensors")
def list_sensors(db: Session = Depends(get_db), _: User = Depends(VIEW)):
    """The custom SNMP sensors, how many devices each applies to, and the examples."""
    from app.core.platforms import PLATFORMS
    from app.tools.monitoring import sensors as sn
    from app.tools.monitoring.models import Sensor
    from app.tools.monitoring.poller import load_jobs, load_sensors

    defs = {d["id"]: d for d in load_sensors(db)}
    jobs = [j for j in load_jobs(db, None) if j.snmp is not None or "secrets" in j.snmp_note]
    counts = {i: sum(sn.applies(d, j.device_id, j.platform, j.site) for j in jobs) for i, d in defs.items()}
    return {"sensors": [_sensor_out(x, counts) for x in db.scalars(select(Sensor).order_by(Sensor.name))],
            "modes": sn.MODES, "examples": sn.EXAMPLES,
            "platforms": {k: p.label for k, p in PLATFORMS.items()}}


@router.post("/sensors", status_code=201)
def add_sensor(body: SensorIn, db: Session = Depends(get_db), user: User = Depends(MANAGE)):
    from app.tools.monitoring.models import Sensor

    x = Sensor()
    _apply_sensor(x, _check_sensor(body), user)
    db.add(x)
    try:
        db.flush()
    except IntegrityError:
        raise HTTPException(409, "A sensor with that name already exists") from None
    audit(db, user.username, "monitoring.sensor_add", f"{x.name}: {x.oid} ({x.mode})")
    return _sensor_out(x, {})


@router.put("/sensors/{sensor_id}")
def change_sensor(sensor_id: int, body: SensorIn, db: Session = Depends(get_db), user: User = Depends(MANAGE)):
    from app.tools.monitoring.models import Sensor

    x = db.get(Sensor, sensor_id)
    if x is None:
        raise HTTPException(404, "Sensor not found")
    _apply_sensor(x, _check_sensor(body), user)
    try:
        db.flush()
    except IntegrityError:
        raise HTTPException(409, "A sensor with that name already exists") from None
    audit(db, user.username, "monitoring.sensor_change", f"{x.name}: {x.oid} ({x.mode}), {'on' if x.enabled else 'off'}")
    return _sensor_out(x, {})


@router.delete("/sensors/{sensor_id}")
def delete_sensor(sensor_id: int, db: Session = Depends(get_db), user: User = Depends(MANAGE)):
    from app.tools.monitoring.models import Sensor

    x = db.get(Sensor, sensor_id)
    if x is None:
        raise HTTPException(404, "Sensor not found")
    db.delete(x)
    audit(db, user.username, "monitoring.sensor_delete", x.name)
    return {"ok": True}


class SensorTestIn(SensorIn):
    test_device_id: int


@router.post("/sensors/test")
def test_sensor(body: SensorTestIn, request: Request, db: Session = Depends(get_db),
                user: User = Depends(MANAGE)):
    """Read the sensor (saved or not) from one device now, with the device's SNMP profile."""
    import asyncio

    from app.tools.monitoring import sensors as sn
    from app.tools.monitoring.poller import load_jobs

    v = _check_sensor(body)
    d = db.get(Device, body.test_device_id)
    if d is None:
        raise HTTPException(404, "Device not found")
    job = next((j for j in load_jobs(db, request.app.state.cipher) if j.device_id == d.id), None)
    if job is None or job.snmp is None:
        raise HTTPException(422, f"{d.name} isn't polled with SNMP" + (f": {job.snmp_note}" if job and job.snmp_note else ""))
    client = request.app.state.snmp_client
    if client is None:
        from app.tools.monitoring.snmp import SnmpClient
        client = SnmpClient()
    try:
        readings = asyncio.run(sn.read(client, job.snmp, [v], time.time(), {}))
    except SnmpError as exc:
        audit(db, user.username, "monitoring.sensor_test", f"{v['name']} on {d.name}: failed: {exc}")
        return {"ok": False, "message": str(exc), "readings": []}
    audit(db, user.username, "monitoring.sensor_test", f"{v['name']} on {d.name}: {len(readings)} reading(s)")
    got = [r for r in readings if r.value is not None or r.source.startswith("first read")]
    msg = (f"{d.name} answered: {len(readings)} reading{'s' if len(readings) != 1 else ''}" if got
           else readings[0].source if readings else "No answer")
    return {"ok": bool(got), "message": msg, "readings": [r.as_dict() for r in readings]}


@router.get("/howto")
def setup_help(request: Request, _: User = Depends(VIEW)):
    """Suggested SNMP configs per platform; ``{server}`` is this server's address."""
    return {"general": howto.GENERAL, "platforms": howto.HOWTO, "user": howto.USER,
            "server": request.url.hostname or ""}
