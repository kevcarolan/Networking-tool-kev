"""Supported device platforms. Adding a vendor = adding an entry here."""

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Platform:
    key: str
    label: str
    netmiko_type: str
    vendor: str = "Cisco"
    backup_commands: tuple[str, ...] = ("show running-config",)
    needs_enable: bool = True
    # Lines that change on every run (timestamps, checksums) and would make
    # every backup look like a config change.
    volatile_lines: tuple[str, ...] = field(default_factory=tuple)
    # (pattern, replacement) for values the device shows differently on every run,
    # e.g. FortiOS re-encrypts each secret with a new salt each time it is shown.
    masks: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    # False for the "SNMP only" types (UPS cards, PDUs, probes): never reached over SSH, so
    # no backups, version checks, port scans or upgrades; monitored with ping and SNMP only.
    ssh: bool = True

    def volatile_regex(self) -> re.Pattern | None:
        if not self.volatile_lines:
            return None
        return re.compile("|".join(f"(?:{p})" for p in self.volatile_lines))


# Text a device prints instead of output when it rejects a command, for every
# platform. Only the start of an output is checked.
CLI_ERRORS = (
    "% Invalid input", "% Incomplete command", "% Unknown command", "ERROR: % Invalid",
    "% Ambiguous command",
    "% Error: Unrecognized command",  # Dell OS10
    "Invalid input:",  # Aruba AOS-CX, ArubaOS-Switch
    "error: syntax error", "error: unknown command",  # Junos
    "Unknown action 0", "Command fail. Return code",  # FortiOS
    "Invalid syntax.", "Unknown command:",  # PAN-OS
    "CLINFR0329",  # Check Point Gaia clish: invalid command
    "bad command name", "expected end of command", "syntax error (line",  # RouterOS
    "Error: Unrecognized command", "Error: Wrong parameter",  # Huawei VRP
    "Invalid command:",  # EdgeOS
)


_IOS_VOLATILE = (
    r"^Building configuration",
    r"^Current configuration\s*:",
    r"^! Last configuration change at",
    r"^! NVRAM config last updated",
    r"^! No configuration change since last restart",
    r"^ntp clock-period",
)
_ASA_VOLATILE = (
    r"^Cryptochecksum:",
    r"^: Written by",
    r"^: Saved",
)

_FORTIOS_SECRETS = (r"(\s(?:ENC|SH2)\s)\S+", r"\1<encrypted>")

