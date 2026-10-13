"""How the demo network is cabled: each device answers its neighbour commands (CDP, LLDP,
MikroTik discovery) with these links, so the network scan fills the topology map.

Two cores and six access switches at HQ with a firewall and a WAN router; a leaf/spine
data centre linked to the HQ cores; a router and three switches at Branch North; three
switches at Branch South and the Warehouse. Some phones and access points too.
"""

from app.tools.circuits import live

# (device, its port, neighbour, the neighbour's port)
LINKS = [
    ("hq-core1", "Ethernet1/49", "hq-core2", "Ethernet1/49"),
    ("hq-core1", "Ethernet1/50", "hq-core2", "Ethernet1/50"),
    *[(f"hq-acc-sw{i}", "GigabitEthernet1/1/1", "hq-core1", f"Ethernet1/{i}") for i in range(1, 7)],
    *[(f"hq-acc-sw{i}", "GigabitEthernet2/1/1", "hq-core2", f"Ethernet1/{i}") for i in range(1, 7)],
    ("hq-core1", "Ethernet1/47", "hq-fw1", "GigabitEthernet0/0"),
    ("hq-core2", "Ethernet1/47", "hq-fw1", "GigabitEthernet0/1"),
    ("hq-core1", "Ethernet1/46", "hq-wan-rtr", "GigabitEthernet0/0/1"),
    ("hq-core2", "Ethernet1/46", "hq-wan-rtr", "GigabitEthernet0/0/2"),
    ("hq-core1", "Ethernet1/48", "dc1-spine1", "xe-0/0/48"),
    ("hq-core2", "Ethernet1/48", "dc1-spine2", "xe-0/0/48"),
    *[(f"dc1-leaf{i}", "Ethernet49/1", "dc1-spine1", f"xe-0/0/{i}") for i in range(1, 5)],
    *[(f"dc1-leaf{i}", "Ethernet50/1", "dc1-spine2", f"xe-0/0/{i}") for i in range(1, 5)],
    ("dc1-leaf1", "Ethernet47", "dc1-leaf2", "Ethernet47"),
    ("dc1-leaf3", "Ethernet47", "dc1-leaf4", "Ethernet47"),
    ("bn-rtr1", "ether1", "isp-north-ce", "GigabitEthernet0/1"),
    ("bn-rtr1", "sfp-sfpplus1", "bn-sw1", "49"),
    ("bn-sw1", "50", "bn-sw2", "49"),
    ("bn-sw1", "51", "bn-sw3", "49"),
    ("bs-sw1", "port1.0.1", "isp-south-ce", "GigabitEthernet0/1"),
    ("bs-sw1", "port1.0.27", "bs-sw2", "port1.0.27"),
    ("bs-sw1", "port1.0.28", "bs-sw3", "port1.0.27"),
    ("wh-sw1", "ethernet1/1/49", "wh-sw2", "ethernet1/1/49"),
    ("wh-sw1", "ethernet1/1/50", "wh-sw3", "ethernet1/1/49"),
    ("wh-sw1", "ethernet1/1/52", "hq-core1", "Ethernet1/45"),
    # phones and wireless access points (left off the map unless asked for)
    ("hq-acc-sw1", "GigabitEthernet1/0/48", "hq-ap-01", "eth0"),
    ("hq-acc-sw2", "GigabitEthernet1/0/47", "SEP0004F2AA0201", "Port 1"),
    ("bn-sw2", "5", "SEP0004F2AA0101", "Port 1"),
    ("bn-sw2", "6", "ap-bn-01", "eth0"),
    ("wh-sw1", "ethernet1/1/1", "wh-ap-01", "eth0"),
]
UNMANAGED = {"hq-wan-rtr": ("198.51.100.201", "router"), "isp-north-ce": ("198.51.100.202", "router"),
             "isp-south-ce": ("198.51.100.203", "router"), "hq-ap-01": ("", "ap"),
             "ap-bn-01": ("", "ap"), "wh-ap-01": ("", "ap"),
             "SEP0004F2AA0201": ("", "phone"), "SEP0004F2AA0101": ("", "phone")}
