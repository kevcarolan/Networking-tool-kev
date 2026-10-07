# Upgrade jobs

Every device upgrade goes through an **upgrade job**. The job is the procedure (the same
checks and steps, in the same order, every time) and the record (what was checked, who
decided what and why, and what happened). It is there to stop mistakes and short cuts,
not to slow you down.

> **Before production:** every platform and path must pass the lab tests in
> [upgrade-lab-tests.md](upgrade-lab-tests.md). Until a platform has passed, keep it out of
> `NETOPS_UPGRADE_LIVE_PLATFORMS` so its jobs can only be dry runs.

## Dry run or live

Each job is created as a **dry run** or a **live upgrade**. Both run the same procedure.

* **Dry run:** the checks really log in and read the device. Every step that would change
  something (copy, configure, install, reload, commit, failover) is only recorded as
  "DRY RUN - would …". Use it to rehearse a change, or to try NetOps on a new platform.
* **Live:**
  * Only for platforms (or `platform:path`) listed in `NETOPS_UPGRADE_LIVE_PLATFORMS`.
  * Only with a change window, and Start or Continue only works inside the window.
  * You type the device name to confirm Start, Continue and Roll back.

## Who can do what

Set on the **Users** page ([users.md](users.md)), area **Upgrade jobs**:

| Level | Can |
|---|---|
| view | See jobs, reports and history |
| dry run | Also create, check, stage, start, continue, override, roll back, stop and cancel **dry-run** jobs |
| live | The same for **live** jobs |

Device upgrade settings and marking an image "Recommended" need **Firmware - manage**.
AD users who aren't on the Users page get upgrades from `NETOPS_LDAP_UPGRADER_GROUP`
(dry run and live); if that setting is empty, admins get them. The break-glass admin can
always run upgrades.

## Before the first job

1. **Upload the image** in **Firmware › Image library**:
   * Download it from the vendor yourself; NetOps never downloads anything.
   * When you upload, paste the vendor's MD5 or SHA-512.
   * The library is grouped by vendor. An admin can mark a release **Recommended**.
2. **Read the device's version:** Firmware › Versions › **Check now**.
3. **Set its upgrade settings** (admin): Firmware › Versions › **Upgrade settings**.

   | Setting | What it's for |
   |---|---|
   | Upgrade account | A privileged account used only for upgrades, never the backup account. Without it the pre-checks are blocked. |
   | Usual upgrade path | The path new jobs start with (see below). |
   | Pair / peer device | The other unit of an HA, failover or vPC pair. Both units must be NetOps devices, and both are set to point at each other. |
   | File system | Only if the device doesn't use the default (`flash:`, `bootflash:`, `disk0:/`). |
   | FDM certificate (FTD) | Press **Fetch from the device**, compare the fingerprint with the one FDM shows, then save. NetOps refuses to talk to an FDM whose certificate has changed since. |
4. **Allow the copy on the device:** enable its SCP server. See the table below, and
   [security-hardening.md §11](security-hardening.md).
5. **Upload the circuit list** ([circuits.md](circuits.md)), so the job can show what the
   device carries.

## The procedure

1. **Firmware › Upgrade jobs › New upgrade job:**
   * Pick the device; only the images for its platform and model are offered.
   * Pick the **upgrade path**. Pair paths need a peer.
   * Choose dry run or live, and add the change reference, the window and any notes.
   * There is one open job per device; for a pair, per unit.
   * The affected circuits are saved with the job.
2. **Run pre-checks** whenever you like before the window. The job becomes:
   * **Ready to start**: every blocker passed;
   * **Blocked**: the failing blockers are listed at the top of the job window. Fix the
     device and press **Re-check**, or override (see below).
3. **Stage image** (optional, before the window):
   * Copies the image to every unit and checks its MD5 *on the device*.
   * Nothing is reloaded.
   * A copy that doesn't match is never accepted; this can't be overridden.
4. **Start**, in the change window:
   * The pre-checks run again first.
   * Then the circuits are saved again and the steps run one by one (see the
     **Procedure** tab): backup, copy and MD5 (skipped if already staged), install or
     boot change, reload, wait for the device to come back, **post-checks**, commit,
     backup.
5. The result is **Completed**, **Completed with overrides**, **Failed**, or **Paused**
   (the job stopped between steps; **Continue** carries on).

### Stopping safely

* **Stop after this step** pauses the job before its next step. A step that is already
  running, such as a reload, is never interrupted.
* A live job also **pauses by itself before any reload step once the change window has
  ended**. Continue only works inside a window, so re-plan the window first.
* If the upgrade worker is stopped (for example for maintenance), running jobs pause
  before their next step.

### Overriding a check

Some failures are expected: a power supply already known to be faulty, or other work
going on at the same time.

