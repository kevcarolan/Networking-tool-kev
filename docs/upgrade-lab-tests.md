# Upgrade lab tests (sign-off before production)

NetOps' upgrade procedures have been tested against a **network simulator**
(`backend/app/demo/simnet.py`). It reproduces the commands, prompts, reloads,
failovers and the FDM API as documented by the vendors. Real devices and software
releases differ in details: prompt wording, output format, and the FDM API version. So
**every platform and path has to pass these tests on lab kit before it is switched on
for live use** (`NETOPS_UPGRADE_LIVE_PLATFORMS`).

Work through one section per platform. Tick each line, note the NetOps job number, and
keep the job reports with the sign-off. If something doesn't behave as described, send
the job report (it includes the device output), plus a **capture** of the device (below).
The fix is usually a one-line change in the platform's driver
(`backend/app/tools/firmware_upgrade/drivers/`).

### Capturing a device

One command saves the output of **every read-only command the tools send** to a device:
* the version check;
* the upgrade pre-checks, including the platform's own;
* the MAC, ARP and neighbour tables used for circuits.

```bash
sudo netops-cli capture <device>                 # uses the device's upgrade account
sudo netops-cli capture <device> --account backup
sudo cat /var/lib/netops/captures/<device>-<date>.txt
```

* It only ever sends `show`, `display`, `get` and `dir` style commands; anything else is
  refused. It never includes the running configuration.
* The top of the file says **what the tools read** from the output: the version, model and
  free space, each health check's result, and the MAC, ARP and uplink counts. Compare those
  with the device. A line that is wrong, or says "COULD NOT READ", is a reader to fix.
* **Addresses:** IP and MAC addresses are replaced with stand-ins. The same address always
  gets the same stand-in, so the tables still match up. Hostnames, interface names and
  serial numbers stay, so check the file before you send it outside your organisation.
  `--raw` keeps the real addresses.

Do one capture per platform and software train, early in the lab work. It is the quickest
way to find a reader that doesn't match the real output. Each capture also becomes a test
sample: `capture.parse_file()` reads it back, command by command, into
`app/demo/vendor_samples.py` or `app/demo/samples.py`.

## 0. Before you start

- [ ] Both services run: `systemctl status netops netops-worker`.
- [ ] The Upgrade jobs tab shows no "worker isn't running" banner.
- [ ] The lab devices are in NetOps, with a backup account and an **upgrade account** (Upgrade settings).
- [ ] Firmware › Versions › Check now reads the model and version of each device correctly.
- [ ] A capture of each lab device: `sudo netops-cli capture <device>` (see above).
- [ ] The SCP server is enabled on each device (see upgrades.md).
- [ ] The firewall allows SSH, and HTTPS to the FTDs, FortiGates and PAN-OS firewalls, from the server (`FDM_HOSTS`).
- [ ] The images are uploaded with the vendor checksum (they show "verified").
- [ ] `NETOPS_UPGRADE_LIVE_PLATFORMS` lists **only the platform under test**. Restart both services after changing it.

## 1. Every platform: the common tests

Do these for each platform before its own section. Use a **dry run** job first.

- [ ] Pre-checks: every row is plausible. Note any check that is wrong, especially a pass or fail for the wrong reason.
- [ ] Introduce a blocker (e.g. unsaved config, disable SCP). The job is **Blocked**; fix it and Re-check → Ready.
- [ ] Override a blocker with a reason: it appears in the report with your name.
- [ ] Stage image (dry run): it says it would copy. Then on a **live** job: the image is copied and the MD5 on the device passes.
- [ ] Corrupt the staged copy (delete it, or copy a different file with the same name). Stage again: the MD5 check fails and can't be overridden.
- [ ] Dry run Start → **Completed**. The Procedure tab shows each step; the log shows "DRY RUN - would …"; nothing changed on the device.
- [ ] The report opens and prints. It shows the circuits and the overrides.

## 2. IOS-XE install mode (Cat9k, standalone; then a stack if you have one)

