# Demo mode

The whole product on a simulated network, for showing it to a customer, or trying it out,
without real devices.

```bash
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python -m app.demo
```

Open `http://127.0.0.1:8710` and sign in as **demo** / **demo-password**. The command also
prints a link for the **wall display**: open it in a second window or on a big screen.

## What's in it

* **25 devices on 5 sites:**
  * HQ: six Catalyst 9300s, two Nexus cores and an ASA;
  * DC1: four Arista leaves and two Juniper spines;
  * Branch-North: three ArubaOS-Switch and a MikroTik;
  * Branch-South: three AlliedWare Plus;
  * Warehouse: three Dell OS10.
* **Backups** for every device. Two fail on purpose: one is unreachable and one has a wrong
  password, so "Needs attention" has something in it.
* **Firmware standards** for five platforms, with some devices behind. There are images for
  Catalyst 9300, Arista and ArubaOS-Switch, so those can be upgraded.
* **A circuit list** of 72 end devices on the HQ access switches (CCTV, access control,
  building management, wireless). After the first scan, one has **moved** port and one is
  **not seen**.
* **A wall display** called "Demo wall".
* **An inventory** of 42 items: the 25 devices with their rack places, plus racks, UPSs,
  PDUs, patch panels, servers, a storage array and a spare switch. There is a custom
  column *Power feed*, a faulty UPS at Branch-North, and a spare switch in the stores.
* **Syslog:** three days of messages from every device, at every severity, then a new one
  every few seconds (try **Live**). Some incidents run through them:
  * BGP between dc1-spine1 and dc1-leaf3 drops (hold timer expired) and comes back;
  * a power supply fails on hq-core1, and the vPC keepalive is lost;
  * the HQ firewall loses its failover link, and wh-sw1 overheats (Emergency);
  * someone tries passwords on hq-fw1 and dc1-spine2 from 203.0.113.66;
  * BPDU guard shuts a user port on hq-acc-sw3;
  * a VPN tunnel on bn-rtr1 keeps failing;
  * an access point that isn't in the inventory (192.0.2.250) sends too.

  Try **Errors and worse**, a device's **Logs** button, or a search for `BGP` or `%LINK`.

## Showing an upgrade

1. **Firmware › Upgrade jobs › New upgrade job:**
   * choose a switch that is behind, for example `hq-acc-sw3`, `dc1-leaf3` or `bn-sw1`;
   * choose its image;
   * choose **Live**;
   * set a window that has already started.
2. **Run pre-checks**, then **Start**. Type the device name to confirm.
3. Watch it go through the steps:
   * backup;
   * copy and checksum;
   * install;
   * reload: the switch is "down" for about 15 seconds;
   * post-checks, including the circuits back on their ports;
   * commit and backup.

   The whole job takes about 40 seconds. On the wall display, the upgrades page shows
   the job, its step and the circuits it affects.

Dry runs, overrides, roll back and the activity report all work the same way as on a real
network.

## Good to know

* **Nothing contacts a real device.** Backups, checks, scans and upgrades all run against
  the simulator (`app/demo/simnet.py`, the same one the tests use). As a second guard, the
  devices have documentation addresses (192.0.2.x), which are never routed.
* **It keeps its own data** in `demo-data/` (or `--data <folder>`). It refuses to use a
  folder that holds anything else, so it can't touch a real database.
* **It needs no licence**, and shows a "Demo" banner on every page.
* **Stopping and starting** keeps everything, including upgrades done in the demo. To start
  again from a fresh network: `python -m app.demo --reset`.
* **Another port:** `python -m app.demo --port 8720`.
* It needs the development requirements (`requirements-dev.txt`), so run it from a copy of
  the code, not on an installed server.
