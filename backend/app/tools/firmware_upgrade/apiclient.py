"""HTTPS to a device's management API with a pinned certificate (FDM, FortiGate, PAN-OS).

Devices use self-signed certificates, so instead of a CA we pin the SHA-256
fingerprint: an admin confirms it once in the device's upgrade settings, and every
connection is refused if it doesn't match. Standard library only.
"""

import hashlib
import socket
import ssl
import uuid
from http.client import HTTPSConnection
from pathlib import Path

from app.core.ssh import SETUP, UNREACHABLE, DeviceError


def _context() -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # trust comes from the pinned fingerprint instead
    return ctx


def fetch_fingerprint(address: str, port: int = 443, timeout: float = 10) -> str:
    """SHA-256 of the certificate the device presents, as colon-separated hex."""
    try:
        with socket.create_connection((address, port), timeout=timeout) as sock, \
                _context().wrap_socket(sock) as tls:
            der = tls.getpeercert(binary_form=True)
    except OSError as exc:
        raise DeviceError(UNREACHABLE, f"Could not connect to {address}:{port}: {exc}") from None
    return format_fp(hashlib.sha256(der).hexdigest())


def format_fp(hexdigest: str) -> str:
    h = hexdigest.replace(":", "").lower()
    return ":".join(h[i:i + 2] for i in range(0, len(h), 2)).upper()


def require_fingerprint(fingerprint: str, what: str) -> str:
    if not fingerprint:
        raise DeviceError(SETUP, f"The {what} certificate isn't trusted yet: an admin must "
                                 "confirm its fingerprint in the device's upgrade settings")
    return format_fp(fingerprint)


def pinned_connection(address: str, port: int, fingerprint: str, timeout: float,
                      what: str) -> HTTPSConnection:
    """An open HTTPS connection, refused unless the certificate matches the pin."""
    conn = HTTPSConnection(address, port, timeout=timeout, context=_context())
    try:
        conn.connect()
    except OSError as exc:
        raise DeviceError(UNREACHABLE, f"{what} API unreachable: {exc}") from None
    seen = format_fp(hashlib.sha256(conn.sock.getpeercert(binary_form=True)).hexdigest())
    if seen != fingerprint:
        conn.close()
        raise DeviceError(SETUP, f"{what} certificate changed (now {seen}); check the device "
                                 "and trust the new certificate in its upgrade settings")
    return conn


def multipart(field: str, local: Path) -> tuple[bytes, str]:
    """A multipart/form-data body with one file, and its content type. Images are up to
    about 1 GB and read in one go (the worker has the memory headroom)."""
    boundary = uuid.uuid4().hex
    head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; "
            f"filename=\"{local.name}\"\r\nContent-Type: application/octet-stream\r\n\r\n")
    raw = head.encode() + local.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    return raw, f"multipart/form-data; boundary={boundary}"
