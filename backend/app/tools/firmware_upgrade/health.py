"""Health checks and the before/after snapshot for the platforms other than Cisco IOS.

Each platform has a profile: for every check, the read-only command(s) it needs and a
reader for their output. The checks are the same everywhere:

    env        fans, power supplies and temperature OK                        (blocks)
    alarms     no critical or major alarms; minor ones warn                    (blocks)
    modules    every module, stack, virtual-chassis or line-card member is up (blocks)
    cpu, mem   CPU and memory below the warning limits                         (warns)
    unsaved    no unsaved configuration                                        (blocks)
    reload     why the device last restarted (a crash or power loss warns)     (info)

and the snapshot, compared after the upgrade (checks.compare_snapshots):

    interfaces  interface -> up / down / admin-down
    neighbors   'local port > neighbour' from LLDP (or CDP, or MikroTik's discovery)
    lag         port-channel / LAG / trunk / bundle -> the member ports carrying traffic

A command a device doesn't support is skipped, not failed. The readers were written
from vendor documentation; each is confirmed on real kit with ``netops-cli capture``
(docs/upgrade-lab-tests.md) and its sample in app/demo/health_samples.py replaced.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field

# --- small helpers -------------------------------------------------------------------

_NUM = r"(\d+(?:\.\d+)?)"


def _float(text: str) -> float:
    return float(text.replace(",", ""))


def idle_cpu(out: str) -> int | None:
    """CPU use from an 'idle' figure: '%Cpu(s): ... 95.3 id', '94.70% idle', 'Idle 92 percent',
    'idle 93.6%'."""
    m = (re.search(rf"{_NUM}\s*%?\s*id(?:le)?\b", out) or
         re.search(rf"\bidle\s+{_NUM}\s*(?:%|percent)", out, re.I))
    return round(100 - float(m.group(1))) if m else None


def percent_after(label: str) -> Callable[[str], int | None]:
    """The percentage after a label: 'CPU Usage : 8%', 'cpu-load: 3%'."""
    def read(out: str) -> int | None:
        m = re.search(rf"{label}\D{{0,20}}?{_NUM}\s*(?:%|percent)", out, re.I)
        return round(float(m.group(1))) if m else None
    return read


def used_of_total(total: str, used: str | None = None, free: str | None = None
                  ) -> Callable[[str], int | None]:
    """Memory use from a total and a used (or free) figure, in the same unit."""
    def read(out: str) -> int | None:
        t = re.search(rf"{total}\D{{0,15}}?([\d,]+(?:\.\d+)?)", out, re.I)
        if not t or not _float(t.group(1)):
            return None
        if used:
            u = re.search(rf"{used}\D{{0,15}}?([\d,]+(?:\.\d+)?)", out, re.I)
            if u:
                return round(100 * _float(u.group(1)) / _float(t.group(1)))
        if free:
            f = re.search(rf"{free}\D{{0,15}}?([\d,]+(?:\.\d+)?)", out, re.I)
            if f:
                return round(100 - 100 * _float(f.group(1)) / _float(t.group(1)))
        return None
    return read


def number_after(label: str) -> Callable[[str], int | None]:
    """A whole number after a label: 'CPU Util (%)     : 3'."""
    def read(out: str) -> int | None:
        m = re.search(rf"{label}\s*{_NUM}", out, re.I)
        return round(float(m.group(1))) if m else None
    return read


def top_memory(out: str) -> int | None:
    """Memory use from top's 'KiB Mem : 8000000 total, 6000000 free, 1500000 used, ...'."""
    m = re.search(r"Mem\s*:\s*([\d.]+)\s*total,\s*([\d.]+)\s*free", out)
    if not m or not float(m.group(1)):
        return None
    return round(100 - 100 * float(m.group(2)) / float(m.group(1)))


def first_of(*readers: Callable[[str], int | None]) -> Callable[[str], int | None]:
    def read(out: str) -> int | None:
        for r in readers:
            v = r(out)
            if v is not None:
                return v
        return None
    return read


# --- environment and alarms ------------------------------------------------------------

_ENV_BAD = re.compile(r"\b(fail(?:ed|ure|ing)?|faulty|faulted|fault|bad|not\s*ok|power\s*loss"
                      r"|shut\s*down|shutdown|overheat(?:ed|ing)?|abnormal|not\s*supply(?:ing)?"
                      r"|powered\s*off|down|alarm(?:ed)?|critical)\b", re.I)
