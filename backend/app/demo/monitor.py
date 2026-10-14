"""Ping and SNMP answers for the simulated network (the demo and the tests): the monitoring
poller is given this instead of real ping and SNMP, so nothing is sent on the network.

A device answers while its simulated device is up (an upgrade's reload takes it down for a
while, and it comes back with a new uptime). On top of that, per device:

* ``down``: answers nothing (unplugged);
* ``no_ping``: doesn't answer ping (a firewall that drops ICMP), SNMP works;
* ``snmp_error``: SNMP fails with this message (wrong community, an access list...);
* ``rtt``: the usual response time in ms.
"""

import math
import random
import re
import time

from app.tools.monitoring import ifaces as ifm
from app.tools.monitoring.ping import PingResult
from app.tools.monitoring.snmp import SYS_DESCR, SYS_NAME, SYS_OBJECT_ID, SYS_UPTIME, SnmpError

DESCR = {
    "cisco_ios": "Cisco IOS Software [Dublin], Catalyst L3 Switch Software (CAT9K_IOSXE), Version {v}",
    "cisco_nxos": "Cisco NX-OS(tm) n9000, Software (n9000-dk9), Version {v}",
    "cisco_asa": "Cisco Adaptive Security Appliance Version {v}",
    "arista_eos": "Arista Networks EOS version {v} running on an Arista DCS-7050SX3-48YC8",
    "juniper_junos": "Juniper Networks, Inc. qfx5120-48y Ethernet Switch, kernel JUNOS {v}",
    "aruba_osswitch": "Aruba JL322A 2930M-48G-PoE+ Switch, revision {v}",
    "mikrotik_routeros": "RouterOS CCR2004-16G-2S+ {v}",
    "allied_awplus": "Allied Telesis router/switch, AW+ v{v}",
    "dell_os10": "Dell SmartFabric OS10 Enterprise, version {v}",
}
OBJECT_ID = {"cisco_ios": "1.3.6.1.4.1.9.1.2694", "cisco_nxos": "1.3.6.1.4.1.9.12.3.1.3.1812",
             "cisco_asa": "1.3.6.1.4.1.9.1.2313", "arista_eos": "1.3.6.1.4.1.30065.1.3011.7050.3741.48",
             "juniper_junos": "1.3.6.1.4.1.2636.1.1.1.4.132.2", "aruba_osswitch": "1.3.6.1.4.1.11.2.3.7.11.181.1",
             "mikrotik_routeros": "1.3.6.1.4.1.14988.1", "allied_awplus": "1.3.6.1.4.1.207.1.14.112",
             "dell_os10": "1.3.6.1.4.1.674.11000.5000.100.2.1.12"}


