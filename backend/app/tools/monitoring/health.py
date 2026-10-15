"""Hardware health over SNMP: CPU, memory, temperatures, fans and power supplies.

Each platform has its readers (``PLATFORM_PROBES``): the vendor's own MIB where it has one
(Cisco, Juniper, Fortinet, HPE, Extreme, Huawei, MikroTik, Check Point, Aruba controllers),
then the standard ones every other device answers (HOST-RESOURCES-MIB for CPU and memory,
ENTITY-SENSOR-MIB for temperatures and fans). The first read tries them all and remembers
the ones that answered; later reads use only those (tried again once a day).

Readers built from vendor documentation: confirm each on a real device (lab tests). A
reader that finds nothing simply adds nothing; it never fails the device.

The status of a temperature, fan or power supply is the device's own (normal, warning,
critical, failed, not present). A temperature with no status from the device is shown, not
judged. CPU and memory are judged against the Settings page thresholds by the poller.
"""

from dataclasses import asdict, dataclass

from app.tools.monitoring.snmp import SnmpError

OK, WARNING, CRITICAL, ABSENT, UNKNOWN = "ok", "warning", "critical", "absent", "unknown"
KINDS = {"cpu": "CPU", "memory": "Memory", "temperature": "Temperature", "fan": "Fan",
         "psu": "Power supply", "sensor": "Sensor"}
ENT_NAME = "1.3.6.1.2.1.47.1.1.1.1.7"  # ENTITY-MIB entPhysicalName
ENT_DESCR = "1.3.6.1.2.1.47.1.1.1.1.2"


@dataclass
class Reading:
    kind: str  # cpu, memory, temperature, fan, psu
    name: str
    value: float | None = None  # % for cpu and memory, °C for temperatures, rpm for fans
    status: str = OK
    source: str = ""
    unit: str = ""  # custom sensors (sensors.py)
    sensor: str = ""  # custom sensors: the sensor's own name (a table row's name adds its label)

    def as_dict(self) -> dict:
        return asdict(self)


def _rows(rows: list[tuple[str, object]], base: str) -> dict[str, object]:
    """Walked rows by the index after ``base`` ('1', '9.1.0.0'...)."""
    out = {}
    for oid, value in rows:
        if oid.startswith(base + "."):
            out[oid[len(base) + 1:]] = value
    return out


async def _walk(client, t, base: str) -> dict[str, object]:
    return _rows(await client.walk(t, base, max_rows=2000), base)


async def _names(client, t) -> dict[str, str]:
    names = await _walk(client, t, ENT_NAME)
    if not any(names.values()):
        names = await _walk(client, t, ENT_DESCR)
    return {k: str(v) for k, v in names.items() if v}


def _num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _pct(used, free=None, total=None) -> float | None:
    used, free, total = _num(used), _num(free), _num(total)
    if used is None:
        return None
    total = total if total else (used + free if free is not None else None)
    return round(100 * used / total, 1) if total else None


def _kind_of(name: str) -> str | None:
    n = name.lower()
    if "fan" in n:
        return "fan"
    if any(w in n for w in ("power", "psu", "pem", "ps ")) or n.startswith("ps"):
        return "psu"
    if "temp" in n or "thermal" in n or "°c" in n:
        return "temperature"
    return None


# --- standard MIBs ----------------------------------------------------------------------

async def host_cpu(c, t) -> list[Reading]:
    """HOST-RESOURCES-MIB hrProcessorLoad: the average of every core (last minute)."""
    loads = [v for v in (_num(x) for x in (await _walk(c, t, "1.3.6.1.2.1.25.3.3.1.2")).values())
             if v is not None]
    return [Reading("cpu", "CPU", round(sum(loads) / len(loads), 1), source="HOST-RESOURCES-MIB")] if loads else []


