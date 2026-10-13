"""Where things are at a site: buildings, floors and rooms, and the racks in them.

Each site has a tree of locations: buildings, floors in a building, and rooms on a floor
(or straight in a building that has no floors). An inventory row is placed by its own
Building, Floor and Room text, matched to the tree by name (any case), the same way a row
is at a site by name or code. A row in a rack (its Rack is the name of a *rack* row at the
same site) is wherever the rack is.

Rack elevations are drawn from the rows' Rack, Position (U), Height (U), Rack face and
Depth. A move (``POST /api/racks/move``) checks the rack's height and the other items in it,
then saves the new place, and copies the rack's site, building, floor and room to the item.
Renaming a building, floor or room changes that text on the rows that used it.
"""

from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from pydantic import Field as PField
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.auth import User, current_user, require
from app.core.db import get_db
from app.tools.inventory import api as inv
from app.tools.inventory.models import Asset, Location, Site

router = APIRouter(prefix="/api", tags=["layout"])
MANAGE = require("inventory", "manage")

KINDS = ("building", "floor", "room")
TEXT = {"building": "building", "floor": "floor", "room": "room"}  # the row's column per kind
DEFAULT_RACK_U = 42


def _key(text) -> str:
    return str(text or "").strip().lower()


class Layout:
    """Every site's tree, every inventory row's place in it, and the racks."""

    def __init__(self, db: Session):
        from app.tools.inventory.sites import _index

        self.sites = list(db.scalars(select(Site).order_by(func.lower(Site.name))))
        self.site_by_text = _index(self.sites)
        self.locations = list(db.scalars(select(Location).order_by(Location.position, Location.id)))
        self.by_id = {loc.id: loc for loc in self.locations}
        self.children: dict[tuple, dict[str, Location]] = defaultdict(dict)
        for loc in self.locations:  # (site id, parent id) -> name -> location
            self.children[(loc.site_id, loc.parent_id)].setdefault(_key(loc.name), loc)
        self.rows = inv.rows(db)
        self.row_by_id = {r["id"]: r for r in self.rows}
        self.own: dict[int, tuple] = {}  # row id -> (site, building, floor, room) from its own text
        for r in self.rows:
            self.own[r["id"]] = self._own_place(r)
        self.racks: dict[tuple, dict] = {}  # (site id, rack name) -> rack row
        racks_by_name: dict[str, list] = defaultdict(list)
        for r in self.rows:
            if r["values"]["type"] == "rack":
                site = self.own[r["id"]][0]
                self.racks.setdefault((site.id if site else None, _key(r["values"]["name"])), r)
                racks_by_name[_key(r["values"]["name"])].append(r)
        self.unique_rack = {k: v[0] for k, v in racks_by_name.items() if len(v) == 1}
        self.rack_of: dict[int, dict] = {}  # row id -> the rack row it is in
        for r in self.rows:
            name = _key(r["values"]["rack"])
            if not name or r["values"]["type"] == "rack":
                continue
            site = self.own[r["id"]][0]
            rack = self.racks.get((site.id if site else None, name))
            if rack is None and site is None:
                rack = self.unique_rack.get(name)
            if rack is not None:
                self.rack_of[r["id"]] = rack

    # --- placing a row ---------------------------------------------------------------------

    def _own_place(self, r: dict) -> tuple:
        site = self.site_by_text.get(_key(inv._effective(r, "site")))
        building = floor = room = None
        if site is not None:
            building = self.children[(site.id, None)].get(_key(r["values"]["building"]))
            if building is not None and building.kind != "building":
                building = None
        if building is not None:
            floor = self.children[(site.id, building.id)].get(_key(r["values"]["floor"]))
            if floor is not None and floor.kind != "floor":
                floor = None
            parent = floor or building
            room = self.children[(site.id, parent.id)].get(_key(r["values"]["room"]))
            if room is not None and room.kind != "room":
                room = None
        return site, building, floor, room

    def place(self, row_id: int) -> tuple:
        """(site, building, floor, room): a rack's place for a row in a rack, else its own."""
        rack = self.rack_of.get(row_id)
        return self.own[rack["id"]] if rack is not None else self.own[row_id]

    def deepest(self, row_id: int) -> Location | None:
        _, b, f, rm = self.place(row_id)
        return rm or f or b

    def under(self, row_id: int, loc: Location) -> bool:
        """Is the row at this location or somewhere inside it?"""
        node = self.deepest(row_id)
        while node is not None:
            if node.id == loc.id:
                return True
            node = self.by_id.get(node.parent_id)
        return False

    def path(self, loc: Location | None) -> list[dict]:
        out = []
        while loc is not None:
            out.insert(0, {"id": loc.id, "kind": loc.kind, "name": loc.name})
            loc = self.by_id.get(loc.parent_id)
        return out

    # --- racks -----------------------------------------------------------------------------

    def rack_out(self, rack: dict) -> dict:
        height = rack["values"]["rack_units"] or DEFAULT_RACK_U
        items, zero_u, unplaced, problems = [], [], [], []
        if not rack["values"]["rack_units"]:
            problems.append(f"Height not set: drawn as {DEFAULT_RACK_U}U")
        for r in self.rows:
            if self.rack_of.get(r["id"]) is not rack:
                continue
            v = r["values"]
            item = {"id": r["id"], "name": v["name"], "type": v["type"],
                    "model": inv._effective(r, "model"), "managed": r["managed"],
                    "backup": r["backup"], "compliance": r["compliance"], "device": r["device"],
                    "position": v["rack_position"], "height": v["rack_units"],
                    "face": v["rack_face"] or "front", "depth": v["rack_depth"] or "full"}
            if v["rack_units"] == 0:
                zero_u.append(item)
            elif v["rack_position"] is None:
                unplaced.append(item)
            else:
                if v["rack_units"] is None:
                    item["height"] = 1
                    problems.append(f"{v['name']}: height not set, drawn as 1U")
                items.append(item)
        items.sort(key=lambda i: -i["position"])
        used = [0] * (height + 1)
        for i in items:
            top = i["position"] + i["height"] - 1
            if i["position"] < 1 or top > height:
                problems.append(f"{i['name']}: U{i['position']}-U{top} is outside the "
                                f"rack (1-{height})")
        for a in items:
            for b in items:
                if a["id"] < b["id"] and _clash(a, b):
                    problems.append(f"{a['name']} and {b['name']} overlap")
        for i in items:
            for u in range(max(1, i["position"]), min(height, i["position"] + i["height"] - 1) + 1):
                used[u] = 1
        site, building, floor, room = self.own[rack["id"]]
        return {"id": rack["id"], "name": rack["values"]["name"], "height": height,
                "site_id": site.id if site else None,
                "path": self.path(room or floor or building),
                "location_id": (room or floor or building).id if (room or floor or building) else None,
                "items": items, "zero_u": zero_u, "unplaced": unplaced,
                "used_u": sum(used), "free_u": height - sum(used), "problems": problems}

    def racks_at(self, site: Site, loc: Location | None = None) -> list[dict]:
        out = []
        for (site_id, _), rack in self.racks.items():
            if site_id == site.id and (loc is None or self.under(rack["id"], loc)):
                out.append(self.rack_out(rack))
        return sorted(out, key=lambda r: r["name"].lower())


