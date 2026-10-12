# NetOps Tools: notes for Claude

Read this first in every session, then read [docs/PROGRESS.md](docs/PROGRESS.md) to see
where the project is and what comes next.

## What this is

**Networking-tool-kev**: the owner's own product version of NetOps Tools, for their own
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
  credentials or addresses in its feed. Email alerts (`core/alerts.py`): the web app's
  scheduler checks state every minute and sends each new event once (`alerts_sent` table);
  the mailer is injectable (`create_app(mailer=)`), tests never send mail. Licences (`core/licence.py`, made with `python -m app.licence_tool`, see
  [docs/licensing.md](docs/licensing.md)): a 60-day trial, then signed licences with an end
  date and a device count. Without one, only new work is blocked (`licence.require_active`,
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
  circuits; inventory's `addresses` level guards anything that decides where a credential is sent) plus the admin flag (users, activity). Protect endpoints with `require(area, level)`
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
