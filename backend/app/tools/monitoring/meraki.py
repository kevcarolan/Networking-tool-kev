"""Cisco Meraki through the Dashboard API (v1): devices, their status, MX uplinks and
scheduled firmware upgrades, read with a read-only API key.

Meraki devices are managed from the Meraki cloud, so they aren't polled with ping and SNMP
like the rest: the poller asks the Dashboard API every ``monitor_meraki_seconds`` (5
minutes) and keeps the answers in its own store. Read-only: only GET requests are sent.

* The API key is encrypted with the credential key, like device passwords, and only sent to
  the Dashboard API address chosen for the connection (``BASES``). Redirects (Meraki moves
  requests to the organisation's shard) are followed only to Meraki's own domain.
* Rate limits: Meraki allows about 10 requests a second per organisation; a "429 Too Many
  Requests" answer is waited out (Retry-After) and tried again.
* The server needs outbound HTTPS (443) to the Dashboard API: it can't work on an air-gapped
  site. An HTTPS proxy is used when ``https_proxy`` is set for the service.
"""

import datetime as dt
import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable

BASES = {
    "https://api.meraki.com/api/v1": "Global (api.meraki.com)",
    "https://api.meraki.ca/api/v1": "Canada (api.meraki.ca)",
    "https://api.meraki.cn/api/v1": "China (api.meraki.cn)",
    "https://api.gov-meraki.com/api/v1": "US government (api.gov-meraki.com)",
}
DEFAULT_BASE = "https://api.meraki.com/api/v1"
PRODUCT_TYPES = {"appliance": "firewall", "switch": "switch", "wireless": "access point",
                 "camera": "camera", "cellularGateway": "router", "sensor": "other",
                 "systemsManager": "other", "wirelessController": "wireless controller"}
STATUSES = {"online": "Online", "alerting": "Alerting", "offline": "Offline", "dormant": "Dormant"}
MAX_PAGES = 50
UPGRADES_EVERY = 3600  # scheduled firmware upgrades: once an hour is plenty

Fetch = Callable[[str, dict], tuple[int, dict, bytes]]


class MerakiError(Exception):
    """A request that failed; the message is for people."""


def _domain(url: str) -> str:
    host = urllib.parse.urlsplit(url).hostname or ""
    return ".".join(host.split(".")[-2:])  # meraki.com, gov-meraki.com, meraki.cn...


class _MerakiRedirects(urllib.request.HTTPRedirectHandler):
    """Follow redirects only to the same Meraki domain (they carry the API key)."""

    def __init__(self, domain: str):
        self.domain = domain

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urlsplit(newurl)
        if target.scheme != "https" or not (target.hostname or "").endswith(self.domain):
            raise MerakiError(f"The Dashboard API redirected to an unexpected address ({target.hostname})")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def urllib_fetch(domain: str, timeout: int = 30) -> Fetch:
    """GET over HTTPS with the system's trusted certificates (and https_proxy if set)."""
    opener = urllib.request.build_opener(_MerakiRedirects(domain),
                                         urllib.request.HTTPSHandler(context=ssl.create_default_context()))

    def fetch(url: str, headers: dict) -> tuple[int, dict, bytes]:
        try:
            with opener.open(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
                return r.status, dict(r.headers), r.read(20 * 2**20)
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers or {}), exc.read(65536) if exc.fp else b""
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise MerakiError(f"Can't reach the Dashboard API: {reason}. The server needs outbound "
                              "HTTPS to it (the firewall, or https_proxy)") from None
    return fetch


