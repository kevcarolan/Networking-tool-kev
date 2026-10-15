# Installing NetCairn on an air-gapped server

This is the supported way to install the platform on a network with no internet
access. For a server that can reach the internet, [install-online.md](install-online.md)
does the same steps on the server with one command. Everything the server needs goes across in **one offline bundle**:

* the app;
* every Python package, pinned and checked for known vulnerabilities;
* the Ubuntu packages, as a local package repository;
* checksums.

Nothing is downloaded on the server, and nothing needs compiling there.

```
 Internet side                        Transfer                 Air-gapped side
 ┌──────────────────────────┐   ┌───────────────────┐   ┌──────────────────────────────┐
 │ Build machine            │   │ Approved media     │   │ NetOps server (Ubuntu 26.04) │
 │ (Ubuntu 26.04 VM / WSL)  │──►│ scanned per policy │──►│ verify SHA-256 ─► install.sh │
 │ build-bundle.sh          │   │ + SHA-256 in the   │   │ ─► configure ─► harden       │
 │ ─► netops-bundle-*.tar.gz│   │   change ticket    │   │                              │
 └──────────────────────────┘   └───────────────────┘   └──────────────────────────────┘
```

Do the hardening in [security-hardening.md](security-hardening.md) **before** you add real
device credentials. This guide says at which point.

---

## 1. What you need

