"""Custom SNMP sensors: any value a device gives over SNMP, by its OID, with thresholds.

An admin adds a sensor (Monitoring › Sensors) with the OID to read and which devices it is
for (a platform, a site, chosen devices, or every SNMP device). The poller reads it with the
hardware health, every ``monitor_health_seconds``, so a sensor is one more health reading:
its history is graphed, and a value past a threshold makes the device a warning, an event
and an email alert, like a failed fan.

Three ways to read a value:

* ``value``: the number as the device gives it (a temperature, a percentage, sessions...),
  times ``scale`` (e.g. 0.1 for tenths of a degree);
* ``rate``: a counter that only goes up (packets, errors, bytes): the change per second
  since the last read, times ``scale``;
* ``state``: a status code (1 = normal, 2 = on battery...): fine when the value is one of
  ``ok_values``, otherwise critical (or warning when it is one of ``warn_values``).

A sensor can be one value (an OID ending in its instance, often ``.0``) or a **table**
column: every row is read, up to ``TABLE_ROWS``, each its own reading, named by the
``label_oid`` column if there is one (e.g. a port or peer name), else by the row's index.

Read-only: SNMP GET and GETBULK, like everything else in monitoring.
"""

import re

from app.tools.monitoring.health import CRITICAL, OK, UNKNOWN, WARNING, Reading, _rows
from app.tools.monitoring.snmp import SnmpError

MODES = {"value": "Value", "rate": "Rate (a counter, per second)", "state": "State (status codes)"}
TABLE_ROWS = 50
MAX_PER_DEVICE = 40  # sensors on one device; more are not read
OID_RE = re.compile(r"^\.?(\d+\.){3,}\d+$")
COUNTER_WRAP = (2**32, 2**64)


def clean_oid(oid: str) -> str:
    """'.1.3.6.1.2.1.1.3.0' -> '1.3.6.1.2.1.1.3.0'; raises ValueError if it isn't a numeric OID."""
    oid = (oid or "").strip()
    if not OID_RE.match(oid):
        raise ValueError("Enter the OID in numbers, e.g. 1.3.6.1.4.1.318.1.1.1.2.2.1.0 "
                         "(snmptranslate -On turns a name into numbers)")
    return oid.lstrip(".")


def codes(text: str) -> set[str]:
    """'2, 3' -> {'2', '3'}."""
    return {c.strip() for c in (text or "").replace(";", ",").split(",") if c.strip()}


def applies(sensor: dict, device_id: int, platform: str, site: str) -> bool:
    if not sensor.get("enabled", True):
        return False
    if sensor.get("device_ids"):
        return device_id in sensor["device_ids"]
    if sensor.get("platform") and sensor["platform"] != platform:
        return False
    return not (sensor.get("site") and sensor["site"].lower() != (site or "").lower())


def judge(sensor: dict, value) -> str:
    """The status of one value against the sensor's thresholds or codes."""
    if value is None:
        return UNKNOWN
    if sensor["mode"] == "state":
        text = str(value).strip()
        try:
            text = str(int(float(text)))
        except ValueError:
            pass
        if text in codes(sensor.get("ok_values", "")):
            return OK
        return WARNING if text in codes(sensor.get("warn_values", "")) else CRITICAL
    v = float(value)
    for limit, above, status in (("crit_above", True, CRITICAL), ("crit_below", False, CRITICAL),
                                 ("warn_above", True, WARNING), ("warn_below", False, WARNING)):
        x = sensor.get(limit)
        if x is not None and (v > x if above else v < x):  # strictly: "below 1" is 0
            return status
    return OK


def _number(raw):
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return raw
    try:
        return float(str(raw).strip().split()[0])  # "23.5 C" from some agents
    except (ValueError, IndexError):
        return None


