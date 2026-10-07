# Project progress

The single place to see where Networking-tool-kev is and what's next. Update it at the end
of every working session.

**Now:** Clean copy of NetOps Tools (config backup, firmware and upgrade jobs, circuits with
live MAC/ARP locations, users and activity). No PRTG integration; generic sample data.
**Next:** Multi-vendor support, as planned in [plans/multi-vendor.md](plans/multi-vendor.md): PR A (backup, versions, circuits for every new platform), then PR B (SSH/SCP upgrade drivers), then PR C (firewall upgrades via API).

## Roadmap

### Multi-vendor ([plans/multi-vendor.md](plans/multi-vendor.md))
- [ ] PR A: Arista, Juniper, Fortinet, Palo Alto, Check Point, Aruba (CX, ProCurve, AOS 8 controllers), Dell OS10, Extreme, Cisco IOS-XR and SMB, MikroTik, Ubiquiti EdgeOS, Huawei: backup, versions, circuits
- [ ] PR B: upgrade drivers for the SSH/SCP platforms
- [ ] PR C: firewall upgrades (FortiGate and PAN-OS via API, Check Point CPUSE)

### Product
- [ ] Product name and branding (GUI title, logo, docs)
- [ ] Licence terms (EULA, or open source plus support)
- [ ] First-run setup screen (admin account, AD settings, certificate) instead of editing `netops.env`
- [ ] Installer for internet-connected and air-gapped sites
- [ ] Customer documentation (install, admin guide, user guide)
- [ ] Optional: multi-site support, licence keys

### Platform (inherited)
- [x] Core: AD and local login, per-area permissions, device inventory, encrypted credentials, audit and activity report
- [x] Air-gapped install kit, hardening guide and templates, nightly backups
- [ ] GitHub Actions: run the tests on every pull request
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

## Open questions

- Product name?
- Licence model: sold, subscription, or open source with paid support?

## Session log

| Date | Where | What happened |
|---|---|---|
| 2026-10-07 | Networking-tool-kev | Repository created from NetOps Tools (main @ 29e6bb1): PRTG removed, sample data made generic |
