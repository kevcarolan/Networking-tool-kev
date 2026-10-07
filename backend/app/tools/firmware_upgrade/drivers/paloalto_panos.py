"""Palo Alto PAN-OS, through the XML API (certificate pinned, like FDM).

Standalone: upload the image, install it (a job on the firewall), restart, post-checks.
HA pair (active/passive): the passive unit first - suspend it, upgrade, restart, make it
  functional again and check the pair; then the active unit (suspending it fails the
  pair over to the upgraded unit), and the pair is checked again at the end.
Roll back: install the previous version (still on the firewall) and restart.

PAN-OS needs the base release of a feature version (e.g. 10.2.0) on the firewall before
a maintenance release of it (10.2.8); the pre-check says when it is missing.
"""

import re

from app.core.ssh import DeviceError
from app.tools.firmware_upgrade import checks as ck
from app.tools.firmware_upgrade.drivers.base import Step, StepFailed, Unit, UpgradeDriver, UpgradePath


def base_release(version: str) -> str:
    """'10.2.8-h3' -> '10.2.0'."""
    m = re.match(r"(\d+)\.(\d+)", version or "")
    return f"{m.group(1)}.{m.group(2)}.0" if m else ""


def ha_pair(out: str) -> dict:
    """'show high-availability state': this unit's and the peer's state."""
    local = re.search(r"Local Information:.*?^\s*State:\s*(\S+)", out or "", re.M | re.S)
    peer = re.search(r"Peer Information:.*?^\s*State:\s*(\S+)", out or "", re.M | re.S)
    conn = re.search(r"Connection status:\s*(\S+)", out or "")
    return {"local": local.group(1).lower() if local else "",
            "peer": peer.group(1).lower() if peer else "",
            "connection": conn.group(1).lower() if conn else ""}


def pair_healthy(h: dict) -> bool:
    return h["connection"] == "up" and {h["local"], h["peer"]} == {"active", "passive"}