async def host_mem(c, t) -> list[Reading]:
    """HOST-RESOURCES-MIB hrStorage: the RAM row."""
    types = await _walk(c, t, "1.3.6.1.2.1.25.2.3.1.2")
    ram = [k for k, v in types.items() if str(v).endswith("1.3.6.1.2.1.25.2.1.2")]
    if not ram:
        return []
    size = await _walk(c, t, "1.3.6.1.2.1.25.2.3.1.5")
    used = await _walk(c, t, "1.3.6.1.2.1.25.2.3.1.6")
    pct = _pct(used.get(ram[0]), total=size.get(ram[0]))
    return [Reading("memory", "Memory", pct, source="HOST-RESOURCES-MIB")] if pct is not None else []


async def ucd_mem(c, t) -> list[Reading]:
    """UCD-SNMP-MIB (net-snmp on Linux): used = total - available - buffers - cache."""
    v = await c.get(t, ["1.3.6.1.4.1.2021.4.5.0", "1.3.6.1.4.1.2021.4.6.0",
                        "1.3.6.1.4.1.2021.4.14.0", "1.3.6.1.4.1.2021.4.15.0"])
    total, avail, buf, cache = (_num(v.get(o)) for o in ("1.3.6.1.4.1.2021.4.5.0", "1.3.6.1.4.1.2021.4.6.0",
                                                         "1.3.6.1.4.1.2021.4.14.0", "1.3.6.1.4.1.2021.4.15.0"))
    if not total or avail is None:
        return []
    used = total - avail - (buf or 0) - (cache or 0)
    return [Reading("memory", "Memory", round(100 * max(used, 0) / total, 1), source="UCD-SNMP-MIB")]


async def entity_sensor(c, t, base: str = "1.3.6.1.2.1.99.1.1.1", source: str = "ENTITY-SENSOR-MIB") -> list[Reading]:
    """Temperatures (celsius) and fans (rpm) from ENTITY-SENSOR-MIB (RFC 3433) or Cisco's
    copy of it: type, scale, precision, value and status per physical entity."""
    kinds = await _walk(c, t, f"{base}.1")
    wanted = {k: v for k, v in kinds.items() if v in (8, 10)}  # 8 celsius, 10 rpm
    if not wanted:
        return []
    scale, prec = await _walk(c, t, f"{base}.2"), await _walk(c, t, f"{base}.3")
    value, status = await _walk(c, t, f"{base}.4"), await _walk(c, t, f"{base}.5")
    names = await _names(c, t)
    out = []
    for k, kind in wanted.items():
        raw = _num(value.get(k))
        if raw is None:
            continue
        p = _num(prec.get(k)) or 0
        v = raw / (10 ** p) if 0 < p < 10 else raw
        if scale.get(k) not in (None, 9):  # 9 = units; others (milli, kilo...) are rare for these
            v = v * 10 ** ((int(scale[k]) - 9) * 3)
        st = {1: OK, 2: UNKNOWN, 3: CRITICAL}.get(status.get(k), UNKNOWN)
        name = names.get(k) or f"Sensor {k}"
        if kind == 8:
            out.append(Reading("temperature", name, round(v, 1), st, source))
        else:
            out.append(Reading("fan", name, round(v), st if not (st == OK and v == 0) else CRITICAL, source))
    return out


# --- Cisco -------------------------------------------------------------------------------

async def cisco_cpu(c, t) -> list[Reading]:
    """CISCO-PROCESS-MIB: CPU over 5 minutes; IOS-XE, NX-OS and XR also give memory."""
    cpu = await _walk(c, t, "1.3.6.1.4.1.9.9.109.1.1.1.1.8")
    out = []
    for i, (k, v) in enumerate(sorted(cpu.items())):
        if _num(v) is not None:
            out.append(Reading("cpu", "CPU" if len(cpu) == 1 else f"CPU {i + 1}", float(v),
                               source="CISCO-PROCESS-MIB"))
    if out:
        used = await _walk(c, t, "1.3.6.1.4.1.9.9.109.1.1.1.1.12")
        free = await _walk(c, t, "1.3.6.1.4.1.9.9.109.1.1.1.1.13")
        k = next(iter(sorted(used)), None)
        pct = _pct(used.get(k), free.get(k)) if k else None
        if pct is not None:
            out.append(Reading("memory", "Memory", pct, source="CISCO-PROCESS-MIB"))
    return out