- [ ] Pre-checks show "Device runs in install mode" and a **Rollback point** (install rollback id).
- [ ] Live Start inside the window. Confirm:
  - [ ] `install add file flash:<image>` runs; the job log shows SUCCESS.
  - [ ] `install activate auto-abort-timer 120 prompt-level none` is accepted, and the switch reloads.
    *Confirm the exact syntax on your release; adjust in `cisco_ios.py`.*
  - [ ] The job waits, sees the switch back, and runs the post-checks.
  - [ ] The banner shows "Not committed: … goes back … at HH:MM" while the post-checks run.
  - [ ] Post-checks pass → `install commit` → **Completed**. `show install summary` shows the new version committed (C).
- [ ] Failure path: before Start, shut a port that is up (or unplug a neighbour) so a post-check fails after the reload. Then:
  - [ ] the job is **Failed**, not committed;
  - [ ] **Roll back** runs `install abort prompt-level none`, the switch returns to the old version, and the post-checks pass → **Rolled back**.
- [ ] Override path: post-check failure → **Override** → Paused → **Continue** commits → **Completed with overrides**.
- [ ] Timer path (optional, use `NETOPS_UPGRADE_ABORT_TIMER_MIN=30` in the lab): leave a failed job alone past the timer. The switch reverts by itself, and the job turns **Needs attention** with that message.
- [ ] Stack: every member upgrades. "All stack members back" passes.

## 3. IOS / IOS-XE bundle mode (or a classic IOS switch)

- [ ] Pre-checks: "Device boots a single image file" and "Current image stays on flash" pass.
- [ ] Live Start: `no boot system`, `boot system flash:<new>`, `boot system <old>`, `write memory`, `reload`. The switch comes back on the new image.
- [ ] The reload question ("Save? [yes/no]", "Proceed with reload? [confirm]") is answered automatically. *If your release asks something else, note the exact text.*
- [ ] Roll back after a forced post-check failure: the switch boots the old image again.

## 4. NX-OS

- [ ] Standalone live Start:
  - [ ] the image is copied and `show file bootflash:<img> md5sum` matches;
  - [ ] `show install all impact` is recorded under "Image on the device" and parsed correctly (try an incompatible image to see it block);
  - [ ] `install all nxos bootflash:<img> non-interruptive` runs; the switch reloads and comes back;
  - [ ] post-checks pass.
- [ ] vPC pair (if you have one): set each switch as the other's peer. The pre-checks show the vPC healthy, with one primary and one secondary.
  - [ ] Live Start upgrades the **secondary** first.
  - [ ] It checks the vPC is healthy again, then upgrades the primary.
- [ ] Roll back: `install all nxos <previous image>`.

## 5. ASA

- [ ] Standalone: `boot system` lines are set (new first, old as fallback), `write memory`, `reload noconfirm`; the ASA comes back on the new version.
  *Confirm that `clear configure boot system` is accepted on your release.*
- [ ] Failover pair: in NetOps, the **active address** device has the **standby address** device as its peer. Then:
  - [ ] pre-checks show "One active and one standby unit";
  - [ ] the image is staged on **both** units;
  - [ ] `boot system` on the active unit replicates to the standby;
  - [ ] `write memory` and `failover exec mate write memory` both run;
  - [ ] `failover reload-standby`: the standby comes back as **Standby Ready** on the new version, and its post-checks pass;
  - [ ] `failover active` on the standby address: the upgraded unit takes over, and traffic continues (watch a continuous ping through the firewall);
  - [ ] `failover reload-standby`: the other unit comes back on the new version, and both units' post-checks pass.
- [ ] Roll back the pair: the same sequence, back to the old image.

## 6. FTD (FDM)

These steps confirm the **FDM API** behaves as the driver expects. The endpoint paths are
in `ENDPOINTS` in `backend/app/tools/firmware_upgrade/fdm.py`; compare them with your
FDM's API Explorer (`https://<ftd>/#/api-explorer`).

- [ ] Upgrade settings → **Fetch from the device**: the fingerprint matches the FDM certificate. Save it.
- [ ] Pre-checks:
  - [ ] "FDM API reachable…" passes;
  - [ ] make a change in FDM without deploying it: "No undeployed changes in FDM" fails; deploy, then Re-check;
  - [ ] HA path: "HA pair healthy and in sync" passes.
