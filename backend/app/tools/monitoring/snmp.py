"""Reading values from devices over SNMP (v2c and v3), with pysnmp.

Read-only: the poller only ever sends GET and GETBULK requests. Nothing here can change a
device (no SET), and nothing listens for traps.

``SnmpClient`` is the real thing. The poller, the tests and the demo can pass any object
with the same two methods (``get`` and ``walk``), so tests never send a packet.
"""

import asyncio
import ipaddress
import re
from dataclasses import dataclass, field

# System group (SNMPv2-MIB): every SNMP device answers these.
SYS_DESCR = "1.3.6.1.2.1.1.1.0"
SYS_OBJECT_ID = "1.3.6.1.2.1.1.2.0"
SYS_UPTIME = "1.3.6.1.2.1.1.3.0"  # hundredths of a second since the SNMP agent started
SYS_NAME = "1.3.6.1.2.1.1.5.0"
SYSTEM = [SYS_DESCR, SYS_OBJECT_ID, SYS_UPTIME, SYS_NAME]

# AES-192/256 come in two kinds: net-snmp's names, "-C" for Cisco's (Reeder key extension).
AUTH_PROTOCOLS = ("SHA", "SHA-224", "SHA-256", "SHA-384", "SHA-512", "MD5")
PRIV_PROTOCOLS = ("AES", "AES-192", "AES-256", "AES-192-C", "AES-256-C", "DES", "3DES")


class SnmpError(Exception):
    """A request that got no usable answer; the message is for people."""


@dataclass(frozen=True)
class SnmpTarget:
    address: str
    port: int = 161
    version: str = "2c"  # "2c" or "3"
    community: str = field(default="", repr=False)
    username: str = ""
    level: str = "authPriv"  # v3: authPriv, authNoPriv or noAuthNoPriv
    auth_protocol: str = "SHA"
    auth_key: str = field(default="", repr=False)
    priv_protocol: str = "AES"
    priv_key: str = field(default="", repr=False)
    timeout: int = 2
    retries: int = 1


def value(v):
    """A pysnmp value as plain Python: numbers as int, text as str, missing as None."""
    name = type(v).__name__
    if name in ("NoSuchObject", "NoSuchInstance", "EndOfMibView", "Null"):
        return None
    if name in ("Integer", "Integer32", "Unsigned32", "Counter32", "Counter64", "Gauge32",
                "TimeTicks"):
        return int(v)
    if name == "ObjectIdentifier" or name == "ObjectName":
        return str(v)
    if name == "IpAddress":
        return str(ipaddress.IPv4Address(bytes(v)))
    raw = bytes(v) if hasattr(v, "asOctets") else str(v).encode()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.hex(":")  # e.g. a MAC address
    return text if text.isprintable() or "\n" in text or "\r" in text else raw.hex(":")


_FRIENDLY = [
    (r"timed? ?out|No SNMP response", "No answer (timed out): check the device's SNMP settings "
     "(the community or user), its access list, and that UDP 161 is open from this server"),
    (r"Unknown USM user|unknownUserName", "The device doesn't know this SNMPv3 user"),
    (r"Wrong SNMP PDU digest|wrongDigest", "Wrong SNMPv3 authentication password or protocol"),
    (r"[Dd]ecryption error|decryptionError", "Wrong SNMPv3 encryption password or protocol"),
    (r"[Uu]nsupported security level|unsupportedSecLevel",
     "The device doesn't allow this security level for the user"),
    (r"[Nn]ot in time window", "The device's SNMPv3 clock didn't match: it will be tried again"),
    (r"authorizationError|noAccess", "The device refused: this user or community may not read "
     "these values (an SNMP view or access list)"),
]


def friendly(text: str) -> str:
    for pattern, message in _FRIENDLY:
        if re.search(pattern, text):
            return message
    return text[:200]


