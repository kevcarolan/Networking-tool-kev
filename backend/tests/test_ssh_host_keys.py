"""SSH host keys: recorded at the first connection, checked before any password is sent,
and forgotten only by an admin."""

import socket
import threading

import paramiko
import pytest

from app.core import ssh
from app.core.ssh import Target, classify_error, run_commands


class _Server(paramiko.ServerInterface):
    def __init__(self, seen):
        self.seen = seen

    def get_allowed_auths(self, username):
        return "password"

    def check_auth_password(self, username, password):
        self.seen.append(password)  # the device received the password
        return paramiko.AUTH_FAILED


@pytest.fixture
def device():
    """A pretend device: a real SSH key exchange, every login refused."""
    key = paramiko.Ed25519Key.generate() if hasattr(paramiko.Ed25519Key, "generate") else None
    key = key or paramiko.RSAKey.generate(2048)
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    state = {"key": key, "seen": [], "stop": False}

    def serve():
        while not state["stop"]:
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            t = paramiko.Transport(conn)
            t.add_server_key(state["key"])
            try:
                t.start_server(server=_Server(state["seen"]))
                t.accept(2)
            except Exception:  # noqa: BLE001, S110 - the client hung up
                pass
            finally:
                t.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    state["port"] = srv.getsockname()[1]
    yield state
    state["stop"] = True
    srv.close()


@pytest.fixture
def known(tmp_path, monkeypatch):
    monkeypatch.setattr(ssh, "_known_hosts", tmp_path / "known_hosts")
    return tmp_path / "known_hosts"


def _target():
    return Target(name="sw1", address="127.0.0.1", platform="cisco_ios", username="u",
                  password="the-password", enable_secret=None, ssh_timeout=5)


_fetch = ssh.fetch_host_key


def _from(device, monkeypatch):
    """Fetch keys from the pretend device's port, whatever address is asked for."""
    monkeypatch.setattr(ssh, "fetch_host_key",
                        lambda address, timeout: _fetch("127.0.0.1", timeout, device["port"]))


def test_the_first_connection_records_the_key(device, known, monkeypatch):
    _from(device, monkeypatch)
    ssh.trust_on_first_use("127.0.0.1", 5)
    assert ssh.host_key("127.0.0.1")["fingerprint"] == ssh.fingerprint(device["key"])
    assert oct(known.stat().st_mode & 0o777) == "0o600"


def test_a_different_key_is_refused_before_the_password_is_sent(device, known, monkeypatch):
    # The recorded key is not the device's: e.g. someone answering in its place.
    keys = paramiko.HostKeys()
    other = paramiko.RSAKey.generate(2048)
    keys.add(f"[127.0.0.1]:{device['port']}", other.get_name(), other)
    keys.save(str(known))
    client = paramiko.SSHClient()
    client.load_host_keys(str(known))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    with pytest.raises(paramiko.SSHException) as exc:
        client.connect("127.0.0.1", port=device["port"], username="u", password="the-password",
                       timeout=5, look_for_keys=False, allow_agent=False)
    assert device["seen"] == []  # no password reached it
    kind, message = classify_error(exc.value)
    assert kind == "setup" and "no password was sent" in message


def test_netmiko_uses_the_recorded_keys(known):
    params = ssh.strict_params()
    assert params == {"ssh_strict": True, "system_host_keys": False, "alt_host_keys": True,
                      "alt_key_file": str(known)}


def test_forgetting_a_key(device, known, monkeypatch):
    _from(device, monkeypatch)
    ssh.trust_on_first_use("127.0.0.1", 5)
    assert ssh.forget_host_key("127.0.0.1") and ssh.host_key("127.0.0.1") is None
    assert not ssh.forget_host_key("127.0.0.1")


def test_device_page_shows_and_admins_forget_the_key(admin, device, known, monkeypatch):
    d = admin.post("/api/devices", json={"name": "sw9", "address": "127.0.0.1",
                                         "platform": "cisco_ios"}).json()
    assert admin.get(f"/api/devices/{d['id']}/ssh-key").json()["key"] is None
    _from(device, monkeypatch)
    ssh.trust_on_first_use("127.0.0.1", 5)
    key = admin.get(f"/api/devices/{d['id']}/ssh-key").json()["key"]
    assert key["fingerprint"].startswith("SHA256:")
    assert admin.delete(f"/api/devices/{d['id']}/ssh-key").status_code == 204
    assert admin.get("/api/audit").json()[0]["action"] == "device.ssh_key_forget"
    assert admin.get(f"/api/devices/{d['id']}/ssh-key").json()["key"] is None


def test_address_and_account_changes_are_in_the_activity_log(admin, credential):
    d = admin.post("/api/devices", json={"name": "sw8", "address": "10.0.0.8",
                                         "platform": "cisco_ios"}).json()
    admin.put(f"/api/devices/{d['id']}", json={**d, "address": "10.0.0.9",
                                               "credential_id": credential["id"]})
    detail = admin.get("/api/audit").json()[0]["detail"]
    assert "address 10.0.0.8 -> 10.0.0.9" in detail and "credential - -> switch-ro" in detail


def test_run_commands_records_then_checks(known, monkeypatch):
    """run_commands: the key is recorded before Netmiko connects, and Netmiko then checks it."""
    calls = []
    monkeypatch.setattr(ssh, "trust_on_first_use", lambda a, t: calls.append(("tofu", a)))

    class FakeConn:
        def __init__(self, **params):
            calls.append(("connect", params.get("ssh_strict"), params.get("alt_key_file")))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def check_enable_mode(self):
            return True

        def send_command(self, cmd, read_timeout):
            return "ok"
    import netmiko
    monkeypatch.setattr(netmiko, "ConnectHandler", FakeConn)
    assert run_commands(_target(), ["show version"]) == ["ok"]
    assert calls == [("tofu", "127.0.0.1"), ("connect", True, str(known))]
