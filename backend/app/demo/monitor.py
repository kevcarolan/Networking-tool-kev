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
import time

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
        return {o: values.get(o) for o in oids}

    async def walk(self, target, oid: str, max_rows: int = 20000) -> list:
        await self.get(target, [SYS_NAME])
        return []


# --- the demo's story ---------------------------------------------------------------------

DOWN = {"bn-sw3"}  # unplugged at the branch (its backups fail too)
NO_PING = {"hq-fw1"}  # the firewall drops ping; SNMP answers
SNMP_ERROR = {"bn-rtr1": "The device doesn't know this SNMPv3 user"}  # not set up for SNMP yet
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


def start(settings, sim: SimMonitor, cipher) -> None:
    """Run the demo's poller in a thread of its own (its own event loop)."""
    import asyncio
    import threading

    poller = build(settings, sim, cipher)
    threading.Thread(target=lambda: asyncio.run(poller.serve()), name="demo-monitor",
                     daemon=True).start()
