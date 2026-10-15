# NetCairn: notes for Claude

Read this first in every session, then read [docs/PROGRESS.md](docs/PROGRESS.md) to see
where the project is and what comes next.

## What this is

**Networking-tool-kev**, product name **NetCairn** (2026-10-14; logo and notes in
`docs/branding/`): the owner's own product version of NetOps Tools, for their own
deployments to sites and, later, to give or sell to customers. It started as a clean copy
of the NetOps Tools code (no history, no PRTG integration, generic sample data).

A self-hosted web platform for network operations: one server, one web address, one login
(Active Directory and/or local users), and a set of tools that share a device inventory and
one database.

| Tool | Folder | Status |
|---|---|---|
| Config Backup | `backend/app/tools/config_backup/` | Done |
| Firmware (version report, image library, upgrade jobs) | `backend/app/tools/firmware_upgrade/` | Built for every platform; needs lab testing ([docs/upgrades.md](docs/upgrades.md), [docs/upgrade-lab-tests.md](docs/upgrade-lab-tests.md)) |
| Circuits (circuit list from Excel, live location from MAC/ARP tables) | `backend/app/tools/circuits/` | Done; live locations need lab testing ([docs/circuits.md](docs/circuits.md)) |
| Syslog (receiver on 514, one file per day, search page, device setup help) | `backend/app/tools/syslog/` | Done ([docs/syslog.md](docs/syslog.md)) |
| Monitoring (ping and SNMP: up/down, response times, restarts, interfaces and traffic, hardware health; map, wall, alerts) | `backend/app/tools/monitoring/` | Done: up/down, interfaces, hardware health ([docs/monitoring.md](docs/monitoring.md)); health readers need lab confirmation |
| Network inventory (every device plus racks, servers, UPSs…; custom columns, import/export) | `backend/app/tools/inventory/` | Done ([docs/inventory.md](docs/inventory.md)) |
| Sites (site list, what the inventory has at each) | `backend/app/tools/inventory/sites.py` | Done ([docs/sites.md](docs/sites.md)) |
| Site layout and rack elevations (buildings, floors, rooms; drag to move) | `backend/app/tools/inventory/layout.py` | Done ([docs/racks.md](docs/racks.md)) |
| Config compliance (rules checked after every backup) | `backend/app/tools/config_backup/compliance.py` | Done ([docs/compliance.md](docs/compliance.md)) |
| Report (Activity › Report, emailed on a schedule) | `backend/app/core/reports.py` | Done |
| Users and activity (per-area permissions, activity report) | `backend/app/core/users.py`, `permissions.py` | Done ([docs/users.md](docs/users.md)) |

Design docs: [docs/design.md](docs/design.md) (platform and backup tool),
[docs/firmware.md](docs/firmware.md) (firmware tool and upgrade plan).

## Where it runs

* Each deployment is a customer or site network. Don't assume any one network: platforms
  supported today are Cisco IOS/IOS-XE (install and bundle mode), NX-OS (+vPC), ASA (+failover),
  Firepower FTD managed by FDM (+HA), and Allied Telesis AlliedWare Plus. Backups, version
  checks and circuit locations also cover Arista, Juniper, Fortinet, Palo Alto, Check Point,
  HPE Aruba, Dell, Extreme, Cisco IOS-XR/small business, MikroTik, Ubiquiti and Huawei
  ([docs/vendors.md](docs/vendors.md)), and most have upgrade drivers that still need lab
  sign-off (`drivers/common.py` holds their shared copy-check-boot-reload logic).
  Upgrade procedures are drivers with selectable paths, so new designs are new paths.
* Login is Active Directory over LDAPS and/or local NetOps users, plus a break-glass local admin.
* Target server: **Ubuntu 26.04** (Python 3.14, nginx, systemd), often **air-gapped**, installed
  from an offline bundle (`deploy/airgap/`, [docs/install-airgap.md](docs/install-airgap.md)).
  Connected servers run `deploy/install-online.sh`, which builds the same bundle on the server
  and runs the same `install.sh` ([docs/install-online.md](docs/install-online.md)); the
  Ubuntu package list for both is `deploy/os-packages.txt`.
  Any new Python or Ubuntu dependency must work with `build-bundle.sh` (wheels only, no
  compiling) and be added to it. The bundle installs only on the Ubuntu release it was built on.
  Security is a priority: see [docs/security-hardening.md](docs/security-hardening.md) before
  changing deployment, ports or outbound connections (the host firewall blocks outbound by default).