* Press **Override…** on the failed row and say why it is safe to go on (at least 10
  characters).
* The override, your name and the time are kept in the record and the report.
* An override only covers **that exact result**:
  * If the same check fails again in the same way, the override is carried forward,
    including from the pre-check to the post-check.
  * If it fails differently (for example a *new* alarm), it needs a new override.
* Checksum and platform checks can't be overridden.
* Warnings (high CPU, a minor alarm, old images on flash) never block. They are recorded
  for you to judge.

### When post-checks fail

The job stops at the failed post-check. Every choice you make is recorded:

* **Investigate and fix it** by hand, then **Re-run post-checks**. If they pass, the job
  is Paused and **Continue** carries on.
* **Override** the failure with a note. The job is Paused, and Continue carries on (for
  IOS-XE that is the commit).
* **Roll back** to the previous version (see each platform below).

If NetOps restarts mid-step, or a device doesn't come back after a reload, the job is
**Needs attention**. Check the device on the console, then **Re-run post-checks** or
**Roll back**.

## Paths per platform

| Platform | Path | What it does | Roll back |
|---|---|---|---|
| IOS-XE | **Install mode** (standalone or stack) | `install add file flash:<img>`, then `install activate auto-abort-timer 120 prompt-level none` (reloads). **Commits only after the post-checks pass or are overridden** (`install commit`). | Before the commit: `install abort` (the switch also reverts by itself when the timer runs out; the job then shows Needs attention). After it: `install rollback to id <id>`, the rollback point recorded at the pre-check. |
| IOS / IOS-XE | **Bundle mode** | `boot system flash:<new>`, then the old image as a fallback, `write memory`, `reload`. | `boot system <old>`, `write memory`, `reload`. |
| NX-OS | **Standalone** | `show install all impact` must pass, then `install all nxos bootflash:<img> non-interruptive`. | `install all` with the previous image. |
| NX-OS | **vPC pair** | The vPC **secondary** first, check that the vPC is healthy, then the primary. | Each switch back, in reverse order. |
| ASA | **Standalone** | `boot system disk0:/<new>` (old one as fallback), `write memory`, `reload noconfirm`. | Boot the old image and reload. |
| ASA | **Failover pair** | Both units staged and checked. Then: `boot system` on the active unit, `write memory` on both, `failover reload-standby`. Wait for Standby Ready and post-check it. `failover active` on the upgraded unit, `failover reload-standby` for the other, then post-check both. No outage beyond the failovers. | The same sequence with the old image. |
| FTD (FDM) | **Standalone** | Through the FDM REST API: no undeployed changes, upload the package, readiness check, upgrade, then wait until FDM reports the new version. | FDM's **revert upgrade**. |
| FTD (FDM) | **HA pair** | The **standby** unit first; when it is back and HA is healthy, **fail over** so the upgraded unit is active; then the other unit; HA health checked at the end. | Revert each unit. |
| AlliedWare Plus | **Standalone or VCStack** | SCP the `.rel`, `boot system flash:/<new>.rel`, `boot system backup flash:/<old>.rel`, `write memory`, `reload`. Stack members follow the master. | `boot system flash:/<old>.rel`, `write memory`, `reload`. |

**Other vendors** (October 2026). These were built from vendor documentation and tested on
the simulator only. Keep them as dry runs until each one passes its lab test
([upgrade-lab-tests.md](upgrade-lab-tests.md), section 9).

