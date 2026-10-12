# Project progress

The single place to see where Networking-tool-kev is and what's next. Update it at the end
of every working session.

**Now:** Clean copy of NetOps Tools (config backup, firmware and upgrade jobs, circuits with
live MAC/ARP locations, users and activity). No PRTG integration; generic sample data.
**Next:** Multi-vendor support, as planned in [plans/multi-vendor.md](plans/multi-vendor.md): PR A (backup, versions, circuits for every new platform), then PR B (SSH/SCP upgrade drivers), then PR C (firewall upgrades via API).

## Roadmap

### Multi-vendor ([plans/multi-vendor.md](plans/multi-vendor.md))
- [x] PR A: Arista, Juniper, Fortinet, Palo Alto, Check Point, Aruba (CX, ProCurve, AOS 8 controllers), Dell OS10, Extreme, Cisco IOS-XR and SMB, MikroTik, Ubiquiti EdgeOS, Huawei: backup, versions, circuits ([vendors.md](vendors.md)). Readers built from vendor docs: check each on a real device (lab tests 7b)
- [x] PR B: upgrade drivers for Arista (+MLAG), Junos (+Virtual Chassis), ArubaOS-Switch, Aruba AOS 8, Dell OS10, EXOS, Huawei VRP, IOS-XR, MikroTik, EdgeRouter ([upgrades.md](upgrades.md#paths-per-platform)); lab tests section 9
- [ ] Later if needed: Junos NSSU and SRX clusters; Dell VLT and Aruba controller cluster paths
- [x] PR C: FortiGate (standalone, HA cluster) and PAN-OS (standalone, HA pair), image sent through their API ([upgrades.md](upgrades.md#paths-per-platform)); lab tests section 10

### Product
- [x] Per-customer settings: customer or site name (header, reports) and day-to-day defaults on the Settings page; safety gates stay in `netops.env`
- [ ] Product name and branding (GUI title, logo, docs). The name is now one setting,
  `NETOPS_PRODUCT_NAME`; still to do: choose the name, a logo, and rename the docs
- [ ] Licence terms: draft agreement in [legal/EULA-draft.md](legal/EULA-draft.md); decisions listed at its end, then a solicitor's review
- [ ] Owner: make the licence signing key and commit its public key ([licensing.md](licensing.md#one-time-make-the-signing-key))
- [x] First-run setup screen (admin account, AD settings, certificate) instead of editing `netops.env`; AD and the certificate stay on a Settings page for admins
- [x] Installer for internet-connected and air-gapped sites (`deploy/install-online.sh` builds and installs the same bundle on the server; [install-online.md](install-online.md))
- [x] Customer documentation: install guide, admin guide, user guide ([customer/](customer/README.md))
- [x] Licence keys: 60-day trial, signed licences (end date, devices, optional installation), read-only for new work without one ([licensing.md](licensing.md))
- [x] Wall display for NOC screens: overview and upgrades pages, own port (8443), per-screen links ([customer/admin-guide.md](customer/admin-guide.md#wall-displays))
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

## Open questions

- Licence agreement: per installation or per site? Managed-service use? Support terms, warranty, liability cap, governing law ([legal/EULA-draft.md](legal/EULA-draft.md))

- Product name?
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