class SimMonitor:
    def __init__(self, net, addresses: dict[str, str], clock=time.time, seed: int = 7):
        self.net = net
        self.by_address = {a: n for n, a in addresses.items()}
        self.clock = clock
        self.down: set[str] = set()
        self.no_ping: set[str] = set()
        self.snmp_error: dict[str, str] = {}
        self.rtt: dict[str, float] = {}
        self.boot: dict[str, float] = {}
        self.no_interfaces: set[str] = set()  # answers the system values only
        self.faults: dict[str, set[str]] = {}  # device -> hardware faults: psu2, fan2, temp
        self.cpu: dict[str, float] = {}  # device -> CPU % (else a quiet daily curve)
        self._reloads: dict[str, int] = {}
        self._was_up: dict[str, bool] = {}
        self._rand = random.Random(seed)
        self.pings = 0
        self.gets = 0

    def _device(self, address: str):
        name = self.by_address.get(address)
        return (name, self.net.devices.get(name)) if name else (None, None)

    def _alive(self, name, dev) -> bool:
        if dev is None or name in self.down:
            return False
        up = getattr(dev, "up", True)
        if up and not self._was_up.get(name, True):
            self.boot[name] = self.clock()  # back from a reload: uptime starts again
        self._was_up[name] = up
        return up

    async def ping(self, address: str, count: int = 3, timeout: float = 1.0) -> PingResult:
        self.pings += 1
        name, dev = self._device(address)
        if not self._alive(name, dev) or name in self.no_ping:
            return PingResult(count, 0, None)
        base = self.rtt.get(name, 1.5)
        return PingResult(count, count, round(base * (0.8 + 0.5 * self._rand.random()), 2))

    async def get(self, target, oids: list[str]) -> dict:
        self.gets += 1
        name, dev = self._device(target.address)
        if not self._alive(name, dev):
            raise SnmpError("No answer (timed out): check the device's SNMP settings "
                            "(the community or user), its access list, and that UDP 161 is "
                            "open from this server")
        if name in self.snmp_error:
            raise SnmpError(self.snmp_error[name])
        boot = self.boot.setdefault(name, self.clock() - 86400 * (20 + (sum(map(ord, name)) % 90)))
        platform = getattr(dev, "platform", "")
        values = {SYS_NAME: name, SYS_UPTIME: int((self.clock() - boot) * 100) % 2**32,
                  SYS_DESCR: DESCR.get(platform, "Network device {v}").format(v=getattr(dev, "version", "")),
                  SYS_OBJECT_ID: OBJECT_ID.get(platform, "1.3.6.1.4.1.8072.3.2.10")}
        mib = self.mib(name, platform)
        return {o: values[o] if o in values else mib.get(o) for o in oids}

    def mib(self, name: str, platform: str) -> dict[str, object]:
        """The device's hardware health values (instance OID -> value), as its vendor's MIBs give them."""
        return health_mib(name, platform, self.clock(), self.faults.get(name, set()), self.cpu.get(name))

    async def walk(self, target, oid: str, max_rows: int = 20000) -> list:
        await self.get(target, [SYS_NAME])
        name, dev = self._device(target.address)
        if name in self.no_interfaces:
            return []
        key = next((k for k, v in ifm.COLUMNS.items() if v == oid), None)
        if key is None:
            mib = self.mib(name, getattr(dev, "platform", ""))
            rows = [(o, v) for o, v in mib.items() if o.startswith(oid + ".")]
            return sorted(rows, key=lambda r: [int(x) for x in r[0].split(".")])[:max_rows]
        t = self.clock()
        return [(f"{oid}.{p.index}", p.value(key, t))
                for p in ports_of(name, getattr(dev, "platform", ""))][:max_rows]


# --- the simulated hardware -----------------------------------------------------------------