_ENV_SKIP = re.compile(r"threshold|range|limit|airflow|direction|^0\s*/\s*\d+\b", re.I)
_HEADER_WORDS = re.compile(r"\b(status|description|model|sensor|state|reading|speed|type|"
                           r"slot|unit|class|item|measurement|alert|critical|major|minor)\b", re.I)


def env_faults(out: str) -> list[str]:
    """Lines reporting a fan, power or temperature fault. Header lines (no figures, only
    column names) and threshold columns are left out."""
    faults = []
    for line in out.splitlines():
        text = line.strip()
        if not text:
            continue
        m = re.search(r"status is:\s*(\S+)", text, re.I)  # Arista 'System cooling status is: Ok'
        if m:
            if m.group(1).lower() not in ("ok", "normal", "good"):
                faults.append(text)
            continue
        if not re.search(r"\d", text) and len(_HEADER_WORDS.findall(text)) >= 2:
            continue  # a column header
        if _ENV_SKIP.search(text):
            continue
        if _ENV_BAD.search(text):
            faults.append(text)
    return faults


def alarm_rows(out: str) -> dict[str, list[str]]:
    """Active alarms by severity: 'serious' (critical, major) and 'minor' (minor, warning).
    Rows without a figure are headers ('Alarm time Class Description'), except a
    'Severity: major' line."""
    serious, minor = [], []
    for line in out.splitlines():
        text = line.strip()
        severity_line = re.match(r"severity\s*[:=]", text, re.I)  # Dell OS10 lists one per alarm
        if not text or re.search(r"alarms? currently active", text, re.I) or (
                not re.search(r"\d", text) and not severity_line):
            continue
        if re.search(r"\b(critical|major)\b", text, re.I):
            serious.append(text)
        elif re.search(r"\b(minor|warning)\b", text, re.I):
            minor.append(text)
    return {"serious": serious, "minor": minor}


# --- modules, stack and chassis members ----------------------------------------------------

def table_states(pattern: str, ok: tuple[str, ...]) -> Callable[[str], dict[str, str]]:
    """Member -> state, from rows matching ``pattern`` (groups: name, state). A state not in
    ``ok`` is reported as a problem."""
    rx = re.compile(pattern, re.M | re.I)
    oks = {o.lower() for o in ok}

    def read(out: str) -> dict[str, str]:
        rows = {m.group(1): m.group(2) for m in rx.finditer(out)}
        return {k: ("ok" if v.lower() in oks else v) for k, v in rows.items()}
    return read


# --- interfaces ----------------------------------------------------------------------------

def interface_table(pattern: str, up: tuple[str, ...], admin_down: tuple[str, ...] = (),
                    state_group: int = 2) -> Callable[[str], dict[str, str]]:
    """Interface -> up / down / admin-down, from rows matching ``pattern`` (group 1 the
    name; ``state_group`` the state word)."""
    rx = re.compile(pattern, re.M | re.I)
    ups = {u.lower() for u in up}
    admins = {a.lower() for a in admin_down}

    def read(out: str) -> dict[str, str]:
        result = {}
        for m in rx.finditer(out):
            state = m.group(state_group).lower()
            result[m.group(1)] = ("up" if state in ups else
                                  "admin-down" if state in admins else "down")
        return result
    return read


def junos_terse(out: str) -> dict[str, str]:
    """'ge-0/0/1   up    down': admin then link; logical units (ge-0/0/1.0) left out."""
    result = {}
    for m in re.finditer(r"^((?:ge|xe|et|mge|ae|em|fxp|me)-?\d[\w/:-]*)\s+(up|down)\s+(up|down)",
                         out, re.M):
        name, admin, link = m.groups()
        result[name] = "admin-down" if admin == "down" else ("up" if link == "up" else "down")
    return result


def vrp_brief(out: str) -> dict[str, str]:
    """'GigabitEthernet0/0/1  up  up' (PHY, protocol); '*down' is shut down."""
    result = {}
    for m in re.finditer(r"^\s*((?:\w*Ethernet|Eth-Trunk|XGE|GE|40GE|100GE|MEth)[\d/.]+)"
                         r"(?:\(\w+\))?\s+(\*?down|up|\^down)\s+(up|down|\*down)", out, re.M):
        name, phy, proto = m.groups()
        result[name] = ("admin-down" if phy.startswith("*") else
                        "up" if phy == "up" and proto == "up" else "down")
    return result


