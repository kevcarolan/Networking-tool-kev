"""Where each circuit really is: reading MAC and ARP tables, and matching them to the list.

Pure parsing and rules - no SSH and no database - so it can be tested with sample
output. scan.py (the weekly scan) and the upgrade jobs run the commands; store.py keeps
the results.

A MAC address is "on" the switch port where it is learned at the edge. Every switch on
the way also learns it on its uplink, so entries on uplinks are ignored when locating a
circuit. An uplink is a port-channel (or one of its members), or a port whose CDP/LLDP
neighbour is a switch or router. Phones and wireless access points are *not* uplinks:
the device behind a phone is still on that port.
"""

import re
from dataclasses import dataclass, field

from app.core.platforms import CLI_ERRORS
from app.tools.circuits.importer import normalize_mac, normalize_port

# Read-only commands per platform. Keys: mac, arp, cdp, lldp (neighbour detail),
# lldp_table (one line per neighbour), mt_neighbor (MikroTik), pc (port-channels).
# Firewalls and routers only have an ARP table.
COMMANDS: dict[str, dict[str, str]] = {
    "cisco_ios": {"mac": "show mac address-table", "arp": "show ip arp",
                  "cdp": "show cdp neighbors detail", "lldp": "show lldp neighbors detail",
                  "pc": "show etherchannel summary"},
    "cisco_nxos": {"mac": "show mac address-table", "arp": "show ip arp vrf all",
                   "cdp": "show cdp neighbors detail", "lldp": "show lldp neighbors detail",
                   "pc": "show port-channel summary"},
    "allied_awplus": {"mac": "show mac address-table", "arp": "show arp",
                      "lldp": "show lldp neighbors detail"},
    "cisco_asa": {"arp": "show arp"},
    "cisco_ftd": {"arp": "show arp"},
    "cisco_xr": {"arp": "show arp vrf all"},
    "cisco_smb": {"mac": "show mac address-table", "arp": "show arp",
                  "lldp_table": "show lldp neighbors"},
    "arista_eos": {"mac": "show mac address-table", "arp": "show ip arp vrf all",
                   "lldp": "show lldp neighbors detail"},
    "juniper_junos": {"mac": "show ethernet-switching table", "arp": "show arp no-resolve",
                      "lldp_table": "show lldp neighbors"},
    "fortinet_fortios": {"arp": "get system arp"},
    "paloalto_panos": {"arp": "show arp all"},
    "checkpoint_gaia": {"arp": "show arp dynamic all"},
    "aruba_aoscx": {"mac": "show mac-address-table", "arp": "show arp all-vrfs",
                    "lldp": "show lldp neighbor-info detail"},
    "aruba_osswitch": {"mac": "show mac-address", "arp": "show arp",
                       "lldp": "show lldp info remote-device detail"},
    "aruba_aos8": {"arp": "show arp"},
    "dell_os10": {"mac": "show mac address-table", "arp": "show ip arp",
                  "lldp": "show lldp neighbors detail"},
    "extreme_exos": {"mac": "show fdb", "arp": "show iparp",
                     "lldp": "show lldp neighbors detailed"},
    "mikrotik_routeros": {"mac": "/interface bridge host print terse",
                          "arp": "/ip arp print terse", "mt_neighbor": "/ip neighbor print terse"},
    "ubiquiti_edgeos": {"arp": "show arp"},
    "huawei_vrp": {"mac": "display mac-address", "arp": "display arp all",
                   "lldp": "display lldp neighbor"},
}

_CLI_ERRORS = CLI_ERRORS + (
    "% Invalid command", "Invalid command", "% Error", "error: ",
    "% LLDP is not enabled", "% CDP is not enabled", "CDP is not enabled",
    "LLDP is not enabled", "Error: LLDP is disabled")

_MAC_TEXT = (r"[0-9a-fA-F]{4}\.[0-9a-fA-F]{4}\.[0-9a-fA-F]{4}"  # Cisco 0011.2233.4455
             r"|[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"  # Huawei 0011-2233-4455
             r"|[0-9a-fA-F]{6}-[0-9a-fA-F]{6}"  # ArubaOS-Switch 001122-334455
             r"|[0-9a-fA-F]{2}(?:[:-][0-9a-fA-F]{2}){5}")  # 00:11:22:33:44:55
