"""Config compliance: rules every backed-up config is checked against.

A rule lists config lines that **must** be in the config (every one of them), or that
**must not** be (any one fails it). Lines are matched as text (ignoring spaces at either
end) or, for a regex rule, as patterns searched in each config line. A rule can be limited
to platforms and sites. Each device's latest config is checked after every successful
backup, and again when the rules change or someone clicks Check now; each device keeps its
latest result per rule (``compliance_results``), and when it started failing.

Results say pass or fail to anyone who can see backups; the config lines in a result
(missing or offending) only to those who may read configs, because configs hold secrets.
Part of the Config backups licence.
"""

import io
import json
import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from pydantic import Field as PField
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core import exports, licence
from app.core.audit import audit
from app.core.auth import User, require
from app.core.db import get_db, utcnow
from app.core.models import Device
from app.core.platforms import PLATFORMS
from app.tools.config_backup.models import BackupState, ComplianceResult, ComplianceRule

router = APIRouter(prefix="/api/compliance", tags=["compliance"],
                   dependencies=[Depends(licence.module("backups"))])
VIEW = require("backups", "view")
MANAGE = require("backups", "manage")
KINDS = ("must", "must_not")
SEVERITIES = ("critical", "warning")
MAX_DETAIL = 20  # config lines kept per result

# Starting points an admin can add with one click (Cisco IOS / IOS-XE).
EXAMPLES = [
    {"name": "NTP server set", "kind": "must", "regex": True, "lines": r"^ntp server ",
     "platforms": ["cisco_ios"], "severity": "warning",
     "description": "Every switch takes its time from NTP, so logs line up."},
    {"name": "Syslog to a server", "kind": "must", "regex": True, "lines": r"^logging host ",
     "platforms": ["cisco_ios"], "severity": "warning",
     "description": "Messages go to the syslog server."},
    {"name": "SSH version 2", "kind": "must", "regex": False, "lines": "ip ssh version 2",
     "platforms": ["cisco_ios"], "severity": "critical", "description": ""},
    {"name": "No Telnet", "kind": "must_not", "regex": True,
     "lines": r"transport input (telnet|all)", "platforms": ["cisco_ios"],
     "severity": "critical", "description": "Management by SSH only."},
    {"name": "No HTTP server", "kind": "must_not", "regex": True, "lines": r"^ip http server",
     "platforms": ["cisco_ios"], "severity": "warning",
     "description": "The plain web interface is off (ip http secure-server is allowed)."},
    {"name": "Passwords encrypted", "kind": "must", "regex": False,
     "lines": "service password-encryption", "platforms": ["cisco_ios"], "severity": "warning",
     "description": ""},
    {"name": "AAA", "kind": "must", "regex": False, "lines": "aaa new-model",
     "platforms": ["cisco_ios"], "severity": "warning", "description": ""},
    {"name": "No default SNMP communities", "kind": "must_not", "regex": True,
     "lines": r"snmp-server community (public|private)\b", "platforms": ["cisco_ios"],
     "severity": "critical", "description": ""},
]


# --- checking -------------------------------------------------------------------------------

def _wanted(rule: ComplianceRule) -> list[str]:
    return [ln.strip() for ln in rule.lines.splitlines() if ln.strip()]


def applies(rule: ComplianceRule, device: Device) -> bool:
    platforms = json.loads(rule.platforms or "[]")
    sites = {s.lower() for s in json.loads(rule.sites or "[]")}
    return rule.enabled and (not platforms or device.platform in platforms) and \
        (not sites or device.site.strip().lower() in sites)


def evaluate(rule: ComplianceRule, config: str) -> tuple[bool, list[str]]:
    """(passed, config lines that are missing (must) or offending (must not))."""
    lines = [ln.rstrip() for ln in config.splitlines()]
    stripped = [ln.strip() for ln in lines]
    found = []
    for want in _wanted(rule):
        if rule.regex:
            pattern = re.compile(want)
            hits = [ln for ln in lines if pattern.search(ln)]
        else:
            hits = [ln for ln, s in zip(lines, stripped) if s == want]
        if rule.kind == "must" and not hits:
            found.append(want)
        elif rule.kind == "must_not":
            found.extend(hits)
    return not found, found[:MAX_DETAIL]


