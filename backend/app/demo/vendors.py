"""The simulator (tests/fake_network.py) for the platforms added with multi-vendor
support: their show output and how they react to each upgrade command.

Each SimDevice keeps the vendor's own idea of where software lives:
  image     the running image file, or the slot booted from (primary, partition 0, ...)
  slots     ArubaOS-Switch primary/secondary, AOS 8 partitions 0/1, EXOS primary/secondary,
            OS10 active/standby, EdgeOS default/other: slot -> version
  boot      the boot setting (Arista, Huawei) as in fake_network
Show output comes from tests/vendor_samples.py with the version swapped in.
"""

from app.demo import vendor_samples as v

MIB = 1024 ** 2

# The platform's first version command (FACT_COMMANDS[platform][0])
VERSION_COMMANDS = {
    "arista_eos": "show version", "juniper_junos": "show version", "aruba_osswitch": "show version",
    "aruba_aos8": "show version", "dell_os10": "show version", "extreme_exos": "show version",
    "cisco_xr": "show version", "huawei_vrp": "display version",
    "mikrotik_routeros": "/system resource print", "ubiquiti_edgeos": "show version",
}


def setup(d) -> None:
    """Starting state for a new simulated device (called by SimDevice)."""
    d.slots, d.selected = {}, ""
    if d.platform == "aruba_osswitch":
        d.slots = {"primary": (26170212, d.version), "secondary": (25000000, "WC.16.08.0001")}
        d.selected = "primary"
    elif d.platform == "aruba_aos8":
        d.slots = {"0": d.version, "1": "8.6.0.4"}
        d.selected = "0"
    elif d.platform == "extreme_exos":
        d.slots = {"primary": d.version, "secondary": "31.6.1.3"}
        d.selected = "primary"
    elif d.platform == "dell_os10":
        d.slots = {"active": d.version, "standby": "10.5.4.0"}
        d.selected = "active"
        d.install_state = "Completed: No error"
    elif d.platform == "ubiquiti_edgeos":
        d.slots = {"default": d.version, "other": "2.0.8"}
    elif d.platform == "mikrotik_routeros":
        d.rb_firmware, d.rb_pending = d.version, False
    elif d.platform == "cisco_xr":
        d.install_request = "No install operation in progress\n"
    elif d.platform == "huawei_vrp":
        d.files[d.image.split("/")[-1]] = (112345678, "b" * 32)  # the running .cc stays on flash
    firewall_setup(d)


def _ros_size(size: int) -> str:
    """RouterOS 7 rounds file sizes: 13.2MiB, 7.4KiB."""
    return f"{size / MIB:.1f}MiB" if size >= MIB else f"{size / 1024:.1f}KiB"


def _listing(d, style: str) -> str:
    rows = list(d.files.items())
    if style == "ios":  # Arista, IOS-XR
        return "".join(f"  {size}  -rw-  Jan 1 2024 10:00:00  {n}\n" for n, (size, _) in rows)
    if style == "unix":  # Junos, AOS 8, OS10, EXOS, EdgeOS
        return "".join(f"-rw-r--r--  1 up  up  {size} Jan  1 10:00 {n}\n" for n, (size, _) in rows)
    if style == "vrp":
        return "".join(f"  1  -rw-   {size:,}  Jan 01 2024 10:00:00   {n}\n" for n, (size, _) in rows)
    raise ValueError(style)


def version_text(d) -> str | None:
    ver = d.version
    if d.platform == "arista_eos":
        return v.EOS_VERSION.replace("4.30.1F", ver)
    if d.platform == "juniper_junos":
        return v.JUNOS_VERSION.replace("22.4R3-S2.11", ver)
    if d.platform == "aruba_osswitch":
        return v.OSSWITCH_VERSION.replace("WC.16.11.0012", ver).replace(
            "Boot Image:     Primary", f"Boot Image:     {d.image.title()}")
    if d.platform == "aruba_aos8":
        return v.AOS8_VERSION.replace("8.10.0.7", ver)
    if d.platform == "dell_os10":
        return v.OS10_VERSION.replace("10.5.5.5", ver)
    if d.platform == "extreme_exos":
        return v.EXOS_VERSION.replace("31.7.1.4", ver)
    if d.platform == "cisco_xr":
        return v.XR_VERSION.replace("7.9.2", ver)
    if d.platform == "huawei_vrp":
        return v.VRP_VERSION.replace("V200R021C10SPC600", ver)
    if d.platform == "mikrotik_routeros":
        return v.ROUTEROS_RESOURCE.replace("7.12.1", ver)
    if d.platform == "ubiquiti_edgeos":
        return v.EDGEOS_VERSION.replace("v2.0.9-hotfix.7", f"v{ver}")
    return None