| Platform | Path | What it does | Roll back |
|---|---|---|---|
| Arista EOS | **Standalone** | Copy the `.swi` to flash, check its MD5, `boot system flash:<new>.swi`, `write memory`, `reload now`. | `boot system` the previous `.swi` (kept on flash), `write memory`, `reload now`. |
| Arista EOS | **MLAG pair** | The MLAG **secondary** first; check that the MLAG is active and the peer link is up; then the primary. | Each switch back, in reverse order. |
| Juniper Junos | **Standalone or Virtual Chassis** | Copy the package to `/var/tmp`, check its MD5, `request system software add /var/tmp/<pkg> reboot`. A Virtual Chassis upgrades and reloads every member together. | `request system software rollback`, `request system reboot`. |
| ArubaOS-Switch | **Standalone or stack** | Upload over SCP straight into the image slot the switch is **not** running from, check it there, `write memory`, `boot set-default flash <slot>`, `reload`. | `boot set-default flash <previous slot>`, `reload`. |
| Aruba AOS 8 controller | **One controller** | Copy to flash, `copy flash: <img> system: partition <other>`, check the version in that partition, `boot system partition <other>`, `write memory`, `reload`. A cluster: one controller per job. | `boot system partition <previous>`, `write memory`, `reload`. |
| Dell OS10 | **One switch** | Copy to the account's home folder, `image install home://<img>` (waits until `show image status` says it is done), `boot system standby`, `write memory`, `reload`. A VLT pair: one switch per job, the secondary first. | `boot system standby` (the previous software is there now), `write memory`, `reload`. |
| Extreme EXOS | **Standalone or SummitStack** | Copy to `/usr/local/cfg`, check its size, `install image <file> reboot` (installs into the partition not in use and boots from it). | `use image <previous partition>`, `reboot`. |
| Huawei VRP | **Standalone or stack** | Upload the `.cc` over SCP, check its size, `startup system-software flash:/<new>.cc`, `save`, `reboot`. | `startup system-software` the previous `.cc`, `save`, `reboot`. |
| Cisco IOS-XR | **install add / activate** (eXR) | `install add source harddisk: <img>` (waits until it is done), `install activate <img> noprompt` (reloads). **Commits only after the post-checks pass** (`install commit`). | Before the commit: `reload location all`, which comes back on the committed (previous) software. After the commit: by hand. |
| Cisco IOS-XR | **install replace** (XR 7 on 8000, NCS 540/5700) | `install replace /harddisk:/<img> noprompt` (reloads), then `install commit` after the post-checks. | The same as above. |
| MikroTik RouterOS | **One router or switch** | Upload the `routeros` `.npk`, `/system reboot` (RouterOS installs it while booting). After the post-checks: `/system routerboard upgrade` and one more reboot, unless the firmware is already current. | **By hand:** RouterOS keeps no copy of the old release. Upload the previous `.npk` and run `/system package downgrade`. The job shows Needs attention with this instruction. |
| Ubiquiti EdgeRouter | **One router** | Copy the `.tar` to `/tmp`, check its MD5, `add system image /tmp/<file>` (replaces the image not in use and makes the new one the default), `reboot`. | `set system image default-image` (back to the previous image), `reboot`. |

**Firewalls** (October 2026, built from vendor documentation; lab test first, section 10):