def routeros_interfaces(out: str) -> dict[str, str]:
    """'/interface print terse': flags R (running) and X (disabled), then name=..."""
    result = {}
    for m in re.finditer(r"^\s*\d+\s+([A-Z ]*?)\s*name=(\S+)", out, re.M):
        flags, name = m.groups()
        result[name] = "admin-down" if "X" in flags else ("up" if "R" in flags else "down")
    return result


# --- neighbours ------------------------------------------------------------------------------

def neighbour_table(pattern: str, local: int = 1, remote: int = 2) -> Callable[[str], list[str]]:
    rx = re.compile(pattern, re.M | re.I)

    def read(out: str) -> list[str]:
        return sorted({f"{m.group(local)} > {m.group(remote).split('.')[0]}"
                       for m in rx.finditer(out)})
    return read


def edgeos_lldp(out: str) -> list[str]:
    pairs = []
    for block in re.split(r"^-{5,}\s*$", out, flags=re.M):
        intf = re.search(r"Interface:\s+([^,\s]+)", block)
        name = re.search(r"SysName:\s+(\S+)", block)
        if intf and name:
            pairs.append(f"{intf.group(1)} > {name.group(1).split('.')[0]}")
    return sorted(set(pairs))


# --- port-channels / LAGs ----------------------------------------------------------------------

def members_in_flags(pattern: str, member_flag: str = "P") -> Callable[[str], dict[str, list[str]]]:
    """'Po1(SU)  ...  Eth1/49(P) Eth1/50(P)': the members flagged as carrying traffic."""
    rx = re.compile(pattern, re.M | re.I)
    member = re.compile(rf"(\S+?)\([^)]*{member_flag}[^)]*\)")

    def read(out: str) -> dict[str, list[str]]:
        return {m.group(1): sorted(member.findall(m.group(2))) for m in rx.finditer(out)}
    return read


def junos_lacp(out: str) -> dict[str, list[str]]:
    """'show lacp interfaces': members whose mux state is Collecting distributing."""
    result: dict[str, list[str]] = {}
    for block in re.split(r"^(?=Aggregated interface:)", out, flags=re.M):
        name = re.search(r"Aggregated interface:\s*(\S+)", block)
        if not name:
            continue
        mux = re.findall(r"^\s*((?:ge|xe|et|mge)-\S+)\s+.*Collecting distributing",
                         block, re.M)
        result[name.group(1)] = sorted(set(mux))
    return result


def vrp_trunks(out: str) -> dict[str, list[str]]:
    """'display eth-trunk': each Eth-Trunk and its member ports that are Up."""
    result: dict[str, list[str]] = {}
    for block in re.split(r"^(?=Eth-Trunk\d+'s state information)", out, flags=re.M):
        name = re.search(r"^(Eth-Trunk\d+)'s state information", block, re.M)
        if name:
            result[name.group(1)] = sorted(re.findall(
                r"^((?:\w*Ethernet|XGE|GE)[\d/]+)\s+Up\b", block, re.M))
    return result


def osswitch_lacp(out: str) -> dict[str, list[str]]:
    """'show lacp': 'Port  LACP  Trunk  Port Status  Partner  Status' rows."""
    result: dict[str, list[str]] = {}
    for m in re.finditer(r"^\s*(\S+)\s+Active\s+(Trk\d+)\s+(Up|Down)\s+\S+\s+(Success|Failure)",
                         out, re.M):
        port, trunk, status, lacp = m.groups()
        result.setdefault(trunk, [])
        if status == "Up" and lacp == "Success":
            result[trunk].append(port)
    return {k: sorted(v) for k, v in result.items()}


def awplus_etherchannel(out: str) -> dict[str, list[str]]:
    """'show etherchannel': 'Aggregator po1 ...' then 'Link: port1.0.49 (IfIndex 5049) sync: 1'."""
    result: dict[str, list[str]] = {}
    for block in re.split(r"^(?=\s*Aggregator\s)", out, flags=re.M):
        name = re.search(r"Aggregator\s+(\S+)", block)
        if name:
            result[name.group(1)] = sorted(re.findall(r"Link:\s*(\S+).*?sync:\s*1", block))
    return result


