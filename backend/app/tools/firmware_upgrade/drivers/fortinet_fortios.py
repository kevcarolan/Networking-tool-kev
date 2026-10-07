"""Fortinet FortiGate (FortiOS).

FortiOS can't receive a file over SSH, so the image is sent through the REST API
(certificate pinned, like FDM); FortiOS checks it, writes it to the partition it is
not running from, and reboots onto it. Everything else runs over SSH.

Standalone: send the image, wait for the reboot, post-checks.
  Roll back: execute set-next-reboot <previous partition>, execute reboot.
HA cluster (one NetOps device: the cluster's management address): send the image to
  the primary; with uninterruptible-upgrade the cluster upgrades the secondaries first,
  fails over and upgrades the old primary, so the address stays up. The job waits until
  the cluster reports the new version and HA is healthy. Roll back: by hand.
"""

import re

from app.core.ssh import DeviceError
from app.tools.firmware_upgrade import checks as ck
from app.tools.firmware_upgrade.drivers.base import Step, StepFailed, Unit, UpgradeDriver, UpgradePath
from app.tools.firmware_upgrade.drivers.common import check_output
from app.tools.firmware_upgrade.facts import compare_versions, parse_facts


def flash_partitions(out: str) -> dict[str, tuple[str, bool]]:
    """'diagnose sys flash list': partition -> (image, active).
        1          FGT60F-7.02-FW-build1517-230606       253920    164104   65%  Yes"""
    return {m.group(1): (m.group(2), m.group(3).lower() == "yes") for m in re.finditer(
        r"^\s*([12])\s+(\S+)\s+\d+\s+\d+\s+\d+%\s+(Yes|No)\s*$", out or "", re.M | re.I)}


def ha_status(out: str) -> dict:
    """'get system ha status': mode and health."""
    mode = re.search(r"^Mode:\s*(.+)$", out or "", re.M)
    health = re.search(r"^HA Health Status:\s*(\S+)", out or "", re.M)
    return {"mode": mode.group(1).strip() if mode else "",
            "health": health.group(1).strip() if health else ""}