async def cisco_mempool(c, t) -> list[Reading]:
    """CISCO-MEMORY-POOL-MIB: the processor pool (IOS, ASA)."""
    used = await _walk(c, t, "1.3.6.1.4.1.9.9.48.1.1.1.5")
    if not used:
        return []
    free = await _walk(c, t, "1.3.6.1.4.1.9.9.48.1.1.1.6")
    k = "1" if "1" in used else sorted(used)[0]
    pct = _pct(used.get(k), free.get(k))
    return [Reading("memory", "Memory", pct, source="CISCO-MEMORY-POOL-MIB")] if pct is not None else []


ENVMON = {1: OK, 2: WARNING, 3: CRITICAL, 4: CRITICAL, 5: ABSENT, 6: CRITICAL}


async def cisco_envmon(c, t) -> list[Reading]:
    """CISCO-ENVMON-MIB: temperatures, fans and power supplies with the device's state."""
    base, out = "1.3.6.1.4.1.9.9.13.1", []
    for kind, table, value_col, state_col in (("temperature", 3, 3, 6), ("fan", 4, None, 3),
                                              ("psu", 5, None, 3)):
        descr = await _walk(c, t, f"{base}.{table}.1.2")
        if not descr:
            continue
        state = await _walk(c, t, f"{base}.{table}.1.{state_col}")
        values = await _walk(c, t, f"{base}.{table}.1.{value_col}") if value_col else {}
        for k, name in descr.items():
            out.append(Reading(kind, str(name), _num(values.get(k)),
                               ENVMON.get(state.get(k), UNKNOWN), "CISCO-ENVMON-MIB"))
    return out


async def cisco_entity_sensor(c, t) -> list[Reading]:
    return await entity_sensor(c, t, "1.3.6.1.4.1.9.9.91.1.1.1.1", "CISCO-ENTITY-SENSOR-MIB")


async def cisco_fru(c, t) -> list[Reading]:
    """CISCO-ENTITY-FRU-CONTROL-MIB: power supplies and fan trays (NX-OS, XR, IOS-XE)."""
    psu = await _walk(c, t, "1.3.6.1.4.1.9.9.117.1.1.2.1.2")
    fans = await _walk(c, t, "1.3.6.1.4.1.9.9.117.1.4.1.1.1")
    if not psu and not fans:
        return []
    names = await _names(c, t)
    out = [Reading("psu", names.get(k, f"Power supply {k}"), None,
                   OK if v == 2 else UNKNOWN if v == 3 else CRITICAL, "CISCO-ENTITY-FRU-CONTROL-MIB")
           for k, v in psu.items()]
    out += [Reading("fan", names.get(k, f"Fan tray {k}"), None,
                    {2: OK, 3: CRITICAL, 4: WARNING}.get(v, UNKNOWN), "CISCO-ENTITY-FRU-CONTROL-MIB")
            for k, v in fans.items()]
    return out


async def cisco_smb_cpu(c, t) -> list[Reading]:
    """Cisco small business (CBS, Catalyst 1200/1300): rlCpuUtilDuringLast5Minutes."""
    v = (await c.get(t, ["1.3.6.1.4.1.9.6.1.101.1.9.0"])).get("1.3.6.1.4.1.9.6.1.101.1.9.0")
    return [Reading("cpu", "CPU", float(v), source="CISCOSB-rndMng")] if _num(v) is not None and v != 101 else []


# --- other vendors -------------------------------------------------------------------------