def xr_bundles(out: str) -> dict[str, list[str]]:
    """'show bundle brief': only counts are listed (links act/stdby/cfgd), so 'link 1..n'
    stands for the n active members."""
    return {m.group(1): [f"link {i + 1}" for i in range(int(m.group(2)))]
            for m in re.finditer(r"^(BE\d+)\s.*?\b(?:Up|Down)\b.*?(\d+)\s*/\s*\d+\s*/\s*\d+",
                                 out, re.M)}


def exos_sharing(out: str) -> dict[str, list[str]]:
    """'show sharing': a group's first row names its master port and LACP/Static; every
    member row ends 'port  Y/N  link-state  transitions' (link state A = active)."""
    result: dict[str, list[str]] = {}
    master = None
    for line in out.splitlines():
        m = re.match(r"^\s*(\d+(?::\d+)?)\s+(?:\d+(?::\d+)?\s+)?(?:LACP|Static)\b", line)
        if m:
            master = m.group(1)
            result.setdefault(master, [])
        mm = re.search(r"(\d+(?::\d+)?)\s+[YN-]\s+(\S+)\s+\d+\s*$", line)
        if mm and master is not None and mm.group(2) == "A":
            result[master].append(mm.group(1))
    return {k: sorted(v) for k, v in result.items()}


# --- unsaved configuration and restart cause -------------------------------------------------

def diff_lines(out: str) -> int | None:
    """Changed lines in a running-vs-startup diff; an empty answer means none."""
    lines = [ln for ln in out.splitlines()
             if re.match(r"^\s*[+-]\s*\S", ln) and not re.match(r"^\s*(\+\+\+|---)", ln)]
    return len(lines) if lines or not out.strip() else 0


def osswitch_config_status(out: str) -> int | None:
    if re.search(r"is the same as the startup|matches the saved", out, re.I):
        return 0
    if re.search(r"needs to be saved|has been changed|differs", out, re.I):
        return 1
    return None


def reason_after(pattern: str) -> Callable[[str], str | None]:
    rx = re.compile(pattern, re.M | re.I)

    def read(out: str) -> str | None:
        m = rx.search(out)
        return m.group(1).strip()[:200] if m else None
    return read


def eos_reload_cause(out: str) -> str | None:
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    for i, ln in enumerate(lines):
        if re.match(r"Reload Cause \d+:", ln) and i + 1 < len(lines):
            nxt = lines[i + 1] if not set(lines[i + 1]) <= {"-"} else (lines[i + 2] if i + 2 < len(lines) else "")
            return nxt[:200]
    return lines[0][:200] if lines else None


CRASH = re.compile(r"crash|watchdog|exception|panic|power\s*(?:fail|cycle|loss|outage)"
                   r"|unexpected|kernel|fatal|hardware\s*(?:error|failure)|parity", re.I)


# --- the profiles ------------------------------------------------------------------------------

@dataclass(frozen=True)
class Check:
    commands: tuple[str, ...]
    read: Callable[[str], object]


@dataclass(frozen=True)
class Profile:
    checks: dict[str, Check] = field(default_factory=dict)

    def commands(self) -> dict[str, str]:
        """key -> command, for checks.commands_for (keys 'h:<check>' or 'h:<check>:<n>')."""
        out = {}
        for name, c in self.checks.items():
            for i, cmd in enumerate(c.commands):
                out[f"h:{name}" if i == 0 else f"h:{name}:{i}"] = cmd
        return out


def C(*commands: str, read: Callable) -> Check:  # noqa: N802 - reads as a table below
    return Check(tuple(commands), read)


