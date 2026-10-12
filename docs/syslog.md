# Syslog

A central place for the devices' log messages: the first place to look when something
goes wrong on site, instead of logging in to switch after switch.

The devices send syslog to the server, and the **Syslog** page searches it. You can narrow
it down by device, severity (Emergency to Debug), period and text, see a timeline of how
many messages arrived when, and download what you found as a `.log` file. A device's
**Logs** button on Config backups opens the page with only that device's messages.

## How it works

* **The receiver** is its own small service, `netops-syslog`. It listens on **UDP and TCP
  port 514**, runs as the `netops` account, and has one extra right: to listen on a port
  below 1024. Restarting or upgrading the web app doesn't stop it, so no messages are lost.
* **The sender is the address the message came from.** It is matched to the inventory
  by the device's address. A device that sends from another address (a loopback or
  another interface) shows as a *sender not in the inventory*: set its logging source
  interface to the management address.
* **Storage: one file per day** in `/var/lib/netops/syslog/` (`2026-10-12.db`, and so on).
  Days are in UTC, by the time the server received the message. Each file is a small
  database with indexes, so searching a day or a month is quick. Old messages are removed
  by deleting whole days, and each day can be downloaded as plain text.
* **Nothing is lost when parsing.** The whole line is kept as the device sent it. The
  severity and facility are read from it, and so are the message code or program
  (`%LINK-3-UPDOWN`, `%ASA-4-106023`, `sshd`, `mib2d`), so you can search for them.

## How long messages are kept

On **Settings › Site and defaults**:

| Setting | Default | |
|---|---|---|
| Keep syslog messages for (days) | 30 | 7, 30, 60 or 90 are usual choices |
| Keep at most this much syslog (GB) | 20 | Whichever limit is reached first wins |
| Keep messages only from inventory devices | off | Otherwise anything the firewall lets in is kept |

* The oldest days are deleted first. Today's file is never deleted.
* Storing stops (and the page says so in red) if today's messages alone go over the size
  limit, or if less than `NETOPS_SYSLOG_KEEP_FREE_MB` (2 GB) of disk is free. It starts
  again by itself once there is room.
* One sender may send up to `NETOPS_SYSLOG_RATE_PER_SOURCE` (2000) messages a second.
  More are counted and dropped, so one device in a loop can't drown the others.

**How much space?** A message takes about 300 bytes on disk. A site of 100 switches at
informational level sends roughly 50,000 to 500,000 messages a day: 15–150 MB a day, so
30 days is 0.5–5 GB. Firewalls that log every connection send far more. Keep connection
logging off, or at *notifications*, unless you need it.

## Setting up the devices

Click **Help: set up devices** on the Syslog page. It shows a suggested config for each
platform (Cisco IOS/IOS-XE, NX-OS, ASA, FTD, IOS-XR, small business, Allied Telesis,
Arista, Juniper, FortiGate, Palo Alto, Check Point, HPE Aruba, Dell, Extreme, MikroTik,
Ubiquiti, Huawei, and Linux), with this server's address filled in, and a **Copy**
button. The same text is in `backend/app/tools/syslog/howto.py`. For every device:

* send from the **management address** that is in the inventory (source interface);
* use **NTP**, so the device's own timestamps line up;
* send **informational** and up. Debug can flood the log.

The configs are a starting point: check them against your release. The server never
changes a device's config by itself.

## Syslog over TLS (encrypted)

Plain syslog crosses the network as readable text, and over UDP anyone on the path can send
a message that looks like it came from a switch. **Syslog over TLS** (RFC 5425, TCP port
6514) encrypts the messages the way HTTPS does: nobody on the way can read or change them,
the device checks it is talking to this server, and over TCP nothing is silently lost. Use
it when syslog crosses a network you don't control (between sites, over a provider's WAN),
or when a customer's security policy asks for it. Plain and TLS can run side by side.

**On the server** (off until you switch it on):

