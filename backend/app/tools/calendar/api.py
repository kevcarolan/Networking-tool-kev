"""The maintenance calendar: upgrade job windows and the changes, maintenance, outages and
change freezes people add, with clashes flagged.

Two items clash when their times overlap and they share a device, or a site (an item with
no site is everywhere). Anything at a site during a change freeze there clashes with the
freeze. Upgrade jobs come from the jobs themselves and are shown to people who can see
upgrade jobs; they are changed on the Upgrade jobs page, not here.
"""

import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core import permissions as pm
from app.core.audit import audit
from app.core.auth import User, current_user, require
from app.core.db import get_db, utcnow
from app.core.models import Device
from app.tools.calendar.models import KINDS, CalendarEvent

router = APIRouter(prefix="/api/calendar", tags=["calendar"])
MANAGE = require("inventory", "manage")
MAX_DAYS = 400


class _Sites:
    """Site names as the site list has them (a device's Site may be a code)."""

    def __init__(self, db: Session):
        from app.tools.inventory.models import Site
        from app.tools.inventory.sites import _index

        self.index = _index(list(db.scalars(select(Site))))

    def name(self, text: str) -> str:
        s = self.index.get((text or "").strip().lower())
        return s.name if s else (text or "").strip()


def _event_out(e: CalendarEvent, names: dict[int, str]) -> dict:
    ids = json.loads(e.devices or "[]")
    return {"key": f"e:{e.id}", "source": "event", "id": e.id, "kind": e.kind,
            "kind_label": KINDS.get(e.kind, e.kind), "title": e.title, "start": e.start,
            "end": e.end, "sites": json.loads(e.sites or "[]"),
            "devices": [{"id": i, "name": names.get(i, f"device {i}")} for i in ids],
            "change_ref": e.change_ref, "notes": e.notes, "created_by": e.created_by,
            "updated_by": e.updated_by, "updated_at": e.updated_at}


def _jobs(db: Session, start: datetime, end: datetime, sites: _Sites, devices: dict) -> list[dict]:
    from app.tools.firmware_upgrade.models import CANCELLED, JobUnit, UpgradeJob

    jobs = list(db.scalars(select(UpgradeJob).where(
        UpgradeJob.planned_start.is_not(None), UpgradeJob.planned_end.is_not(None),
        UpgradeJob.planned_start < end, UpgradeJob.planned_end > start,
        UpgradeJob.status != CANCELLED)))
    units: dict[int, list[int]] = {}
    if jobs:
        for u in db.scalars(select(JobUnit).where(JobUnit.job_id.in_([j.id for j in jobs]))
                            .order_by(JobUnit.position)):
            units.setdefault(u.job_id, []).append(u.device_id)
    out = []
    for j in jobs:
        ids = units.get(j.id) or [j.device_id]
        devs = [devices[i] for i in ids if i in devices]
        names = " + ".join(d.name for d in devs) or "a device"
        out.append({"key": f"j:{j.id}", "source": "upgrade", "id": j.id,
                    "kind": "upgrade" if not j.dry_run else "dry_run",
                    "kind_label": "Upgrade" if not j.dry_run else "Upgrade (dry run)",
                    "title": f"{names} → {j.target_version}", "start": j.planned_start,
                    "end": j.planned_end,
                    "sites": sorted({sites.name(d.site) for d in devs if d.site}),
                    "devices": [{"id": d.id, "name": d.name} for d in devs],
                    "change_ref": j.change_ref, "notes": j.notes, "status": j.status,
                    "created_by": j.created_by})
    return out


def _clashes(items: list[dict]) -> None:
    """Fill each item's 'clashes' with the keys of the items it clashes with."""
    for it in items:
        it["clashes"] = []
    for i, a in enumerate(items):
        for b in items[i + 1:]:
            if not (a["start"] < b["end"] and b["start"] < a["end"]):
                continue
            if a["kind"] == "freeze" and b["kind"] == "freeze":
                continue
            sa, sb = set(a["sites"]), set(b["sites"])
            share_site = not sa or not sb or bool(sa & sb)
            share_device = bool({d["id"] for d in a["devices"]} & {d["id"] for d in b["devices"]})
            if "freeze" in (a["kind"], b["kind"]):
                hit = share_site
            else:
                hit = share_device or (share_site and (sa or sb))
            if hit:
                a["clashes"].append(b["key"])
                b["clashes"].append(a["key"])


def items(db: Session, user: User, start: datetime, end: datetime, site: str = "") -> list[dict]:
    from app.core import licence

    sites = _Sites(db)
    devices = {d.id: d for d in db.scalars(select(Device))}
    names = {i: d.name for i, d in devices.items()}
    events = list(db.scalars(select(CalendarEvent).where(CalendarEvent.start < end,
                                                         CalendarEvent.end > start)))
    out = [_event_out(e, names) for e in events]
    perms = pm.normalise(user.perms)
    if pm.at_least(perms, "upgrades", "view") and licence.has_module("upgrades", db):
        out += _jobs(db, start, end, sites, devices)
    _clashes(out)
    if site:
        wanted = sites.name(site).lower()
        out = [x for x in out if not x["sites"] or wanted in {s.lower() for s in x["sites"]}]
    out.sort(key=lambda x: (x["start"], x["title"].lower()))
    return out