def health_mib(name: str, platform: str, t: float, faults: set[str], cpu: float | None) -> dict[str, object]:
    """CPU, memory, temperatures, fans and power supplies in the MIBs the health readers use
    for each platform (app/tools/monitoring/health.py)."""
    seed = sum(ord(c) for c in name)
    day = math.sin(2 * math.pi * t / DAY + math.pi / 2 - 2 * math.pi * PEAK_HOUR / 24)
    load = cpu if cpu is not None else round(8 + seed % 9 + 6 * max(day, 0) + (seed % 3), 1)
    mem = 35 + seed % 30
    temp = 30 + seed % 8 + round(3 * max(day, 0))
    m: dict[str, object] = {}
    ok_psu2 = "psu2" not in faults
    ok_fan2 = "fan2" not in faults
    hot = "temp" in faults
    if platform in ("cisco_ios", "cisco_asa", "cisco_nxos"):
        m["1.3.6.1.4.1.9.9.109.1.1.1.1.8.1"] = int(load)  # cpmCPUTotal5minRev
        if platform == "cisco_asa":
            m["1.3.6.1.4.1.9.9.48.1.1.1.2.1"] = "System memory"
            m["1.3.6.1.4.1.9.9.48.1.1.1.5.1"] = mem * 80_000_000 // 100
            m["1.3.6.1.4.1.9.9.48.1.1.1.6.1"] = (100 - mem) * 80_000_000 // 100
        else:
            m["1.3.6.1.4.1.9.9.109.1.1.1.1.12.1"] = mem * 8_000_000 // 100  # KB used
            m["1.3.6.1.4.1.9.9.109.1.1.1.1.13.1"] = (100 - mem) * 8_000_000 // 100
    if platform == "cisco_ios":
        b = "1.3.6.1.4.1.9.9.13.1"
        for i, (n, v) in enumerate((("Inlet Temp Sensor", temp), ("Hotspot Temp Sensor", temp + 14)), 1):
            m[f"{b}.3.1.2.{i}"], m[f"{b}.3.1.3.{i}"] = f"Switch 1 - {n}", v + (25 if hot else 0)
            m[f"{b}.3.1.6.{i}"] = 3 if hot else 1
        for i in (1, 2, 3):
            m[f"{b}.4.1.2.{i}"], m[f"{b}.4.1.3.{i}"] = f"Switch 1 - FAN {i}", 1 if i != 2 or ok_fan2 else 6
        m[f"{b}.5.1.2.1"], m[f"{b}.5.1.3.1"] = "Switch 1 - Power Supply A", 1
        m[f"{b}.5.1.2.2"], m[f"{b}.5.1.3.2"] = "Switch 1 - Power Supply B", 1 if ok_psu2 else 6
    if platform == "cisco_nxos":
        s, f = "1.3.6.1.4.1.9.9.91.1.1.1.1", "1.3.6.1.4.1.9.9.117.1"
        for k, n, v in ((21590, "module-1 FRONT", temp), (21591, "module-1 BACK", temp + 6),
                        (21592, "module-1 CPU", temp + 12)):
            m[f"{s}.1.{k}"], m[f"{s}.2.{k}"], m[f"{s}.3.{k}"] = 8, 9, 0
            m[f"{s}.4.{k}"], m[f"{s}.5.{k}"], m[f"{ENT_NAME}.{k}"] = v, 1, n
        for k, n, ok in ((470, "PowerSupply-1", True), (471, "PowerSupply-2", ok_psu2)):
            m[f"{f}.1.2.1.2.{k}"], m[f"{ENT_NAME}.{k}"] = 2 if ok else 8, n
        for k in (534, 535, 536, 537):
            m[f"{f}.4.1.1.1.{k}"], m[f"{ENT_NAME}.{k}"] = 2 if k != 535 or ok_fan2 else 3, f"Fan Module-{k - 533}"
    if platform == "juniper_junos":
        b = "1.3.6.1.4.1.2636.3.1.13.1"
        rows = [("9.1.0.0", "Routing Engine 0", 2, temp + 8, int(load), mem),
                ("7.1.0.0", "FPC: QFX5120-48Y @ 0/*/*", 2, temp + 12, 0, 0),
                ("2.1.0.0", "Power Supply 0", 2, 0, 0, 0), ("2.2.0.0", "Power Supply 1", 2 if ok_psu2 else 6, 0, 0, 0),
                ("4.1.0.0", "Fan Tray 0 Fan 0", 2, 0, 0, 0), ("4.2.0.0", "Fan Tray 1 Fan 0", 2 if ok_fan2 else 6, 0, 0, 0)]
        for k, d, st, tp, c, me in rows:
            m[f"{b}.5.{k}"], m[f"{b}.6.{k}"], m[f"{b}.7.{k}"], m[f"{b}.8.{k}"], m[f"{b}.11.{k}"] = d, st, tp, c, me
    if platform == "aruba_osswitch":
        m["1.3.6.1.4.1.11.2.14.11.5.1.9.6.1.0"] = int(load)
        m["1.3.6.1.4.1.11.2.14.11.5.1.1.2.1.1.1.5.1"] = 400_000_000
        m["1.3.6.1.4.1.11.2.14.11.5.1.1.2.1.1.1.6.1"] = 400_000_000 * (100 - mem) // 100
        for i, (d, st) in enumerate((("Fan Sensor", 4 if ok_fan2 else 2), ("Power Supply Sensor", 4 if ok_psu2 else 2),
                                     ("Over-temperature Sensor", 2 if hot else 4)), 1):
            m[f"1.3.6.1.4.1.11.2.14.11.1.2.6.1.7.{i}"], m[f"1.3.6.1.4.1.11.2.14.11.1.2.6.1.4.{i}"] = d, st
    if platform == "mikrotik_routeros":
        for i, (n, v, u) in enumerate((("temperature", temp + 10, 1), ("cpu-temperature", temp + 20, 1),
                                       ("fan1-speed", 5200, 2), ("fan2-speed", 5100 if ok_fan2 else 0, 2)), 1):
            g = "1.3.6.1.4.1.14988.1.1.3.100.1"
            m[f"{g}.2.{i}"], m[f"{g}.3.{i}"], m[f"{g}.4.{i}"] = n, v, u
    if platform in ("arista_eos", "dell_os10", "allied_awplus", "mikrotik_routeros"):
        for core in range(1, 5):  # HOST-RESOURCES: per core, the last minute
            m[f"1.3.6.1.2.1.25.3.3.1.2.{core}"] = max(0, int(load) + core - 2)
        h = "1.3.6.1.2.1.25.2.3.1"
        m[f"{h}.2.1"], m[f"{h}.3.1"], m[f"{h}.4.1"] = "1.3.6.1.2.1.25.2.1.2", "RAM", 1024
        m[f"{h}.5.1"], m[f"{h}.6.1"] = 8_000_000, 8_000_000 * mem // 100
    if platform in ("arista_eos", "dell_os10", "allied_awplus"):
        e = "1.3.6.1.2.1.99.1.1.1"
        sensors = [(100006001, "Cpu temp sensor", 8, temp + 15, 1), (100006002, "Inlet sensor", 8, temp, 1 if not hot else 3),
                   (100601111, "Fan 1/1", 10, 8100, 1), (100602111, "Fan 2/1", 10, 8000 if ok_fan2 else 0, 1 if ok_fan2 else 3)]
        for k, n, kind, v, st in sensors:
            m[f"{e}.1.{k}"], m[f"{e}.2.{k}"], m[f"{e}.3.{k}"] = kind, 9, 0
            m[f"{e}.4.{k}"], m[f"{e}.5.{k}"], m[f"{ENT_NAME}.{k}"] = v, st, n
    return m