async def juniper(c, t) -> list[Reading]:
    """JUNIPER-MIB jnxOperatingTable: every component's state; the routing engine's CPU,
    memory and temperature; other boards' temperatures."""
    base = "1.3.6.1.4.1.2636.3.1.13.1"
    descr = await _walk(c, t, f"{base}.5")
    if not descr:
        return []
    state, temp = await _walk(c, t, f"{base}.6"), await _walk(c, t, f"{base}.7")
    cpu, mem = await _walk(c, t, f"{base}.8"), await _walk(c, t, f"{base}.11")
    out = []
    for k, d in descr.items():
        name, kind = str(d), _kind_of(str(d))
        st = state.get(k)
        if kind in ("fan", "psu"):
            status = {2: OK, 3: OK, 5: WARNING, 6: CRITICAL, 7: OK}.get(st, UNKNOWN)
            if kind == "psu" and st == 1:
                status = ABSENT
            out.append(Reading(kind, name, None, status, "JUNIPER-MIB"))
            continue
        if "routing engine" in name.lower() and (_num(cpu.get(k)) or _num(mem.get(k))):
            out.append(Reading("cpu", f"CPU ({name})", _num(cpu.get(k)), source="JUNIPER-MIB"))
            out.append(Reading("memory", f"Memory ({name})", _num(mem.get(k)), source="JUNIPER-MIB"))
        if _num(temp.get(k)):
            out.append(Reading("temperature", name, _num(temp.get(k)),
                               CRITICAL if st == 6 else OK, "JUNIPER-MIB"))
    return out


async def fortinet(c, t) -> list[Reading]:
    """FORTINET-FORTIGATE-MIB: CPU and memory in %, hardware sensors with an alarm flag."""
    v = await c.get(t, ["1.3.6.1.4.1.12356.101.4.1.3.0", "1.3.6.1.4.1.12356.101.4.1.4.0"])
    out = []
    if _num(v.get("1.3.6.1.4.1.12356.101.4.1.3.0")) is not None:
        out.append(Reading("cpu", "CPU", float(v["1.3.6.1.4.1.12356.101.4.1.3.0"]), source="FORTINET-FORTIGATE-MIB"))
    if _num(v.get("1.3.6.1.4.1.12356.101.4.1.4.0")) is not None:
        out.append(Reading("memory", "Memory", float(v["1.3.6.1.4.1.12356.101.4.1.4.0"]), source="FORTINET-FORTIGATE-MIB"))
    names = await _walk(c, t, "1.3.6.1.4.1.12356.101.4.3.2.1.2")
    if names:
        values = await _walk(c, t, "1.3.6.1.4.1.12356.101.4.3.2.1.3")
        alarm = await _walk(c, t, "1.3.6.1.4.1.12356.101.4.3.2.1.4")
        for k, n in names.items():
            kind = _kind_of(str(n)) or ("temperature" if "temp" in str(n).lower() else None)
            if kind:
                out.append(Reading(kind, str(n), _num(values.get(k)),
                                   CRITICAL if alarm.get(k) == 1 else OK, "FORTINET-FORTIGATE-MIB"))
    return out


async def hp_procurve(c, t) -> list[Reading]:
    """HP ArubaOS-Switch (ProCurve): STATISTICS-MIB CPU, NETSWITCH-MIB memory, and
    HP-ICF-CHASSIS sensors (fans, power supplies, over-temperature)."""
    v = await c.get(t, ["1.3.6.1.4.1.11.2.14.11.5.1.9.6.1.0"])
    out = []
    if _num(v.get("1.3.6.1.4.1.11.2.14.11.5.1.9.6.1.0")) is not None:
        out.append(Reading("cpu", "CPU", float(v["1.3.6.1.4.1.11.2.14.11.5.1.9.6.1.0"]), source="HP STATISTICS-MIB"))
    total = await _walk(c, t, "1.3.6.1.4.1.11.2.14.11.5.1.1.2.1.1.1.5")
    if total:
        free = await _walk(c, t, "1.3.6.1.4.1.11.2.14.11.5.1.1.2.1.1.1.6")
        k = sorted(total)[0]
        if _num(total.get(k)) and _num(free.get(k)) is not None:
            out.append(Reading("memory", "Memory", round(100 * (1 - float(free[k]) / float(total[k])), 1),
                               source="HP NETSWITCH-MIB"))
    descr = await _walk(c, t, "1.3.6.1.4.1.11.2.14.11.1.2.6.1.7")
    if descr:
        status = await _walk(c, t, "1.3.6.1.4.1.11.2.14.11.1.2.6.1.4")
        for k, d in descr.items():
            kind = _kind_of(str(d))
            if kind:
                out.append(Reading(kind, str(d), None, {2: CRITICAL, 3: WARNING, 4: OK, 5: ABSENT}.get(
                    status.get(k), UNKNOWN), "HP-ICF-CHASSIS"))
    return out


