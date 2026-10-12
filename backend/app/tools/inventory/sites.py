"""The site list: data centres, offices, campuses... and what the inventory has at each.

An inventory row (or a device, through its row) is at a site when its Site value is the
site's name or its code, in any case. Renaming a site, or changing its code, changes that
value on the rows and devices that used the old one. Part of every licence, like the
inventory; changes need the inventory's ``manage`` level, and admins add columns.
"""

import io
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from pydantic import Field as PField
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import exports, licence
from app.core.audit import audit
from app.core.auth import User, current_user, require, require_admin
from app.core.db import get_db, session_scope
from app.core.models import Device
from app.tools.inventory import api as inv
from app.tools.inventory import fields as fl
from app.tools.inventory.fields import Field
from app.tools.inventory.models import Asset, Site, SiteField

router = APIRouter(prefix="/api/sites", tags=["sites"])
MANAGE = require("inventory", "manage")

TYPES = ("data centre", "office", "campus", "branch", "warehouse", "factory", "colocation",
         "remote cabinet", "other")
STATUSES = ("live", "planned", "being built", "closing", "closed")

STANDARD: tuple[Field, ...] = (
    Field("name", "Name", "Site", default_shown=True, max_length=100),
    Field("code", "Site code", "Site", default_shown=True, max_length=50),
    Field("type", "Type", "Site", "choice", TYPES, default_shown=True),
    Field("status", "Status", "Site", "choice", STATUSES, default_shown=True),
    Field("region", "Region", "Site", default_shown=True, max_length=100),
    Field("address", "Address", "Address", max_length=500),
    Field("city", "Town / city", "Address", default_shown=True, max_length=100),
    Field("postcode", "Postcode", "Address", max_length=30),
    Field("country", "Country", "Address", default_shown=True, max_length=100),
    Field("contact", "Site contact", "Contact", default_shown=True),
    Field("phone", "Phone", "Contact", max_length=50),
    Field("email", "Email", "Contact"),
    Field("access", "Access and opening hours", "Other", max_length=5000),
    Field("circuits", "WAN / internet circuits", "Other", max_length=5000),
    Field("notes", "Notes", "Other", max_length=5000),
)
COUNTS = (("items", "Items"), ("devices", "Managed devices"), ("backup_failed", "Backups failing"),
          ("behind", "Firmware behind"), ("circuits", "Circuits"))


def _counts(db: Session) -> list[tuple[str, str]]:
    """The counts shown: circuits only when the licence includes the circuit list."""
    return [c for c in COUNTS if c[0] != "circuits" or licence.has_module("circuits", db)]


def all_fields(db: Session) -> list[Field]:
    return [*STANDARD, *fl.custom_fields(db, SiteField)]


def _key(text) -> str:
    return str(text or "").strip().lower()


def _sites(db: Session) -> list[Site]:
    return list(db.scalars(select(Site).order_by(func.lower(Site.name))))


def _index(sites: list[Site]) -> dict[str, Site]:
    """Name or code (lower case) -> site; a name wins over another site's code."""
    out = {_key(s.code): s for s in sites if s.code.strip()}
    out |= {_key(s.name): s for s in sites}
    return out


def _values(site: Site, custom: list[Field]) -> dict:
    values = {f.key: getattr(site, f.key) for f in STANDARD}
    stored = json.loads(site.custom or "{}")
    return values | {f.key: stored.get(f.key[2:]) for f in custom}


def overview(db: Session) -> dict:
    """Every site with what the inventory has there, and the site names the inventory
    uses that aren't on the list."""
    sites = _sites(db)
    index = _index(sites)
    custom = fl.custom_fields(db, SiteField)
    counts = {s.id: dict.fromkeys((k for k, _ in COUNTS), 0) for s in sites}
    unlisted: dict[str, dict] = {}
    for row in inv.rows(db):
        name = str(inv._effective(row, "site") or "").strip()
        if not name:
            continue
        site = index.get(_key(name))
        if site is None:
            entry = unlisted.setdefault(_key(name), {"name": name, "items": 0})
            entry["items"] += 1
            continue
        c = counts[site.id]
        c["items"] += 1
        if row["managed"]:
            c["devices"] += 1
            c["backup_failed"] += row["backup"] == "failed"
            c["behind"] += row["compliance"] == "behind"
    if licence.has_module("circuits", db):
        from app.tools.circuits.api import site_counts

        for site_id, n in site_counts(db).items():
            if site_id in counts:
                counts[site_id]["circuits"] = n
    return {"sites": [{"id": s.id, "values": _values(s, custom), "counts": counts[s.id],
                       "updated_at": s.updated_at, "updated_by": s.updated_by} for s in sites],
            "unlisted": sorted(unlisted.values(), key=lambda u: u["name"].lower())}