_MAC = re.compile(rf"\b({_MAC_TEXT})\b")
_IPV4 = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")
# An interface name: starts with a letter, contains a digit (Gi1/0/5, Eth1/5, port1.0.1, Po10)
_INTF = re.compile(r"^[A-Za-z][A-Za-z-]*\d[\w/.:-]*$")
_NOT_PORTS = ("vlan", "cpu", "router", "switch", "drop", "sup-", "nve", "peer-link")


def commands_for(platform: str) -> dict[str, str]:
    return dict(COMMANDS.get(platform, {}))


def failed(out: str | None) -> bool:
    """No output, or the device rejected the command."""
    return out is None or any(m in out[:400] for m in _CLI_ERRORS)


@dataclass
class MacEntry:
    mac: str  # normalised aa:bb:cc:dd:ee:ff
    vlan: str
    port: str  # as the device shows it
    port_norm: str
    uplink: bool = False


@dataclass
class DeviceRead:
    """What one device reported. None = that table couldn't be read (keep the old one)."""
    macs: list[MacEntry] | None = None
    arps: list[tuple[str, str]] | None = None  # (ip, mac)
    uplinks: set[str] = field(default_factory=set)
    neighbors: list["Neighbor"] | None = None  # None: no neighbour table could be read

    @property
    def edge(self) -> list[MacEntry]:
        return [e for e in self.macs or [] if not e.uplink]


# --- parsers -------------------------------------------------------------------

def _entry(mac_text: str, vlan: str, port: str) -> MacEntry | None:
    mac = normalize_mac(mac_text)
    if not mac or mac.startswith("01:") or mac == "ff:ff:ff:ff:ff:ff":
        return None
    if not port or port.lower().startswith(_NOT_PORTS) or not re.search(r"\d", port):
        return None
    return MacEntry(mac, vlan, port, normalize_port(port))


def _mac_lines(out: str, pattern: str) -> list[MacEntry]:
    """MAC table entries from lines matching a pattern with groups mac, vlan and port."""
    rx = re.compile(pattern.replace("MAC", _MAC_TEXT))
    entries, seen = [], set()
    for line in (out or "").splitlines():
        m = rx.match(line)
        if not m:
            continue
        e = _entry(m.group("mac"), m.group("vlan"), m.group("port"))
        if e and (e.mac, e.vlan, e.port) not in seen:
            seen.add((e.mac, e.vlan, e.port))
            entries.append(e)
    return entries


# Line layouts of the MAC tables that the column-guessing parser below can't read.
_MAC_LAYOUTS = {
    # "  10    0050.56a1.0001    DYNAMIC     Et5        1       0:01:02 ago"
    "arista_eos": r"^\s*(?P<vlan>\d+)\s+(?P<mac>MAC)\s+\S+\s+(?P<port>\S+)",
    # "   users   00:50:56:a1:00:01   D   -   ge-0/0/5.0   0   0" (VLAN is a name)
    "juniper_junos": r"^\s*(?P<vlan>\S+)\s+(?P<mac>MAC)\s+\S+\s+\S+\s+(?P<port>\S+)",
    # "00:50:56:a1:00:01    10       dynamic                   1/1/5"
    "aruba_aoscx": r"^\s*(?P<mac>MAC)\s+(?P<vlan>\d+)\s+\S+\s+(?P<port>\S+)",
    # "  005056-a10001 5      10"
    "aruba_osswitch": r"^\s*(?P<mac>MAC)\s+(?P<port>\S+)\s+(?P<vlan>\d+)\s*$",
    # "10             00:50:56:a1:00:02     dynamic       ethernet1/1/5"
    "dell_os10": r"^\s*(?P<vlan>\d+)\s+(?P<mac>MAC)\s+\S+\s+(?P<port>\S+)",
    # "   10       00:50:56:a1:00:02       gi5      dynamic"
    "cisco_smb": r"^\s*(?P<vlan>\d+)\s+(?P<mac>MAC)\s+(?P<port>\S+)\s+(?!self)\w+",
    # "0050-56a1-0001 10/-/-        GE0/0/5             dynamic"
    "huawei_vrp": r"^\s*(?P<mac>MAC)\s+(?P<vlan>\d+)\S*\s+(?P<port>\S+)",
}


def _exos_fdb(out: str) -> list[MacEntry]:
    """EXOS 'show fdb': "00:50:56:a1:00:01   users(0010) 0000  d m   1:49" (VLAN name and tag)."""
    entries = []
    for m in re.finditer(rf"^\s*({_MAC_TEXT})\s+\S*?\((\d+)\)\s+\d+\s+.*?\s([\d:]+)\s*$",
                         out or "", re.M):
        e = _entry(m.group(1), str(int(m.group(2))), m.group(3))
        if e:
            entries.append(e)
    return entries


