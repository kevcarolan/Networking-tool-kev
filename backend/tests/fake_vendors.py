"""The simulator (tests/fake_network.py) for the platforms added with multi-vendor
support: their show output and how they react to each upgrade command.

Each SimDevice keeps the vendor's own idea of where software lives:
  image     the running image file, or the slot booted from (primary, partition 0, ...)
  slots     ArubaOS-Switch primary/secondary, AOS 8 partitions 0/1, EXOS primary/secondary,
            OS10 active/standby, EdgeOS default/other: slot -> version
  boot      the boot setting (Arista, Huawei) as in fake_network
Show output comes from tests/vendor_samples.py with the version swapped in.
"""

from tests import vendor_samples as v

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
