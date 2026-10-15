"""The demo network: about 26 simulated devices on five sites, and the data a new user
would have entered (accounts, standards, images, a circuit list), so every page has
something to show. Used by ``python -m app.demo``; nothing here talks to a real device.

Addresses are from the documentation ranges (192.0.2.0/24, 198.51.100.0/24,
203.0.113.0/24), which are never routed, as a second guard.
"""

import io
from datetime import UTC, datetime, timedelta
import time
from dataclasses import dataclass

from openpyxl import Workbook

from app.demo import samples as s
from app.demo import topology as demo_topology
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


# SNMP-only devices (no SSH: monitored with ping, SNMP and sensors): name, site, platform
SNMP_DEVICES = [("hq-ups1", "HQ", "snmp_ups"), ("dc1-pdu1", "DC1", "snmp_pdu"),
                ("dc1-env1", "DC1", "snmp_env")]


DEMO_SENSORS = [
    ("UPS on battery", "1.3.6.1.2.1.33.1.4.1.0", {"mode": "state", "ok_values": "3", "warn_values": "4",
                                                   "platform": "snmp_ups", "notes": "upsOutputSource: 3 = normal, 5 = on battery"}),
    ("UPS battery charge", "1.3.6.1.2.1.33.1.2.4.0", {"unit": "%", "warn_below": 80, "crit_below": 50,
                                                       "platform": "snmp_ups"}),
    ("UPS runtime", "1.3.6.1.2.1.33.1.2.3.0", {"unit": "min", "warn_below": 15, "crit_below": 5,
                                                "platform": "snmp_ups"}),
    ("PDU load", "1.3.6.1.4.1.318.1.1.12.2.3.1.1.2.1", {"unit": "A", "scale": 0.1, "warn_above": 12,
                                                         "crit_above": 16, "platform": "snmp_pdu",
                                                         "notes": "APC rPDULoadStatusLoad, phase 1 (tenths of an amp)"}),
    ("Room temperature", "1.3.6.1.4.1.318.1.1.10.2.3.2.1.4.1", {"unit": "°C", "warn_above": 27, "crit_above": 32,
                                                                 "platform": "snmp_env"}),
]


def snmp_address(k: int) -> str:
    return f"192.0.2.{200 + k}"


def address(i: int) -> str:
    nets = ("192.0.2", "198.51.100", "203.0.113")
    return f"{nets[i // 80]}.{10 + i % 80}"