def _routeros_hosts(out: str) -> list[MacEntry]:
    """RouterOS '/interface bridge host print terse':
    "0 D mac-address=00:50:56:A1:00:01 vid=10 on-interface=ether5 bridge=bridge1".
    Local entries (flag L) are the router's own MACs."""
    entries = []
    for line in (out or "").splitlines():
        m = re.match(r"^\s*\d+\s+([A-Z]*)\s+(.*)$", line)
        if not m or "L" in m.group(1):
            continue
        kv = dict(re.findall(r"([\w-]+)=(\S+)", m.group(2)))
        e = _entry(kv.get("mac-address", ""), kv.get("vid", ""), kv.get("on-interface", ""))
        if e:
            entries.append(e)
    return entries


def mac_table_parser(platform: str):
    if platform == "extreme_exos":
        return _exos_fdb
    if platform == "mikrotik_routeros":
        return _routeros_hosts
    if platform in _MAC_LAYOUTS:
        return lambda out: _mac_lines(out, _MAC_LAYOUTS[platform])
    return parse_mac_table


def parse_mac_table(out: str) -> list[MacEntry]:
    """IOS / IOS-XE, NX-OS and AlliedWare Plus 'show mac address-table'.

        IOS:   10    0011.2233.4455    DYNAMIC     Gi1/0/5
        NX-OS: *   10     0050.56a1.0001   dynamic  0   F   F    Eth1/5
        AW+:   1     port1.0.1        0000.cd28.0752 forward   dynamic
    System entries (CPU, sup-eth, router, peer-link) are left out."""
    entries, seen = [], set()
    for line in (out or "").splitlines():
        m = _MAC.search(line)
        if not m:
            continue
        mac = normalize_mac(m.group(1))
        if not mac or mac.startswith("01:") or mac == "ff:ff:ff:ff:ff:ff":
            continue
        tokens = line.replace(",", " ").split()
        mac_tok = m.group(1)
        before = line[:m.start()].split()
        vlan = next((t for t in before if t.isdigit()), "")
        ports = [t for t in tokens if t != mac_tok and "(" not in t and _INTF.match(t)
                 and not t.lower().startswith(_NOT_PORTS)]
        if not ports or not vlan:
            continue
        port = ports[-1]
        key = (mac, vlan, port)
        if key in seen:
            continue
        seen.add(key)
        entries.append(MacEntry(mac, vlan, port, normalize_port(port)))
    return entries


def parse_arp(out: str) -> list[tuple[str, str]]:
    """(ip, mac) from IOS 'show ip arp', NX-OS 'show ip arp vrf all', ASA and AW+ 'show arp'."""
    result, seen = [], set()
    for line in (out or "").splitlines():
        ip, mac = _IPV4.search(line), _MAC.search(line)
        if not ip or not mac or "incomplete" in line.lower():
            continue
        pair = (ip.group(1), normalize_mac(mac.group(1)))
        if pair[1] and pair not in seen:
            seen.add(pair)
            result.append(pair)
    return result


# Lines that start one neighbour in 'detail' output, besides a line of dashes
_BLOCK_STARTS = (
    r"\s*Local port(?:\S|\s+:)",  # AlliedWare Plus "Local port1.0.1:", ArubaOS-Switch "Local Port   : 25"
    r"Interface \S+ detected",  # Arista
    r"\S+ has \d+ neighbou?r",  # Huawei
    r"Port\s+:",  # AOS-CX
    r"LLDP Port \S+ detected",  # EXOS
)
_BLOCK_SPLIT = re.compile(r"^-{5,}\s*$|^(?=(?:" + "|".join(_BLOCK_STARTS) + "))", re.M | re.I)

# The local port of a neighbour block, most specific first
_LOCAL_PORT = (
    re.compile(r"Local (?:Intf|Port id):\s*(\S+)", re.I),  # IOS, NX-OS, OS10
    re.compile(r"^\s*Local (port\S+?):?\s*$", re.M | re.I),  # AlliedWare Plus
    re.compile(r"^\s*Local Port\s*:\s*(\S+)", re.M),  # ArubaOS-Switch
    re.compile(r"^Interface (\S+) detected", re.M),  # Arista
    re.compile(r"^LLDP Port (\S+) detected", re.M),  # EXOS
    re.compile(r"^(\S+) has \d+ neighbou?r", re.M),  # Huawei
    re.compile(r"^Port\s*:\s*(\S+)", re.M),  # AOS-CX
)
_CAPS = (
    re.compile(r"Enabled (?:System )?Capabilities\s*[.:]*\s*(.+)$", re.M | re.I),
    re.compile(r"Capabilities Enabled\s*[.:]*\s*(.+)$", re.M | re.I),
    re.compile(r"System Capabilities\s*[.:]*\s*(.+)$", re.M | re.I),
)


