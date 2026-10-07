# Project progress

The single place to see where Networking-tool-kev is and what's next. Update it at the end
of every working session.

**Now:** Clean copy of NetOps Tools (config backup, firmware and upgrade jobs, circuits with
live MAC/ARP locations, users and activity). No PRTG integration; generic sample data.
**Next:** Multi-vendor support, as planned in [plans/multi-vendor.md](plans/multi-vendor.md): PR A (backup, versions, circuits for every new platform), then PR B (SSH/SCP upgrade drivers), then PR C (firewall upgrades via API).

## Roadmap

### Multi-vendor ([plans/multi-vendor.md](plans/multi-vendor.md))
- [x] PR A: Arista, Juniper, Fortinet, Palo Alto, Check Point, Aruba (CX, ProCurve, AOS 8 controllers), Dell OS10, Extreme, Cisco IOS-XR and SMB, MikroTik, Ubiquiti EdgeOS, Huawei: backup, versions, circuits ([vendors.md](vendors.md)). Readers built from vendor docs: check each on a real device (lab tests 7b)
- [ ] PR B: upgrade drivers for the SSH/SCP platforms
- [ ] PR C: firewall upgrades (FortiGate and PAN-OS via API, Check Point CPUSE)

### Product
- [ ] Product name and branding (GUI title, logo, docs). The name is now one setting,
  `NETOPS_PRODUCT_NAME`; still to do: choose the name, a logo, and rename the docs
- [ ] Licence terms (EULA, or open source plus support)
- [ ] First-run setup screen (admin account, AD settings, certificate) instead of editing `netops.env`
- [ ] Installer for internet-connected and air-gapped sites
- [ ] Customer documentation (install, admin guide, user guide)
- [ ] Optional: multi-site support, licence keys

### Platform (inherited)
- [x] Core: AD and local login, per-area permissions, device inventory, encrypted credentials, audit and activity report
- [x] Air-gapped install kit, hardening guide and templates, nightly backups
- [x] GitHub Actions: run the tests on every pull request (Python 3.11 and 3.14)
- [ ] Add database migrations (Alembic) before the first change to an existing table

### Tools (inherited)
- [x] Config backup
- [x] Firmware: version report, standards, image library, upgrade jobs for every platform
- [x] Circuits: Excel import, live location from MAC/ARP tables
- [ ] Lab-test the upgrade paths and the MAC/ARP parsing ([upgrade-lab-tests.md](upgrade-lab-tests.md))

## Decisions

| Date | Decision | Why |
|---|---|---|
| 2026-10-07 | Separate repository from the work version, started from a clean copy without history | Product and work tool evolve independently |
| 2026-10-07 | No PRTG integration; monitoring through `/api/health` and syslog forwarding | Customers use different monitoring systems |
| 2026-10-07 | Product name comes from `NETOPS_PRODUCT_NAME` (default "NetOps Tools"); messages say "inventory" instead of naming the product | Name not chosen yet; renaming or rebranding for a customer is a setting, not a code change |
| 2026-10-07 | Readers for the new vendors are built from vendor documentation, with samples in `tests/vendor_samples.py` | No lab kit yet; each is checked on a real device (lab tests 7b) and its sample replaced |
| 2026-10-07 | FortiGate backups mask `ENC` secrets | FortiOS re-encrypts them on every show, so every backup would look changed; full restores use FortiGate's own backup |
| 2026-10-07 | `ubiquiti_edgeos` is EdgeRouter only (Netmiko `ubiquiti_edgerouter`) | EdgeSwitch has a different CLI; UniFi needs its controller API |

## Open questions

- Product name?
- Licence model: sold, subscription, or open source with paid support?
- FortiGate backups: is masking the secrets acceptable, or should the backup use FortiGate's own encrypted backup file instead?
- The AlliedWare Plus circuit-location fix (ports named `port1.0.x` were treated as port-channels) also applies to the work version; copy it across?

## Session log

| Date | Where | What happened |
|---|---|---|
| 2026-10-07 | Networking-tool-kev | Repository created from NetOps Tools (main @ 29e6bb1): PRTG removed, sample data made generic |
| 2026-10-07 | Networking-tool-kev | Tests run on every pull request (GitHub Actions); product name made a setting |
| 2026-10-07 | Networking-tool-kev | Multi-vendor PR A: 15 platforms for backups, version checks and circuit locations; vendor groups in the GUI; fixed AlliedWare Plus circuits never being located |
