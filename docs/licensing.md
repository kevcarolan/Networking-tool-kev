# Licences

For the owner: how licences work, how to make them, and what customers see.

## How it works

* A licence is a short block of text, signed with the owner's **signing key**. It says:
  * who it is for;
  * the last day it is valid;
  * the most devices it covers;
  * **which tools it unlocks** (its *modules*);
  * optionally, the one server it is for (its **installation ID**).
* The server checks the signature itself, so nothing is sent anywhere. It works the same on
  air-gapped sites. Changing any part of the text breaks the signature.
* An admin pastes the licence on the **Settings** page.

| State | What works |
|---|---|
| **Trial**: the first 60 days of a new install (or of an install upgraded to this version) | Everything |
| **Licensed** | Everything, up to the licence's number of devices. Admins see a notice 30 days before the end date |
| **Trial over, or licence ended** | Everything **except** adding devices and planning or starting upgrade jobs. Backups, version checks, circuit scans and viewing keep working. An upgrade job already under way can always continue or roll back. Nothing is deleted |

### Modules: one install, the licence unlocks the tools

Every server gets the full product. The licence decides which tools are unlocked:

| Module | Unlocks |
|---|---|
| `backups` | Config backups: scheduled and manual backups, history, configs and changes |
| `firmware` | Firmware: version report, standards, image library, version checks |
| `upgrades` | Upgrade jobs (always brings `firmware`, which holds the images) |
| `circuits` | Circuits: the circuit list and the nightly comparison with the network |
| `syslog` | Syslog: the receiver, the Syslog page and syslog email alerts |
| `monitoring` | Monitoring: the ping and SNMP poller, the Monitoring page, map colours, its wall display page and alerts |

Always included: the device inventory and credentials, users and the activity report,
Settings, email alerts for whatever is unlocked, and the wall display.

* A tool that isn't unlocked is greyed out with a padlock in the top bar. Clicking it
  says it isn't in the licence and lists what is.
* Its scheduled work doesn't run: no backups, version checks, circuit scans, syslog
  stored, or monitoring checks. Its pages and API are refused.
* Without **backups**, the Config backups page still lists the devices and lets you manage
  them, because the other tools need the inventory.
* The **trial**, licences made before modules existed, and your own internal licence
  unlock everything. A licence that lists its modules unlocks only those: one made before
  a module existed (such as `monitoring`) doesn't include it until it is renewed with it.
* A module left out at renewal keeps its data. Nothing is deleted, and an upgrade job
  already under way still finishes or rolls back.

Editions are only names for a set of modules, for example *Essentials* = backups + syslog,
*Professional* = + firmware and upgrades, *Complete* = everything. You can rename or
re-bundle them at any time without changing the software.

When the trial or licence has ended, everyone sees a notice at the top of the page.
During the trial, and when a licence is ending, only admins see one.

## Development and your own testing

* **`python -m app`** (development and trials on your own PC) needs no licence and shows no
  limits.
* For your own installed servers (lab, test, your own sites), make yourself an **internal
  licence**: no end date, any number of devices (below).

There is no hidden login or setting that turns licensing off. Anyone could find one of those
in the shipped code.

## One-time: make the signing key

Do this once, on your own PC (not on a customer server), from `backend/` with the virtual
environment set up as in the README:

```bash
python -m app.licence_tool keygen --out ~/licence-signing.key
```

1. **Keep `licence-signing.key` secret and backed up**, for example in your password vault:
   * anyone with it can make licences;
   * if you lose it, you can't make new licences for servers that already trust it.
2. The command prints one line, the **public key**. Paste it into
   `backend/app/core/licence_keys.txt`, then commit it and merge it.
3. Every bundle built from then on accepts your licences.

Until that file has a key, servers can't accept any licence: they run the 60-day trial and
then become read-only for new work.

To move to a new signing key later:
1. add its public key as a second line;
2. issue new licences with the new key;
3. remove the old line once every customer has a new licence.

## Make a licence

```bash
# A customer: end date, number of devices
python -m app.licence_tool sign --key ~/licence-signing.key \
    --customer "Acme Ltd" --expires 2027-10-31 --devices 500 --out acme-2027.lic

# Only some tools (default: all of them)
python -m app.licence_tool sign --key ~/licence-signing.key \
    --customer "Acme Ltd" --expires 2027-10-31 --devices 500 \
    --modules backups,syslog --out acme-2027.lic

# Tied to one server: ask for the installation ID shown on its Settings page
python -m app.licence_tool sign --key ~/licence-signing.key \
    --customer "Acme Ltd" --expires 2027-10-31 --devices 500 \
    --install-id 1CED-A204-C5AB-0B11 --out acme-2027.lic

# Yourself: no end date, any number of devices
python -m app.licence_tool sign --key ~/licence-signing.key --internal --out internal.lic

# Check what a licence says
python -m app.licence_tool show acme-2027.lic
```

* `--expires` is the **last day** the licence works.
* `--devices` counts every device in the inventory.
* `--modules`: `backups`, `firmware`, `upgrades`, `circuits`, `syslog`, `monitoring`, comma separated.
  Leave it out for all of them. `show` lists what a licence unlocks.
* Send the `.lic` file, or its text, to the customer. It is not secret.

## Renewing

Make a new licence with a later end date and send it. The admin pastes it on the Settings
page, and it replaces the old one straight away.

**Adding a tool** works the same way. Make a new licence listing *all* the modules the
customer now has, not just the new one. It replaces the old licence, so there is still
one licence with one end date and one device count. The new tool unlocks as soon as it
is pasted in.

## Notes

* The trial start, the installation ID and the licence are kept in the database. A
  restored database backup keeps them. A new, empty database starts a new trial.
* A customer with root on the server could change the code to get around the check. The
  licence is there to keep honest customers honest; the licence agreement covers the rest.
* Every licence added, or refused, is in the activity report (`licence.install`,
  `licence.rejected`).
