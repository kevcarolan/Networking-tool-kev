# Plan: multi-vendor support

Agreed with the owner on 2026-10-07: build **everything at once** (backup, versions, circuits and upgrade procedures) for all the vendors below, in three PRs (A, B, C). Live upgrades stay off per platform until lab sign-off.


## Context
The user wants the product version (kevcarolan/Networking-tool-kev) to cover many more vendors and platforms: config backup, version, model and serial reading, circuits (MAC/ARP), and **upgrade procedures for every vendor in this round**. The work repo is unchanged.
- Chosen vendor groups: Arista + Juniper, firewalls, campus switching, Cisco extras + others, **plus Aruba**. Aruba switches are already in "campus", so Aruba **wireless controllers** (AOS 8 Mobility Controllers and Conductor) are added as well.
- The work is done in the product repo, by the **"Networking-tool-kev" session**, so the two projects stay separate. After approval, this plan is sent to that session to carry out.
- All new upgrade procedures are built from vendor documentation and the network simulator. Live upgrades stay off per platform (`NETOPS_UPGRADE_LIVE_PLATFORMS`) until each passes lab tests, as with Cisco today.

## Platforms to add (key, Netmiko type, example chassis)
| Vendor | Platform key | Netmiko | Chassis / families |
|---|---|---|---|
| Arista | arista_eos | arista_eos | 720XP campus, 7050X3/7060X, 7280R3, 7500R3 |
| Juniper | juniper_junos | juniper_junos | EX2300/3400/4100/4400, QFX5120, MX204/MX480, SRX300/1500/4600 |
| Fortinet | fortinet_fortios | fortinet | FortiGate 40F–600F, 1000F+, VM |
| Palo Alto | paloalto_panos | paloalto_panos | PA-400/1400/3400/5400, VM-Series |
| Check Point | checkpoint_gaia | checkpoint_gaia | Quantum 3600–9800, open servers (Gaia OS only; policy is on the management server) |
| HPE Aruba | aruba_aoscx | aruba_aoscx | CX 6000/6100/6200/6300/6400, 8325/8360/8400 |
| HPE Aruba | aruba_osswitch | hp_procurve | 2530/2930F/2930M/3810M/5400R (ProCurve) |
| HPE Aruba | aruba_aos8 | aruba_os | Mobility Controllers 7000/9000/9200, Mobility Conductor |
| Dell | dell_os10 | dell_os10 | S4100/S5200/Z9200 (OS10) |
| Extreme | extreme_exos | extreme_exos | X440-G2/X460-G2/X465/X590 (EXOS / Switch Engine) |
| Cisco | cisco_xr | cisco_xr | ASR 9000, NCS 540/5500, 8000 |
| Cisco | cisco_smb | cisco_s300 | Catalyst 1200/1300, CBS250/350, SG350 |
| MikroTik | mikrotik_routeros | mikrotik_routeros | CCR2004/2116, CRS3xx, RB5009, hAP |
| Ubiquiti | ubiquiti_edgeos | ubiquiti_edge | EdgeRouter, EdgeSwitch (UniFi needs its controller API: later) |
| Huawei | huawei_vrp | huawei | CloudEngine S5700/S6700, CE6800/CE12800, AR routers |

## Phased build (one PR each in the product repo; all tests must pass)

### PR A – Inventory, backup, versions, circuits (every new platform)
- **`core/platforms.py`:**
  - add a `vendor` field (to group in the GUI and the image library);
  - backup commands, enable/no-enable, and volatile lines for each platform. For example:
    - Junos `show configuration | display set`;
    - EOS `show running-config`;
    - FortiOS `show full-configuration`;
    - PAN-OS `set cli config-output-format set` + `show`;
    - RouterOS `/export terse`;
    - VRP `display current-configuration`;
    - EXOS `show configuration`;
    - OS10 `show running-configuration`.
- **`firmware_upgrade/facts.py`:** per-platform `show version` parsers (version, model, serial, image, flash free, HA role). Sample outputs go in `tests/firmware_samples.py`.
- **`circuits/live.py`:**
  - MAC table, ARP and neighbour commands and parsers per switching/routing platform (e.g. EOS `show mac address-table`, Junos `show ethernet-switching table`, AOS-CX `show mac-address-table`, VRP `display mac-address`, ProCurve `show mac-address`, EXOS `show fdb`, RouterOS `/interface bridge host print`);
  - interface-name normalisation for each vendor (`importer.normalize_port`).
