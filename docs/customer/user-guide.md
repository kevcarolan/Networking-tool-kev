# User guide

For everyone who signs in. What you see depends on the permissions an admin gave you, so
some pages or buttons may be missing for you.

## Signing in

* **Domain account:** sign in with your normal username and password (`jsmith`,
  `jsmith@corp.local` or `CORP\jsmith`).
* **Local account:** sign in with the username an admin gave you. Change your password
  with **Change password** (top right). It needs at least 12 characters.
* You are signed out after 12 hours (an admin can change this), and straight away if an admin
  disables your account.
* **Two-factor sign-in (optional):** after the password, a 6-digit code from an authenticator app on
  your phone. Turn it on with **Two-factor** (top right): scan the QR code, type the code,
  and keep the 10 recovery codes somewhere safe (each signs you in once without the phone).
  Your admin may require it, and then you set it up the next time you sign in. Lost your
  phone? Use a recovery code, or ask an admin to **Reset 2FA**.

A coloured line under the top bar is a notice from the server, for example that the
licence has ended. While a licence has ended, nobody can add devices or start upgrades,
but everything else works. Tell your admin.

A tab with a padlock is a tool your licence doesn't include. Clicking it tells you so.

## Search

The box at the top right finds anything by part of its name or number. Press **/** to
jump to it from anywhere.

| Type | It finds | Click a result to |
|---|---|---|
| a device name, address, site, platform or serial number | devices | open the device's window (backups, ports, circuits…) |
| a name, serial number, asset tag, model, address, MAC or rack | other inventory items (racks, servers, UPSs…) | open the item |
| a site name, code, town or address | sites | open the site's page |
| a circuit's device name, IP, MAC, service, switch, port or drawing | circuits | show it on the Circuits page |
| a MAC address (any format, or part of one) or an IP address | where the last network scan saw it: switch, port and VLAN | open that switch's ports |

Use the arrow keys and Enter to pick a result, Esc to close the list. You only see results
from pages you are allowed to open. A short number like `1234` isn't taken as part of a MAC
(it could be a port or VLAN); type at least 6 digits, or use a separator (`5e:00`).

## Config backups

The device list shows each device's backup status:
* **OK**;
* **Failing**, with the reason (wrong password, unreachable, timeout, a command the device
  refused, no credential set);
* **Never backed up**;
* **Disabled**;
* **SNMP only**: a UPS, PDU or probe that is only monitored (Monitoring page); it has no
  config to back up.

The tiles at the top count each status.

* **Backup now:** back up one device straight away (needs **Backups: run**).
* **History:** every config version, when it changed, and what changed (needs
  **Backups: configs**, because configs contain password hashes and keys). You can view
  or download any version.
* A failed device is tried again automatically, sooner than its normal schedule.
* **Compliance:** the rules every config is checked against, what fails and since when
  ([compliance.md](../compliance.md)). A device that fails a rule shows **⚠ N compliance
  rule(s)**; its **History › Compliance** tab lists them.
* **Ports** (needs **Circuits: view**): the device drawn as a faceplate, each port coloured
  by what is on it: its circuit is there, its circuit isn't there any more, a circuit from
  another port is there, in use but not in the circuit list, or an uplink. Click a port for
  its circuits and the MAC addresses (and IPs) seen on it. It comes from the last network
  scan: no device is contacted. Also from the Inventory and an item's form.

## Inventory

Everything on the network in one list, not only the devices the tools manage: servers,
racks, UPSs, PDUs, patch panels and so on.

* **Managed** rows are the devices the tools back up and check. Their model, serial
  number and version come from the device (shown in grey). **Inventory only** rows are
  just recorded.
* Search any column, filter by type, site, status or managed, and click a name to see or
  change the details.
* **Columns**: choose which columns you see and their order (remembered for you).
* **Site**: from the list's Site column, else from the circuit's switch. Filter by site, or
  click it to open the site.
* **CSV** / **Excel**: export everything. **Import** (needs *Devices and credentials:
  manage*) shows what would change before it changes anything.
* **Blank template**: a sheet with just the column names (the ones you see, or all), to
  fill in and import.

More: [inventory.md](../inventory.md).

## Sites

The list of your sites (data centres, offices, branches...) and what the inventory has at
each one. An item is at a site when its *Site* is the site's name or code.

* Counts per site: items, managed devices, backups failing, firmware behind, circuits.
  Click a name or a count to see the site's details and everything at it; the circuits
  count opens the Circuits page for that site.
* A site name anywhere (Config backups, Firmware, Inventory, Circuits) is a link to it.
* A note above the table lists sites the inventory uses that aren't on the list yet.
* **Columns**, **CSV** / **Excel**, **Blank template** and **Import** work as on the
  Inventory page. Changes need *Devices and credentials: manage*.

* Click a site's name for its page: its **buildings, floors and rooms** on the left, and
  the **racks** of the place you pick, front and rear, with every item where it is. Drag an
  item to move it (needs *Devices and credentials: manage*); **Print** for a site visit.
* **Network map** (on the Sites page, or a site's page) draws how the devices are connected,
  from the CDP/LLDP neighbours found at the last network scan: devices at other sites and
  routers not in the inventory on top, then each hop further down. Click a line for its ports
  and a box for the device; drag boxes and **Save layout**; **Download** a picture. More:
  [circuits.md](../circuits.md#network-map-topology).

More: [sites.md](../sites.md), [racks.md](../racks.md).

## Firmware

* **Versions:** for every device, its model, serial, software version, boot mode and free
  flash, compared with the approved **standard**:
  * **on standard**;
  * **behind**;
  * **ahead**;
  * **no standard set**.

  **Check now** reads one device again. **Export CSV** gives you the whole report.
* **Standards:** the approved version for each platform and model, for example `C9300-*`.
* **Image library:** the firmware images, with their MD5 and SHA-512 checksums. Images are
  downloaded from the vendor by your team and uploaded here. The server never downloads
  anything.

## Upgrade jobs

Every upgrade goes through a job: the same checks and steps every time, and a full record
of who did what and why.

1. **New upgrade job:** choose:
   * the device;
   * the image (only images for its platform and model are offered);
   * the upgrade path;
   * **dry run** or **live**;
   * the change reference and the window.
2. **Run pre-checks** any time before the window. They log in and check, among other things:
   * the version;
   * free space;
   * fans, power, temperature and alarms;
   * modules and the HA or stack state;
   * CPU and memory;
   * unsaved configuration;
   * why the device last restarted;
   * a recent backup.

   A failed blocker stops the job until it is fixed, or overridden with a reason.
3. **Stage image** (optional): copies the image to the device and checks its checksum
   there. Nothing is reloaded.
4. **Start** in the window. For a live job, type the device name to confirm. The steps
   run one by one, and the **post-checks** compare the device with how it was before:
   interfaces, neighbours, port-channel members, modules, and the circuits seen on its ports.
5. **Stop after this step** pauses safely between steps. A reload is never interrupted.
   If post-checks fail, you can fix and re-check, override with a reason, or **Roll back**.

* **Report:** a printable record of the job, for the change ticket.
* **Dry run:** does everything except the changes, which it lists as "DRY RUN - would …".
  Use it to rehearse.

Details per platform: [upgrades.md](../upgrades.md).

## Circuits

The master circuit list: every end device or service and the switch port it uses.

* **Upload spreadsheet** (needs **Circuits: manage**), Excel or CSV: you see a preview of
  what's new, changed and removed before you make it the live list. Your own list works in
  any layout: if its column names aren't known, you say which column is which (only the MAC
  or IP address is needed), and the layout is remembered for next time.
* **Found on the network**: devices plugged into switch ports that aren't on the list, with
  their IP, VLAN, port and what they say they are (LLDP/CDP). Tick them and **Add selected
  to the list**, or download them as a spreadsheet to fill in. A switch's **Ports** view has
  **Add to the circuit list** on ports in use that aren't on the list.
* **Blank template**: a sheet with just the column names (the ones you see, or all), in
  the form the upload reads. MAC and IP address are always in it.
* **Columns**: choose which columns you see and their order (remembered for you).
* **Site**: from the list's Site column, else from the circuit's switch. Filter by site, or
  click it to open the site.
* **On the network:** where each circuit was really seen in the switches' MAC and ARP
  tables:
  * **Matches the list**;
  * **Moved**;
  * **Found**;
  * **Not seen**;
  * **Several ports**.
* **Scan network now** reads the tables straight away. Otherwise they are read on the
  schedule an admin sets, and at every upgrade.
* **Exports:** the list as CSV, or an updated spreadsheet with the switch and port taken
  from the network.

Upgrade jobs save the circuits on the device before and after, and warn about any that
haven't come back. Details: [circuits.md](../circuits.md).

## Monitoring

Which devices are up, which are down, and which need a look. Every device is checked once a
minute with ping and SNMP; the server only asks, it never changes anything.

* **The tiles** count the devices **Down**, with a **Warning**, **Up**, in **maintenance** and
  **Not monitored**. Click one to show only those. The list puts the worst first.
* **Down:** no answer to ping or SNMP for two checks in a row (about two minutes).
  **Warning:** it answers, but something needs a look; the *Note* says what (SNMP fails, no
  reply to ping, a missed check). **maintenance:** in a calendar window or an upgrade, so
  nobody is emailed about it.
* **Each row:** response time, how long the device has been up (it restarted then), how
  many checks it answered in the last 7 days, and since when it has been in its status.
* **Click a device** for its response-time graph (6 hours to a year: the line is the
  average, the band the worst, red marks the checks with no answer), how many checks it
  answered over a day, a week, a month and a year, what it says about itself, and its
  events (down, back up, restarted, SNMP stopped or started answering).
* **CPU · memory** in the list, with a red **hardware** badge when a fan or power supply has
  failed, a temperature is too high, or CPU or memory is over the threshold. The
  **Hardware problems** tile and list show every device with one.
* **Health**, in the device window: CPU and memory with their graph, and every temperature,
  fan and power supply with its status. Also the switches in a **stack** and the units of an
  **HA pair** (firewalls) with their role, the **optics'** light levels and the **PoE**
  power used. A switch dropping out of its stack, an HA peer lost, an optic's light past its
  limit or a PoE budget nearly used up shows as a hardware problem. A change of active
  switch or firewall is a **Failover** event, emailed like a device going down.
* **Sensors** your admins added (a UPS, BGP peers, firewall sessions…) are in the same
  Health table (Part: *Sensor*); click one for its graph. One past its threshold makes the
  device a warning, like a failed fan. With Monitoring *manage* you can add them yourself:
  **Sensors** on the Monitoring page, with a step-by-step guide in the window.
* **Interfaces**, in the device window: every port with its description, status, speed, how
  full it is, traffic in and out, and errors and discards a minute. You can sort it busiest
  first, errors first or down first. Click a port for its traffic graph (the dashed red line
  is its speed).
* **Busiest ports** and **Ports with errors or discards** under the list cover every device.
* **Last 24 hours** under those: everything that went down, came back or restarted, and
  described ports that went down or came back.
* **Network map:** the devices coloured green (up), orange (warning) and red (down). The
  lines are coloured by load: orange from 50%, red from 80%. Click a line for the traffic at
  both ends.
* **Meraki** (if your admin connected it): every Meraki device with its status from the
  Meraki dashboard (**online**, **alerting**, **offline**, **dormant**), its network, model,
  addresses and firmware, and each MX's internet uplinks. Firmware upgrades scheduled in
  Meraki are listed under it and on the **Calendar** ("Meraki upgrade"; change them in the
  Meraki dashboard). **Add to the inventory** puts the Meraki devices in the inventory.
* With *manage*: switch monitoring, ping or SNMP off for a device (its window, or tick
  several and use the bar above the list). **SNMP profiles** and **Help: set up devices**
  (the SNMP config for each platform) are for admins; see [monitoring.md](../monitoring.md).

## Calendar

Planned work in one place: every upgrade job's window (shown to people who can see upgrade
jobs) and the changes, maintenance, outages and change freezes people add.

* **Month** shows the weeks (Monday first, in your browser's time); **List** shows the next
  60 days with sites, devices, change references and clashes. **Every site** narrows it to
  one site (items for every site stay).
* **⚠ Clashes** are outlined in red:
  * two items at the same time on the same device, or at the same site;
  * anything at a site during a change freeze there (a freeze with no site ticked covers
    every site).

  Click an item to see what it clashes with.
* **+ Add** (needs *Devices and credentials: manage*): what, kind, change reference, start
  and end, the sites (none ticked: every site) and, optionally, the devices. Click an item
  to **Edit**, **Copy** (a new one like it) or **Delete** it. Upgrade jobs open their job
  window; change them on the Upgrade jobs page.
* **Download .ics** saves the period shown for Outlook, Google or Apple Calendar.
* Everything added, changed or deleted is in the activity log.

## Syslog

The devices' log messages, in one place: the first place to look when something goes wrong.

* **Period:** the last 15 minutes to 30 days, or *Choose the period…* for exact times.
  Click a bar in the **timeline** to look at just that slice of time.
* **Device:** one device, or *Senders not in the inventory*. Click a device name in the
  list to see only that device. On **Config backups**, a device's **Logs** button does the
  same.
* **Severity:** the buttons show how many messages there are of each, from Emergency to
  Debug. Click one to hide or show it, or use **Errors and worse** or **Warnings and worse**.
* **Search:** any text in the message, or its code: `%LINK`, `BGP`, `Gi1/0/14`, `%ASA-4`.
* **Live:** shows new messages every 5 seconds.
* **Download .log:** what you are looking at, as a plain text file (oldest first).
* **Help: set up devices:** a suggested config for each kind of device, with the
  server's address filled in, ready to copy.

Times are shown in your computer's time zone, by when the server received the message.
Hover over a message to see the whole line as the device sent it.