class MerakiClient:
    def __init__(self, base: str, api_key: str, fetch: Fetch | None = None, sleep=time.sleep):
        if base not in BASES:
            raise MerakiError("Unknown Dashboard API address")
        self.base, self.key = base, api_key
        self.fetch = fetch or urllib_fetch(_domain(base))
        self.sleep = sleep
        self.requests = 0

    def _get(self, url: str) -> tuple[object, dict]:
        headers = {"Authorization": f"Bearer {self.key}", "Accept": "application/json",
                   "User-Agent": "network-inventory/1.0"}
        for attempt in range(4):
            self.requests += 1
            status, head, body = self.fetch(url, headers)
            if status == 429 and attempt < 3:
                try:
                    wait = float({k.lower(): v for k, v in head.items()}.get("retry-after", 2))
                except ValueError:
                    wait = 2
                self.sleep(min(max(wait, 1), 30))
                continue
            if status == 200:
                try:
                    return json.loads(body or b"null"), head
                except ValueError:
                    raise MerakiError("The Dashboard API sent something that isn't JSON") from None
            raise MerakiError(_message(status, body))
        raise MerakiError(_message(429, b""))

    def get(self, path: str, params: dict | None = None):
        url = f"{self.base}{path}" + (f"?{urllib.parse.urlencode(params)}" if params else "")
        return self._get(url)[0]

    def get_all(self, path: str, params: dict | None = None) -> list:
        """Every page (the Link: <...>; rel=next header), up to MAX_PAGES."""
        url = f"{self.base}{path}?{urllib.parse.urlencode({'perPage': 1000, **(params or {})})}"
        out: list = []
        for _ in range(MAX_PAGES):
            data, head = self._get(url)
            out += data if isinstance(data, list) else []
            link = {k.lower(): v for k, v in head.items()}.get("link", "")
            m = re.search(r'<([^>]+)>;\s*rel="?next"?', link)
            if not m:
                break
            url = m.group(1)
            if _domain(url) != _domain(self.base):
                raise MerakiError("The Dashboard API sent a next-page link to another address")
        return out

    # --- what is read -----------------------------------------------------------------------

    def organizations(self) -> list[dict]:
        return [{"id": str(o.get("id")), "name": o.get("name", "")} for o in self.get("/organizations") or []]

    def snapshot(self, org_id: str, upgrades: bool = True) -> dict:
        """Everything the page shows for one organisation."""
        org = quote(org_id)
        networks = {n["id"]: n for n in self.get_all(f"/organizations/{org}/networks")}
        devices = self.get_all(f"/organizations/{org}/devices")
        statuses = {s.get("serial"): s for s in self.get_all(f"/organizations/{org}/devices/statuses")}
        try:
            uplinks = {u.get("serial"): u.get("uplinks") or [] for u in
                       self.get_all(f"/organizations/{org}/appliance/uplink/statuses")}
        except MerakiError:
            uplinks = {}  # an organisation with no MX
        rows = []
        for d in devices:
            s = statuses.get(d.get("serial")) or {}
            net = networks.get(d.get("networkId")) or {}
            rows.append({
                "serial": d.get("serial", ""), "name": d.get("name") or d.get("serial", ""),
                "model": d.get("model", ""), "product_type": d.get("productType") or s.get("productType", ""),
                "network_id": d.get("networkId") or "", "network": net.get("name", ""),
                "mac": d.get("mac", ""), "lan_ip": d.get("lanIp") or s.get("lanIp") or "",
                "public_ip": s.get("publicIp") or "", "firmware": d.get("firmware", ""),
                "status": s.get("status") or "unknown", "last_reported": s.get("lastReportedAt") or "",
                "tags": " ".join(d.get("tags") or []) if isinstance(d.get("tags"), list) else str(d.get("tags") or ""),
                "address": d.get("address", ""),
                "uplinks": [{"interface": u.get("interface", ""), "status": u.get("status", ""),
                             "ip": u.get("ip", ""), "public_ip": u.get("publicIp", "")}
                            for u in uplinks.get(d.get("serial"), [])],
            })
        upgrade_rows = []
        if upgrades:
            for net_id, net in list(networks.items())[:200]:
                try:
                    fw = self.get(f"/networks/{quote(net_id)}/firmwareUpgrades") or {}
                except MerakiError:
                    continue
                for product, p in (fw.get("products") or {}).items():
                    nxt = (p or {}).get("nextUpgrade") or {}
                    upgrade_rows.append({
                        "network_id": net_id, "network": net.get("name", ""), "product": product,
                        "current": ((p or {}).get("currentVersion") or {}).get("shortName", ""),
                        "next_version": (nxt.get("toVersion") or {}).get("shortName", ""),
                        "next_time": nxt.get("time") or ""})
        return {"devices": rows, "networks": len(networks), "upgrades": upgrade_rows if upgrades else None}


def reported_at(text: str) -> float | None:
    """'2026-10-14T08:00:00.000000Z' as a timestamp (None if empty or unreadable)."""
    try:
        return dt.datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() if text else None
    except ValueError:
        return None


def quote(value: str) -> str:
    return urllib.parse.quote(str(value), safe="")


def _message(status: int, body: bytes) -> str:
    try:
        errors = json.loads(body or b"{}").get("errors") or []
    except (ValueError, AttributeError):
        errors = []
    detail = f" ({'; '.join(map(str, errors))[:200]})" if errors else ""
    if status == 401:
        return "The API key was refused: check it, and that API access is on for the organisation" + detail
    if status == 403:
        return "The API key may not read this organisation" + detail
    if status == 404:
        return "Not found: check the organisation ID" + detail
    if status == 429:
        return "The Dashboard API kept answering 'too many requests': try again later"
    return f"The Dashboard API answered {status}{detail}"