async def extreme(c, t) -> list[Reading]:
    """EXTREME-SYSTEM-MIB and EXTREME-SOFTWARE-MONITOR-MIB."""
    v = await c.get(t, ["1.3.6.1.4.1.1916.1.32.1.2.0", "1.3.6.1.4.1.1916.1.1.1.8.0",
                        "1.3.6.1.4.1.1916.1.1.1.7.0"])
    out = []
    if _num(v.get("1.3.6.1.4.1.1916.1.32.1.2.0")) is not None:
        out.append(Reading("cpu", "CPU", float(v["1.3.6.1.4.1.1916.1.32.1.2.0"]), source="EXTREME-SOFTWARE-MONITOR-MIB"))
    if _num(v.get("1.3.6.1.4.1.1916.1.1.1.8.0")) is not None:
        out.append(Reading("temperature", "System", float(v["1.3.6.1.4.1.1916.1.1.1.8.0"]),
                           CRITICAL if v.get("1.3.6.1.4.1.1916.1.1.1.7.0") == 1 else OK, "EXTREME-SYSTEM-MIB"))
    total = await _walk(c, t, "1.3.6.1.4.1.1916.1.32.2.2.1.2")
    if total:
        free = await _walk(c, t, "1.3.6.1.4.1.1916.1.32.2.2.1.3")
        k = sorted(total)[0]
        if _num(total.get(k)) and _num(free.get(k)) is not None:
            out.append(Reading("memory", "Memory", round(100 * (1 - float(free[k]) / float(total[k])), 1),
                               source="EXTREME-SOFTWARE-MONITOR-MIB"))
    for k, s in (await _walk(c, t, "1.3.6.1.4.1.1916.1.1.1.9.1.2")).items():
        out.append(Reading("fan", f"Fan {k}", None, OK if s == 1 else CRITICAL, "EXTREME-SYSTEM-MIB"))
    for k, s in (await _walk(c, t, "1.3.6.1.4.1.1916.1.1.1.27.1.2")).items():
        out.append(Reading("psu", f"Power supply {k}", None, {1: ABSENT, 2: OK, 3: CRITICAL}.get(s, UNKNOWN),
                           "EXTREME-SYSTEM-MIB"))
    return out


async def huawei(c, t) -> list[Reading]:
    """HUAWEI-ENTITY-EXTENT-MIB: CPU, memory and temperature of the main boards; fans."""
    base = "1.3.6.1.4.1.2011.5.25.31.1.1.1.1"
    cpu = {k: v for k, v in (await _walk(c, t, f"{base}.5")).items() if _num(v)}
    out = []
    if cpu:
        mem, temp = await _walk(c, t, f"{base}.7"), await _walk(c, t, f"{base}.11")
        names = await _names(c, t)
        for k, v in cpu.items():
            board = names.get(k, f"Board {k}")
            out.append(Reading("cpu", f"CPU ({board})" if len(cpu) > 1 else "CPU", float(v), source="HUAWEI-ENTITY-EXTENT-MIB"))
            if _num(mem.get(k)) is not None:
                out.append(Reading("memory", f"Memory ({board})" if len(cpu) > 1 else "Memory", float(mem[k]),
                                   source="HUAWEI-ENTITY-EXTENT-MIB"))
            if _num(temp.get(k)):
                out.append(Reading("temperature", board, float(temp[k]), source="HUAWEI-ENTITY-EXTENT-MIB"))
    for k, s in (await _walk(c, t, "1.3.6.1.4.1.2011.5.25.31.1.1.10.1.7")).items():
        out.append(Reading("fan", f"Fan {k}", None, OK if s == 1 else CRITICAL, "HUAWEI-ENTITY-EXTENT-MIB"))
    return out


