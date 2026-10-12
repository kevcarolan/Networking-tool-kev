# Installing on a server with internet access

For a server that can reach the internet, at least while you install or upgrade. For a
network with no internet access, use [install-airgap.md](install-airgap.md) instead.

The online installer does the same as the air-gapped install, but on the server itself:

1. it installs the Ubuntu packages from Ubuntu's own repositories;
2. it builds an install bundle from your copy of the code, downloading the Python
   packages from PyPI and checking them for known vulnerabilities;
3. it runs the bundle's installer.

So both kinds of site install, upgrade and roll back in exactly the same way. The bundle
is kept, so you can install the same version on an air-gapped server of the same Ubuntu
release.

## 1. What you need

* **Ubuntu Server 26.04 LTS**, minimal install, with:
  * 2 vCPU;
  * 4 GB of memory;
  * 40 GB of disk, plus room for firmware images.

  [install-airgap.md](install-airgap.md) §2 describes the server build. It is the same here.
* A DNS name for the server, for example `netops.corp.local`.
* While installing or upgrading, outbound HTTPS (TCP 443) to:
  * the Ubuntu archive (or your apt mirror);
  * `pypi.org` and `files.pythonhosted.org`;
  * the git server you clone the code from.
* Access to the repository: a read-only deploy key or account.

## 2. Get the code

```bash
sudo apt-get update && sudo apt-get install -y git
sudo git clone <repository URL> /usr/local/src/netops
cd /usr/local/src/netops
```

Clone it **as root** into a root-owned folder, such as `/usr/local/src/netops`. The
installer runs as root, so it refuses a copy that any other account could change (one
in your home folder, for example): whoever could edit it could run commands as root at the
next upgrade.

To install a particular version, check out its tag or commit:
`sudo git checkout <tag>`.

## 3. Install

```bash
sudo deploy/install-online.sh
```

It takes a few minutes. On a first install, it:
* creates the `netops` service account and the folders;
* makes a temporary 30-day certificate;
* starts the services.

It ends with the next steps.

Then follow [install-airgap.md](install-airgap.md) **§6 First-time configuration**, from the
encryption key onwards:
1. save `/etc/netops/credential.key` offline;
2. open `https://<server name>/` and complete the setup screen (admin, Active Directory,
   certificate);
3. add the licence on the Settings page;
4. harden the server.

The installer keeps the bundle in `/usr/local/src/netops/dist/`, with its SHA-256 and a list of every
package and version. Attach that list to your change ticket.

## 4. Upgrade

```bash
cd /usr/local/src/netops
sudo git pull         # or: sudo git fetch && sudo git checkout <new tag>
sudo deploy/install-online.sh
```

* The running version is backed up and the database copied before the switch.
* If the new version doesn't come back healthy, the installer puts the previous version
  (and its database) back by itself.
* The installer won't restart while a live device upgrade is running.

## 5. The firewall after hardening

The hardened firewall ([security-hardening.md](security-hardening.md) §5) blocks all
outbound traffic except to the devices and your own services. That includes the internet,
so installs and upgrades can't download anything. Choose one:

* **Open it only for the upgrade.** Add a rule for TCP 443 out to your proxy or the
  internet, run the upgrade, then reload the normal rules (`sudo nft -f /etc/nftables.conf`).
* **Use a proxy.** Allow TCP out to the proxy only, and set it for the install:
  `sudo https_proxy=http://proxy:3128 http_proxy=http://proxy:3128 deploy/install-online.sh`.
  Set apt's proxy in `/etc/apt/apt.conf.d/` too.
* **Treat the site as air-gapped.** Build the bundle on another machine and install it
  with [install-airgap.md](install-airgap.md).

The app itself never needs the internet. Licences are checked on the server, and there's
no telemetry and no update check.

## 6. Options

| Option | What it does |
|---|---|
| `--skip-os-packages` | Don't install Ubuntu packages (they're already there) |
| `ALLOW_VULNS=1` | Install even if a Python package has a known vulnerability (avoid this; better to wait for a fixed version) |
| `FORCE=1` | Upgrade even while a live device upgrade is running (don't) |