- **Docs:** vendor support matrix, plus a per-vendor account and SCP/API setup table.

### PR B – Upgrade drivers: SSH/SCP-based platforms
One driver per platform in `firmware_upgrade/drivers/`, each with paths, pre-checks, steps and roll back:
- **Arista EOS:**
  - standalone: copy .swi, verify MD5, `boot system`, `write`, `reload`; roll back to the previous .swi;
  - MLAG pair: the peer first, `show mlag` healthy, then the other.
- **Juniper Junos:**
  - standalone: `request system software add … reboot`; roll back with `request system software rollback`;
  - EX Virtual Chassis: `member all`, or NSSU;
  - SRX chassis cluster: node by node.
- **Aruba AOS-CX:**
  - copy to the secondary partition, `boot system secondary`; roll back to the primary;
  - VSX pair: the secondary first, then `show vsx status`.
- **ArubaOS-Switch:** copy to flash secondary, `boot system flash secondary`; stack-aware.
- **Aruba AOS 8 controllers:**
  - copy to the non-boot partition, `boot system partition`, reload;
  - cluster: one controller at a time.
- **Dell OS10:**
  - `image install`, `boot system standby`, reload;
  - VLT pair: the secondary first.
- **Extreme EXOS:**
  - install to the inactive partition, `use image`, reboot;
  - stack-aware.
- **Huawei VRP:**
  - copy .cc, `startup system-software`, reboot;
  - stack/CSS: one member at a time.
- **Cisco IOS-XR:** `install add`, `install activate`, then commit after the post-checks (same model as IOS-XE).
- **Cisco SMB (Catalyst 1200/1300, CBS):** copy to the inactive image, `boot system image-N`, reload.
- **MikroTik RouterOS:** upload the .npk over SFTP, reboot, then upgrade the RouterBOARD firmware; roll back by downgrading.
- **Ubiquiti EdgeOS:** `add system image`, reboot; roll back with `set system image default-image`.

For every driver:
- extend `tests/fake_network.py` with each new command;
- add end-to-end tests for each path (dry run and live, a failure path, roll back).

### PR C – Upgrade drivers: firewalls (API-based where the vendor requires it)
- **FortiGate:**
  - backup and upgrade over the REST API (an API token per device, with a pinned certificate fingerprint as for FDM);
  - upload the image, upgrade, wait for the new version;
  - HA: uninterruptible upgrade, then check the HA status;
  - roll back: boot the alternate partition.
- **Palo Alto PAN-OS:**
  - XML API (an API key, pinned fingerprint);
  - pre-check that the base image is present (x.y.0 before a maintenance release);
  - upload, install, reboot, wait;
  - HA pair: suspend the passive unit, upgrade it, fail over, then the other unit.
- **Check Point Gaia:**
  - CPUSE over SSH (`installer import`, `installer verify`, `installer install`);
  - ClusterXL: the standby member first;
  - document that the management server and policy are out of scope.
- Shared API client code, in the same style as `firmware_upgrade/fdm.py`.

## Shared changes
- **Settings:** the `NETOPS_UPGRADE_LIVE_PLATFORMS` names are documented for the new keys.
- **Image library:** model patterns per vendor (e.g. `EX4400-*`, `PA-14*`), and the vendor checksum types used (MD5, SHA-256, SHA-512).
- **Lab tests:** `docs/upgrade-lab-tests.md` gets a section per vendor.
- **Bundle:** no new Python dependencies expected (Netmiko already supports these platforms). Confirm with `build-bundle.sh` that the wheels resolve.

## Verification
- Run the full `pytest` after each PR. The existing 177 tests stay green.
- New tests for each platform:
  - facts and MAC/ARP parsers against sample output;
  - backup volatile-line filtering;
  - every upgrade path through the simulator (dry run, live, post-check failure, roll back, HA/pair ordering).
- A GUI check in the browser: the new platforms appear in Add device and the image library groups.
- Lab sign-off per vendor before adding it to `NETOPS_UPGRADE_LIVE_PLATFORMS`.

