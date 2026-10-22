"""The search box in the top bar: one query, everything it matches.

Finds devices (name, address, site, platform, serial), other inventory items (name,
serial, asset tag, model, address, MAC, rack), sites (name, code, city, address), and,
with the circuits tool, circuits (device, IP, MAC, service, switch, port, drawing) and
MAC or IP addresses the last network scan found (which switch port they are on).
Each group is shown only to people who may see that page, and only when the licence has
the tool. Nothing here contacts a device.
"""

import re

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.auth import User, current_user
from app.core.db import get_db
from app.core.models import Device
from app.core import permissions as pm
from app.core.permissions import at_least

router = APIRouter(prefix="/api/search", tags=["search"])

LIMIT = 8  # results per group
_HEX = re.compile(r"^[0-9a-fA-F:.\-]+$")


def _like(column, q: str):
    return func.lower(column).contains(q.lower(), autoescape=True)


def mac_fragment(q: str) -> str:
    """The hex digits of a query that looks like (part of) a MAC address, else ''."""
    digits = re.sub(r"[^0-9a-fA-F]", "", q).lower()
    if not _HEX.match(q) or len(digits) < 4:
        return ""
    if not re.search(r"[:.\-]", q) and not re.search(r"[a-f]", digits) and len(digits) < 6:
        return ""  # a short number is more likely a port, VLAN or serial than a MAC
    return digits


def _mac_like(column, digits: str):
    """Match a stored MAC (any separators) against hex digits."""
    stripped = func.lower(func.replace(func.replace(func.replace(column, ":", ""), "-", ""), ".", ""))
    return stripped.contains(digits, autoescape=True)


def _group(rows: list, limit: int) -> dict:
    return {"items": rows[:limit], "more": len(rows) > limit}


def search(db: Session, user: User, q: str, limit: int = LIMIT) -> dict:
    from app.core import licence

    q = q.strip()
    modules = set(licence.status(db)["modules"])
    perms = pm.normalise(user.perms)
    out: dict[str, dict] = {}
    if len(q) < 2:
        return {"q": q, "groups": out}
    mac = mac_fragment(q)

    # devices: the inventory's view level is everyone's lowest
    from app.tools.inventory.models import Asset, Site

    serials = {a.device_id: a for a in db.scalars(
        select(Asset).where(Asset.device_id.is_not(None),
                            or_(_like(Asset.serial, q), _like(Asset.asset_tag, q),
                                _like(Asset.model, q))))}
    conds = [_like(Device.name, q), _like(Device.address, q), _like(Device.site, q),
             _like(Device.platform, q)]
    if serials:
        conds.append(Device.id.in_(serials))
    devices = list(db.scalars(select(Device).where(or_(*conds))
                              .order_by(func.lower(Device.name)).limit(limit + 1)))
    assets = dict(db.execute(select(Asset.device_id, Asset.id).where(
        Asset.device_id.in_([d.id for d in devices]))).all()) if devices else {}
    out["devices"] = _group([{
        "id": d.id, "name": d.name, "address": d.address, "site": d.site,
        "platform": d.platform, "asset_id": assets.get(d.id),
        "serial": serials[d.id].serial if d.id in serials else ""} for d in devices], limit)

    # other inventory items (racks, servers, UPSs ...)
    item_conds = [_like(Asset.name, q), _like(Asset.serial, q), _like(Asset.asset_tag, q),
                  _like(Asset.model, q), _like(Asset.mgmt_ip, q), _like(Asset.rack, q),
                  _like(Asset.role, q)]
    if mac:
        item_conds.append(_mac_like(Asset.mac, mac))
    items = list(db.scalars(select(Asset).where(Asset.device_id.is_(None), or_(*item_conds))
                            .order_by(func.lower(Asset.name)).limit(limit + 1)))
    out["items"] = _group([{"id": a.id, "name": a.name, "type": a.type, "site": a.site,
                            "rack": a.rack, "serial": a.serial, "model": a.model}
                           for a in items], limit)

    sites = list(db.scalars(select(Site).where(or_(
        _like(Site.name, q), _like(Site.code, q), _like(Site.city, q), _like(Site.address, q),
        _like(Site.postcode, q))).order_by(func.lower(Site.name)).limit(limit + 1)))
    out["sites"] = _group([{"id": s.id, "name": s.name, "code": s.code, "city": s.city}
                           for s in sites], limit)

    if "circuits" in modules and at_least(perms, "circuits", "view"):
        out["circuits"] = _circuits(db, q, mac, limit)
        out["carriers"] = _carriers(db, q, limit)
        out["network"] = _network(db, q, mac, limit)
    return {"q": q, "groups": {k: v for k, v in out.items() if v["items"]}}


