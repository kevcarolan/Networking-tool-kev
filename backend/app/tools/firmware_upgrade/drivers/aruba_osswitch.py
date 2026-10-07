"""HPE ArubaOS-Switch (ProCurve): two image slots, primary and secondary.

The new image is uploaded over SCP straight into the slot the switch is *not* running
from (needs 'ip ssh filetransfer'). Then:
    write memory, boot set-default flash <slot>, reload
A stack (VSF or backplane stacking) takes the image from the commander.
Roll back: boot set-default flash <previous slot>, reload.
"""

import re

from app.tools.firmware_upgrade import checks as ck
from app.tools.firmware_upgrade.drivers.base import Unit, UpgradePath
from app.tools.firmware_upgrade.drivers.common import SimpleBootDriver


def flash_slots(out: str) -> dict[str, tuple[int, str]]:
    """'show flash': slot -> (size, version).
        Primary Image    :   26170212 03/13/23 WC.16.11.0012"""
    return {m.group(1).lower(): (int(m.group(2)), m.group(3)) for m in re.finditer(
        r"^\s*(Primary|Secondary) Image\s*:\s*(\d+)\s+\S+\s+(\S+)", out or "", re.M)}


class ArubaOsSwitchDriver(SimpleBootDriver):
    platform = "aruba_osswitch"
    verify_by = "size"
    save_command = None  # saved before the boot setting changes (step_set_boot)
    paths = [UpgradePath("standalone", "Standalone or stack", 1,
                         "Upload into the other image slot, boot from it, reload")]

    @staticmethod
    def _slot(unit: Unit) -> str:
        running = (unit.running_image or unit.facts.get("image") or "primary").lower()
        return "secondary" if running == "primary" else "primary"

    def file_system(self, unit):
        return f"/os/{self._slot(unit)}"

    def listing_command(self, u):
        return "show flash"

    def extra_commands(self, unit, image):
        return {"fw:flash": "show flash", "fw:scp": "show ip ssh"}

    def running_image(self, unit, outputs):
        return (unit.facts.get("image") or "").lower()

    def extra_prechecks(self, ctx, unit, outputs, path):
        unit.running_image = self.running_image(unit, outputs)
        slots = flash_slots(outputs.get("fw:flash") or "")
        target = self._slot(unit)
        unit.image_present = slots.get(target, (0, ""))[1] == ctx.image.version
        scp = re.search(r"Secure Copy Enabled\s*:\s*Yes", outputs.get("fw:scp") or "", re.I)
        return [
            ck.CheckResult("previous_image", "Current software kept for roll back", ck.BLOCKER,
                           ck.PASS if unit.running_image else ck.FAIL,
                           f"running from {unit.running_image or '?'}; the new image goes to "
                           f"{target}"),
            ck.CheckResult("image_on_device", "Image already in the other slot", ck.INFO, ck.PASS,
                           "yes" if unit.image_present else
                           f"no - {target} has {slots.get(target, (0, 'nothing'))[1]}"),
            ck.CheckResult("scp_server", "SCP enabled (for the image upload)", ck.BLOCKER,
                           ck.PASS if scp else ck.FAIL, "enabled" if scp else "not enabled",
                           "" if scp else "Configure 'ip ssh filetransfer'"),
        ]

    def verify(self, ctx, u, record=False):
        slot = self._slot(u)
        size, version = flash_slots(ctx.show(u, ["show flash"])[0]).get(slot, (None, ""))
        ok = size == ctx.image.size or version == ctx.image.version
        if record:
            ctx.record_checks(u, "stage", [ck.CheckResult(
                "device_size", f"Image in the {slot} slot is the new one", ck.BLOCKER,
                ck.PASS if ok else ck.FAIL, f"{size} bytes, {version}" if size else "empty",
                "" if ok else f"expected {ctx.image.size} bytes or version {ctx.image.version}")])
        return ok

    def boot_commands(self, ctx, u, previous):
        slot = u.running_image if previous else self._slot(u)
        return ["write memory", f"boot set-default flash {slot}"], False
