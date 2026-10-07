"""Dell SmartFabric OS10: two partitions (active and standby).

    copy the .bin to the upgrade account's home folder (home://)
    image install home://<image>        (runs in the background: show image status)
    boot system standby, write memory, reload
Roll back: boot system standby (the previous software is now there), write memory, reload.

Not yet: a VLT pair as one job (upgrade each peer as its own job, secondary first).
"""

import re

from app.tools.firmware_upgrade.drivers.base import Step, UpgradePath
from app.tools.firmware_upgrade.drivers.common import (SimpleBootDriver, check_output,
                                                       pending_on_device)


def install_state(out: str) -> str:
    """'show image status': "State Detail: Completed: No error" -> "Completed: No error"."""
    m = re.search(r"State Detail:\s*(.+)$", out or "", re.M)
    return m.group(1).strip() if m else ""


class DellOs10Driver(SimpleBootDriver):
    platform = "dell_os10"
    default_fs = "home://"
    verify_by = "size"
    paths = [UpgradePath("standalone", "One switch", 1,
                         "image install to the standby partition, boot from it, reload")]

    def listing_command(self, u):
        return "dir home"

    def running_image(self, unit, outputs):
        return "active partition" if unit.facts.get("version") else ""

    def activate_steps(self, ctx, u):
        d = u.device_id
        return [Step(f"install:{d}", "image_install", f"{u.name}: image install to the standby "
                     "partition", d), *super().activate_steps(ctx, u)]

    def step_image_install(self, ctx, step, u):
        out = ctx.change(u, [f"image install {self.file_system(u)}{ctx.image.filename}"])
        check_output(ctx, u, out, "image install")
        pending_on_device(ctx, u, "show image status",
                          lambda o: install_state(o).startswith("Completed: No error"),
                          lambda o: "fail" in install_state(o).lower(), 45, "image install")

    def boot_commands(self, ctx, u, previous):
        return ["boot system standby"], False