* Monitoring is whatever the customer uses: `GET /api/health`, and syslog forwarding
  (`deploy/hardening/rsyslog-forward.conf`). There is no vendor-specific monitoring integration.

## Product direction (to discuss and plan)

Product name and branding, licence terms, an installer for online and offline sites, a
first-run setup screen instead of editing `netops.env`, per-customer settings, customer
documentation, and optionally multi-site use and licence keys.

## Related repository

The work version lives in `kevcarolan/Networking-Tools`. Fixes that apply to both are
copied across **on request only** (by hand or `git cherry-pick` with the other repo added as a
remote); never sync the two automatically.

## Code layout and conventions

* Backend: Python 3.11+, FastAPI, SQLAlchemy 2, Netmiko. Settings are env vars prefixed
  `NETOPS_` (`backend/app/core/config.py`, documented in `.env.example`).
* Never write the product name into the GUI, reports or messages: use the `product_name`
  setting (`{{product_name}}` in `index.html`), or neutral words such as "inventory".
* `core/` is shared by every tool: auth, inventory, credentials, platforms, SSH (`core/ssh.py`),
  audit log. First-run setup (setup code, first admin, AD, certificate) is `core/setup.py`;
  AD settings and the site name and day-to-day defaults (`appsettings.OPTIONS`) made in the
  GUI live in the `app_settings` table (`core/appsettings.py`), and a value in `netops.env`
  always wins. Safety gates (live upgrade platforms, break-glass admin, ports, secrets) stay
  in `netops.env` only. The app only proposes a certificate in
  `<data>/tls/`; the root `netops-tls` path unit (`deploy/netops-tls-apply.sh`) checks and
  installs it. The wall display (`core/display.py`, `static/display/`) is a read-only feed
  and page for NOC screens, reached with a per-screen key on its own nginx site and port
  (8443, `deploy/nginx-netops-display.conf`); the main site refuses it. Never put configs,
  credentials or addresses in its feed (nor syslog message text); each screen picks its pages
  (`display_screens.pages`). Email alerts (`core/alerts.py`): the web app's
  scheduler checks state every minute and sends each new event once (`alerts_sent` table);
  the mailer is injectable (`create_app(mailer=)`), tests never send mail. Alert kinds include
  config changes (who changed it from syslog; changed lines optional, secret-like lines never)
  and compliance; the report (`core/reports.py`, Activity › Report) is emailed by the same
  scheduler on a day and time. Config compliance (`tools/config_backup/compliance.py`, tables
  `compliance_rules`, `compliance_results`) runs after every backup; config lines in results
  only for `backups:configs`. Licences (`core/licence.py`, made with `python -m app.licence_tool`, see
  [docs/licensing.md](docs/licensing.md)): a 60-day trial, then signed licences with an end
  date, a device count and the tools it unlocks (`licence.MODULES`: backups, firmware,
  upgrades, circuits, syslog, monitoring; one full install, the licence unlocks parts of it). A tool's
  router gets `Depends(licence.module(...))`, its scheduler checks `licence.has_module`,
  and the GUI greys out its tab (`data-module`). The trial and older licences unlock
  everything. Without a licence, only new work is blocked (`licence.require_active`,
  `licence.room_for`): never backups, checks, or an upgrade job already under way.
  `python -m app` is development mode, with no licence needed. Tools live in `tools/<name>/` with `models.py`, `service.py`, `api.py`.
* **Database:** SQLite `data/app.db`, kept up to date by **Alembic** migrations, applied when
  the app or worker starts (`core/migrate.py`, `backend/migrations/`). After changing a model,
  run `alembic revision --autogenerate -m "..."` from `backend/`, review the file (SQLite: batch
  mode), and commit it with the model. `tests/test_migrations.py` fails when a model and the
  migrations disagree. Never edit `tests/baseline_schema.sql` or an existing migration.