async def mikrotik(c, t) -> list[Reading]:
    """MIKROTIK-MIB gauges (RouterOS 7): temperatures and fan speeds."""
    names = await _walk(c, t, "1.3.6.1.4.1.14988.1.1.3.100.1.2")
    if not names:
        return []
    values = await _walk(c, t, "1.3.6.1.4.1.14988.1.1.3.100.1.3")
    units = await _walk(c, t, "1.3.6.1.4.1.14988.1.1.3.100.1.4")
    out = []
    for k, n in names.items():
        v = _num(values.get(k))
        if v is None:
            continue
        if units.get(k) == 1:
            out.append(Reading("temperature", str(n), v, source="MIKROTIK-MIB"))
        elif units.get(k) == 2:
            out.append(Reading("fan", str(n), v, OK if v > 0 else CRITICAL, "MIKROTIK-MIB"))
    return out


async def checkpoint(c, t) -> list[Reading]:
    """CHECKPOINT-MIB: CPU and real memory."""
    oids = ["1.3.6.1.4.1.2620.1.6.7.2.4.0", "1.3.6.1.4.1.2620.1.6.7.4.3.0", "1.3.6.1.4.1.2620.1.6.7.4.4.0"]
    v = await c.get(t, oids)
    out = []
    if _num(v.get(oids[0])) is not None:
        out.append(Reading("cpu", "CPU", float(v[oids[0]]), source="CHECKPOINT-MIB"))
    if _num(v.get(oids[1])) and _num(v.get(oids[2])) is not None:
        out.append(Reading("memory", "Memory", round(100 * float(v[oids[2]]) / float(v[oids[1]]), 1),
                           source="CHECKPOINT-MIB"))
    return out


async def aruba_aos8(c, t) -> list[Reading]:
    """WLSX-SYSTEMEXT-MIB (Aruba Mobility Controllers): processor load and memory."""
    load = await _walk(c, t, "1.3.6.1.4.1.14823.2.2.1.2.1.13.1.3")
    out = []
    if load:
        vals = [v for v in (_num(x) for x in load.values()) if v is not None]
        if vals:
            out.append(Reading("cpu", "CPU", round(sum(vals) / len(vals), 1), source="WLSX-SYSTEMEXT-MIB"))
    size = await _walk(c, t, "1.3.6.1.4.1.14823.2.2.1.2.1.15.1.2")
    if size:
        used = await _walk(c, t, "1.3.6.1.4.1.14823.2.2.1.2.1.15.1.3")
        k = sorted(size)[0]
        pct = _pct(used.get(k), total=size.get(k))
        if pct is not None:
            out.append(Reading("memory", "Memory", pct, source="WLSX-SYSTEMEXT-MIB"))
    return out


PROBES = {
    "host_cpu": host_cpu, "host_mem": host_mem, "ucd_mem": ucd_mem, "entity_sensor": entity_sensor,
    "cisco_cpu": cisco_cpu, "cisco_mempool": cisco_mempool, "cisco_envmon": cisco_envmon,
    "cisco_entity_sensor": cisco_entity_sensor, "cisco_fru": cisco_fru, "cisco_smb_cpu": cisco_smb_cpu,
    "juniper": juniper, "fortinet": fortinet, "hp_procurve": hp_procurve, "extreme": extreme,
    "huawei": huawei, "mikrotik": mikrotik, "checkpoint": checkpoint, "aruba_aos8": aruba_aos8,
}
GENERIC = ["host_cpu", "host_mem", "entity_sensor"]
PLATFORM_PROBES: dict[str, list[str]] = {
    "cisco_ios": ["cisco_cpu", "cisco_mempool", "cisco_envmon", "cisco_entity_sensor", "cisco_fru"],
    "cisco_nxos": ["cisco_cpu", "cisco_entity_sensor", "cisco_fru"],
    "cisco_xr": ["cisco_cpu", "cisco_entity_sensor", "cisco_fru"],
    "cisco_asa": ["cisco_cpu", "cisco_mempool", "cisco_entity_sensor"],
    "cisco_ftd": ["cisco_cpu", "cisco_mempool", "cisco_entity_sensor"],
    "cisco_smb": ["cisco_smb_cpu"],
    "juniper_junos": ["juniper"],
    "fortinet_fortios": ["fortinet"],
    "paloalto_panos": [],
    "checkpoint_gaia": ["checkpoint", "ucd_mem"],
    "arista_eos": [],
    "aruba_aoscx": [],
    "aruba_osswitch": ["hp_procurve"],
    "aruba_aos8": ["aruba_aos8"],
    "dell_os10": [],
    "extreme_exos": ["extreme"],
    "huawei_vrp": ["huawei"],
    "mikrotik_routeros": ["mikrotik"],
    "ubiquiti_edgeos": ["ucd_mem"],
    "allied_awplus": [],
    # SNMP only: the standard readers (HOST-RESOURCES, ENTITY-SENSOR) where the card has them;
    # the rest through custom sensors (sensors.EXAMPLES has the UPS-MIB and APC ones)
    "snmp_ups": [], "snmp_pdu": [], "snmp_env": [], "snmp_other": [],
}