def _span(i: dict) -> range:
    return range(i["position"], i["position"] + max(i["height"] or 1, 1))


def _faces(i: dict) -> set[str]:
    return {"front", "rear"} if i["depth"] != "half" else {i["face"]}


def _clash(a: dict, b: dict) -> bool:
    return bool(set(_span(a)) & set(_span(b))) and bool(_faces(a) & _faces(b))


# --- the tree --------------------------------------------------------------------------------

def _site(db: Session, site_id: int) -> Site:
    site = db.get(Site, site_id)
    if site is None:
        raise HTTPException(404, "No such site")
    return site


def _node(layout: Layout, loc: Location) -> dict:
    kids = [_node(layout, c) for c in layout.locations
            if c.parent_id == loc.id]
    at = [r for r in layout.rows if layout.under(r["id"], loc)]
    return {"id": loc.id, "kind": loc.kind, "name": loc.name, "notes": loc.notes,
            "items": len(at), "racks": sum(1 for r in at if r["values"]["type"] == "rack"),
            "children": kids}


@router.get("/sites/{site_id:int}/layout")
def site_layout(site_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    """The site's buildings, floors and rooms with what is in each, and the Building,
    Floor and Room values its items use that aren't in the tree yet."""
    site = _site(db, site_id)
    layout = Layout(db)
    tree = [_node(layout, b) for b in layout.locations if b.site_id == site.id and b.parent_id is None]
    at_site = [r for r in layout.rows if layout.place(r["id"])[0] is site]
    missing: dict[tuple, dict] = {}
    for r in at_site:
        if r["id"] in layout.rack_of:
            continue
        _, b, f, rm = layout.own[r["id"]]
        v = r["values"]
        want = [("building", v["building"], b), ("floor", v["floor"], f), ("room", v["room"], rm)]
        if b is None and not v["building"].strip():
            continue
        names = []
        for kind, text, found in want:
            if not text.strip():
                continue
            names.append(text.strip())
            if found is None:
                key = tuple(n.lower() for n in names)
                entry = missing.setdefault(key, {"path": list(names), "kind": kind, "items": 0})
                entry["items"] += 1
                break
    return {"site": {"id": site.id, "name": site.name}, "tree": tree,
            "not_placed": sum(1 for r in at_site if layout.deepest(r["id"]) is None),
            "missing": sorted(missing.values(), key=lambda m: [p.lower() for p in m["path"]])}


def _parent_is(parent_id: int | None):
    return Location.parent_id.is_(None) if parent_id is None else Location.parent_id == parent_id


class LocationIn(BaseModel):
    kind: str = "building"
    name: str = PField(min_length=1, max_length=100)
    parent_id: int | None = None
    notes: str = PField("", max_length=2000)


def _check_name(db: Session, site_id: int, parent_id: int | None, name: str,
                exclude: int | None = None) -> str:
    name = name.strip()
    if not name:
        raise HTTPException(422, "Name: required")
    for other in db.scalars(select(Location).where(Location.site_id == site_id,
                                                   _parent_is(parent_id))):
        if other.id != exclude and _key(other.name) == _key(name):
            raise HTTPException(409, f"There is already a {other.kind} called {other.name} here")
    return name


@router.post("/sites/{site_id:int}/locations", status_code=201)
def add_location(site_id: int, body: LocationIn, db: Session = Depends(get_db),
                 user: User = Depends(MANAGE)):
    site = _site(db, site_id)
    if body.kind not in KINDS:
        raise HTTPException(422, f"Kind: one of {', '.join(KINDS)}")
    parent = db.get(Location, body.parent_id) if body.parent_id else None
    if body.parent_id and (parent is None or parent.site_id != site.id):
        raise HTTPException(404, "No such building or floor at this site")
    allowed = {"building": (None,), "floor": ("building",), "room": ("building", "floor")}
    if (parent.kind if parent else None) not in allowed[body.kind]:
        raise HTTPException(422, {"building": "A building is at the top of a site",
                                  "floor": "A floor goes in a building",
                                  "room": "A room goes in a building or on a floor"}[body.kind])
    name = _check_name(db, site.id, body.parent_id, body.name)
    position = (db.scalar(select(func.max(Location.position))
                          .where(Location.site_id == site.id)) or 0) + 1
    loc = Location(site_id=site.id, parent_id=body.parent_id, kind=body.kind, name=name,
                   notes=body.notes, position=position)
    db.add(loc)
    db.flush()
    audit(db, user.username, "site.layout_add",
          f"{site.name}: {' / '.join(p['name'] for p in _path(db, loc))} ({loc.kind})")
    return {"id": loc.id}


def _path(db: Session, loc: Location) -> list[dict]:
    out = []
    while loc is not None:
        out.insert(0, {"id": loc.id, "kind": loc.kind, "name": loc.name})
        loc = db.get(Location, loc.parent_id) if loc.parent_id else None
    return out


def _location(db: Session, loc_id: int) -> Location:
    loc = db.get(Location, loc_id)
    if loc is None:
        raise HTTPException(404, "No such building, floor or room")
    return loc


@router.put("/locations/{loc_id:int}")
def change_location(loc_id: int, body: LocationIn, db: Session = Depends(get_db),
                    user: User = Depends(MANAGE)):
    """Rename (or change the notes of) a building, floor or room. The rows placed there
    get the new name in their Building, Floor or Room."""
    loc = _location(db, loc_id)
    name = _check_name(db, loc.site_id, loc.parent_id, body.name, exclude=loc.id)
    moved = 0
    if _key(name) != _key(loc.name) or name != loc.name:
        layout = Layout(db)
        column = TEXT[loc.kind]
        for r in layout.rows:
            if r["id"] not in layout.rack_of and layout.under(r["id"], loc) \
                    and _key(r["values"][column]) == _key(loc.name):
                setattr(db.get(Asset, r["id"]), column, name)
                moved += 1
    old, loc.name, loc.notes = loc.name, name, body.notes
    audit(db, user.username, "site.layout_change",
          f"{old} -> {name}" + (f" (changed on {moved} inventory rows)" if moved else ""))
    return {"renamed_on": moved}


@router.delete("/locations/{loc_id:int}", status_code=204)
def delete_location(loc_id: int, db: Session = Depends(get_db), user: User = Depends(MANAGE)):
    """Delete a building, floor or room, and what is inside it. Items keep their Building,
    Floor and Room values (they show as not in the layout)."""
    loc = _location(db, loc_id)
    db.execute(delete(Location).where(Location.id == loc.id))  # its floors and rooms cascade
    audit(db, user.username, "site.layout_delete", f"{loc.name} ({loc.kind})")
    return Response(status_code=204)


@router.post("/sites/{site_id:int}/layout/from-inventory")
def add_from_inventory(site_id: int, db: Session = Depends(get_db), user: User = Depends(MANAGE)):
    """Add the buildings, floors and rooms the site's items use that aren't in the tree."""
    site = _site(db, site_id)
    added = []
    for _ in range(3):  # a building first, then its floors, then rooms
        missing = site_layout(site.id, db, user)["missing"]
        if not missing:
            break
        for m in missing:
            parent_id, ok = None, True
            for depth, name in enumerate(m["path"]):
                kids = {_key(c.name): c for c in db.scalars(select(Location).where(
                    Location.site_id == site.id, _parent_is(parent_id)))}
                found = kids.get(_key(name))
                if found is None:
                    kind = _kind_for(db, parent_id, depth, len(m["path"]), m["kind"])
                    if kind is None:
                        ok = False
                        break
                    found = Location(site_id=site.id, parent_id=parent_id, kind=kind,
                                     name=name[:100], notes="", position=len(added) + 1000)
                    db.add(found)
                    db.flush()
                    added.append(" / ".join(m["path"][:depth + 1]))
                parent_id = found.id
            if not ok:
                continue
    if added:
        audit(db, user.username, "site.layout_add", f"{site.name}, from the inventory: "
              + ", ".join(added))
    return {"added": added}


def _kind_for(db: Session, parent_id: int | None, depth: int, length: int, last: str) -> str | None:
    if parent_id is None:
        return "building"
    parent = db.get(Location, parent_id)
    if parent.kind == "room":
        return None
    if parent.kind == "floor":
        return "room"
    # in a building: a floor, unless this is the last name and the item has no floor
    return "room" if (depth == length - 1 and last == "room") else "floor"


# --- racks ---------------------------------------------------------------------------------

@router.get("/racks")
def racks(site_id: int, location_id: int | None = None, db: Session = Depends(get_db),
          _: User = Depends(current_user)):
    """The racks at a site (or in one building, floor or room), with what is in each."""
    site = _site(db, site_id)
    loc = _location(db, location_id) if location_id else None
    layout = Layout(db)
    out = layout.racks_at(site, loc)
    items = []
    if loc is not None:  # what is here but not in a rack
        for r in layout.rows:
            if r["values"]["type"] != "rack" and r["id"] not in layout.rack_of \
                    and layout.under(r["id"], loc):
                items.append({"id": r["id"], "name": r["values"]["name"], "type": r["values"]["type"],
                              "model": inv._effective(r, "model"), "managed": r["managed"],
                              "backup": r["backup"], "compliance": r["compliance"],
                              "device": r["device"], "rack": r["values"]["rack"],
                              "path": layout.path(layout.deepest(r["id"]))})
    named = sorted({r["values"]["rack"].strip() for r in layout.rows
                    if r["values"]["rack"].strip() and r["id"] not in layout.rack_of
                    and r["values"]["type"] != "rack" and layout.place(r["id"])[0] is site
                    and (loc is None or layout.under(r["id"], loc))}, key=str.lower)
    return {"racks": out, "items": items, "unknown_racks": named,
            "path": layout.path(loc) if loc else []}


@router.get("/racks/locate/{asset_id:int}")
def locate(asset_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    """Where an item (or a rack) is: its site, its deepest location and its rack."""
    layout = Layout(db)
    if asset_id not in layout.row_by_id:
        raise HTTPException(404, "Not found in the inventory")
    row = layout.row_by_id[asset_id]
    rack = row if row["values"]["type"] == "rack" else layout.rack_of.get(asset_id)
    site, *_ = layout.place(asset_id)
    loc = layout.deepest(asset_id)
    return {"site_id": site.id if site else None, "location_id": loc.id if loc else None,
            "rack_id": rack["id"] if rack else None}


class MoveIn(BaseModel):
    asset_id: int
    rack_id: int | None = None  # None: take it out of its rack
    position: int | None = PField(None, ge=1, le=100)  # None: in the rack, not placed yet
    face: str = "front"


@router.post("/racks/move")
def move(body: MoveIn, db: Session = Depends(get_db), user: User = Depends(MANAGE)):
    """Put an item in a rack at a U position (or in the rack unplaced, or out of it)."""
    asset = db.get(Asset, body.asset_id)
    if asset is None:
        raise HTTPException(404, "Not found in the inventory")
    if asset.type == "rack":
        raise HTTPException(422, "A rack can't go in a rack")
    if body.face not in ("front", "rear"):
        raise HTTPException(422, "Face: front or rear")
    if body.rack_id is None:
        old = asset.rack
        asset.rack, asset.rack_position = "", None
        asset.updated_by = user.username
        audit(db, user.username, "inventory.update", f"{asset.name}: out of rack {old}")
        return {"ok": True}
    rack = db.get(Asset, body.rack_id)
    if rack is None or rack.type != "rack":
        raise HTTPException(404, "No such rack")
    layout = Layout(db)
    rack_row = layout.row_by_id[rack.id]
    height = asset.rack_units
    if height == 0:
        position = None  # zero-U: on the side of the rack
    else:
        position = body.position
    if position is not None:
        size = height or 1
        rack_u = rack.rack_units or DEFAULT_RACK_U
        if position + size - 1 > rack_u:
            raise HTTPException(409, f"{asset.name} is {size}U: from U{position} it would go "
                                     f"past the top of {rack.name} ({rack_u}U)")
        me = {"id": asset.id, "position": position, "height": size, "face": body.face,
              "depth": asset.rack_depth or "full"}
        for other in layout.rack_out(rack_row)["items"]:
            if other["id"] != asset.id and _clash(me, other):
                top = other["position"] + other["height"] - 1
                where = f"U{other['position']}" + (f"-U{top}" if top > other["position"] else "")
                raise HTTPException(409, f"That space is taken by {other['name']} ({where}"
                                         f"{', ' + other['face'] if other['depth'] == 'half' else ''})")
    site, building, floor, room = layout.own[rack.id]
    asset.rack, asset.rack_position, asset.rack_face = rack.name, position, body.face
    # The item is where its rack is: copy the rack's place, so the inventory shows it.
    rack_v = rack_row["values"]
    if site is not None and layout.place(asset.id)[0] is not site:
        asset.site = inv._effective(rack_row, "site")
    asset.building, asset.floor, asset.room = rack_v["building"], rack_v["floor"], rack_v["room"]
    asset.updated_by = user.username
    where = f"U{position} {body.face}" if position else ("side (0U)" if height == 0 else "not placed")
    audit(db, user.username, "inventory.update", f"{asset.name}: rack {rack.name}, {where}")
    return {"ok": True}


def follow_rack(db: Session, rack: Asset, old_name: str) -> int:
    """After a rack row changed: its items get its name and its place. Returns how many."""
    n = 0
    for a in db.scalars(select(Asset).where(func.lower(func.trim(Asset.rack)) == _key(old_name),
                                            Asset.type != "rack")):
        if a.site.strip() and rack.site.strip() and _key(a.site) != _key(rack.site):
            continue  # a rack of the same name at another site
        a.rack = rack.name
        a.building, a.floor, a.room = rack.building, rack.floor, rack.room
        n += 1
    return n