@router.get("/meta")
def meta(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return {"fields": fl.describe(all_fields(db)), "kinds": fl.KINDS,
            "counts": [{"key": k, "label": label} for k, label in _counts(db)],
            "can_manage": user.can("inventory", "manage"), "is_admin": user.is_admin}


@router.get("/index")
def site_index(db: Session = Depends(get_db), _: User = Depends(current_user)):
    """Every site's id, name and code: the pages link a Site value to its site with it."""
    return [{"id": s.id, "name": s.name, "code": s.code} for s in _sites(db)]


@router.get("")
def list_sites(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return overview(db)


@router.get("/{site_id:int}/items")
def items(site_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    """The inventory rows at this site."""
    site = _get(db, site_id)
    names = {_key(site.name)} | ({_key(site.code)} if site.code.strip() else set())
    index = _index(_sites(db))
    out = []
    for row in inv.rows(db):
        name = _key(inv._effective(row, "site"))
        if name in names and index.get(name) is site:
            out.append({"id": row["id"], "managed": row["managed"], "backup": row["backup"],
                        "compliance": row["compliance"], "device": row["device"],
                        **{k: inv._effective(row, k) for k in
                           ("name", "type", "model", "mgmt_ip", "building", "room", "rack",
                            "status")}})
    return out


class SiteIn(BaseModel):
    values: dict = PField(default_factory=dict)


def _blank(**values) -> Site:
    return Site(**({f.key: "" for f in STANDARD} | {"custom": "{}"} | values))


def _get(db: Session, site_id: int) -> Site:
    site = db.get(Site, site_id)
    if site is None:
        raise HTTPException(404, "No such site")
    return site


def _clash(db: Session, site: Site) -> None:
    """Names and codes are unique across the list, so a row's Site value means one site."""
    for other in _sites(db):
        if other is site or other.id == site.id:
            continue
        taken = {_key(other.name)} | ({_key(other.code)} if other.code.strip() else set())
        if _key(site.name) in taken:
            raise HTTPException(409, f"{other.name} already uses the name or code {site.name}")
        if site.code.strip() and _key(site.code) in taken:
            raise HTTPException(409, f"{other.name} already uses the name or code {site.code}")


def _set(db: Session, site: Site, values: dict, user: User) -> list[str]:
    try:
        changed = fl.apply(site, values, all_fields(db))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    if not site.name.strip():
        raise HTTPException(422, "Name: required")
    _clash(db, site)
    site.updated_by = user.username
    return changed


def _rename(db: Session, old: str, new: str) -> int:
    """Change a site's name or code on the inventory rows, devices and the circuit list
    (live and pending versions) that use it. Returns how many inventory rows and devices."""
    from app.tools.circuits.models import ACTIVE, PENDING, Circuit, CircuitImport

    if not old.strip() or _key(old) == _key(new):
        return 0
    n = 0
    for model in (Asset, Device):
        for row in db.scalars(select(model).where(func.lower(func.trim(model.site)) == _key(old))):
            row.site = new
            n += 1
    current = select(CircuitImport.id).where(CircuitImport.status.in_((ACTIVE, PENDING)))
    for c in db.scalars(select(Circuit).where(Circuit.import_id.in_(current),
                                              func.lower(func.trim(Circuit.site)) == _key(old))):
        c.site = new
    return n


@router.post("", status_code=201)
def add_site(body: SiteIn, db: Session = Depends(get_db), user: User = Depends(MANAGE)):
    site = _blank()
    _set(db, site, {"status": "live", **body.values}, user)
    db.add(site)
    db.flush()
    audit(db, user.username, "site.add", site.name)
    return {"id": site.id}


@router.put("/{site_id:int}")
def update_site(site_id: int, body: SiteIn, db: Session = Depends(get_db),
                user: User = Depends(MANAGE)):
    site = _get(db, site_id)
    old_name, old_code = site.name, site.code
    changed = _set(db, site, body.values, user)
    moved = _rename(db, old_name, site.name) + _rename(db, old_code, site.code)
    if changed:
        audit(db, user.username, "site.update", f"{site.name}: {', '.join(changed)}"
              + (f" (Site changed on {moved} inventory rows and devices)" if moved else ""))
    return {"changed": changed, "renamed_on": moved}


@router.delete("/{site_id:int}", status_code=204)
def delete_site(site_id: int, db: Session = Depends(get_db), user: User = Depends(MANAGE)):
    site = _get(db, site_id)
    db.delete(site)
    audit(db, user.username, "site.delete", site.name)
    return Response(status_code=204)


@router.post("/from-inventory")
def add_from_inventory(db: Session = Depends(get_db), user: User = Depends(MANAGE)):
    """Add every site name the inventory uses that isn't on the list yet."""
    names = [u["name"] for u in overview(db)["unlisted"]]
    for name in names:
        db.add(_blank(name=name[:100], status="live", updated_by=user.username))
    if names:
        db.flush()
        audit(db, user.username, "site.add", f"from the inventory: {', '.join(names)}")
    return {"added": names}


# --- the columns admins add --------------------------------------------------------------------

@router.post("/fields", status_code=201)
def add_field(body: inv.FieldIn, db: Session = Depends(get_db),
              user: User = Depends(require_admin)):
    return inv.add_custom_field(db, body, SiteField, STANDARD, user, "site")


@router.put("/fields/{key}")
def change_field(key: str, body: inv.FieldIn, db: Session = Depends(get_db),
                 user: User = Depends(require_admin)):
    return inv.change_custom_field(db, SiteField, STANDARD, key, body, user, "site")


@router.delete("/fields/{key}", status_code=204)
def delete_field(key: str, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    inv.delete_custom_field(db, SiteField, Site, key, user, "site")
    return Response(status_code=204)


# --- export, blank template and import ----------------------------------------------------------

def _table(db: Session) -> tuple[list[str], list[list]]:
    fields = all_fields(db)
    data = overview(db)
    counts = _counts(db)
    head = [f.label for f in fields] + [label for _, label in counts]
    body = [[inv._plain(s["values"].get(f.key)) for f in fields]
            + [s["counts"][k] for k, _ in counts] for s in data["sites"]]
    return head, body


@router.get("/export.csv")
def export_csv(db: Session = Depends(get_db), _: User = Depends(current_user)):
    head, body = _table(db)
    out = io.StringIO()
    w = exports.csv_writer(out)
    w.writerow(head)
    for row in body:
        w.writerow(["" if v is None else v for v in row])
    return Response(out.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="sites.csv"'})


@router.get("/export.xlsx")
def export_xlsx(db: Session = Depends(get_db), _: User = Depends(current_user)):
    from openpyxl import Workbook

    head, body = _table(db)
    wb = Workbook()
    ws = wb.active
    ws.title = "Sites"
    ws.append(head)
    for row in body:
        exports.append_row(ws, ["" if v is None else v for v in row])
    ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(), media_type=exports.XLSX_TYPE,
                    headers={"Content-Disposition": 'attachment; filename="sites.xlsx"'})


TEMPLATE_NOTES = [
    "Fill in one row per site on the first sheet, under the column names, then import the file "
    "on the Sites page (Import).",
    "Keep the column names as they are. Columns can be in any order, and you can delete the ones "
    "you don't use; Name is always needed.",
    "Rows are matched to the list by site code, then name: a match is updated, anything else is "
    "added. Empty cells leave a value as it is.",
    "The inventory links an item to a site when the item's Site is the site's name or code.",
    "Type and Status (and pick-list columns) take one of their listed values: Excel shows the list.",
]


@router.get("/template.{fmt}")
def template(fmt: str, columns: str = Query("", max_length=4000), db: Session = Depends(get_db),
             _: User = Depends(current_user)):
    if fmt not in ("csv", "xlsx"):
        raise HTTPException(404, "Use template.csv or template.xlsx")
    fields = {f.key: f for f in all_fields(db)}
    keys = [k for k in dict.fromkeys(c.strip() for c in columns.split(",")) if k in fields] \
        or list(fields)
    if "name" not in keys:
        keys.insert(0, "name")
    chosen = [fields[k] for k in keys]
    return exports.template(fmt, [f.label for f in chosen], "sites-template", TEMPLATE_NOTES,
                            {f.label: list(f.choices) for f in chosen if f.choices},
                            sheet="Sites")


def plan_import(db: Session, table: list[list]) -> dict:
    """What an import would do. Rows are matched by site code, then name."""
    fields = all_fields(db)
    names = {}
    for f in fields:
        names[f.label.lower()] = f
        names[f.key.lower()] = f
    if not table or not any(str(c).strip() for c in table[0]):
        raise HTTPException(422, "The first row must hold the column names")
    header = [str(c).strip() for c in table[0]]
    # The counts in an export are not read back (Circuits is also a column's key).
    counts = {label.lower() for _, label in COUNTS} - {f.label.lower() for f in fields}
    columns = {i: names[h.lower()] for i, h in enumerate(header)
               if h.lower() in names and h.lower() not in counts}
    unknown = [h for i, h in enumerate(header) if h and i not in columns and h.lower() not in counts]
    if not any(f.key == "name" for f in columns.values()):
        raise HTTPException(422, "A 'Name' column is needed")
    existing = _sites(db)
    by_code = {_key(s.code): s for s in existing if s.code.strip()}
    by_name = {_key(s.name): s for s in existing}
    new, updated, errors, seen = [], [], [], set()
    for line, raw in enumerate(table[1:], start=2):
        values = {f.key: raw[i] if i < len(raw) else "" for i, f in columns.items()}
        values = {k: v for k, v in values.items() if str(v).strip() != ""}
        if not values:
            continue
        match = by_code.get(_key(values.get("code"))) if values.get("code") else None
        match = match or by_name.get(_key(values.get("name")))
        probe = _blank()
        if match:
            probe.custom = match.custom
            for f in STANDARD:
                setattr(probe, f.key, getattr(match, f.key))
        try:
            changed = fl.apply(probe, values, fields)
        except ValueError as exc:
            errors.append({"row": line, "message": str(exc)})
            continue
        if not probe.name.strip():
            errors.append({"row": line, "message": "Name: required for a new site"})
            continue
        key = id(match) if match else _key(probe.name)
        if key in seen:
            errors.append({"row": line, "message": f"{probe.name} is in the file twice"})
            continue
        seen.add(key)
        if match:
            if changed:
                updated.append({"row": line, "id": match.id, "name": match.name,
                                "changes": changed, "values": values})
        else:
            new.append({"row": line, "name": probe.name, "values": values})
    return {"new": new, "updated": updated, "errors": errors, "unknown_columns": unknown,
            "columns": [f.label for f in columns.values()]}


@router.put("/import")
async def import_file(request: Request, filename: str = Query(..., max_length=255),
                      commit: bool = False, user: User = Depends(MANAGE)):
    """Upload a spreadsheet (raw body). Without ``commit`` it only shows what would change."""
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > inv.MAX_IMPORT:
            raise HTTPException(413, f"File is larger than {inv.MAX_IMPORT // 2**20} MB")
    table = await run_in_threadpool(inv.read_table, bytes(body), filename)

    def work():
        with session_scope() as db:
            plan = plan_import(db, table)
            if not commit:
                return plan
            if plan["errors"]:
                raise HTTPException(422, f"Fix the {len(plan['errors'])} row(s) with errors first")
            for item in plan["new"]:
                site = _blank()
                _set(db, site, {"status": "live", **item["values"]}, user)
                db.add(site)
                db.flush()
            for item in plan["updated"]:
                site = db.get(Site, item["id"])
                old_name, old_code = site.name, site.code
                _set(db, site, item["values"], user)
                _rename(db, old_name, site.name)
                _rename(db, old_code, site.code)
            audit(db, user.username, "site.import",
                  f"{filename}: {len(plan['new'])} new, {len(plan['updated'])} updated")
            return {**plan, "committed": True}

    return await run_in_threadpool(work)