def output(d, cmd: str) -> str | None:
    """Show output for the new platforms (None: not handled here)."""
    p = d.platform
    fw = firewall_output(d, cmd)
    if fw is not None:
        return fw
    if cmd == VERSION_COMMANDS.get(p):
        return version_text(d)
    if p == "arista_eos":
        if cmd == "dir flash:":
            running = d.image.split(":")[-1].lstrip("/")
            return (f"Directory of flash:/\n\n  1028382542  -rwx  Jan 1 2024 10:00:00  {running}\n"
                    + _listing(d, "ios") + "\n3957301248 bytes total (1916573028 bytes free)\n")
        if cmd == "show boot-config":
            return f"Software image: {d.image.replace('flash:', 'flash:/')}\nConsole speed: (not set)\n"
        if cmd == "show mlag detail":
            ok = d.peer is not None and d.peer.up
            return (f"MLAG Status:\nstate                       :     {'Active' if ok else 'Inactive'}\n"
                    f"negotiation status          :     {'Connected' if ok else 'Connecting'}\n"
                    f"peer-link status            :     {'Up' if ok else 'Down'}\n\n"
                    f"MLAG Detailed Status:\nState                       :     {d.role}\n")
    if p == "juniper_junos":
        if cmd == "show chassis hardware":
            return v.JUNOS_HARDWARE
        if cmd.startswith("file list "):
            return "/var/tmp/:\n" + _listing(d, "unix")
        if cmd.startswith("file checksum md5 "):
            path = cmd.split()[-1]
            name = path.split("/")[-1]
            return f"MD5 ({path}) = {d.files[name][1]}\n" if name in d.files else \
                f"error: could not resolve file: {path}\n"
    if p == "aruba_osswitch":
        if cmd == "show system":
            return v.OSSWITCH_SYSTEM
        if cmd == "show modules":
            return v.OSSWITCH_MODULES
        if cmd == "show flash":
            return "Image           Size (Bytes) Date   Version\n" + "".join(
                f"{slot.title()} Image    : {size:>10} 03/13/23 {ver}\n"
                for slot, (size, ver) in d.slots.items()) + \
                f"\nBoot ROM Version : WC.17.02.0006\nDefault Boot Image   : {d.selected.title()}\n"
        if cmd == "show ip ssh":
            return "  SSH Enabled     : Yes\n  Secure Copy Enabled : Yes\n"
    if p == "aruba_aos8":
        if cmd == "show inventory":
            return v.AOS8_INVENTORY
        if cmd == "dir":
            return _listing(d, "unix")
        if cmd == "show image version":
            return "".join(
                f"----------------------------------\nPartition               : 0:{n} (/dev/usb/flash{n})"
                f"{' **Default boot**' if n == d.selected else ''}\n"
                f"Software Version        : ArubaOS {ver} (Digitally Signed - Production Build)\n"
                for n, ver in sorted(d.slots.items()))
    if p == "dell_os10":
        if cmd == "show inventory":
            return v.OS10_INVENTORY
        if cmd == "dir home":
            return "Directory contents for folder: home\n" + _listing(d, "unix")
        if cmd == "show image status":
            return f"Image Upgrade State:     idle\nState Detail:            {d.install_state}\n"
    if p == "extreme_exos":
        if cmd == "show switch":
            return v.EXOS_SWITCH.replace("Primary ver:      31.7.1.4",
                                         f"Primary ver:      {d.slots['primary']}") \
                .replace("Image Selected:   primary", f"Image Selected:   {d.selected}") \
                .replace("Image Booted:     primary", f"Image Booted:     {d.image}")
        if cmd == "ls":
            return _listing(d, "unix")
    if p == "cisco_xr":
        if cmd == "show inventory":
            return v.XR_INVENTORY
        if cmd == "dir harddisk:":
            return "Directory of harddisk:\n" + _listing(d, "ios")
        if cmd.startswith("show md5 file "):
            name = cmd.split("/")[-1]
            return f"{d.files[name][1]}\n" if name in d.files else "No such file\n"
        if cmd == "show install request":
            return d.install_request
    if p == "huawei_vrp":
        if cmd == "display esn":
            return v.VRP_ESN
        if cmd == "dir flash:/":
            return "Directory of flash:/\n" + _listing(d, "vrp")
        if cmd.startswith("dir flash:/"):
            name = cmd.split("/")[-1]
            if name not in d.files:
                return "Error: File can't be found in the directory.\n"
            return f"Directory of flash:/\n  1  -rw-   {d.files[name][0]:,}  Jan 01 2024 10:00:00   {name}\n"
        if cmd == "display startup":
            nxt = d.boot[0] if d.boot else d.image
            return (f"MainBoard:\n  Configured startup system software:        {d.image}\n"
                    f"Startup system software:      {d.image}\n"
                    f"Next startup system software: {nxt}\n")
        if cmd == "display scp":
            return "SCP server state             : Enable\n"
    if p == "mikrotik_routeros":
        if cmd == "/system routerboard print":
            return v.ROUTEROS_ROUTERBOARD.replace("current-firmware: 7.12.1",
                                                  f"current-firmware: {d.rb_firmware}") \
                .replace("upgrade-firmware: 7.12.1", f"upgrade-firmware: {d.version}")
        if cmd == "/file print terse":
            return "".join(f" {i} name={n} type=package size={_ros_size(size)}\n"
                           for i, (n, (size, _)) in enumerate(d.files.items()))
    if p == "ubiquiti_edgeos":
        if cmd.startswith("ls -l "):
            return _listing(d, "unix")
        if cmd.startswith("md5sum "):
            name = cmd.split("/")[-1]
            return f"{d.files[name][1]}  {cmd.split()[-1]}\n" if name in d.files else \
                f"md5sum: {cmd.split()[-1]}: No such file or directory\n"
    return None


