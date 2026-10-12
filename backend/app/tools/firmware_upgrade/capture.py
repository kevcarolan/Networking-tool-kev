"""Lab capture: run every read-only command the tools send to one device and save the
outputs in one text file, with what the tools read from them.

    sudo netops-cli capture core-sw1

Used to check the version, health-check, upgrade pre-check and MAC/ARP readers against
a real device, and to replace the samples taken from vendor documentation
(app/demo/vendor_samples.py). Only read-only commands are ever sent (``is_read_only``); the
running configuration is not included. IP and MAC addresses are replaced with stand-ins,
the same address always by the same stand-in so tables still match up (``--raw`` keeps
them).
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.core.platforms import PLATFORMS
from app.tools.firmware_upgrade import checks as ck
from app.tools.firmware_upgrade import drivers
from app.tools.firmware_upgrade.drivers.base import ImageRef, Unit
from app.tools.firmware_upgrade.facts import FACT_COMMANDS, parse_facts

_READ_ONLY = re.compile(
    r"^(show|display|get|dir|ls)\b"          # show/display/get commands, file listings
    r"|^/[a-z][\w /-]* print( terse)?$"      # MikroTik: /ip arp print terse
    r"|^diagnose sys flash list$"            # FortiGate: the firmware partitions
    r"|^file list [\w/.-]+( detail)?$",      # Junos: file list /var/tmp/ detail
    re.I)
_CHANGES = re.compile(r"\b(conf(ig(ure)?)?\s+t|copy|delete|erase|format|reload|reboot|install"
                      r"\s+(add|activate|commit|remove)|request|write|commit|clear)\b", re.I)


_WRITES = re.compile(r"\|\s*(redirect|tee|append|save|copy)\b|>", re.I)  # output to a file


def is_read_only(command: str) -> bool:
    """Only commands that can't change a device are ever captured."""
    command = command.strip()
    return (bool(_READ_ONLY.search(command)) and not _CHANGES.search(command.split("|")[0])
            and not _WRITES.search(command))


def capture_commands(platform: str, name: str = "device") -> dict[str, str]:
    """key -> command: the version check, the upgrade pre-checks (with the platform's own
    extra checks) and the circuit tables, as an upgrade job's pre-check sends them."""
    commands = dict(ck.commands_for(platform))
    driver = drivers.for_platform(platform)
    if driver is not None:
        unit = Unit(device_id=0, name=name, address="", platform=platform, position=0)
        image = ImageRef(0, "capture-check.bin", "0", "", 0, Path("/nonexistent"))
        commands.update(driver.extra_commands(unit, image))
    for i, cmd in enumerate(FACT_COMMANDS.get(platform, ())):
        if cmd not in commands.values():
            commands[f"facts{i}"] = cmd
    return {k: c for k, c in commands.items() if is_read_only(c)}


# --- stand-ins for addresses -------------------------------------------------------

_IPV4 = re.compile(r"(?<![\d.])(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?![\d.])")
_MAC = re.compile(r"(?<![0-9A-Fa-f:.-])("
                  r"[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}"
                  r"|[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}"
                  r"|[0-9A-Fa-f]{6}-[0-9A-Fa-f]{6}"
                  r"|[0-9A-Fa-f]{2}(?:[:-][0-9A-Fa-f]{2}){5}"
                  r")(?![0-9A-Fa-f:.-])")


