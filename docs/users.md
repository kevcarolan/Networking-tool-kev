# Users, permissions and the activity report

Admins manage who can sign in and what each person can do on the **Users** page. The
**Activity** page shows who did what, with the result of every job they ran.

## Who can sign in

The **first admin** is made on the setup screen, the first time anyone opens the server
([install-airgap.md](install-airgap.md) §6). It is a normal local user (step 2 below)
with every right. Active Directory is set on the setup screen too, and later on the
**Settings** page (admins only).

NetOps checks, in this order:

1. **The break-glass admin** (optional: `NETOPS_LOCAL_ADMIN_USER` and its password hash in
   `/etc/netops/netops.env`). It always has every right, so you can't lock yourself out.
2. **A user added on the Users page.** They get **exactly** the permissions set there.
   * **Active Directory:** they sign in with their normal AD password (`jsmith`,
     `jsmith@corp.local` or `CORP\jsmith`). Their AD groups don't matter.
   * **Local (password kept here):** for the test server, contractors or anyone without AD.
     The password is stored hashed (scrypt) and needs at least 12 characters. The user can
     change it with **Change password** (top right); an admin can **Reset password**.
3. **Any other AD user**, from the AD groups as before:
   * `NETOPS_LDAP_ADMIN_GROUP`: everything;
   * `NETOPS_LDAP_VIEWER_GROUP` (or every domain user if it's empty): view only;
   * `NETOPS_LDAP_UPGRADER_GROUP`: may run upgrade jobs, dry run and live (if the group
     isn't set, admins may).

   To stop this fallback, set the viewer group to a group nobody else is in, and add
   everyone on the Users page.

A change on the Users page applies **straight away**, even to someone who is signed in.
A **disabled** (or deleted) account is signed out at its next click.

## Permissions

Each user has a level in each area. Each level includes the ones before it.

| Area | Levels |
|---|---|
| Devices and credentials | **view**: see devices · **manage**: edit device details (name, platform, site, notes, schedule) and delete devices · **addresses**: add devices and change a device's address or credential profile · **credentials**: add, change and delete credential profiles |
| Config backups | none · **view**: status and history · **run**: run a backup now · **configs**: read stored configs and diffs (they contain secrets) · **manage**: change backup schedules |
| Firmware | none · **view**: versions, standards, image library · **manage**: check versions, upload images, set standards and device upgrade settings |
| Upgrade jobs | none · **view**: jobs and reports · **dry run**: plan and run dry-run jobs · **live**: plan and run live upgrades |
| Circuits | none · **view**: the list and exports · **manage**: upload the list and scan the network |

**Administrator** (a tick box) means the top level everywhere, plus the Users and
Activity pages.

**Devices and credentials** has two levels above *manage*, because a device's address and
credential profile decide where that account's password is sent: the next backup logs in
to whatever the address points at.
* **addresses** lets a user add devices and change a device's address or credential
  profile. Give it only to people you would trust with the device accounts themselves.
* **credentials** also lets them add, change and delete the credential profiles.
* With **manage** alone, the address and credential fields are greyed out.

Both changes are in the activity report with the old and new values, and the server
refuses a device whose SSH key has changed. Users who had *manage* before this level was
split keep *manage*: give *addresses* to those who add devices.

**Presets** fill in the levels; adjust them after:

| Preset | Devices | Backups | Firmware | Upgrades | Circuits |
|---|---|---|---|---|---|
| Viewer | view | view | view | view | view |
| Backup operator | view | run | view | view | view |
| Upgrader | view | configs | view | live | view |
| Administrator | everything, plus users and activity | | | | |

A **live** upgrade still needs everything it needed before: the platform in
`NETOPS_UPGRADE_LIVE_PLATFORMS`, a change window, and the typed device name. A user with
**dry run** can plan, check, stage and rehearse any job, but can't create or act on a live
one.

`NETOPS_VIEWERS_CAN_READ_CONFIGS=true` still works: everyone who can see backups can then
read configs.

## The activity report

**Activity** (admins) shows the last 30 days by default. Filter by user, area and dates.

* **Per user:** sign-ins (and failed ones), backups run, configs viewed, version checks,
  upgrade jobs planned (dry run and live), starts, roll backs, overrides, cancellations,
  circuit lists made live, network scans, and changes to devices, credentials and users.
  Click a name to see only their actions.
* **Upgrade jobs:** every job in the period, with who planned it, who started it, dry run
  or live, the versions and the **result** (completed, failed, rolled back…).
* **Backups run by hand:** who ran which backup and whether it worked.
* **Every action:** the audit log itself.

**Export CSV** downloads the actions for the current filter.

Scheduled work (nightly backups, the weekly network scan) isn't anyone's action, so it
isn't in the per-user figures; it is on the Config backups and Circuits pages.