def transfer(d, file_system: str, filename: str, size: int, md5: str, version: str) -> bool:
    """ArubaOS-Switch: the upload goes straight into an image slot."""
    if d.platform == "aruba_osswitch" and file_system.startswith("/os/"):
        d.slots[file_system.split("/")[-1]] = (size, version)
        return True
    return False


def execute(net, d, cmd: str) -> str | None:
    """An exec (change) command on the new platforms (None: not handled here)."""
    from app.tools.firmware_upgrade.deviceio import RELOAD_CLOSED

    p = d.platform
    version_of = net._image_version
    fw = firewall_execute(net, d, cmd)
    if fw is not None:
        return fw
    if p == "arista_eos" and cmd == "reload now":
        boot = d.boot[0] if d.boot else d.image
        net.reload(d, version_of(boot), boot)
        return RELOAD_CLOSED
    if p == "juniper_junos":
        if cmd.startswith("request system software add "):
            name = cmd.split()[4].split("/")[-1]
            if name not in d.files:
                return f"error: could not find {name}"
            net.reload(d, net.versions[name])
            return "Validating on fpc0\nDone with validate on all virtual chassis members\n" \
                   "Rebooting" + RELOAD_CLOSED
        if cmd == "request system software rollback":
            d.rollback_to = d.previous[0] if d.previous else d.version
            return "Junos version will become active at next reboot\n"
        if cmd == "request system reboot":
            net.reload(d, getattr(d, "rollback_to", None) or d.version)
            return "Reboot the system ? [yes,no] (no) " + RELOAD_CLOSED
    if p == "aruba_osswitch":
        if cmd.startswith("boot set-default flash "):
            d.selected = cmd.split()[-1]
            return ""
        if cmd == "reload":
            net.reload(d, d.slots[d.selected][1], d.selected)
            return "Device will be rebooted, do you want to continue [y/n]? " + RELOAD_CLOSED
    if p == "aruba_aos8":
        if cmd.startswith("copy flash: "):
            name, n = cmd.split()[2], cmd.split()[-1]
            if name not in d.files:
                return "Error: file not found"
            d.slots[n] = net.versions[name]
            return "Copy completed successfully.\n"
        if cmd.startswith("boot system partition "):
            d.selected = cmd.split()[-1]
            return ""
        if cmd == "reload":
            net.reload(d, d.slots[d.selected], f"partition {d.selected}")
            return "Do you really want to restart the system(y/n): " + RELOAD_CLOSED
    if p == "dell_os10":
        if cmd.startswith("image install home://"):
            name = cmd.split("//")[-1]
            if "image_install" in d.fail or name not in d.files:
                d.install_state = "Failed: image install failed"
                return ""
            d.slots["standby"] = net.versions[name]
            d.install_state = "Completed: No error"
            return ""
        if cmd == "boot system standby":
            d.selected = "standby" if d.selected == "active" else "active"
            return ""
        if cmd == "reload":
            if d.selected == "standby":  # the partitions swap roles on boot
                d.slots = {"active": d.slots["standby"], "standby": d.slots["active"]}
                d.selected = "active"
            net.reload(d, d.slots["active"])
            return "Proceed to reboot the system? [confirm yes/no]: " + RELOAD_CLOSED
    if p == "extreme_exos":
        if cmd.startswith("install image "):
            name = cmd.split()[2]
            other = "secondary" if d.image == "primary" else "primary"
            d.slots[other] = net.versions[name]
            d.selected = other
            net.reload(d, d.slots[other], other)
            return "Installation complete. Rebooting..." + RELOAD_CLOSED
        if cmd.startswith("use image "):
            d.selected = cmd.split()[-1]
            return ""
        if cmd == "reboot":
            net.reload(d, d.slots[d.selected], d.selected)
            return "Are you sure you want to reboot the switch? (y/N) " + RELOAD_CLOSED
    if p == "huawei_vrp":
        if cmd.startswith("startup system-software "):
            path = cmd.split()[-1]
            if path.split("/")[-1] not in d.files:
                return "Error: The file does not exist."
            d.boot = [path]
            return "Info: Succeeded in setting the software for booting system.\n"
        if cmd == "save":
            return "Are you sure to continue?[Y/N]: y\nSave the configuration successfully.\n"
        if cmd == "reboot":
            boot = d.boot[0] if d.boot else d.image
            net.reload(d, version_of(boot), boot)
            return "System will reboot! Continue? [Y/N]: " + RELOAD_CLOSED
    if p == "cisco_xr":
        if cmd.startswith("install add source "):
            name = cmd.split()[-1]
            d.added = name if name in d.files else None
            d.install_request = ("No install operation in progress\n" if d.added else
                                 "Install operation 3 failed: file not found\n")
            return "Install operation 3 started by up:\n  install add source harddisk: " + name
        if cmd.startswith(("install activate ", "install replace ")):
            name = cmd.split()[2].split("/")[-1]
            if "activate" in d.fail:
                return "Install operation 4 failed: insufficient space"
            d.uncommitted = True
            net.reload(d, net.versions[name])
            return "Install operation 4 started\nThe system will reload" + RELOAD_CLOSED
        if cmd == "install commit":
            d.uncommitted = False
            return "Install operation 5 started by up:\n  install commit\n"
        if cmd == "reload location all noprompt":
            d.uncommitted = False
            net.reload(d, d.previous[0] if d.previous else d.version)
            return RELOAD_CLOSED
    if p == "mikrotik_routeros":
        if cmd == "/system reboot":
            npk = next((n for n in d.files if n.endswith(".npk")), None)
            version = net.versions[npk] if npk else d.version
            if npk:
                del d.files[npk]  # RouterOS removes the package once it is installed
            if d.rb_pending:
                d.rb_firmware, d.rb_pending = d.version, False
            net.reload(d, version)
            return "Reboot, yes? [y/N]: y" + RELOAD_CLOSED
        if cmd == "/system routerboard upgrade":
            d.rb_pending = True
            return "Do you really want to upgrade firmware? [y/n] y\nfirmware upgraded successfully, " \
                   "please reboot for changes to take effect!\n"
    if p == "ubiquiti_edgeos":
        if cmd.startswith("add system image "):
            name = cmd.split("/")[-1]
            d.slots = {"default": net.versions[name], "other": d.version}
            return "Checking upgrade image...Done\nAdding new release...Done\nDone.\n"
        if cmd == "set system image default-image":
            d.slots = {"default": d.slots["other"], "other": d.slots["default"]}
            return "The default image has been changed.\n"
        if cmd == "reboot":
            net.reload(d, d.slots["default"])
            return "Proceed with reboot? [confirm][y] " + RELOAD_CLOSED
    return None