def _blocks(out: str) -> list[str]:
    """Split neighbour detail output into one block per neighbour."""
    return _BLOCK_SPLIT.split(out or "")


def _search(patterns, text: str) -> str | None:
    for rx in patterns:
        m = rx.search(text)
        if m:
            return m.group(1)
    return None


def _is_infra(caps: str) -> bool:
    """A switch or router neighbour, but not a phone or wireless AP."""
    c = caps.lower()
    if re.search(r"phone|telephone|trans-bridge|wlan|\bt\b|\bw\b", c):
        return False
    return bool(re.search(r"switch|router|bridge|\bb\b|\br\b", c))


def parse_uplinks_cdp(out: str) -> set[str]:
    ports = set()
    for block in _blocks(out):
        intf = re.search(r"Interface:\s*([^,\s]+)", block)
        caps = re.search(r"Capabilit(?:y|ies):\s*(.+)$", block, re.M)
        if intf and caps and _is_infra(caps.group(1)):
            ports.add(normalize_port(intf.group(1)))
    return ports


def parse_uplinks_lldp(out: str) -> set[str]:
    ports = set()
    for block in _blocks(out):
        intf, caps = _search(_LOCAL_PORT, block), _search(_CAPS, block)
        if intf and caps and _is_infra(caps):
            ports.add(normalize_port(intf.rstrip(":")))
    return ports


# A neighbour's port that is a switch or router interface (Ethernet1, ge-0/0/1,
# Gi1/0/1, 1/1/1), not a phone's or an access point's ("eth0", "Port 1", a MAC address).
_SWITCH_PORT = re.compile(r"^(?:[a-z][a-z-]*\d+(?:[/.:]\d+)+|ethernet\d+|[a-z]{2}-\d+/\d+/\d+.*"
                          r"|\d+/\d+(?:/\d+)*)$", re.I)


def parse_uplinks_lldp_table(out: str) -> set[str]:
    """One line per neighbour.

    Cisco small business has a capabilities column:
        gi1/0/49  00:1c:73:00:00:01   Ethernet1      spine1           B, R        91
    Junos has none, so a neighbour counts when its port looks like a switch port:
        ge-0/0/47          -                   00:1c:73:00:00:01   Ethernet1          spine1"""
    ports = set()
    for line in (out or "").splitlines():
        m = re.match(rf"^\s*(\S+)\s+(?:(\S+)\s+)?({_MAC_TEXT})\s+(\S+)(.*)$", line)
        if not m or not re.search(r"\d", m.group(1)):
            continue
        local, rest = m.group(1), m.group(5)
        caps = re.search(r"((?:\b[A-Z]\b,?\s*)+)\s+\d+\s*$", rest)
        if caps:
            infra = _is_infra(caps.group(1))
        else:
            infra = bool(_SWITCH_PORT.match(m.group(4)))
        if infra:
            ports.add(normalize_port(local))
    return ports


def parse_uplinks_mikrotik(out: str) -> set[str]:
    """RouterOS '/ip neighbor print terse': "... interface=ether1,bridge1 ...
    system-caps-enabled=bridge,router" (the first interface is the port)."""
    ports = set()
    for line in (out or "").splitlines():
        kv = dict(re.findall(r"([\w-]+)=(\S*)", line))
        intf, caps = kv.get("interface", "").split(",")[0], kv.get("system-caps-enabled", "")
        if intf and caps and _is_infra(caps.replace(",", " ")):
            ports.add(normalize_port(intf))
    return ports


def parse_port_channels(out: str) -> set[str]:
    """Port-channels and every member, from IOS 'show etherchannel summary' and
    NX-OS 'show port-channel summary'."""
    ports = set()
    for line in (out or "").splitlines():
        m = re.match(r"^\s*\d+\s+(Po\d+)\(\w+\)\s+(.*)$", line)
        if m:
            ports.add(normalize_port(m.group(1)))
            ports.update(normalize_port(p) for p in re.findall(r"(\S+?)\(\w+\)", m.group(2)))
    return ports


