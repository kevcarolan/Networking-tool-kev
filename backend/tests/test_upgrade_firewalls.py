"""Firewall upgrades (multi-vendor PR C): FortiGate and PAN-OS, standalone and HA, end to
end against the simulator (tests/fake_network.py + tests/fake_vendors.py)."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.tools.firmware_upgrade.drivers.fortinet_fortios import flash_partitions, ha_status
from app.tools.firmware_upgrade.drivers.paloalto_panos import base_release, ha_pair, pair_healthy
from app.tools.firmware_upgrade.panos import op_xml
from tests.conftest import ADMIN_PASSWORD, FakeFetcher
from tests.fake_network import FP, FakeNetwork, SimDevice
from tests.test_upgrade_engine import Lab, _check, _msgs


@pytest.fixture
def lab(settings):
    settings.upgrade_live_platforms = "fortinet_fortios,paloalto_panos"
    net = FakeNetwork()
    app = create_app(settings, fetcher=FakeFetcher(), start_scheduler=False,
                     fw_collector=net.show, upgrade_io=net)
    with TestClient(app) as client:
        assert client.post("/api/auth/login", json={"username": "admin",
                                                    "password": ADMIN_PASSWORD}).status_code == 200
        yield Lab(client, app, net, settings)


def _fgt(lab, name="fgt1", role="", address="10.8.0.1", trusted=True):
    sim = SimDevice(name, "fortinet_fortios", "7.2.5", "")
    sim.role = role
    dev = lab.device(sim, address, fdm_fingerprint=FP if trusted else "")
    return sim, dev


def _pa(lab, name, address, role="", base=True):
    sim = SimDevice(name, "paloalto_panos", "10.2.7-h3", "")
    sim.role = role
    if base:
        sim.software["10.2.0"] = True
    return sim, lab.device(sim, address, fdm_fingerprint=FP)


# --- FortiGate ------------------------------------------------------------------------------

def test_fortigate_standalone_upgrade_and_rollback(lab):
    sim, dev = _fgt(lab)
    img = lab.image("FGT_60F-v7.4.4.F-build2662-FORTINET.out", "fortinet_fortios", "7.4.4")
    job = lab.job(dev, img)
    j = lab.act(job, "precheck")
    assert j["status"] == "ready", [c for c in j["checks"]["pre"] if c["status"] in ("fail", "error")]
    assert "primary" in _check(j, "pre", "previous_image")["value"]
    j = lab.act(job, "start")
    assert j["status"] == "completed", _msgs(j)
    assert sim.version == "7.4.4" and sim.selected == "2" and sim.reloads == 1
    assert ("fgt1", "api:upgrade FGT_60F-v7.4.4.F-build2662-FORTINET.out") in lab.net.log
    assert "FortiGate API on fgt1: send" in _msgs(j)

    # a second firewall: the new version fails its post-check, roll back to the old partition
    sim2, dev2 = _fgt(lab, "fgt2", address="10.8.0.2")
    lab.net.versions["FGT_60F-v7.4.4.F-build2662-FORTINET.out"] = "7.4.3"
    job2 = lab.job(dev2, img)
    lab.act(job2, "precheck")
    j2 = lab.act(job2, "start")
    assert j2["status"] == "failed" and sim2.version == "7.4.3"
    j2 = lab.act(job2, "rollback")
    assert j2["status"] == "rolled_back", _msgs(j2)
    assert sim2.version == "7.2.5" and ("fgt2", "execute set-next-reboot primary") in lab.net.log


def test_fortigate_needs_a_trusted_certificate_and_refuses_ha_on_standalone_path(lab):
    sim, dev = _fgt(lab, trusted=False)
    img = lab.image("FGT_60F-v7.4.4.F-build2662-FORTINET.out", "fortinet_fortios", "7.4.4")
    j = lab.act(lab.job(dev, img), "precheck")
    assert j["status"] == "blocked" and _check(j, "pre", "api")["status"] == "fail"
    sim2, dev2 = _fgt(lab, "fgt-ha", role="primary", address="10.8.0.3")
    j = lab.act(lab.job(dev2, img, path="standalone"), "precheck")
    assert _check(j, "pre", "standalone")["status"] == "fail"


def test_fortigate_ha_cluster_upgrades_itself(lab):
    sim, dev = _fgt(lab, "fgt-ha", role="primary")
    img = lab.image("FGT_60F-v7.4.4.F-build2662-FORTINET.out", "fortinet_fortios", "7.4.4")
    job = lab.job(dev, img, path="ha_cluster")
    j = lab.act(job, "precheck")
    assert j["status"] == "ready", [c for c in j["checks"]["pre"] if c["status"] == "fail"]
    j = lab.act(job, "start")
    assert j["status"] == "completed", _msgs(j)
    assert sim.version == "7.4.4" and sim.reloads == 0  # the cluster address stayed up
    # a cluster can't be rolled back by the job
    sim.uninterruptible = False
    assert _check(lab.act(lab.job(dev, img, path="ha_cluster"), "precheck"), "pre",
                  "uninterruptible_upgrade")["status"] == "fail"


def test_fortigate_rejected_image_stops_before_anything_changes(lab):
    sim, dev = _fgt(lab)
    sim.fail.add("image_rejected")
    img = lab.image("FGT_60F-v7.4.4.F-build2662-FORTINET.out", "fortinet_fortios", "7.4.4")
    job = lab.job(dev, img)
    lab.act(job, "precheck")
    j = lab.act(job, "start")
    assert j["status"] in ("failed", "needs_attention") and sim.reloads == 0
    assert "refused the image" in _msgs(j)


def test_fortigate_dry_run(lab):
    sim, dev = _fgt(lab)
    img = lab.image("FGT_60F-v7.4.4.F-build2662-FORTINET.out", "fortinet_fortios", "7.4.4")
    job = lab.job(dev, img, live=False, window=False)
    lab.act(job, "precheck")
    j = lab.act(job, "start")
    assert j["status"] == "completed" and lab.net.log == [] and sim.reloads == 0
    assert "DRY RUN - would send" in _msgs(j)


# --- PAN-OS ------------------------------------------------------------------------------------

def test_panos_standalone_upgrade_and_rollback(lab):
    sim, dev = _pa(lab, "pa1", "10.8.1.1")
    img = lab.image("PanOS_3400-10.2.8", "paloalto_panos", "10.2.8")
    job = lab.job(dev, img)
    j = lab.act(job, "precheck")
    assert j["status"] == "ready", [c for c in j["checks"]["pre"] if c["status"] in ("fail", "error")]
    j = lab.act(job, "start")
    assert j["status"] == "completed", _msgs(j)
    assert sim.version == "10.2.8"
    assert [c for _, c in lab.net.log] == ["api:upload PanOS_3400-10.2.8", "api:install 10.2.8",
                                           "api:restart"]

    sim2, dev2 = _pa(lab, "pa2", "10.8.1.2")
    sim2.fail.add("stays_old")  # restarts but comes back on the old version
    job2 = lab.job(dev2, img)
    lab.act(job2, "precheck")
    j2 = lab.act(job2, "start")
    assert j2["status"] == "failed" and _check(j2, "post", "post_version")["status"] == "fail"
    sim2.fail.clear()
    j2 = lab.act(job2, "rollback")
    assert j2["status"] == "rolled_back", _msgs(j2)
    assert sim2.version == "10.2.7-h3" and ("pa2", "api:install 10.2.7-h3") in lab.net.log


def test_panos_base_release_missing_blocks(lab):
    sim, dev = _pa(lab, "pa1", "10.8.1.1", base=False)
    sim.version = "10.1.9"
    sim.software = {"10.1.9": True}
    img = lab.image("PanOS_3400-10.2.8", "paloalto_panos", "10.2.8")
    j = lab.act(lab.job(dev, img), "precheck")
    assert j["status"] == "blocked"
    assert _check(j, "pre", "base_release")["value"] == "10.2.0 missing"


def test_panos_install_failure_stops_before_the_restart(lab):
    sim, dev = _pa(lab, "pa1", "10.8.1.1")
    sim.fail.add("install")
    img = lab.image("PanOS_3400-10.2.8", "paloalto_panos", "10.2.8")
    job = lab.job(dev, img)
    lab.act(job, "precheck")
    j = lab.act(job, "start")
    assert j["status"] == "failed" and sim.reloads == 0
    assert "Failed to install 10.2.8" in _msgs(j)


def test_panos_ha_pair_passive_first(lab):
    act, dev_a = _pa(lab, "pa-a", "10.8.2.1", "active")
    pas, dev_p = _pa(lab, "pa-b", "10.8.2.2", "passive")
    act.peer, pas.peer = pas, act
    r = lab.c.put(f"/api/firmware/devices/{dev_a['id']}/settings",
                  json={"upgrade_credential_id": lab.up["id"], "peer_device_id": dev_p["id"],
                        "default_path": "ha_pair", "fdm_fingerprint": FP})
    assert r.status_code == 200, r.text
    img = lab.image("PanOS_3400-10.2.8", "paloalto_panos", "10.2.8")
    job = lab.job(dev_a, img)
    assert job["path"] == "ha_pair"
    j = lab.act(job, "precheck")
    assert j["status"] == "ready", [c for c in j["checks"]["pre"] if c["status"] == "fail"]
    j = lab.act(job, "start")
    assert j["status"] == "completed", _msgs(j)
    restarts = [d for d, c in lab.net.log if c == "api:restart"]
    assert restarts == ["pa-b", "pa-a"]
    assert act.version == pas.version == "10.2.8"
    # suspending the active unit failed the pair over to the upgraded one
    assert pas.role == "active" and act.role == "passive"
    assert not act.suspended and not pas.suspended


# --- parsers ----------------------------------------------------------------------------

def test_firewall_parsers():
    assert flash_partitions(
        "Partition  Image  TotalSize(KB)  Used(KB)  Use%  Active\n"
        "1          FGT60F-7.02-FW-build1517-230606       253920    164104   65%  Yes\n"
        "2          FGT60F-7.00-FW-build0444-220519       253920    163968   65%  No\n"
        "3          ETDB-1.00000                          3021708    326528   11%  No\n") == {
        "1": ("FGT60F-7.02-FW-build1517-230606", True), "2": ("FGT60F-7.00-FW-build0444-220519", False)}
    assert ha_status("HA Health Status: OK\nMode: HA A-P\n") == {"mode": "HA A-P", "health": "OK"}
    assert base_release("10.2.8-h3") == "10.2.0" and base_release("") == ""
    h = ha_pair("  Local Information:\n    State: passive (last 1 days)\n"
                "  Peer Information:\n    Connection status: up\n    State: active (last 1 days)\n")
    assert pair_healthy(h) and h["local"] == "passive"
    assert not pair_healthy({**h, "connection": "down"})
    assert op_xml("request", "system", "software", "install", "version", value="10.2.8") == \
        "<request><system><software><install><version>10.2.8</version></install></software>" \
        "</system></request>"


# --- the real API clients against a local HTTPS server -----------------------------------------

@pytest.fixture
def https_device(tmp_path):
    """A local HTTPS server answering like a FortiGate and a PAN-OS firewall."""
    import datetime
    import ssl
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import parse_qs, urlparse

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    from app.tools.firmware_upgrade.apiclient import format_fp

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "fw.lab")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(1)
            .not_valid_before(now).not_valid_after(now + datetime.timedelta(days=1))
            .sign(key, hashes.SHA256()))
    (tmp_path / "c.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (tmp_path / "k.pem").write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _reply(self, body: str, ctype="application/json", cookies=()):
            data = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            for c in cookies:
                self.send_header("Set-Cookie", c)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            seen.append(("GET", self.path, dict(self.headers), b""))
            self._reply('{"version": "v7.2.5", "build": 1517}')

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            seen.append(("POST", self.path, dict(self.headers), body))
            path = urlparse(self.path)
            if path.path == "/logincheck":
                self._reply("1", "text/plain", ["APSCOOKIE_123=abc; path=/", 'ccsrftoken="tok"; path=/'])
            elif path.path.startswith("/api/v2/monitor/system/firmware/upgrade"):
                self._reply('{"status": "success"}')
            elif path.path == "/api//" or path.path == "/api/":
                params = parse_qs(body.decode()) if b"=" in body[:50] else parse_qs(path.query)
                if params.get("type") == ["keygen"]:
                    self._reply('<response status="success"><result><key>K1</key></result></response>',
                                "application/xml")
                elif params.get("type") == ["import"]:
                    self._reply('<response status="success"><msg>uploaded</msg></response>',
                                "application/xml")
                elif "<install>" in (params.get("cmd") or [""])[0]:
                    self._reply('<response status="success"><result><job>7</job></result></response>',
                                "application/xml")
                else:
                    self._reply('<response status="success"><result><sw-updates><versions>'
                                '<entry><version>10.2.8</version><downloaded>yes</downloaded>'
                                '<current>no</current></entry></versions></sw-updates></result>'
                                '</response>', "application/xml")
            else:
                self.send_response(404)
                self.end_headers()

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(tmp_path / "c.pem", tmp_path / "k.pem")
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1], format_fp(cert.fingerprint(hashes.SHA256()).hex()), seen
    httpd.shutdown()


def test_fortios_client_session_login_token_and_upload(https_device, tmp_path):
    from app.core.ssh import DeviceError
    from app.tools.firmware_upgrade.fortios import FortiosClient

    port, fp, seen = https_device
    image = tmp_path / "FGT.out"
    image.write_bytes(b"firmware")
    c = FortiosClient("127.0.0.1", "admin", "pw", fp, port=port)
    c.login()
    assert seen[0][1] == "/logincheck" and b"secretkey=pw" in seen[0][3]
    assert c.status()["version"] == "v7.2.5"
    assert seen[-1][2]["X-CSRFTOKEN"] == "tok"
    c.upgrade(image)
    assert b'"source": "upload"' in seen[-1][3] and b"ZmlybXdhcmU=" in seen[-1][3]  # base64

    t = FortiosClient("127.0.0.1", "", "", fp, token="T0KEN", port=port)
    t.login()
    assert seen[-1][2]["Authorization"] == "Bearer T0KEN"
    with pytest.raises(DeviceError, match="certificate changed"):
        FortiosClient("127.0.0.1", "admin", "pw", "00" * 32, port=port).login()


def test_panos_client_keygen_upload_install(https_device, tmp_path):
    from app.tools.firmware_upgrade.panos import PanosClient

    port, fp, seen = https_device
    image = tmp_path / "PanOS_3400-10.2.8"
    image.write_bytes(b"software")
    c = PanosClient("127.0.0.1", "admin", "pw", fp, port=port)
    c.login()
    assert c.key == "K1" and b"password=pw" in seen[0][3] and "pw" not in seen[0][1]
    assert c.software_info() == [{"version": "10.2.8", "downloaded": True, "current": False}]
    assert seen[-1][2]["X-PAN-KEY"] == "K1"
    c.upload(image)
    assert "type=import" in seen[-1][1] and b"software" in seen[-1][3]
    assert c.install("10.2.8") == "7"
