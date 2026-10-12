"""Which inventory device a syslog sender is: by the address it sends from.

A device entered with a host name is looked up in DNS (kept for 10 minutes). A device
that sends from another address than the one in the inventory (for example a loopback
or another interface) shows as an unknown sender: set its logging source interface to
the management address (docs/syslog.md).
"""

import ipaddress
import socket
import threading
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

_CACHE: dict[str, tuple[float, list[str]]] = {}
_LOCK = threading.Lock()
_TTL = 600


def normalise(address: str) -> str:
    """'::ffff:10.0.0.1' -> '10.0.0.1'; other text unchanged."""
    try:
        ip = ipaddress.ip_address(address.split("%")[0])
    except ValueError:
        return address
    if ip.version == 6 and ip.ipv4_mapped:
        return str(ip.ipv4_mapped)
    return str(ip)


def _resolve(name: str) -> list[str]:
    try:
        return [normalise(str(ipaddress.ip_address(name)))]
    except ValueError:
        pass
    now = time.monotonic()
    with _LOCK:
        hit = _CACHE.get(name)
        if hit and now - hit[0] < _TTL:
            return hit[1]
    try:
        found = sorted({normalise(a[4][0]) for a in socket.getaddrinfo(name, None)})
    except (OSError, UnicodeError):
        found = []
    with _LOCK:
        _CACHE[name] = (now, found)
    return found


def device_addresses(db: Session) -> dict[str, tuple[int, str]]:
    """Sender address -> (device id, device name), for every inventory device."""
    from app.core.models import Device

    out: dict[str, tuple[int, str]] = {}
    for dev_id, name, address in db.execute(select(Device.id, Device.name, Device.address)):
        for ip in _resolve(address.strip()):
            out.setdefault(ip, (dev_id, name))
    return out