- [ ] Replace the FTD certificate (or point the device at another FTD): pre-checks fail with "certificate changed".
- [ ] Stage image: the package appears in FDM › Device › Updates.
- [ ] Standalone live Start:
  - [ ] the readiness check starts, and its result is recorded;
  - [ ] **note the field FDM uses for the readiness result** (`readinessCheckState`?) if the job waits for 30 minutes without one;
  - [ ] the upgrade starts; FDM reboots; the job waits until FDM reports the new version (it allows up to 90 minutes);
  - [ ] post-checks pass.
- [ ] HA pair (your current design): set each FTD as the other's peer, each with its own trusted fingerprint. Then live Start:
  - [ ] the **standby** unit upgrades first;
  - [ ] HA is healthy again;
  - [ ] **HA failover**: the upgraded unit becomes active, and traffic continues;
  - [ ] the other unit upgrades;
  - [ ] the final HA check passes.
- [ ] Roll back: FDM **revert upgrade**. The unit returns to the previous version.

## 7. AlliedWare Plus (standalone; then a VCStack)

- [ ] The SCP copy works. *Note where the file lands and the remote path used. If AW+ wants `flash:/<file>`, set the device's file system to `flash:/` in Upgrade settings.*
- [ ] The size check on the device passes (AW+ has no MD5 command).
- [ ] Live Start: `boot system flash:/<new>.rel`, `boot system backup flash:/<old>.rel`, `write memory`, `reload` (the reboot question is answered). The switch comes back on the new release.
- [ ] VCStack: every member is on the new release afterwards.
- [ ] Roll back: the switch boots the old release again.

## 7a. Circuit locations (MAC and ARP tables)

- [ ] Circuits › **Scan network now**: every lab device shows as read under the tiles (no errors).
- [ ] A device plugged into an access port shows **Matches** (or **Found** if the sheet has no
      port). Move it to another port, scan again: **Moved**, with the new port.
- [ ] A MAC learned through an uplink or port-channel is *not* shown on the uplink.
- [ ] A row with only an IP is found through ARP ("MAC … from ARP").
- [ ] An IP phone port: the PC behind the phone is located on that port.
- [ ] Upgrade job: unplug one circuit before the post-checks. "Circuits seen before the upgrade
      are back" is a warning that names it with its MAC; the job still commits.
- If any table is read wrong, send `show mac address-table` (and the CDP/LLDP detail) from
  that device: the parsers are in `backend/app/tools/circuits/live.py`.

## 7b. Other vendors: backups, versions and circuit locations

For each platform added in October 2026 (Arista, Juniper, Fortinet, Palo Alto, Check Point,
HPE Aruba, Dell, Extreme, Cisco IOS-XR and small business, MikroTik, Ubiquiti, Huawei).
Their output readers were written from vendor documentation, so check them on one real
device each. Commands and accounts: [vendors.md](vendors.md).

- [ ] **Backup:** `sudo netops-cli backup <device>` works. Run it twice with no change on the
      device: the second run shows **no change**. (If it does show one, the diff shows which
      line changes on every run.)
- [ ] The backup holds the whole configuration, including secrets where the vendor shows
      them (FortiGate: masked on purpose).
- [ ] **Capture:** `sudo netops-cli capture <device>` (see "Capturing a device" above). Its
      summary shows the right version, model and serial, the HA or cluster role on
      firewalls, and sensible MAC/ARP counts on switches. Send the file either way: it
      replaces the documentation sample.
- [ ] **Circuits** (switches): the 7a tests above. Also check that a port-channel or LAG and
      an LLDP uplink to another switch are *not* used as a circuit's location.
- If anything is read wrong, the capture file has every output needed. Replace the sample in
  `backend/app/demo/vendor_samples.py` with the real output and fix the reader so the test passes.

## 8. Operations

- [ ] **Stop after this step** during a live job (e.g. while it copies): it pauses before the next step; Continue finishes it.
- [ ] Window end: make a window that ends while the job is copying. The job pauses before the reload; Continue is refused outside the window.
- [ ] `sudo systemctl restart netops` during a live job: the job carries on (it runs in the worker).
- [ ] `sudo systemctl stop netops-worker` during a copy: the job pauses before its next step (or, if the copy is cut off, shows Needs attention). Start the worker again.
- [ ] Reinstall the bundle while a live job runs: `install.sh` refuses ("a live upgrade job is running").

## 9. Other vendors: upgrade jobs