# --- firewalls: SSH output and the management APIs ---------------------------------------

def firewall_setup(d) -> None:
    if d.platform == "fortinet_fortios":
        d.slots, d.selected = {"1": d.version, "2": "7.0.12"}, "1"
        d.uninterruptible = True
    elif d.platform == "paloalto_panos":
        d.software = {d.version: True}  # version -> downloaded
        d.next_version, d.suspended, d.jobs = None, False, {}


def firewall_output(d, cmd: str) -> str | None:
    if d.platform == "fortinet_fortios":
        if cmd == "get system status":
            mode = "standalone" if not d.role else f"a-p, {d.role}"
            return v.FORTIOS_STATUS.replace("v7.2.5,build1517", f"v{d.version},build1517") \
                .replace("Current HA mode: a-p, primary", f"Current HA mode: {mode}")
        if cmd == "diagnose sys flash list":
            return "Partition  Image                         TotalSize(KB)  Used(KB)  Use%  Active\n" + \
                "".join(f"{p}          FGT60F-{ver}-FW-build1517      253920    164104   65%  "
                        f"{'Yes' if p == d.selected and d.up else 'No'}\n"
                        for p, ver in sorted(d.slots.items()))
        if cmd == "get system ha status":
            if not d.role:
                return "HA Health Status: OK\nModel: FortiGate-60F\nMode: standalone\n"
            return "HA Health Status: OK\nModel: FortiGate-60F\nMode: HA A-P\nGroup: 1\n"
        if cmd == "get system ha | grep uninterruptible-upgrade":
            return f"uninterruptible-upgrade: {'enable' if d.uninterruptible else 'disable'}\n"
    if d.platform == "paloalto_panos":
        if cmd == "show system info":
            return v.PANOS_INFO.replace("sw-version: 10.2.7-h3", f"sw-version: {d.version}")
        if cmd == "show high-availability state":
            if not d.role:
                return "HA not enabled\n"
            peer = d.peer
            link = "up" if peer is not None and peer.up else "down"
            me = "suspended" if d.suspended else d.role
            other = ("suspended" if peer.suspended else peer.role) if peer and peer.up else "unknown"
            return (f"Group 1:\n  Mode: Active-Passive\n  Local Information:\n    Version: 1\n"
                    f"    State: {me} (last 1 days)\n  Peer Information:\n"
                    f"    Connection status: {link}\n    State: {other} (last 1 days)\n")
    return None


