"""Interfaces over SNMP (IF-MIB): each port's name, description, status and speed, and its
traffic, error and discard counters, turned into rates between two reads.

Read every ``monitor_interface_seconds`` (5 minutes by default) with GETBULK walks of the
IF-MIB columns below: the 64-bit counters (ifXTable) where the device has them, else the
32-bit ones (which wrap after 4 GB, about 34 seconds at 1 Gb/s, so 64-bit matters on fast
links). A counter that went backwards is a wrap (32-bit) or a restart (64-bit: no rate for
that interval).
"""

from dataclasses import dataclass, field

IF_DESCR = "1.3.6.1.2.1.2.2.1.2"
IF_TYPE = "1.3.6.1.2.1.2.2.1.3"
IF_SPEED = "1.3.6.1.2.1.2.2.1.5"  # bits/s, 32-bit (tops out at 4.29 Gb/s)
IF_ADMIN = "1.3.6.1.2.1.2.2.1.7"  # 1 up, 2 down, 3 testing
IF_OPER = "1.3.6.1.2.1.2.2.1.8"  # 1 up, 2 down, 3 testing, 5 dormant, 6 notPresent, 7 lowerLayerDown
IF_IN_OCTETS = "1.3.6.1.2.1.2.2.1.10"
IF_IN_DISCARDS = "1.3.6.1.2.1.2.2.1.13"
IF_IN_ERRORS = "1.3.6.1.2.1.2.2.1.14"
IF_OUT_OCTETS = "1.3.6.1.2.1.2.2.1.16"
IF_OUT_DISCARDS = "1.3.6.1.2.1.2.2.1.19"
IF_OUT_ERRORS = "1.3.6.1.2.1.2.2.1.20"
IF_NAME = "1.3.6.1.2.1.31.1.1.1.1"
IF_HC_IN = "1.3.6.1.2.1.31.1.1.1.6"
IF_HC_OUT = "1.3.6.1.2.1.31.1.1.1.10"
IF_HIGH_SPEED = "1.3.6.1.2.1.31.1.1.1.15"  # Mb/s
IF_ALIAS = "1.3.6.1.2.1.31.1.1.1.18"  # the description set on the port

COLUMNS = {"descr": IF_DESCR, "type": IF_TYPE, "speed": IF_SPEED, "admin": IF_ADMIN,
           "oper": IF_OPER, "in": IF_IN_OCTETS, "in_disc": IF_IN_DISCARDS, "in_err": IF_IN_ERRORS,
           "out": IF_OUT_OCTETS, "out_disc": IF_OUT_DISCARDS, "out_err": IF_OUT_ERRORS,
           "name": IF_NAME, "hc_in": IF_HC_IN, "hc_out": IF_HC_OUT, "high_speed": IF_HIGH_SPEED,
           "alias": IF_ALIAS}
LOOPBACK = 24  # softwareLoopback: never graphed
LAG = 161  # ieee8023adLag: a port-channel, always watched
OPER = {1: "up", 2: "down", 3: "testing", 4: "unknown", 5: "dormant", 6: "not present",
        7: "lower layer down"}
MAX_PER_DEVICE = 1000  # interfaces read per device (physical ones first)
WRAP32 = 2**32


@dataclass
class Iface:
    index: int
    name: str = ""
    descr: str = ""
    alias: str = ""
    type: int = 0
    admin: int = 0
    oper: int = 0
    speed: int = 0  # bits/s
    hc: bool = False
    counters: dict = field(default_factory=dict)  # in, out, in_err, out_err, in_disc, out_disc

    @property
    def label(self) -> str:
        return self.name or self.descr or f"ifIndex {self.index}"

    @property
    def watched(self) -> bool:
        """Its going down is an event: it has a description, or it is a port-channel."""
        return bool(self.alias.strip()) or self.type == LAG

    @property
    def graphed(self) -> bool:
        return self.admin == 1 and self.type != LOOPBACK


def from_walks(columns: dict[str, list[tuple[str, object]]]) -> list[Iface]:
    """The walked columns (key -> [(oid, value)]) as interfaces, by ifIndex."""
    out: dict[int, Iface] = {}
    for key, rows in columns.items():
        base = COLUMNS[key]
        for oid, value in rows:
            if not oid.startswith(base + "."):
                continue
            try:
                index = int(oid[len(base) + 1:].split(".")[0])
            except ValueError:
                continue
            i = out.setdefault(index, Iface(index))
            if key in ("name", "descr", "alias"):
                setattr(i, key, str(value or "")[:200])
            elif key in ("type", "admin", "oper") and isinstance(value, int):
                setattr(i, key, value)
            elif key == "speed" and isinstance(value, int) and not i.speed:
                i.speed = value
            elif key == "high_speed" and isinstance(value, int) and value:
                i.speed = value * 1_000_000
            elif key in ("hc_in", "hc_out") and isinstance(value, int):
                i.counters[key[3:]] = value
                i.hc = True
            elif key in ("in", "out") and isinstance(value, int):
                i.counters.setdefault(key, value)  # the 64-bit one wins if there is one
            elif isinstance(value, int):
                i.counters[key] = value
    ifaces = sorted(out.values(), key=lambda i: (i.type in (53, 136, 131, LOOPBACK), i.index))
    return sorted(ifaces[:MAX_PER_DEVICE], key=lambda i: i.index)


def _delta(new, old, wide: bool) -> int | None:
    if new is None or old is None:
        return None
    if new >= old:
        return new - old
    return None if wide else new + WRAP32 - old  # 64-bit backwards: a reset


def rates(new: Iface, old: dict | None, elapsed: float) -> dict:
    """Bits/s in and out, errors and discards a minute, and how full the port is (0..1),
    from the counters of the read before (``old``: the stored counters)."""
    out = {"in_bps": None, "out_bps": None, "errors": None, "discards": None,
           "in_util": None, "out_util": None}
    if not old or elapsed <= 0:
        return out
    c, o = new.counters, old
    wide = new.hc and bool(o.get("hc"))
    for key, name in (("in", "in_bps"), ("out", "out_bps")):
        d = _delta(c.get(key), o.get(key), wide)
        if d is not None:
            bps = d * 8 / elapsed
            if not new.speed or bps <= new.speed * 1.5:  # more than the port can carry: bogus
                out[name] = round(bps, 1)
    for keys, name in ((("in_err", "out_err"), "errors"), (("in_disc", "out_disc"), "discards")):
        ds = [_delta(c.get(k), o.get(k), False) for k in keys]
        ds = [d for d in ds if d is not None and d < WRAP32 // 2]
        if ds:
            out[name] = round(sum(ds) * 60 / elapsed, 2)
    if new.speed:
        for key in ("in", "out"):
            if out[f"{key}_bps"] is not None:
                out[f"{key}_util"] = round(min(out[f"{key}_bps"] / new.speed, 1.0), 4)
    return out
