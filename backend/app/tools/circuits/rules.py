"""Rules per type of circuit: what to check and email for, say, every CCTV camera.

A rule applies to the rows of the circuit list whose Device Type (or Service) is its value,
or to every row when the value is empty. It can:

* email when one of those circuits **moves** (found on another switch port than the list says);
* email when one is **not seen** on the network for a number of hours;
* check the **VLAN** it is on: one of the rule's VLANs, or the row's own VLAN column, and
  email when it is on another.

Everything is worked out from the stored MAC/ARP tables (no device is contacted here), so
the checks are as fresh as the last network scan. The emails (``core/alerts._circuits``) are
checked once after each scan, and each problem is emailed once.
"""

import re
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.auth import User, require
from app.core.db import get_db, utcnow
from app.tools.circuits import live
from app.tools.circuits.models import CircuitRule

router = APIRouter(prefix="/api/circuits/rules", tags=["circuits"])

VIEW = require("circuits", "view")
MANAGE = require("circuits", "manage")

FIELDS = {"device_type": "Device type", "service": "Service"}
LOCATED = (live.MATCHES, live.MOVED, live.FOUND)
_VLAN = re.compile(r"^[\w.-]{1,64}$")


def parse_vlans(text: str) -> set[str]:
    """'10, 20-22 users' -> {'10', '20', '21', '22', 'users'} (lower case: Junos VLANs are
    names). Raises ValueError on anything else."""
    out: set[str] = set()
    for tok in re.split(r"[,;\s]+", (text or "").strip()):
        if not tok:
            continue
        m = re.fullmatch(r"(\d{1,4})-(\d{1,4})", tok)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if a > b or b - a > 4094:
                raise ValueError(f"'{tok}' is not a VLAN range")
            out.update(str(v) for v in range(a, b + 1))
        elif _VLAN.match(tok):
            out.add(str(int(tok)) if tok.isdigit() else tok.lower())
        else:
            raise ValueError(f"'{tok}' is not a VLAN")
    return out


def _vlan(text) -> str:
    t = str(text or "").strip()
    return str(int(t)) if t.isdigit() else t.lower()


def label(r: CircuitRule) -> str:
    return f"{FIELDS.get(r.field, r.field)} {r.value}" if r.value else "Every circuit"


class RuleSet:
    def __init__(self, rules: list[CircuitRule]):
        self.rules = rules

    @classmethod
    def load(cls, db: Session) -> "RuleSet":
        return cls(list(db.scalars(select(CircuitRule).order_by(CircuitRule.id))))

    def matching(self, row: dict) -> list[CircuitRule]:
        return [r for r in self.rules
                if not r.value or str(row.get(r.field) or "").strip().lower() == r.value.lower()]

    def vlan_problem(self, row: dict, rules: list[CircuitRule] | None = None) -> str:
        """'' when fine (or not checked or not located); else what is wrong."""
        rules = self.matching(row) if rules is None else rules
        checks = [r for r in rules if r.check_vlan]
        if not checks or row.get("live_status") not in LOCATED or not row.get("live_vlan"):
            return ""
        expected: set[str] = set()
        for r in checks:
            if r.vlans:
                expected |= parse_vlans(r.vlans)
            elif row.get("vlan"):
                expected.add(_vlan(row["vlan"]))
        if not expected or _vlan(row["live_vlan"]) in expected:
            return ""
        shown = sorted(expected, key=lambda v: (not v.isdigit(), int(v) if v.isdigit() else 0, v))
        more = "…" if len(shown) > 6 else ""
        return f"On VLAN {row['live_vlan']}, expected {', '.join(shown[:6])}{more}"

    def annotate(self, rows: list[dict]) -> None:
        """Adds rule_problems (list of text) to each row of the circuit list."""
        if not self.rules:
            for row in rows:
                row["rule_problems"] = []
            return
        for row in rows:
            v = self.vlan_problem(row)
            row["rule_problems"] = [v] if v else []


def _ident(row: dict) -> str:
    """What a circuit is known by across uploads: its MAC, else its IP, else its name."""
    if row.get("live_mac"):
        return row["live_mac"]
    if (row.get("ip") or "").strip():
        return "ip:" + row["ip"].strip()
    return "name:" + (row.get("device_name") or str(row.get("id"))).strip().lower()


def _who(row: dict) -> str:
    name = row.get("device_name") or row.get("live_mac") or row.get("ip") or f"row {row.get('row_no')}"
    kind = row.get("device_type") or row.get("service")
    return f"{name}{f' ({kind})' if kind else ''}"


def _fmt(t) -> str:
    return f"{t:%Y-%m-%d %H:%M} UTC" if t else ""


def problems(db: Session, now: datetime | None = None) -> list[tuple[str, str, str]]:
    """What the rules say to email about, from the last scan: (key, kind, line). kind is
    moved, missing or vlan; the key changes when the problem does (another port, seen and
    lost again, another VLAN), so each one is emailed once."""
    from app.tools.circuits.api import _export_rows

    rules = RuleSet.load(db)
    if not any(r.email_moved or r.email_missing or r.email_vlan for r in rules.rules):
        return []
    now = now or utcnow()
    out = []
    for row in _export_rows(db):
        if not row.get("live_status"):
            continue  # never scanned
        matched = rules.matching(row)
        if not matched:
            continue
        ident, st = _ident(row), row["live_status"]
        if st == live.MOVED and any(r.email_moved for r in matched):
            where = f"{row['live_switch'] or '?'} {row['live_port']}"
            out.append((f"ctm:{ident}:{row['live_device_id']}:{row['live_port'].lower()}", "moved",
                        f"  {_who(row)}: MOVED to {where} (the list says {row['switch']} {row['port']})"))
        if st == live.NOT_SEEN:
            hours = [r.missing_hours for r in matched if r.email_missing]
            last = row.get("last_seen_at")
            if hours and (last is None or now - last >= timedelta(hours=min(hours))):
                seen = f"last seen {_fmt(last)} on {row['last_seen_where']}" if last else "never seen"
                out.append((f"ctx:{ident}:{last.isoformat() if last else 'never'}", "missing",
                            f"  {_who(row)}: NOT SEEN, {seen} (the list says {row['switch']} {row['port']})"))
        flagged = [r for r in matched if r.email_vlan]
        if flagged:
            v = rules.vlan_problem(row, matched)
            if v:
                out.append((f"ctv:{ident}:{row['live_device_id']}:{row['live_port'].lower()}:"
                            f"{_vlan(row['live_vlan'])}", "vlan",
                            f"  {_who(row)}: WRONG VLAN on {row['live_switch']} {row['live_port']}: {v}"))
    return out


