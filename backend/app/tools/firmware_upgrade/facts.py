"""Reads model, serial, software version, free flash and HA state from each
platform's show commands, and compares versions against the standards."""

import fnmatch
import re
from dataclasses import dataclass

from app.core.platforms import CLI_ERRORS, PLATFORMS

# Commands run on each platform, in order. Only the first one must succeed;
# the rest add detail (flash space, failover state) and may be missing.
FACT_COMMANDS: dict[str, tuple[str, ...]] = {
    "cisco_ios": ("show version", "dir"),
    "cisco_nxos": ("show version", "dir bootflash:"),
    "cisco_asa": ("show version", "dir", "show failover"),
    "cisco_ftd": ("show version", "show failover"),
    "allied_awplus": ("show version", "show system"),
    "cisco_xr": ("show version", "show inventory"),
    "cisco_smb": ("show version", "show inventory"),
    "arista_eos": ("show version", "dir flash:"),
    "juniper_junos": ("show version", "show chassis hardware"),
    "fortinet_fortios": ("get system status",),
    "paloalto_panos": ("show system info", "show high-availability state"),
    "checkpoint_gaia": ("show version all", "show asset all", "show cluster state"),
    "aruba_aoscx": ("show version", "show system"),
    "aruba_osswitch": ("show version", "show system", "show modules"),
    "aruba_aos8": ("show version", "show inventory"),
    "dell_os10": ("show version", "show inventory"),
    "extreme_exos": ("show version", "show switch"),
    "mikrotik_routeros": ("/system resource print", "/system routerboard print"),
    "ubiquiti_edgeos": ("show version",),
    "huawei_vrp": ("display version", "display esn"),
}


@dataclass
class Facts:
    version: str | None = None
    model: str | None = None
    serial: str | None = None
    image: str | None = None
    boot_mode: str | None = None
    ha_role: str | None = None
    flash_total: int | None = None
    flash_free: int | None = None


def _find(pattern: str, text: str, flags: int = re.M) -> str | None:
    m = re.search(pattern, text, flags)
    return m.group(1).strip() if m else None


def _first(*values: str | None) -> str | None:
    return next((v for v in values if v), None)


def _cli_error(text: str) -> bool:
    return any(marker in text[:300] for marker in CLI_ERRORS)


def _extra(outputs: list[str], i: int) -> str:
    """Output of an optional command, or '' when it is missing or was rejected."""
    out = outputs[i] if len(outputs) > i else ""
    return "" if _cli_error(out) else out


def _size(value: str | None, unit: str | None) -> int | None:
    """'1036.0', 'MiB' -> bytes."""
    if not value:
        return None
    scale = {"": 1, "b": 1, "k": 1024, "m": 1024 ** 2, "g": 1024 ** 3}[(unit or "")[:1].lower()]
    return int(float(value) * scale)


def _dir_space(text: str, facts: Facts) -> None:
    # IOS / IOS-XE / ASA:  "11353194496 bytes total (8151625728 bytes free)"
    m = re.search(r"(\d+)\s+bytes total\s*\((\d+)\s+bytes free", text)
    if m:
        facts.flash_total, facts.flash_free = int(m.group(1)), int(m.group(2))
        return
    # NX-OS:  "   1234 bytes free" / "   5678 bytes total" on separate lines
    free, total = _find(r"^\s*(\d+)\s+bytes free", text), _find(r"^\s*(\d+)\s+bytes total", text)
    if free and total:
        facts.flash_total, facts.flash_free = int(total), int(free)


def _asa_failover(text: str) -> str | None:
    if re.search(r"^Failover Off", text, re.M):
        return "standalone"
    m = re.search(r"^\s*This host:\s*(\w+)\s*-\s*(.+?)\s*$", text, re.M)
    return f"{m.group(1)} / {m.group(2)}" if m else None


def _parse_ios(outputs: list[str]) -> Facts:
    ver = outputs[0]
    f = Facts()
    f.version = _first(_find(r"Cisco IOS XE Software, Version\s+(\S+)", ver),
                       _find(r"Cisco IOS Software.*?,\s*Version\s+([^\s,]+)", ver),
                       _find(r"\bVersion\s+([^\s,]+)", ver))
    f.model = _first(_find(r"^Model [Nn]umber\s*:\s*(\S+)", ver),
                     _find(r"^cisco\s+(\S+)\s+\(.*?\)\s+processor", ver, re.M | re.I))
    f.serial = _first(_find(r"^System [Ss]erial [Nn]umber\s*:\s*(\S+)", ver),
                      _find(r"Processor board ID\s+(\S+)", ver))
    f.image = _find(r'System image file is "([^"]+)"', ver)
    # IOS-XE switches list each member with its mode (INSTALL / BUNDLE).
    if re.search(r"^\*?\s*\d+\s+\d+\s+\S+\s+\S+\s+\S+\s+INSTALL\s*$", ver, re.M) or \
            (f.image or "").endswith("packages.conf"):
        f.boot_mode = "install"
    elif re.search(r"^\*?\s*\d+\s+\d+\s+\S+\s+\S+\s+\S+\s+BUNDLE\s*$", ver, re.M) or \
            (f.image or "").lower().endswith(".bin"):
        f.boot_mode = "bundle"
    return f


