"""Upgrade procedures for the platforms added with multi-vendor support (PR B), end to end
against the simulator (tests/fake_network.py + tests/fake_vendors.py): live and dry run,
a bad copy, a failed post-check with roll back, and the pair and commit paths."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.tools.firmware_upgrade.drivers import DRIVERS
from app.tools.firmware_upgrade.drivers.arista_eos import mlag_healthy, parse_mlag
from app.tools.firmware_upgrade.drivers.aruba_aos8 import partitions
from app.tools.firmware_upgrade.drivers.aruba_osswitch import flash_slots
from app.tools.firmware_upgrade.drivers.common import file_size
from app.tools.firmware_upgrade.drivers.dell_os10 import install_state
from app.tools.firmware_upgrade.drivers.juniper_junos import vc_members
from tests.conftest import ADMIN_PASSWORD, FakeFetcher
from tests.fake_network import FakeNetwork, SimDevice
from tests.test_upgrade_engine import Lab, _check, _msgs

NEW = ["arista_eos", "juniper_junos", "aruba_osswitch", "aruba_aos8", "dell_os10", "extreme_exos",
       "huawei_vrp", "cisco_xr", "mikrotik_routeros", "ubiquiti_edgeos"]


@pytest.fixture
def lab(settings):
    settings.upgrade_live_platforms = ",".join(NEW)
    net = FakeNetwork()
    app = create_app(settings, fetcher=FakeFetcher(), start_scheduler=False,
                     fw_collector=net.show, upgrade_io=net)
    with TestClient(app) as client:
        assert client.post("/api/auth/login", json={"username": "admin",
                                                    "password": ADMIN_PASSWORD}).status_code == 200
        yield Lab(client, app, net, settings)


# platform: (running version, running image or slot, files already on the device,
#            new image file, new version, a command that must be in the change log)
CASES = {
    "arista_eos": ("4.30.1F", "flash:EOS-4.30.1F.swi", {"EOS-4.30.1F.swi": (1028382542, "a" * 32)},
                   "EOS-4.32.2F.swi", "4.32.2F", "reload now"),
    "juniper_junos": ("22.4R3-S2.11", "", {}, "junos-arm-32-23.4R2-S3.9.tgz", "23.4R2-S3.9",
                      "request system software add /var/tmp/junos-arm-32-23.4R2-S3.9.tgz reboot"),
    "aruba_osswitch": ("WC.16.11.0012", "primary", {}, "WC_16_11_0018.swi", "WC.16.11.0018",
                       "boot set-default flash secondary"),
    "aruba_aos8": ("8.10.0.7", "partition 0", {}, "ArubaOS_72xx_8.10.0.12_89876", "8.10.0.12",
                   "copy flash: ArubaOS_72xx_8.10.0.12_89876 system: partition 1"),
    "dell_os10": ("10.5.5.5", "", {}, "PKGS_OS10-Enterprise-10.5.6.0.bin", "10.5.6.0",
                  "image install home://PKGS_OS10-Enterprise-10.5.6.0.bin"),
    "extreme_exos": ("31.7.1.4", "primary", {}, "summit_arm-32.6.1.2.xos", "32.6.1.2",
                     "install image summit_arm-32.6.1.2.xos reboot"),
    "huawei_vrp": ("V200R021C10SPC600", "flash:/s5735-v200r021c10spc600.cc", {},
                   "s5735-v200r022c00spc500.cc", "V200R022C00SPC500",
                   "startup system-software flash:/s5735-v200r022c00spc500.cc"),
    "cisco_xr": ("7.9.2", "", {}, "asr9k-x64-7.11.2.iso", "7.11.2", "install commit"),
    "mikrotik_routeros": ("7.12.1", "", {}, "routeros-7.15.3-arm64.npk", "7.15.3",
                          "/system routerboard upgrade"),
    "ubiquiti_edgeos": ("2.0.9-hotfix.7", "", {}, "ER-e300.v2.0.9-hotfix.8.tar", "2.0.9-hotfix.8",
                        "add system image /tmp/ER-e300.v2.0.9-hotfix.8.tar"),
}


def _setup(lab, platform, n=1):
    version, image, files, new_file, new_version, _ = CASES[platform]
    sim = SimDevice(f"{platform[:6]}{n}", platform, version, image or "running")
    sim.files.update(files)
    dev = lab.device(sim, f"10.9.{NEW.index(platform)}.{n}")
    img = lab.image(new_file, platform, new_version) if n == 1 else None
    return sim, dev, img


def test_every_new_platform_has_a_driver():
    assert set(NEW) <= set(DRIVERS)
    assert "aruba_aoscx" not in DRIVERS and "cisco_smb" not in DRIVERS  # need a pull method first


@pytest.mark.parametrize("platform", NEW)
def test_live_upgrade(lab, platform):
    sim, dev, img = _setup(lab, platform)
    job = lab.job(dev, img)
    j = lab.act(job, "precheck")
    assert j["status"] == "ready", [c for c in j["checks"]["pre"] if c["status"] in ("fail", "error")]
    j = lab.act(job, "start")
    assert j["status"] == "completed", _msgs(j)
    assert sim.version == CASES[platform][4]
    assert (sim.name, CASES[platform][5]) in lab.net.log
    assert _check(j, "post", "post_version")["status"] == "pass"


@pytest.mark.parametrize("platform", NEW)
def test_dry_run_changes_nothing(lab, platform):
    sim, dev, img = _setup(lab, platform)
    job = lab.job(dev, img, live=False, window=False)
    lab.act(job, "precheck")
    j = lab.act(job, "start")
    assert j["status"] == "completed", _msgs(j)
    assert lab.net.log == [] and sim.reloads == 0
    assert "DRY RUN - would" in _msgs(j)


@pytest.mark.parametrize("platform", [p for p in NEW if p != "aruba_osswitch"])
def test_bad_copy_stops_before_any_reload(lab, platform):
    sim, dev, img = _setup(lab, platform)
    sim.fail.add("copy_md5")
    job = lab.job(dev, img)
    lab.act(job, "precheck")
    j = lab.act(job, "start")
    assert j["status"] == "failed" and sim.reloads == 0, _msgs(j)
    check = next(c for c in j["checks"]["stage"] if c["check_id"] in ("device_md5", "device_size"))
    assert check["status"] == "fail"


def _other_version(version: str) -> str:
    """Same format as the target, one digit different."""
    return version[:-1] + ("8" if version[-1] == "9" else "9")


@pytest.mark.parametrize("platform", ["arista_eos", "juniper_junos", "aruba_osswitch",
                                      "dell_os10", "extreme_exos", "huawei_vrp", "cisco_xr",
                                      "ubiquiti_edgeos"])
def test_failed_post_check_then_roll_back(lab, platform):
    sim, dev, img = _setup(lab, platform)
    old = sim.version
    # the new image boots, but reports another version: the post-check fails
    wrong = _other_version(CASES[platform][4])
    lab.net.versions[CASES[platform][3]] = wrong
    job = lab.job(dev, img)
    lab.act(job, "precheck")
    j = lab.act(job, "start")
    assert j["status"] == "failed" and sim.version == wrong, _msgs(j)
    assert _check(j, "post", "post_version")["status"] == "fail"
    j = lab.act(job, "rollback")
    assert j["status"] == "rolled_back", _msgs(j)
    assert sim.version == old


def test_aos8_partition_is_checked_before_the_reload_and_rolls_back(lab):
    sim, dev, img = _setup(lab, "aruba_aos8")
    lab.net.versions[CASES["aruba_aos8"][3]] = "8.10.0.13"  # not what the library says
    job = lab.job(dev, img)
    lab.act(job, "precheck")
    j = lab.act(job, "start")
    assert j["status"] == "failed" and sim.reloads == 0
    assert _check(j, "stage", "partition_version")["status"] == "fail"
    # the right image this time, but the controller stays on the old software
    lab.net.versions[CASES["aruba_aos8"][3]] = "8.10.0.12"
    sim.fail.add("stays_old")
    j = lab.act(job, "continue")
    assert j["status"] == "failed" and _check(j, "post", "post_version")["status"] == "fail"
    sim.fail.clear()
    j = lab.act(job, "rollback")
    assert j["status"] == "rolled_back" and sim.selected == "0", _msgs(j)
    assert ("aruba_1", "boot system partition 0") in lab.net.log


def test_unreadable_version_after_the_upgrade_fails_the_post_check(lab):
    sim, dev, img = _setup(lab, "huawei_vrp")
    lab.net.versions[CASES["huawei_vrp"][3]] = "9.9.9"  # VRP can't parse this
    job = lab.job(dev, img)
    lab.act(job, "precheck")
    j = lab.act(job, "start")
    assert j["status"] == "failed"
    assert _check(j, "post", "post_version")["value"] == "could not be read"


def test_arista_mlag_pair_secondary_first(lab):
    a, dev_a, img = _setup(lab, "arista_eos", 1)
    b, dev_b, _ = _setup(lab, "arista_eos", 2)
    a.role, b.role = "primary", "secondary"
    a.peer, b.peer = b, a
    r = lab.c.put(f"/api/firmware/devices/{dev_a['id']}/settings",
                  json={"upgrade_credential_id": lab.up["id"], "peer_device_id": dev_b["id"],
                        "default_path": "mlag_pair"})
    assert r.status_code == 200, r.text
    job = lab.job(dev_a, img)
    assert job["path"] == "mlag_pair"
    j = lab.act(job, "precheck")
    assert j["status"] == "ready", [c for c in j["checks"]["pre"] if c["status"] == "fail"]
    j = lab.act(job, "start")
    assert j["status"] == "completed", _msgs(j)
    reloads = [d for d, c in lab.net.log if c == "reload now"]
    assert reloads == [b.name, a.name] and a.version == b.version == "4.32.2F"


def test_xr_install_replace_path_and_rollback_only_before_commit(lab):
    sim, dev, img = _setup(lab, "cisco_xr")
    job = lab.job(dev, img, path="install_replace")
    lab.act(job, "precheck")
    j = lab.act(job, "start")
    assert j["status"] == "completed" and not sim.uncommitted, _msgs(j)
    assert (sim.name, "install replace /harddisk:/asr9k-x64-7.11.2.iso noprompt") in lab.net.log
    assert not j["pending_commit"]


def test_os10_install_failure_stops_before_the_reload(lab):
    sim, dev, img = _setup(lab, "dell_os10")
    sim.fail.add("image_install")
    job = lab.job(dev, img)
    lab.act(job, "precheck")
    j = lab.act(job, "start")
    assert j["status"] == "failed" and sim.reloads == 0
    assert "image install failed" in _msgs(j)


def test_mikrotik_firmware_follows_and_rollback_is_by_hand(lab):
    sim, dev, img = _setup(lab, "mikrotik_routeros")
    job = lab.job(dev, img)
    lab.act(job, "precheck")
    j = lab.act(job, "start")
    assert j["status"] == "completed", _msgs(j)
    assert sim.reloads == 2 and sim.rb_firmware == "7.15.3"
    # a failed post-check: roll back needs the previous package uploaded by hand
    sim2, dev2, _ = _setup(lab, "mikrotik_routeros", 2)
    sim2.fail.add("stays_old")
    job2 = lab.job(dev2, img)
    lab.act(job2, "precheck")
    assert lab.act(job2, "start")["status"] == "failed"
    j2 = lab.act(job2, "rollback")
    assert j2["status"] == "needs_attention" and "/system package downgrade" in _msgs(j2)


def test_procurve_needs_scp_and_writes_the_other_slot(lab):
    sim, dev, img = _setup(lab, "aruba_osswitch")
    job = lab.job(dev, img)
    j = lab.act(job, "precheck")
    assert "secondary" in _check(j, "pre", "previous_image")["value"]
    lab.act(job, "start")
    assert sim.slots["secondary"][1] == "WC.16.11.0018" and sim.image == "secondary"
    assert sim.slots["primary"][1] == "WC.16.11.0012"  # kept for roll back


# --- parsers ---------------------------------------------------------------------------------

def test_vendor_upgrade_parsers():
    m = parse_mlag("state : Active\nnegotiation status : Connected\npeer-link status : Up\n"
                   "State : secondary\n")
    assert mlag_healthy(m) and m["role"] == "secondary"
    assert not mlag_healthy({**m, "peer_link": "Down"})
    assert flash_slots("Primary Image    :   26170212 03/13/23 WC.16.11.0012\n"
                       "Secondary Image  :   25000000 01/10/23 WC.16.10.0009\n") == {
        "primary": (26170212, "WC.16.11.0012"), "secondary": (25000000, "WC.16.10.0009")}
    parts = partitions("Partition               : 0:0 (/dev/usb/flash1) **Default boot**\n"
                       "Software Version        : ArubaOS 8.10.0.7 (Digitally Signed)\n"
                       "Partition               : 0:1 (/dev/usb/flash2)\n"
                       "Software Version        : ArubaOS 8.6.0.4 (Digitally Signed)\n")
    assert parts == {"0": {"version": "8.10.0.7", "default": True},
                     "1": {"version": "8.6.0.4", "default": False}}
    assert install_state("Image Upgrade State: idle\nState Detail: Completed: No error\n") == \
        "Completed: No error"
    assert vc_members("0 (FPC 0)  Prsnt  XN1 ex4400-48p 128 Master* N VC\n"
                      "1 (FPC 1)  NotPrsnt  XN2 ex4400-48p 128 Backup  N VC\n") == \
        {"0": "Prsnt", "1": "NotPrsnt"}
    assert file_size("  1  -rw-   123,456,789  Jan 01 2024 10:00:00   s.cc\n", "s.cc") == 123456789
    assert file_size("-rw-r--r--  1 up  up  4567 Jan  1 10:00 a.bin\n", "a.bin") == 4567
    assert file_size("", "a.bin") is None


@pytest.mark.parametrize("prompt, answer", [
    ("This install operation will reload the system, continue? [yes/no]:[yes] ", "yes"),  # IOS-XR
    ("Proceed to reboot the system? [confirm yes/no]:", "yes"),  # Dell OS10
    ("Reboot the system ? [yes,no] (no) ", "yes"),  # Junos
    ("Are you sure you want to replace old version? (Yes/No) [Yes]: ", "Yes"),  # EdgeOS
    ("Proceed with reboot? [confirm][y] ", "y"),  # EdgeOS
    ("Device will be rebooted, do you want to continue [y/n]? ", "y"),  # ArubaOS-Switch
    ("Do you want to save current configuration [y/n/^C]? ", "y"),  # ArubaOS-Switch
    ("Do you really want to restart the system(y/n): ", "y"),  # AOS 8
    ("System will reboot! Continue? [Y/N]: ", "y"),  # Huawei
    ("Are you sure you want to reboot the switch? (y/N) ", "y"),  # EXOS
    ("Reboot, yes? [y/N]: ", "y"),  # RouterOS
])
def test_vendor_prompts_are_answered(prompt, answer):
    from app.tools.firmware_upgrade.deviceio import PROMPT_ANSWERS
    found = next((a for q, a in PROMPT_ANSWERS if q.search(prompt)), None)
    assert found == answer


def test_copy_routes():
    from app.tools.firmware_upgrade.deviceio import SCP_PUSH, scp_remote_path
    assert {"aruba_osswitch", "huawei_vrp", "allied_awplus"} <= SCP_PUSH
    assert scp_remote_path("/os/secondary", "WC_16_11_0018.swi") == "/os/secondary"
    assert scp_remote_path("flash:/", "s.cc") == "flash:/s.cc"
    assert scp_remote_path("", "s.cc") == "s.cc"
    assert DRIVERS["arista_eos"].transfer_fs(SimpleUnit()) == "/mnt/flash"
    assert DRIVERS["juniper_junos"].transfer_fs(SimpleUnit()) == "/var/tmp"


def SimpleUnit():
    from app.tools.firmware_upgrade.drivers.base import Unit
    return Unit(device_id=1, name="x", address="10.0.0.1", platform="", position=0)
