"""The topology map: which devices are connected to which, from the CDP/LLDP neighbours
each device reported at the last network scan (live.Neighbor, table ct_live_neighbors).

A neighbour is matched to the inventory by its name (without the domain) or its
management address. One that isn't in the inventory is shown as an unmanaged box; one at
another site as a box for that site's device. Phones and wireless access points are left
out unless asked for (each device says how many it has). When both ends report a link it
is shown once. Boxes go where people dragged them (ct_topology_positions), else the page
places them. Nothing here contacts a device: run a network scan for fresh links.
"""

from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.auth import User, require
from app.core.db import get_db
from app.core.models import Device
from app.tools.circuits.importer import normalize_port
from app.tools.circuits.models import DeviceScanState, LiveNeighbor, TopologyPosition

router = APIRouter(prefix="/api/topology", tags=["topology"])
VIEW = require("circuits", "view")
MANAGE = require("circuits", "manage")
ALL_SITES = 0


def _key(name: str) -> str:
    return (name or "").strip().lower().split(".")[0]


class _Sites:
    def __init__(self, db: Session):
        from app.tools.inventory.models import Site
        from app.tools.inventory.sites import _index

        self.index = _index(list(db.scalars(select(Site))))

    def of(self, text: str):
        return self.index.get((text or "").strip().lower())


def build(db: Session, site_id: int = ALL_SITES, endpoints: bool = False) -> dict:
    sites = _Sites(db)
    devices = list(db.scalars(select(Device)))
    by_name = {_key(d.name): d for d in devices}
    by_address = {d.address.strip(): d for d in devices if d.address}

    def site_of(d: Device):
        return sites.of(d.site)

    def in_scope(d: Device) -> bool:
        if site_id == ALL_SITES:
            return True
        s = site_of(d)
        return bool(s and s.id == site_id)

    nodes: dict[str, dict] = {}

    def device_node(d: Device, outside: bool = False) -> str:
        key = f"d:{d.id}"
        if key not in nodes:
            s = site_of(d)
            nodes[key] = {"key": key, "kind": "other_site" if outside else "device",
                          "id": d.id, "name": d.name, "platform": d.platform,
                          "site": s.name if s else d.site, "site_id": s.id if s else None,
                          "address": d.address, "endpoints": 0}
        return key

    scope = [d for d in devices if in_scope(d)]
    for d in scope:
        device_node(d)
    read = {s.device_id: s for s in db.scalars(select(DeviceScanState))}

    # pair (sorted node keys) -> side (node key) -> [(local port, remote port)]
    sides: dict[tuple, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    rows = list(db.scalars(select(LiveNeighbor).order_by(LiveNeighbor.device_id,
                                                         LiveNeighbor.id)))
    ids = {d.id for d in scope}
    names = {d.id: d for d in devices}
    for n in rows:
        here = names.get(n.device_id)
        if here is None:
            continue
        other = by_name.get(_key(n.name)) or by_address.get(n.address.strip())
        if other is not None and other.id == here.id:
            continue
        if n.device_id not in ids and not (other is not None and other.id in ids):
            continue  # neither end is at this site
        if not n.infra and other is None:
            if n.device_id in ids:
                nodes[device_node(here)]["endpoints"] += 1
                if not endpoints:
                    continue
            else:
                continue
        a = device_node(here, outside=here.id not in ids)
        if other is not None:
            b = device_node(other, outside=other.id not in ids)
        else:
            b = f"n:{_key(n.name)}"
            nodes.setdefault(b, {"key": b, "kind": "unmanaged" if n.infra else "endpoint",
                                 "name": n.name, "platform": n.platform, "address": n.address,
                                 "site": "", "site_id": None, "endpoints": 0})
        pair = tuple(sorted((a, b)))
        sides[pair][a].append((n.local_port, n.remote_port))

    edges = []
    for (a, b), by_side in sides.items():
        links: list[dict] = [{"a_port": lp, "b_port": rp} for lp, rp in by_side.get(a, [])]
        for lp, rp in by_side.get(b, []):  # b's view: its port first
            same = next((x for x in links if (x["b_port"] and normalize_port(x["b_port"]) ==
                                              normalize_port(lp)) or
                         (rp and normalize_port(x["a_port"]) == normalize_port(rp))), None)
            if same:
                same["b_port"] = same["b_port"] or lp
                same["a_port"] = same["a_port"] or rp
            else:
                links.append({"a_port": rp, "b_port": lp})
        edges.append({"a": a, "b": b, "links": links})

    positions = {p.node: {"x": p.x, "y": p.y} for p in db.scalars(
        select(TopologyPosition).where(TopologyPosition.site_id == site_id))}
    for key, node in nodes.items():
        if node["kind"] in ("device", "other_site"):
            st = read.get(node["id"])
            node["read"] = bool(st and st.last_success)
            node["read_error"] = (st.last_error or "") if st else ""
    not_read = sorted(n["name"] for n in nodes.values()
                      if n["kind"] == "device" and not n.get("read"))
    last = max((s.last_success for s in read.values() if s.last_success), default=None)
    return {"site_id": site_id, "nodes": list(nodes.values()), "edges": edges,
            "positions": positions, "not_read": not_read, "last_scan": last}


@router.get("")
def topology(site_id: int = ALL_SITES, endpoints: bool = False, db: Session = Depends(get_db),
             _: User = Depends(VIEW)):
    if site_id != ALL_SITES:
        from app.tools.inventory.models import Site

        if db.get(Site, site_id) is None:
            raise HTTPException(404, "Site not found")
    return build(db, site_id, endpoints)


class PositionsIn(BaseModel):
    site_id: int = ALL_SITES
    positions: dict[str, dict[str, int]] = Field(default_factory=dict, max_length=2000)


@router.put("/positions")
def save_positions(body: PositionsIn, db: Session = Depends(get_db), user: User = Depends(MANAGE)):
    db.execute(delete(TopologyPosition).where(TopologyPosition.site_id == body.site_id))
    for node, p in body.positions.items():
        if len(node) > 300 or not node.startswith(("d:", "n:")):
            raise HTTPException(422, f"Unknown box: {node[:50]}")
        x, y = int(p.get("x", 0)), int(p.get("y", 0))
        if not (-100000 < x < 100000 and -100000 < y < 100000):
            raise HTTPException(422, "Position out of range")
        db.add(TopologyPosition(site_id=body.site_id, node=node, x=x, y=y))
    audit(db, user.username, "topology.layout",
          f"site {body.site_id or 'all'}: {len(body.positions)} box(es)")
    return {"saved": len(body.positions)}


@router.delete("/positions")
def reset_positions(site_id: int = ALL_SITES, db: Session = Depends(get_db),
                    user: User = Depends(MANAGE)):
    db.execute(delete(TopologyPosition).where(TopologyPosition.site_id == site_id))
    audit(db, user.username, "topology.layout_reset", f"site {site_id or 'all'}")
    return {"ok": True}
