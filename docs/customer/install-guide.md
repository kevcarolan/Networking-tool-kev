# Install guide

## 1. What you need

| | |
|---|---|
| Server | A VM running **Ubuntu Server 26.04 LTS** (minimal install): 2 vCPU, 4 GB memory, 40 GB disk, plus about 100 GB if you keep firmware images on it |
| Name | A DNS name for the server (e.g. `netops.corp.local`) and a certificate for it from your CA (you can request it from the setup screen) |
| Network | The server reaches every device's management address on **TCP 22** (SSH); FTD (FDM), FortiGate and PAN-OS also on **TCP 443**. Users reach the server on **TCP 443** |
| Sign-in | Active Directory over LDAPS (optional; local accounts work too): the DCs' CA certificate and the group DNs for admins, viewers and upgraders |
| Device accounts | A **read-only** account for backups and checks, and a separate **privileged** account for upgrades ([vendors.md](../vendors.md) lists what each platform needs) |
| Licence | The 60-day trial starts at install. Ask for a licence with the installation ID from the Settings page |

The server never needs the internet to run: licences are checked on the server, and there
is no telemetry and no update check.

## 2. Choose how to install

* **The server can reach the internet** (at least while installing): one command on the
  server. See [install-online.md](../install-online.md).
* **No internet (air-gapped):** build an offline bundle on another machine, check its
  SHA-256, carry it across and install it. See [install-airgap.md](../install-airgap.md).

Both install the same way:
* the code goes in `/opt/netops`;
* the settings in `/etc/netops`;
* the data in `/var/lib/netops`.

Both upgrade, and roll back, the same way too.

## 3. The first visit

The installer starts the services with a temporary certificate. Then:

1. **Save the encryption key** somewhere safe and offline (password vault):
   `sudo cat /etc/netops/credential.key`. Without it, the stored device passwords can't be
   decrypted. It is not in the nightly backups, on purpose.
2. Open `https://<server name>/`. Accept the certificate warning this once.
3. Show the **setup code** on the server, and type it into the setup screen:
   `sudo cat /var/lib/netops/setup-token`.
4. Create the **admin account**, connect **Active Directory** (test a sign-in before
   saving), and install the **certificate**. The [admin guide](admin-guide.md#1-first-run-setup)
   explains each step.
5. **Finish**, then sign in.

## 4. Before go-live

- [ ] Encryption key saved offline
- [ ] Certificate from your CA installed (no browser warning)
- [ ] AD sign-in tested: an admin, a viewer, and someone in neither group
- [ ] Licence added (Settings page)
- [ ] Server hardened ([security-hardening.md](../security-hardening.md)): SSH, firewall,
      logging. Do this **before** adding real device credentials
- [ ] Monitoring points at `https://<server>/api/health`, and syslog is forwarded
- [ ] Credential profiles and devices added, first backups successful
- [ ] Live upgrades stay off until the platform has passed the lab tests
      ([upgrade-lab-tests.md](../upgrade-lab-tests.md))
