# Project progress

The single place to see where Networking-tool-kev is and what's next. Update it at the end
of every working session.

**Now:** Clean copy of NetOps Tools (config backup, firmware and upgrade jobs, circuits with
live MAC/ARP locations, users and activity). No PRTG integration; generic sample data.
**Next:** Decide the product name and licence; then database migrations (Alembic) and the first-run setup screen.

## Roadmap

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

## Open questions

- Product name?
- Licence model: sold, subscription, or open source with paid support?

## Session log

| Date | Where | What happened |
|---|---|---|
| 2026-10-07 | Networking-tool-kev | Repository created from NetOps Tools (main @ 29e6bb1): PRTG removed, sample data made generic |
| 2026-10-07 | Networking-tool-kev | Tests run on every pull request (GitHub Actions); product name made a setting |
