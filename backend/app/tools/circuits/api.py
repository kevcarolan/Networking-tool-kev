"""HTTP API for the master circuit list."""

import csv
import io
import json
from collections import defaultdict

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.auth import User, require
from app.core.db import get_db, session_scope, utcnow
from app.core.models import Device
from app.tools.circuits.importer import (FIELDS, CircuitImportError, diff, match_switches,
                                         parse_workbook, row_key)
from app.tools.circuits import live
from app.tools.circuits.models import (ACTIVE, PENDING, SUPERSEDED, Circuit, CircuitImport,
                                       CircuitScan)
from app.tools.circuits.store import LiveIndex

router = APIRouter(prefix="/api/circuits", tags=["circuits"])

CIRCUITS_VIEW = require("circuits", "view")
CIRCUITS_MANAGE = require("circuits", "manage")

CSV_HEADERS = {
    "ip_partition": "IP Partition", "service": "Service", "eng_prefix": "Engineering prefix",
    "device_name": "Device Name", "device_type": "Device Type", "manufacturer": "Manufacturer",
    "mac": "Hardware Mac Address", "floor": "Floor Level", "room": "Room / Area",
    "ip": "IP Address", "mask": "Subnet Mask", "gateway": "Default Gateway", "vlan": "VLAN",
    "conn_type": "TYPE", "port": "PORT", "switch": "DEVICE", "drawing_number": "Drawing Number",
    "drawing_ref": "Device Drawing Reference",
}


def _active(db: Session) -> CircuitImport | None:
    return db.scalar(select(CircuitImport).where(CircuitImport.status == ACTIVE))


def _rows(db: Session, import_id: int) -> list[Circuit]:
    return db.scalars(select(Circuit).where(Circuit.import_id == import_id)
                      .order_by(Circuit.row_no)).all()


def _matches(db: Session, rows) -> dict[str, tuple[str, list[int]]]:
    names = dict(db.execute(select(Device.id, Device.name)).all())
    return match_switches(names, {r.switch_norm for r in rows if r.switch_norm})


def _row_out(c: Circuit, matches: dict, names: dict[int, str], idx: LiveIndex | None = None) -> dict:
    status, ids = matches.get(c.switch_norm, ("none", []))
    out = {f: getattr(c, f) for f in FIELDS}
    doc_id = ids[0] if status == "matched" else None
    out.update(id=c.id, row_no=c.row_no, port_norm=c.port_norm, warnings=c.warnings,
               match=status if c.switch_norm else "none",
               switch_device_id=doc_id, switch_device_name=names.get(doc_id) if doc_id else None)
    if idx is not None:
        out.update(_live(c, doc_id, names, idx))
    return out


def _live(c: Circuit, doc_id: int | None, names: dict[int, str], idx: LiveIndex) -> dict:
    """The circuit's live location from the last MAC/ARP tables (live.resolve)."""
    if not idx.has_data:
        return {"live_status": "", "live_status_label": "Not scanned yet", "live_device_id": None,
                "live_switch": "", "live_port": "", "live_vlan": "", "live_mac": c.mac_norm,
                "live_mac_source": "", "live_scanned_at": None, "last_seen_at": None,
                "last_seen_where": ""}
    r = live.resolve(c.mac_norm, c.ip.strip(), (doc_id, c.port_norm if c.port else ""),
                     idx.edges, idx.arp)
    dev = r["live_device_id"]
    st = idx.scanned.get(dev) if dev else None
    last = idx.last_seen.get(r["live_mac"]) if r["live_mac"] else None
    return {**r, "live_status_label": live.STATUS_LABELS.get(r["live_status"], ""),
            "live_switch": names.get(dev, "") if dev else "",
            "live_scanned_at": st.last_success if st else None,
            "last_seen_at": last.seen_at if last else None,
            "last_seen_where": f"{names.get(last.device_id, '?')} {last.port}" if last else ""}


def _names(db: Session) -> dict[int, str]:
    return dict(db.execute(select(Device.id, Device.name)).all())