def _circuits(db: Session, q: str, mac: str, limit: int) -> dict:
    from app.tools.circuits.api import _active
    from app.tools.circuits.models import Circuit

    imp = _active(db)
    if imp is None:
        return _group([], limit)
    conds = [_like(getattr(Circuit, c), q) for c in
             ("device_name", "ip", "service", "switch", "port", "drawing_number", "site",
              "ip_partition", "eng_prefix")]
    if mac:
        conds.append(_mac_like(Circuit.mac_norm, mac))
    rows = list(db.scalars(select(Circuit).where(Circuit.import_id == imp.id, or_(*conds))
                           .order_by(Circuit.row_no).limit(limit + 1)))
    return _group([{"id": c.id, "name": c.device_name or f"row {c.row_no}", "service": c.service,
                    "ip": c.ip, "mac": c.mac_norm or c.mac, "switch": c.switch, "port": c.port,
                    "site": c.site} for c in rows], limit)


def _carriers(db: Session, q: str, limit: int) -> dict:
    from app.tools.circuits.models import CarrierCircuit

    rows = list(db.scalars(select(CarrierCircuit).where(or_(*[
        _like(getattr(CarrierCircuit, c), q) for c in
        ("provider", "circuit_ref", "service", "site", "wan_ip", "support", "interface")]))
        .order_by(CarrierCircuit.provider).limit(limit + 1)))
    return _group([{"id": c.id, "provider": c.provider, "circuit_ref": c.circuit_ref,
                    "service": c.service, "site": c.site, "wan_ip": c.wan_ip} for c in rows], limit)


def _network(db: Session, q: str, mac: str, limit: int) -> dict:
    """A MAC or IP address in the last scan's tables: which switch port it is on."""
    from app.tools.circuits.models import LiveArp, LiveMac

    names = dict(db.execute(select(Device.id, Device.name)).all())
    found: list[dict] = []
    macs: set[str] = set()
    ip_like = re.fullmatch(r"[0-9.]{3,}|[0-9a-fA-F:]*:[0-9a-fA-F:]*", q) and not mac
    if ip_like:
        arps = list(db.scalars(select(LiveArp).where(LiveArp.ip.startswith(q, autoescape=True))
                               .limit(limit * 4)))
        ip_of = {}
        for a in arps:
            ip_of.setdefault(a.mac_norm, a.ip)
            macs.add(a.mac_norm)
        edge = {m.mac_norm: m for m in db.scalars(select(LiveMac).where(
            LiveMac.mac_norm.in_(macs), LiveMac.uplink.is_(False)))} if macs else {}
        for m_norm, ip in ip_of.items():
            m = edge.get(m_norm)
            found.append({"mac": m_norm, "ip": ip,
                          "device_id": m.device_id if m else None,
                          "device": names.get(m.device_id, "") if m else "",
                          "port": m.port if m else "", "vlan": m.vlan if m else "",
                          "seen_at": m.seen_at if m else None})
    elif mac:
        rows = list(db.scalars(select(LiveMac).where(_mac_like(LiveMac.mac_norm, mac),
                                                     LiveMac.uplink.is_(False))
                               .limit(limit + 1)))
        ips = {a.mac_norm: a.ip for a in db.scalars(select(LiveArp).where(
            LiveArp.mac_norm.in_([m.mac_norm for m in rows])))} if rows else {}
        for m in rows:
            found.append({"mac": m.mac_norm, "ip": ips.get(m.mac_norm, ""),
                          "device_id": m.device_id, "device": names.get(m.device_id, ""),
                          "port": m.port, "vlan": m.vlan, "seen_at": m.seen_at})
    return _group(found, limit)


@router.get("")
def run_search(q: str = Query("", max_length=100), db: Session = Depends(get_db),
               user: User = Depends(current_user)):
    return search(db, user, q)
