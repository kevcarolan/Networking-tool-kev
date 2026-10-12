"""The demo network: about 26 simulated devices on five sites, and the data a new user
would have entered (accounts, standards, images, a circuit list), so every page has
something to show. Used by ``python -m app.demo``; nothing here talks to a real device.

Addresses are from the documentation ranges (192.0.2.0/24, 198.51.100.0/24,
203.0.113.0/24), which are never routed, as a second guard.
"""

import io
import time
from dataclasses import dataclass

from openpyxl import Workbook

from app.demo import samples as s
from app.demo.simnet import IOS_HEALTH, FakeNetwork, SimDevice
from app.tools.circuits import live
from app.tools.config_backup.collector import BackupError

ADMIN_USER = "demo"
ADMIN_PASSWORD = "demo-password"


@dataclass(frozen=True)
class DemoDevice:
    name: str
    site: str
    platform: str
    version: str
    image: str = ""
    model: str = ""


# Two of each kind on the standard and some behind it, so firmware compliance has a story.
DEVICES = [
    *[DemoDevice(f"hq-acc-sw{i}", "HQ", "cisco_ios", v, "flash:packages.conf")
      for i, v in enumerate(["17.12.04", "17.12.04", "17.09.04a", "17.09.04a", "17.12.04",
                             "17.09.04a"], 1)],
    DemoDevice("hq-core1", "HQ", "cisco_nxos", "9.3(10)", "bootflash:///nxos.9.3.10.bin"),
    DemoDevice("hq-core2", "HQ", "cisco_nxos", "9.3(10)", "bootflash:///nxos.9.3.10.bin"),
    DemoDevice("hq-fw1", "HQ", "cisco_asa", "9.18(4)", "disk0:/cisco-asa-fp2k.9.18.4.SPA"),
    *[DemoDevice(f"dc1-leaf{i}", "DC1", "arista_eos", v, "flash:EOS-4.30.1F.swi")
      for i, v in enumerate(["4.32.2F", "4.32.2F", "4.30.1F", "4.30.1F"], 1)],
    DemoDevice("dc1-spine1", "DC1", "juniper_junos", "22.4R3-S2.11"),
    DemoDevice("dc1-spine2", "DC1", "juniper_junos", "22.4R3-S2.11"),
    *[DemoDevice(f"bn-sw{i}", "Branch-North", "aruba_osswitch", v, "primary")
      for i, v in enumerate(["WC.16.11.0012", "WC.16.11.0012", "WC.16.11.0018"], 1)],
    DemoDevice("bn-rtr1", "Branch-North", "mikrotik_routeros", "7.12.1"),
    *[DemoDevice(f"bs-sw{i}", "Branch-South", "allied_awplus", "5.5.2",
                 "flash:/x930-5.5.2-0.4.rel") for i in (1, 2, 3)],
    DemoDevice("wh-sw1", "Warehouse", "dell_os10", "10.5.5.5"),
    DemoDevice("wh-sw2", "Warehouse", "dell_os10", "10.5.5.5"),
    DemoDevice("wh-sw3", "Warehouse", "dell_os10", "10.5.6.0"),
]
FAILING = {"bn-sw3": ("unreachable", "Could not connect over SSH (port 22) - device unreachable?"),
           "wh-sw2": ("auth", "Authentication failed - check the credential profile")}

# (platform, model pattern, approved version, image file to upload or "")
STANDARDS = [
    ("cisco_ios", "C9300-*", "17.12.04", "cat9k_iosxe.17.12.04.SPA.bin"),
    ("arista_eos", "*", "4.32.2F", "EOS-4.32.2F.swi"),
    ("aruba_osswitch", "*", "WC.16.11.0018", "WC_16_11_0018.swi"),
    ("dell_os10", "*", "10.5.6.0", ""),
    ("cisco_nxos", "*", "9.3(10)", ""),
]
LIVE_PLATFORMS = "cisco_ios,arista_eos,aruba_osswitch"

SERVICES = [("CCTV", 40), ("Access control", 42), ("Building management", 50),
            ("Wireless APs", 60)]


def address(i: int) -> str:
    nets = ("192.0.2", "198.51.100", "203.0.113")
    return f"{nets[i // 80]}.{10 + i % 80}"


# --- the simulated network -------------------------------------------------------------

class DemoNetwork(FakeNetwork):
    """The test simulator, slowed down to something a person can watch: a reload takes
    about 15 seconds and an image copy a few."""

    def __init__(self):
        super().__init__(reload_seconds=90)

    def sleep(self, seconds: float) -> None:
        time.sleep(min(seconds, 2.0))
        super().sleep(seconds)

    def transfer(self, target, local, file_system, filename, timeout=3600):
        time.sleep(4)
        return super().transfer(target, local, file_system, filename, timeout)


def _mac(n: int) -> str:
    h = f"02005e{n:06x}"
    return f"{h[0:4]}.{h[4:8]}.{h[8:12]}"


def circuits_for(switch_no: int) -> list[dict]:
    """The end devices on one HQ access switch: a few per service."""
    rows = []
    for k in range(12):
        service, vlan = SERVICES[k % len(SERVICES)]
        n = switch_no * 100 + k
        rows.append({"name": f"{service.split()[0].upper()}-HQ{switch_no}-{k + 1:02d}",
                     "service": service, "vlan": vlan, "mac": _mac(n),
                     "port": f"Gi1/0/{5 + k}", "ip": f"10.{vlan}.{switch_no}.{20 + k}"})
    return rows