ENT_NAME = "1.3.6.1.2.1.47.1.1.1.1.7"


# --- the simulated interfaces --------------------------------------------------------------

DAY = 86400
PEAK_HOUR = 14  # UTC: the busiest time of the working day
HOT = {("hq-core1", "Ethernet1/48"): 0.55, ("bs-sw1", "port1.0.1"): 0.45}  # busy links: average load
ERRORS = {("hq-acc-sw3", "GigabitEthernet1/0/12"): 0.3}  # CRC errors a second (a bad cable)
DISCARDS = {("wh-sw1", "ethernet1/1/52"): 2.5}  # discards a second (a congested uplink)
ACCESS = {  # (how to name an access port, how many)
    "cisco_ios": ("GigabitEthernet1/0/{}", 24), "cisco_nxos": ("Ethernet1/{}", 12),
    "arista_eos": ("Ethernet{}", 16), "aruba_osswitch": ("{}", 24), "mikrotik_routeros": ("ether{}", 6),
    "allied_awplus": ("port1.0.{}", 24), "dell_os10": ("ethernet1/1/{}", 24),
    "cisco_asa": ("GigabitEthernet0/{}", 4), "juniper_junos": ("ge-0/0/{}", 4),
}
SHORT = (("TenGigabitEthernet", "Te"), ("GigabitEthernet", "Gi"))


def _speed(port: str, platform: str) -> int:
    p = port.lower()
    if re.search(r"(49|50)/1$", p) or p.startswith(("xe-", "sfp")) or (platform == "aruba_osswitch" and p in ("49", "50", "51", "52")):
        return 10_000_000_000 if not re.search(r"(49|50)/1$", p) else 100_000_000_000
    if platform in ("cisco_nxos",) and p.startswith("ethernet"):
        return 10_000_000_000
    if platform == "dell_os10":
        return 25_000_000_000
    if platform == "allied_awplus" and p in ("port1.0.27", "port1.0.28"):
        return 10_000_000_000
    return 1_000_000_000


def _platform_of(name: str) -> str:
    from app.demo import seed

    return next((d.platform for d in seed.DEVICES if d.name == name), "")