def _parse_nxos(outputs: list[str]) -> Facts:
    ver = outputs[0]
    f = Facts()
    f.version = _first(_find(r"NXOS:\s+version\s+(\S+)", ver),
                       _find(r"system:\s+version\s+(\S+)", ver))
    f.model = _find(r"cisco Nexus\S*\s+(\S+)\s+[Cc]hassis", ver)
    f.serial = _find(r"Processor [Bb]oard ID\s+(\S+)", ver)
    f.image = _first(_find(r"NXOS image file is:\s+(\S+)", ver),
                     _find(r"system image file is:\s+(\S+)", ver))
    return f


def _parse_asa(outputs: list[str]) -> Facts:
    ver = outputs[0]
    f = Facts()
    f.version = _find(r"Cisco Adaptive Security Appliance Software Version\s+(\S+)", ver)
    f.model = _find(r"^Hardware:\s+([^,\s]+)", ver)
    f.serial = _find(r"^Serial Number:\s+(\S+)", ver)
    f.image = _find(r'System image file is "([^"]+)"', ver)
    return f


def _parse_ftd(outputs: list[str]) -> Facts:
    ver = outputs[0]
    f = Facts()
    # "Model : Cisco Firepower 2110 Threat Defense (77) Version 7.2.5 (Build 208)"
    m = re.search(r"^Model\s*:\s*(.+?)\s+Version\s+(\S+)(?:\s+\(Build\s+(\d+)\))?", ver, re.M)
    if m:
        f.version = m.group(2)
        f.image = f"build {m.group(3)}" if m.group(3) else None
    f.model = _first(_find(r"^Hardware:\s+([^,\s]+)", ver),
                     re.sub(r"^Cisco\s+|\s*\(\d+\)$", "", m.group(1)) if m else None)
    f.serial = _find(r"^Serial Number:\s+(\S+)", ver)
    return f


def _parse_awplus(outputs: list[str]) -> Facts:
    ver = outputs[0]
    f = Facts()
    build = _find(r"^Build name\s*:\s*(\S+)", ver)
    f.image = build
    f.version = _first(_find(r"-(\d+\.\d+\.\d+[\w.-]*?)\.rel$", build or ""),
                       _find(r"AlliedWare Plus \(TM\)\s+(\S+)", ver),
                       _find(r"^Software version\s*:\s*(\S+)", ver))
    system = outputs[1] if len(outputs) > 1 else ""
    # "Base       414        x930-28GTX       B-0  A04563H182400035"
    m = re.search(r"^Base\s+\d+\s+(.*?)\s+(\S+)\s+(\S+)\s*$", system, re.M)
    if m:
        f.model, f.serial = m.group(1).split()[-1], m.group(3)
    else:
        f.model = _find(r"^(x\d+\S*|SBx\d+\S*|AT-\S+)-\d+\.\d+\.\d+", build or "")
    return f


def _cisco_inventory(text: str, f: Facts) -> None:
    """Model and serial from the first 'PID: ..., SN: ...' entry of 'show inventory'."""
    m = re.search(r"^\s*PID:[ \t]*([^,\s]+)\s*,?.*?SN:[ \t]*(\S+)", text, re.M)
    if m:
        f.model, f.serial = m.group(1), m.group(2)


def _parse_xr(outputs: list[str]) -> Facts:
    ver = outputs[0]
    f = Facts()
    f.version = _find(r"Cisco IOS XR Software,\s*Version\s+([\w.]+)", ver)
    f.model = _find(r"^cisco\s+(\S+)\s+(?:\(.*?\)\s+)?(?:processor|Series)", ver, re.M | re.I)
    _cisco_inventory(_extra(outputs, 1), f)
    return f