def address_of(name: str) -> str:
    """A demo device's address by name (SSH devices and SNMP-only ones)."""
    for i, d in enumerate(DEVICES):
        if d.name == name:
            return address(i)
    return snmp_address(next(k for k, (n, _, _) in enumerate(SNMP_DEVICES) if n == name))


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
    addresses = {d.name: address(i) for i, d in enumerate(DEVICES)}
    platforms = {d.name: d.platform for d in DEVICES}
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
        sim.outputs.update(demo_topology.outputs(d.name, d.platform, addresses, platforms))
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
    ws.append([None] * (len(HEADER) + 1))
    ws.append(BANDS + ["PATCHING"])
    ws.append(HEADER + ["Patch panel"])  # a custom column (seed adds it first)
    for d in DEVICES:
        if d.platform != "cisco_ios":
            continue
        no = int(d.name[-1])
        for k, r in enumerate(circuits_for(no)):
            ws.append(["DEMO", r["service"], None, r["name"], "End device", "Various",
                       r["mac"].replace(".", ""), "Ground Floor", "Comms room", r["ip"],
                       "255.255.255.0", r["ip"].rsplit(".", 1)[0] + ".1", r["vlan"], "STATIC",
                       r["port"], d.name, None, None, f"HQ-PP-0{1 + no % 2} port {k + 1}"])
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
    _ok(client.post("/api/circuits/fields", json={"label": "Patch panel"}))
    imp = _ok(client.put("/api/circuits/imports/upload", params={"filename": "circuits.xlsx"},
                         content=circuit_workbook())).json()
    _ok(client.post(f"/api/circuits/imports/{imp['id']}/commit"))
    inventory(client)
    # SNMP-only devices, after the inventory so hq-ups1 takes over the HQ-UPS1 row (its rack
    # place, model and serial); no credential: nothing is read over SSH
    for k, (name, site, platform) in enumerate(SNMP_DEVICES):
        ids[name] = _ok(client.post("/api/devices", json={
            "name": name, "address": snmp_address(k), "platform": platform, "site": site})).json()["id"]
    sites(client)
    calendar(client, ids)
    _ok(client.post("/api/compliance/examples"))  # checked at each device's first backup
    _ok(client.post("/api/monitoring/profiles", json={  # the simulated devices answer any secret
        "name": "switches-v3", "version": "3", "username": "netops-mon", "level": "authPriv",
        "auth_protocol": "SHA", "auth_key": "demo-auth-pass", "priv_protocol": "AES",
        "priv_key": "demo-priv-pass", "is_default": True}))
    _ok(client.post("/api/monitoring/sensors", json={  # custom SNMP sensors (app.demo.monitor answers them)
        "name": "BGP peer", "oid": "1.3.6.1.2.1.15.3.1.2", "mode": "state", "table": True, "ok_values": "6",
        "device_ids": [ids["hq-core1"], ids["hq-core2"]], "notes": "bgpPeerState: 6 = established"}))
    _ok(client.post("/api/monitoring/sensors", json={
        "name": "ASA connections", "oid": "1.3.6.1.4.1.9.9.147.1.2.2.2.1.5.40.6", "unit": "connections",
        "warn_above": 50000, "platform": "cisco_asa"}))
    _ok(client.post("/api/monitoring/sensors", json={
        "name": "IPsec tunnels", "oid": "1.3.6.1.4.1.9.9.171.1.3.1.1.0", "unit": "tunnels",
        "warn_below": 1, "platform": "cisco_asa"}))
    for name, oid, extra in DEMO_SENSORS:  # the SNMP-only devices' readings (app.demo.monitor answers)
        _ok(client.post("/api/monitoring/sensors", json={"name": name, "oid": oid, **extra}))
    from app.demo import meraki as demo_meraki
    _ok(client.post("/api/monitoring/meraki/connections", json={  # answered by app.demo.meraki
        "name": demo_meraki.ORG["name"], "api_key": demo_meraki.KEY, "org_id": demo_meraki.ORG["id"],
        "org_name": demo_meraki.ORG["name"]}))
    screen = _ok(client.post("/api/displays", json={"name": "Demo wall"})).json()
    return {"display_key": screen["key"], "ids": ids}


