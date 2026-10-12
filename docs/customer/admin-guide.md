# Admin guide

For admins: setting the platform up, keeping it healthy, and deciding who can do what.

## 1. First-run setup

The first visit to a new server shows the **setup screen**. Every step needs the **setup
code**, which only someone with access to the server can read:

```bash
sudo cat /var/lib/netops/setup-token
```

Wrong codes are slowed down and written to the activity log. The steps:

1. **Admin account.** A local account with every right. It still works when Active
   Directory is down, so keep its password in your vault.
2. **Active Directory** (optional):
   * **Server, domain and base DN:** `ldaps://dc1.corp.local`, `corp.local`,
     `DC=corp,DC=local`. Users sign in as `jsmith`, `jsmith@corp.local` or `CORP\jsmith`.
     The server signs in as the user, so no AD service account is needed.
   * **Groups** (full DNs):
     * **admin**: everything;
     * **viewer**: view only;
     * **upgrader**: may run upgrade jobs.

     **Set the viewer group**: if it is empty, every domain user can sign in and look.
   * **CA certificate:** the one that signed the domain controllers' certificates.
   * **Test sign-in:** try a real account before saving. It shows the access that account
     would get.
3. **Certificate** (optional; you can do it later on the Settings page). Either:
   * make a **request** here: the key is made on the server and never leaves it. Send the
     request (`netops.csr`) to your CA, then paste the certificate it issues (with any
     intermediate certificates); or
   * paste a certificate **and its key** that you already have.

   The server checks the certificate before installing it:
   * it is in date;
   * it matches the key;
   * the web server accepts it.

   If any check fails, it keeps the current certificate and the Settings page shows why.
   Reload the page to use the new certificate.
4. **Finish.** The setup code is deleted. Sign in with the admin account.

## 2. The Settings page

**Settings** (admins only) in the top bar. Every change is in the activity report.

### Licence

* **State:** trial (with the days left), licensed (with the customer and end date), or ended.
* **Tools unlocked:** the tools the licence covers (Config backups, Firmware, Upgrade jobs,
  Circuits, Syslog). Others are greyed out with a padlock in the top bar, and their
  scheduled work doesn't run. To add one, ask your supplier for a new licence that
  includes it.
* **Devices:** how many are in the inventory, and how many the licence covers.
* **Installation ID:** send it when you ask for a licence or a renewal.
* **Adding a licence:** paste the licence text and press **Add licence**. A new licence
  replaces the old one straight away.