class FortinetFortiosDriver(UpgradeDriver):
    platform = "fortinet_fortios"
    default_fs = ""
    paths = [
        UpgradePath("standalone", "Standalone FortiGate", 1,
                    "Send the image (REST API), FortiOS installs it and reboots"),
        UpgradePath("ha_cluster", "HA cluster (uninterruptible upgrade)", 1,
                    "Send the image to the cluster; it upgrades the secondaries first, "
                    "fails over, then the old primary"),
    ]

    def extra_commands(self, unit, image):
        return {"fw:flash": "diagnose sys flash list", "fw:ha": "get system ha status",
                "fw:ha_cfg": "get system ha | grep uninterruptible-upgrade"}

    def extra_prechecks(self, ctx, unit: Unit, outputs, path):
        results = []
        try:
            status = ctx.api(unit).status()
            results.append(ck.CheckResult(
                "api", "FortiGate API reachable, certificate trusted, account accepted",
                ck.BLOCKER, ck.PASS, f"API reports {status.get('version', '?')}"))
        except (DeviceError, StepFailed) as exc:
            results.append(ck.CheckResult(
                "api", "FortiGate API reachable, certificate trusted, account accepted",
                ck.BLOCKER, ck.FAIL, "", str(exc)))
        parts = flash_partitions(outputs.get("fw:flash") or "")
        active = next((p for p, (_, on) in parts.items() if on), "")
        unit.running_image = {"1": "primary", "2": "secondary"}.get(active, "")
        results.append(ck.CheckResult(
            "previous_image", "Current firmware kept for roll back", ck.BLOCKER,
            ck.PASS if unit.running_image else ck.FAIL,
            f"running from the {unit.running_image} partition" if unit.running_image else "unknown",
            "" if unit.running_image else "'diagnose sys flash list' showed no active partition"))
        ha = ha_status(outputs.get("fw:ha") or "")
        standalone = ha["mode"].lower() in ("", "standalone")
        unit.role = "standalone" if standalone else "cluster"
        if path.id == "ha_cluster":
            healthy = not standalone and ha["health"].upper() == "OK"
            results.append(ck.CheckResult(
                "fortigate_ha", "HA cluster healthy", ck.BLOCKER, ck.PASS if healthy else ck.FAIL,
                f"{ha['mode'] or 'standalone'}, health {ha['health'] or '?'}"))
            hitless = "enable" in (outputs.get("fw:ha_cfg") or "")
            results.append(ck.CheckResult(
                "uninterruptible_upgrade", "uninterruptible-upgrade enabled", ck.WARNING,
                ck.PASS if hitless else ck.FAIL, "enabled" if hitless else "not enabled",
                "" if hitless else "Without it every cluster member reboots at the same time"))
        elif not standalone:
            results.append(ck.CheckResult(
                "standalone", "Not part of an HA cluster", ck.BLOCKER, ck.FAIL, ha["mode"],
                "This FortiGate is in an HA cluster: use the HA cluster path"))
        unit.image_present = False
        return results

    # --- the procedure ---------------------------------------------------------------

    def unit_steps(self, ctx, u):
        d = u.device_id
        cluster = ctx.path.id == "ha_cluster"
        return [
            Step(f"backup_before:{d}", "backup", f"{u.name}: config backup before", d,
                 args={"label": "before"}),
            Step(f"stage:{d}", "stage", f"{u.name}: nothing to stage (the image is sent at the "
                 "upgrade)", d),
            Step(f"upgrade:{d}", "upgrade", f"{u.name}: send the image; FortiOS installs it and "
                 "reboots", d, reload=True),
            Step(f"wait:{d}", "wait_cluster" if cluster else "wait",
                 f"{u.name}: wait for " + ("the cluster to report the new version" if cluster
                                           else "the FortiGate to come back"), d),
            Step(f"postcheck:{d}", "postcheck", f"{u.name}: post-checks", d, gate=True),
            Step(f"backup_after:{d}", "backup", f"{u.name}: config backup after", d,
                 args={"label": "after"}),
        ]

    def rollback_steps(self, ctx, u):
        d = u.device_id
        if ctx.path.id == "ha_cluster":
            return [Step(f"rb:{d}", "manual_rollback", f"{u.name}: roll back the cluster by hand", d)]
        return [Step(f"rb:{d}", "boot_previous", f"{u.name}: boot the previous partition", d,
                     reload=True)]

    def step_stage(self, ctx, step, u):
        ctx.event(f"FortiOS installs an image as soon as it receives it, so {ctx.image.filename} "
                  "is sent at the upgrade step", step.kind, device_id=u.device_id)
        u.staged = True

    def step_upgrade(self, ctx, step, u):
        u.status = "activated"
        ctx.api_change(u, f"send {ctx.image.filename} ({ctx.image.size // 2**20} MB); FortiOS "
                          "installs it and reboots", lambda api: api.upgrade(ctx.image.path))

    def step_wait_cluster(self, ctx, step, u):
        if ctx.dry_run:
            ctx.event(f"DRY RUN - would wait for the cluster to report {ctx.image.version} with "
                      "HA healthy", step.kind, "action", u.device_id)
            return
        seen = {}

        def done() -> bool:
            try:
                status, ha = ctx.show(u, ["get system status", "get system ha status"])
                seen["v"] = parse_facts(self.platform, [status]).version
            except (StepFailed, ValueError):
                return False
            return compare_versions(seen["v"], ctx.image.version) == 0 and \
                ha_status(ha)["health"].upper() == "OK"

        if not ctx.poll(done, minutes=ctx.settings().upgrade_reload_timeout_min * 3,
                        what="the cluster upgrade"):
            raise StepFailed(f"The cluster didn't report {ctx.image.version} with HA healthy in "
                             f"time (last seen: {seen.get('v') or 'no answer'})", attention=True)
        ctx.settle(u)

    def step_boot_previous(self, ctx, step, u):
        out = ctx.change(u, [f"execute set-next-reboot {u.running_image}"])
        check_output(ctx, u, out, "execute set-next-reboot")
        ctx.change(u, ["execute reboot"], expect_reload=True)

    def step_manual_rollback(self, ctx, step, u):
        raise StepFailed(f"Roll back the cluster {u.name} by hand: on each member 'execute "
                         f"set-next-reboot {u.running_image}' and reboot, secondaries first",
                         attention=True)
