"""SSH access to devices (via Netmiko), shared by every tool: login, running
show commands, and turning connection errors into a type the GUI can show.

Host keys: the first time the server connects to a device it records the device's SSH
host key in <data>/known_hosts (trust on first use, like answering "yes" once in an SSH
client). From then on every connection checks it before any password is sent, so a
machine pretending to be the device gets nothing. When a device is really replaced, an
admin forgets the old key on the device's page and the next connection records the new one.
"""

import base64
import hashlib
import logging
import os
import socket
import threading
from dataclasses import dataclass
from pathlib import Path

from app.core.crypto import CredentialCipher
from app.core.models import Credential, Device
from app.core.platforms import PLATFORMS

# Error types shown in the GUI
AUTH, UNREACHABLE, TIMEOUT, COMMAND, SETUP, ERROR = (
    "auth", "unreachable", "timeout", "command", "setup", "error")


log = logging.getLogger(__name__)
_known_hosts: Path | None = None  # set at start (use_known_hosts); None = not checked (tests)
_lock = threading.Lock()


def use_known_hosts(path: Path) -> None:
    global _known_hosts
    _known_hosts = Path(path)


def _host_keys():
    import paramiko

    keys = paramiko.HostKeys()
    if _known_hosts is not None and _known_hosts.exists():
        keys.load(str(_known_hosts))
    return keys


def _save(keys) -> None:
    tmp = _known_hosts.with_name(_known_hosts.name + ".new")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.close(fd)
    keys.save(str(tmp))
    os.replace(tmp, _known_hosts)


def fingerprint(key) -> str:
    return "SHA256:" + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")


def fetch_host_key(address: str, timeout: float, port: int = 22):
    """The device's SSH host key, read without logging in."""
    import paramiko

    sock = socket.create_connection((address, port), timeout=timeout)
    transport = paramiko.Transport(sock)
    try:
        transport.start_client(timeout=timeout)
        return transport.get_remote_server_key()
    finally:
        transport.close()


def trust_on_first_use(address: str, timeout: float) -> None:
    """Record the device's host key if none is known yet (before any login)."""
    if _known_hosts is None:
        return
    with _lock:
        if _host_keys().lookup(address):
            return
    key = fetch_host_key(address, timeout)
    with _lock:
        keys = _host_keys()
        if not keys.lookup(address):
            keys.add(address, key.get_name(), key)
            _save(keys)
            log.warning("Recorded the SSH host key of %s (first connection): %s %s",
                        address, key.get_name(), fingerprint(key))


def host_key(address: str) -> dict | None:
    """The recorded key of an address: {'type', 'fingerprint'}, or None."""
    if _known_hosts is None:
        return None
    with _lock:
        entry = _host_keys().lookup(address)
    if not entry:
        return None
    kind = next(iter(entry.keys()))
    return {"type": kind, "fingerprint": fingerprint(entry[kind])}


def forget_host_key(address: str) -> bool:
    if _known_hosts is None:
        return False
    with _lock:
        keys = _host_keys()
        if address not in keys:
            return False
        del keys[address]
        _save(keys)
        return True


def strict_params() -> dict:
    """Netmiko settings that check the recorded host key (no key = no login)."""
    if _known_hosts is None:
        return {}
    return {"ssh_strict": True, "system_host_keys": False, "alt_host_keys": True,
            "alt_key_file": str(_known_hosts)}


class DeviceError(Exception):
    def __init__(self, error_type: str, message: str):
        super().__init__(message)
        self.error_type = error_type


@dataclass
class Target:
    name: str
    address: str
    platform: str
    username: str
    password: str
    enable_secret: str | None
    ssh_timeout: int = 30
    command_timeout: int = 180


def target_for(device: Device, cipher: CredentialCipher, ssh_timeout: int = 30,
               command_timeout: int = 180, credential: Credential | None = None) -> Target:
    """Build a Target from a device and its credential profile (or the given
    credential, e.g. the device's upgrade credential).

    Raises DeviceError(SETUP) when there is no usable credential."""
    cred = credential if credential is not None else device.credential
    if cred is None:
        raise DeviceError(SETUP, "No credential profile assigned to this device")
    try:
        password = cipher.decrypt(cred.password_enc)
        enable = cipher.decrypt(cred.enable_secret_enc) if cred.enable_secret_enc else None
    except Exception:  # noqa: BLE001 - e.g. credential key was replaced
        raise DeviceError(
            SETUP, "Stored credential could not be decrypted - re-enter the password") from None
    return Target(name=device.name, address=device.address, platform=device.platform,
                  username=cred.username, password=password, enable_secret=enable,
                  ssh_timeout=ssh_timeout, command_timeout=command_timeout)


def run_commands(target: Target, commands: tuple[str, ...] | list[str]) -> list[str]:
    """Log in (entering enable mode if the platform needs it) and return the
    output of each command, in order."""
    from netmiko import ConnectHandler

    platform = PLATFORMS.get(target.platform)
    if platform is None:
        raise DeviceError(SETUP, f"Unsupported platform '{target.platform}'")
    params = dict(
        device_type=platform.netmiko_type, host=target.address,
        username=target.username, password=target.password,
        secret=target.enable_secret or "",
        conn_timeout=target.ssh_timeout, auth_timeout=target.ssh_timeout,
        banner_timeout=target.ssh_timeout, fast_cli=False, **strict_params(),
    )
    trust_on_first_use(target.address, target.ssh_timeout)
    with ConnectHandler(**params) as conn:
        if platform.needs_enable and not conn.check_enable_mode():
            conn.enable()
        return [conn.send_command(cmd, read_timeout=target.command_timeout) for cmd in commands]


def classify_error(exc: Exception) -> tuple[str, str]:
    """Map an exception to (error_type, human-readable message)."""
    if isinstance(exc, DeviceError):
        return exc.error_type, str(exc)
    import paramiko

    if isinstance(exc, paramiko.BadHostKeyException) or (
            isinstance(exc, paramiko.SSHException) and "known_hosts" in str(exc)):
        return SETUP, ("The device's SSH host key is not the one recorded the first time: "
                       "no password was sent. If the device was replaced or reinstalled, an "
                       "admin forgets the old key on its page; otherwise investigate")
    from netmiko.exceptions import (NetmikoAuthenticationException,
                                    NetmikoTimeoutException, ReadTimeout)

    if isinstance(exc, NetmikoAuthenticationException):
        return AUTH, "Authentication failed - check the credential profile"
    if isinstance(exc, ReadTimeout):
        return TIMEOUT, "Timed out waiting for the device to respond"
    if isinstance(exc, NetmikoTimeoutException):
        return UNREACHABLE, "Could not connect over SSH (port 22) - device unreachable?"
    if isinstance(exc, socket.gaierror):
        return UNREACHABLE, f"Hostname could not be resolved: {exc}"
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return TIMEOUT, "Connection timed out"
    if isinstance(exc, (ConnectionRefusedError, ConnectionResetError, OSError)):
        return UNREACHABLE, f"Connection failed: {exc}"
    return ERROR, f"{type(exc).__name__}: {exc}"[:1000]