def _parse_smb(outputs: list[str]) -> Facts:
    ver = outputs[0]
    f = Facts()
    # "Active-image: flash://system/images/image_cbs_..._3.3.0.16....bin\n  Version: 3.3.0.16"
    m = re.search(r"^Active-image:[ \t]*(\S+)\s*\n\s*Version:[ \t]*(\S+)", ver, re.M)
    f.image, f.version = (m.group(1), m.group(2)) if m else (None, _find(r"Version:[ \t]*(\S+)", ver))
    _cisco_inventory(_extra(outputs, 1), f)
    return f


def _parse_eos(outputs: list[str]) -> Facts:
    ver = outputs[0]
    f = Facts()
    f.version = _find(r"^Software image version:[ \t]*(\S+)", ver)
    f.model = _first(_find(r"^Arista\s+(\S+)", ver), _find(r"^Model name:[ \t]*(\S+)", ver))
    f.serial = _find(r"^Serial number:[ \t]*(\S+)", ver)
    return f


def _parse_junos(outputs: list[str]) -> Facts:
    ver = outputs[0]
    f = Facts()
    # Newer: "Junos: 22.4R3-S2.11"; older: "JUNOS Software Release [21.4R3.15]" or
    # "JUNOS EX  Software Suite [18.4R2-S3]". Virtual Chassis lists every member: first wins.
    f.version = _first(_find(r"^Junos:[ \t]*(\S+)", ver),
                       _find(r"^JUNOS .*?\[([^\]]+)\]", ver))
    f.model = _find(r"^Model:[ \t]*(\S+)", ver)
    f.model = f.model.upper() if f.model else None
    hw = _extra(outputs, 1)
    # "Chassis                                XN1234567890      EX4400-48P"
    m = re.search(r"^Chassis\s+(\S+)\s+(\S+)", hw, re.M)
    if m:
        f.serial = m.group(1)
        f.model = f.model or m.group(2)
    return f


def _parse_fortios(outputs: list[str]) -> Facts:
    ver = outputs[0]
    f = Facts()
    # "Version: FortiGate-60F v7.2.5,build1517,230606 (GA.F)"
    m = re.search(r"^Version:[ \t]*(\S+)\s+v([\d.]+),build(\d+)", ver, re.M)
    if m:
        f.model, f.version, f.image = m.group(1), m.group(2), f"build{m.group(3)}"
    f.serial = _find(r"^Serial-Number:[ \t]*(\S+)", ver)
    # "Current HA mode: standalone" / "Current HA mode: a-p, master" (or "primary")
    ha = _find(r"^Current HA mode:[ \t]*(.+)$", ver)
    if ha:
        f.ha_role = "standalone" if ha.lower() == "standalone" else ha
    return f


def _parse_panos(outputs: list[str]) -> Facts:
    info = outputs[0]
    f = Facts()
    f.version = _find(r"^sw-version:[ \t]*(\S+)", info)
    f.model = _find(r"^model:[ \t]*(\S+)", info)
    f.serial = _find(r"^serial:[ \t]*(\S+)", info)
    ha = _extra(outputs, 1)
    if re.search(r"HA not enabled", ha, re.I):
        f.ha_role = "standalone"
    else:
        # "  Local Information:\n    Version: 1\n    Mode: Active-Passive\n    State: active ..."
        m = re.search(r"Local Information:.*?^\s*State:[ \t]*(\S+)", ha, re.M | re.S)
        f.ha_role = m.group(1) if m else None
    return f


def _parse_gaia(outputs: list[str]) -> Facts:
    ver = outputs[0]
    f = Facts()
    f.version = _find(r"^Product version\s+Check Point Gaia\s+(\S+)", ver)
    f.image = _first(_find(r"^OS build\s+(\S+)", ver))
    asset = _extra(outputs, 1)
    f.model = _first(_find(r"^Platform:[ \t]*(\S+)", asset), _find(r"^Model:[ \t]*(.+)$", asset))
    f.serial = _find(r"^Serial Number:[ \t]*(\S+)", asset)
    cluster = _extra(outputs, 2)
    # "1 (local)  10.0.0.1  100%  ACTIVE  fw1"
    state = _find(r"\(local\)\s+\S+\s+\S+\s+([A-Za-z()]+)", cluster)
    if state:
        f.ha_role = state.lower()
    elif re.search(r"not (?:a cluster member|configured)|cluster.*disabled", cluster, re.I):
        f.ha_role = "standalone"
    return f


def _parse_aoscx(outputs: list[str]) -> Facts:
    ver = outputs[0]
    f = Facts()
    f.version = _find(r"^Version[ \t]*:[ \t]*(\S+)", ver)
    f.image = _find(r"^Active Image[ \t]*:[ \t]*(\S+)", ver)
    system = _extra(outputs, 1)
    # "Product Name : JL658A 6300M 24SFP+ 4SFP56 Swch" -> "JL658A"
    f.model = _find(r"^Product Name[ \t]*:[ \t]*(\S+)", system)
    f.serial = _find(r"^Chassis Serial Nbr[ \t]*:[ \t]*(\S+)", system)
    return f