class SnmpClient:
    """SNMP requests with pysnmp. One client (one SNMP engine) per event loop."""

    MAX_ROWS = 20000  # a walk stops here, whatever the device sends

    def __init__(self):
        self._engine = None

    def _auth(self, t: SnmpTarget):
        from pysnmp.hlapi.v3arch import asyncio as h

        if t.version != "3":
            return h.CommunityData(t.community, mpModel=1)  # v2c
        auth = {"SHA": h.usmHMACSHAAuthProtocol, "SHA-224": h.usmHMAC128SHA224AuthProtocol,
                "SHA-256": h.usmHMAC192SHA256AuthProtocol,
                "SHA-384": h.usmHMAC256SHA384AuthProtocol,
                "SHA-512": h.usmHMAC384SHA512AuthProtocol, "MD5": h.usmHMACMD5AuthProtocol}
        priv = {"AES": h.usmAesCfb128Protocol, "AES-192": h.usmAesBlumenthalCfb192Protocol,
                "AES-256": h.usmAesBlumenthalCfb256Protocol, "AES-192-C": h.usmAesCfb192Protocol,
                "AES-256-C": h.usmAesCfb256Protocol, "DES": h.usmDESPrivProtocol,
                "3DES": h.usm3DESEDEPrivProtocol}
        if t.level == "noAuthNoPriv":
            return h.UsmUserData(t.username)
        if t.level == "authNoPriv":
            return h.UsmUserData(t.username, t.auth_key, authProtocol=auth[t.auth_protocol])
        return h.UsmUserData(t.username, t.auth_key, t.priv_key,
                             authProtocol=auth[t.auth_protocol], privProtocol=priv[t.priv_protocol])

    async def _transport(self, t: SnmpTarget):
        from pysnmp.hlapi.v3arch import asyncio as h

        try:
            ip = ipaddress.ip_address(t.address)
        except ValueError:
            ip = None  # a host name: pysnmp looks it up
        kind = h.Udp6TransportTarget if ip is not None and ip.version == 6 else h.UdpTransportTarget
        return await kind.create((t.address, t.port), timeout=t.timeout, retries=t.retries)

    def _get_engine(self):
        from pysnmp.hlapi.v3arch import asyncio as h

        if self._engine is None:
            self._engine = h.SnmpEngine()
        return self._engine

    async def get(self, t: SnmpTarget, oids: list[str]) -> dict[str, object]:
        """The values of these OIDs (None for any the device doesn't have)."""
        from pysnmp.hlapi.v3arch import asyncio as h

        try:
            transport = await self._transport(t)
            err, status, index, binds = await h.get_cmd(
                self._get_engine(), self._auth(t), transport, h.ContextData(),
                *[h.ObjectType(h.ObjectIdentity(o)) for o in oids])
        except SnmpError:
            raise
        except Exception as exc:  # noqa: BLE001 - name lookup, bad key length...
            raise SnmpError(friendly(f"{type(exc).__name__}: {exc}")) from None
        if err:
            raise SnmpError(friendly(str(err)))
        if status:
            raise SnmpError(friendly(status.prettyPrint()))
        return {str(o): value(v) for o, v in binds}

    async def walk(self, t: SnmpTarget, oid: str, max_rows: int = MAX_ROWS) -> list[tuple[str, object]]:
        """Every value under ``oid`` (GETBULK), in order."""
        from pysnmp.hlapi.v3arch import asyncio as h

        rows: list[tuple[str, object]] = []
        try:
            transport = await self._transport(t)
            async for err, status, index, binds in h.bulk_walk_cmd(
                    self._get_engine(), self._auth(t), transport, h.ContextData(), 0, 25,
                    h.ObjectType(h.ObjectIdentity(oid)), lexicographicMode=False):
                if err:
                    raise SnmpError(friendly(str(err)))
                if status:
                    raise SnmpError(friendly(status.prettyPrint()))
                for o, v in binds:
                    rows.append((str(o), value(v)))
                if len(rows) >= max_rows:
                    break
        except SnmpError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise SnmpError(friendly(f"{type(exc).__name__}: {exc}")) from None
        return rows


def read_system(t: SnmpTarget, client=None) -> dict[str, object]:
    """One read of the system values, for the "Test" button (runs its own event loop)."""
    client = client or SnmpClient()

    async def run():
        return await client.get(t, SYSTEM)

    return asyncio.run(run())