class PaloaltoPanosDriver(UpgradeDriver):
    platform = "paloalto_panos"
    default_fs = ""
    paths = [
        UpgradePath("standalone", "Standalone firewall", 1, "Upload, install, restart"),
        UpgradePath("ha_pair", "HA pair (passive first)", 2,
                    "Upgrade the passive unit, then the active one (it fails over first)"),
    ]

    def extra_commands(self, unit, image):
        return {"fw:ha": "show high-availability state"}

    def extra_prechecks(self, ctx, unit: Unit, outputs, path):
        label = "PAN-OS API reachable, certificate trusted, account accepted"
        try:
            known = {s["version"]: s for s in ctx.api(unit).software_info()}
        except (DeviceError, StepFailed) as exc:
            return [ck.CheckResult("api", label, ck.BLOCKER, ck.FAIL, "", str(exc))]
        current = unit.facts.get("version") or ""
        unit.running_image = current
        results = [ck.CheckResult("api", label, ck.BLOCKER, ck.PASS, f"running {current or '?'}")]
        target = ctx.image.version
        unit.image_present = known.get(target, {}).get("downloaded", False)
        results.append(ck.CheckResult(
            "image_on_device", "Image already on the firewall", ck.INFO, ck.PASS,
            "yes" if unit.image_present else "no - uploaded at Stage image or Start"))
        base = base_release(target)
        need_base = base and base != target and base_release(current) != base
        base_ok = not need_base or known.get(base, {}).get("downloaded", False)
        results.append(ck.CheckResult(
            "base_release", "Base release on the firewall (for a maintenance release)",
            ck.BLOCKER, ck.PASS if base_ok else ck.FAIL,
            "not needed" if not need_base else (f"{base} downloaded" if base_ok else f"{base} missing"),
            "" if base_ok else f"Download {base} on the firewall (Device > Software) first; "
                               "it doesn't need to be installed"))
        previous_ok = current in known
        results.append(ck.CheckResult(
            "previous_image", "Current version kept for roll back", ck.BLOCKER,
            ck.PASS if previous_ok else ck.FAIL, current or "unknown",
            "" if previous_ok else "The running version isn't in 'request system software info'"))
        h = ha_pair(outputs.get("fw:ha") or "")
        unit.role = h["local"] or "standalone"
        if path.units == 2:
            results.append(ck.CheckResult(
                "panos_ha", "HA pair healthy (one active, one passive)", ck.BLOCKER,
                ck.PASS if pair_healthy(h) else ck.FAIL,
                f"this: {h['local'] or '?'}; peer: {h['peer'] or '?'}; link {h['connection'] or '?'}"))
        elif h["local"]:
            results.append(ck.CheckResult(
                "standalone", "Not part of an HA pair", ck.BLOCKER, ck.FAIL, h["local"],
                "This firewall is in an HA pair: use the HA pair path"))
        return results

    def pair_checks(self, ctx, units, path):
        roles = sorted(u.role for u in units)
        ok = roles == ["active", "passive"]
        return [ck.CheckResult("pair_roles", "One active and one passive unit", ck.BLOCKER,
                               ck.PASS if ok else ck.FAIL,
                               ", ".join(f"{u.name}: {u.role or '?'}" for u in units))]

    def order_units(self, units):
        return sorted(units, key=lambda u: 0 if u.role == "passive" else 1)

    # --- the procedure ---------------------------------------------------------------

    def unit_steps(self, ctx, u):
        d = u.device_id
        pair = ctx.path.units == 2
        return [
            Step(f"backup_before:{d}", "backup", f"{u.name}: config backup before", d,
                 args={"label": "before"}),
            Step(f"stage:{d}", "stage", f"{u.name}: upload the image", d),
            *([Step(f"suspend:{d}", "ha_state", f"{u.name}: suspend HA (the peer carries the "
                    "traffic)", d, reload=True, args={"state": "suspend"})] if pair else []),
            Step(f"install:{d}", "install", f"{u.name}: install {ctx.image.version}", d),
            Step(f"restart:{d}", "restart", f"{u.name}: restart", d, reload=True),
            Step(f"wait:{d}", "wait", f"{u.name}: wait for the firewall to come back", d),
            *([Step(f"functional:{d}", "ha_state", f"{u.name}: make HA functional again", d,
                    args={"state": "functional"})] if pair else []),
            Step(f"postcheck:{d}", "postcheck", f"{u.name}: post-checks", d, gate=True),
            Step(f"backup_after:{d}", "backup", f"{u.name}: config backup after", d,
                 args={"label": "after"}),
        ]

    def upgrade_plan(self, ctx, path, units):
        if path.units == 1:
            return self.unit_steps(ctx, units[0])
        first, second = units  # passive first
        return [*self.unit_steps(ctx, first),
                Step(f"ha_check:{first.device_id}", "ha_check", "HA pair healthy with the "
                     "upgraded unit", first.device_id),
                *self.unit_steps(ctx, second),
                Step(f"ha_check_end:{first.device_id}", "ha_check", "HA pair healthy on the new "
                     "version", first.device_id)]

    def rollback_steps(self, ctx, u):
        d = u.device_id
        return [Step(f"rb_install:{d}", "install", f"{u.name}: install {u.from_version}", d,
                     args={"previous": True}),
                Step(f"rb_restart:{d}", "restart", f"{u.name}: restart", d, reload=True)]

    # --- steps -----------------------------------------------------------------------

    def _downloaded(self, ctx, u, version: str) -> bool:
        return any(s["version"] == version and s["downloaded"]
                   for s in ctx.api(u).software_info())

    def step_stage(self, ctx, step, u):
        if u.staged or (not ctx.dry_run and self._downloaded(ctx, u, ctx.image.version)):
            u.staged = True
            ctx.record_checks(u, "stage", [ck.CheckResult(
                "device_package", "Image on the firewall", ck.BLOCKER, ck.PASS,
                ctx.image.version, "already uploaded")])
            return
        ctx.api_change(u, f"upload {ctx.image.filename} ({ctx.image.size // 2**20} MB)",
                       lambda api: api.upload(ctx.image.path))
        if ctx.dry_run:
            ctx.record_checks(u, "stage", [ck.CheckResult(
                "device_package", "Image on the firewall", ck.BLOCKER, ck.SKIP,
                ctx.image.version, "DRY RUN: would upload the image")])
            return
        ok = self._downloaded(ctx, u, ctx.image.version)
        ctx.record_checks(u, "stage", [ck.CheckResult(
            "device_package", "Image on the firewall", ck.BLOCKER, ck.PASS if ok else ck.FAIL,
            ctx.image.version, "" if ok else "The firewall doesn't list the version after the upload")])
        if not ok:
            raise StepFailed(f"{u.name} doesn't list {ctx.image.version} after the upload")
        u.staged = True

    def step_install(self, ctx, step, u):
        version = u.from_version if step.args.get("previous") else ctx.image.version
        job = ctx.api_change(u, f"install {version}", lambda api: api.install(version))
        if ctx.dry_run:
            return
        last = {}

        def finished() -> bool:
            last.update(ctx.api(u).job(job))
            return (last.get("status") or "").upper() == "FIN"

        if not ctx.poll(finished, minutes=60, what=f"the install of {version}"):
            raise StepFailed(f"Installing {version} on {u.name} didn't finish within 60 minutes",
                             attention=True)
        if (last.get("result") or "").upper() != "OK":
            raise StepFailed(f"Installing {version} on {u.name} failed: {last.get('details')}")
        ctx.event(f"{version} installed on {u.name} - active after the restart", step.kind,
                  device_id=u.device_id)

    def step_restart(self, ctx, step, u):
        u.status = "activated"
        ctx.api_change(u, "restart", lambda api: api.restart())
        ctx.forget_fdm(u)

    def step_ha_state(self, ctx, step, u):
        state = step.args["state"]
        ctx.api_change(u, f"set HA state {state}", lambda api: api.ha_state(state))

    def step_ha_check(self, ctx, step, u):
        if ctx.dry_run:
            ctx.event("DRY RUN - would check the HA pair is healthy", step.kind, "action",
                      u.device_id)
            return
        h = {}

        def healthy() -> bool:
            h.update(ha_pair(ctx.show(u, ["show high-availability state"])[0]))
            return pair_healthy(h)

        if not ctx.poll(healthy, minutes=15, what="the HA pair"):
            raise StepFailed(f"HA pair not healthy: this {h.get('local')}, peer {h.get('peer')}, "
                             f"link {h.get('connection')}")
        ctx.event("HA pair healthy", step.kind, device_id=u.device_id)
