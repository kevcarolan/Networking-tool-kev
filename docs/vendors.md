# Supported vendors and platforms

What each tool can do on each platform, the commands it runs, and the device account it
needs. Every command in this page is read-only (`show` or the vendor's equivalent).

> **Status:** Cisco IOS/IOS-XE, NX-OS, ASA, FTD and Allied Telesis AlliedWare Plus are
> complete. The other platforms (added October 2026) do **backups, version checks and
> circuit locations**, and most of them **upgrade jobs** too. They were written from the
> vendors' documentation and tested on the simulator, so each one must be checked against a
> real device first ([upgrade-lab-tests.md](upgrade-lab-tests.md), sections 7b and 9). Until
> then, keep their upgrade jobs as dry runs. Upgrade procedures: [upgrades.md](upgrades.md#paths-per-platform).

## What works where

| Vendor | Platform (key) | Backup | Version, model, serial | Circuits: MAC table | Circuits: ARP | Upgrade jobs |
|---|---|---|---|---|---|---|
| Cisco | IOS / IOS-XE (`cisco_ios`) | yes | yes | yes | yes | yes |
| Cisco | NX-OS (`cisco_nxos`) | yes | yes | yes | yes | yes |
| Cisco | ASA (`cisco_asa`) | yes | yes, failover role | no | yes | yes |
| Cisco | FTD managed by FDM (`cisco_ftd`) | yes | yes, HA role | no | yes | yes |
| Cisco | IOS-XR (`cisco_xr`) | yes | yes | no | yes | lab test first |
| Cisco | Catalyst 1200/1300, CBS, SG (`cisco_smb`) | yes | yes | yes | yes | later (image pull) |
| Allied Telesis | AlliedWare Plus (`allied_awplus`) | yes | yes | yes | yes | yes |
| Arista | EOS (`arista_eos`) | yes | yes, free flash | yes | yes | lab test first; MLAG pairs |
| Juniper | Junos: EX, QFX, MX, SRX (`juniper_junos`) | yes | yes | yes (EX, QFX) | yes | lab test first; not SRX clusters |
| Fortinet | FortiGate (`fortinet_fortios`) | yes (see below) | yes, HA mode | no | yes | later |
| Palo Alto | PAN-OS (`paloalto_panos`) | yes | yes, HA state | no | yes | later |
| Check Point | Gaia gateways (`checkpoint_gaia`) | yes (Gaia OS only) | yes, cluster state | no | yes | later |
| HPE Aruba | AOS-CX (`aruba_aoscx`) | yes | yes, active image | yes | yes | later (image pull) |
| HPE Aruba | ArubaOS-Switch / ProCurve (`aruba_osswitch`) | yes | yes | yes | yes | lab test first |
| HPE Aruba | Mobility Controller / Conductor, AOS 8 (`aruba_aos8`) | yes | yes | no | yes | lab test first |
| Dell | SmartFabric OS10 (`dell_os10`) | yes | yes (service tag) | yes | yes | lab test first |
| Extreme | EXOS / Switch Engine (`extreme_exos`) | yes | yes, booted image | yes | yes | lab test first |
| MikroTik | RouterOS (`mikrotik_routeros`) | yes | yes, free storage | yes (bridge hosts) | yes | lab test first; roll back by hand |
| Ubiquiti | EdgeRouter, EdgeOS (`ubiquiti_edgeos`) | yes | yes | no | yes | lab test first |
| Huawei | VRP: S series, CloudEngine, AR (`huawei_vrp`) | yes | yes | yes | yes | lab test first |

Not supported yet: Ubiquiti EdgeSwitch and UniFi (UniFi is managed through its controller,
not SSH), and the Check Point management server (policy lives there, not on the gateway).

## Commands per platform

| Platform | Backup | Version check | Circuit locations |
|---|---|---|---|
| Cisco IOS-XR | `show running-config` | `show version`, `show inventory` | `show arp vrf all` |
| Cisco small business | `show running-config` | `show version`, `show inventory` | `show mac address-table`, `show arp`, `show lldp neighbors` |
| Arista EOS | `show running-config` | `show version`, `dir flash:` | `show mac address-table`, `show ip arp vrf all`, `show lldp neighbors detail` |
| Juniper Junos | `show configuration \| display set` | `show version`, `show chassis hardware` | `show ethernet-switching table`, `show arp no-resolve`, `show lldp neighbors` |
| FortiGate | `show full-configuration` | `get system status` | `get system arp` |
| PAN-OS | `set cli config-output-format set`, then `show` in configure mode | `show system info`, `show high-availability state` | `show arp all` |
| Check Point Gaia | `show configuration` | `show version all`, `show asset all`, `show cluster state` | `show arp dynamic all` |
| AOS-CX | `show running-config` | `show version`, `show system` | `show mac-address-table`, `show arp all-vrfs`, `show lldp neighbor-info detail` |
| ArubaOS-Switch | `show running-config` | `show version`, `show system`, `show modules` | `show mac-address`, `show arp`, `show lldp info remote-device detail` |
| Aruba AOS 8 | `show running-config` | `show version`, `show inventory` | `show arp` |
| Dell OS10 | `show running-configuration` | `show version`, `show inventory` | `show mac address-table`, `show ip arp`, `show lldp neighbors detail` |
| Extreme EXOS | `show configuration` | `show version`, `show switch` | `show fdb`, `show iparp`, `show lldp neighbors detailed` |
| MikroTik RouterOS | `/export terse` | `/system resource print`, `/system routerboard print` | `/interface bridge host print terse`, `/ip arp print terse`, `/ip neighbor print terse` |
| Ubiquiti EdgeOS | `show configuration commands` | `show version` | `show arp` |
| Huawei VRP | `display current-configuration` | `display version`, `display esn` | `display mac-address`, `display arp all`, `display lldp neighbor` |

The Cisco and Allied Telesis commands are in [firmware.md](firmware.md) and
[circuits.md](circuits.md).

**Lines left out of backups.** Lines that change on every run would make every backup look
like a change, so they are removed: timestamps ("Last commit", "Time:", "Exported by"),
the RouterOS export header, the IOS-XR time stamp, and the FortiGate file counters
(`#conf_file_ver`, `#buildno`).

**FortiGate secrets.** FortiOS encrypts each password and key again, with a new salt,
every time the configuration is shown. So the backup replaces each `ENC ...` value with
`ENC <encrypted>`. The backup still shows which settings have a secret and when one is
added or removed. But to restore a FortiGate from it, you have to type the secrets in
again. Keep FortiGate's own encrypted backups (System › Configuration › Backup) if you
need a full restore.

**Uplinks on the new switches.** A MAC address learned on an uplink isn't where the device
is, so uplinks are ignored when locating a circuit. They are found as follows:
* aggregated links by name: `Po`, `Port-Channel`, Junos `ae`, AOS-CX `lag`, ProCurve `Trk`,
  Huawei `Eth-Trunk`, MikroTik `bond`;
* LLDP neighbours that are a switch or router (not a phone or access point). Junos doesn't
  list capabilities in `show lldp neighbors`, so a Junos neighbour counts as an uplink when
  its port has a switch-style name (`Ethernet1`, `ge-0/0/1`, `Gi1/0/1`, `1/1/1`).

**Port names.** Short and long forms match, as on Cisco: Arista `Et5` = `Ethernet5`, Huawei
`GE0/0/5` = `GigabitEthernet0/0/5`, `XGE0/0/1` = `XGigabitEthernet0/0/1`, Dell
`ethernet1/1/5` = `Eth1/1/5`. Junos units are ignored: `ge-0/0/5.0` = `ge-0/0/5`.

## The device account

Use a dedicated backup account (ideally through TACACS+ or RADIUS), as for Cisco. It
needs enough rights to show the **full** configuration; many read-only roles hide parts of
it. Check each platform with `python -m app.cli backup <device>` and
`python -m app.cli firmware-check <device> --raw` before rolling out.

| Platform | Account |
|---|---|
| Arista EOS | Privilege 15, or an enable secret in the credential profile. |
| Juniper Junos | A login class with `view` and `view-configuration`. Without `view-configuration`, secrets show as `## SECRET-DATA`. |
| FortiGate | An administrator with a read-only profile. With VDOMs, a global administrator. |
| PAN-OS | Superuser (read-only), or an admin role that allows configure mode for `show`. |
| Check Point Gaia | A Gaia user whose shell is **clish** (not bash), with a read-only role covering all features. |
| AOS-CX | A user in a group that can run `show running-config`. Check this in the lab: the built-in operators group can't. |
| ArubaOS-Switch | The manager level: put the manager password in the enable secret. |
| Aruba AOS 8 | A management user with a read-only role, plus the enable password. |
| Dell OS10 | The `netadmin` or `sysadmin` role (`netoperator` can't show the configuration). |
| Extreme EXOS | An admin-level account (user-level accounts can't show the configuration). |
| Cisco IOS-XR | A user group with read access to the configuration. |
| Cisco small business | Privilege 15, or an enable secret. |
| MikroTik RouterOS | A group with `read`, `ssh` and `sensitive`. Without `sensitive`, `/export` leaves out the secrets. |
| Ubiquiti EdgeOS | An admin-level account. |
| Huawei VRP | Level 3 (management), so `display current-configuration` is allowed. |

SSH must be allowed from the server to each device (TCP 22). Nothing else is needed for
backups, version checks, circuit locations or the upgrade jobs above: the image is copied
over the same SSH connection (SCP). Some devices need their SCP server switched on first
([upgrades.md](upgrades.md)). Upgrades use a separate **upgrade account** with the rights to
copy files, change the boot setting and reload. Firewall upgrades (later) will need HTTPS to
the FortiGate and PAN-OS APIs.
