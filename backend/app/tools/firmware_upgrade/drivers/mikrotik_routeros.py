"""MikroTik RouterOS: upload the routeros .npk, reboot (RouterOS installs it while it
boots), then upgrade the RouterBOARD firmware to match and reboot once more.

Only the main routeros package is upgraded. Extra packages (wireless, container, ...)
must be uploaded for the same release first, by hand.

Roll back is not automatic: RouterOS keeps no copy of the previous release. Upload the
previous .npk and run '/system package downgrade' (see upgrades.md).
"""

import re

from app.tools.firmware_upgrade import checks as ck
from app.tools.firmware_upgrade.drivers.base import Step, StepFailed, UpgradePath
from app.tools.firmware_upgrade.drivers.common import SimpleBootDriver, check_output


class MikrotikRouterosDriver(SimpleBootDriver):
    platform = "mikrotik_routeros"
    default_fs = ""
    verify_by = "size"
    save_command = None
    reload_command = "/system reboot"
    paths = [UpgradePath("standalone", "One router or switch", 1,
                         "Upload the .npk, reboot, then upgrade the RouterBOARD firmware")]

    def listing_command(self, u):
        return "/file print terse"

    def size_name(self, u, filename):
        return f"name={filename}"

    @staticmethod
    def size_ok(found, expected):
        return abs(found - expected) <= max(expected // 100, 1)  # RouterOS rounds: "13.2MiB"

    def verify(self, ctx, u, record=False):
        # "0 name=routeros-7.15-arm64.npk type=package size=13.2MiB ..." (v7) or size=13 875 200 (v6)
        listing = ctx.show(u, [self.listing_command(u)])[0]
        line = next((ln for ln in listing.splitlines() if f"name={ctx.image.filename}" in ln), "")
        m = re.search(r"size=([\d.]+)\s*([KMG]i?B)?|size=([\d ]+)", line)
        size = None
        if m and m.group(1):
            scale = {"K": 1024, "M": 1024 ** 2, "G": 1024 ** 3}.get((m.group(2) or " ")[0], 1)
            size = int(float(m.group(1)) * scale)
        elif m and m.group(3):
            size = int(m.group(3).replace(" ", ""))
        ok = size is not None and self.size_ok(size, ctx.image.size)
        if record:
            ctx.record_checks(u, "stage", [ck.CheckResult(
                "device_size", "Package on the router has the right size", ck.BLOCKER,
                ck.PASS if ok else ck.FAIL, f"{size} bytes" if size is not None else "not found",
                "" if ok else f"expected about {ctx.image.size} bytes")])
        return ok

    def running_image(self, unit, outputs):
        return unit.facts.get("version") or ""

    def activate_steps(self, ctx, u):
        d = u.device_id
        return [Step(f"reload:{d}", "reload", f"{u.name}: reboot to install the package", d,
                     reload=True)]

    def finish_steps(self, ctx, u):
        d = u.device_id
        return [Step(f"firmware:{d}", "routerboard_firmware", f"{u.name}: upgrade the RouterBOARD "
                     "firmware and reboot (skipped when it is already current)", d, reload=True)]

    def rollback_steps(self, ctx, u):
        return [Step(f"rb:{u.device_id}", "manual_rollback", f"{u.name}: downgrade by hand",
                     u.device_id)]

    def step_routerboard_firmware(self, ctx, step, u):
        board = ctx.show(u, ["/system routerboard print"])[0]
        current = re.search(r"current-firmware:\s*(\S+)", board)
        upgrade = re.search(r"upgrade-firmware:\s*(\S+)", board)
        if "routerboard: yes" not in board:
            ctx.event(f"{u.name} isn't a RouterBOARD (e.g. CHR): no firmware to upgrade",
                      step.kind, device_id=u.device_id)
            return
        if current and upgrade and current.group(1) == upgrade.group(1) and not ctx.dry_run:
            ctx.event(f"RouterBOARD firmware on {u.name} is already {current.group(1)}",
                      step.kind, device_id=u.device_id)
            return
        out = ctx.change(u, ["/system routerboard upgrade"])
        check_output(ctx, u, out, "RouterBOARD firmware upgrade")
        ctx.change(u, [self.reload_command], expect_reload=True)
        ctx.wait_back(u)

    def step_manual_rollback(self, ctx, step, u):
        raise StepFailed(f"RouterOS keeps no copy of the previous release: upload the previous "
                         f"routeros .npk to {u.name} and run '/system package downgrade'",
                         attention=True)