def _scan_out(db: Session) -> dict:
    last = db.scalar(select(CircuitScan).order_by(CircuitScan.id.desc()).limit(1))
    full = db.scalar(select(CircuitScan).where(CircuitScan.trigger.not_like("upgrade-job:%"))
                     .where(CircuitScan.finished_at.is_not(None))
                     .order_by(CircuitScan.id.desc()).limit(1))
    return {"last": _scan_row(last) if last else None,
            "last_full": _scan_row(full) if full else None}


def _scan_row(s: CircuitScan) -> dict:
    return {"id": s.id, "trigger": s.trigger, "started_at": s.started_at,
            "finished_at": s.finished_at, "devices_ok": s.devices_ok,
            "devices_failed": s.devices_failed, "errors": s.errors}


def _import_out(imp: CircuitImport) -> dict:
    return {"id": imp.id, "filename": imp.filename, "sheet": imp.sheet, "status": imp.status,
            "uploaded_by": imp.uploaded_by, "uploaded_at": imp.uploaded_at,
            "committed_by": imp.committed_by, "committed_at": imp.committed_at,
            "row_count": imp.row_count, "warning_count": imp.warning_count,
            "summary": json.loads(imp.summary or "{}")}


# --- the current list -------------------------------------------------------

@router.get("")
def list_circuits(db: Session = Depends(get_db), _: User = Depends(CIRCUITS_VIEW)):
    imp = _active(db)
    scan = _scan_out(db)
    if imp is None:
        return {"import": None, "circuits": [], "scan": scan}
    rows = _rows(db, imp.id)
    matches = _matches(db, rows)
    names, idx = _names(db), LiveIndex(db)
    return {"import": _import_out(imp), "scan": scan,
            "circuits": [_row_out(c, matches, names, idx) for c in rows]}


@router.get("/export.csv")
def export_csv(db: Session = Depends(get_db), _: User = Depends(CIRCUITS_VIEW)):
    imp = _active(db)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow([CSV_HEADERS[f] for f in FIELDS] + ["Matched inventory device", "Warnings"]
               + LIVE_HEADERS)
    for r in _export_rows(db):
        w.writerow([r[f] for f in FIELDS] + [r["switch_device_name"] or r["match"],
                                              r["warnings"]] + _live_cells(r))
    return Response(out.getvalue(), media_type="text/csv", headers={
        "Content-Disposition": 'attachment; filename="circuit-list.csv"'})


LIVE_HEADERS = ["Live status", "Live switch", "Live port", "Live VLAN", "MAC used",
                "Live data from", "Last seen", "Last seen on"]


def _fmt(t) -> str:
    return f"{t:%Y-%m-%d %H:%M}" if t else ""


def _live_cells(r: dict) -> list:
    mac = r["live_mac"] + (" (from ARP)" if r["live_mac_source"] == "arp" else "")
    return [r["live_status_label"], r["live_switch"], r["live_port"], r["live_vlan"], mac,
            _fmt(r["live_scanned_at"]), _fmt(r["last_seen_at"]), r["last_seen_where"]]


def _export_rows(db: Session) -> list[dict]:
    imp = _active(db)
    if imp is None:
        return []
    rows = _rows(db, imp.id)
    matches = _matches(db, rows)
    names, idx = _names(db), LiveIndex(db)
    return [_row_out(c, matches, names, idx) for c in rows]