def probes_for(platform: str) -> list[str]:
    """The readers to try for a platform: its own, then the standard ones."""
    own = PLATFORM_PROBES.get(platform, [])
    return own + [g for g in GENERIC if g not in own]


async def read(client, target, platform: str, known: list[str] | None = None) -> tuple[list[Reading], list[str]]:
    """Every reading the device gives, and the readers that answered. ``known``: only
    these readers (the ones that answered before)."""
    readings: list[Reading] = []
    answered: list[str] = []
    timeouts = 0
    for name in known or probes_for(platform):
        try:
            got = await PROBES[name](client, target)
        except SnmpError as exc:
            if "timed out" in str(exc):
                timeouts += 1
                if timeouts >= 2:
                    raise  # the device stopped answering: try again next time
            continue
        if got:
            answered.append(name)
            readings += got
    # One CPU and one memory figure per name: a vendor reader wins over the standard one;
    # the same sensor from two readers is kept once.
    seen, out = set(), []
    has_vendor = {r.kind for r in readings if not r.source.startswith(("HOST-RESOURCES", "ENTITY-SENSOR"))}
    for r in readings:
        if r.kind in ("cpu", "memory") and r.kind in has_vendor and r.source.startswith("HOST-RESOURCES"):
            continue
        key = (r.kind, r.name.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out, answered


def judge(readings: list[Reading], cpu_warn: int, mem_warn: int) -> list[Reading]:
    """CPU and memory against the thresholds (the device judges everything else)."""
    for r in readings:
        if r.kind == "cpu" and r.value is not None:
            r.status = WARNING if r.value >= cpu_warn else OK
        elif r.kind == "memory" and r.value is not None:
            r.status = WARNING if r.value >= mem_warn else OK
    return readings


def problems(readings: list[Reading]) -> dict[str, str]:
    """What needs a look: key -> text, e.g. 'psu:power supply 2' -> 'Power supply 2 failed'."""
    out = {}
    for r in readings:
        if r.status not in (WARNING, CRITICAL):
            continue
        key = f"{r.kind}:{r.name.lower()}"
        if r.kind == "sensor":
            from app.tools.monitoring.sensors import problem_text
            out[key] = problem_text(r)
        elif r.kind in ("cpu", "memory"):
            out[key] = f"{r.name} {r.value:.0f}%"
        elif r.kind == "temperature":
            out[key] = f"Temperature {r.name} {'critical' if r.status == CRITICAL else 'high'}" + (
                f" ({r.value:.0f} °C)" if r.value is not None else "")
        else:
            what = r.name if KINDS[r.kind].lower().split()[0] in r.name.lower() else f"{KINDS[r.kind]} {r.name}"
            out[key] = f"{what} {'failed' if r.status == CRITICAL else 'warning'}"
    return out


def worst(readings: list[Reading]) -> str:
    s = {r.status for r in readings}
    return CRITICAL if CRITICAL in s else WARNING if WARNING in s else OK if readings else UNKNOWN