@dataclass
class Masker:
    """Replaces IPv4 and MAC addresses, the same one always by the same stand-in. The last
    octet of an IP address is kept, so addresses in one subnet stay in one subnet; masks,
    0.0.0.0, loopback and multicast are kept as they are."""

    prefixes: dict[str, str] = field(default_factory=dict)
    macs: dict[str, str] = field(default_factory=dict)

    def ip(self, m: re.Match) -> str:
        octets = [int(x) for x in m.groups()]
        if any(o > 255 for o in octets) or octets[0] in (0, 127, 255) or 224 <= octets[0] <= 239:
            return m.group(0)
        prefix = ".".join(m.groups()[:3])
        if prefix not in self.prefixes:
            n = len(self.prefixes) + 1
            self.prefixes[prefix] = f"10.{100 + n // 256}.{n % 256}"
        return f"{self.prefixes[prefix]}.{octets[3]}"

    def mac(self, m: re.Match) -> str:
        text = m.group(0)
        digits = re.sub(r"[^0-9A-Fa-f]", "", text).lower()
        if digits not in self.macs:
            self.macs[digits] = f"02{len(self.macs) + 1:010x}"  # locally administered
        upper = any(c in "ABCDEF" for c in text) and not any(c in "abcdef" for c in text)
        new = iter(self.macs[digits].upper() if upper else self.macs[digits])
        return "".join(next(new) if c in "0123456789abcdefABCDEF" else c for c in text)

    def __call__(self, text: str) -> str:
        return _IPV4.sub(self.ip, _MAC.sub(self.mac, text))


# --- what the tools read -------------------------------------------------------------

def summary(platform: str, outputs: dict[str, str], th: ck.Thresholds) -> list[str]:
    lines = []
    try:
        facts = parse_facts(platform, ck.facts_outputs(platform, outputs))
        lines.append("Version check: " + ", ".join(
            f"{k} {v}" for k, v in vars(facts).items() if v not in (None, "")))
    except ValueError as exc:
        lines.append(f"Version check: COULD NOT READ ({exc})")
    for r in ck.health_checks(platform, outputs, th):
        lines.append(f"Check {r.check_id}: {r.status}" + (f" - {r.value}" if r.value else "")
                     + (f" ({r.detail})" if r.detail else ""))
    read = ck.live_read(outputs, platform)
    if read.macs is not None:
        lines.append(f"MAC table: {len(read.macs)} entries, {len(read.edge)} on edge ports")
    if read.arps is not None:
        lines.append(f"ARP table: {len(read.arps)} entries")
    if read.uplinks:
        lines.append(f"Uplinks (not edge ports): {', '.join(sorted(read.uplinks))}")
    return lines


Collector = Callable[[object, list[str]], list[str]]


def capture(target, platform: str, collector: Collector, account: str, th: ck.Thresholds,
            raw: bool = False, now: datetime | None = None) -> tuple[str, list[str]]:
    """Run the commands on the device; return the file's text and the summary lines."""
    commands = capture_commands(platform, target.name)
    unique = list(dict.fromkeys(commands.values()))
    by_cmd = dict(zip(unique, collector(target, unique)))
    outputs = {key: by_cmd.get(cmd) or "" for key, cmd in commands.items()}
    lines = summary(platform, outputs, th)
    mask = (lambda s: s) if raw else Masker()
    now = now or datetime.now(timezone.utc)
    label = PLATFORMS[platform].label if platform in PLATFORMS else platform
    head = [
        "# Lab capture: what the tools read from one device (send it for parser checks)",
        f"# platform: {platform} ({label})",
        f"# captured: {now:%Y-%m-%d %H:%M} UTC, with the {account} account",
        "# addresses: " + ("as on the device (--raw)" if raw else
                           "IP and MAC addresses replaced with stand-ins (--raw keeps them)"),
        "# Not included: the running configuration. Check the file before sending it on.",
        "#",
        "# What the tools read from it:",
        *[f"#   {mask(line)}" for line in lines],
        "",
    ]
    body = []
    for cmd in unique:
        keys = ", ".join(k for k, c in commands.items() if c == cmd)
        body += [f"===== {cmd} =====  [{keys}]", mask(by_cmd.get(cmd) or "").rstrip(), ""]
    return "\n".join(head + body) + "\n", lines


def parse_file(text: str) -> dict[str, str]:
    """command -> output, from a capture file (for turning captures into test samples)."""
    out, cmd, buf = {}, None, []
    for line in text.splitlines():
        m = re.match(r"^===== (.+?) =====(?:  \[.*\])?$", line)
        if m:
            if cmd is not None:
                out[cmd] = "\n".join(buf).rstrip() + "\n"
            cmd, buf = m.group(1), []
        elif cmd is not None:
            buf.append(line)
    if cmd is not None:
        out[cmd] = "\n".join(buf).rstrip() + "\n"
    return out