| State | What works |
|---|---|
| Trial (60 days) or licensed | Everything (up to the licence's devices) |
| Trial over, or licence ended | Everything **except** adding devices and planning or starting upgrade jobs. Backups, version checks, circuit scans and viewing go on. An upgrade under way can always continue or roll back. Nothing is deleted |

Admins see a notice from 30 days before the licence ends.

### Site and defaults

| Setting | What it does |
|---|---|
| Customer or site name | Shown next to the product name, and on upgrade reports |
| Backup every (minutes), for new devices | The schedule new devices start with; each device's own schedule is on Config backups |
| Retry a failed backup or version check after | How soon a failed device is tried again |
| Keep backup and check history for | Run history only; every config version is always kept |
| Read each device's software version every | The Firmware version report |
| Circuit location scan | When every switch's MAC and ARP tables are read and compared with the circuit list: `daily 03:00` (every night, the default), `sun 02:00` (weekly), or empty for none |
| Viewers may read device configs | Configs contain password hashes and keys, so the default is no |
| Upgrade pre-check limits | When CPU or memory use gives a warning in an upgrade pre-check (a warning never blocks) |
| Fresh backup before an upgrade | An upgrade takes a new config backup first if the last one is older than this |

A setting shown as **"Set in netops.env"** is fixed in the server's settings file and wins
over this page. To manage it here instead, comment that line out with `#` in
`/etc/netops/netops.env`, then run `sudo systemctl restart netops netops-worker`.

### Email alerts

Sent through your own mail server. Each recipient chooses which kinds of alert they get
(**Who gets what**: one row per address, a tick per kind). Each event is sent once, and the
server checks every minute.

| Alert | When |
|---|---|
| Backups | A device's backup has been failing for longer than the hours you set (24 by default; 0 switches this off). The failing devices go in one email |
| Upgrades | An upgrade job (live or dry run) has completed, failed, rolled back, or needs attention |
| Licence | 30 and 7 days before the licence ends, and when it (or the trial) has ended |
| Upgrade worker | The upgrade worker has been stopped for more than 10 minutes |
| Syslog | Devices sent messages at the level you choose (Critical and worse by default) or worse. They are gathered into at most one email every few minutes (5 by default), listing up to 50, so a storm of messages is one email |

1. Fill in:
   * the mail server, port and security (STARTTLS on 587, TLS on 465, or none on port 25
     for an internal relay that doesn't offer encryption);
   * a username and password if the server needs them;
   * the From address;
   * under **Who gets what**, each recipient's address and the alerts they get
     (**+ Add recipient** for more, ✕ to remove one).
2. Tick **Send email alerts**, then press **Save**.
3. Press **Send test email**: it says straight away if the mail server refused it.

* Only events after you switch alerts on are sent, not the history.
* If the mail server can't be reached, the last error shows here, and the alerts are tried
  again at the next check.
* The hardened firewall needs the mail relay allowed: `SMTP_HOSTS` in `/etc/nftables.conf`.
* The relay's certificate is checked. For an internal CA, add it to the server's trusted
  CAs (`sudo cp corp-ca.crt /usr/local/share/ca-certificates/ && sudo update-ca-certificates`).

### Wall displays

A read-only status screen for a NOC or an engineers' office, readable from across the
room. Two pages take turns every 20 seconds:

* **Overview:**
  * tiles for failing backups, firmware on standard (a percentage, with how many are
    behind), upgrades running, and server health (the upgrade worker and the licence);
  * the devices whose backups are failing, with the reason and for how long;
  * one box per site, coloured by its worst problem.
* **Upgrades:**
  * every upgrade under way: the device, live or dry run, the versions, the current step
    with a progress bar, when the window ends, and the circuits it affects (by service and
    VLAN), so alarms during a change can be put down to it;
  * the upgrades coming up in the next 12 hours.

  This page is skipped when there are none.

The screen shows only names, counts and statuses: no configs, passwords or addresses.

**To add a screen:**
1. **Settings › Wall displays:** type a name (for example "NOC wall 1"), then **Add display**.
2. Copy the link it shows. **It is shown only once**: it holds the screen's key.
3. Open the link full screen in the screen's browser (kiosk mode).

* **Settings** lists every screen, with when and from where it last connected.
* **Remove** stops a screen's link straight away.
* To show only the overview for longer, or rotate faster, add `&rotate=40` (seconds) to the
  end of the link.

**The port.** The display is served only on its own port, **8443**, and never on the
normal web address. The hardened firewall keeps 8443 closed until you allow your screens'
network: set `DISPLAY_NETS` in `/etc/nftables.conf`
([security-hardening.md](../security-hardening.md) §5). If the screen shows **"No data
since …"** in red, it has lost contact with the server; the time says since when.

### Active Directory and the certificate

The same forms as the setup screen. Change and test AD at any time, and renew the
certificate here before it expires.

### Only in netops.env

Some settings need someone with root on the server. They are kept out of the browser on
purpose:
* which platforms may run **live** upgrades (`NETOPS_UPGRADE_LIVE_PLATFORMS`);
* the break-glass admin;
* ports, worker counts and timeouts.

Edit `/etc/netops/netops.env`, then run `sudo systemctl restart netops netops-worker netops-syslog`.

## 3. Users and permissions

**Users** page: add AD users (they sign in with their AD password) or local users (for
anyone without AD; at least 12 characters). Give each a level per area, or start from a
preset:

| Preset | Devices | Backups | Firmware | Upgrades | Circuits | Syslog |
|---|---|---|---|---|---|---|
| Viewer | view | view | view | view | view | view |
| Backup operator | view | run | view | view | view | view |
| Upgrader | view | configs | view | live | view | view |
| Administrator | everything, plus Users, Activity and Settings | | | | |

* AD users who aren't on the Users page get access from the AD groups.
* A change applies straight away.
* A disabled user is signed out at their next click.

* **Devices and credentials** has four levels. *manage* edits device details; *addresses*
  also adds devices and changes their address or credential profile, which decides where
  a device account's password is sent; *credentials* also manages the credential profiles.

All the levels are explained in [users.md](../users.md).

**Activity** shows who did what: sign-ins, backups run, configs viewed, upgrade jobs and
their results, overrides, and changes to devices, users and settings. Export it as CSV.

## 4. Devices and credentials

1. **Credentials** page: add a **credential profile** for each kind of account:
   * a **read-only backup account** (for example `switch-backup`), used by backups,
     version checks and circuit scans;
   * a **privileged upgrade account**, set per device in its upgrade settings and used
     only by upgrade jobs.

   Passwords are encrypted on the server and never shown again.
2. Add devices on **Config backups › Add device**, or many at once from a CSV file on the
   server:
   ```bash
   sudo netops-cli import-csv /tmp/devices.csv
   ```
   The columns are `name,address,platform,site,credential,frequency_minutes,notes`.
   There is an example in `docs/devices-example.csv`.
3. Check each new platform with one device first: **Backup now**, then **Firmware › Check now**.
4. **SSH host keys.** The first time the server connects to a device it records the
   device's SSH key, which is shown in the device's edit dialog. After that, a device that
   answers with a different key is refused **before any password is sent**, and the
   reason says so. When you have really replaced or reinstalled the device, an admin
   clicks **Forget** next to the key in its edit dialog, and the next connection records the
   new one. Otherwise, find out who is answering on that address first.
5. Changes to a device's **address** or **credential profile** are shown in the activity
   report with the old and new values: whoever can edit devices decides where an
   account's password is sent.

### The inventory

**Inventory** lists every device plus anything else you record (servers, racks, UPSs…).
Only devices the tools manage count towards the licence.

* **Custom columns** (admins): add columns for everyone at the site, e.g. *Power feed*
  as a pick-list.
* **Import** a spreadsheet of your existing inventory first: when you then add the
  devices on Config backups, they are linked to their rows by name or address.
* **Manage this device…** in an item's form turns a recorded switch into a managed one.

Details: [inventory.md](../inventory.md).

## 5. Live upgrades

Every upgrade job can run as a **dry run**: it logs in and checks for real, but only
records the steps that would change the device. Live upgrades are **off** until you
switch them on, platform by platform:

1. Run the platform through the lab tests ([upgrade-lab-tests.md](../upgrade-lab-tests.md)).
2. Add it to `NETOPS_UPGRADE_LIVE_PLATFORMS` in `/etc/netops/netops.env` (for example
   `cisco_ios,cisco_nxos`), then restart the services.
3. Give the engineers **Upgrade jobs: live** on the Users page.

A live job also needs:
* a change window;
* the device name typed to confirm Start, Continue and Roll back;
* passing pre-checks, or overrides that each give a reason.

The full procedure is in [upgrades.md](../upgrades.md).

## 6. Monitoring

* **Health:** point your monitoring at `https://<server>/api/health`. It answers
  `{"ok": true}` when the web app is up.
* **Logs:** sign-ins, failed sign-ins and every change go to the service log. Forward them
  to your syslog server with `deploy/hardening/rsyslog-forward.conf`
  ([security-hardening.md](../security-hardening.md) §9).
* **Daily look:** the **Config backups** tiles show failing and never-backed-up devices,
  with the reason (wrong password, unreachable, timeout…).
* **The devices' syslog:** the server collects it on the **Syslog** page (next section).

## 6a. Syslog from the devices

The server receives the devices' syslog on UDP and TCP 514 (the `netops-syslog` service)
and keeps it in one file per day under `/var/lib/netops/syslog/`.

1. **Firewall:** in `/etc/nftables.conf`, set `SYSLOG_SOURCES` to the devices' management
   networks, then `sudo nft -f /etc/nftables.conf`.
2. **Devices:** on the Syslog page, click **Help: set up devices**. Choose the platform, check
   the server address, and copy the suggested config to the device. Send from the
   management address that is in the inventory, and use NTP.
3. **How long:** on **Settings › Site and defaults**, set *Keep syslog messages for (days)*
   (30 by default) and *Keep at most this much syslog (GB)* (20). The oldest days go first.
   *Keep messages only from inventory devices* drops everything else.
4. **Who sees it:** the **Syslog** permission (none or view) on the Users page.
5. **Encrypted (optional):** for syslog that crosses networks you don't control, switch on
   syslog over TLS: `NETOPS_SYSLOG_TLS_PORT=6514` in `netops.env`, then
   `sudo systemctl restart netops-syslog`. It uses the server's certificate. The help has
   *Send as: Encrypted* examples for the devices that support it.

Sizing, the limits that protect the disk, and troubleshooting: [syslog.md](../syslog.md).

## 7. Backing up the server

* A backup is made every night at 02:30, in `/var/backups/netops/` (kept for 14 days). It
  holds the database, the config archive and `netops.env`.
* **Copy that folder off the server**: a backup that only exists on the server doesn't
  help if you lose the server.
* The **encryption key** is not in the backup, on purpose. Keep it in your vault. You need
  it to restore onto a new server.
* Test a restore after installing, then every quarter:
  [install-airgap.md](../install-airgap.md) §9.

## 8. Upgrading the platform

* **Online:** `cd /usr/local/src/netops && sudo git pull && sudo deploy/install-online.sh`.
* **Air-gapped:** build, carry across and verify the new bundle, then run
  `sudo bash netops-bundle-<new>/install.sh`.

The installer:
* takes a backup, switches to the new version and checks that it is healthy;
* switches back by itself if it isn't;
* updates the database by itself, keeping a copy first;
* won't restart while a live device upgrade is running.

Settings, the key and the licence are kept. See [install-airgap.md](../install-airgap.md) §7.

## 9. Troubleshooting

| Symptom | Check |
|---|---|
| The page doesn't load, or shows 502 | `systemctl status netops`; `journalctl -u netops -n 50` |
| AD sign-in fails | Settings › Active Directory › **Test sign-in** shows the error. Then check the server's time (`chronyc tracking`), the CA certificate, and the firewall to the DCs on TCP 636 |
| The certificate wasn't installed | The Settings page shows the reason. Usually the certificate doesn't match the key, or is missing the intermediate certificate |
| A device's version, model or a check result is read wrong | Run `sudo netops-cli capture <device>` and send the file (`/var/lib/netops/captures/`) to support. It holds only read-only command output, with IP and MAC addresses replaced |
| Device backups fail | The reason is on Config backups: wrong account, the device's SSH access list, or the server's firewall to the device |
| "The device's SSH key has changed" | The device was replaced or reinstalled: an admin clicks **Forget** next to the key in its edit dialog. If it wasn't, investigate before forgetting it |
| "Your session has expired" | Sign-ins last at most `NETOPS_SESSION_MAX_AGE_HOURS` (12 by default), even while in use: sign in again |
| "The upgrade worker isn't running" | `systemctl status netops-worker`; `journalctl -u netops-worker -n 50` |
| "The syslog receiver isn't running" | `systemctl status netops-syslog`; `journalctl -u netops-syslog -n 50` |
| A device's syslog doesn't arrive, or shows as "not in the inventory" | `SYSLOG_SOURCES` in the firewall; the device's logging source interface must be the inventory address ([syslog.md](../syslog.md)) |
| Can't add devices or start upgrades | The trial or licence has ended: Settings › Licence |
| No email alerts arrive | Settings › Email alerts › **Send test email** shows the mail server's answer. Check `SMTP_HOSTS` in the firewall and the relay's certificate |
| A wall display shows "No data since …" | The screen can't reach port 8443 (`DISPLAY_NETS` in the firewall), or its link was removed: add it again on Settings › Wall displays |
| A setting is greyed out ("Set in netops.env") | See *Site and defaults* above |
| Forgot the admin password | Another admin resets it on the Users page. If there is no other admin, set a break-glass admin in `netops.env` (`sudo netops-cli hash-password`), restart, and sign in with it |

More: [install-airgap.md](../install-airgap.md) §10.
