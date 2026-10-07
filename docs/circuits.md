# Master circuit list

The **Circuits** page holds the master circuit list: every end device or service and the
switch port it uses. When you plan an upgrade, it shows which circuits a device carries.
Each firmware upgrade job saves the device's circuits when it is planned and again when
it starts ([upgrades.md](upgrades.md)).

## Uploading the spreadsheet

1. **Circuits → Upload spreadsheet** (admins only) and choose the workbook (`.xlsx`).
2. NetOps finds the sheet and the header row by the **column names**. The coloured band
   row above the names, the column order and extra sheets don't matter.
3. You get a **preview** before anything changes:
   * rows read, and rows **new / changed / removed** compared with the live list. Changed
     rows show the old and new value of each field;
   * **switches not found in NetOps**: their rows can't be linked yet;
   * rows with **warnings**: an invalid IP, mask, gateway, VLAN or MAC, no MAC *and* no IP, or
     only one of DEVICE and PORT.
4. Click **Make this the live list** or **Discard**. Every upload is kept in **Import history**.

Expected columns, from the current template:

| Band | Columns |
|---|---|
| SERVICE | IP Partition, Service |
| DEVICE INFORMATION | Engineering prefix, Device Name, Device Type, Manufacturer, Hardware Mac Address |
| LOCATION | Floor Level, Room / Area |
| IP DETAILS | IP Address, Subnet Mask, Default Gateway |
| NETWORK PORT | VLAN, TYPE, PORT, **DEVICE** |
| DRAWING DETAILS | Drawing Number, Device Drawing Reference |

Each row needs a **MAC address or an IP address**, so NetOps can find it on the network.
**DEVICE** and **PORT** are optional: they are the *documented* location. Leave them empty
and NetOps fills in the *live* location from the switches (see below). Any other missing
column is left empty.

## How rows are linked to NetOps devices

- **DEVICE** is matched to a NetOps device name, ignoring upper/lower case. `ACC-SW01`
  matches a device called `ACC-SW01`, `acc-sw01.corp.local` or `SITEA-ACC-SW01`.
  * An exact name wins over a match on the end of a name.
  * If several devices match, the row shows **Several devices match**. Rename one so the
    match is unambiguous.
- Linking happens every time the list is shown. So when you add a missing switch to
  NetOps later, its rows link straight away, without uploading again.
- **PORT** short and long forms are treated as the same port: `Gi2/0/13` =
  `GigabitEthernet2/0/13`, also `Te`, `Fa`, `Eth`, `Po`, and AlliedWare Plus `port1.0.1`.

## Where it shows

- **Circuits page:**
  * tiles: total, linked, not linked, with warnings, switches;
  * search and filters by service, switch, VLAN and link status;
  * CSV export.
- **Device → History → Circuits tab:** the circuits on that switch, grouped by service and
  VLAN. This is the list an upgrade job will show and save.

## Where each circuit really is (live location)

NetOps reads the **MAC address table** of every switch, and the **ARP table** of every
device that routes, and matches them with the list. The uploaded sheet stays as it was:
the live location is shown **next to** it.

**When the tables are read:**
* **Weekly**, by default Sunday at 02:00 (server time): `NETOPS_CIRCUIT_SCAN_SCHEDULE`, e.g.
  `sun 02:00` or `daily 02:00`; empty turns the scheduled scan off.
* **In every upgrade job**, for the device being upgraded: at the pre-checks and again at the
  post-checks. So the job's circuit list is based on fresh data.
* **Scan network now** on the Circuits page (admins), e.g. after installing new kit.

The scan logs in with each device's **backup account** and only runs `show` commands:

| Platform | Commands |
|---|---|
| IOS / IOS-XE | `show mac address-table`, `show ip arp`, `show cdp neighbors detail`, `show lldp neighbors detail`, `show etherchannel summary` |
| NX-OS | `show mac address-table`, `show ip arp vrf all`, CDP and LLDP detail, `show port-channel summary` |
| AlliedWare Plus | `show mac address-table`, `show arp`, `show lldp neighbors detail` |
| ASA | `show arp` (to find the MAC of rows that only have an IP) |
| Other vendors | See [vendors.md](vendors.md) |

**How a circuit is found:**
1. Its MAC from the sheet. If the sheet has only an IP, the MAC comes from an ARP table
   (shown as "MAC … from ARP").
2. The switch port where that MAC is learned **at the edge**. Every switch on the way also
   learns it on its uplink, so these are ignored:
   * port-channels and their member ports;
   * ports whose CDP or LLDP neighbour is a switch or router.

   A port with an IP phone or a wireless access point behind it is *not* an uplink: the
   device behind the phone is still on that port.

**Status** (column "On the network", tiles and the filter):

| Status | Meaning |
|---|---|
| Matches the list | Found on the switch and port the sheet says |
| Moved | Found on a different switch or port |
| Found | The sheet has no switch/port; NetOps found it |
| Not seen | The MAC isn't in any table. The device may be off or quiet (switches forget a MAC after about 5 minutes without traffic). The last place it was seen is shown |
| Several ports | Seen on more than one edge port (e.g. a hub, or a moved VM) |
| No MAC or IP | The row has neither, so it can't be looked up |

A switch that can't be read keeps its last tables, so one failed login doesn't make every
circuit on it "Not seen". The scan's result and errors are shown under the tiles.

**Exports:**
* **Export CSV:** the list as uploaded, plus the live columns.
* **Updated sheet (.xlsx):** the list with **DEVICE and PORT taken from the network** where the
  circuit was found, plus "Documented DEVICE/PORT", the status and when it was last seen.
  Uploading this file again makes the live locations the documented ones.

**In upgrade jobs:** before the reload, the job records which circuits are on the device's
edge ports. After the reload, the post-check **"Circuits seen before the upgrade are back"**
lists any that are missing, with their **name, MAC address, service, VLAN and port**. It is a
**warning**: it doesn't stop the commit, because a quiet device may not have sent anything
yet. Check them, then Re-run post-checks if you like. Circuits now on a different port are
listed for information.

## Later

A sync with NetBox, once NetBox is in the closed environment.