def _value(sensor: dict, key: str, raw, now: float, prev: dict) -> tuple[object, str]:
    """(the value to show, a note) for one raw SNMP value."""
    if raw is None:
        return None, "the device doesn't have this OID"
    if sensor["mode"] == "state":
        n = _number(raw)
        return (int(n) if n is not None and float(n).is_integer() else str(raw)[:60]), ""
    n = _number(raw)
    if n is None:
        return None, f"not a number ({str(raw)[:40]})"
    scale = sensor.get("scale") or 1
    if sensor["mode"] == "value":
        return round(n * scale, 3), ""
    last = prev.get(key)
    prev[key] = (now, n)
    if not last or now <= last[0]:
        return None, "first read: the rate is shown from the next one"
    delta = n - last[1]
    if delta < 0:  # the counter wrapped (or the device restarted)
        wrap = next((w for w in COUNTER_WRAP if last[1] < w), None)
        if wrap is None or wrap - last[1] + n > wrap / 2:
            return None, "the counter went back (restart?)"
        delta += wrap
    return round(delta / (now - last[0]) * scale, 3), ""


async def read(client, target, sensors: list[dict], now: float, prev: dict) -> list[Reading]:
    """Every reading from these sensors on one device. ``prev`` keeps the raw counters for
    ``rate`` sensors between reads (key: sensor id and row)."""
    out: list[Reading] = []
    scalars = [s for s in sensors if not s.get("table")][:MAX_PER_DEVICE]
    if scalars:
        try:
            got = await client.get(target, [s["oid"] for s in scalars])
        except SnmpError as exc:
            if "timed out" in str(exc):
                raise
            got = {}
            for s in scalars:  # one bad OID can spoil a whole GET on some agents
                try:
                    got.update(await client.get(target, [s["oid"]]))
                except SnmpError:
                    got[s["oid"]] = None
        for s in scalars:
            value, note = _value(s, f"{s['id']}", got.get(s["oid"]), now, prev)
            out.append(_reading(s, s["name"], value, note))
    for s in [s for s in sensors if s.get("table")][:max(0, MAX_PER_DEVICE - len(scalars))]:
        try:
            rows = _rows(await client.walk(target, s["oid"], max_rows=TABLE_ROWS), s["oid"])
            labels = _rows(await client.walk(target, s["label_oid"], max_rows=TABLE_ROWS),
                           s["label_oid"]) if s.get("label_oid") else {}
        except SnmpError as exc:
            if "timed out" in str(exc):
                raise
            out.append(_reading(s, s["name"], None, str(exc)))
            continue
        if not rows:
            out.append(_reading(s, s["name"], None, "the device has no rows under this OID"))
        for index, raw in list(rows.items())[:TABLE_ROWS]:
            label = str(labels.get(index) or index)[:60]
            value, note = _value(s, f"{s['id']}:{index}", raw, now, prev)
            out.append(_reading(s, f"{s['name']} {label}", value, note))
    return out


def _reading(sensor: dict, name: str, value, note: str) -> Reading:
    status = judge(sensor, value) if value is not None else UNKNOWN
    return Reading("sensor", name[:100], value, status, note or f"OID {sensor['oid']}",
                   unit=sensor.get("unit", ""), sensor=sensor["name"])


def problem_text(r: Reading) -> str:
    shown = f"{r.value:g}" if isinstance(r.value, (int, float)) else str(r.value)
    return f"{r.name}: {shown}{(' ' + r.unit) if r.unit else ''} ({'critical' if r.status == CRITICAL else 'warning'})"


