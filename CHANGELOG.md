# What's new

Each version in plain words, newest first. Versions are MAJOR.MINOR.PATCH
([docs/releasing.md](docs/releasing.md)): a new **minor** version brings new features, a
**patch** only fixes, and a new **major** version needs a manual step on upgrade (it says
which). Upgrading: install the new bundle as in the install guide; the database updates
itself, and the installer refuses to go back to an older version.

## 2.1.0 (not released yet)

**New**
- **SNMP-only devices**: UPS cards, PDUs, room probes and other devices you monitor but
  never log in to. Added with no credential; no backups, version checks or upgrades;
  monitored with ping, SNMP and sensors. Setup help for each type (Monitoring and Syslog).
- **Version numbers**: the installed version is shown in the top bar (after signing in), in
  the report and with `netops-cli version`; bundles are named by version; the installer
  says "Upgrading from … to …" and refuses to install an older version.

- **Stacks, HA and optics**: the Monitoring page now shows each switch in a Cisco stack, the
  units of ASA, FortiGate and Palo Alto HA pairs, Cisco optics' light levels and the PoE
  budget used. A stack member or HA peer lost, an optic past its own limits (on a port that
  is up) or PoE nearly used up is a hardware problem; a change of active unit is a
  **Failover** event, emailed with the monitoring alerts.

**Fixed**
- The Add/Edit device window (and other two-column forms) no longer runs off the right-hand
  side, hiding the Save button.

## 2.0.0 (2026-10-15)

The first release under the NetCairn name (versions before it were dated builds).

- **Config backups**: scheduled SSH backups with history and differences, compliance rules
  checked after each backup, config change alerts naming who changed it.
- **Firmware**: version report against your standards, image library, upgrade jobs with
  pre-checks, dry runs, maintenance windows and post-checks, for Cisco, Allied Telesis and
  (lab sign-off pending) Arista, Juniper, Fortinet, Palo Alto, HPE Aruba, Dell, Extreme,
  MikroTik, Ubiquiti and Huawei.
- **Circuits**: the circuit list from Excel or CSV, and where each circuit is now from the
  switches' MAC and ARP tables.
- **Syslog**: a receiver on port 514 (and TLS on 6514), a search page, and device setup help.
- **Monitoring**: ping and SNMP up/down, response times and restarts; interfaces and
  traffic with graphs; hardware health (CPU, memory, temperatures, fans, power supplies);
  custom SNMP sensors with thresholds; Cisco Meraki through the Dashboard API; the network
  map coloured by status and load; alerts and the wall display.
- **Inventory, sites and racks**: every device and item with custom columns, import and
  export; a site list; buildings, floors and rooms with rack elevations.
- **Calendar** of changes, maintenance, freezes and upgrades with clash warnings;
  **search** across everything; the scheduled **report**; **email alerts**.
- **Users**: Active Directory and local users with per-area permissions, two-factor
  sign-in, and the activity log.
- **Installing**: offline bundle for air-gapped Ubuntu servers, the online installer, the
  first-run setup screen, licences with a 60-day trial, and the demo.
