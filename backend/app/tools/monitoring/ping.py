"""Ping (ICMP echo) without root: Linux "ping sockets" (SOCK_DGRAM, IPPROTO_ICMP).

Ubuntu allows them for every group (``net.ipv4.ping_group_range = 0 2147483647``, set by
systemd), so the poller needs no extra rights. If a server forbids them, ``PingNotAllowed``
is raised and the poller carries on with SNMP alone, saying so on the page.
"""

import asyncio
import os
import socket
import struct
import time
from dataclasses import dataclass


class PingNotAllowed(Exception):
    pass


@dataclass
class PingResult:
    sent: int
    received: int
    rtt_ms: float | None  # average of the replies, None when none came back

    @property
    def ok(self) -> bool:
        return self.received > 0

    @property
    def loss(self) -> float:
        return 1 - self.received / self.sent if self.sent else 1.0


def _checksum(data: bytes) -> int:
    if len(data) % 2:
        data += b"\0"
    s = sum(struct.unpack(f"!{len(data) // 2}H", data))
    s = (s >> 16) + (s & 0xFFFF)
    s += s >> 16
    return ~s & 0xFFFF


def _packet(v6: bool, seq: int, token: bytes) -> bytes:
    kind = 128 if v6 else 8
    head = struct.pack("!BBHHH", kind, 0, 0, 0, seq)
    return struct.pack("!BBHHH", kind, 0, 0 if v6 else _checksum(head + token), 0, seq) + token


async def ping(address: str, count: int = 3, timeout: float = 1.0) -> PingResult:
    """Send ``count`` echo requests one after the other; wait up to ``timeout`` for each."""
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(address, None, type=socket.SOCK_DGRAM)
    family, _, _, _, sockaddr = infos[0]
    v6 = family == socket.AF_INET6
    try:
        sock = socket.socket(family, socket.SOCK_DGRAM,
                             socket.IPPROTO_ICMPV6 if v6 else socket.IPPROTO_ICMP)
    except PermissionError as exc:
        raise PingNotAllowed("This server doesn't allow ping without root "
                             "(net.ipv4.ping_group_range)") from exc
    sock.setblocking(False)
    token = os.urandom(8)
    rtts = []
    try:
        for seq in range(1, count + 1):
            start = time.monotonic()
            try:
                await loop.sock_sendto(sock, _packet(v6, seq, token), sockaddr)
            except OSError:
                continue  # no route: counts as lost
            deadline = start + timeout
            while (left := deadline - time.monotonic()) > 0:
                try:
                    data = await asyncio.wait_for(loop.sock_recv(sock, 2048), left)
                except (TimeoutError, OSError):
                    break
                if len(data) >= 8 and data[0] == (129 if v6 else 0) and \
                        struct.unpack("!H", data[6:8])[0] == seq and data[8:16] == token:
                    rtts.append((time.monotonic() - start) * 1000)
                    break
    finally:
        sock.close()
    return PingResult(count, len(rtts), round(sum(rtts) / len(rtts), 2) if rtts else None)