* Frontend: plain HTML/CSS/JS in `backend/app/static/`, no build step. Use the `h()` and
  `api()` helpers in `app.js`, keep styles on the CSS variables in `style.css` (light and dark),
  and hide admin-only controls with `data-admin`.
* Permissions are a level per area (`core/permissions.py`: inventory, backups, firmware, upgrades,
  circuits, syslog, monitoring; inventory's `addresses` level guards anything that decides where a credential is sent) plus the admin flag (users, activity). Protect endpoints with `require(area, level)`
  (`require_admin` only for users/activity); in the GUI use `can(area, level)` and
  `data-perm="area:level"`. Users are added on the Users page (`core/users.py`, table `users`) or
  come from AD groups as a fallback ([docs/users.md](docs/users.md)). Live upgrade jobs also
  need `upgrades:live`. Everything that changes something is written to the audit log with
  `audit()`; the activity report reads it.
* Upgrade jobs:
  * checks and parsers in `checks.py`; one **driver** per platform in `drivers/` (paths, extra
    pre-checks, the procedure as `Step`s); the engine in `jobs.py` (`JobService`, `allowed_actions`);
    device access in `deviceio.py` (SSH change/copy) and the management APIs (`fdm.py`,
    `fortios.py`, `panos.py`, sharing the pinned-certificate code in `apiclient.py`);
  * upgrade jobs only for devices whose image can be sent from the server (SSH/SCP or the
    device's own API); never build a way for devices to pull images;
  * the web app only **queues** requests (`request_action`); the **worker** (`app/worker.py`,
    `netops-worker.service`) runs them. Never talk to a device for a job from the web process;
  * a dry run and a live run use the same steps: only `StepContext.change/transfer/fdm_change`
    differ. Live needs `NETOPS_UPGRADE_LIVE_PLATFORMS`, a window and the typed device name;
  * tests drive every path against the network simulator `app/demo/simnet.py` (also the demo's
    network; `tests/fake_network.py` is kept as an alias). Extend the simulator with any new
    command a driver sends.
* SSH host keys: `core/ssh.py` records a device's key on first use (`<data>/known_hosts`) and
  every SSH or SCP connection then checks it (`ssh.trust_on_first_use`, `ssh.strict_params()`);
  any new way of reaching a device must do the same. CSV/XLSX exports go through
  `core/exports.py` (`csv_writer`, `append_row`) so formula-like text stays text. Root scripts
  (`deploy/`) must never read, write or run anything the `netops` account can change.
* Syslog: the receiver (`tools/syslog/receiver.py`, `python -m app.tools.syslog`,
  `netops-syslog.service`, CAP_NET_BIND_SERVICE only) is the only writer; it keeps one
  SQLite file per UTC day in `<data>/syslog/` (`store.py`, not Alembic: no migrations) and
  writes `status.json` for the web app, which only reads. The sender is the source
  address, matched to the inventory in `sources.py`. Suggested device configs per platform
  are in `howto.py`: add one for every new platform (a test checks). The demo fills it from
  `app/demo/syslog.py`.
* Monitoring (`tools/monitoring/`): the poller (`poller.py`, `python -m app.tools.monitoring`,
  `netops-monitor.service`, no capabilities) is the only writer of `<data>/monitoring/`
  (`store.py`: `state.db` with states, interfaces, events and daily totals, a file per UTC
  day of checks, `ifd-<day>.db` interface readings and `ifh-<month>.db` hourly rollups; not
  Alembic) and writes `status.json`; the web app only reads. Interfaces: `ifaces.py`
  (IF-MIB columns, counters to rates). Hardware health: `health.py` (`PLATFORM_PROBES`, one
  entry per platform, a test checks; readers from vendor MIB docs until confirmed in the lab;
  the simulator answers them in `app/demo/monitor.py` `health_mib`). Read-only towards devices:
  ping sockets (`ping.py`) and SNMP GET/GETBULK (`snmp.py`, pysnmp), never SET, no traps
  (syslog covers device messages). SNMP profiles (`mon_profiles`, secrets encrypted) need
  `inventory:credentials`; choosing a device's profile needs `inventory:addresses`; area
  `monitoring` (none/view/manage). Ping and SNMP are injectable (`Poller(snmp=, pinger=)`,
  `create_app(snmp_client=)`); tests and the demo use `app/demo/monitor.py` (`SimMonitor`).
  Suggested SNMP configs per platform are in `howto.py`: add one for every new platform (a
  test checks). Calendar windows and upgrades under way mark devices "maintenance" (events
  kept, not emailed). The wall display shows names and statuses only, never reasons.
  Custom SNMP sensors (`sensors.py`, table `mon_sensors`, area `monitoring:manage`): read
  with the health read as `Reading(kind="sensor")`, so history (`s:<name>` in `hx`/`hh`),
  problems, events and alerts come for free; the wall shows only the sensor's name
  (`display._wall_problems`), never a row label or value. Examples in `sensors.EXAMPLES`
  (a test adds each); the simulator answers extra OIDs per device (`SimMonitor.extra`).
  Cisco Meraki (`meraki.py`): the poller reads each `mon_meraki` organisation through the
  Dashboard API (GET only, read-only key encrypted like credentials, only to `meraki.BASES`,
  redirects only within Meraki's domain) into `meraki_*` tables in `state.db`; the only
  internet connection the product makes, optional (firewall `MERAKI_HOSTS` or `https_proxy`).
  Injectable (`Poller(meraki_fetch=)`, `create_app(meraki_fetch=)`); tests and the demo use
  `app/demo/meraki.py` (`FakeDashboard`). Connections need `inventory:credentials`.
* Inventory (`tools/inventory/`): table `assets`, one row per thing; a row with `device_id`
  is managed and every device gets one (`fields.sync_devices`, which also links an existing
  row by name or address). Built-in columns are `fields.STANDARD` (page, import and export
  all read it); admins' columns are `asset_fields`, their values JSON in `assets.custom`
  under `x_<key>`. Values from the device (`Field.auto`) are shown where a row is empty.
  Only `devices` count for the licence. Part of every licence. Blank templates for
  inventory, sites and circuits go through `exports.template()`. Sites (`sites.py`, tables
  `sites`, `site_fields`) reuse the inventory's field code; a row is at a site when its
  effective Site is the site's name or code, and renaming one rewrites `assets.site` and
  `devices.site`. Circuit custom columns (`ct_fields`, values in `ct_circuits.custom`) are
  text, read by header name on upload (`importer.parse_workbook`/`parse_csv`, `custom=`).
  A circuit's site (`circuits/api.SiteIndex`): its Site column, else its switch's, else the
  switch it was found on; the GUI links any Site value with `siteLink()`.
  Site layout (`layout.py`, table `site_locations`: building > floor > room, or a room in a
  building): rows are placed by their Building/Floor/Room text, a row in a rack (its Rack =
  a rack row's name at the same site) is where the rack is. Rack elevations come from Rack,
  Position (bottom U), Height (0 = zero-U), Rack face and Depth; `POST /api/racks/move` checks
  range and overlap. Renames rewrite the rows' text, like sites do.
* Device access is always injectable (`fetcher=` / `fw_collector=` in `create_app`), so tests
  never touch SSH. Parser tests use real sample output in `app/demo/samples.py` (alias
  `tests/firmware_samples.py`); the newer vendors' samples (`app/demo/vendor_samples.py`) are
  from vendor documentation until replaced by lab captures (`netops-cli capture <device>`,
  `tools/firmware_upgrade/capture.py`; `capture.parse_file()` reads a capture back). A new
  show command a driver or check sends must pass `capture.is_read_only`; the capture refuses
  anything else.

## Working rules

* Run the tests before every commit: `cd backend && python -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt && pytest -q`.
  All must pass.
* Work on a feature branch and never push to `main`. The user merges through pull requests.
* Nothing that changes a device (copy, boot, reload, install) runs without an explicit
  admin action, a maintenance window and pre-checks. See the safety rules in `docs/firmware.md`.
* **At the end of every session, update `docs/PROGRESS.md`:** tick finished items, add a
  line to the session log, and record new decisions and open questions.
* Keep the docs in plain language. The users are network engineers, not developers.
  When a change alters what admins or users see, update the customer guides in `docs/customer/` too.