MODEL = {"cisco_ios": "cisco C9300-48P", "cisco_nxos": "N9K-C93180YC-FX", "cisco_asa": "cisco FPR-2110",
         "arista_eos": "Arista DCS-7050SX3-48YC8", "juniper_junos": "Juniper QFX5120-48Y",
         "aruba_osswitch": "Aruba JL320A 2930M", "mikrotik_routeros": "MikroTik CCR2004",
         "allied_awplus": "Allied Telesis x930-28GTX", "dell_os10": "Dell EMC S5248F-ON"}


def _kind(name: str, platforms: dict) -> str:
    if name in UNMANAGED:
        return UNMANAGED[name][1]
    return "firewall" if platforms.get(name) == "cisco_asa" else "switch"


def _mac(name: str) -> str:
    n = sum(ord(c) * (i + 1) for i, c in enumerate(name)) & 0xFFFFFF
    return f"00:1c:73:{n >> 16:02x}:{(n >> 8) & 0xff:02x}:{n & 0xff:02x}"


def neighbours_of(name: str) -> list[tuple[str, str, str]]:
    """(local port, neighbour, neighbour's port) for one device."""
    out = [(p, b, bp) for a, p, b, bp in LINKS if a == name]
    out += [(bp, a, p) for a, p, b, bp in LINKS if b == name]
    return out


def outputs(name: str, platform: str, addresses: dict, platforms: dict) -> dict[str, str]:
    """The device's neighbour command outputs (live.COMMANDS keys cdp, lldp, lldp_table,
    mt_neighbor)."""
    cmds = live.commands_for(platform)
    rows = neighbours_of(name)
    address = lambda n: addresses.get(n) or UNMANAGED.get(n, ("", ""))[0]  # noqa: E731
    out = {}
    if "cdp" in cmds:
        caps = {"switch": "Router Switch IGMP", "firewall": "Router", "router": "Router",
                "ap": "Trans-Bridge", "phone": "Host Phone"}
        out[cmds["cdp"]] = "".join(
            f"-------------------------\nDevice ID: {n}\nEntry address(es): \n"
            f"  IP address: {address(n)}\nPlatform: {MODEL.get(platforms.get(n), 'unknown')},  "
            f"Capabilities: {caps[_kind(n, platforms)]} \n"
            f"Interface: {lp},  Port ID (outgoing port): {rp}\nHoldtime : 150 sec\n\n"
            for lp, n, rp in rows)
        if "lldp" in cmds:
            out[cmds["lldp"]] = ""  # Cisco: the links come from CDP
    elif "lldp" in cmds:
        caps = {"switch": "B, R", "firewall": "R", "router": "R", "ap": "W", "phone": "B, T"}
        out[cmds["lldp"]] = "".join(
            f"------------------------------------------------\nLocal Intf: {lp}\n"
            f"Chassis id: {_mac(n)}\nPort id: {rp}\nSystem Name: {n}\n"
            f"System Capabilities: {caps[_kind(n, platforms)]}\n"
            f"Enabled Capabilities: {caps[_kind(n, platforms)]}\n"
            + (f"Management Address: {address(n)}\n" if address(n) else "") + "\n"
            for lp, n, rp in rows)
    if "lldp_table" in cmds:
        out[cmds["lldp_table"]] = (
            "Local Interface    Parent Interface    Chassis Id          Port info          System Name\n"
            + "".join(f"{lp:<18} {'-':<19} {_mac(n):<19} {rp:<18} {n}\n" for lp, n, rp in rows))
    if "mt_neighbor" in cmds:
        caps = {"switch": "bridge,router", "firewall": "router", "router": "router", "ap": "wlan",
                "phone": "telephone"}
        out[cmds["mt_neighbor"]] = "".join(
            f" {i} interface={lp},bridge address={address(n)} mac-address={_mac(n).upper()} "
            f"identity={n} platform={MODEL.get(platforms.get(n), 'unknown').split()[0]} "
            f"interface-name={rp} system-caps-enabled={caps[_kind(n, platforms)]}\n"
            for i, (lp, n, rp) in enumerate(rows))
    return out
