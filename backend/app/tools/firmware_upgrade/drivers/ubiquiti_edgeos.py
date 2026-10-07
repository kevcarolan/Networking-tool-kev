"""Ubiquiti EdgeRouter (EdgeOS): two image slots; 'add system image' replaces the one
not running and makes the new one the default.

    copy the .tar to /tmp, md5sum
    add system image /tmp/<file>, reboot
Roll back: set system image default-image (back to the previous image), reboot.
"""

from app.tools.firmware_upgrade.drivers.base import Step, UpgradePath
from app.tools.firmware_upgrade.drivers.common import SimpleBootDriver, check_output


class UbiquitiEdgeosDriver(SimpleBootDriver):
    platform = "ubiquiti_edgeos"
    default_fs = "/tmp/"
    save_command = None
    reload_command = "reboot"
    paths = [UpgradePath("standalone", "One router", 1, "add system image, reboot")]

    def transfer_fs(self, unit):
        return self.file_system(unit).rstrip("/")

    def listing_command(self, u):
        return f"ls -l {self.file_system(u)}"

    def verify_command(self, u, filename):
        return f"md5sum {self.file_system(u)}{filename}"

    def running_image(self, unit, outputs):
        return unit.facts.get("version") or ""

    def activate_steps(self, ctx, u):
        d = u.device_id
        return [Step(f"add:{d}", "add_image", f"{u.name}: add system image", d),
                Step(f"reload:{d}", "reload", f"{u.name}: reboot", d, reload=True)]

    def step_add_image(self, ctx, step, u):
        out = ctx.change(u, [f"add system image {self.file_system(u)}{ctx.image.filename}"],
                         long=True)
        check_output(ctx, u, out, "add system image")

    def boot_commands(self, ctx, u, previous):
        return ["set system image default-image"], False
