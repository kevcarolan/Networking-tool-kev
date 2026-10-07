"""A small client for the PAN-OS XML API: send the software image, install it, follow
the install job, restart, and the HA state changes. The certificate is pinned
(apiclient.py). The upgrade account's username and password get an API key at login.

Commands are the same XML as the CLI ('request system software install version ...').
"""

import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlencode

from app.core.ssh import AUTH, ERROR, UNREACHABLE, DeviceError
from app.tools.firmware_upgrade.apiclient import multipart, pinned_connection, require_fingerprint


def op_xml(*path: str, value: str | None = None) -> str:
    """op_xml("request", "system", "software", "install", "version", value="10.2.8") ->
    <request><system><software><install><version>10.2.8</version></install>...</request>"""
    inner = value if value is not None else ""
    for tag in reversed(path):
        inner = f"<{tag}>{inner}</{tag}>"
    return inner


class PanosClient:
    def __init__(self, address: str, username: str, password: str, fingerprint: str,
                 timeout: float = 600, port: int = 443):
        self.fingerprint = require_fingerprint(fingerprint, "PAN-OS")
        self.address, self.username, self.password = address, username, password
        self.timeout, self.port = timeout, port
        self.key = ""

    def _call(self, params: dict, raw: bytes | None = None, content_type: str = "") -> ET.Element:
        headers = {"Accept": "application/xml"}
        if self.key:
            headers["X-PAN-KEY"] = self.key
        if raw is None:  # parameters in the body, so passwords and keys stay out of logs
            raw, content_type = urlencode(params).encode(), "application/x-www-form-urlencoded"
            path = "/api/"
        else:
            path = "/api/?" + urlencode(params)
        headers["Content-Type"] = content_type
        conn = pinned_connection(self.address, self.port, self.fingerprint, self.timeout, "PAN-OS")
        try:
            conn.request("POST", path, body=raw, headers=headers)
            resp = conn.getresponse()
            text = resp.read().decode("utf-8", "replace")
        except OSError as exc:
            raise DeviceError(UNREACHABLE, f"PAN-OS API connection failed: {exc}") from None
        finally:
            conn.close()
        if resp.status in (401, 403):
            raise DeviceError(AUTH, "PAN-OS API rejected the upgrade account")
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            raise DeviceError(ERROR, f"PAN-OS API: HTTP {resp.status} {text[:300]}") from None
        if resp.status >= 400 or root.get("status") != "success":
            msg = " ".join(t.strip() for t in root.itertext() if t.strip())
            raise DeviceError(ERROR, f"PAN-OS API: {msg[:300] or resp.status}")
        return root

    def login(self) -> None:
        root = self._call({"type": "keygen", "user": self.username, "password": self.password})
        self.key = root.findtext("./result/key") or ""
        if not self.key:
            raise DeviceError(AUTH, "PAN-OS API returned no key")

    def op(self, cmd: str) -> ET.Element:
        return self._call({"type": "op", "cmd": cmd})

    # --- read-only ---------------------------------------------------------------

    def software_info(self) -> list[dict]:
        """Versions the firewall knows: [{version, downloaded, current}]."""
        root = self.op(op_xml("request", "system", "software", "info"))
        return [{"version": e.findtext("version") or "", "downloaded": e.findtext("downloaded") == "yes",
                 "current": e.findtext("current") == "yes"}
                for e in root.iter("entry") if e.find("version") is not None]

    def job(self, job_id: str) -> dict:
        root = self.op(op_xml("show", "jobs", "id", value=job_id))
        j = root.find(".//job")
        details = " ".join((j.findtext("./details/line") or "").split()) if j is not None else ""
        return {"status": j.findtext("status") if j is not None else "",
                "result": j.findtext("result") if j is not None else "", "details": details}

    # --- changes -----------------------------------------------------------------

    def upload(self, local: Path) -> None:
        raw, content_type = multipart("file", local)
        self._call({"type": "import", "category": "software"}, raw=raw, content_type=content_type)

    def install(self, version: str) -> str:
        """Start installing a version; returns the job id."""
        root = self.op(op_xml("request", "system", "software", "install", "version", value=version))
        job = root.findtext(".//job") or ""
        if not job:
            raise DeviceError(ERROR, "PAN-OS didn't return an install job")
        return job

    def restart(self) -> None:
        self.op(op_xml("request", "restart", "system"))

    def ha_state(self, state: str) -> None:
        """'suspend' or 'functional'."""
        self.op(op_xml("request", "high-availability", "state", state))
