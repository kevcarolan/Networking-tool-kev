"""Cisco IOS-XR (ASR 9000, NCS 540/5500, 8000).

Two paths, by the XR generation:
  install add/activate (eXR, 6.x-7.x):
      install add source harddisk: <image>     (background: show install request)
      install activate <image> noprompt        (reloads)
  install replace (XR 7 "LNT" on 8000 / NCS 540 / NCS 5700):
      install replace /harddisk:/<image> noprompt   (reloads)
then, only after the post-checks pass (or are overridden): install commit.
Roll back before the commit: reload location all - the router comes back on the
committed (previous) software.
"""

import re

from app.tools.firmware_upgrade.drivers.base import Step, StepFailed, UpgradePath
from app.tools.firmware_upgrade.drivers.common import (SimpleBootDriver, check_output,
                                                       pending_on_device)

_BUSY = re.compile(r"in progress", re.I)


def install_idle(out: str) -> bool:
    return bool(re.search(r"No install operation in progress", out or "", re.I))


def install_failed(out: str) -> bool:
    return bool(re.search(r"\b(failed|aborted)\b", out or "", re.I)) and not _BUSY.search(out or "")


class CiscoXrDriver(SimpleBootDriver):
    platform = "cisco_xr"
    default_fs = "harddisk:"
    paths = [
        UpgradePath("install_add", "install add / activate (eXR)", 1,
                    "install add, install activate; committed only after the post-checks"),
        UpgradePath("install_replace", "install replace (XR 7 LNT)", 1,
                    "install replace; committed only after the post-checks"),
    ]

    def listing_command(self, u):
        return f"dir {self.file_system(u)}"

    def verify_command(self, u, filename):
        return f"show md5 file /{self.file_system(u)}/{filename}"

    def running_image(self, unit, outputs):
        return unit.facts.get("version") or ""

    def activate_steps(self, ctx, u):
        d = u.device_id
        if ctx.path.id == "install_replace":
            return [Step(f"activate:{d}", "install_replace", f"{u.name}: install replace "
                         "(reloads)", d, reload=True)]
        return [Step(f"add:{d}", "install_add", f"{u.name}: install add", d),
                Step(f"activate:{d}", "install_activate", f"{u.name}: install activate (reloads)",
                     d, reload=True)]

    def finish_steps(self, ctx, u):
        return [Step(f"commit:{u.device_id}", "install_commit", f"{u.name}: install commit",
                     u.device_id)]

    def rollback_steps(self, ctx, u):
        return [Step(f"rb:{u.device_id}", "reload_uncommitted", f"{u.name}: reload to the "
                     "committed (previous) software", u.device_id, reload=True)]

    def step_install_add(self, ctx, step, u):
        out = ctx.change(u, [f"install add source {self.file_system(u)} {ctx.image.filename}"],
                         long=True)
        check_output(ctx, u, out, "install add")
        pending_on_device(ctx, u, "show install request", install_idle, install_failed, 60,
                          "install add")

    def step_install_activate(self, ctx, step, u):
        u.status = "activated"
        out = ctx.change(u, [f"install activate {ctx.image.filename} noprompt"],
                         expect_reload=True, long=True)
        check_output(ctx, u, out.split("[connection closed")[0], "install activate",
                     attention=True)
        ctx.set_job(pending_commit=True)

    def step_install_replace(self, ctx, step, u):
        u.status = "activated"
        out = ctx.change(u, [f"install replace /{self.file_system(u)}/{ctx.image.filename} "
                             "noprompt"], expect_reload=True, long=True)
        check_output(ctx, u, out.split("[connection closed")[0], "install replace",
                     attention=True)
        ctx.set_job(pending_commit=True)

    def step_install_commit(self, ctx, step, u):
        out = ctx.change(u, ["install commit"], long=True)
        check_output(ctx, u, out, "install commit")
        pending_on_device(ctx, u, "show install request", install_idle, install_failed, 30,
                          "install commit")
        ctx.set_job(pending_commit=False)

    def step_reload_uncommitted(self, ctx, step, u):
        if not ctx.pending_commit:
            raise StepFailed(f"The new software on {u.name} is already committed: roll back by "
                             "hand ('install rollback to committed' or an install of the "
                             "previous release)", attention=True)
        ctx.change(u, ["reload location all noprompt"], expect_reload=True)
        ctx.set_job(pending_commit=False)
