"""HPE Aruba Mobility Controller or Conductor (AOS 8): two partitions, 0 and 1.

The image is copied to flash, then into the partition the controller is *not* booted
from, and checked there:
    copy flash: <image> system: partition <n>
    boot system partition <n>, write memory, reload
Roll back: boot system partition <previous>, write memory, reload.

A cluster is upgraded one controller at a time, as separate jobs (Live Upgrade, which
moves the access points between controllers, is not used yet).
"""

import re

from app.tools.firmware_upgrade import checks as ck
from app.tools.firmware_upgrade.drivers.base import Step, StepFailed, Unit, UpgradePath
from app.tools.firmware_upgrade.drivers.common import SimpleBootDriver, check_output


def partitions(out: str) -> dict:
    """'show image version': partition -> {"version": ..., "default": bool}.
        Partition               : 0:0 (/dev/usb/flash1) **Default boot**
        Software Version        : ArubaOS 8.10.0.7 (Digitally Signed SHA1/SHA256 - Production Build)"""
    parts = {}
    for block in re.split(r"^(?=Partition\s*:)", out or "", flags=re.M):
        m = re.match(r"Partition\s*:\s*\d+:(\d+)", block)
        if not m:
            continue
        v = re.search(r"Software Version\s*:\s*ArubaOS\s+(\S+)", block)
        parts[m.group(1)] = {"version": v.group(1) if v else "",
                             "default": "Default boot" in block}
    return parts


class ArubaAos8Driver(SimpleBootDriver):
    platform = "aruba_aos8"
    default_fs = "flash:"
    verify_by = "size"
    paths = [UpgradePath("standalone", "One controller", 1,
                         "Copy into the other partition, boot from it, reload")]

    def listing_command(self, u):
        return "dir"

    def extra_commands(self, unit, image):
        return {"fw:dir": "dir", "fw:image": "show image version"}

    def running_image(self, unit, outputs):
        boot = [p for p, info in partitions(outputs.get("fw:image") or "").items() if info["default"]]
        return f"partition {boot[0]}" if boot else ""

    @staticmethod
    def _target(u: Unit) -> str:
        return "1" if u.running_image.endswith("0") else "0"

    def activate_steps(self, ctx, u):
        d = u.device_id
        return [Step(f"partition:{d}", "copy_partition", f"{u.name}: copy the image into "
                     f"partition {self._target(u)}", d), *super().activate_steps(ctx, u)]

    def step_copy_partition(self, ctx, step, u):
        n = self._target(u)
        out = ctx.change(u, [f"copy flash: {ctx.image.filename} system: partition {n}"], long=True)
        check_output(ctx, u, out, "Copying the image into the partition")
        if ctx.dry_run:
            return
        found = partitions(ctx.show(u, ["show image version"])[0]).get(n, {}).get("version", "")
        ctx.record_checks(u, "stage", [ck.CheckResult(
            "partition_version", f"Partition {n} holds the new version", ck.BLOCKER,
            ck.PASS if found == ctx.image.version else ck.FAIL, found or "empty")])
        if found != ctx.image.version:
            raise StepFailed(f"Partition {n} on {u.name} has '{found}', not {ctx.image.version}")

    def boot_commands(self, ctx, u, previous):
        n = u.running_image.split()[-1] if previous else self._target(u)
        return [f"boot system partition {n}"], False
