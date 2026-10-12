"""deploy/netops-tls-apply.sh: the root script that installs a certificate saved by the
setup screen. Run with stand-ins for nginx, systemctl and logger."""

import datetime
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "netops-tls-apply.sh"
pytestmark = pytest.mark.skipif(not shutil.which("openssl") or not shutil.which("bash"),
                                reason="needs bash and openssl")


def _pair(days=30):
    key = ec.generate_private_key(ec.SECP256R1())
    now = datetime.datetime.now(datetime.timezone.utc)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "netops.corp.local")])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(1)
            .not_valid_before(now - datetime.timedelta(days=2))
            .not_valid_after(now + datetime.timedelta(days=days)).sign(key, hashes.SHA256()))
    return (cert.public_bytes(serialization.Encoding.PEM),
            key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                              serialization.NoEncryption()))


def _run(tmp_path, nginx_ok=True):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, body in (("nginx", "exit 0" if nginx_ok else "exit 1"),
                       ("systemctl", f'echo "$@" >> {tmp_path}/systemctl.log'), ("logger", "true")):
        (bin_dir / name).write_text(f"#!/bin/sh\n{body}\n")
        (bin_dir / name).chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}",
           "NETOPS_TLS_SRC": str(tmp_path / "src"), "NETOPS_TLS_DST": str(tmp_path / "dst"),
           "NETOPS_TLS_STATUS_DIR": str(tmp_path / "status")}
    return subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)


def _propose(tmp_path, cert, key):
    src = tmp_path / "src"
    src.mkdir(exist_ok=True)
    (src / "netops.crt").write_bytes(cert)
    (src / "netops.key").write_bytes(key)


def test_good_certificate_is_installed_and_nginx_reloaded(tmp_path):
    cert, key = _pair()
    _propose(tmp_path, cert, key)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp_path / "dst" / "netops.crt").read_bytes() == cert
    assert oct((tmp_path / "dst" / "netops.key").stat().st_mode & 0o777) == "0o600"
    assert "reload nginx" in (tmp_path / "systemctl.log").read_text()
    assert "applied: CN" in (tmp_path / "status" / "apply-status").read_text()


def test_mismatched_or_expired_certificates_are_refused(tmp_path):
    cert, _ = _pair()
    _, other_key = _pair()
    _propose(tmp_path, cert, other_key)
    assert _run(tmp_path).returncode == 1
    assert "doesn't belong" in (tmp_path / "status" / "apply-status").read_text()
    assert not (tmp_path / "dst" / "netops.crt").exists()
    cert, key = _pair(days=-1)
    _propose(tmp_path, cert, key)
    assert _run(tmp_path).returncode == 1
    assert "expired" in (tmp_path / "status" / "apply-status").read_text()


def test_nginx_failure_puts_the_old_certificate_back(tmp_path):
    old_cert, old_key = _pair()
    _propose(tmp_path, old_cert, old_key)
    assert _run(tmp_path).returncode == 0
    new_cert, new_key = _pair()
    _propose(tmp_path, new_cert, new_key)
    assert _run(tmp_path, nginx_ok=False).returncode == 1
    assert (tmp_path / "dst" / "netops.crt").read_bytes() == old_cert
    assert "previous one is still in use" in (tmp_path / "status" / "apply-status").read_text()


def test_symlinks_are_refused(tmp_path):
    cert, key = _pair()
    _propose(tmp_path, cert, key)
    (tmp_path / "secret").write_bytes(key)
    (tmp_path / "src" / "netops.key").unlink()
    (tmp_path / "src" / "netops.key").symlink_to(tmp_path / "secret")
    assert _run(tmp_path).returncode == 1
    assert "not a plain file" in (tmp_path / "status" / "apply-status").read_text()


def test_the_status_never_goes_into_the_service_accounts_folder(tmp_path):
    cert, key = _pair()
    _propose(tmp_path, cert, key)
    assert _run(tmp_path).returncode == 0
    assert sorted(p.name for p in (tmp_path / "src").iterdir()) == ["netops.crt", "netops.key"]


def test_a_pipe_or_a_linked_folder_is_refused(tmp_path):
    cert, key = _pair()
    _propose(tmp_path, cert, key)
    (tmp_path / "src" / "netops.key").unlink()
    os.mkfifo(tmp_path / "src" / "netops.key")  # would make a plain read wait for ever
    r = _run(tmp_path)
    assert r.returncode == 1 and not (tmp_path / "dst").exists()
    (tmp_path / "real").mkdir()
    shutil.rmtree(tmp_path / "src")
    (tmp_path / "src").symlink_to(tmp_path / "real")
    assert _run(tmp_path).returncode == 1
    assert "is not a folder" in (tmp_path / "status" / "apply-status").read_text()