Arista, Junos, ArubaOS-Switch, Aruba AOS 8, Dell OS10, Extreme EXOS, Huawei VRP, Cisco IOS-XR,
MikroTik and EdgeRouter. Do section 7b for the platform first, then section 1 (the common
tests), then these. Procedures and roll back: [upgrades.md](upgrades.md#paths-per-platform).

For every one of these platforms:
- [ ] **Copy:** Stage image works and lands where the procedure expects it (note the path). The
      check after the copy (MD5 or size) passes; a copy that is cut off fails it.
- [ ] **Prompts:** every question the device asks during the upgrade is answered (the job
      log shows the device output). Note any question that made a step time out.
- [ ] **Live Start:** the device comes back on the new version; the post-checks pass.
- [ ] **Roll back:** make the post-check fail (e.g. use a standard with the wrong version),
      roll back, and the device comes back on the previous version.

Platform notes to confirm:
- [ ] **Arista MLAG:** the secondary is upgraded first and the job waits for the MLAG to be
      active before the primary.
- [ ] **Junos Virtual Chassis:** every member is on the new version; `request system software
      rollback` is available on this release.
- [ ] **ArubaOS-Switch:** the SCP upload goes into `/os/secondary` (or primary) directly; the
      `show flash` size matches the file.
- [ ] **Aruba AOS 8:** the copy to flash works with the controller's SCP (Netmiko); `copy flash:
      ... system: partition` and `boot system partition` are run from enable mode.
- [ ] **Dell OS10:** `home://` is the upgrade account's home folder; `show image status` shows
      "Completed: No error" when the install has finished.
- [ ] **Extreme EXOS:** `install image ... reboot` installs into the other partition and asks no
      question the job doesn't answer.
- [ ] **Huawei VRP:** `dir flash:/<file>` shows the size; `startup system-software` and `reboot`
      work on this model (S series or CloudEngine).
- [ ] **IOS-XR:** the right path for the release (install add / activate, or install replace);
      `show install request` shows when the operation has finished; roll back before the
      commit brings back the committed software.
- [ ] **MikroTik:** the `.npk` goes to the right folder for the model (root or `flash/`); the
      RouterBOARD firmware step runs; roll back stops with the "by hand" instruction.
- [ ] **EdgeRouter:** `md5sum` works from the upgrade account; `add system image` and `set system
      image default-image` work.

## 10. Firewalls: FortiGate and PAN-OS

Do section 7b for the platform first. Trust the certificate in each device's upgrade settings
(Fetch from the device, compare with what the device shows), and allow HTTPS to it from
the server (`FDM_HOSTS`).

**FortiGate (standalone, then an HA cluster):**
- [ ] The API pre-check passes, with a REST API token (in the credential's enable secret) and
      without one (username and password). Note which you will use.
- [ ] Live Start: the image is accepted and the FortiGate reboots onto the new version.
      Note how long the upload takes, and check the job log shows the API's answer *before*
      the reboot. (If the connection drops instead, the job stops at that step although the
      upgrade goes ahead: report it, the step then needs to treat the drop as "rebooting".)
- [ ] `diagnose sys flash list` shows the partitions; roll back with `execute set-next-reboot`
      brings back the previous version. With VDOMs: check the commands work from the
      account's context (they may need `config global`).
- [ ] HA cluster with `uninterruptible-upgrade`: the job waits while the cluster upgrades
      itself, and finishes when every member is on the new version and HA health is OK.

**PAN-OS (standalone, then an HA pair):**
- [ ] The API pre-check passes; the base release check is right for a maintenance release.
- [ ] Stage image uploads the software; the firewall lists it as downloaded.
- [ ] Live Start: the install job finishes, the firewall restarts on the new version.
- [ ] Roll back installs the previous version and restarts.
- [ ] HA pair: the passive unit is upgraded first; suspending the active unit fails the pair
      over to it; both end on the new version and the pair is healthy (active/passive).

## Sign-off

| Platform / path | Lab job numbers | Tested by | Date | Live enabled |
|---|---|---|---|---|
| IOS-XE install | | | | |
| IOS bundle | | | | |
| NX-OS standalone | | | | |
| NX-OS vPC pair | | | | |
| ASA standalone | | | | |
| ASA failover pair | | | | |
| FTD standalone | | | | |
| FTD HA pair | | | | |
| AW+ / VCStack | | | | |