def _parse_osswitch(outputs: list[str]) -> Facts:
    ver = outputs[0]
    f = Facts()
    # The release ("WC.16.10.0009") is on its own line under "Image stamp:"
    f.version = _find(r"^\s+([A-Z]{1,2}\.\d{2}\.\d{2}\.\d{4})\s*$", ver)
    f.image = _find(r"^Boot Image:[ \t]*(\S+)", ver)
    system = _extra(outputs, 1)
    f.serial = _find(r"Serial Number[ \t]*:[ \t]*(\S+)", system)
    modules = _extra(outputs, 2)
    # " Chassis: 2930M-24G-PoE+ JL320A          Serial Number:   SG9ZKMX123"
    f.model = _find(r"^\s*Chassis:\s*\S+\s+([A-Z]{1,2}\d{3,4}[A-Z])\b", modules)
    f.serial = f.serial or _find(r"^\s*Chassis:.*Serial Number:[ \t]*(\S+)", modules)
    return f


def _parse_aos8(outputs: list[str]) -> Facts:
    ver = outputs[0]
    f = Facts()
    # "ArubaOS (MODEL: Aruba7210), Version 8.10.0.7"
    m = re.search(r"\(MODEL:[ \t]*([^)]+)\),\s*Version\s+(\S+)", ver)
    if m:
        f.model, f.version = m.group(1).strip(), m.group(2)
    f.serial = _find(r"^System Serial#[ \t]*:[ \t]*(\S+)", _extra(outputs, 1))
    return f


def _parse_os10(outputs: list[str]) -> Facts:
    ver = outputs[0]
    f = Facts()
    f.version = _find(r"^OS Version:[ \t]*(\S+)", ver)
    f.model = _find(r"^System Type:[ \t]*(\S+)", ver)
    inv = _extra(outputs, 1)
    # Unit table: "* 1   S5248F-ON  0P1M1R  A00  TW-0P1M1R-28298-998-0012  9531XC2 ..." - the
    # service tag (Svc Tag) is what Dell support asks for.
    m = re.search(r"^\*?\s*1\s+\S+\s+\S+\s+\S+\s+\S+\s+(\w{7})\b", inv, re.M)
    f.serial = _first(_find(r"^Product Serial Number[ \t]*:[ \t]*(\S+)", inv), m.group(1) if m else None)
    return f


def _parse_exos(outputs: list[str]) -> Facts:
    ver = outputs[0]
    f = Facts()
    f.version = _find(r"^Image[ \t]*:[ \t]*(?:ExtremeXOS|Extreme Networks Switch Engine)\s+version\s+(\S+)",
                      ver)
    # "Switch      : 800616-00-02 1928G-12345 Rev 2.0 ..." or "Slot-1 : ..." on a stack
    f.serial = _find(r"^(?:Switch|Slot-1)\s*:\s*\S+\s+(\S+)\s+Rev", ver)
    switch = _extra(outputs, 1)
    f.model = _find(r"^System Type:[ \t]*(\S+)", switch)
    f.image = _find(r"^Image Booted:[ \t]*(\S+)", switch)
    return f


def _parse_routeros(outputs: list[str]) -> Facts:
    res = outputs[0]
    f = Facts()
    f.version = _find(r"^\s*version:[ \t]*(\S+)", res)
    f.model = _find(r"^\s*board-name:[ \t]*(.+?)\s*$", res)
    m_free = re.search(r"^\s*free-hdd-space:[ \t]*([\d.]+)\s*([KMG]i?B)?", res, re.M)
    m_total = re.search(r"^\s*total-hdd-space:[ \t]*([\d.]+)\s*([KMG]i?B)?", res, re.M)
    if m_free and m_total:
        f.flash_free, f.flash_total = _size(*m_free.groups()), _size(*m_total.groups())
    rb = _extra(outputs, 1)
    f.serial = _find(r"^\s*serial-number:[ \t]*(\S+)", rb)
    f.image = _first(_find(r"^\s*current-firmware:[ \t]*(\S+)", rb))
    f.image = f"RouterBOOT {f.image}" if f.image else None
    return f


def _parse_edgeos(outputs: list[str]) -> Facts:
    ver = outputs[0]
    f = Facts()
    f.version = _find(r"^Version:\s*v?(\S+)", ver)
    f.model = _find(r"^HW model:[ \t]*(.+?)\s*$", ver)
    f.serial = _find(r"^HW S/N:[ \t]*(\S+)", ver)
    return f