1. The certificate: by default the receiver uses the **web server's certificate** (the
   one from the setup screen). systemd hands the receiver a private copy when it starts,
   so the key in `/etc/netops/tls/` stays readable by root only. The certificate must name
   what the devices send to: the server's DNS name, or its IP address (add the address to
   the names when you make the certificate request on Settings › Certificate).
2. In `/etc/netops/netops.env`: `NETOPS_SYSLOG_TLS_PORT=6514`, then
   `sudo systemctl restart netops-syslog`.
3. The firewall already lets `SYSLOG_SOURCES` reach TCP 6514.
4. The Syslog page's status line shows "TLS on port 6514", or in red why it isn't
   listening (plain syslog keeps working either way).

A new certificate from the setup screen restarts the receiver by itself, so TLS uses it
straight away.

**Optional:**

* A separate certificate for syslog: `NETOPS_SYSLOG_TLS_CERT` and `NETOPS_SYSLOG_TLS_KEY`
  (files the `netops` account can read, e.g. `root:netops 0640`).
* **Devices must prove who they are:** `NETOPS_SYSLOG_TLS_CLIENT_CA=<CA file>`. Every
  device then needs its own certificate signed by that CA, and devices without one are
  refused. This is stronger, but means a certificate on every device.

**On the devices:** **Help: set up devices**, *Send as: Encrypted*. It has examples for
Cisco IOS-XE, NX-OS and ASA, Juniper, Arista, FortiGate, Palo Alto, HPE Aruba AOS-CX and
Linux. Each device needs the CA certificate that signed the server's certificate. Platforms
without an example (small switches, MikroTik, Ubiquiti and others) can't send TLS, or only
on some releases: keep those on plain syslog over the management network. Time must be
right on both sides (NTP), or the certificate check fails.

## The firewall

The hardened firewall (`deploy/hardening/nftables.conf`) lets syslog in only from
`SYSLOG_SOURCES`, on UDP and TCP 514, and TCP 6514 for syslog over TLS. Set it to the devices' management networks
(usually the same as `DEVICE_NETS`), then reload: `sudo nft -f /etc/nftables.conf`.

## Email alerts for serious messages

On **Settings › Email alerts**, tick **Syslog** for the recipients who should get them, and
choose the level: Emergency only, Alert and worse, **Critical and worse** (the default) or
Error and worse. Messages at that level are gathered into at most one email every few
minutes (5 by default), listing up to 50 with the device, time and message. Only messages
that arrive after a recipient chooses Syslog are sent, not the history.

## Checking and troubleshooting

| Symptom | Check |
|---|---|
| "The syslog receiver isn't running" | `systemctl status netops-syslog`; `journalctl -u netops-syslog -n 50` |
| A device's messages don't arrive | Is the device in `SYSLOG_SOURCES`? On the server: `sudo tcpdump -ni any udp port 514 and host <device>` |
| The messages show as a sender not in the inventory | The device sends from another address: set its logging source interface to the address in the inventory |
| "NOT STORING" in red | The disk is nearly full, or today's messages are over the size limit: lower the level on chatty devices, or raise the limit |
| "TLS NOT LISTENING: …" in red | The reason follows: usually no certificate, or a key that doesn't match. `journalctl -u netops-syslog -n 50` |
| A device can't connect over TLS | The device must trust the CA that signed the server's certificate, send to a name or address that is in it, and have the right time |
| "dropped (too many from one sender)" | A device is sending more than 2000 messages a second: look at it (often a loop or debug left on) |

Downloads are recorded in the activity report (`syslog.export`). Syslog files aren't part
of the nightly server backup (`netops-backup`): they are large and only kept for a set
time. (A second, standby server holding copies is planned for later.)

## Who can see it

The permission area **Syslog** (Users page): *none* or *view*. Users who were added before
syslog existed get *view*. Messages can contain user names and addresses, so set *none*
for anyone who shouldn't see them.