class SimPort:
    def __init__(self, index, device, port, platform, kind, alias, rand, peer=None):
        self.index, self.device, self.port, self.kind, self.alias = index, device, port, kind, alias
        self.descr = port
        self.name = port
        if platform == "cisco_ios":
            for long, short in SHORT:
                self.name = self.name.replace(long, short)
        self.type = {"vlan": 53, "loopback": 24}.get(kind, 6)
        self.speed = 0 if kind in ("vlan", "loopback") else _speed(port, platform)
        self.up = kind in ("link", "vlan", "loopback") or rand.random() < 0.65 or \
            (device, port) in ERRORS or (device, port) in DISCARDS
        if kind == "link":  # the same load at both ends, as much as the slower port takes
            n, rp = peer
            pair = random.Random("|".join(sorted([f"{device} {port}", f"{n} {rp}"])))
            load = HOT.get((device, port)) or HOT.get((n, rp)) or 0.04 + 0.25 * pair.random()
            self.avg = min(self.speed, _speed(rp, _platform_of(n) or platform)) * load
        else:
            self.avg = (2 + 28 * rand.random()) * 1e6 if self.up and kind == "access" else 0.0
        self.amp = self.avg * (0.6 if (device, port) in HOT else 0.8)
        self.ratio = 0.3 + 0.9 * rand.random()  # out against in
        self.err = ERRORS.get((device, port), 0.0)
        self.disc = DISCARDS.get((device, port), 0.0)
        self.phase = math.pi / 2 - 2 * math.pi * PEAK_HOUR / 24

    def bps(self, t: float, noise: float = 1.0) -> float:
        if not self.up or not self.avg:
            return 0.0
        return max(0.0, (self.avg + self.amp * math.sin(2 * math.pi * t / DAY + self.phase)) * noise)

    def octets(self, t: float, ratio: float = 1.0) -> int:
        """The byte counter at time t: the integral of the traffic (never goes backwards)."""
        if not self.up or not self.avg:
            return 123456
        k = DAY / (2 * math.pi)
        bits = self.avg * t - self.amp * k * math.cos(2 * math.pi * t / DAY + self.phase) + self.amp * k
        return int(bits * ratio / 8) % 2**64

    def value(self, key: str, t: float):
        v = {"descr": self.descr, "name": self.name, "alias": self.alias, "type": self.type,
             "speed": min(self.speed, 2**32 - 1), "high_speed": self.speed // 1_000_000,
             "admin": 1, "oper": 1 if self.up else 2,
             "hc_in": self.octets(t), "hc_out": self.octets(t, self.ratio),
             "in_err": int(self.err * t) % 2**32, "out_err": 0, "in_disc": 0,
             "out_disc": int(self.disc * t) % 2**32}
        if key in ("in", "out"):
            return v[f"hc_{key}"] % 2**32
        return v.get(key)


_PORTS: dict[str, list[SimPort]] = {}


def ports_of(name: str, platform: str) -> list[SimPort]:
    """The demo device's interfaces: its links on the demo map, access ports, a VLAN."""
    if name not in _PORTS:
        from app.demo import topology

        rand = random.Random(sum(ord(c) * (i + 3) for i, c in enumerate(name)))
        links = [(lp, f"to {n} {rp}", (n, rp)) for lp, n, rp in topology.neighbours_of(name)
                 if n not in ("hq-ap-01", "ap-bn-01", "wh-ap-01") and not n.startswith("SEP")]
        used = {lp for lp, _, _ in links}
        pattern, count = ACCESS.get(platform, ("port{}", 8))
        first = 2 if platform in ("mikrotik_routeros", "allied_awplus", "cisco_asa", "dell_os10") else 1
        access = [pattern.format(n) for n in range(first, first + count)]
        ports = [(p, "link", a, peer) for p, a, peer in links]
        ports += [(p, "access", "", None) for p in access if p not in used]
        if platform in ("cisco_ios", "cisco_nxos", "arista_eos"):
            ports.append(("Vlan10", "vlan", "management", None))
        ports.append(("Loopback0" if platform.startswith("cisco") else "lo0", "loopback", "", None))
        _PORTS[name] = [SimPort(i, name, p, platform, kind, alias, rand, peer)
                        for i, (p, kind, alias, peer) in enumerate(ports, 1)]
    return _PORTS[name]


# --- the demo's story ---------------------------------------------------------------------

DOWN = {"bn-sw3"}  # unplugged at the branch (its backups fail too)
NO_PING = {"hq-fw1"}  # the firewall drops ping; SNMP answers
SNMP_ERROR = {"bn-rtr1": "The device doesn't know this SNMPv3 user"}  # not set up for SNMP yet
FAULTS = {"hq-core2": {"psu2"}, "wh-sw3": {"fan2"}}  # a failed power supply, a stopped fan
CPU_HIGH = {"dc1-leaf2": 92.0}  # a busy control plane
RTT = {"HQ": 1.2, "DC1": 0.6, "Branch-North": 14.0, "Branch-South": 18.0, "Warehouse": 26.0}
HISTORY_DAYS = 3


