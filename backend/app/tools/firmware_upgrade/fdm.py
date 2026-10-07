"""A small client for the FDM REST API (Firepower Threat Defense managed by FDM).

Standard library only. The certificate is pinned (apiclient.py).

The endpoint paths are in ENDPOINTS so they can be adjusted to the FDM API version
without touching the procedure (confirm them in the lab - see upgrade-lab-tests.md).
"""

import json
from http.client import HTTPSConnection
from pathlib import Path

from app.core.ssh import AUTH, ERROR, UNREACHABLE, DeviceError
from app.tools.firmware_upgrade.apiclient import (fetch_fingerprint, format_fp, multipart,
                                                  pinned_connection, require_fingerprint)

__all__ = ["ENDPOINTS", "FdmClient", "fetch_fingerprint", "format_fp"]

BASE = "/api/fdm/latest"
ENDPOINTS = {
    "token": "/fdm/token",
    "system": "/operational/systeminfo/default",
    "pending": "/operational/pendingchanges",
    "ha_status": "/devices/default/operational/ha/status/default",
    "ha_failover": "/devices/default/action/ha/failover",
    "upload": "/action/uploadupgrade",
    "upgrade_files": "/managedentity/upgradefiles",
    "readiness": "/action/upgradereadinesscheck",
    "upgrade": "/action/upgrade",
    "upgrade_status": "/managedentity/upgradestatus",
    "revert": "/action/revertupgrade",
}


class FdmClient:
    def __init__(self, address: str, username: str, password: str, fingerprint: str,
                 timeout: float = 60, port: int = 443):
        self.fingerprint = require_fingerprint(fingerprint, "FDM")
        self.address, self.username, self.password = address, username, password
        self.timeout, self.port = timeout, port
        self.token: str | None = None

    # --- transport ---------------------------------------------------------------

    def _connection(self) -> HTTPSConnection:
        return pinned_connection(self.address, self.port, self.fingerprint, self.timeout, "FDM")

    def request(self, method: str, name_or_path: str, body=None, raw: bytes | None = None,
                content_type: str = "application/json") -> dict:
        path = BASE + ENDPOINTS.get(name_or_path, name_or_path)
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        data = raw
        if body is not None:
            data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
        elif raw is not None:
            headers["Content-Type"] = content_type
        conn = self._connection()
        try:
            conn.request(method, path, body=data, headers=headers)
            resp = conn.getresponse()
            text = resp.read().decode("utf-8", "replace")
        except OSError as exc:
            raise DeviceError(UNREACHABLE, f"FDM API connection failed: {exc}") from None
        finally:
            conn.close()
        if resp.status in (401, 403):
            raise DeviceError(AUTH, "FDM API rejected the upgrade account")
        if resp.status >= 400:
            raise DeviceError(ERROR, f"FDM API {method} {path}: HTTP {resp.status} {text[:300]}")
        return json.loads(text) if text.strip() else {}

    def login(self) -> None:
        r = self.request("POST", "token", {"grant_type": "password", "username": self.username,
                                           "password": self.password})
        self.token = r.get("access_token")
        if not self.token:
            raise DeviceError(AUTH, "FDM API returned no access token")

    # --- read-only ---------------------------------------------------------------

    def system_info(self) -> dict:
        return self.request("GET", "system")

    def pending_changes(self) -> list:
        return self.request("GET", "pending").get("items", [])

    def ha_status(self) -> dict:
        return self.request("GET", "ha_status")

    def upgrade_files(self) -> list:
        return self.request("GET", "upgrade_files").get("items", [])

    def upgrade_status(self) -> dict:
        r = self.request("GET", "upgrade_status")
        items = r.get("items")
        return items[0] if items else r

    # --- changes -----------------------------------------------------------------

    def upload(self, local: Path) -> dict:
        raw, content_type = multipart("fileToUpload", local)
        return self.request("POST", "upload", raw=raw, content_type=content_type)

    def readiness_check(self, file_id: str) -> dict:
        return self.request("POST", "readiness", {"type": "upgradereadinesscheck",
                                                  "upgradeFile": {"id": file_id}})

    def start_upgrade(self, file_id: str) -> dict:
        return self.request("POST", "upgrade", {"type": "upgrade", "upgradeFile": {"id": file_id}})

    def ha_failover(self) -> dict:
        return self.request("POST", "ha_failover", {})

    def revert(self) -> dict:
        return self.request("POST", "revert", {})
