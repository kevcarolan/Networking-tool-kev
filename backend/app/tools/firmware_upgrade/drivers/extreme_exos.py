"""Extreme EXOS / Switch Engine: two image partitions (primary and secondary).

    copy the .xos to /usr/local/cfg
    install image <file> reboot     (installs into the partition not in use, selects it
                                     for the next boot and reboots; a stack: every slot)
Roll back: use image <previous partition>, reboot.
"""

from app.tools.firmware_upgrade.drivers.base import Step, UpgradePath
from app.tools.firmware_upgrade.drivers.common import SimpleBootDriver, check_output


class ExtremeExosDriver(SimpleBootDriver):
    platform = "extreme_exos"
    default_fs = "/usr/local/cfg/"
    verify_by = "size"
    save_command = None
    reload_command = "reboot"
    paths = [UpgradePath("standalone", "Standalone or SummitStack", 1,
                         "install image into the other partition, reboot")]

    def transfer_fs(self, unit):
        return self.file_system(unit).rstrip("/")

    def listing_command(self, u):
        return "ls"

    def running_image(self, unit, outputs):
        return unit.facts.get("image") or ""  # "primary" / "secondary" (Image Booted)

    def activate_steps(self, ctx, u):
        d = u.device_id
        return [Step(f"activate:{d}", "install_image", f"{u.name}: install image (reboots)", d,
                     reload=True)]

    def step_install_image(self, ctx, step, u):
        u.status = "activated"
        out = ctx.change(u, [f"install image {ctx.image.filename} reboot"], expect_reload=True,
                         long=True)
        check_output(ctx, u, out.split("[connection closed")[0], "install image", attention=True)

    def boot_commands(self, ctx, u, previous):
        return [f"use image {u.running_image}"], False
