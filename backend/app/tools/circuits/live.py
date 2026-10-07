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

from app.tools.circuits.importer import normalize_mac, normalize_port

# Read-only commands per platform. Keys: mac, arp, cdp, lldp, pc (port-channels).
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
}

_CLI_ERRORS = ("% Invalid input", "% Incomplete command", "% Unknown command", "% Invalid command",
               "ERROR: % Invalid", "% Ambiguous command", "Invalid command", "% Error",
               "% LLDP is not enabled", "% CDP is not enabled", "CDP is not enabled")

_MAC = re.compile(r"\b([0-9a-fA-F]{4}\.[0-9a-fA-F]{4}\.[0-9a-fA-F]{4}"
                  r"|[0-9a-fA-F]{2}(?:[:-][0-9a-fA-F]{2}){5})\b")
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

    @property
    def edge(self) -> list[MacEntry]:
        return [e for e in self.macs or [] if not e.uplink]


# --- parsers -------------------------------------------------------------------

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


def _blocks(out: str) -> list[str]:
    """Split neighbour detail output into one block per neighbour."""
    text = out or ""
    if re.search(r"^-{5,}\s*$", text, re.M):
        return re.split(r"^-{5,}\s*$", text, flags=re.M)
    # AlliedWare Plus: "Local port1.0.1:" starts each block
    return re.split(r"^(?=\s*Local port)", text, flags=re.M | re.I)


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
        intf = (re.search(r"Local (?:Intf|Port id):\s*(\S+)", block, re.I)
                or re.search(r"^\s*Local (port\S+?):?\s*$", block, re.M | re.I))
        caps = (re.search(r"Enabled Capabilities\s*[.:]*\s*(.+)$", block, re.M)
                or re.search(r"System Capabilities\s*[.:]*\s*(.+)$", block, re.M))
        if intf and caps and _is_infra(caps.group(1)):
            ports.add(normalize_port(intf.group(1).rstrip(":")))
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


def _is_aggregate(port_norm: str) -> bool:
    return port_norm.startswith(("po", "sa", "port-channel"))


def read_device(outputs: dict[str, str]) -> DeviceRead:
    """outputs: key (mac, arp, cdp, lldp, pc) -> command output."""
    r = DeviceRead()
    for key, parse in (("cdp", parse_uplinks_cdp), ("lldp", parse_uplinks_lldp),
                       ("pc", parse_port_channels)):
        if not failed(outputs.get(key)):
            r.uplinks |= parse(outputs[key])
    if not failed(outputs.get("mac")):
        r.macs = parse_mac_table(outputs["mac"])
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
