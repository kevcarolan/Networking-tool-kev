# Trying it out: the demo on your own computer

Everything runs on your own computer, against a **simulated network of 25 devices**. There is
no lab to build and nothing to connect: the switches, firewalls and their answers are
simulated inside the program. Nothing is sent to a real device. (Testing against real
devices comes later: see [upgrade-lab-tests.md](upgrade-lab-tests.md).)

## 1. What you need

* **Python 3.11 or newer**: <https://www.python.org/downloads/>. On Windows, tick *Add
  python.exe to PATH* when installing.
* **Git**: <https://git-scm.com/downloads> (Windows: *Git for Windows*). Config backups
  are kept in a git repository.
* About 300 MB of disk, and a web browser.

## 2. Download

Either:

* on GitHub, **Code › Download ZIP**, and unzip it anywhere; or
* `git clone https://github.com/kevcarolan/Networking-tool-kev.git`

## 3. Start it

* **Windows:** double-click `run-demo.bat` in the folder.
* **Mac or Linux:** in a terminal, in the folder: `./run-demo.sh`

The first start takes a minute or two (it downloads the Python packages). Then it shows:

```
Demo running on http://127.0.0.1:8710  (sign in as demo / demo-password)
Wall display: http://127.0.0.1:8710/display/#key=...
```

Open <http://127.0.0.1:8710> and sign in as **demo** / **demo-password**. Leave the window
with the messages open: closing it (or Ctrl+C) stops the demo.

* **Carry on later:** start it again; everything you did is kept (in `demo-data/`).
* **Start afresh:** `run-demo.bat --reset` or `./run-demo.sh --reset`.
* **Port 8710 in use?** Add `--port 8720` and open that port instead.

## 4. What to try

Tick these off as you go. Anything that looks wrong, odd or unclear: note the page, what
you did and what you expected, and send it over.

**Config backups**
- [ ] The tiles at the top: 25 devices, two failing (bn-sw3 unreachable, wh-sw2 wrong password).
- [ ] **History** on a device: its backups, **Config versions**, and a diff between two.
- [ ] **Backup now** on a device, and watch its result change.
- [ ] **+ Add device**, edit one, and delete it again.

**Inventory**
- [ ] 43 items: 25 managed devices and 18 others (racks, UPSs, PDUs, servers, a spare switch).
- [ ] Filter by site, type, status and *Inventory only*; search for `Dell` or `HQ-R01`.
- [ ] **Columns**: add *Room* and *Power feed*, move them, then **Reset to the defaults**.
- [ ] Open a managed device: grey values come from the device; type over one.
- [ ] **Custom columns** (admin): add one, see it in the form and in **Columns**.
- [ ] **Excel** export, change something in Excel, **Import** it back: check the preview.
- [ ] Open *spare-c9300-48p*, **Manage this device…**: it becomes a managed device.
- [ ] **Blank template**: the columns you see, as CSV; fill in two rows and **Import** it.

**Sites**
- [ ] Four sites, and a note that the inventory also uses *Warehouse*: **Add them to the list**.
- [ ] Open *Head office*: its details and the 19 items there, with their backup and firmware state.
- [ ] Rename a site's code (e.g. `HQ` to `HO`), then check the devices' site on Config backups.
- [ ] Click *Head office*: its buildings, floors and rooms; click **Comms 1** for its two racks.
- [ ] Drag *spare-c9300-48p* (in **Stores**, on **Ground floor**) into HQ-R01; drag a server onto
      another item (refused); drag a patch panel to the rear; **Print**.
- [ ] Add a room (**+ room**), rename it, delete it. **+ Add a rack here** in a room.
- [ ] In the inventory, click a Rack value: it opens the rack.
- [ ] Click *Head office*'s **Circuits** count: the 72 circuits there. Click a Site link on
      Circuits, Inventory or Config backups: it opens the site.
- [ ] **Columns** (add *Firmware behind*), **Custom columns**, **Blank template**, **Import**.

**Firmware and upgrades**
- [ ] **Firmware › Versions**: which devices are behind their standard.
- [ ] **Upgrade jobs › New upgrade job** on `hq-acc-sw3` (or `dc1-leaf3`, `bn-sw1`):
      choose its image, **Live**, a window that has already started; **Run pre-checks**,
      **Start**, type the device name. Watch the steps for about 40 seconds: backup, copy,
      install, reload (the switch is down for about 15 seconds), post-checks, commit.
- [ ] Open the job's **report**.
- [ ] Try a **dry run** on another device: the same steps, nothing changed.
- [ ] On `dc1-leaf3` (Arista), `dc1-spine1` (Juniper) or `hq-core1` (NX-OS), the pre-checks
      list fans/power, alarms, modules, CPU, memory, unsaved config and last restart, and the
      post-checks compare interfaces, LLDP neighbours, port-channel members and modules.

**Circuits**
- [ ] 72 circuits; one has **moved** port and one is **not seen**.
- [ ] **Scan network now**, and the circuit exports.
- [ ] **Columns**: add *Patch panel* (a custom column) and *Subnet Mask*, take away *Drawing*.
- [ ] **Blank template** (the columns you see, CSV): fill in a few rows and **Upload spreadsheet**
      it: check the preview, then **Discard** (or make it live and upload the export again).
- [ ] **Custom columns** (admin): add one, then upload a sheet with a column of that name.

**Syslog**
- [ ] The last 24 hours: severity buttons, the timeline (click a bar to zoom in).
- [ ] **Errors and worse**; search `BGP`, `%LINK` or `203.0.113.66`.
- [ ] Pick a device, or *Senders not in the inventory*.
- [ ] **Live**: a new message every few seconds.
- [ ] **Help: set up devices**: the configs per platform, plain and encrypted.
- [ ] **Download .log**.

**Compliance, alerts, report**
- [ ] **Config backups › Compliance**: the example rules; six HQ switches fail. Open one with
      **⚠ 3 compliance rule(s)**; add a rule of your own.
- [ ] **Ports** on `hq-acc-sw1` (Config backups or Inventory): click a port.
- [ ] **Activity › Report** for 7 days; **Print**.
- [ ] **Settings › Email alerts**: Config changes, Compliance and Report (the emails need a
      real mail server).

**Everything else**
- [ ] **Search** (top right, or press **/**): `branch` (sites and devices), `ups` (inventory
      items), a circuit's MAC in any format (the circuit, and the switch port it is on: Enter
      opens the port), a circuit's IP.
- [ ] The **wall display** link (from the start-up messages) in a second window: the
      overview, the sites and network pages, and the upgrades page while an upgrade runs.
      On **Settings › Wall displays**, untick a page and **Save pages**.
- [ ] **Users**: add a user with *Viewer*, sign in as them in a private window, and see
      what they can't do.
- [ ] **Activity**: everything you did above is listed.
- [ ] **Settings**: site name, syslog retention, email alerts (the test email needs a real
      mail server), licence (the demo needs none).

## 5. What the demo doesn't show

* **Real devices:** the simulator answers like the real ones, but every platform still needs
  a lab check ([upgrade-lab-tests.md](upgrade-lab-tests.md)).
* **The installed server:** sign-in with Active Directory, the certificate, the services,
  the firewall and real syslog on port 514. For that, install on an Ubuntu 26.04 virtual
  machine with [install-online.md](install-online.md), and point a few lab devices at it.
* **Licences:** the demo needs none, so every tool is unlocked.