| Platform | Path | What it does | Roll back |
|---|---|---|---|
| FortiGate | **Standalone** | The image is sent through the FortiGate REST API (FortiOS can't receive a file over SSH). FortiOS checks it, writes it to the partition it isn't running from, and reboots onto it. | `execute set-next-reboot <previous partition>`, `execute reboot`. |
| FortiGate | **HA cluster** | The image is sent to the cluster. With `uninterruptible-upgrade` (a pre-check warns when it is off) the cluster upgrades the secondaries, fails over, then the old primary, so its address stays up. The job waits until the cluster reports the new version with HA health OK. | **By hand** on each member (the job says how). |
| PAN-OS | **Standalone** | Through the XML API: upload the image, `request system software install version <v>` (the job follows the install), restart. The pre-check makes sure the base release (e.g. 10.2.0 before 10.2.8) is on the firewall. | Install the previous version (still on the firewall) and restart. |
| PAN-OS | **HA pair** | The **passive** unit first: suspend it, install, restart, make it functional and check the pair. Then the active unit: suspending it fails the pair over to the upgraded unit. The pair is checked again at the end. | Each unit back to the previous version, in reverse order. |

**FortiGate account:** the upgrade account logs in over SSH (version checks, roll back) and
to the REST API. For the API, use a REST API token if you have one: put it in the
credential's **enable secret**. Without one, the account's username and password are used.

Not done, by choice: HPE Aruba AOS-CX and the Cisco small business switches (they would
have to pull the image from a server; they keep backups, versions and circuits). Check
Point (its package has to be copied with an expert-shell account: to be decided). Also not
yet: Junos NSSU and SRX chassis clusters, and pair paths for Dell VLT and Aruba controller
clusters.

The ASA failover pair is set up as two NetOps devices: the **active address** (the job's
device) and the **standby address** (its peer). The addresses follow the roles, so
NetOps always talks to "whichever unit is active" and "whichever is standby".

Adding a new design (another pair type, a different procedure) means adding a path to a
driver in `backend/app/tools/firmware_upgrade/drivers/`. The GUI, the engine and the report
pick it up from there.

**SCP server needed on the device** (for the copy):

| Platform | Command |
|---|---|
| IOS/IOS-XE | `ip scp server enable` |
| NX-OS | `feature scp-server` |
| ASA | `ssh scopy enable` |
| AW+ | `ssh server scp` |
| Arista EOS | none (SCP works with the switch's SSH server) |
| Junos, IOS-XR, Dell OS10, EXOS, MikroTik, EdgeRouter | none (the copy uses the SSH login) |
| ArubaOS-Switch | `ip ssh filetransfer` |
| Aruba AOS 8 | none (checked in the lab) |
| Huawei VRP | `scp server enable` |

FTD, FortiGate and PAN-OS receive the image through their management API instead, so the
server needs HTTPS (443) to their management addresses (`FDM_HOSTS` in the firewall
template). Each one's certificate is trusted once, in its upgrade settings ("Fetch from the
device", then compare with the fingerprint the device shows).

## The checks

**Pre-checks on every platform:**
* upgrade account set;
* can log in;
* the image is for this platform and model;
* the image file on the server still matches its MD5;
* the device isn't already on the target version;
* enough free flash (image size × 1.1, or × 2.2 for IOS-XE install mode);
* the SCP server is enabled;
* the current image is still on flash, for a roll back;
* a config backup in the last 24 hours (taken there and then if not).

**IOS / IOS-XE, in addition:**
* install mode (install path) or bundle mode (bundle path);
* no critical or major alarms (a minor alarm is a warning);
* fans, power and temperature OK;
* CPU and memory (warnings);
* no install operation pending;
* old inactive images (info);
* no unsaved configuration;
* every stack member Ready.

**Platform-specific:**

| Platform | Extra pre-checks |
|---|---|
| ASA | The failover pair is healthy, with one active and one standby unit. A pair member can't use the standalone path. |
| NX-OS | The vPC peer link and keep-alive are healthy (vPC path); `show install all impact` runs before the reload. |
| FTD | The FDM API is reachable with a trusted certificate; no undeployed changes; HA is healthy and in sync (HA path). |
| Arista EOS | The running `.swi` stays on flash; the MLAG is active with the peer link up (MLAG path). |
| Junos | Every Virtual Chassis member is present. |
| ArubaOS-Switch, Huawei | The SCP server is on. ArubaOS-Switch shows which slot the new image goes to. |
| FortiGate | The API answers with a trusted certificate; the running partition is known; standalone path: not in a cluster; HA path: cluster health OK and `uninterruptible-upgrade` on (a warning). |
| PAN-OS | The API answers with a trusted certificate; the base release is on the firewall; the running version is kept for roll back; HA path: one active and one passive unit, link up. |
| Every other vendor | The running software is known, so it can be rolled back to. |

For the other vendors the before/after snapshot is the version and the MAC addresses on
edge ports (for the circuit check). Their alarm, environment and interface checks come later.

**Before and after snapshot (IOS / IOS-XE):** interfaces, CDP and LLDP neighbours,
port-channels, MAC address count, the MAC addresses on edge ports, stack members and version.
The MAC and ARP tables read here also update the circuit list's live locations.

**Post-checks** compare the two:
* the device runs the target version;
* interfaces that were up are still up;
* neighbours and port-channel members are back;
* the MAC count hasn't dropped by more than 20 % (a warning);
* the circuits whose MAC was on the device before are back (a warning that lists each missing
  circuit with its MAC address; see [circuits.md](circuits.md#where-each-circuit-really-is-live-location));
* the stack is complete;
* the alarm and environment checks are run again.

## The record

* **Open report** in the job window gives a printable page with:
  * the summary, the path and the units;
  * the procedure with each step's progress;
  * every check with its value and detail;
  * every override and who made it;
  * the affected circuits;
  * the full step log, including the device output.
* **Checks CSV** is the check table on its own.
* Each device's **History › Upgrade history** tab lists all its jobs (including pair jobs)
  with their reports.
* A device with upgrade history can't be deleted (disable it instead), and an image used
  by a job can't be deleted, so the record stays complete.
* Every action is also in the audit log (`firmware.job.*`) and the Activity page.

## Behind the scenes

* **Where jobs run:** in the **upgrade worker** (`netops-worker` service), a separate
  process from the web app. Restarting or upgrading the web app never touches a running
  upgrade. If the worker isn't running, the GUI says so and refuses to queue anything.
* **Software updates:** `install.sh` refuses to update NetOps while a live upgrade is
  running. Check with `sudo netops-cli upgrades-running`.
* **Settings** (in `/etc/netops/netops.env`):

  | Setting | Default | What it does |
  |---|---|---|
  | `NETOPS_UPGRADE_LIVE_PLATFORMS` | empty | Which platforms (or `platform:path`) may run live upgrades |
  | `NETOPS_UPGRADE_ABORT_TIMER_MIN` | 120 | IOS-XE auto-abort timer |
  | `NETOPS_UPGRADE_RELOAD_TIMEOUT_MIN` | 30 | How long to wait for a reload (FTD gets three times this) |
  | `NETOPS_UPGRADE_SETTLE_SECONDS` | 120 | Wait after a device is back, before the post-checks |
  | `NETOPS_UPGRADE_COPY_TIMEOUT_MIN` | 60 | Image copy and install commands |