# Examples an admin can start from (Monitoring › Sensors › Examples). From vendor MIB
# documentation: confirm each on a real device with the Test button.
EXAMPLES = [
    {"name": "UPS on battery", "group": "UPS (standard UPS-MIB, RFC 1628)", "platform": "snmp_ups", "oid": "1.3.6.1.2.1.33.1.4.1.0",
     "mode": "state", "ok_values": "3", "warn_values": "4",
     "help": "upsOutputSource: 3 = normal, 4 = bypass, 5 = on battery"},
    {"name": "UPS battery charge", "group": "UPS (standard UPS-MIB, RFC 1628)", "platform": "snmp_ups", "oid": "1.3.6.1.2.1.33.1.2.4.0",
     "mode": "value", "unit": "%", "warn_below": 80, "crit_below": 50,
     "help": "upsEstimatedChargeRemaining"},
    {"name": "UPS runtime", "group": "UPS (standard UPS-MIB, RFC 1628)", "platform": "snmp_ups", "oid": "1.3.6.1.2.1.33.1.2.3.0",
     "mode": "value", "unit": "min", "warn_below": 15, "crit_below": 5,
     "help": "upsEstimatedMinutesRemaining"},
    {"name": "APC UPS output status", "group": "APC / Schneider UPS (PowerNet-MIB)", "platform": "snmp_ups", "oid": "1.3.6.1.4.1.318.1.1.1.4.1.1.0",
     "mode": "state", "ok_values": "2", "warn_values": "12",
     "help": "upsBasicOutputStatus: 2 = on line, 3 = on battery, 12 = smart trim"},
    {"name": "APC UPS battery capacity", "group": "APC / Schneider UPS (PowerNet-MIB)", "platform": "snmp_ups", "oid": "1.3.6.1.4.1.318.1.1.1.2.2.1.0",
     "mode": "value", "unit": "%", "warn_below": 80, "crit_below": 50, "help": "upsAdvBatteryCapacity"},
    {"name": "APC UPS load", "group": "APC / Schneider UPS (PowerNet-MIB)", "platform": "snmp_ups", "oid": "1.3.6.1.4.1.318.1.1.1.4.2.3.0",
     "mode": "value", "unit": "%", "warn_above": 70, "crit_above": 90, "help": "upsAdvOutputLoad"},
    {"name": "APC UPS battery replace", "group": "APC / Schneider UPS (PowerNet-MIB)", "platform": "snmp_ups", "oid": "1.3.6.1.4.1.318.1.1.1.2.2.4.0",
     "mode": "state", "ok_values": "1", "help": "upsAdvBatteryReplaceIndicator: 1 = fine, 2 = replace the battery"},
    {"name": "BGP peer", "group": "Routing (standard BGP4-MIB)", "oid": "1.3.6.1.2.1.15.3.1.2",
     "mode": "state", "ok_values": "6", "table": True,
     "help": "bgpPeerState for every peer (named by its address): 6 = established. Only IPv4 peers in the default VRF"},
    {"name": "OSPF neighbour", "group": "Routing (standard OSPF-MIB)", "oid": "1.3.6.1.2.1.14.10.1.6",
     "mode": "state", "ok_values": "8", "warn_values": "4", "table": True,
     "help": "ospfNbrState for every neighbour: 8 = full, 4 = 2-way (normal between DROthers)"},
    {"name": "FortiGate sessions", "group": "Firewalls", "oid": "1.3.6.1.4.1.12356.101.4.1.8.0",
     "mode": "value", "unit": "sessions", "platform": "fortinet_fortios", "help": "fgSysSesCount"},
    {"name": "Palo Alto session use", "group": "Firewalls", "oid": "1.3.6.1.4.1.25461.2.1.2.3.1.0",
     "mode": "value", "unit": "%", "warn_above": 80, "crit_above": 95, "platform": "paloalto_panos",
     "help": "panSessionUtilization"},
    {"name": "ASA connections", "group": "Firewalls", "oid": "1.3.6.1.4.1.9.9.147.1.2.2.2.1.5.40.6",
     "mode": "value", "unit": "connections", "platform": "cisco_asa",
     "help": "cfwConnectionStatValue, current connections"},
    {"name": "IPsec tunnels", "group": "Firewalls", "oid": "1.3.6.1.4.1.9.9.171.1.3.1.1.0",
     "mode": "value", "unit": "tunnels", "warn_below": 1,
     "help": "cipSecGlobalActiveTunnels (Cisco IOS and ASA): warn when none are up"},
    {"name": "Interface errors in", "group": "Interfaces (IF-MIB)", "oid": "1.3.6.1.2.1.2.2.1.14.1",
     "mode": "rate", "unit": "/s", "warn_above": 1, "crit_above": 10,
     "help": "ifInErrors of interface index 1 (change the last number to the port's ifIndex)"},
    {"name": "Room temperature", "group": "Environment", "platform": "snmp_env", "oid": "1.3.6.1.4.1.318.1.1.10.2.3.2.1.4.1",
     "mode": "value", "unit": "°C", "warn_above": 27, "crit_above": 32,
     "help": "APC environmental probe 1 (iemStatusProbeCurrentTemp)"},
]