# Port-channel (Cisco po, AlliedWare Plus sa/po), Junos ae, AOS-CX lag, ArubaOS-Switch
# trk, Huawei Eth-Trunk and MikroTik bond. (Not "port1.0.1": an AlliedWare Plus port.)
_AGGREGATE = re.compile(r"^(?:po|sa|ae|lag|trk|bond|eth-trunk|port-channel)\d")


def _is_aggregate(port_norm: str) -> bool:
    return bool(_AGGREGATE.match(port_norm))


# --- neighbours (the topology map) -------------------------------------------------

@dataclass
class Neighbor:
    """A device seen on one of this device's ports, from CDP, LLDP or MikroTik discovery."""
    local_port: str
    name: str  # as it calls itself (domain removed)
    remote_port: str = ""
    address: str = ""  # its management address, when it says
    platform: str = ""  # its model or software, when it says
    infra: bool = True  # a switch or router (not a phone or wireless access point)


_REMOTE_NAME = (re.compile(r"System Name\s*[.:]*\s*\"?([^\"\s]+)", re.I),
                re.compile(r"Chassis-Name\s*[.:]*\s*\"?([^\"\s]+)", re.I),  # AOS-CX
                re.compile(r"SysName\s*[.:]*\s*\"?([^\"\s]+)", re.I))
_REMOTE_PORT = (re.compile(r"(?<![Ll]ocal )\bPort[ -]?id\b(?!\s*(?:sub)?type)[ \t.:]*\"?([^\"\n]*?)\"?[ \t]*$",
                           re.I | re.M),)
_REMOTE_ADDRESS = (re.compile(r"(?:Management Address(?:es)?|IPv4 Address|IP address|Mgmt IP)"
                              r"[^\n\d]*(\d{1,3}(?:\.\d{1,3}){3})", re.I),)
_REMOTE_DESCR = (re.compile(r"System Description\s*[.:]*\s*\"?([^\"\n]+)", re.I),)


def _short(name: str) -> str:
    name = (name or "").strip().strip('"')
    return name if re.fullmatch(r"[\d.]+", name) else name.split(".")[0]


def parse_neighbors_cdp(out: str) -> list[Neighbor]:
    """IOS and NX-OS 'show cdp neighbors detail'."""
    found = []
    for block in _blocks(out):
        dev = re.search(r"Device ID:\s*(\S+)", block)
        intf = re.search(r"Interface:\s*([^,\s]+),\s*Port ID \(outgoing port\):\s*(\S+)", block)
        if not dev or not intf:
            continue
        dev_name = re.sub(r"\(.*\)$", "", dev.group(1))  # NX-OS 'name(serial)'
        caps = re.search(r"Capabilit(?:y|ies):\s*(.+)$", block, re.M)
        plat = re.search(r"Platform:\s*([^,\n]+)", block)
        found.append(Neighbor(intf.group(1), _short(dev_name), intf.group(2),
                              _search(_REMOTE_ADDRESS, block) or "",
                              plat.group(1).strip() if plat else "",
                              _is_infra(caps.group(1)) if caps else True))
    return found


def parse_neighbors_lldp(out: str) -> list[Neighbor]:
    """LLDP neighbour detail, any vendor (the same block markers as the uplinks)."""
    found = []
    for block in _blocks(out):
        local, name = _search(_LOCAL_PORT, block), _search(_REMOTE_NAME, block)
        if not local or not name:
            continue
        port = _search(_REMOTE_PORT, block) or ""
        caps = _search(_CAPS, block)
        found.append(Neighbor(local.rstrip(":"), _short(name), port,
                              _search(_REMOTE_ADDRESS, block) or "",
                              (_search(_REMOTE_DESCR, block) or "").strip()[:80],
                              _is_infra(caps) if caps else bool(_SWITCH_PORT.match(port))))
    return found


def parse_neighbors_lldp_table(out: str) -> list[Neighbor]:
    """One line per neighbour (Junos, Cisco small business): see parse_uplinks_lldp_table."""
    found = []
    for line in (out or "").splitlines():
        m = re.match(rf"^\s*(\S+)\s+(?:(\S+)\s+)?({_MAC_TEXT})\s+(\S+)\s+(\S+)(.*)$", line)
        if not m or not re.search(r"\d", m.group(1)):
            continue
        caps = re.search(r"((?:\b[A-Z]\b,?\s*)+)\s+\d+\s*$", m.group(6))
        infra = _is_infra(caps.group(1)) if caps else bool(_SWITCH_PORT.match(m.group(4)))
        found.append(Neighbor(m.group(1), _short(m.group(5)), m.group(4), infra=infra))
    return found


