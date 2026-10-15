# Project progress

The single place to see where Networking-tool-kev is and what's next. Update it at the end
of every working session.

**Now:** NetCairn (named 2026-10-14; it started as a clean copy of NetOps Tools): config
backups and compliance, firmware and upgrade jobs for every platform, circuits with live
locations, syslog, device monitoring (ping and SNMP: up/down, response times, restarts,
interfaces and traffic, map lines by load, hardware health, custom SNMP sensors; Cisco
Meraki through its Dashboard API),
inventory, sites, racks and the network map, the calendar, search, alerts, reports, the wall
display, users with two-factor sign-in, licences and the installers.
**Next:** the owner's to-do list below: test in the demo, lab tests on real devices, the full
install test on Ubuntu, then clearing the name and the licence terms.

## Roadmap

### Multi-vendor ([plans/multi-vendor.md](plans/multi-vendor.md))
- [x] PR A: Arista, Juniper, Fortinet, Palo Alto, Check Point, Aruba (CX, ProCurve, AOS 8 controllers), Dell OS10, Extreme, Cisco IOS-XR and SMB, MikroTik, Ubiquiti EdgeOS, Huawei: backup, versions, circuits ([vendors.md](vendors.md)). Readers built from vendor docs: check each on a real device (lab tests 7b)
- [x] PR B: upgrade drivers for Arista (+MLAG), Junos (+Virtual Chassis), ArubaOS-Switch, Aruba AOS 8, Dell OS10, EXOS, Huawei VRP, IOS-XR, MikroTik, EdgeRouter ([upgrades.md](upgrades.md#paths-per-platform)); lab tests section 9
- [ ] Later if needed: Junos NSSU and SRX clusters; Dell VLT and Aruba controller cluster paths
- [x] PR C: FortiGate (standalone, HA cluster) and PAN-OS (standalone, HA pair), image sent through their API ([upgrades.md](upgrades.md#paths-per-platform)); lab tests section 10

### Product
- [x] Per-customer settings: customer or site name (header, reports) and day-to-day defaults on the Settings page; safety gates stay in `netops.env`
- [ ] Product name and branding (GUI title, logo, docs). The name is now one setting,
  `NETOPS_PRODUCT_NAME`, default **NetCairn**; the cairn logo is the browser icon and is on the
  sign-in page, top bar and wall display ([branding/](branding/README.md)). Still to do: clear
  the name (owner), then perhaps rename the internal names (`netops` service, `NETOPS_`)
- [x] Licence modules: the licence unlocks tools (backups, firmware, upgrades, circuits, syslog); locked tabs greyed out ([licensing.md](licensing.md))
- [ ] Licence terms: draft agreement in [legal/EULA-draft.md](legal/EULA-draft.md); decisions listed at its end, then a solicitor's review
- [x] Owner: make the licence signing key and commit its public key (2026-10-15; in 2.2.0) ([licensing.md](licensing.md#one-time-make-the-signing-key))
- [x] First-run setup screen (admin account, AD settings, certificate) instead of editing `netops.env`; AD and the certificate stay on a Settings page for admins
- [x] Installer for internet-connected and air-gapped sites (`deploy/install-online.sh` builds and installs the same bundle on the server; [install-online.md](install-online.md))
- [x] Customer documentation: install guide, admin guide, user guide ([customer/](customer/README.md))
- [x] Licence keys: 60-day trial, signed licences (end date, devices, optional installation), read-only for new work without one ([licensing.md](licensing.md))
- [x] Wall display for NOC screens: overview and upgrades pages, own port (8443), per-screen links ([customer/admin-guide.md](customer/admin-guide.md#wall-displays))
- [x] Security review of the whole product, with fixes (see the session log of 2026-10-12)
- [x] Syslog: a central receiver (UDP/TCP 514) with a search page (device, severity, period, text, timeline), retention by days and size, suggested device configs per platform, demo messages ([syslog.md](syslog.md))
- [x] Network inventory: every device plus anything else (racks, servers, UPSs…), admins' custom columns, per-person columns, import/export ([inventory.md](inventory.md))
- [x] Circuit list like the inventory: admins' custom columns (read from uploads by name), per-person columns, CSV uploads, blank templates ([circuits.md](circuits.md)); blank templates for the inventory too
- [x] Sites: the list of sites with counts of items, devices, failing backups, firmware behind and circuits; circuits linked to sites; site names are links on every page; site detail with everything at the site; custom columns, import/export, blank template ([sites.md](sites.md))
- [ ] Full install test on Ubuntu (owner, after the demo)
- [x] Site layout (buildings, floors, rooms) and rack elevations: front and rear, zero-U, half depth, drag to move with overlap checks, print ([racks.md](racks.md))
- [ ] Site plans: a floor plan picture per floor, rooms marked on it to click into (owner: after the layout)
- [x] Config change alerts: what changed and who changed it (from the device's syslog); changed lines optional, secret-like lines never
- [x] Config compliance: must / must not rules per platform and site, checked after every backup, Compliance view, device tab, alerts, CSV ([compliance.md](compliance.md))
- [x] Switch port view: a faceplate per device from the last scan and the circuit list ([circuits.md](circuits.md#a-switchs-ports))
- [x] Report: Activity › Report, and emailed on a day and time to the recipients of "Report"
- [x] Wall display: compliance and config changes tiles, Sites and Network pages, pages chosen per screen
- [x] Health checks and before/after comparison for NX-OS, ASA, Arista, Junos, ArubaOS-Switch, AOS 8, Dell OS10, EXOS, Huawei, IOS-XR, AlliedWare Plus, MikroTik and EdgeOS: environment, alarms, modules/stack, CPU, memory, unsaved config, last restart; interfaces, neighbours, LAG members and modules compared after ([upgrades.md](upgrades.md#the-checks)). Readers from vendor docs: confirm each with a capture (lab tests section 9)
- [x] Search box in the top bar: devices, inventory items, sites, circuits, and MAC/IP addresses from the last scan, by permission and licence ([customer/user-guide.md](customer/user-guide.md#search))
- [ ] Later: config search across all backups and side-by-side diff of any two backups
- [ ] Later: Teams and Slack messages alongside email
- [ ] Later: a layout for phones
- [x] Maintenance calendar: upgrade job windows plus changes, maintenance, outages and change freezes; clashes (same device or site at once, work in a freeze) flagged; month and list views; .ics download ([customer/user-guide.md](customer/user-guide.md#calendar))
- [x] Two-factor sign-in: authenticator-app codes for users on the Users page (local and AD), compulsory for local users by a setting, recovery codes, admin reset, the break-glass admin from netops.env ([users.md](users.md#two-factor-sign-in))
- [x] Network map (topology) per site and for every site, from the CDP/LLDP neighbours kept at each network scan; drag and save layout, download as SVG ([circuits.md](circuits.md#network-map-topology))
- [x] Monitoring phase 1: ping and SNMP (v2c, v3) every minute from its own service (`netops-monitor`); up, warning, down, restarts and SNMP trouble as events; response-time graphs and availability; SNMP profiles with a Test button; per-platform SNMP configs (Help: set up devices); map colours, wall display page, email alerts, calendar windows as maintenance ([monitoring.md](monitoring.md))
- [x] Monitoring phase 2: interfaces (status, speed, traffic, errors, discards) read every 5 minutes with SNMP; each reading kept 7 days, hourly average and peak 13 months; traffic graphs per port; busiest ports and ports with errors (page and wall); map lines coloured by load; described ports going down or up as events and alerts ([monitoring.md](monitoring.md))
- [x] Monitoring phase 3: hardware health per vendor (CPU, memory, temperatures, fans, power supplies) from each vendor's MIBs and the standard ones, readers remembered per device; problems make a warning, an event and an alert; device window, list column, Hardware problems tile and list, wall display ([monitoring.md](monitoring.md#hardware-health)). Readers from vendor MIB docs: confirm each platform in the lab
- [x] Meraki through the Dashboard API (owner, 2026-10-14; built 2026-10-14): connections per organisation with an encrypted read-only key, devices and status (online/alerting/offline/dormant), MX uplinks, scheduled firmware upgrades on the page and the calendar, events and alerts, wall panel, add to the inventory by serial; needs outbound HTTPS (firewall `MERAKI_HOSTS` or `https_proxy`). Not yet: per-uplink loss and latency, the Meraki event log, Meraki devices on the network map. Lab: try it against a real organisation
- [x] Custom SNMP sensors (owner, 2026-10-14; built 2026-10-15): any OID as a value, a rate or a state code, single or a table column, warning/critical thresholds, for a platform, a site or chosen devices; Test button; read with the health, so graphs, warnings, events, alerts and the wall come with it; 15 examples (UPS-MIB, APC PowerNet, BGP, OSPF, FortiGate, Palo Alto, ASA, IPsec, port errors, room temperature) and a step-by-step guide in the window and in monitoring.md. Lab: try the examples on real devices
- [x] SNMP-only device types (owner, 2026-10-15; built 2026-10-15): UPS, PDU, environment probe and other SNMP device platforms with no credential, no backups, version checks, scans or upgrades; monitored with ping, SNMP and sensors (the UPS and room probe examples scoped to them); SNMP and syslog setup help for each; demo UPS, PDU and a warm room probe. Lab: an APC NMC and an Eaton card
- [x] Licence editions and selling (owner, 2026-10-15): Essentials (backups, syslog), Professional (+ firmware, upgrades, circuits), Complete, Monitoring add-on; per device per year in bands 50/250/1,000/unlimited; UPS cards, PDUs and probes count as one device each; each Meraki organisation counts as 25 devices; Stripe for payment; the ledger and the download bundles in the owner's OneDrive; licence_tool editions, ledger and renew `--from` (docs/selling.md)
- [ ] Owner: set up the Stripe products and prices (per edition and band, Stripe Tax, Invoicing); signing key and OneDrive folders done (2026-10-15). 2.2.0 is the first version that accepts licences
- [ ] Owner: on the PC, a GitHub read-only token and the release sync script (`deploy/windows/Sync-NetCairnRelease.ps1 -SetToken`, then `-Register`; docs/releasing.md)
- [ ] Check the first automatic bundle build (ubuntu:26.04 container on GitHub) and install it on a lab server
- [ ] Later: a customer portal (Stripe payment makes the licence, the key in a key vault; customers download licences and bundles)
- [ ] Built-in UPS health (UPS-MIB and APC PowerNet readers as hardware health, so a UPS on battery is a problem without adding sensors), if the sensors prove too manual
- [x] Versioning (owner approved 2026-10-15): 2.MINOR.PATCH; 2.0.0 = main after Meraki and sensors (tag v2.0.0); VERSION file (next release, now 2.1.0) shown after sign-in, in the report and `netops-cli version`; bundles named by version (`-dev.<date>.<commit>` between releases); installer says "Upgrading from … to …" and refuses older versions; CHANGELOG.md; release steps in docs/releasing.md
- [x] Stacks, HA and optics (owner, 2026-10-15; built 2026-10-15, for 2.1.0): Cisco StackWise members, ASA failover, FortiGate HA, Palo Alto HA, failover events and alerts, Cisco optics (dBm, the transceiver's own thresholds, only on ports that are up), PoE budget (any vendor). Lab: a Cisco stack, an ASA pair, a FortiGate cluster, a PA pair, an optic with DOM
- [ ] Next for optics and stacks: Juniper (DOM, Virtual Chassis), Arista and Aruba optics, HPE/Aruba and Dell stacks
- [ ] SNMP ideas, not started (sensors cover some by hand today): wireless controllers (APs joined, clients); built-in BGP/OSPF neighbour checks with names
- [ ] NetFlow, only if the owner asks (2026-10-14 overview given): a collector (nfcapd/nfdump or similar) on UDP 2055, top talkers per interface and site; challenges are the data volume (GBs a day on busy sites), device config and sampling, NAT hiding hosts, and personal data (GDPR) in flow records
- [ ] Later: Schneider EcoStruxure Building Operation (EBO), likely through EBO Web Services (EWS); the owner is to come back to it. Today: monitor its servers and automation servers with ping/SNMP as devices
- [ ] Idea: UPSs with network cards (APC/Schneider PowerNet-MIB): on battery, battery health, load and runtime, as part of health
- [ ] Main and standby server: two VMs (one DC or across a campus), one active at a time with the database and configs copied to the standby and a shared address; only the active one polls, receives syslog and runs jobs; the licence covers the pair
- [ ] Later: site collectors for cloud or many-site use (owner, 2026-10-14: "sounds better"): a small collector at each site does the polling, syslog, backups and upgrades locally and keeps that site's device passwords (encrypted so the centre can't read them); it connects out over HTTPS (its own certificate) to a central server with the global view, users, inventory, reports and alerts; jobs wait at the centre for the collector to fetch; images copied to collectors overnight and pushed locally in the window; keeps working while the link is down. One central install per customer
- [ ] Later: one overview of several servers (the display feed is the starting point); several customers on one server kept as an idea

### Platform (inherited)
- [x] Core: AD and local login, per-area permissions, device inventory, encrypted credentials, audit and activity report
- [x] Air-gapped install kit, hardening guide and templates, nightly backups
- [x] GitHub Actions: run the tests on every pull request (Python 3.11 and 3.14)
- [x] Database migrations (Alembic): applied at start, copy kept first, installer restores it on a failed upgrade

### Tools (inherited)
- [x] Config backup
- [x] Firmware: version report, standards, image library, upgrade jobs for every platform
- [x] Circuits: Excel import, live location from MAC/ARP tables
- [ ] Lab-test the upgrade paths and the MAC/ARP parsing ([upgrade-lab-tests.md](upgrade-lab-tests.md))
- [x] Email alerts through the customer's mail server: failing backups, upgrade results, licence, upgrade worker ([customer/admin-guide.md](customer/admin-guide.md#email-alerts))
- [x] Demo mode: `python -m app.demo`, the product on a simulated 25-device network ([demo.md](demo.md))
- [x] Lab capture: `netops-cli capture <device>` saves every read-only command's output, with what the tools read from it ([upgrade-lab-tests.md](upgrade-lab-tests.md#capturing-a-device))

## Decisions

| Date | Decision | Why |
|---|---|---|
| 2026-10-07 | Separate repository from the work version, started from a clean copy without history | Product and work tool evolve independently |
| 2026-10-07 | No PRTG integration; monitoring through `/api/health` and syslog forwarding | Customers use different monitoring systems |
| 2026-10-07 | Product name comes from `NETOPS_PRODUCT_NAME` (default "NetOps Tools"); messages say "inventory" instead of naming the product | Name not chosen yet; renaming or rebranding for a customer is a setting, not a code change |
| 2026-10-07 | Readers for the new vendors are built from vendor documentation, with samples in `tests/vendor_samples.py` | No lab kit yet; each is checked on a real device (lab tests 7b) and its sample replaced |
| 2026-10-07 | FortiGate backups mask `ENC` secrets | FortiOS re-encrypts them on every show, so every backup would look changed; full restores use FortiGate's own backup |
| 2026-10-07 | `ubiquiti_edgeos` is EdgeRouter only (Netmiko `ubiquiti_edgerouter`) | EdgeSwitch has a different CLI; UniFi needs its controller API |
| 2026-10-07 | New drivers share `drivers/common.py` (copy, check by MD5 or size, set boot, save, reload) | Ten platforms follow the same pattern; each driver only says what differs |
| 2026-10-07 | A post-check fails when the version could be read before the upgrade but not after it | Before, an unreadable version let the post-check pass |
| 2026-10-07 | MikroTik roll back is by hand | RouterOS keeps no copy of the previous release |
| 2026-10-07 | Upgrade jobs only for devices whose image can be sent from the server (SSH/SCP or the firewall's own API); AOS-CX and Cisco small business keep backups, versions and circuits only | The owner: the tool is for large production networks managed over SSH; nothing is built for devices to pull images |
| 2026-10-07 | FortiGate and PAN-OS get the image through their management API (pinned certificate, like FDM); everything else over SSH | They can't receive a file over SSH; the API upload is a push from the server |
| 2026-10-07 | FortiGate REST API token kept in the credential's enable secret (optional) | No database change needed; FortiOS has no enable mode |
| 2026-10-07 | Check Point upgrades stay in SmartConsole / Central Deployment; the tool does backups, versions and ARP for Check Point | Upgrading from the tool would need an expert-shell account on every gateway; production sites already upgrade from the management server |
| 2026-10-07 | The app uses port 8710 everywhere (`NETOPS_PORT`, `python -m app`, Docker, systemd/nginx) | 8000 clashes with other local tools the owner runs |
| 2026-10-07 | Alembic migrations run automatically at start (locked, database copied first); new databases are created from the models and marked current; old installs are marked as the baseline | No manual step for engineers installing an upgrade; a failed upgrade can always go back |
| 2026-10-08 | The setup screen needs a one-time setup code read from the server (`/var/lib/netops/setup-token`); installs that already have an admin or AD in `netops.env` skip setup | Between install and setup the page is open to anyone on the network; the code proves the person has the server |
| 2026-10-08 | The app only proposes a certificate; a root path unit checks it and installs it for nginx, keeping the old one if `nginx -t` fails | The app stays without root and can't write to `/etc` or reload nginx |
| 2026-10-08 | AD settings from the GUI are stored in the database (`app_settings`); a value in `netops.env` wins and is shown as locked | Existing installs keep working unchanged; a site can still keep AD settings root-only |
| 2026-10-08 | A first install starts the services with a 30-day self-signed certificate | The setup screen needs HTTPS before a real certificate exists |
| 2026-10-08 | The Settings page holds the site name and day-to-day defaults; live upgrade platforms, the break-glass admin, ports and secrets stay in `netops.env` | Admins tune their site without root; switching on live upgrades still needs someone with root on the server |
| 2026-10-08 | Licences are signed text checked on the server (Ed25519); no activation server | Air-gapped sites must work the same way |
| 2026-10-08 | A licence sets an end date and a device count; a new install gets a 60-day trial | The owner's choice: yearly subscription priced by network size; long enough to test an upgrade in a change window |
| 2026-10-08 | Without a valid licence only new work is blocked (adding devices, planning and starting upgrades); backups, checks, viewing and jobs under way go on | A customer's network is never left without backups, and a device is never left half-upgraded |
| 2026-10-08 | No bypass login or setting; the owner uses an internal licence, and `python -m app` is development mode | A hidden bypass could be found in the shipped code |
| 2026-10-08 | The online installer builds the air-gapped bundle on the server and runs the same `install.sh` | One install, upgrade and roll-back path to test and support; the bundle doubles as the record for the change ticket |
| 2026-10-09 | No remote collectors: devices are reached over SSH from the server inside each company's network | The owner: production sites can reach their devices from a central management server |
| 2026-10-09 | Several customers on one server is kept as an idea, not built | Not needed while each company runs its own server |
| 2026-10-09 | A read-only wall display on its own port (8443) with a per-screen key, rather than a signed-in session | A wall screen can't sign in every few hours; the separate port and key let the firewall and admins limit it to the screens |
| 2026-10-12 | Email alerts look at the state every minute and send each event once, rather than being sent from inside each tool | One place to switch alerts on and off; events from the worker process are covered too; a failed send is simply tried again |
| 2026-10-12 | SSH host keys are trusted on first use and then checked; only an admin can forget one (device edit dialog, audited) | Devices have no central key list to load; a device answering with another key never receives a password |
| 2026-10-12 | Sign-ins last at most `NETOPS_SESSION_MAX_AGE_HOURS` even while in use; a break-glass session ends when its password changes | A stolen cookie or a forgotten browser stays useful for a limited time only |
| 2026-10-12 | Root scripts never act on files the app account can change (TLS status in `/var/lib/netops-tls`, backups copied as `netops`, online installer only from a root-owned clone) | The app account must not be a way to root |
| 2026-10-12 | Spreadsheet exports keep formula-like text as text | Text from sign-in names, uploaded sheets and device output ends up in exports opened in Excel |
| 2026-10-12 | Devices and credentials gets two more levels: *addresses* (add devices, change a device's address or credential profile) and *credentials* (manage the profiles); *manage* keeps only device details | The owner: whoever sets the address decides where a device account's password goes, so it is given per user on the Users page |
| 2026-10-12 | The network simulator and sample outputs moved from `tests/` to `app/demo/` (tests keep the old names) | One simulator for the tests and the demo, so the demo shows exactly what the tests check |
| 2026-10-12 | Captures replace IP and MAC addresses with consistent stand-ins by default, and never include the running configuration | Captures are sent outside the customer's network for parser fixes; the tables still match up, so the readers can be tested |
| 2026-10-12 | Syslog is kept in one SQLite file per day, written only by its own receiver service | Quick search by device, severity and time; old days go by deleting files; the web app can restart without losing messages |
| 2026-10-12 | The syslog sender is the packet's source address, matched to the inventory; the server never changes device logging itself (configs are suggested on a Help page) | The host name in a message can be anything; device changes need an admin |
| 2026-10-12 | Syslog files stay out of the nightly server backup | The owner: the backup is fine as it is; a standby server with copies is the plan for later |
| 2026-10-12 | Email alerts: each recipient ticks the kinds they get (backups, upgrades, licence, worker, syslog); syslog alerts at Critical and worse by default, at most one email every 5 minutes | The owner asked for syslog alerts to be optional per recipient; a storm of messages must not become hundreds of emails |
| 2026-10-12 | The circuit list is compared with the network every night at 03:00 by default (was Sundays 02:00) | The owner: nightly, late at night |
| 2026-10-12 | Syslog over TLS (6514) is built in, off by default, switched on in netops.env; it reuses the web certificate through systemd LoadCredential, with optional device certificates | The owner: syslog may cross other networks; a port is a netops.env setting, and the key must stay root-only |
| 2026-10-12 | One full install; the licence lists the tools it unlocks (backups, firmware, upgrades, circuits, syslog); one licence per customer, replaced to add a tool | The owner: unlock parts of one product rather than separate products; one licence keeps one end date and one device count |
| 2026-10-12 | The inventory is one list (table `assets`): managed rows are linked to devices, inventory-only rows aren't and don't count for the licence | Everything in one place, and the tools keep working from `devices` |
| 2026-10-12 | Admins add custom columns for everyone at the site; each person chooses and orders the columns they see (kept in their browser) | The owner: every customer's inventory is different |
| 2026-10-12 | Ubuntu only: no Windows or Mac builds or installers of the full product (the demo still runs anywhere Python does) | The owner: the product is deployed on Ubuntu servers |
| 2026-10-12 | Circuit list custom columns are text, read from uploads by their name; a header row with only known names is accepted (a blank template with few columns) | Circuit lists come from spreadsheets; checks belong in the sheet, and a template must import whatever columns were chosen |
| 2026-10-12 | A circuit's site is the list's Site column, else its switch's site, else the site of the switch it was found on (migration 0008) | The owner: circuits linked to sites, "everything linked through"; most lists have no site column, and the switch's site is right for them |
| 2026-10-13 | Sites are divided into buildings, floors and rooms (a room may sit straight in a building); items are placed by their Building/Floor/Room text, an item in a rack where its rack is | The owner: any site, not one design; text keeps imports and exports working, like Site |
| 2026-10-13 | Config change emails never hold a line that may be a secret; compliance results show config lines only to `backups:configs`; the wall display never shows syslog text | Emails and screens travel further than the GUI; syslog text can hold addresses |
| 2026-10-13 | The switch port view is built from stored scans and the circuit list, not by contacting the device | No new device commands to approve; it works the same in the demo and offline |
| 2026-10-13 | Rack positions are the item's lowest U; full depth fills front and rear, half depth one face; height 0 is zero-U | The usual rack convention; patch panels share a U front and rear |
| 2026-10-13 | Health checks for the other platforms live in one table per platform (`firmware_upgrade/health.py`: commands and a reader per check); the snapshot uses the IOS keys (`interfaces`, `lldp`, `etherchannel`) so one comparison serves every platform | Adding or fixing a platform is one table, checked against a capture; the post-check rules stay the same everywhere |
| 2026-10-13 | `show reload cause`, `show reboot history` and `display reboot-info` are allowed by exact name in the capture's read-only check | They are read-only but contain words the check refuses; listing them exactly keeps every other "reload"/"reboot" command refused |
| 2026-10-13 | No upgrade campaigns (many devices in waves), no end-of-life or warranty tracking, no scheduled daily health check for now | The owner: campaigns have no place in production; the daily health check to be looked at another way later |
| 2026-10-13 | The search box only reads what is stored (inventory, sites, circuit list, the last scan); it never contacts a device, and each group is shown by the page's permission and the licence | Fast, safe, and nobody sees through search what their pages hide |
| 2026-10-13 | The calendar is part of every licence; anyone signed in sees it, *Devices and credentials: manage* adds and changes items; upgrade jobs show only to people who may see jobs and are changed on the jobs page | Planned work is for everyone to see; who may plan matches who may edit devices; no new permission area |
| 2026-10-13 | Clashes: overlapping times and the same device, or the same site (an item for every site clashes with any site's item); anything at a site during a freeze there; two freezes never clash | The checks engineers do by hand before a CAB |
| 2026-10-13 | Two-factor sign-in uses standard authenticator-app codes (TOTP, RFC 6238), checked in our own code; the QR code is drawn on the server with `segno` (one pure-Python wheel, no dependencies, added to requirements and so to the offline bundle) | Works with every phone app, on air-gapped sites, and nothing is sent outside |
| 2026-10-13 | Two-factor is for users on the Users page (local and AD); compulsory only for local users (a Settings option); the break-glass admin's secret lives in netops.env | AD users usually have MFA in their organisation already; the break-glass account must not depend on the database |
| 2026-10-13 | The network map is drawn from the neighbours kept at the circuit scan (table `ct_live_neighbors`, migration 0012), so it is part of the Circuits module and permission; no new device commands | The scan already reads CDP/LLDP on every switch for uplinks; keeping the names costs nothing and the map never contacts a device |
| 2026-10-14 | The product is called NetCairn (default `product_name`); internal names (`netops` service and account, `NETOPS_` settings, paths, `netops-cli`) stay | The owner chose the name; renaming internals needs an upgrade path for installed servers and can wait until the trademark is cleared |
| 2026-10-14 | Device monitoring is built in (Monitoring module): ping and SNMP from its own service (`netops-monitor`) into its own files (`<data>/monitoring/`, not Alembic), read by the web app, like syslog; the server's own health is still `/api/health` | The owner wants a monitoring wall like PRTG or SolarWinds; one writer per store keeps the web app fast and the checks running while it restarts |
| 2026-10-14 | No SNMP traps and no NetFlow; syslog stays the place for device messages | The owner: syslog is the network engineer's way to diagnose; traps duplicate it |
| 2026-10-14 | SNMP with `pysnmp` (pure-Python wheel, plus `pyasn1`; its encryption uses `cryptography`, already in the bundle); read-only (GET/GETBULK), never SET; ping through Linux ping sockets, so the service needs no capabilities | Works offline from the bundle, SNMPv3 with SHA-2 and AES, least privilege |
| 2026-10-14 | SNMP profiles are secrets like device credentials: managed with *credentials*, a device's profile chosen with *addresses*; Monitoring permission area none/view/manage (view for users made before it) | Same rule as credential profiles: who decides where a secret goes |
| 2026-10-14 | Calendar windows (change, maintenance, outage) and upgrade jobs under way mark devices "maintenance": events kept, not emailed | No alerts for planned work |
| 2026-10-14 | Interfaces: read every 5 minutes (64-bit counters where there are any); every reading kept 7 days in a file per day, then the hourly average and peak for 13 months in a file per month; whole files deleted, like syslog. Port events only for ports with a description, and port-channels | Graphs for a year without the store growing without limit; access ports going up and down all day would drown the real events |
| 2026-10-14 | Hardware health: each platform's vendor MIB readers, then HOST-RESOURCES and ENTITY-SENSOR for everyone; the readers that answered are remembered and all retried daily; the device's own status decides for fans, power supplies and temperatures, the Settings thresholds for CPU and memory; a problem makes the device a warning (not down) | Works across vendors without per-device setup; no false alarms from guessed temperature limits |
| 2026-10-14 | Meraki through its Dashboard API, on the to-do list; Schneider EBO later | The owner: Meraki looks after itself but its data belongs in the overall view |
| 2026-10-15 | Releases are published automatically: merging a "Release x.y.z" PR (a dated changelog heading) makes the tag and the GitHub release (release.yml, deploy/release.py); the tag goes on the commit that dated the heading, checked against its VERSION | The owner shouldn't have to tag by hand; a release always matches its changelog |
| 2026-10-15 | Selling: Stripe for payment and customer records; licences made on the owner's PC with licence_tool and recorded in a ledger CSV in the owner's OneDrive; bundles shared from OneDrive with a SHA-256; editions as named module sets; Meraki organisation = 25 devices | No servers to run yet; air-gapped sites keep working (offline licences); can grow into a portal later |
| 2026-10-15 | Stacks and HA as health readings with a role; a failover is a change of the active unit between reads (an event, not a problem); optics judged only by the transceiver's own thresholds and only on ports that are up; PoE warns at the device's own threshold, else 90% | No guessed dBm limits (they differ per optic type); unused ports with optics fitted would otherwise alarm all day |
| 2026-10-15 | Versions: MAJOR.MINOR.PATCH from 2.0.0, one VERSION file, a plain-words CHANGELOG.md, tags v2.x.y on main; the version is shown only after sign-in, never on /api/health or the sign-in page | The owner wants to say "upgrade to 2.x"; an exact version on an open page tells attackers what to try |
| 2026-10-15 | SNMP-only devices are platforms with `ssh=False` (no new table): no credential, no backup or version-check rows, so every SSH feature skips them by having no row | One device list and one inventory for everything; the existing pages, counts and alerts needed no special cases |
| 2026-10-15 | Custom SNMP sensors are health readings ("sensor" kind) read with the hardware health, not a separate store; thresholds are strict (below 1 = 0); a missing OID is "unknown", not a problem; the wall shows only the sensor's name | One history, problem, event and alert path for everything a device reports; table row labels (BGP peer addresses) stay off the wall |
| 2026-10-14 | Meraki is read by the monitoring poller through the Dashboard API (GET only, every 5 minutes, upgrades hourly), not SNMP; one connection per organisation; the key goes only to Meraki's own addresses; the only internet connection the product makes, and optional | Meraki's cloud already knows every device's status; SNMP to Meraki is limited and per-device; air-gapped sites simply don't use it |
| 2026-10-14 | Cloud or many-site design: per-site collectors connecting out to a central server (like PRTG remote probes), one central install per customer, after phase 2 and the main/standby pair | Device passwords stay at the site, no way into the sites from the centre, no VPN mesh, images staged locally |
| 2026-10-12 | Sites are a list of their own (table `sites`); items and devices keep a Site text, matched to a site's name or code; renaming a site rewrites that text | The owner: a site list cross-referenced with the inventory, without changing how devices and backups store their site |

## Open questions


**Owner's to-do, in this order (remind the owner each session):**
1. Testing of what is built: the demo (owner, 2026-10-13: "everything looks good so far"),
   now the Monitoring page (a switch down, a router with SNMP not set up, a firewall that
   drops ping; graphs, SNMP profiles and their Test button, Help: set up devices, the map
   colours, the wall display's Monitoring page; interfaces in a device's window, a port's
   traffic graph, the busiest ports and errors, the map's lines coloured by load; hardware
   health: hq-core2's failed power supply, wh-sw3's stopped fan, dc1-leaf2's high CPU), the site layout and rack elevations,
   compliance, the port view, the report and the wall display pages too ([try-it.md](try-it.md)); and an upgrade job's pre-checks on an
   Arista, Juniper or NX-OS demo device, which now show the health checks; the search box.
2. Full install test on Ubuntu ([install-online.md](install-online.md)), after the demo.
3. Product name: **NetCairn** (owner, 2026-10-14). The product, demo and logo use it
   ([branding/](branding/README.md)). Still to do by the owner: buy netcairn.ie, search the
   trademark registers, an attorney's clearance, then register the mark (see the session log).
   NetLantern and NetSteward were ruled out (too close to Spectrum's LANtern; the exact name of
   a US product).
   Earlier working name NetLantern (2026-10-14; NetSteward the alternative); the demo uses it and a draft logo is in [branding/](branding/README.md), with
   the second web check: Spectrum's **LANtern** (UK network monitoring) is close to NetLantern,
   and a small US firm sells a network monitoring platform called **NetSteward** (the exact
   name). Next: trademark registers, domains (.ie is free), a trademark attorney.
   Earlier check (2026-10-12):
   * ruled out: NetKeeper / NetKeeper Pro (live US trademark NETKEEPER, reg. 4944745, network
     management software), NetWeb (two companies), Backplane, Rackwise, Uplinq, Configra,
     Portwarden (existing products); NetKeep is close to the NETKEEPER mark (risky);
   * the owner likes NetLantern (no product found; "Lantern" is a known VPN tool, a
     different field);
   * looked clear: NetHarbour, OpsLedger, Netcairn, Wirebook, Switchkeep, NetSteward,
     Lanward, Netquay, Opsbay, Netvale;
   * still to do: domains (.com, .co.uk) and the UK/EU/US trademark registers, then a
     trademark attorney's clearance search.
4. Licence terms, editions and pricing: last.
5. Done (2026-10-15): the licence signing key (`python -m app.licence_tool keygen`), before the first
   customer licence.
6. Site plans (floor plan pictures), after the rack elevations are tried.
7. Lab testing on real devices (soon, by the owner).

- Licence agreement: per installation or per site? Managed-service use? Support terms, warranty, liability cap, governing law ([legal/EULA-draft.md](legal/EULA-draft.md))

- Product name?
- Editions: which sets of modules to sell, and their names and prices (any set works without code changes)
- Sites next steps: a map, or a site tile on the wall display?
- Syslog next steps: a wall display tile for Critical and worse messages?
- Later: two servers (main and standby) with copies of the data and the syslog files
- Syslog forwarding is plain UDP (`rsyslog-forward.conf`); offer TLS forwarding for sites whose log server supports it?
- Docker image: `--forwarded-allow-ips "*"` trusts any proxy's client address; fine behind the bundled nginx, but should it be narrowed?
- The air-gapped bundle has a SHA-256 but no signature; sign bundles once the product is sold?
- Licence model: sold, subscription, or open source with paid support?
- FortiGate backups: is masking the secrets acceptable, or should the backup use FortiGate's own encrypted backup file instead?
- Setup screen: also add product name, syslog forwarding or the upgrade live-platform list later, or keep those in `netops.env`?
- The migration fix (legacy installs now create only the baseline tables) also applies to the work version once it has migrations; copy it across?
- The AlliedWare Plus circuit-location fix (ports named `port1.0.x` were treated as port-channels) also applies to the work version; copy it across?

## Session log

| Date | Where | What happened |
|---|---|---|
| 2026-10-07 | Networking-tool-kev | Repository created from NetOps Tools (main @ 29e6bb1): PRTG removed, sample data made generic |
| 2026-10-07 | Networking-tool-kev | Tests run on every pull request (GitHub Actions); product name made a setting |
| 2026-10-07 | Networking-tool-kev | Multi-vendor PR A: 15 platforms for backups, version checks and circuit locations; vendor groups in the GUI; fixed AlliedWare Plus circuits never being located |
| 2026-10-07 | Networking-tool-kev | Multi-vendor PR B: upgrade drivers for 10 more platforms, tested on the simulator; post-check now fails when the version can't be read |
| 2026-10-07 | Networking-tool-kev | Multi-vendor PR C: FortiGate and PAN-OS upgrades (standalone and HA) through their APIs; shared pinned-certificate client; Check Point and pull-only switches left out by decision |
| 2026-10-07 | Networking-tool-kev | Decided: Check Point upgrades stay in SmartConsole |
| 2026-10-07 | Networking-tool-kev | Multi-vendor PRs A-C merged; app port 8000 replaced by 8710 for development and Docker (`NETOPS_PORT`) |
| 2026-10-07 | Networking-tool-kev | Alembic migrations added (baseline, startup upgrade, db-status, installer roll back of the database) |
| 2026-10-08 | Networking-tool-kev | First-run setup screen (setup code, admin, AD with test sign-in, certificate request or upload) and admin Settings page; root certificate service; installer starts the services on a first install; fixed legacy databases failing once a later migration adds a table |
| 2026-10-08 | Networking-tool-kev | Customer documentation (install, admin and user guides) and a draft licence agreement; open-source licences checked (no GPL; LGPL ldap3, paramiko, scp) |
| 2026-10-08 | Networking-tool-kev | Per-customer settings on the Settings page (site name, defaults), applied live in the web app and the worker; circuit scan follows the schedule setting |
| 2026-10-08 | Networking-tool-kev | Licence keys: trial, signed licences, Settings page and banner, signing tool; wrong setup codes are now kept in the audit log (they were rolled back) |
| 2026-10-08 | Networking-tool-kev | Online installer (`deploy/install-online.sh`), shared Ubuntu package list; tested end to end in an Ubuntu container (bundle built, verified and installed) |
| 2026-10-09 | Networking-tool-kev | Wall display: overview and upgrades pages rotating, own nginx site on 8443 (checked with a real nginx: refused on the main port, only the display there), per-screen links on the Settings page |
| 2026-10-12 | Networking-tool-kev | Email alerts (Settings › Email alerts, test email, sent once each, tried again after a failure); firewall template allows the mail relay |
| 2026-10-12 | Networking-tool-kev | Security review (sign-in, setup/licence/display, device access, deployment, browser): fixed a root escalation through the certificate status file, the sign-in throttle bypass, sign-in with a trusted domain's name, root git in the backup script, the online installer trusting a user's clone, unchecked SSH host keys, sessions that never ended, formula injection in exports, failed sign-ins missing from the activity report, and smaller upload and licence gaps |
| 2026-10-12 | Networking-tool-kev | Demo mode (`python -m app.demo`): 25 simulated devices, failing backups, circuits, live upgrades in about 40 s, wall display; sign-in now returns the site name (it only showed after a reload) |
| 2026-10-12 | Networking-tool-kev | Lab capture tool (`netops-cli capture`); blocks anything but read-only commands, including `| redirect` and `| tee` |
| 2026-10-12 | Networking-tool-kev | Syslog: receiver service on 514 (rate limit per sender, disk guard), daily store, Syslog page with severity buttons, timeline and download, Help with suggested configs for every platform, Logs button per device, demo history with BGP, PSU, failover, BPDU guard and brute-force incidents |
| 2026-10-12 | Networking-tool-kev | Email alerts per recipient, syslog alerts (Critical and worse, gathered), nightly circuit scan by default |
| 2026-10-12 | Networking-tool-kev | Syslog over TLS: third listener (6514), web certificate via systemd, optional device certificates, TLS examples in the device help, receiver restarted on a new certificate |
| 2026-10-12 | Networking-tool-kev | Licence modules: one install, the licence unlocks Config backups, Firmware, Upgrade jobs, Circuits and Syslog; locked tabs greyed out with a padlock; scheduled work and alerts follow the licence; signing tool --modules |
| 2026-10-12 | Networking-tool-kev | Network inventory: assets table (migration 0005), devices linked automatically with model/serial/version from the device, inventory-only items, Manage this device, admins' custom columns, per-person columns, CSV/Excel export, import with preview; demo inventory of 42 items |
| 2026-10-12 | Networking-tool-kev | Demo launchers (run-demo.bat / run-demo.sh), a try-it guide with a test checklist, the demo runs on Windows (no fcntl needed); product names checked on the web |
| 2026-10-12 | Networking-tool-kev | Circuit list: admins' custom columns (migration 0006), per-person columns, CSV uploads, blank templates (CSV/Excel, the columns you see or all); blank templates for the inventory |
| 2026-10-12 | Networking-tool-kev | Sites tab (migration 0007): site list with counts from the inventory, site detail, sites the inventory uses but aren't listed, renames carried to items and devices, custom columns, import/export, blank template; demo has four sites |
| 2026-10-12 | Networking-tool-kev | Circuits linked to sites (Site column, else the switch's site; migration 0008), circuit counts on Sites, site names linked on every page, site items open in the inventory |
| 2026-10-13 | Networking-tool-kev | Site layout and rack elevations (migration 0009): buildings, floors, rooms from the inventory, site page with the tree and racks front and rear, drag to move with checks, rack names and sites linked from the inventory, print; demo has the layout and racks filled in |
| 2026-10-13 | Networking-tool-kev | Config change alerts (who changed it from syslog), config compliance (migration 0010), switch port view, report (Activity and scheduled email), wall display Sites and Network pages with per-screen pages (migration 0011); answered which pre/post-checks run on Cisco and Arista |
| 2026-10-13 | Networking-tool-kev | Owner didn't see the rack elevations after updating: browsers kept the old app.js (no caching instructions were sent). Every response now says Cache-Control: no-cache |
| 2026-10-13 | Networking-tool-kev | Health checks and before/after comparison for every SSH upgrade platform (NX-OS, ASA extras, Arista, Junos, ArubaOS-Switch, AOS 8, OS10, EXOS, VRP, IOS-XR, AW+, MikroTik, EdgeOS); healthy sample output in the demo network for each command; fault tests (power, alarms, modules, unsaved config, LAG member lost after the reload) |
| 2026-10-13 | Networking-tool-kev | Suggestions agreed with the owner (topology map, search, maintenance calendar, two-factor sign-in; Teams/Slack, phone layout and config search later). Search box built; a daily health check was started and dropped at the owner's request |
| 2026-10-13 | Networking-tool-kev | Maintenance calendar (migration 0014_calendar): month and list views, clashes and change freezes, add/edit/copy/delete, .ics download; demo has two weeks of planned work with two clashes |
| 2026-10-13 | Networking-tool-kev | Two-factor sign-in (migration 0013_two_factor): authenticator codes and recovery codes, set-up with a QR code, required for local users by a setting, admin reset, break-glass secret (`netops-cli totp-secret`), lock-out shared with wrong passwords |
| 2026-10-13 | Networking-tool-kev | Network map: neighbours (CDP, LLDP detail and table, MikroTik) kept at each scan, map per site and for every site with links between sites, phones/APs optional, drag and save layout, SVG download; the demo network is cabled (HQ cores, DC leaf/spine, branches, warehouse) |
| 2026-10-14 | Networking-tool-kev | Name: second web check of NetLantern and NetSteward (both have neighbours in network monitoring: Spectrum's LANtern, Network Stewards' NetSteward); the demo is called NetLantern; draft lantern logo (mark, light and dark logos) in docs/branding |
| 2026-10-14 | Networking-tool-kev | Named NetCairn: default product name, demo, deploy labels, README and install guide; cairn logo (mark, light and dark logos) as the browser icon and on the sign-in page, top bar and wall display; other names checked on the web (NetKeel, Netquay, Linkhaven, Portlight…) |
| 2026-10-14 | Networking-tool-kev | Monitoring phase 1 (migration 0015_monitoring): SNMP v2c/v3 client (pysnmp) and ping sockets, `netops-monitor` service with its own store (state, events, daily totals, a file per day), up/warning/down with "down after N checks", restarts from the uptime, maintenance from the calendar and upgrades; Monitoring page (tiles, list, device window with graphs and availability, bulk on/off and profile), SNMP profiles with Test, per-platform SNMP configs for 22 platforms, map colours, wall display page and site counts, "Devices down or up" alerts, Settings options, licence module and permission area; firewall UDP 161, sysctl, installer; demo with history; fixed the calendar dialog's missing end tag that hid the network map |
| 2026-10-14 | Networking-tool-kev | Monitoring phase 2: interfaces read with SNMP (IF-MIB, 64-bit counters first; wrap and reset handling), rates and load, a file per day of readings and per month of hourly average/peak; device window's interface table, a port's traffic and errors graphs, busiest ports and ports with errors on the page and the wall, map lines coloured by load; described ports going down or up as events and alerts; demo ports with daily traffic, a busy link, a port with errors and one with discards |
| 2026-10-14 | Networking-tool-kev | Monitoring phase 3: hardware health (health.py) with readers for Cisco (process, memory pool, envmon, entity sensor, FRU), Juniper, Fortinet, HPE ArubaOS-Switch, Aruba controllers, Extreme, Huawei, MikroTik, Check Point and the standard HOST-RESOURCES/ENTITY-SENSOR/UCD MIBs; problems as warnings, events and alerts; CPU/memory and temperature history with the interface files; device window health, list column, Hardware problems tile and list, wall display panel; demo faults (power supply, fan, CPU). Answered: Meraki API (to-do), Schneider EBO (later), site collectors |
| 2026-10-14 | Networking-tool-kev | Cisco Meraki (migration 0016_meraki): Dashboard API client (paging, rate limits, region addresses, redirect guard), connections with an encrypted key and "Find organisations", poller reads into the monitoring store, Meraki section on the Monitoring page (status, uplinks, scheduled upgrades), calendar items, alerts, wall panel, add to the inventory; demo with three stores (pretend dashboard); firewall and security notes, guides. Answered: more SNMP options and a NetFlow overview; the owner chose custom OID sensors next |
| 2026-10-15 | Networking-tool-kev | Custom SNMP sensors (migration 0017_sensors): value/rate/state, tables with row names, thresholds and fine codes, per platform/site/devices, Test button, 15 examples; readings, graph and problems in the device window's Health; events, alerts, wall (names only); "How to set up a sensor" guide in the window, Custom sensors section in monitoring.md, admin and user guides; demo BGP peers (one down on hq-core1), ASA connections and IPsec tunnels |
| 2026-10-15 | Networking-tool-kev | SNMP-only device types (UPS, PDU, environment probe, other): no credential or SSH, skipped by backups, version checks, upgrades, reports and the CLI; "SNMP only" on the Config backups page, device form without credential and backup fields; SNMP and syslog setup help per type; sensor examples scoped to them; demo UPS, PDU and room probe with sensors. Versioning approved and built (VERSION 2.1.0, CHANGELOG, releasing guide, bundle and installer versions, v2.0.0 tag) |
| 2026-10-15 | Networking-tool-kev | Stacks, HA and optics for 2.1.0: Cisco StackWise, ASA/FortiGate/Palo Alto HA, failover events and alerts, Cisco optic light levels, PoE budget; demo stacks (hq-acc-sw2 member removed), ASA pair with yesterday's failover, a low optic on hq-acc-sw3, PoE nearly full on hq-acc-sw5 |
| 2026-10-15 | Networking-tool-kev | Explained the GitHub release steps (tag and release notes); parked the licence question for SNMP-only devices on the to-do list |
| 2026-10-15 | Networking-tool-kev | Release 2.1.0: changelog dated (SNMP-only devices, versions, stacks/HA/optics/PoE, the device form fix); the owner tags v2.1.0 on GitHub after merging |
| 2026-10-15 | Networking-tool-kev | Licensing for selling: editions and the Monitoring add-on in the product and on the Settings page, Meraki organisations as 25-device blocks, licence_tool editions, device bands, ledger and renewals; docs/selling.md (Stripe, OneDrive ledger and downloads, renewals, upgrades); VERSION 2.2.0 |
| 2026-10-15 | Networking-tool-kev | Automatic releases (release.yml + deploy/release.py; v2.1.0 is made on merge); the workflow builds each release's bundle on Ubuntu 26.04 and attaches it; a script on the owner's PC copies the newest into OneDrive and removes the older ones |
| 2026-10-15 | Networking-tool-kev | The owner's licence public key committed (made on the owner's PC; the private key stays there and in the password vault) |