def check_device(db: Session, device: Device, config: str, rules: list | None = None) -> int:
    """Check one config against the rules; store the results. Returns how many fail."""
    rules = rules if rules is not None else list(db.scalars(select(ComplianceRule)))
    now = utcnow()
    current = {r.rule_id: r for r in db.scalars(
        select(ComplianceResult).where(ComplianceResult.device_id == device.id))}
    failing = 0
    for rule in rules:
        old = current.pop(rule.id, None)
        if not applies(rule, device):
            if old is not None:
                db.delete(old)
            continue
        try:
            passed, detail = evaluate(rule, config)
        except re.error as exc:
            passed, detail = False, [f"(the rule's pattern is not valid: {exc})"]
        failing += not passed
        if old is None:
            db.add(ComplianceResult(device_id=device.id, rule_id=rule.id, passed=passed,
                                    detail="\n".join(detail), checked_at=now,
                                    failing_since=None if passed else now))
        else:
            if not passed and (old.passed or old.failing_since is None):
                old.failing_since = now
            if passed:
                old.failing_since = None
            old.passed, old.detail, old.checked_at = passed, "\n".join(detail), now
    for gone in current.values():  # results of rules that no longer exist
        db.delete(gone)
    return failing


def check_all(db: Session, store) -> int:
    """Check every device's latest stored config. Returns how many devices were checked."""
    rules = list(db.scalars(select(ComplianceRule)))
    n = 0
    for device, state in db.execute(select(Device, BackupState)
                                    .join(BackupState, BackupState.device_id == Device.id)
                                    .where(BackupState.config_path.is_not(None))):
        try:
            config = store.read(state.config_path)
        except (FileNotFoundError, ValueError):
            continue
        check_device(db, device, config, rules)
        n += 1
    return n


# --- API ---------------------------------------------------------------------------------------

def _can_read_lines(request: Request, user: User) -> bool:
    return user.can("backups", "configs") or (
        request.app.state.settings.viewers_can_read_configs and user.can("backups", "view"))


def _rule_out(r: ComplianceRule) -> dict:
    return {"id": r.id, "name": r.name, "description": r.description, "kind": r.kind,
            "lines": r.lines, "regex": r.regex, "platforms": json.loads(r.platforms or "[]"),
            "sites": json.loads(r.sites or "[]"), "severity": r.severity, "enabled": r.enabled,
            "updated_at": r.updated_at, "updated_by": r.updated_by}


@router.get("")
def overview(request: Request, db: Session = Depends(get_db), user: User = Depends(VIEW)):
    """The rules, and every device's result for each rule."""
    rules = list(db.scalars(select(ComplianceRule).order_by(ComplianceRule.name)))
    lines = _can_read_lines(request, user)
    devices = {d.id: d for d in db.scalars(select(Device))}
    results = []
    for r in db.scalars(select(ComplianceResult)):
        d = devices.get(r.device_id)
        if d is None:
            continue
        results.append({"device_id": d.id, "device": d.name, "site": d.site, "rule_id": r.rule_id,
                        "passed": r.passed, "checked_at": r.checked_at,
                        "failing_since": r.failing_since,
                        "detail": r.detail if lines else None})
    return {"rules": [_rule_out(r) for r in rules], "results": results,
            "can_manage": user.can("backups", "manage"), "can_read_lines": lines,
            "platforms": {k: p.label for k, p in PLATFORMS.items()}}


@router.get("/device/{device_id}")
def for_device(device_id: int, request: Request, db: Session = Depends(get_db),
               user: User = Depends(VIEW)):
    lines = _can_read_lines(request, user)
    rules = {r.id: r for r in db.scalars(select(ComplianceRule))}
    out = []
    for r in db.scalars(select(ComplianceResult).where(ComplianceResult.device_id == device_id)):
        rule = rules.get(r.rule_id)
        if rule:
            out.append({"rule_id": rule.id, "rule": rule.name, "severity": rule.severity,
                        "kind": rule.kind, "passed": r.passed, "checked_at": r.checked_at,
                        "failing_since": r.failing_since, "detail": r.detail if lines else None})
    return sorted(out, key=lambda x: (x["passed"], x["severity"] != "critical", x["rule"].lower()))


class RuleIn(BaseModel):
    name: str = PField(min_length=1, max_length=100)
    description: str = PField("", max_length=2000)
    kind: str = "must"
    lines: str = PField(min_length=1, max_length=5000)
    regex: bool = False
    platforms: list[str] = PField(default_factory=list, max_length=50)
    sites: list[str] = PField(default_factory=list, max_length=200)
    severity: str = "warning"
    enabled: bool = True


def _check_rule(body: RuleIn) -> None:
    if body.kind not in KINDS:
        raise HTTPException(422, "Kind: must or must_not")
    if body.severity not in SEVERITIES:
        raise HTTPException(422, "Severity: critical or warning")
    if bad := [p for p in body.platforms if p not in PLATFORMS]:
        raise HTTPException(422, f"Unknown platform: {', '.join(bad)}")
    lines = [ln.strip() for ln in body.lines.splitlines() if ln.strip()]
    if not lines:
        raise HTTPException(422, "Give at least one config line")
    if body.regex:
        for ln in lines:
            if len(ln) > 300:
                raise HTTPException(422, "A pattern can be at most 300 characters")
            try:
                re.compile(ln)
            except re.error as exc:
                raise HTTPException(422, f"Not a valid pattern: {ln} ({exc})") from None