def _parse_vrp(outputs: list[str]) -> Facts:
    ver = outputs[0]
    f = Facts()
    # "VRP (R) software, Version 5.170 (S5735 V200R021C10SPC600)"
    m = re.search(r"VRP \(R\) software,\s*Version\s+(\S+)\s+\((\S+)\s+(V\d+R\d+\w*)\)", ver)
    if m:
        f.version, f.image = m.group(3), f"VRP {m.group(1)}"
    # "HUAWEI S5735-L48T4X-A1 Routing Switch uptime is ..." / "HUAWEI CE6881-48S6CQ uptime is"
    f.model = _find(r"^HUAWEI\s+(\S+)\s+.*uptime is", ver)
    f.serial = _find(r"^ESN of (?:slot|master chassis|chassis)\s*\S*[ \t]*:[ \t]*(\S+)", _extra(outputs, 1))
    return f


_PARSERS = {
    "cisco_ios": _parse_ios,
    "cisco_nxos": _parse_nxos,
    "cisco_asa": _parse_asa,
    "cisco_ftd": _parse_ftd,
    "cisco_xr": _parse_xr,
    "cisco_smb": _parse_smb,
    "allied_awplus": _parse_awplus,
    "arista_eos": _parse_eos,
    "juniper_junos": _parse_junos,
    "fortinet_fortios": _parse_fortios,
    "paloalto_panos": _parse_panos,
    "checkpoint_gaia": _parse_gaia,
    "aruba_aoscx": _parse_aoscx,
    "aruba_osswitch": _parse_osswitch,
    "aruba_aos8": _parse_aos8,
    "dell_os10": _parse_os10,
    "extreme_exos": _parse_exos,
    "mikrotik_routeros": _parse_routeros,
    "ubiquiti_edgeos": _parse_edgeos,
    "huawei_vrp": _parse_vrp,
}


def parse_facts(platform: str, outputs: list[str]) -> Facts:
    """Turn command outputs (in FACT_COMMANDS order) into Facts."""
    commands = FACT_COMMANDS[platform]
    outputs = [o.replace("\r\n", "\n").replace("\r", "\n") for o in outputs]
    if not outputs or _cli_error(outputs[0]):
        raise ValueError("Device rejected 'show version'")
    facts = _PARSERS[platform](outputs)
    for cmd, out in zip(commands[1:], outputs[1:]):
        if _cli_error(out):
            continue
        if cmd.startswith("dir"):
            _dir_space(out, facts)
        elif cmd == "show failover":
            facts.ha_role = _asa_failover(out)
    if not facts.version:
        raise ValueError("Could not find the software version in 'show version'")
    return facts


# --- version comparison -----------------------------------------------------

def version_key(version: str) -> tuple:
    """Split a version into comparable parts, so that 17.09.04a == 17.9.4a,
    9.16(4)23 > 9.16(4) and 15.2(7)E8 > 15.2(7)E3."""
    parts = re.findall(r"\d+|[A-Za-z]+", version or "")
    return tuple((0, int(p), "") if p.isdigit() else (1, 0, p.lower()) for p in parts)


def compare_versions(a: str, b: str) -> int:
    ka, kb = version_key(a), version_key(b)
    return (ka > kb) - (ka < kb)


def pattern_matches(pattern: str, model: str | None) -> bool:
    pattern = (pattern or "*").strip()
    if pattern == "*":
        return True
    return bool(model) and fnmatch.fnmatchcase(model.upper(), pattern.upper())


def best_standard(standards, platform: str, model: str | None):
    """The most specific standard for a device: platform must match, and the
    longest matching model pattern wins ("C9300-48*" beats "C9300-*" beats "*")."""
    candidates = [s for s in standards
                  if s.platform == platform and pattern_matches(s.model_pattern, model)]
    return max(candidates, key=lambda s: (s.model_pattern != "*", len(s.model_pattern)),
               default=None)


COMPLIANT, BEHIND, AHEAD, NO_STANDARD, UNKNOWN = (
    "compliant", "behind", "ahead", "no_standard", "unknown")


def compliance(current: str | None, target: str | None) -> str:
    if target is None:
        return NO_STANDARD
    if not current:
        return UNKNOWN
    c = compare_versions(current, target)
    return COMPLIANT if c == 0 else BEHIND if c < 0 else AHEAD


def vendor_for(platform: str) -> str:
    """Repository section for a platform key ('cisco_ios' -> 'Cisco')."""
    p = PLATFORMS.get(platform)
    return p.vendor if p else platform.split("_")[0].title()