| Item | Details |
|---|---|
| Server | A VMware VM: 2 vCPU, 4 GB RAM, a 30 GB system disk, and a separate **100 GB data disk** (firmware images). x86_64. vCenter with a key provider for VM Encryption (the built-in Native Key Provider is enough) |
| Operating system | Ubuntu Server 26.04 LTS ISO. The bundle must be built on the **same Ubuntu release** as the server; 24.04 works too, if both sides use it |
| Build machine | Ubuntu 26.04 (the server's release) with internet access and sudo: a VM, Windows WSL (`wsl --install -d Ubuntu-26.04`), or an `ubuntu:26.04` Docker container. Use a clean, patched machine that is used only for this |
| DNS name | e.g. `netops.corp.local`, with a DNS record on the air-gapped network |
| TLS certificate | Issued by your internal CA for that name, with the key. PEM format; include any intermediate CA in the certificate file |
| AD | Two groups: `NetOps-Admins` and `NetOps-Viewers`. The CA certificate that signed the domain controllers' LDAPS certificates |
| Network facts | For the firewall: admin/jump-host subnets, the subnets allowed to use the GUI, device management subnets, and the DC, DNS, NTP and syslog addresses |
| Logging | The syslog server or SIEM address the server forwards its security events to |
| People | Named admin accounts for the server (no shared logins), each with an SSH key. Hardware keys (YubiKey or similar) if you have them |

---

## 2. Build the server (operating system)

1. **Create the VM in vCenter.** The details are in security-hardening.md §2:
   * Guest OS: Ubuntu Linux (64-bit). **EFI firmware with Secure Boot**, and a **vTPM**.
   * Two disks on a PVSCSI controller: 30 GB for the system and 100 GB for data.
     VMXNET3 network adapter on the management port group.
   * Apply the **VM Encryption Policy** to the VM and both disks.
   * Remove the floppy, USB and sound devices. Set the advanced settings from §2. Untick
     *Synchronize guest time with host*.
2. **Install Ubuntu Server 26.04:**
   * Choose **Ubuntu Server (minimized)**.
   * Storage: use LVM on the 30 GB disk. Leave LUKS off: vSphere VM Encryption already
     encrypts the disks, without a passphrase at every boot.
   * Tick **Install OpenSSH server**. Don't import SSH keys from GitHub or Launchpad.
   * **Don't** select any of the "featured server snaps".
   * Create your own named admin account.
3. **Set up the data disk** as `/var/lib/netops`, so firmware images can't fill the
   system disk. The mount options stop anything on it being run as a program:
   ```bash
   sudo mkfs.ext4 -L netops-data /dev/sdb          # check the device name with lsblk first!
   sudo mkdir -p /var/lib/netops
   echo 'LABEL=netops-data /var/lib/netops ext4 defaults,nodev,nosuid,noexec 0 2' | sudo tee -a /etc/fstab
   sudo mount /var/lib/netops
   ```
4. **Set the time source** before anything else, because TLS, AD logins and logs
   all depend on correct time. You can do this after step 5 (chrony comes in the bundle):
   edit `/etc/chrony/chrony.conf`, replace the `pool ...` lines with
   `server <your-internal-ntp> iburst`, then run `sudo systemctl restart chrony && chronyc tracking`.

---

## 3. Build the bundle (internet side)

You don't download packages one at a time. The build script downloads everything the
server needs, including every dependency, and packs it into one file.

### On a Windows PC (WSL)

Use an internet-connected PC that you're allowed to use for this.

1. **Use Ubuntu under WSL, on the same release as the server.** Check what you have,
   in PowerShell: `wsl -l -v`, then inside Ubuntu: `grep PRETTY /etc/os-release`. If it
   isn't the server's release, install that release (PowerShell as administrator, then reboot):
   ```powershell
   wsl --install -d Ubuntu-26.04
   ```
   Open it from the Start menu and create a user name and password when asked.
   They're local to WSL.
2. **Get the code and build.** In the Ubuntu window:
   ```bash
   sudo apt update && sudo apt install -y git
   git clone https://github.com/kevcarolan/Networking-tool-kev.git
   cd Networking-tool-kev
   sudo MAKE_ISO=1 deploy/airgap/build-bundle.sh
   ```
3. **Find the output.** In Windows Explorer, open
   `\\wsl$\<distro name from wsl -l>\home\<your WSL user>\Networking-tool-kev\dist\`.
   You can also type `explorer.exe dist` in the Ubuntu window.

### On an Ubuntu VM (same release as the server), or with Docker

```bash
git clone https://github.com/kevcarolan/Networking-tool-kev.git && cd Networking-tool-kev
sudo MAKE_ISO=1 deploy/airgap/build-bundle.sh
# or, on any machine with Docker:
docker run --rm -e MAKE_ISO=1 -v "$PWD":/src -w /src ubuntu:26.04 deploy/airgap/build-bundle.sh
```

### What you get

The build takes a couple of minutes. It writes these files to `dist/`:

| File | What it is |
|---|---|
| `netops-bundle-<version>.tar.gz` | The bundle (about 90 MB): app, Python packages, Ubuntu packages, checksums. `<version>` is e.g. `2.1.0` for a release, or `2.1.0-dev.<date>.<commit>` for a build between releases ([releasing.md](releasing.md)) |
| `….tar.gz.sha256` | Its SHA-256 |
| `….MANIFEST.txt` | **The list of every package and version in the bundle, with the vulnerability report.** Attach it to the change ticket |
| `….iso` and `….iso.sha256` | With `MAKE_ISO=1`: a CD image holding the three files above, for vSphere (§4) |

The build:

* runs **pip-audit** and stops if any Python package has a known vulnerability;
* downloads the Ubuntu packages and their full dependency tree (about 170 packages), so
  the result doesn't depend on what is installed on the build machine. With an internal
  Ubuntu mirror you can set `SKIP_DEBS=1`;
* prints the **SHA-256** of the bundle. Record it in the change ticket, or send it by a
  different channel from the files. On the server it proves the file wasn't changed in transit.

---

## 4. Transfer and verify

1. Copy the files from `dist/` to the approved transfer media, and scan them at your
   media-scanning station as your policy requires.
2. Get them onto the server in one of these ways.

   **A. As a CD image through vSphere (easiest for a VM):**
   1. In the vSphere Client, go to **Storage** → the VM's datastore → **Files** →
      **Upload Files**, and upload the `.iso`.
   2. In **Edit Settings** for the VM, set **CD/DVD drive 1** to *Datastore ISO File*,
      choose the ISO, and tick **Connected**. If you removed the CD drive after
      installing Ubuntu, add one back for now.
   3. On the server:
      ```bash
      sudo mount -o ro /dev/sr0 /mnt
      sudo install -d -m 0700 /root/netops-install
      sudo cp /mnt/netops-bundle-* /root/netops-install/
      sudo umount /mnt
      ```
   4. Disconnect the ISO in the VM settings, and delete it from the datastore when
      you've finished.

   **B. From an admin machine on the air-gapped network** that the files have already
   reached:
   ```bash
   scp netops-bundle-*.tar.gz* <you>@<server>:/tmp/
   # then on the server:
   sudo install -d -m 0700 /root/netops-install && sudo mv /tmp/netops-bundle-* /root/netops-install/
   ```
3. **Verify, on the server.** The folder is readable only by root, so open a root shell first:
   ```bash
   sudo -i                                 # root shell; type "exit" when finished
   cd /root/netops-install
   sha256sum netops-bundle-*.tar.gz        # must match the value in the change ticket
   sha256sum -c netops-bundle-*.tar.gz.sha256
   ```
   **If the hash doesn't match, stop.** Don't extract the file.

---

## 5. Install

In the root shell from §4 (or `sudo -i` again):

```bash
cd /root/netops-install
tar -xzf netops-bundle-*.tar.gz
bash netops-bundle-*/install.sh
exit                                    # leave the root shell
```

If there is more than one bundle in the folder, use the full file names instead of `*`.

The installer:

1. checks every file in the bundle against its `SHA256SUMS`;
2. installs the Ubuntu packages from the bundle. It adds only what is missing and
   never downgrades anything:
   * `python3-venv`, `git`, `sqlite3`, `nginx`;
   * the hardening tools: `nftables`, `chrony`, `auditd`, `aide`, `apparmor-utils`,
     `rsyslog-gnutls`, `apt-offline`;
3. creates the `netops` system account. It has no password and no login shell;
4. installs the release into `/opt/netops/releases/<version>/` (owned by root and
   read-only to the service) and points `/opt/netops/current` at it;
5. creates `/etc/netops/netops.env` and a new encryption key, `/etc/netops/credential.key`;
6. installs:
   * the sandboxed systemd services `netops` (web app), `netops-worker` (upgrade jobs),
     `netops-syslog` (receives the devices' syslog on port 514, [syslog.md](syslog.md)) and
     `netops-monitor` (pings the devices and reads them with SNMP, [monitoring.md](monitoring.md));
   * the nightly backup timer;
   * the `netops-cli` admin command;
   * the audit rules;
   * the nginx sites: the main one (443) and the wall display (8443, closed by the
     hardened firewall until you allow your screens);
   * the certificate service: it installs a certificate you add on the setup screen
     (`netops-tls.path`, `/usr/local/sbin/netops-tls-apply`);
7. on a **first install**: makes a temporary self-signed certificate (30 days) for the
   server's name and addresses, turns on the nginx site and starts the services. The
   first visit shows the **setup screen** (section 6).

| Path | What | Owner / mode |
|---|---|---|
| `/opt/netops/current` → `releases/<version>` | Code and Python environment | root, read-only |
| `/etc/netops/netops.env` | Settings | root:netops 0640 |
| `/etc/netops/credential.key` | Key that encrypts device passwords | root:netops 0640 |
| `/etc/netops/tls/` | nginx certificate and key | root 0700 |
| `/var/lib/netops/` | Database, config archive, firmware images | netops 0750 |
| `/var/lib/netops/setup-token` | The setup code (until setup is finished) | netops 0600 |
| `/var/lib/netops/tls/` | A certificate added on the setup screen, before it is installed | netops 0750 |
| `/var/backups/netops/` | Nightly backups | root 0700 |

---

## 6. First-time configuration

**Before anything else, save the encryption key offline.** Without
`/etc/netops/credential.key`, the stored device passwords can't be decrypted. It is
deliberately **not** in the nightly backups. Copy it to your password vault, or to an
encrypted USB key kept in a safe:
```bash
sudo cat /etc/netops/credential.key
```

### 1. The setup screen

Open `https://<the server's name>/` in a browser. The browser warns about the temporary
certificate; accept it this once. The **setup screen** asks for the **setup code**, which
proves you look after the server. Show it on the server:

```bash
sudo cat /var/lib/netops/setup-token
```

Then:

1. **Admin account.** A local account with full rights. It also works when AD is down,
   so keep the password in the vault. Add AD users and more admins later on the Users page.
2. **Active Directory** (optional; skip to use local accounts only):
   * the server (`ldaps://dc1.corp.local`), the domain and the base DN;
   * the admin, viewer and upgrader group DNs. **Set the viewer group:** if it is empty,
     every domain user can sign in;
   * paste the CA certificate that signed the domain controllers' certificates (PEM);
   * **Test sign-in** with a real account before saving: it shows the role that account
     would get.
3. **Certificate** (optional; you can do it later on the Settings page). Either:
   * **make a request here**: enter the server's DNS name(s). The private key is made on
     the server and never leaves it. Send the request (`netops.csr`) to your CA, then paste
     the certificate it issues (with any intermediate) and press Install; or
   * paste a certificate **and its private key** that you already have, and press Install.

   The server checks the certificate (in date, matches the key, accepted by nginx) and
   installs it within a few seconds. If anything is wrong it keeps the current one, and
   the Settings page says why. Reload the page to use the new certificate.
4. **Finish.** The setup code stops working. Sign in with the admin account.

The server runs a **60-day trial**. Add the licence on the **Settings** page (it shows the
installation ID to send when you ask for one). Without a licence, after the trial nobody
can add devices or start upgrades; backups keep running.

Afterwards, admins set the **customer or site name** and the day-to-day defaults (backup
frequency, retries, history kept, version-check interval, circuit scan schedule, upgrade
pre-check limits) on the **Settings** page. Changes apply straight away.

Settings that need a file edit (rarely) are in `/etc/netops/netops.env`: the safety gates
(which platforms may run live upgrades, the break-glass admin) and the technical ones (ports,
worker counts, timeouts). Restart the services after changing it
(`sudo systemctl restart netops netops-worker`). A setting made in `netops.env` wins over
the Settings page and is shown there as "set in netops.env". On a server installed before
the Settings page, the defaults are still in `netops.env`: comment a line out (`#`) and
restart to manage it on the Settings page instead.

### 2. Check the sign-in

* Sign in with an AD account in the admin group, then check that an account in the
  viewer group can sign in but can't change anything.
* Admins can change AD and the certificate later: **Settings** in the top bar.
* Status: `systemctl status netops netops-worker netops-syslog netops-monitor --no-pager` (all "active (running)").
  If the page doesn't load, check `journalctl -u netops -n 30 --no-pager`.

### 3. Certificate by hand (instead of the setup screen)

If you prefer, put the certificate (full chain) and key in `/etc/netops/tls/` yourself and
reload nginx:

```bash
sudo install -m 0600 netops.crt netops.key /etc/netops/tls/
sudo nginx -t && sudo systemctl reload nginx
```

### 4. Harden the server

Work through [security-hardening.md](security-hardening.md) §3–§9: SSH, firewall,
kernel, accounts, logging. Do it on the production server **before** you add real device
credentials. Then point your monitoring at `https://<server>/api/health`.
On an internet-connected test machine, leave out the firewall (§5): it blocks outbound
traffic, including internet access.

### 5. Add credential profiles and devices

In the GUI, or in bulk:
`sudo cp devices.csv /tmp/ && sudo netops-cli import-csv /tmp/devices.csv`

### 6. Check the firmware parsers

On one device of each platform and model:
`sudo netops-cli firmware-check core-sw1 --raw`

---

## 7. Upgrading NetCairn

1. Build a new bundle (step 3), transfer it and verify it (step 4).
2. `sudo bash netops-bundle-<new>/install.sh`

The installer takes a backup (`/var/backups/netops/netops-pre-upgrade-*.tar.gz`), stops
the service, switches to the new release and starts it again. If the new release doesn't
report healthy within 30 seconds, it **switches back automatically**. It keeps the last
three releases.

To roll back by hand:

```bash
ls /opt/netops/releases/
sudo ln -sfn /opt/netops/releases/<previous> /opt/netops/current
sudo systemctl restart netops
```

Settings and the key are never touched by an upgrade. When a new release changes the
**database layout**, it updates the database by itself when it starts, after keeping a copy
next to it (`/var/lib/netops/app.db.before-<version>`). If the new release then doesn't
start, the installer puts that copy back before switching to the previous release.

Rolling back by hand across such a release: stop the service, put the copy back, then switch
the release as above:

```bash
sudo systemctl stop netops-worker netops
sudo -u netops cp /var/lib/netops/app.db.before-<version> /var/lib/netops/app.db
sudo rm -f /var/lib/netops/app.db-wal /var/lib/netops/app.db-shm
```

`sudo netops-cli db-status` shows the database version and whether it is up to date.
Changes made after the upgrade are lost when you put the copy back, so do it straight away.

---

## 8. Patching Ubuntu without internet

Security updates still matter on an air-gapped server: someone who gets onto the
network can exploit unpatched software. Patch at least monthly, and straight away for
critical advisories.

For now, patch with **`apt-offline`**. Once testing and sign-off are done, the plan is to
connect the server to an internal Ubuntu mirror, which makes this a normal `apt upgrade`.

* **With an internal Ubuntu mirror (later)** (Landscape, Nexus, Artifactory, apt-mirror),
  point `/etc/apt/sources.list.d/ubuntu.sources` at it and use
  `sudo apt update && sudo apt upgrade`.
* **With `apt-offline` (now).** It's in the bundle:
  ```bash
  # 1. On the server: make a request file listing what needs updating
  sudo apt-offline set /root/netops-install/updates.sig --update --upgrade
  # 2. Carry updates.sig to the build machine (same Ubuntu release, with internet):
  sudo apt install apt-offline
  apt-offline get updates.sig --bundle updates.zip --threads 4
  # 3. Scan updates.zip, carry it back, then on the server:
  sudo apt-offline install /root/netops-install/updates.zip
  sudo apt upgrade
  ```
  apt checks the Ubuntu signatures on every package, so the update files are verified.
* Reboot when a kernel or libc update needs it (`/var/run/reboot-required` exists).
  Then check `systemctl status netops nginx`.
* After patching, update the file-integrity baseline (hardening guide §10).

---

## 9. Backups and restore

* Every night at 02:30, `netops-backup` writes
  `/var/backups/netops/netops-nightly-<time>.tar.gz`. It keeps 14 days. It contains:
  * a consistent copy of the database;
  * the config archive (as a git bundle);
  * `netops.env`.
* The encryption key and firmware images are **left out** on purpose (see §6).
* **Copy `/var/backups/netops` off the server.** Your backup system should pull it, or
  you should copy it to backup media regularly. A backup only on the server itself
  doesn't protect against losing the server.
* Take a backup by hand with `sudo netops-backup manual`.

**Restore test:** do this after installing, then once a quarter.

```bash
sudo systemctl stop netops
sudo mkdir /root/restore && sudo tar -xzf /var/backups/netops/netops-nightly-<time>.tar.gz -C /root/restore
sudo install -o netops -g netops -m 0640 /root/restore/app.db /var/lib/netops/app.db
sudo rm -f /var/lib/netops/app.db-wal /var/lib/netops/app.db-shm
sudo mv /var/lib/netops/configs /var/lib/netops/configs.old
sudo install -o netops -m 0600 /root/restore/configs.gitbundle /var/lib/netops/configs.gitbundle
sudo -u netops git clone -q /var/lib/netops/configs.gitbundle /var/lib/netops/configs
sudo rm /var/lib/netops/configs.gitbundle
sudo systemctl start netops
```

On a **new** server: install the same bundle, put the saved `credential.key` in
`/etc/netops/` (`root:netops`, 0640), restore as above, then check that a backup of one
device still works. That proves the stored passwords can still be decrypted.

---

## 10. Troubleshooting

| Symptom | Check |
|---|---|
| `install.sh` says checksum mismatch | The bundle was damaged or changed. Get a fresh copy; don't install |
| Service won't start | `journalctl -u netops -n 50`. Common causes: a typo in `netops.env`, or the key file missing or unreadable |
| 502 Bad Gateway in the browser | The app isn't running: `systemctl status netops` |
| AD login fails | `journalctl -u netops` shows the LDAP error. Check the time (`chronyc tracking`), the CA file, the firewall rule to the DCs on 636 |
| Device backups time out | The firewall output rule to `DEVICE_NETS` on port 22; the device's SSH access list (security-hardening.md §11) |
| Something was blocked | `journalctl -k | grep nft-` shows dropped traffic in and out |
| Check the sandbox | `systemd-analyze security netops` and `… netops-worker` (a lower score is better) |
| "The upgrade worker isn't running" in the GUI | `systemctl status netops-worker`; `journalctl -u netops-worker -n 50` |
| "The syslog receiver isn't running" on the Syslog page | `systemctl status netops-syslog`; `journalctl -u netops-syslog -n 50` |
| "The monitoring poller isn't running" on the Monitoring page | `systemctl status netops-monitor`; `journalctl -u netops-monitor -n 50` |
| Devices show down, or SNMP times out | The firewall output rules to `DEVICE_NETS` (ICMP echo and UDP 161); the device's SNMP access list and user ([monitoring.md](monitoring.md#troubleshooting)) |
| `install.sh` refuses: "a live upgrade job is running" | A device is being upgraded. Wait until the job has finished or paused (`sudo netops-cli upgrades-running`), or run with `FORCE=1` if you are sure |
| FTD, FortiGate or PAN-OS upgrade: "API unreachable" | The firewall output rule to `FDM_HOSTS` on port 443, and the device's management access list (trusted hosts) |