def _store(request: Request):
    from app.tools.config_backup.storage import GitConfigStore

    return GitConfigStore(request.app.state.settings.configs_dir)


def _apply(rule: ComplianceRule, body: RuleIn, user: User) -> None:
    rule.name, rule.description, rule.kind = body.name.strip(), body.description, body.kind
    rule.lines = "\n".join(ln.strip() for ln in body.lines.splitlines() if ln.strip())
    rule.regex, rule.severity, rule.enabled = body.regex, body.severity, body.enabled
    rule.platforms = json.dumps(sorted(set(body.platforms)))
    rule.sites = json.dumps(sorted({s.strip() for s in body.sites if s.strip()}))
    rule.updated_by = user.username


@router.post("/rules", status_code=201)
def add_rule(body: RuleIn, request: Request, db: Session = Depends(get_db),
             user: User = Depends(MANAGE)):
    _check_rule(body)
    rule = ComplianceRule()
    _apply(rule, body, user)
    db.add(rule)
    db.flush()
    check_all(db, _store(request))
    audit(db, user.username, "compliance.rule_add", f"{rule.name} ({rule.kind})")
    return {"id": rule.id}


@router.put("/rules/{rule_id}")
def change_rule(rule_id: int, body: RuleIn, request: Request, db: Session = Depends(get_db),
                user: User = Depends(MANAGE)):
    rule = db.get(ComplianceRule, rule_id)
    if rule is None:
        raise HTTPException(404, "No such rule")
    _check_rule(body)
    _apply(rule, body, user)
    db.flush()
    check_all(db, _store(request))
    audit(db, user.username, "compliance.rule_change", rule.name)
    return {"id": rule.id}


@router.delete("/rules/{rule_id}", status_code=204)
def delete_rule(rule_id: int, db: Session = Depends(get_db), user: User = Depends(MANAGE)):
    rule = db.get(ComplianceRule, rule_id)
    if rule is None:
        raise HTTPException(404, "No such rule")
    db.execute(delete(ComplianceResult).where(ComplianceResult.rule_id == rule.id))
    db.delete(rule)
    audit(db, user.username, "compliance.rule_delete", rule.name)
    return Response(status_code=204)


@router.post("/examples")
def add_examples(request: Request, db: Session = Depends(get_db), user: User = Depends(MANAGE)):
    """Add the example rules that aren't there yet (by name)."""
    have = {n.lower() for n in db.scalars(select(ComplianceRule.name))}
    added = []
    for ex in EXAMPLES:
        if ex["name"].lower() in have:
            continue
        rule = ComplianceRule()
        _apply(rule, RuleIn(**ex), user)
        db.add(rule)
        added.append(ex["name"])
    db.flush()
    check_all(db, _store(request))
    if added:
        audit(db, user.username, "compliance.rule_add", "examples: " + ", ".join(added))
    return {"added": added}


@router.post("/check")
def check_now(request: Request, db: Session = Depends(get_db),
              user: User = Depends(require("backups", "run"))):
    """Check every device's latest stored config again (no device is contacted)."""
    n = check_all(db, _store(request))
    audit(db, user.username, "compliance.check", f"{n} devices")
    return {"checked": n}


@router.get("/export.csv")
def export_csv(request: Request, db: Session = Depends(get_db), user: User = Depends(VIEW)):
    data = overview(request, db, user)
    rules = {r["id"]: r for r in data["rules"]}
    out = io.StringIO()
    w = exports.csv_writer(out)
    head = ["Device", "Site", "Rule", "Severity", "Result", "Failing since", "Checked"]
    w.writerow(head + (["Config lines"] if data["can_read_lines"] else []))
    for r in sorted(data["results"], key=lambda x: (x["device"].lower(), rules[x["rule_id"]]["name"])):
        rule = rules[r["rule_id"]]
        row = [r["device"], r["site"], rule["name"], rule["severity"],
               "pass" if r["passed"] else "FAIL",
               f"{r['failing_since']:%Y-%m-%d %H:%M}" if r["failing_since"] else "",
               f"{r['checked_at']:%Y-%m-%d %H:%M}"]
        w.writerow(row + ([(r["detail"] or "").replace("\n", " | ")] if data["can_read_lines"] else []))
    return Response(out.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="compliance.csv"'})