def sim_for(net, clock=time.time) -> SimMonitor:
    """The demo network's ping and SNMP answers (also the profile Test button's)."""
    from app.demo import seed

    addresses = {d.name: seed.address(i) for i, d in enumerate(seed.DEVICES)}
    sim = SimMonitor(net, addresses, clock=clock)
    sim.down |= DOWN
    sim.no_ping |= NO_PING
    sim.snmp_error.update(SNMP_ERROR)
    sim.rtt.update({d.name: RTT.get(d.site, 2.0) for d in seed.DEVICES})
    sim.faults.update({k: set(v) for k, v in FAULTS.items()})
    sim.cpu.update(CPU_HIGH)
    return sim


def build(settings, sim: SimMonitor, cipher, clock=time.time):
    """The demo's poller: the simulated network answers instead of real ping and SNMP."""
    from app.tools.monitoring.poller import Poller
    from app.tools.monitoring.store import MonitorStore

    return Poller(settings, MonitorStore(settings.monitor_dir), cipher, snmp=sim,
                  pinger=sim.ping, clock=clock)


def history(poller, now: float | None = None) -> None:
    """Three days of made-up checks, so the graphs and availability have something to show:
    a branch switch that dropped off for a quarter of an hour yesterday, a leaf that
    restarted two days ago, and the unplugged switch, down since this morning."""
    from sqlalchemy import select

    from app.core.db import session_scope
    from app.core.models import Device
    from app.demo import seed

    now = now or time.time()
    with session_scope() as db:
        ids = dict(db.execute(select(Device.name, Device.id)).all())
    rand = random.Random(11)
    site = {d.name: d.site for d in seed.DEVICES}
    step = 60
    start = now - HISTORY_DAYS * 86400
    flap = (now - 86400 - 3 * 3600, now - 86400 - 3 * 3600 + 14 * 60)
    unplugged = now - 5 * 3600
    events = [
        {"ts": flap[0], "device_id": ids["bs-sw2"], "kind": "down", "detail": "No answer to ping or SNMP"},
        {"ts": flap[1], "device_id": ids["bs-sw2"], "kind": "up", "detail": "Answering again after 14 min"},
        {"ts": now - 2 * 86400 + 7200, "device_id": ids["dc1-leaf3"], "kind": "restarted",
         "detail": "Started after an upgrade (demo history)"},
        {"ts": unplugged, "device_id": ids["bn-sw3"], "kind": "down", "detail": "No answer to ping or SNMP"},
        {"ts": now - 26 * 3600, "device_id": ids["bn-rtr1"], "kind": "snmp_failed",
         "detail": SNMP_ERROR["bn-rtr1"]},
    ]
    samples = []
    t = start
    while t < now - 120:
        busy = 1.0 + 0.8 * max(0.0, math.sin((t % 86400) / 86400 * 2 * math.pi - 1.6))  # the working day
        for name, device_id in ids.items():
            off = (name == "bs-sw2" and flap[0] <= t < flap[1]) or (name in DOWN and t >= unplugged)
            ping = name not in NO_PING and not off
            rtt = round(RTT.get(site.get(name, ""), 2.0) * busy * (0.8 + 0.6 * rand.random()), 2) if ping else None
            samples.append((t, device_id, rtt, not off))
        t += step
    states = []
    for name, device_id in ids.items():  # where things stand as the history ends
        since = unplugged if name in DOWN else flap[1] if name == "bs-sw2" else start
        states.append({"device_id": device_id, "status": "down" if name in DOWN else "up",
                       "since": since, "fails": 99 if name in DOWN else 0, "reason": "",
                       "sys_name": "", "sys_descr": "", "sys_object_id": "", "maintenance": 0})
    for i in range(0, len(samples), 20000):
        poller.store.save(states if i == 0 else [], events if i == 0 else [], samples[i:i + 20000])
    poller.prev = poller.store.states()
    # interfaces: a reading every five minutes, and the counters as of five minutes ago, so
    # the first live reading already has rates
    from app.tools.monitoring import ifaces as ifm

    platform = {d.name: d.platform for d in seed.DEVICES}
    t0 = now - 300
    for name, device_id in ids.items():
        if name in DOWN or name in SNMP_ERROR:
            continue  # never read: down, or SNMP not set up
        ports = ports_of(name, platform.get(name, ""))
        isamples = []
        t = start - start % 300
        while t < t0:
            for p in ports:
                if p.up and p.avg and p.type != ifm.LOOPBACK:
                    in_bps = round(p.bps(t, 0.9 + 0.2 * rand.random()), 1)
                    isamples.append((t, p.index, in_bps, round(in_bps * p.ratio, 1),
                                     round(p.err * 60, 2), round(p.disc * 60, 2)))
            t += 300
        rows = [{"device_id": device_id, "if_index": p.index, "name": p.name, "descr": p.descr,
                 "alias": p.alias, "type": p.type, "admin": 1, "oper": 1 if p.up else 2,
                 "speed": p.speed, "since": start, "ts": t0,
                 "counters": {"in": p.value("hc_in", t0), "out": p.value("hc_out", t0),
                              "in_err": p.value("in_err", t0), "out_err": 0, "in_disc": 0,
                              "out_disc": p.value("out_disc", t0), "hc": True}} for p in ports]
        poller.store.save_interfaces(device_id, rows, isamples)
    # hardware health: a reading every 15 minutes, and where it stands now
    import asyncio

    from app.tools.monitoring import health as hw
    from app.tools.monitoring.snmp import SnmpTarget

    sim, clock = poller.snmp, poller.snmp.clock
    fault_since = {"hq-core2": now - 6 * 3600, "wh-sw3": now - 30 * 3600}
    try:
        for name, device_id in ids.items():
            if name in DOWN or name in SNMP_ERROR:
                continue
            target = SnmpTarget(seed.address(next(i for i, d in enumerate(seed.DEVICES) if d.name == name)))
            hsamples, record = [], None
            t = start - start % 900
            while t <= t0:
                sim.clock = lambda t=t: t
                faults = sim.faults.get(name, set())
                if name in fault_since and t < fault_since[name]:
                    sim.faults[name] = set()
                if name in CPU_HIGH and t < now - 2 * 3600:
                    sim.cpu.pop(name, None)
                readings, sources = asyncio.run(hw.read(sim, target, platform.get(name, "")))
                sim.faults[name] = faults
                if name in CPU_HIGH:
                    sim.cpu[name] = CPU_HIGH[name]
                hw.judge(readings, poller.settings.monitor_cpu_warn, poller.settings.monitor_mem_warn)
                for kind in ("cpu", "memory"):
                    vals = [r.value for r in readings if r.kind == kind and r.value is not None]
                    if vals:
                        hsamples.append((t, kind, max(vals)))
                for r in [r for r in readings if r.kind == "temperature" and r.value is not None][:8]:
                    hsamples.append((t, f"t:{r.name}", r.value))
                record = {"device_id": device_id, "ts": t, "status": hw.worst(readings),
                          "readings": [r.as_dict() for r in readings], "problems": hw.problems(readings),
                          "sources": sources, "discovered": t, "error": ""}
                t += 900
            if record:
                poller.store.save_health(record, hsamples)
    finally:
        sim.clock = clock
    poller.store.save([], [
        {"ts": fault_since["hq-core2"], "device_id": ids["hq-core2"], "kind": "health_problem",
         "detail": "PowerSupply-2 failed"},
        {"ts": fault_since["wh-sw3"], "device_id": ids["wh-sw3"], "kind": "health_problem",
         "detail": "Fan 2/1 failed"},
        {"ts": now - 2 * 3600, "device_id": ids["dc1-leaf2"], "kind": "health_problem", "detail": "CPU 92%"},
    ], [])
    poller.store.rollup(now, back_hours=HISTORY_DAYS * 24 + 2)
    poller.if_prev = {}
    poller.health = {}


def start(settings, sim: SimMonitor, cipher) -> None:
    """Run the demo's poller in a thread of its own (its own event loop)."""
    import asyncio
    import threading

    poller = build(settings, sim, cipher)
    threading.Thread(target=lambda: asyncio.run(poller.serve()), name="demo-monitor",
                     daemon=True).start()
