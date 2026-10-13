# Master circuit list

The **Circuits** page holds the master circuit list: every end device or service and the
switch port it uses. When you plan an upgrade, it shows which circuits a device carries.
Each firmware upgrade job saves the device's circuits when it is planned and again when
it starts ([upgrades.md](upgrades.md)).

## Uploading the spreadsheet

1. **Circuits → Upload spreadsheet** (*Circuits: manage*) and choose the file: an Excel
   workbook (`.xlsx`) or a CSV file (comma, semicolon or tab separated).
2. The header row is found by the **column names**. The coloured band row above the names,
   the column order and extra sheets don't matter. A header is recognised when at least six
   of the names below are in it, or when every name in it is one the list knows (a
   **Blank template** with only a few columns).
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
| LOCATION | Site, Floor Level, Room / Area |
| IP DETAILS | IP Address, Subnet Mask, Default Gateway |
| NETWORK PORT | VLAN, TYPE, PORT, **DEVICE** |
| DRAWING DETAILS | Drawing Number, Device Drawing Reference |

Each row needs a **MAC address or an IP address**, so NetOps can find it on the network.
**DEVICE** and **PORT** are optional: they are the *documented* location. Leave them empty
and NetOps fills in the *live* location from the switches (see below). Any other missing
column is left empty. Custom columns (below) are read by their name too.

### A blank template to fill in

**Blank template** gives a sheet with only the column names, as CSV or Excel, in the form
the upload reads:

* **The columns I see** (the ones ticked in **Columns**) or **Every column**;
* **Hardware Mac Address** and **IP Address** are always in it;
* the Excel version has a second sheet, *How to fill in*, with the rules above.

Fill it in, one row per circuit, and upload it. The upload replaces the whole list, so
start from **Export CSV** instead when you only want to change a few rows.

## Which site a circuit is at

Each circuit is linked to a site on the **Sites** page ([sites.md](sites.md)):

1. the list's **Site** column (a site's name or code; *Site name* and *Site code* headers
   work too);
2. else the site of the switch it is documented on (DEVICE);
3. else the site of the switch where the network scan last found it.

The **Site** column shows the site as a link (and *from its switch* or *from where it was
found* when it didn't come from the list), or *not on the site list* for a name the Sites
page doesn't have. Filter by site with **All sites**; *Not at a listed site* shows the rest.
The exports have the list's *Site* and the **Linked site**. Renaming a site, or its code,
also changes it in the live circuit list (and a pending upload).

## A switch's ports

**Ports** (on Config backups, the Inventory, an item's form, or a device's History) draws a
device as a faceplate per module (e.g. `gi1/0/`), odd ports on top. Each port is coloured:

| Colour | Means |
|---|---|
| Green | The circuit the list puts here is here |
| Red | The circuit the list puts here isn't (it moved, or wasn't seen) |
| Amber | A circuit the list puts on another port is here |
| White | In use (MACs seen), but not in the circuit list |
| Blue | An uplink to another switch (CDP/LLDP or a port-channel) |
| Dashed | Nothing seen |

Click a port for its circuits (documented where, found where) and the MAC addresses seen,
with their IP from any device's ARP table. It is built from the last scan and the circuit
list only: no device is contacted. Ports are shown up to the highest one seen or listed.

## Choosing the columns you see

**Columns** (everyone): tick the columns you want and put them in order. It is remembered
for you, in your browser; others keep their own. **Reset to the defaults** goes back.

* **Combined** columns show two or three values in one cell: *Service* (with IP
  partition), *Device* (name, engineering prefix, warnings), *Type / make*, *Location*,
  *Site*, *IP* (with gateway and mask), *VLAN* (with connection type), *Switch / port (list)*,
  *On the network* and *Drawing*. These are the default view.
* Every value also has a column of its own (*Subnet Mask*, *Drawing Number*...), plus
  *Warnings* and the custom columns.

## Custom columns

**Custom columns** (admins): add your own columns for everyone, e.g. *Patch panel* or
*Cable number*. They are text. Then:

* an upload reads a column with exactly that name (upper/lower case and punctuation don't
  matter) and keeps its values with each row;
* they are in **Columns**, the search, the blank template and both exports, and the
  preview shows their changes like any other column;
* **Rename** changes the name the upload looks for; the values stay. **Delete** removes
  the column and its values from every version of the list.

A custom column can't have the name of a built-in column (or of one the upload already
reads, such as *Room* or *Mask*), nor of an export-only column such as *Live status*.

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
  * search (including custom columns) and filters by service, switch, VLAN and link status;
  * the columns you choose;
  * **Export CSV** and **Updated sheet**, with the custom columns.
- **Device → History → Circuits tab:** the circuits on that switch, grouped by service and
  VLAN. This is the list an upgrade job will show and save.

## Where each circuit really is (live location)

NetOps reads the **MAC address table** of every switch, and the **ARP table** of every
device that routes, and matches them with the list. The uploaded sheet stays as it was:
the live location is shown **next to** it.

**When the tables are read:**
* **Every night**, by default at 03:00 (server time), on the Settings page or `NETOPS_CIRCUIT_SCAN_SCHEDULE`:
  `daily 03:00` (every night, the default) or `sun 02:00` (weekly); empty turns the scheduled scan off.
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