# Inventory-only items (not managed by the tools): (name, type, site, rack, U, height, details)
EXTRA = [
    ("HQ-R01", "rack", "HQ", "", None, 42, {"manufacturer": "APC", "model": "NetShelter SX 42U",
                                          "building": "Main building", "floor": "Ground floor",
                                          "room": "Comms 1"}),
    ("HQ-R02", "rack", "HQ", "", None, 42, {"manufacturer": "APC", "model": "NetShelter SX 42U",
                                          "building": "Main building", "floor": "Ground floor",
                                          "room": "Comms 1"}),
    ("HQ-UPS1", "UPS", "HQ", "HQ-R01", 1, 3, {"manufacturer": "APC", "model": "Smart-UPS SRT 5000",
                                               "serial": "AS2219123456", "warranty_end": "2027-03-31"}),
    ("HQ-PDU-A", "PDU", "HQ", "HQ-R01", None, 0, {"manufacturer": "Raritan", "model": "PX3-5260R"}),
    ("HQ-PDU-B", "PDU", "HQ", "HQ-R01", None, 0, {"manufacturer": "Raritan", "model": "PX3-5260R"}),
    ("HQ-PP-01", "patch panel", "HQ", "HQ-R02", 42, 1, {"manufacturer": "Panduit", "model": "48-port Cat6A",
                                                       "rack_depth": "half"}),
    ("HQ-PP-02", "patch panel", "HQ", "HQ-R02", 41, 1, {"manufacturer": "Panduit", "model": "48-port Cat6A",
                                                       "rack_depth": "half"}),
    ("HQ-PP-03", "patch panel", "HQ", "HQ-R02", 42, 1, {"manufacturer": "Panduit", "model": "24-port fibre",
                                                       "rack_depth": "half", "rack_face": "rear"}),
    ("hq-esx01", "virtual host", "HQ", "HQ-R01", 20, 2, {"manufacturer": "Dell", "model": "PowerEdge R760",
                                                        "serial": "7XKQ2X3", "owner": "Server team",
                                                        "warranty_end": "2028-06-30"}),
    ("hq-nms01", "server", "HQ", "HQ-R01", 18, 1, {"manufacturer": "Dell", "model": "PowerEdge R660",
                                                   "role": "network management", "owner": "Network team"}),
    ("DC1-R10", "rack", "DC1", "", None, 48, {"manufacturer": "Rittal", "model": "TS IT 48U",
                                               "building": "Data hall", "room": "Hall A"}),
    ("DC1-R11", "rack", "DC1", "", None, 48, {"manufacturer": "Rittal", "model": "TS IT 48U",
                                               "building": "Data hall", "room": "Hall A"}),
    ("dc1-san01", "storage", "DC1", "DC1-R11", 10, 4, {"manufacturer": "NetApp", "model": "AFF A400",
                                                      "owner": "Storage team"}),
    ("BN-R01", "rack", "Branch-North", "", None, 24, {"manufacturer": "APC", "model": "NetShelter WX 24U",
                                                       "building": "Branch office", "room": "Comms cupboard"}),
    ("bn-ups1", "UPS", "Branch-North", "BN-R01", 1, 2, {"manufacturer": "Eaton", "model": "5PX 1500",
                                                       "status": "faulty", "notes": "Battery fault since the last test: replacement ordered"}),
    ("BS-R01", "rack", "Branch-South", "", None, 24, {"manufacturer": "APC", "model": "NetShelter WX 24U",
                                                       "building": "Branch office", "room": "Comms cupboard"}),
    ("WH-R01", "rack", "Warehouse", "", None, 42, {"manufacturer": "APC", "model": "NetShelter SX 42U"}),
    ("spare-c9300-48p", "switch", "HQ", "", None, 1, {"manufacturer": "Cisco", "model": "C9300-48P",
                                                       "serial": "FOC2512X0AB", "status": "spare", "building": "Main building",
                                                       "floor": "Ground floor", "room": "Stores"}),
]
RACK_OF = {"HQ": "HQ-R02", "DC1": "DC1-R10", "Branch-North": "BN-R01", "Branch-South": "BS-R01",
           "Warehouse": "WH-R01"}


def calendar(client, ids: dict) -> None:
    """Planned work for the next weeks, with a clash or two to spot."""
    now = datetime.now(UTC).replace(tzinfo=None, minute=0, second=0, microsecond=0)
    day = lambda n, hour: (now.replace(hour=0) + timedelta(days=n, hours=hour)).isoformat()  # noqa: E731
    image = next((i for i in _ok(client.get("/api/firmware/images")).json()
                  if i["platform"] == "cisco_ios"), None)
    if image:  # an upgrade planned for Thursday night
        _ok(client.post("/api/firmware/jobs", json={
            "device_id": ids["hq-acc-sw6"], "image_id": image["id"], "live": False,
            "change_ref": "CHG0041207", "notes": "Bring hq-acc-sw6 to the standard",
            "planned_start": day(2, 22), "planned_end": day(2, 23)}))
    for ev in [
        {"title": "Replace a fan tray in hq-core1", "kind": "maintenance", "sites": ["Head office"],
         "devices": [ids["hq-core1"]], "change_ref": "CHG0041188",
         "start": day(1, 21), "end": day(1, 22)},
        {"title": "New VLANs for the CCTV upgrade", "kind": "change", "sites": ["Head office"],
         "devices": [ids["hq-acc-sw5"], ids["hq-acc-sw6"]], "change_ref": "CHG0041210",
         "start": day(2, 22), "end": day(3, 0), "notes": "Overlaps the hq-acc-sw6 upgrade"},
        {"title": "ISP line work (provider)", "kind": "outage", "sites": ["Branch North"],
         "start": day(5, 1), "end": day(5, 5), "notes": "Provider ref 7781-22. Branch North offline."},
        {"title": "Firewall rule review", "kind": "change", "sites": ["Head office"],
         "devices": [ids["hq-fw1"]], "change_ref": "CHG0041232", "start": day(9, 19),
         "end": day(9, 20)},
        {"title": "Month-end change freeze", "kind": "freeze", "sites": [],
         "start": day(12, 0), "end": day(15, 0), "notes": "Finance month end: no changes"},
        {"title": "Warehouse switch stack rebuild", "kind": "change", "sites": ["Warehouse"],
         "devices": [ids["wh-sw2"]], "change_ref": "CHG0041250", "start": day(13, 20),
         "end": day(13, 23), "notes": "In the freeze: needs a CAB exception"},
    ]:
        _ok(client.post("/api/calendar/events", json=ev))