PROFILES: dict[str, Profile] = {
    "arista_eos": Profile({
        "env": C("show system environment all", read=env_faults),
        "modules": C("show module", read=table_states(
            r"^\s*(\d+|Fan\S*|PowerSupply\S*)\s+(Ok|Active|Standby|Failed|Disabled|Unknown|"
            r"PoweredOff|Inserted|Upgrading)\s+", ("Ok", "Active", "Standby"))),
        "cpu": C("show processes top once", read=idle_cpu),
        "mem": C("show processes top once", read=top_memory),
        "unsaved": C("show running-config diffs", read=diff_lines),
        "reload": C("show reload cause", read=eos_reload_cause),
        "interfaces": C("show interfaces status", read=interface_table(
            r"^((?:Et|Ma|Po)\S+)\s+.*?\b(connected|notconnect|disabled|errdisabled|inactive)\b",
            up=("connected",), admin_down=("disabled",))),
        "neighbors": C("show lldp neighbors", read=neighbour_table(
            r"^((?:Et|Ma)\S+)\s+(\S+)\s+\S+\s+\d+\s*$")),
        "lag": C("show port-channel summary", read=members_in_flags(
            r"^\s*(Po\d+)\(\w+\)\s+\S+\s+(.*)$")),
    }),
    "cisco_nxos": Profile({
        "env": C("show environment", read=env_faults),
        "modules": C("show module", read=table_states(
            r"^\s*(\d+)\s+\d+\s+.+?\s(active|ok|standby|powered-dn|failure|testing|err-pwd-dn|"
            r"pwr-denied|upgrading)\s*\*?\s*$", ("active", "ok", "standby"))),
        "cpu": C("show system resources", read=idle_cpu),
        "mem": C("show system resources", read=used_of_total(r"Memory usage:", r"K total,", None)),
        "unsaved": C("show running-config diff", read=diff_lines),
        "reload": C("show system reset-reason", read=reason_after(r"Reason:\s*(.+)$")),
        "interfaces": C("show interface brief", read=interface_table(
            r"^((?:Eth|Po|mgmt|Vlan)\S*)\s+.*?\b(up|down)\b", up=("up",))),
        "neighbors": C("show lldp neighbors", read=neighbour_table(
            r"^(\S+)\s+((?:Eth|mgmt)\S+)\s+\d+\s+", local=2, remote=1)),
        "lag": C("show port-channel summary", read=members_in_flags(
            r"^\s*\d+\s+(Po\d+)\(\w+\)\s+\S+\s+\S+\s+(.*)$")),
    }),
    "juniper_junos": Profile({
        "env": C("show chassis environment", read=env_faults),
        "alarms": C("show chassis alarms", "show system alarms", read=alarm_rows),
        "modules": C("show virtual-chassis", read=table_states(
            r"^(\d+)\s+\(FPC\s*\d+\)\s+(\S+)", ("Prsnt",))),
        "cpu": C("show chassis routing-engine", read=idle_cpu),
        "mem": C("show chassis routing-engine", read=percent_after(r"Memory utilization")),
        "reload": C("show chassis routing-engine", read=reason_after(r"Last reboot reason\s+(.+)$")),
        "interfaces": C("show interfaces terse", read=junos_terse),
        "neighbors": C("show lldp neighbors", read=neighbour_table(
            r"^(\S+-\d+/\d+/\d+)\s+(?:\S+\s+)?[0-9a-f]{2}(?::[0-9a-f]{2}){5}\s+.*?\s(\S+)\s*$")),
        "lag": C("show lacp interfaces", read=junos_lacp),
    }),
    "aruba_osswitch": Profile({
        "env": C("show system power-supply", "show system fans", read=env_faults),
        "modules": C("show stacking", read=table_states(
            r"^\s*(\d+)\s+[0-9a-f]{6}-[0-9a-f]{6}\s+.+?\s+\d+\s+(\S+)\s*$",
            ("Commander", "Standby", "Member"))),
        "cpu": C("show system", read=number_after(r"CPU Util \(%\)\s*:")),
        "mem": C("show system", read=used_of_total(r"Memory\s+-\s+Total\s*:", None, r"Free\s*:")),
        "unsaved": C("show config status", read=osswitch_config_status),
        "reload": C("show boot-history", read=reason_after(r"Boot Reason:?\s*(.+)$")),
        "interfaces": C("show interfaces brief", read=interface_table(
            r"^\s*(\S+)\s+\S+\s*\|\s*\S+\s+(?:Yes|No)\s+(Up|Down)\b", up=("up",))),
        "neighbors": C("show lldp info remote-device", read=neighbour_table(
            r"^\s*(\S+)\s*\|\s*(?:[0-9a-f]{2}\s){5}[0-9a-f]{2}\s+\S+\s+\S+\s+(\S+)\s*$")),
        "lag": C("show lacp", read=osswitch_lacp),
    }),
    "aruba_aos8": Profile({
        "env": C("show inventory", read=env_faults),
        "alarms": C("show alarms all", read=alarm_rows),
        "cpu": C("show cpuload", read=idle_cpu),
        "mem": C("show memory", read=used_of_total(r"total:", r"used:", None)),
        "reload": C("show switchinfo", read=reason_after(r"Reboot Cause:\s*(.+)$")),
        "interfaces": C("show port status", read=interface_table(
            r"^((?:GE|TE|XE)\S+)\s+.*?\b(Enabled|Disabled)\s+(Up|Down)\b", up=("up",),
            state_group=3)),
        "neighbors": C("show lldp neighbor", read=neighbour_table(
            r"^((?:GE|TE|XE)\S+)\s+(\S+)\s+")),
    }),
    "dell_os10": Profile({
        "env": C("show environment", read=env_faults),
        "alarms": C("show alarms", read=alarm_rows),
        "cpu": C("show processes node-id 1", read=idle_cpu),
        "mem": C("show processes node-id 1", read=top_memory),
        "unsaved": C("show diff running-configuration startup-configuration", read=diff_lines),
        "interfaces": C("show interface status", read=interface_table(
            r"^(Eth \d\S*)\s+.*?\b(up|down)\b", up=("up",))),
        "neighbors": C("show lldp neighbors", read=neighbour_table(
            r"^((?:ethernet|mgmt)\S+)\s+(\S+)\s+\S+\s+[0-9a-f]{2}(?::[0-9a-f]{2}){5}")),
        "lag": C("show port-channel summary", read=members_in_flags(
            r"^\s*\d+\s+(port-channel\d+)\s*\(\w+\)\s+\S+\s+\S+\s+(.*)$")),
    }),
    "extreme_exos": Profile({
        "env": C("show power", "show fans", read=env_faults),
        "modules": C("show stacking", read=table_states(
            r"^\*?\s*[0-9a-f]{2}(?::[0-9a-f]{2}){5}\s+(\d+)\s+(\S+)", ("Active",))),
        "cpu": C("show cpu-monitoring", read=lambda out: (lambda m: round(float(m.group(1))) if m else None)(
            re.search(r"^\s*System\s+(?:n/a\s+)*(\d+(?:\.\d+)?)", out, re.M))),
        "mem": C("show memory", read=used_of_total(r"Total DRAM \(KB\):", None, r"Free\s*\(KB\):")),
        "interfaces": C("show ports no-refresh", read=interface_table(
            r"^\s*(\d+(?::\d+)?)\s+.*?\b(E|D)\s+(A|R|NP|L|D)\b", up=("a",), state_group=3)),
        "neighbors": C("show lldp neighbors", read=neighbour_table(
            r"^(\d+(?::\d+)?)\s+[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}\s+\S+\s+\d+\s+\d+\s+(\S+)")),
        "lag": C("show sharing", read=exos_sharing),
    }),
    "huawei_vrp": Profile({
        "env": C("display power", "display fan", read=env_faults),
        "alarms": C("display alarm active", read=alarm_rows),
        "modules": C("display device", read=table_states(
            r"^\s*(\d+)\s+\S+\s+\S+\s+Present\s+\S+\s+\S+\s+(Normal|Abnormal)", ("Normal",))),
        "cpu": C("display cpu-usage", read=percent_after(r"CPU Usage\s*:")),
        "mem": C("display memory-usage", read=percent_after(r"Memory Using Percentage Is:")),
        "reload": C("display reboot-info", read=reason_after(
            r"^\s*\d+\s+(\S+)\s+\d{4}[-/]\d{2}[-/]\d{2}")),
        "interfaces": C("display interface brief", read=vrp_brief),
        "neighbors": C("display lldp neighbor brief", read=neighbour_table(
            r"^(\S+\d/\d+/\d+)\s+(\S+)\s+\S+\s+\d+\s*$")),
        "lag": C("display eth-trunk", read=vrp_trunks),
    }),
    "cisco_xr": Profile({
        "env": C("show environment power", "show environment fan", read=env_faults),
        "alarms": C("show alarms brief system active", read=alarm_rows),
        "modules": C("show platform", read=table_states(
            r"^(\d+/\S+)\s+\S+\s+(IOS XR RUN|OPERATIONAL|POWERED_OFF|FAILED|BOOTING|PRESENT)",
            ("IOS XR RUN", "OPERATIONAL"))),
        "cpu": C("show processes cpu | include CPU utilization", read=lambda out: (
            lambda m: int(m.group(1)) if m else None)(re.search(r"five minutes:\s*(\d+)%", out))),
        "mem": C("show memory summary", read=lambda out: (lambda m: round(
            100 - 100 * float(m.group(2)) / float(m.group(1))) if m and float(m.group(1)) else None)(
            re.search(r"Physical Memory:\s*([\d.]+)M total \(([\d.]+)M available\)", out))),
        "interfaces": C("show ipv4 interface brief", read=interface_table(
            r"^(\S+?)\s+\S+\s+(Up|Down|Shutdown)\s+(Up|Down)", up=("up",),
            admin_down=("shutdown",))),
        "neighbors": C("show lldp neighbors", read=neighbour_table(
            r"^(\S+)\s+((?:Gi|Te|Hu|Fo|Mg|TF)\S+)\s+\d+\s+", local=2, remote=1)),
        "lag": C("show bundle brief", read=xr_bundles),
    }),
    "allied_awplus": Profile({
        "env": C("show system environment", read=env_faults),
        "modules": C("show stack", read=table_states(
            r"^\s*(\d+)\s+\S+\s+[0-9a-f]{4}\.[0-9a-f]{4}\.[0-9a-f]{4}\s+\d+\s+(\S+)",
            ("Ready",))),
        "cpu": C("show cpu", read=percent_after(r"60 seconds:")),
        "mem": C("show memory", read=used_of_total(r"RAM total:", None, r"free:")),
        "reload": C("show reboot history", read=reason_after(
            r"^\s*\d{4}-\d{2}-\d{2}\s+\S+\s+\S+\s+(.+)$")),
        "interfaces": C("show interface brief", read=interface_table(
            r"^((?:port|po|sa|vlan|eth)\S+)\s+(admin up|admin down|up|down)\s+(running|down)",
            up=("running",), state_group=3)),
        "neighbors": C("show lldp neighbors", read=neighbour_table(
            r"^(port\S+)\s+[0-9a-f]{4}\.[0-9a-f]{4}\.[0-9a-f]{4}\s+\S+\s+\d+\s+(\S+)")),
        "lag": C("show etherchannel", read=awplus_etherchannel),
    }),
    "mikrotik_routeros": Profile({
        "env": C("/system health print", read=env_faults),
        "cpu": C("/system resource print", read=percent_after(r"cpu-load:")),
        "mem": C("/system resource print", read=lambda out: (lambda f, t: round(
            100 - 100 * f / t) if f is not None and t else None)(
            _mib(re.search(r"free-memory:\s*([\d.]+)(\w+)", out)),
            _mib(re.search(r"total-memory:\s*([\d.]+)(\w+)", out)))),
        "interfaces": C("/interface print terse", read=routeros_interfaces),
        "neighbors": C("/ip neighbor print terse", read=neighbour_table(
            r"interface=(\S+).*?identity=(\S+)")),
    }),
    "ubiquiti_edgeos": Profile({
        "mem": C("show system memory", read=used_of_total(r"Total:", r"Used:", None)),
        "interfaces": C("show interfaces", read=interface_table(
            r"^((?:eth|switch|pppoe|bond)\S*)\s+\S+\s+(u|A|D)/(u|D)\b", up=("u",),
            state_group=3)),
        "neighbors": C("show lldp neighbors", read=edgeos_lldp),
    }),
}


def _mib(m) -> float | None:
    if not m:
        return None
    n, unit = float(m.group(1)), m.group(2).lower()
    return n * {"kib": 1 / 1024, "mib": 1, "gib": 1024}.get(unit, 1)


def profile(platform: str) -> Profile | None:
    return PROFILES.get(platform)


def read(platform: str, outputs: dict[str, str],
         unsupported: Callable[[str | None], bool]) -> dict[str, object]:
    """Each check's reading from the job's outputs; a check whose commands all failed
    (not supported, no answer) or whose output couldn't be read is left out."""
    prof = profile(platform)
    if not prof:
        return {}
    keys = prof.commands()
    result: dict[str, object] = {}
    for name, check in prof.checks.items():
        outs = [outputs.get(k) for k in keys if k == f"h:{name}" or k.startswith(f"h:{name}:")]
        good = [o for o in outs if not unsupported(o)]
        if not good:
            continue
        try:
            value = check.read("\n".join(good))
        except (ValueError, ZeroDivisionError, IndexError):
            value = None
        if value is not None:
            result[name] = value
    return result
