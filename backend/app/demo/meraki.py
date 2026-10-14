"""A pretend Meraki Dashboard API for the demo and the tests: three stores, each with an MX,
a switch and access points; a Galway access point offline, the Cork MX alerting, and
firmware upgrades scheduled in Dublin and Cork. Answers like the real API (JSON, paging with
a Link header, 401 for a wrong key, 429 when asked to), so the client is tested end to end.
Nothing is sent on the network.
"""

import datetime as dt
import json
import time
import urllib.parse

KEY = "demo-meraki-api-key"
ORG = {"id": "549236", "name": "Demo Retail"}
NETWORKS = [{"id": "L_100", "name": "Dublin store"}, {"id": "L_200", "name": "Cork store"},
            {"id": "L_300", "name": "Galway store"}]
DEVICES = [  # (network, name, model, product type, serial, firmware)
    ("L_100", "dub-mx1", "MX68", "appliance", "Q2KY-AAAA-0001", "MX 18.107.10"),
    ("L_100", "dub-ms1", "MS120-8LP", "switch", "Q2HP-AAAA-0002", "MS 16.9"),
    ("L_100", "dub-mr1", "MR46", "wireless", "Q2KD-AAAA-0003", "MR 30.7"),
    ("L_100", "dub-mr2", "MR46", "wireless", "Q2KD-AAAA-0004", "MR 30.7"),
    ("L_200", "cork-mx1", "MX67", "appliance", "Q2KY-BBBB-0001", "MX 18.107.10"),
    ("L_200", "cork-ms1", "MS120-8LP", "switch", "Q2HP-BBBB-0002", "MS 16.9"),
    ("L_200", "cork-mr1", "MR36", "wireless", "Q2KD-BBBB-0003", "MR 29.7.1"),
    ("L_300", "gal-mx1", "MX67", "appliance", "Q2KY-CCCC-0001", "MX 18.107.10"),
    ("L_300", "gal-mr1", "MR36", "wireless", "Q2KD-CCCC-0002", "MR 29.7.1"),
    ("L_300", "gal-mr2", "MR36", "wireless", "Q2KD-CCCC-0003", "MR 29.7.1"),
]


class FakeDashboard:
    """Call it like the real fetch: (url, headers) -> (status, headers, body)."""

    def __init__(self, clock=time.time, page_size: int = 4):
        self.clock = clock
        self.page_size = page_size  # small, so paging is used
        self.status = {d[4]: "online" for d in DEVICES}
        self.status["Q2KD-CCCC-0003"] = "offline"
        self.status["Q2KY-BBBB-0001"] = "alerting"
        self.too_many = 0  # answer 429 this many times first
        self.calls: list[str] = []

    def __call__(self, url: str, headers: dict) -> tuple[int, dict, bytes]:
        self.calls.append(url)
        if headers.get("Authorization") != f"Bearer {KEY}":
            return 401, {}, json.dumps({"errors": ["Invalid API key"]}).encode()
        if self.too_many:
            self.too_many -= 1
            return 429, {"Retry-After": "1"}, b'{"errors": ["API rate limit exceeded"]}'
        parts = urllib.parse.urlsplit(url)
        path = parts.path.split("/api/v1", 1)[-1]
        q = dict(urllib.parse.parse_qsl(parts.query))
        net = {n["id"]: n for n in NETWORKS}
        now = dt.datetime.fromtimestamp(self.clock(), dt.UTC)
        if path == "/organizations":
            return self._json([ORG])
        if path == f"/organizations/{ORG['id']}/networks":
            return self._json(NETWORKS)
        if path == f"/organizations/{ORG['id']}/devices":
            rows = [{"name": n, "serial": s, "mac": f"e0:55:3d:{i:02x}:10:{i:02x}", "model": m,
                     "networkId": nid, "productType": p, "firmware": fw, "lanIp": f"10.{20 + i}.0.1",
                     "tags": ["store"], "address": net[nid]["name"]}
                    for i, (nid, n, m, p, s, fw) in enumerate(DEVICES)]
            return self._page(url, rows, q)
        if path == f"/organizations/{ORG['id']}/devices/statuses":
            rows = [{"serial": s, "name": n, "productType": p, "status": self.status[s],
                     "lastReportedAt": (now - dt.timedelta(hours=7 if self.status[s] == "offline" else 0,
                                                           minutes=1)).isoformat().replace("+00:00", "Z"),
                     "publicIp": f"203.0.113.{10 + i}" if p == "appliance" else "", "lanIp": f"10.{20 + i}.0.1"}
                    for i, (nid, n, m, p, s, fw) in enumerate(DEVICES)]
            return self._page(url, rows, q)
        if path == f"/organizations/{ORG['id']}/appliance/uplink/statuses":
            rows = [{"serial": s, "networkId": nid, "uplinks": [
                {"interface": "wan1", "status": "failed" if s == "Q2KY-BBBB-0001" else "active",
                 "ip": "192.0.2.2", "publicIp": f"203.0.113.{10 + i}"},
                {"interface": "wan2", "status": "active" if s == "Q2KY-BBBB-0001" else "ready",
                 "ip": "198.51.100.2", "publicIp": ""}]}
                for i, (nid, n, m, p, s, fw) in enumerate(DEVICES) if p == "appliance"]
            return self._page(url, rows, q)
        if path.startswith("/networks/") and path.endswith("/firmwareUpgrades"):
            nid = path.split("/")[2]
            when = lambda days: (now + dt.timedelta(days=days)).replace(hour=2, minute=0, second=0, microsecond=0).isoformat().replace("+00:00", "Z")  # noqa: E731
            products = {"appliance": {"currentVersion": {"shortName": "MX 18.107.10"}, "nextUpgrade": {}},
                        "wireless": {"currentVersion": {"shortName": "MR 30.7" if nid == "L_100" else "MR 29.7.1"},
                                     "nextUpgrade": {}}}
            if nid == "L_100":
                products["appliance"]["nextUpgrade"] = {"time": when(2), "toVersion": {"shortName": "MX 18.211.2"}}
            if nid == "L_200":
                products["wireless"]["nextUpgrade"] = {"time": when(5), "toVersion": {"shortName": "MR 30.7"}}
            return self._json({"products": products})
        return 404, {}, b'{"errors": ["Not found"]}'

    def _json(self, data, headers=None):
        return 200, headers or {}, json.dumps(data).encode()

    def _page(self, url: str, rows: list, q: dict):
        start = int(q.get("startingAfter") or 0)
        page = rows[start:start + self.page_size]
        head = {}
        if start + self.page_size < len(rows):
            parts = urllib.parse.urlsplit(url)
            nxt = {**q, "startingAfter": str(start + self.page_size)}
            head["Link"] = f'<{parts.scheme}://{parts.netloc}{parts.path}?{urllib.parse.urlencode(nxt)}>; rel=next'
        return self._json(page, head)
