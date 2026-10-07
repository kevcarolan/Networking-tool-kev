"""Shared pieces of the drivers added with multi-vendor support (PR B).

Most of these platforms upgrade the same way: copy the image, check it, point the boot
setting at it, save, reload; roll back by pointing the boot setting at the previous
image (or slot) and reloading. SimpleBootDriver does that; each platform says how.

The procedures are built from vendor documentation and tested against the simulator
(tests/fake_network.py). Each needs lab sign-off before live use (upgrade-lab-tests.md).
"""

import re

from app.tools.firmware_upgrade import checks as ck
from app.tools.firmware_upgrade.drivers.base import Step, StepFailed, Unit, UpgradeDriver

# Words that mean a change command failed, on any of these platforms
ERRORS = re.compile(r"%\s*Error|\bError:|\berror:|ERROR:|\bfailed\b|failure|Invalid input|"
                    r"not enough space|No such file", re.I)


def file_size(listing: str, filename: str) -> int | None:
    """Size of a file in a directory listing: the largest number on the file's line
    ("1  -rw-  123,456,789  Jan 01 2024 10:00:00  file.cc" -> 123456789)."""
    for line in (listing or "").splitlines():
        if filename in line.split() or line.rstrip().endswith(filename):
            numbers = [int(n.replace(",", "")) for n in re.findall(r"(?<![\w:.])\d[\d,]*(?![\w:])", line)]
            if numbers:
                return max(numbers)
    return None


def check_output(ctx, u: Unit, out: str, what: str, attention: bool = False) -> None:
    """Fail the step when a live change command printed an error."""
    if not ctx.dry_run and ERRORS.search(out or ""):
        raise StepFailed(f"{what} failed on {u.name}: {(out or '').strip()[-400:]}",
                         attention=attention)


class SimpleBootDriver(UpgradeDriver):
    """Copy, verify, set boot, save, reload. Subclasses set:

    verify_by     "md5" (verify_command / parse_checksum) or "size" (listing_command)
    save_command  saves the configuration (None: the platform has nothing to save)
    reload_command
    and implement boot_commands(ctx, u, previous) -> (lines, config_mode)."""

    verify_by = "md5"
    save_command: str | None = "write memory"
    reload_command = "reload"

    # --- pre-checks ----------------------------------------------------------------

    @property
    def check_label(self) -> str:
        return "check its MD5" if self.verify_by == "md5" else "check its size"

    def listing_command(self, u: Unit) -> str:
        return f"dir {self.file_system(u)}"

    def extra_commands(self, unit, image):
        return {"fw:dir": self.listing_command(unit)}

    def running_image(self, unit: Unit, outputs: dict[str, str]) -> str:
        """The image (or slot) the device runs now: the roll back target."""
        return unit.facts.get("image") or ""

    def extra_prechecks(self, ctx, unit: Unit, outputs, path):
        results = self.image_on_device_checks(ctx, unit, outputs)
        unit.running_image = self.running_image(unit, outputs)
        results.append(ck.CheckResult(
            "previous_image", "Current software kept for roll back", ck.BLOCKER,
            ck.PASS if unit.running_image else ck.FAIL, unit.running_image or "unknown",
            "" if unit.running_image else "The running image couldn't be read"))
        return results

    # --- checking the copy ------------------------------------------------------------

    def verify(self, ctx, u, record=False):
        if self.verify_by == "md5":
            return super().verify(ctx, u, record)
        listing = ctx.show(u, [self.size_command(u, ctx.image.filename)], long=True)[0]
        size = file_size(listing, self.size_name(u, ctx.image.filename))
        ok = size is not None and self.size_ok(size, ctx.image.size)
        if record:
            ctx.record_checks(u, "stage", [ck.CheckResult(
                "device_size", "Image on the device has the right size", ck.BLOCKER,
                ck.PASS if ok else ck.FAIL, f"{size} bytes" if size is not None else "not found",
                "" if ok else f"expected {ctx.image.size} bytes\n{listing.strip()[-300:]}")])
        return ok

    def size_command(self, u: Unit, filename: str) -> str:
        return self.listing_command(u)

    def size_name(self, u: Unit, filename: str) -> str:
        return filename

    @staticmethod
    def size_ok(found: int, expected: int) -> bool:
        return found == expected

    # --- the procedure -------------------------------------------------------------------

    def activate_steps(self, ctx, u):
        d = u.device_id
        return [Step(f"boot:{d}", "set_boot", f"{u.name}: boot from the new image, save", d),
                Step(f"reload:{d}", "reload", f"{u.name}: reload", d, reload=True)]

    def rollback_steps(self, ctx, u):
        d = u.device_id
        return [Step(f"rb_boot:{d}", "set_boot", f"{u.name}: boot from the previous image", d,
                     args={"previous": True}),
                Step(f"rb_reload:{d}", "reload", f"{u.name}: reload", d, reload=True)]

    def boot_commands(self, ctx, u: Unit, previous: bool) -> tuple[list[str], bool]:
        raise NotImplementedError

    def step_set_boot(self, ctx, step, u):
        lines, config = self.boot_commands(ctx, u, bool(step.args.get("previous")))
        out = ctx.change(u, lines, config=config)
        check_output(ctx, u, out, "Setting the boot image")
        if self.save_command:
            out = ctx.change(u, [self.save_command])
            check_output(ctx, u, out, "Saving the configuration")

    def step_reload(self, ctx, step, u):
        u.status = "activated"
        ctx.change(u, [self.reload_command], expect_reload=True)


def pending_on_device(ctx, u: Unit, command: str, done, failed, minutes: float, what: str) -> None:
    """Poll a show command until done(output) or failed(output) - for installs that run
    in the background on the device. Nothing to wait for in a dry run."""
    if ctx.dry_run:
        ctx.event(f"DRY RUN - would wait for {what} ('{command}')", "change", "action", u.device_id)
        return
    last = {"out": ""}

    def finished() -> bool:
        last["out"] = ctx.show(u, [command])[0]
        return done(last["out"]) or failed(last["out"])

    if not ctx.poll(finished, minutes=minutes, what=what):
        raise StepFailed(f"{what} on {u.name} didn't finish within {int(minutes)} minutes",
                         attention=True)
    if failed(last["out"]):
        raise StepFailed(f"{what} failed on {u.name}: {last['out'].strip()[-400:]}")