PLATFORMS: dict[str, Platform] = {p.key: p for p in (
    Platform("cisco_ios", "Cisco IOS / IOS-XE", "cisco_ios", volatile_lines=_IOS_VOLATILE),
    Platform("cisco_nxos", "Cisco NX-OS", "cisco_nxos", needs_enable=False,
             volatile_lines=(r"^!Time:", r"^!Running configuration last done at:",
                             r"^!Command: show running-config")),
    Platform("cisco_asa", "Cisco ASA / Firepower (ASA mode)", "cisco_asa",
             volatile_lines=_ASA_VOLATILE),
    Platform("cisco_ftd", "Cisco Firepower Threat Defense (FTD)", "cisco_ftd",
             needs_enable=False, volatile_lines=_ASA_VOLATILE),
    Platform("cisco_xr", "Cisco IOS-XR", "cisco_xr", needs_enable=False,
             volatile_lines=(r"^Building configuration", r"^!! Last configuration change at",
                             # XR prints the time before every command's output
                             r"^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) \w{3}\s+\d+ \d\d:\d\d:\d\d")),
    Platform("cisco_smb", "Cisco Catalyst 1200/1300, CBS, SG (small business)", "cisco_s300"),
    Platform("allied_awplus", "Allied Telesis AlliedWare Plus", "allied_telesis_awplus",
             vendor="Allied Telesis",
             volatile_lines=(r"^Building configuration", r"^Current configuration\s*:")),
    Platform("arista_eos", "Arista EOS", "arista_eos", vendor="Arista",
             volatile_lines=(r"^! Command: show running-config", r"^! Time:")),
    Platform("juniper_junos", "Juniper Junos (EX, QFX, MX, SRX)", "juniper_junos",
             vendor="Juniper", needs_enable=False,
             backup_commands=("show configuration | display set",),
             volatile_lines=(r"^## Last (?:commit|changed):",
                             r"^\{(?:master|backup|primary|secondary)(?::\d+)?\}$")),
    Platform("fortinet_fortios", "Fortinet FortiGate (FortiOS)", "fortinet", vendor="Fortinet",
             needs_enable=False, backup_commands=("show full-configuration",),
             volatile_lines=(r"^#conf_file_ver=", r"^#buildno=", r"^#global_vdom="),
             masks=(_FORTIOS_SECRETS,)),
    Platform("paloalto_panos", "Palo Alto PAN-OS", "paloalto_panos", vendor="Palo Alto",
             needs_enable=False,
             # 'set' format is far easier to compare than XML; it needs configure mode.
             backup_commands=("set cli config-output-format set", "configure", "show", "exit"),
             volatile_lines=(r"^\[edit\]$", r"^Entering configuration mode",
                             r"^Exiting configuration mode")),
    Platform("checkpoint_gaia", "Check Point Gaia (gateway OS)", "checkpoint_gaia",
             vendor="Check Point", needs_enable=False, backup_commands=("show configuration",),
             volatile_lines=(r"^# Exported by",)),
    Platform("aruba_aoscx", "HPE Aruba AOS-CX", "aruba_aoscx", vendor="HPE Aruba",
             needs_enable=False, volatile_lines=(r"^Current configuration:",)),
    Platform("aruba_osswitch", "HPE ArubaOS-Switch (ProCurve)", "hp_procurve", vendor="HPE Aruba",
             volatile_lines=(r"^Running configuration:",)),
    Platform("aruba_aos8", "HPE Aruba Mobility Controller / Conductor (AOS 8)", "aruba_os",
             vendor="HPE Aruba", volatile_lines=(r"^Building Configuration",)),
    Platform("dell_os10", "Dell SmartFabric OS10", "dell_os10", vendor="Dell",
             needs_enable=False, backup_commands=("show running-configuration",),
             volatile_lines=(r"^! Last configuration change at",)),
    Platform("extreme_exos", "Extreme EXOS / Switch Engine", "extreme_exos", vendor="Extreme",
             needs_enable=False, backup_commands=("show configuration",)),
    Platform("mikrotik_routeros", "MikroTik RouterOS", "mikrotik_routeros", vendor="MikroTik",
             needs_enable=False, backup_commands=("/export terse",),
             volatile_lines=(r"^# .* by RouterOS",)),
    Platform("ubiquiti_edgeos", "Ubiquiti EdgeRouter (EdgeOS)", "ubiquiti_edgerouter",
             vendor="Ubiquiti", needs_enable=False,
             backup_commands=("show configuration commands",)),
    Platform("huawei_vrp", "Huawei VRP (S, CloudEngine, AR)", "huawei", vendor="Huawei",
             needs_enable=False, backup_commands=("display current-configuration",),
             volatile_lines=(r"^!Last configuration was (?:updated|saved) at",)),
    # SNMP only: monitored with ping, SNMP and custom sensors; nothing is read over SSH.
    Platform("snmp_ups", "UPS (SNMP only)", "", vendor="SNMP only", backup_commands=(),
             needs_enable=False, ssh=False),
    Platform("snmp_pdu", "PDU (SNMP only)", "", vendor="SNMP only", backup_commands=(),
             needs_enable=False, ssh=False),
    Platform("snmp_env", "Environment probe (SNMP only)", "", vendor="SNMP only",
             backup_commands=(), needs_enable=False, ssh=False),
    Platform("snmp_other", "Other SNMP device", "", vendor="SNMP only", backup_commands=(),
             needs_enable=False, ssh=False),
)}

SNMP_ONLY = frozenset(k for k, p in PLATFORMS.items() if not p.ssh)


def uses_ssh(platform: str) -> bool:
    """False for the SNMP-only types: no backups, version checks, scans or upgrades."""
    return platform not in SNMP_ONLY
