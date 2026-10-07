"""Huawei VRP (S series, CloudEngine, AR): one switch or router, or a stack / CSS
(every member takes the software from the master).

The .cc is uploaded over SCP (needs 'scp server enable'), checked by its size, then:
    startup system-software flash:/<file>, save, reboot
Roll back: startup system-software flash:/<previous>, save, reboot.
"""

import re

from app.tools.firmware_upgrade import checks as ck
from app.tools.firmware_upgrade.drivers.base import UpgradePath
from app.tools.firmware_upgrade.drivers.common import SimpleBootDriver


class HuaweiVrpDriver(SimpleBootDriver):
    platform = "huawei_vrp"
    default_fs = "flash:/"
    verify_by = "size"
    save_command = "save"
    reload_command = "reboot"
    paths = [UpgradePath("standalone", "Standalone or stack", 1,
                         "startup system-software to the new .cc, save, reboot")]

    def extra_commands(self, unit, image):
        return {"fw:dir": "dir flash:/", "fw:startup": "display startup",
                "fw:scp": "display scp"}

    def size_command(self, u, filename):
        return f"dir {self.file_system(u)}{filename}"

    def running_image(self, unit, outputs):
        # "Startup system software:      flash:/s5735-l-v200r021c10spc600.cc"
        m = re.search(r"^Startup system software:\s*(\S+)", outputs.get("fw:startup") or "", re.M)
        return m.group(1) if m else ""

    def extra_prechecks(self, ctx, unit, outputs, path):
        results = super().extra_prechecks(ctx, unit, outputs, path)
        scp = re.search(r"SCP server state\s*:\s*Enable", outputs.get("fw:scp") or "", re.I)
        results.append(ck.CheckResult(
            "scp_server", "SCP server enabled (for the image copy)", ck.BLOCKER,
            ck.PASS if scp else ck.FAIL, "enabled" if scp else "not enabled",
            "" if scp else "Configure 'scp server enable'"))
        return results

    def boot_commands(self, ctx, u, previous):
        image = u.running_image if previous else f"{self.file_system(u)}{ctx.image.filename}"
        return [f"startup system-software {image}"], False