def inventory(client) -> None:
    """A custom column, the rack places of the managed devices, and inventory-only items."""
    _ok(client.post("/api/inventory/fields", json={"label": "Power feed", "kind": "choice",
                                                   "choices": ["A", "B", "A+B"]}))
    rows = _ok(client.get("/api/inventory/assets")).json()
    position: dict[str, int] = {}
    for r in rows:
        site = r["values"]["site"] or (r["auto"].get("site") or "")
        rack = RACK_OF.get(site, "")
        position[rack] = position.get(rack, 40) - 1
        _ok(client.put(f"/api/inventory/assets/{r['id']}", json={"values": {
            "rack": rack, "rack_position": position[rack], "rack_units": 1, "x_power_feed": "A+B",
            "purchase_date": "2023-04-01", "supplier": "Example Networks Ltd"}}))
    for name, kind, site, rack, u, height, more in EXTRA:
        _ok(client.post("/api/inventory/assets", json={"values": {
            "name": name, "type": kind, "site": site, "rack": rack, "rack_position": u,
            "rack_units": height, **more}}))


# The site list: four of the five sites the devices use. "Warehouse" is left off, so the Sites
# page shows how it points out a site the inventory uses that isn't on the list.
SITES = [
    {"name": "Head office", "code": "HQ", "type": "office", "region": "North", "city": "Northtown",
     "address": "1 Example Street", "postcode": "NT1 1AA", "country": "United Kingdom",
     "contact": "Facilities desk", "phone": "+44 1632 960000", "access": "Mon-Fri 07:00-19:00, badge",
     "circuits": "2 x 1 Gb/s internet, 10 Gb/s to DC1"},
    {"name": "Data centre 1", "code": "DC1", "type": "data centre", "region": "North", "city": "Northtown",
     "address": "Unit 4, Example Park", "country": "United Kingdom", "contact": "DC operations",
     "phone": "+44 1632 960001", "access": "24x7, booked visits only", "x_power_supply": "A+B"},
    {"name": "Branch North", "code": "Branch-North", "type": "branch", "region": "North",
     "city": "Upton", "country": "United Kingdom", "x_power_supply": "A"},
    {"name": "Branch South", "code": "Branch-South", "type": "branch", "region": "South",
     "city": "Southby", "country": "United Kingdom", "status": "closing",
     "notes": "Moving to the new office next spring", "x_power_supply": "A"},
]


def sites(client) -> None:
    _ok(client.post("/api/sites/fields", json={"label": "Power supply", "kind": "choice",
                                               "choices": ["A", "A+B", "A+B+generator"]}))
    for values in SITES:
        site_id = _ok(client.post("/api/sites", json={"values": values})).json()["id"]
        # Buildings, floors and rooms from what the inventory already says
        _ok(client.post(f"/api/sites/{site_id}/layout/from-inventory"))
    hq = _ok(client.get("/api/sites/index")).json()
    hq_id = next(s["id"] for s in hq if s["code"] == "HQ")
    tree = _ok(client.get(f"/api/sites/{hq_id}/layout")).json()["tree"]
    main = next(b for b in tree if b["name"] == "Main building")
    first = _ok(client.post(f"/api/sites/{hq_id}/locations", json={
        "kind": "floor", "name": "First floor", "parent_id": main["id"]})).json()["id"]
    _ok(client.post(f"/api/sites/{hq_id}/locations", json={"kind": "room", "name": "Comms 2",
                                                            "parent_id": first}))


def _ok(r):
    if r.status_code >= 400:
        raise RuntimeError(f"demo setup failed: {r.request.method} {r.request.url.path}: "
                           f"{r.status_code} {r.text}")
    return r
