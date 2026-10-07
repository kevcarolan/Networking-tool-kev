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
| Users and activity (per-area permissions, activity report) | `backend/app/core/users.py`, `permissions.py` | Done ([docs/users.md](docs/users.md)) |

Design docs: [docs/design.md](docs/design.md) (platform and backup tool),
[docs/firmware.md](docs/firmware.md) (firmware tool and upgrade plan).

## Where it runs

* Each deployment is a customer or site network. Don't assume any one network: platforms
  supported today are Cisco IOS/IOS-XE (install and bundle mode), NX-OS (+vPC), ASA (+failover),
  Firepower FTD managed by FDM (+HA), and Allied Telesis AlliedWare Plus. Upgrade procedures are
  drivers with selectable paths, so new designs are new paths.
* Login is Active Directory over LDAPS and/or local NetOps users, plus a break-glass local admin.
* Target server: **Ubuntu 26.04** (Python 3.14, nginx, systemd), often **air-gapped**, installed
  from an offline bundle (`deploy/airgap/`, [docs/install-airgap.md](docs/install-airgap.md)).
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
* `core/` is shared by every tool: auth, inventory, credentials, platforms, SSH (`core/ssh.py`),
  audit log. Tools live in `tools/<name>/` with `models.py`, `service.py`, `api.py`.
* **Database:** SQLite `data/app.db`, created with `create_all` and no migration tool. New
  tables appear automatically, but **a new column on an existing table does not**. Add a new
  table (prefixed with the tool, e.g. `fw_`), or introduce Alembic first.
* Frontend: plain HTML/CSS/JS in `backend/app/static/`, no build step. Use the `h()` and
  `api()` helpers in `app.js`, keep styles on the CSS variables in `style.css` (light and dark),
  and hide admin-only controls with `data-admin`.
* Permissions are a level per area (`core/permissions.py`: inventory, backups, firmware, upgrades,
  circuits) plus the admin flag (users, activity). Protect endpoints with `require(area, level)`
  (`require_admin` only for users/activity); in the GUI use `can(area, level)` and
  `data-perm="area:level"`. Users are added on the Users page (`core/users.py`, table `users`) or
  come from AD groups as a fallback ([docs/users.md](docs/users.md)). Live upgrade jobs also
  need `upgrades:live`. Everything that changes something is written to the audit log with
  `audit()`; the activity report reads it.
* Upgrade jobs:
  * checks and parsers in `checks.py`; one **driver** per platform in `drivers/` (paths, extra
    pre-checks, the procedure as `Step`s); the engine in `jobs.py` (`JobService`, `allowed_actions`);
    device access in `deviceio.py` (SSH change/copy) and `fdm.py` (FDM API);
  * the web app only **queues** requests (`request_action`); the **worker** (`app/worker.py`,
    `netops-worker.service`) runs them. Never talk to a device for a job from the web process;
  * a dry run and a live run use the same steps: only `StepContext.change/transfer/fdm_change`
    differ. Live needs `NETOPS_UPGRADE_LIVE_PLATFORMS`, a window and the typed device name;
  * tests drive every path against `tests/fake_network.py`. Extend the simulator with any new
    command a driver sends.
* Device access is always injectable (`fetcher=` / `fw_collector=` in `create_app`), so tests
  never touch SSH. Parser tests use real sample output in `backend/tests/firmware_samples.py`.

## Working rules

* Run the tests before every commit: `cd backend && python -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt && pytest -q`.
  All must pass.
* Work on a feature branch and never push to `main`. The user merges through pull requests.
* Nothing that changes a device (copy, boot, reload, install) runs without an explicit
  admin action, a maintenance window and pre-checks. See the safety rules in `docs/firmware.md`.
* **At the end of every session, update `docs/PROGRESS.md`:** tick finished items, add a
  line to the session log, and record new decisions and open questions.
* Keep the docs in plain language. The users are network engineers, not developers.