# --- API -------------------------------------------------------------------------------------

class RuleIn(BaseModel):
    field: str = Field("device_type", pattern="^(device_type|service)$")
    value: str = Field("", max_length=255)
    email_moved: bool = False
    email_missing: bool = False
    missing_hours: int = Field(12, ge=1, le=720)
    check_vlan: bool = False
    vlans: str = Field("", max_length=255)
    email_vlan: bool = False


def _out(r: CircuitRule, counts: dict[int, list[int]] | None = None) -> dict:
    n, bad = (counts or {}).get(r.id, [0, 0])
    return {"id": r.id, "field": r.field, "value": r.value, "label": label(r),
            "email_moved": r.email_moved, "email_missing": r.email_missing,
            "missing_hours": r.missing_hours, "check_vlan": r.check_vlan, "vlans": r.vlans,
            "email_vlan": r.email_vlan, "updated_at": r.updated_at, "updated_by": r.updated_by,
            "circuits": n, "wrong_vlan": bad}


@router.get("")
def list_rules(db: Session = Depends(get_db), _: User = Depends(VIEW)):
    from app.tools.circuits.api import _export_rows

    rules = RuleSet.load(db)
    rows = _export_rows(db)
    counts: dict[int, list[int]] = {r.id: [0, 0] for r in rules.rules}
    types: dict[str, set[str]] = {f: set() for f in FIELDS}
    for row in rows:
        for f in FIELDS:
            if (row.get(f) or "").strip():
                types[f].add(row[f].strip())
        for r in rules.matching(row):
            counts[r.id][0] += 1
            if r.check_vlan and rules.vlan_problem(row, [r]):
                counts[r.id][1] += 1
    return {"rules": [_out(r, counts) for r in rules.rules], "fields": FIELDS,
            "types": {f: sorted(v, key=str.lower) for f, v in types.items()}}


def _apply(db: Session, r: CircuitRule, body: RuleIn, user: User) -> None:
    value = body.value.strip()
    try:
        parse_vlans(body.vlans)
    except ValueError as exc:
        raise HTTPException(422, f"VLANs: {exc}. Use numbers, ranges such as 20-22, or names.")
    if body.vlans.strip() and not body.check_vlan:
        raise HTTPException(422, "Tick Check the VLAN to use the VLANs.")
    if body.email_vlan and not body.check_vlan:
        raise HTTPException(422, "Tick Check the VLAN to email about it.")
    for other in db.scalars(select(CircuitRule).where(CircuitRule.id != (r.id or 0))):
        if other.value.lower() == value.lower() and (other.field == body.field or not value):
            raise HTTPException(409, f"There is already a rule for {label(other).lower()}.")
    r.field, r.value = body.field, value
    r.email_moved, r.email_missing, r.missing_hours = body.email_moved, body.email_missing, body.missing_hours
    r.check_vlan, r.vlans, r.email_vlan = body.check_vlan, body.vlans.strip(), body.email_vlan
    r.updated_at, r.updated_by = utcnow(), user.username
    _recheck(db)


def _recheck(db: Session) -> None:
    """Check the rules against the last scan again at the next alert check."""
    from app.core import appsettings
    from app.core.alerts import CIRCUITS_SCAN

    appsettings.save(db, {CIRCUITS_SCAN: ""}, "system")


def _summary(r: CircuitRule) -> str:
    parts = [label(r)]
    if r.email_moved:
        parts.append("email moved")
    if r.email_missing:
        parts.append(f"email not seen for {r.missing_hours} h")
    if r.check_vlan:
        parts.append(f"VLAN {r.vlans or 'from the list'}" + (" (emailed)" if r.email_vlan else ""))
    return ", ".join(parts)


@router.post("", status_code=201)
def add_rule(body: RuleIn, db: Session = Depends(get_db), user: User = Depends(MANAGE)):
    r = CircuitRule()
    _apply(db, r, body, user)
    db.add(r)
    db.flush()
    audit(db, user.username, "circuits.rule.add", _summary(r))
    return _out(r)


def _get(db: Session, rule_id: int) -> CircuitRule:
    r = db.get(CircuitRule, rule_id)
    if r is None:
        raise HTTPException(404, "No such rule")
    return r


@router.put("/{rule_id:int}")
def change_rule(rule_id: int, body: RuleIn, db: Session = Depends(get_db),
                user: User = Depends(MANAGE)):
    r = _get(db, rule_id)
    _apply(db, r, body, user)
    audit(db, user.username, "circuits.rule.change", _summary(r))
    return _out(r)


@router.delete("/{rule_id:int}", status_code=204)
def delete_rule(rule_id: int, db: Session = Depends(get_db), user: User = Depends(MANAGE)):
    r = _get(db, rule_id)
    audit(db, user.username, "circuits.rule.delete", label(r))
    db.delete(r)