def parse_neighbors_mikrotik(out: str) -> list[Neighbor]:
    found = []
    for line in (out or "").splitlines():
        kv = dict(re.findall(r"([\w-]+)=(\"[^\"]*\"|\S*)", line))
        kv = {k: v.strip('"') for k, v in kv.items()}
        intf, name = kv.get("interface", "").split(",")[0], kv.get("identity", "")
        if not intf or not name:
            continue
        caps = kv.get("system-caps-enabled", "")
        found.append(Neighbor(intf, _short(name), kv.get("interface-name", ""),
                              kv.get("address", ""), kv.get("platform", ""),
                              _is_infra(caps.replace(",", " ")) if caps else True))
    return found


def _merge_neighbors(lists: list[list[Neighbor]]) -> list[Neighbor]:
    """CDP and LLDP often report the same neighbour: keep it once (CDP first)."""
    seen, out = set(), []
    for n in (n for lst in lists for n in lst):
        key = (normalize_port(n.local_port), n.name.lower())
        if key not in seen:
            seen.add(key)
            out.append(n)
    return out


def read_device(outputs: dict[str, str], platform: str = "") -> DeviceRead:
    """outputs: key (see COMMANDS) -> command output."""
    r = DeviceRead()
    lists = [parse(outputs[key]) for key, parse in (
        ("cdp", parse_neighbors_cdp), ("lldp", parse_neighbors_lldp),
        ("lldp_table", parse_neighbors_lldp_table), ("mt_neighbor", parse_neighbors_mikrotik))
        if key in outputs and not failed(outputs.get(key))]
    if lists:
        r.neighbors = _merge_neighbors(lists)
    for key, parse in (("cdp", parse_uplinks_cdp), ("lldp", parse_uplinks_lldp),
                       ("lldp_table", parse_uplinks_lldp_table),
                       ("mt_neighbor", parse_uplinks_mikrotik), ("pc", parse_port_channels)):
        if not failed(outputs.get(key)):
            r.uplinks |= parse(outputs[key])
    if not failed(outputs.get("mac")):
        r.macs = mac_table_parser(platform)(outputs["mac"])
        for e in r.macs:
            e.uplink = e.port_norm in r.uplinks or _is_aggregate(e.port_norm)
    if not failed(outputs.get("arp")):
        r.arps = parse_arp(outputs["arp"])
    return r


# --- where is each circuit -----------------------------------------------------

MATCHES, MOVED, FOUND, NOT_SEEN, SEVERAL, NO_ADDRESS = (
    "matches", "moved", "found", "not_seen", "several", "no_address")
STATUS_LABELS = {MATCHES: "Matches the list", MOVED: "Moved", FOUND: "Found",
                 NOT_SEEN: "Not seen", SEVERAL: "Several ports", NO_ADDRESS: "No MAC or IP"}


@dataclass
class Seen:
    device_id: int
    port: str
    port_norm: str
    vlan: str


def resolve(mac_norm: str, ip: str, documented: tuple[int | None, str],
            edges: dict[str, list[Seen]], arp: dict[str, str]) -> dict:
    """Live location of one circuit.

    documented: (NetOps device id the list's DEVICE links to, normalised PORT)
    edges: mac -> where it is learned on an edge port; arp: ip -> mac."""
    mac, source = mac_norm, "sheet"
    if not mac and ip:
        mac, source = arp.get(ip, ""), "arp"
    out = {"live_mac": mac, "live_mac_source": source if mac else "",
           "live_device_id": None, "live_port": "", "live_vlan": "", "live_status": ""}
    if not mac:
        out["live_status"] = NO_ADDRESS if not ip else NOT_SEEN
        return out
    places = edges.get(mac, [])
    if not places:
        out["live_status"] = NOT_SEEN
        return out
    if len({(p.device_id, p.port_norm) for p in places}) > 1:
        out["live_status"] = SEVERAL
        out["live_port"] = ", ".join(sorted({p.port for p in places}))
        return out
    p = places[0]
    out.update(live_device_id=p.device_id, live_port=p.port, live_vlan=p.vlan)
    doc_device, doc_port = documented
    if not doc_port:
        out["live_status"] = FOUND
    elif doc_device == p.device_id and doc_port == p.port_norm:
        out["live_status"] = MATCHES
    else:
        out["live_status"] = MOVED
    return out