def mac_table(rows: list[dict], moved: int | None = None, missing: int | None = None) -> str:
    lines = ["          Mac Address Table", "-------------------------------------------", "",
             "Vlan    Mac Address       Type        Ports", "----    -----------       --------    -----"]
    for i, r in enumerate(rows):
        if i == missing:
            continue
        port = "Gi1/0/40" if i == moved else r["port"]
        lines.append(f"  {r['vlan']:<4}  {r['mac']}    DYNAMIC     {port}")
    lines.append(f"Total Mac Addresses for this criterion: {len(rows)}")
    return "\n".join(lines) + "\n"


def build_network() -> FakeNetwork:
    net = DemoNetwork()
    for i, d in enumerate(DEVICES):
        outputs = dict(IOS_HEALTH) if d.platform == "cisco_ios" else {}
        sim = SimDevice(d.name, d.platform, d.version, d.image or "running", outputs)
        if d.platform == "cisco_ios":
            no = int(d.name[-1])
            rows = circuits_for(no)
            outputs.update({
                "show mac address-table": mac_table(rows, moved=3 if no == 2 else None,
                                                    missing=7 if no == 3 else None),
                "show ip arp": s.IOS_ARP,
                "show lldp neighbors detail": s.LLDP_DETAIL,
                "show cdp neighbors detail": s.CDP_DETAIL,
                "show etherchannel summary": s.ETHERCHANNEL,
            })
            sim.outputs.update(outputs)
        for cmd in live.commands_for(d.platform).values():  # other devices: empty tables
            if sim.output(cmd) == s.INVALID:
                sim.outputs[cmd] = ""
        net.add(sim)
    for _platform, _pattern, version, filename in STANDARDS:
        if filename:
            net.versions[filename] = version
    return net


def fetcher(target) -> str:
    """Config backups: a short, valid configuration; two devices fail on purpose."""
    if target.name in FAILING:
        kind, message = FAILING[target.name]
        raise BackupError(kind, message)
    return (f"! demo configuration\nhostname {target.name}\n!\ninterface Vlan1\n"
            f" description management\n ip address {target.address} 255.255.255.0\n!\n"
            "ntp server 192.0.2.250\nlogging host 192.0.2.251\n!\nend\n")


# --- the circuit list --------------------------------------------------------------------

HEADER = ["IP Partition", "Service", "Engineering prefix", "Device Name", "Device Type",
          "Manufacturer", "Hardware Mac Address", "Floor Level", "Room / Area", "IP Address",
          "Subnet Mask", "Default Gateway", "VLAN", "TYPE", "PORT", "DEVICE", "Drawing Number",
          "Device Drawing Reference"]
BANDS = ["SERVICE", "", "DEVICE INFORMATION", "", "", "", "", "LOCATION", "", "IP DETAILS", "",
         "", "NETWORK PORT", "", "", "", "DRAWING DETAILS", ""]


def circuit_workbook() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Circuits"
    ws.append([None] * len(HEADER))
    ws.append(BANDS)
    ws.append(HEADER)
    for d in DEVICES:
        if d.platform != "cisco_ios":
            continue
        for r in circuits_for(int(d.name[-1])):
            ws.append(["DEMO", r["service"], None, r["name"], "End device", "Various",
                       r["mac"].replace(".", ""), "Ground Floor", "Comms room", r["ip"],
                       "255.255.255.0", r["ip"].rsplit(".", 1)[0] + ".1", r["vlan"], "STATIC",
                       r["port"], d.name, None, None])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# --- filling an empty install through the API ----------------------------------------------

def seed(client, settings, net) -> dict:
    """Run once on an empty demo database: the admin, accounts, devices, standards, images,
    circuit list, a first check of everything, and one wall display. Returns what to print."""
    code = (settings.data_dir / "setup-token").read_text().strip()
    head = {"X-Setup-Code": code}
    _ok(client.post("/api/setup/admin", headers=head, json={
        "username": ADMIN_USER, "display_name": "Demo admin", "password": ADMIN_PASSWORD}))
    _ok(client.post("/api/setup/finish", headers=head))
    _ok(client.post("/api/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASSWORD}))
    _ok(client.put("/api/setup/options", json={"site_name": "Demo network"}))
    ro = _ok(client.post("/api/credentials", json={
        "name": "backup-ro", "username": "netops-ro", "password": "demo"})).json()
    up = _ok(client.post("/api/credentials", json={
        "name": "upgrade-rw", "username": "netops-up", "password": "demo"})).json()
    ids = {}
    for i, d in enumerate(DEVICES):
        dev = _ok(client.post("/api/devices", json={
            "name": d.name, "address": address(i), "platform": d.platform, "site": d.site,
            "credential_id": ro["id"]})).json()
        ids[d.name] = dev["id"]
        if d.platform in LIVE_PLATFORMS.split(","):
            _ok(client.put(f"/api/firmware/devices/{dev['id']}/settings",
                           json={"upgrade_credential_id": up["id"]}))
    for platform, pattern, version, filename in STANDARDS:
        image_id = None
        if filename:
            image_id = _ok(client.put("/api/firmware/images/upload", params={
                "filename": filename, "platform": platform, "version": version,
                "model_pattern": pattern}, content=filename.encode() * 4000)).json()["id"]
        _ok(client.post("/api/firmware/standards", json={
            "platform": platform, "model_pattern": pattern, "target_version": version,
            "image_id": image_id, "notes": "Demo standard"}))
    imp = _ok(client.put("/api/circuits/imports/upload", params={"filename": "circuits.xlsx"},
                         content=circuit_workbook())).json()
    _ok(client.post(f"/api/circuits/imports/{imp['id']}/commit"))
    screen = _ok(client.post("/api/displays", json={"name": "Demo wall"})).json()
    return {"display_key": screen["key"], "ids": ids}


def _ok(r):
    if r.status_code >= 400:
        raise RuntimeError(f"demo setup failed: {r.request.method} {r.request.url.path}: "
                           f"{r.status_code} {r.text}")
    return r