@router.get("/export-updated.xlsx")
def export_updated(db: Session = Depends(get_db), _: User = Depends(CIRCUITS_VIEW)):
    """The circuit list with DEVICE and PORT taken from the network where the circuit was
    found, plus the documented values and the live status. Uploading it again makes the
    live locations the documented ones."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Circuits"
    ws.append([CSV_HEADERS[f] for f in FIELDS] + ["Documented DEVICE", "Documented PORT"]
              + LIVE_HEADERS)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for r in _export_rows(db):
        found = r["live_status"] in (live.MATCHES, live.MOVED, live.FOUND)
        values = {**{f: r[f] for f in FIELDS}}
        if found:
            values["switch"], values["port"] = r["live_switch"], r["live_port"]
            values["vlan"] = r["vlan"] or r["live_vlan"]
        ws.append([values[f] for f in FIELDS] + [r["switch"], r["port"]] + _live_cells(r))
    ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(), headers={
        "Content-Disposition": 'attachment; filename="circuit-list-updated.xlsx"'},
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@router.get("/for-device/{device_id}")
def for_device(device_id: int, db: Session = Depends(get_db), _: User = Depends(CIRCUITS_VIEW)):
    """Circuits on one switch, grouped by service and VLAN (for upgrade planning)."""
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(404, "Device not found")
    return circuits_for_device(db, device)


def circuits_for_device(db: Session, device: Device) -> dict:
    """Circuits the list puts on this device, or that were last seen on it.
    Also used by upgrade jobs to freeze the affected circuits."""
    imp = _active(db)
    if imp is None:
        return {"device": device.name, "import": None, "count": 0, "groups": []}
    rows = _rows(db, imp.id)
    matches = _matches(db, rows)
    names, idx = _names(db), LiveIndex(db)
    groups = defaultdict(list)
    count = 0
    for c in rows:
        r = _row_out(c, matches, names, idx)
        if device.id not in (r["switch_device_id"], r["live_device_id"]):
            continue
        r["on_this_device"] = ("both" if r["switch_device_id"] == r["live_device_id"] else
                               "list" if r["switch_device_id"] == device.id else "live")
        count += 1
        groups[(c.service or "(no service)", c.vlan or r["live_vlan"] or "-")].append(r)
    return {"device": device.name, "import": _import_out(imp), "count": count,
            "groups": [{"service": s, "vlan": v, "circuits": items}
                       for (s, v), items in sorted(groups.items())]}


def circuits_seen(db: Session, device_id: int, edge_macs: list[list[str]]) -> list[dict]:
    """Circuits of the live list whose MAC is on one of this device's edge ports
    (edge_macs: [mac, port, port_norm, vlan]). Saved in an upgrade job's pre-check
    snapshot and compared after the reload."""
    imp = _active(db)
    if imp is None or not edge_macs:
        return []
    here = {m[0]: m for m in edge_macs}
    idx = LiveIndex(db)
    seen = []
    for c in _rows(db, imp.id):
        mac = c.mac_norm or (idx.arp.get(c.ip.strip(), "") if c.ip else "")
        if mac in here:
            _, port, port_norm, vlan = here[mac]
            seen.append({"name": c.device_name or c.eng_prefix or f"row {c.row_no}", "mac": mac,
                         "service": c.service, "vlan": vlan or c.vlan, "port": port,
                         "port_norm": port_norm})
    return seen


# --- reading the network (MAC and ARP tables) ---------------------------------

@router.get("/scans")
def list_scans(db: Session = Depends(get_db), _: User = Depends(CIRCUITS_VIEW)):
    rows = db.scalars(select(CircuitScan).order_by(CircuitScan.id.desc()).limit(50))
    return [_scan_row(s) for s in rows]


@router.post("/scan", status_code=202)
def scan_now(request: Request, device_id: int | None = Body(None, embed=True),
             db: Session = Depends(get_db), user: User = Depends(CIRCUITS_MANAGE)):
    """Read the MAC and ARP tables now (every device, or one) with the backup accounts."""
    svc = request.app.state.circuit_scan
    if device_id is not None and db.get(Device, device_id) is None:
        raise HTTPException(404, "Device not found")
    if not svc.scan_in_background(f"manual:{user.username}",
                                  [device_id] if device_id is not None else None):
        raise HTTPException(409, "A scan is already running")
    audit(db, user.username, "circuits.scan",
          f"device {device_id}" if device_id is not None else "all devices")
    return {"started": True}


# --- imports ----------------------------------------------------------------

@router.get("/imports")
def list_imports(db: Session = Depends(get_db), _: User = Depends(CIRCUITS_VIEW)):
    rows = db.scalars(select(CircuitImport).order_by(CircuitImport.id.desc()).limit(100))
    return [_import_out(i) for i in rows]


@router.get("/imports/{import_id}")
def get_import(import_id: int, db: Session = Depends(get_db), _: User = Depends(CIRCUITS_VIEW)):
    imp = db.get(CircuitImport, import_id) or _not_found()
    return _import_out(imp)


@router.put("/imports/upload", status_code=201)
async def upload(request: Request, filename: str = Query(..., max_length=255),
                 user: User = Depends(CIRCUITS_MANAGE)):
    """Upload a spreadsheet (raw .xlsx body). It is checked and kept as a pending
    import with a preview; nothing changes until it is committed."""
    limit = request.app.state.settings.circuits_max_upload_mb * 2**20
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > limit:
            raise HTTPException(413, f"File is larger than {limit // 2**20} MB")
    if not filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(422, "Upload an Excel workbook (.xlsx)")
    try:
        parsed = await run_in_threadpool(parse_workbook, bytes(body))
    except CircuitImportError as exc:
        raise HTTPException(422, str(exc)) from None
    return await run_in_threadpool(_store_pending, parsed, filename, user.username)


def _store_pending(parsed, filename: str, username: str) -> dict:
    with session_scope() as db:
        # Only one pending import at a time: a new upload replaces the old preview.
        for old in db.scalars(select(CircuitImport).where(CircuitImport.status == PENDING)):
            db.delete(old)
        imp = CircuitImport(filename=filename[:255], sheet=parsed.sheet, uploaded_by=username,
                            row_count=len(parsed.rows),
                            warning_count=sum(bool(r.warnings) for r in parsed.rows))
        db.add(imp)
        db.flush()
        db.add_all(Circuit(import_id=imp.id, row_no=r.row_no, switch_norm=r.switch_norm,
                           port_norm=r.port_norm, mac_norm=r.mac_norm,
                           warnings="; ".join(r.warnings), **r.values) for r in parsed.rows)
        db.flush()

        new_rows = _rows(db, imp.id)
        active = _active(db)
        old_rows = _rows(db, active.id) if active else []
        matches = _matches(db, new_rows)
        unmatched = sorted({k for k, (s, _) in matches.items() if s == "unmatched"})
        ambiguous = sorted({k for k, (s, _) in matches.items() if s == "ambiguous"})
        values = lambda c: {f: getattr(c, f) for f in FIELDS}  # noqa: E731
        summary = {
            "header_row": parsed.header_row,
            "columns": parsed.columns,
            "missing_columns": [f for f in FIELDS if f not in parsed.columns],
            "switches": len(matches),
            "unmatched_switches": unmatched,
            "ambiguous_switches": ambiguous,
            "rows_unmatched": sum(1 for c in new_rows
                                  if matches.get(c.switch_norm, ("none",))[0] != "matched"),
            "warnings_sample": [{"row": c.row_no, "warnings": c.warnings}
                                for c in new_rows if c.warnings][:100],
            "diff": diff([(row_key(values(c), c.mac_norm), values(c)) for c in old_rows],
                         [(row_key(values(c), c.mac_norm), values(c)) for c in new_rows]),
            "replaces_import": active.id if active else None,
        }
        imp.summary = json.dumps(summary, default=str)
        audit(db, username, "circuits.import.preview",
              f"{filename}: {imp.row_count} rows, {imp.warning_count} with warnings")
        return _import_out(imp)


@router.post("/imports/{import_id}/commit")
def commit(import_id: int, db: Session = Depends(get_db), user: User = Depends(CIRCUITS_MANAGE)):
    imp = db.get(CircuitImport, import_id) or _not_found()
    if imp.status != PENDING:
        raise HTTPException(409, "Only a pending import can be committed")
    for old in db.scalars(select(CircuitImport).where(CircuitImport.status == ACTIVE)):
        old.status = SUPERSEDED
    imp.status, imp.committed_by, imp.committed_at = ACTIVE, user.username, utcnow()
    d = json.loads(imp.summary or "{}").get("diff", {})
    audit(db, user.username, "circuits.import.commit",
          f"{imp.filename}: {imp.row_count} rows (+{d.get('added', 0)} "
          f"~{d.get('changed', 0)} -{d.get('removed', 0)})")
    return _import_out(imp)


@router.delete("/imports/{import_id}", status_code=204)
def discard(import_id: int, db: Session = Depends(get_db), user: User = Depends(CIRCUITS_MANAGE)):
    imp = db.get(CircuitImport, import_id) or _not_found()
    if imp.status != PENDING:
        raise HTTPException(409, "Only a pending import can be discarded; "
                                 "earlier versions are kept as history")
    db.execute(delete(Circuit).where(Circuit.import_id == imp.id))
    db.delete(imp)
    audit(db, user.username, "circuits.import.discard", imp.filename)
    return Response(status_code=204)


def _not_found():
    raise HTTPException(404, "Import not found")
