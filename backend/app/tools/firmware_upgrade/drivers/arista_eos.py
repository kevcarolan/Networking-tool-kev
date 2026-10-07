"""Arista EOS: copy the .swi to flash, boot system, write memory, reload.

Standalone, or an MLAG pair: the MLAG secondary first, check the MLAG is active and
the peer link is up again, then the primary. Roll back: boot system to the previous
.swi (kept on flash), write memory, reload.
"""

import re

from app.tools.firmware_upgrade import checks as ck
from app.tools.firmware_upgrade.drivers.base import Step, StepFailed, Unit, UpgradePath
from app.tools.firmware_upgrade.drivers.common import SimpleBootDriver


def parse_mlag(out: str) -> dict:
    """'show mlag detail': state, negotiation, peer link and this switch's role.
        state                  :     Active      (MLAG Status)
        State                  :     primary     (MLAG Detailed Status - capital S)"""
    get = lambda pat: (re.search(pat, out or "", re.M) or [None, ""])[1].strip()  # noqa: E731
    return {"state": get(r"^\s*state\s*:\s*(\S+)"), "negotiation": get(r"negotiation status\s*:\s*(.+)$"),
            "peer_link": get(r"peer-link status\s*:\s*(\S+)"),
            "role": get(r"^\s*State\s*:\s*(primary|secondary)\b")}


def mlag_healthy(m: dict) -> bool:
    return (m["state"].lower() == "active" and m["negotiation"].lower() == "connected"
            and m["peer_link"].lower() == "up")


class AristaEosDriver(SimpleBootDriver):
    platform = "arista_eos"
    default_fs = "flash:"
    reload_command = "reload now"
    paths = [
        UpgradePath("standalone", "Standalone switch", 1, "boot system to the new .swi, reload"),
        UpgradePath("mlag_pair", "MLAG pair (secondary first)", 2,
                    "Upgrade the MLAG secondary, check the MLAG, then the primary"),
    ]

    def transfer_fs(self, unit):
        return "/mnt/flash" if self.file_system(unit) == "flash:" else self.file_system(unit)

    def extra_commands(self, unit, image):
        return {"fw:dir": "dir flash:", "fw:boot": "show boot-config",
                "fw:mlag": "show mlag detail"}

    def running_image(self, unit, outputs):
        # "Software image: flash:/EOS-4.30.1F.swi"
        m = re.search(r"Software image:\s*(\S+)", outputs.get("fw:boot") or "")
        return m.group(1).replace("flash:/", "flash:") if m else ""

    def extra_prechecks(self, ctx, unit: Unit, outputs, path):
        results = super().extra_prechecks(ctx, unit, outputs, path)
        old = unit.running_image.split(":")[-1].lstrip("/")
        present = bool(old) and old in (outputs.get("fw:dir") or "")
        results.append(ck.CheckResult(
            "previous_on_flash", "Current .swi stays on flash (for roll back)", ck.BLOCKER,
            ck.PASS if present else ck.FAIL, old or "unknown",
            "" if present else "The running image isn't on flash"))
        if path.units == 2:
            m = parse_mlag(outputs.get("fw:mlag") or "")
            unit.role = m["role"].lower()
            results.append(ck.CheckResult(
                "mlag", "MLAG active, peer connected, peer link up", ck.BLOCKER,
                ck.PASS if mlag_healthy(m) else ck.FAIL, m["role"] or "no MLAG",
                f"state: {m['state']}\nnegotiation: {m['negotiation']}\npeer link: {m['peer_link']}"))
        return results

    def pair_checks(self, ctx, units, path):
        roles = sorted(u.role for u in units)
        ok = roles == ["primary", "secondary"]
        return [ck.CheckResult("pair_roles", "One MLAG primary and one secondary", ck.BLOCKER,
                               ck.PASS if ok else ck.FAIL,
                               ", ".join(f"{u.name}: {u.role or '?'}" for u in units))]

    def order_units(self, units):
        return sorted(units, key=lambda u: 0 if u.role == "secondary" else 1)

    def upgrade_plan(self, ctx, path, units):
        steps: list[Step] = []
        for i, u in enumerate(units):
            if i:
                steps.append(Step(f"mlag_check:{u.device_id}", "mlag_check",
                                  "MLAG healthy again before the second switch", units[0].device_id))
            steps += self.unit_steps(ctx, u)
        return steps

    def boot_commands(self, ctx, u, previous):
        image = u.running_image if previous else f"{self.file_system(u)}{ctx.image.filename}"
        return [f"boot system {image}"], True

    def step_mlag_check(self, ctx, step, u):
        m = parse_mlag(ctx.show(u, ["show mlag detail"])[0])
        if not mlag_healthy(m):
            raise StepFailed(f"The MLAG isn't healthy after the first switch: state {m['state']}, "
                             f"peer link {m['peer_link']}")
        ctx.event("MLAG healthy - carrying on with the second switch", step.kind,
                  device_id=u.device_id)