def _range(start: datetime | None, end: datetime | None) -> tuple[datetime, datetime]:
    start = start or (utcnow() - timedelta(days=7))
    end = end or (start + timedelta(days=42))
    if end <= start or (end - start).days > MAX_DAYS:
        raise HTTPException(422, f"Choose a period of up to {MAX_DAYS} days")
    return start.replace(tzinfo=None), end.replace(tzinfo=None)


@router.get("")
def list_calendar(start: datetime | None = None, end: datetime | None = None,
                  site: str = Query("", max_length=100), db: Session = Depends(get_db),
                  user: User = Depends(current_user)):
    s, e = _range(start, end)
    return {"start": s, "end": e, "items": items(db, user, s, e, site), "kinds": KINDS}


class EventIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    kind: str = "change"
    start: datetime
    end: datetime
    sites: list[str] = Field(default_factory=list, max_length=200)
    devices: list[int] = Field(default_factory=list, max_length=500)
    change_ref: str = Field("", max_length=100)
    notes: str = Field("", max_length=5000)

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        if v not in KINDS:
            raise ValueError(f"kind must be one of {', '.join(KINDS)}")
        return v


def _apply(db: Session, e: CalendarEvent, body: EventIn) -> None:
    start, end = body.start.replace(tzinfo=None), body.end.replace(tzinfo=None)
    if end <= start:
        raise HTTPException(422, "It ends before it starts")
    if (end - start).days > MAX_DAYS:
        raise HTTPException(422, f"At most {MAX_DAYS} days")
    known = set(db.scalars(select(Device.id).where(Device.id.in_(body.devices)))) if body.devices else set()
    if missing := [i for i in body.devices if i not in known]:
        raise HTTPException(422, f"Unknown device(s): {missing[:5]}")
    sites = _Sites(db)
    e.title, e.kind, e.start, e.end = body.title.strip(), body.kind, start, end
    e.sites = json.dumps(sorted({sites.name(s) for s in body.sites if s.strip()}))
    e.devices = json.dumps(sorted(set(body.devices)))
    e.change_ref, e.notes = body.change_ref.strip(), body.notes


@router.post("/events", status_code=201)
def add_event(body: EventIn, db: Session = Depends(get_db), user: User = Depends(MANAGE)):
    e = CalendarEvent(created_by=user.username, updated_by=user.username)
    _apply(db, e, body)
    db.add(e)
    db.flush()
    audit(db, user.username, "calendar.add", f"{KINDS[e.kind]}: {e.title} ({e.start:%Y-%m-%d %H:%M} UTC)")
    return {"id": e.id}


def _get(db: Session, event_id: int) -> CalendarEvent:
    e = db.get(CalendarEvent, event_id)
    if e is None:
        raise HTTPException(404, "Not in the calendar")
    return e


@router.put("/events/{event_id}")
def edit_event(event_id: int, body: EventIn, db: Session = Depends(get_db),
               user: User = Depends(MANAGE)):
    e = _get(db, event_id)
    _apply(db, e, body)
    e.updated_by = user.username
    audit(db, user.username, "calendar.edit", f"{KINDS[e.kind]}: {e.title}")
    return {"ok": True}


@router.delete("/events/{event_id}")
def delete_event(event_id: int, db: Session = Depends(get_db), user: User = Depends(MANAGE)):
    e = _get(db, event_id)
    audit(db, user.username, "calendar.delete", f"{KINDS.get(e.kind, e.kind)}: {e.title}")
    db.delete(e)
    return {"ok": True}


def _ics_text(text: str) -> str:
    return (text or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,") \
        .replace("\r", "").replace("\n", "\\n")


def _fold(line: str) -> str:
    """iCalendar lines are at most 75 octets; longer ones continue after CRLF + space."""
    out, cur = [], ""
    for ch in line:
        if len((cur + ch).encode()) > 74:
            out.append(cur)
            cur = " "
        cur += ch
    return "\r\n".join(out + [cur])


@router.get("/export.ics")
def export_ics(start: datetime | None = None, end: datetime | None = None,
               site: str = Query("", max_length=100), db: Session = Depends(get_db),
               user: User = Depends(current_user)):
    """The calendar as a file Outlook, Google or Apple Calendar can import."""
    s, e = _range(start, end)
    stamp = utcnow().strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//network operations//calendar//EN",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH"]
    for it in items(db, user, s, e, site):
        desc = [it["kind_label"]]
        if it["change_ref"]:
            desc.append(f"Change: {it['change_ref']}")
        if it["devices"]:
            desc.append("Devices: " + ", ".join(d["name"] for d in it["devices"]))
        if it.get("status"):
            desc.append(f"Job status: {it['status']}")
        if it["clashes"]:
            desc.append(f"Clashes with {len(it['clashes'])} other item(s)")
        if it["notes"]:
            desc.append(it["notes"])
        lines += ["BEGIN:VEVENT", f"UID:{it['key'].replace(':', '-')}@calendar", f"DTSTAMP:{stamp}",
                  f"DTSTART:{it['start']:%Y%m%dT%H%M%SZ}", f"DTEND:{it['end']:%Y%m%dT%H%M%SZ}",
                  _fold(f"SUMMARY:{_ics_text(it['kind_label'] + ': ' + it['title'])}"),
                  _fold(f"LOCATION:{_ics_text(', '.join(it['sites']) or 'Every site')}"),
                  _fold(f"DESCRIPTION:{_ics_text(chr(10).join(desc))}"), "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return Response("\r\n".join(lines) + "\r\n", media_type="text/calendar",
                    headers={"Content-Disposition": 'attachment; filename="maintenance-calendar.ics"'})
