"""A small client for the FortiGate REST API, used only to send the firmware image
(FortiOS can't receive a file over SSH). Everything else in a FortiGate upgrade runs
over SSH. The certificate is pinned (apiclient.py).

Login: with a REST API token when the upgrade account's credential has one in its
"enable secret" field (recommended: a REST API admin with a profile allowing firmware
upgrades), otherwise the account's username and password (session login).

The endpoint paths are in ENDPOINTS so they can be adjusted to the FortiOS version
(confirm them in the lab - see upgrade-lab-tests.md).
"""

import base64
import json
from pathlib import Path
from urllib.parse import urlencode

from app.core.ssh import AUTH, ERROR, UNREACHABLE, DeviceError
from app.tools.firmware_upgrade.apiclient import pinned_connection, require_fingerprint

ENDPOINTS = {
    "login": "/logincheck",
    "status": "/api/v2/monitor/system/status",
    "upgrade": "/api/v2/monitor/system/firmware/upgrade",
}


class FortiosClient:
    def __init__(self, address: str, username: str, password: str, fingerprint: str,
                 token: str = "", timeout: float = 600, port: int = 443):
        self.fingerprint = require_fingerprint(fingerprint, "FortiGate")
        self.address, self.username, self.password, self.token = address, username, password, token
        self.timeout, self.port = timeout, port
        self.cookies: dict[str, str] = {}

    def request(self, method: str, name: str, body=None, form: dict | None = None) -> tuple[int, str, list]:
        path = ENDPOINTS.get(name, name)
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.cookies:
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
            if "ccsrftoken" in self.cookies:
                headers["X-CSRFTOKEN"] = self.cookies["ccsrftoken"].strip('"')
        data = None
        if body is not None:
            data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
        elif form is not None:
            data = urlencode(form).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        conn = pinned_connection(self.address, self.port, self.fingerprint, self.timeout, "FortiGate")
        try:
            conn.request(method, path, body=data, headers=headers)
            resp = conn.getresponse()
            text = resp.read().decode("utf-8", "replace")
            cookies = resp.headers.get_all("Set-Cookie") or []
        except OSError as exc:
            raise DeviceError(UNREACHABLE, f"FortiGate API connection failed: {exc}") from None
        finally:
            conn.close()
        if resp.status in (401, 403):
            raise DeviceError(AUTH, "FortiGate API rejected the upgrade account")
        if resp.status >= 400:
            raise DeviceError(ERROR, f"FortiGate API {method} {path}: HTTP {resp.status} {text[:300]}")
        return resp.status, text, cookies

    def login(self) -> None:
        if not self.token:
            _, text, cookies = self.request("POST", "login", form={
                "username": self.username, "secretkey": self.password})
            for c in cookies:
                name, _, value = c.split(";")[0].partition("=")
                self.cookies[name.strip()] = value.strip()
            if not any(k.startswith("APSCOOKIE") or k == "ccsrftoken" for k in self.cookies):
                raise DeviceError(AUTH, "FortiGate API login failed (check the upgrade account)")
        self.status()  # proves the login works

    def status(self) -> dict:
        _, text, _ = self.request("GET", "status")
        return json.loads(text) if text.strip() else {}

    def upgrade(self, local: Path) -> dict:
        """Send the image; FortiOS checks it, installs it and reboots straight away."""
        content = base64.b64encode(local.read_bytes()).decode()
        _, text, _ = self.request("POST", "upgrade", body={"source": "upload",
                                                          "file_content": content})
        r = json.loads(text) if text.strip() else {}
        if r.get("status") not in (None, "success") or \
                (isinstance(r.get("results"), dict) and r["results"].get("status") == "error"):
            raise DeviceError(ERROR, f"FortiGate refused the image: {text[:300]}")
        return r