def firewall_execute(net, d, cmd: str) -> str | None:
    from app.tools.firmware_upgrade.deviceio import RELOAD_CLOSED

    if d.platform == "fortinet_fortios":
        if cmd.startswith("execute set-next-reboot "):
            d.selected = {"primary": "1", "secondary": "2"}[cmd.split()[-1]]
            return "Default image is changed to image# " + d.selected + ".\n"
        if cmd == "execute reboot":
            net.reload(d, d.slots[d.selected])
            return "This operation will reboot the system !\nDo you want to continue? (y/n)y" + \
                RELOAD_CLOSED
    return None


class FakeFortios:
    """The FortiGate REST API: the image upload installs and reboots."""

    def __init__(self, net, dev):
        self.net, self.dev = net, dev

    def _up(self):
        from app.core.ssh import UNREACHABLE, DeviceError
        if not self.dev.up:
            raise DeviceError(UNREACHABLE, "FortiGate API unreachable: device down")

    def login(self):
        self._up()

    def status(self):
        self._up()
        return {"version": f"v{self.dev.version}", "build": 1517}

    def upgrade(self, local):
        from app.core.ssh import ERROR, DeviceError
        self._up()
        d = self.dev
        d.commands.append(f"api:upgrade {local.name}")
        self.net.log.append((d.name, f"api:upgrade {local.name}"))
        if "image_rejected" in d.fail:
            raise DeviceError(ERROR, "FortiGate refused the image: invalid firmware")
        version = self.net.versions[local.name]
        other = "2" if d.selected == "1" else "1"
        d.slots[other], d.selected = version, other
        if d.role:  # an HA cluster upgrades itself; its address stays up
            d.version = version
            return {"status": "success"}
        self.net.reload(d, version)
        return {"status": "success"}


class FakePanos:
    """The PAN-OS XML API."""

    def __init__(self, net, dev):
        self.net, self.dev = net, dev

    def _up(self):
        from app.core.ssh import UNREACHABLE, DeviceError
        if not self.dev.up:
            raise DeviceError(UNREACHABLE, "PAN-OS API unreachable: device down")

    def _log(self, what):
        self.dev.commands.append(what)
        self.net.log.append((self.dev.name, what))

    def login(self):
        self._up()

    def software_info(self):
        self._up()
        return [{"version": ver, "downloaded": dl, "current": ver == self.dev.version}
                for ver, dl in self.dev.software.items()]

    def upload(self, local):
        self._up()
        self._log(f"api:upload {local.name}")
        self.dev.software[self.net.versions[local.name]] = True

    def install(self, version):
        self._up()
        self._log(f"api:install {version}")
        job = str(len(self.dev.jobs) + 1)
        ok = self.dev.software.get(version) and "install" not in self.dev.fail
        self.dev.jobs[job] = {"status": "FIN", "result": "OK" if ok else "FAIL",
                              "details": "" if ok else f"Failed to install {version}"}
        if ok:
            self.dev.next_version = version
        return job

    def job(self, job_id):
        self._up()
        return dict(self.dev.jobs[job_id])

    def restart(self):
        self._up()
        self._log("api:restart")
        self.net.reload(self.dev, self.dev.next_version or self.dev.version)

    def ha_state(self, state):
        self._up()
        self._log(f"api:ha {state}")
        d = self.dev
        d.suspended = state == "suspend"
        if d.suspended and d.role == "active" and d.peer:  # the peer takes over
            d.role, d.peer.role = "passive", "active"
