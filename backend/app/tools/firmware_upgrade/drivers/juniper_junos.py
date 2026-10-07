"""Juniper Junos (EX, QFX, MX, SRX): one switch, router or firewall, or an EX/QFX
Virtual Chassis (all members are upgraded and reload together).

    copy the package to /var/tmp, file checksum md5
    request system software add /var/tmp/<package> reboot
Roll back: request system software rollback, request system reboot.

Not yet: NSSU (in-service upgrade of a Virtual Chassis) and SRX chassis clusters.
"""

import re

from app.tools.firmware_upgrade import checks as ck
from app.tools.firmware_upgrade.drivers.base import Step, Unit, UpgradePath
from app.tools.firmware_upgrade.drivers.common import SimpleBootDriver, check_output


def vc_members(out: str) -> dict[str, str]:
    """'show virtual-chassis': member id -> status ("Prsnt", "NotPrsnt", ...).
        0 (FPC 0)  Prsnt    XN1234567890 ex4400-48p   128   Master*     N  VC   1  vcp-255/1/0"""
    return dict(re.findall(r"^\s*(\d+)\s+\(FPC\s*\d+\)\s+(\S+)", out or "", re.M))


class JuniperJunosDriver(SimpleBootDriver):
    platform = "juniper_junos"
    default_fs = "/var/tmp/"
    paths = [UpgradePath("standalone", "Standalone or Virtual Chassis", 1,
                         "request system software add ... reboot (a Virtual Chassis "
                         "upgrades and reloads every member together)")]

    def transfer_fs(self, unit):
        return self.file_system(unit).rstrip("/")

    def extra_commands(self, unit, image):
        return {"fw:dir": f"file list {self.file_system(unit)} detail",
                "fw:vc": "show virtual-chassis"}

    def verify_command(self, u, filename):
        return f"file checksum md5 {self.file_system(u)}{filename}"

    def running_image(self, unit, outputs):
        # Junos keeps the previous software for 'request system software rollback'
        return unit.facts.get("version") or ""

    def extra_prechecks(self, ctx, unit: Unit, outputs, path):
        results = super().extra_prechecks(ctx, unit, outputs, path)
        members = vc_members(outputs.get("fw:vc") or "")
        if members:
            bad = {m: st for m, st in members.items() if st.lower() != "prsnt"}
            results.append(ck.CheckResult(
                "virtual_chassis", "All Virtual Chassis members present", ck.BLOCKER,
                ck.FAIL if bad else ck.PASS, f"{len(members)} member(s)",
                "\n".join(f"member {m}: {st}" for m, st in bad.items())))
        return results

    def activate_steps(self, ctx, u):
        d = u.device_id
        return [Step(f"activate:{d}", "software_add", f"{u.name}: request system software add "
                     "... reboot", d, reload=True)]

    def rollback_steps(self, ctx, u):
        d = u.device_id
        return [Step(f"rb:{d}", "software_rollback", f"{u.name}: request system software "
                     "rollback, reboot", d, reload=True)]

    def step_software_add(self, ctx, step, u):
        u.status = "activated"
        out = ctx.change(u, [f"request system software add {self.file_system(u)}"
                             f"{ctx.image.filename} reboot"], expect_reload=True, long=True)
        check_output(ctx, u, out.split("[connection closed")[0], "request system software add",
                     attention=True)

    def step_software_rollback(self, ctx, step, u):
        out = ctx.change(u, ["request system software rollback"], long=True)
        check_output(ctx, u, out, "request system software rollback")
        u.status = "activated"
        ctx.change(u, ["request system reboot"], expect_reload=True)
