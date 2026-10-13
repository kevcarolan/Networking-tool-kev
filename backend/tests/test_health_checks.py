"""Health checks and the before/after comparison for the platforms other than Cisco IOS
(tools/firmware_upgrade/health.py), on the sample output in app/demo/health_samples.py."""

import pytest

from app.demo.health_samples import FAULTS
from app.tools.firmware_upgrade import capture, health
from app.tools.firmware_upgrade import checks as c
from tests.fake_network import SimDevice
from tests.test_upgrade_engine import _check, _msgs
from tests.test_upgrade_vendors import _setup, lab  # noqa: F401 - the lab fixture

PLATFORMS = sorted(health.PROFILES)


def _outputs(platform: str, faults: dict | None = None) -> dict[str, str]:
    """key -> output, as a job collects it, from the simulator's healthy answers."""
    sim = SimDevice("dev1", platform, "1.0", "running")
    sim.outputs.update(faults or {})
    return {k: sim.output(cmd) for k, cmd in c.commands_for(platform).items()
            if k.startswith(("h:", "snap:"))}


def _by_id(results):
    return {r.check_id: r for r in results}


@pytest.mark.parametrize("platform", PLATFORMS)
def test_every_command_is_read_only_and_answered_by_the_simulator(platform):
    sim = SimDevice("dev1", platform, "1.0", "running")
    for cmd in health.PROFILES[platform].commands().values():
        assert capture.is_read_only(cmd), cmd
        assert not c._unsupported(sim.output(cmd)), cmd


@pytest.mark.parametrize("platform", PLATFORMS)
def test_healthy_device_passes_every_check(platform):
    results = _by_id(c.health_checks(platform, _outputs(platform), c.Thresholds()))
    prof = health.PROFILES[platform]
    assert "platform_checks" not in results
    expected = {"env": "environment", "alarms": "alarms", "modules": "modules", "cpu": "cpu",
                "mem": "memory"}
    for name, check_id in expected.items():
        if name in prof.checks:
            assert results[check_id].status == c.PASS, (check_id, results[check_id])
    if "reload" in prof.checks:
        assert results["reload_cause"].status == c.PASS


@pytest.mark.parametrize("platform", PLATFORMS)
def test_snapshot_compares_the_same_before_and_after(platform):
    snap = c.snapshot(platform, _outputs(platform))
    prof = health.PROFILES[platform]
    assert any(s == "up" for s in snap["interfaces"].values())
    assert snap["lldp"]
    if "lag" in prof.checks:
        assert all(snap["etherchannel"].values())
    results = c.compare_snapshots(snap, snap, "1.0")
    assert [r for r in results if r.status != c.PASS] == []
    ids = {r.check_id for r in results}
    assert {"post_interfaces", "post_lldp"} <= ids


def test_readers():
    assert health.idle_cpu("CPU states  :   3.50% user,   1.50% kernel,   95.00% idle") == 5
    assert health.idle_cpu("      Idle                      92 percent") == 8
    assert health.idle_cpu("user 2.3%, system 4.1%, idle 93.6%") == 6
    assert health.diff_lines("") == 0
    assert health.diff_lines("--- a\n+++ b\n+ interface Et1\n-  shutdown\n") == 2
    assert health.env_faults("Power Supply 2 ... Faulted") and not health.env_faults(
        "0 / 2 Fans in Failure State")
    assert health.alarm_rows("Severity: major\nName: EQM_PSU_FAILED")["serious"]
    assert health.junos_terse("xe-0/0/5   down  down\nxe-0/0/5.0  up up") == {
        "xe-0/0/5": "admin-down"}


@pytest.mark.parametrize("platform, command, check_id", [
    ("arista_eos", "show system environment all", "environment"),
    ("cisco_nxos", "show module", "modules"),
    ("juniper_junos", "show chassis alarms", "alarms"),
    ("juniper_junos", "show chassis environment", "environment"),
])
def test_faults_block(platform, command, check_id):
    out = _outputs(platform, {command: FAULTS[platform][command]})
    r = _by_id(c.health_checks(platform, out, c.Thresholds()))
    assert r[check_id].blocking, r[check_id]
    assert r[check_id].detail


def test_warnings_and_reload_cause():
    r = _by_id(c.health_checks("cisco_nxos", _outputs("cisco_nxos", {
        "show system resources": FAULTS["cisco_nxos"]["show system resources"]}), c.Thresholds()))
    assert r["cpu"].status == c.FAIL and not r["cpu"].blocking and r["cpu"].value == "96%"
    r = _by_id(c.health_checks("arista_eos", _outputs("arista_eos", {
        "show reload cause": FAULTS["arista_eos"]["show reload cause"]}), c.Thresholds()))
    assert r["reload_cause"].status == c.FAIL and not r["reload_cause"].blocking
    assert "Power Loss" in r["reload_cause"].value


def test_unsupported_commands_are_skipped_not_failed():
    out = {k: "% Invalid input detected at '^' marker." for k in _outputs("arista_eos")}
    r = _by_id(c.health_checks("arista_eos", out, c.Thresholds()))
    assert r["environment"].status == c.SKIP and not r["environment"].blocking
    assert r["cpu"].status == c.SKIP and "reload_cause" not in r


def test_before_and_after_finds_what_went_missing():
    pre = c.snapshot("juniper_junos", _outputs("juniper_junos"))
    post = c.snapshot("juniper_junos", _outputs("juniper_junos", {
        "show lacp interfaces": FAULTS["juniper_junos"]["show lacp interfaces"],
        "show lldp neighbors": "Local Interface    Parent Interface    Chassis Id   Port info  System Name\n",
        "show virtual-chassis": ""}))
    r = _by_id(c.compare_snapshots(pre, post, "1.0"))
    assert r["post_etherchannel"].blocking and "ae0: xe-0/0/2" in r["post_etherchannel"].detail
    assert r["post_lldp"].blocking and "xe-0/0/3 > dc1-leaf2" in r["post_lldp"].detail
    assert r["post_modules"].blocking and "0: missing" in r["post_modules"].detail


# --- whole jobs on the simulator ----------------------------------------------------------

def test_arista_unsaved_config_and_a_power_fault_block_the_job(lab):  # noqa: F811
    sim, dev, img = _setup(lab, "arista_eos")
    sim.outputs.update({k: FAULTS["arista_eos"][k] for k in
                        ("show system environment all", "show running-config diffs")})
    j = lab.act(lab.job(dev, img), "precheck")
    assert j["status"] == "blocked"
    assert _check(j, "pre", "environment")["status"] == "fail"
    assert _check(j, "pre", "unsaved_config")["value"] == "2 changed line(s)"


def test_arista_lag_member_lost_after_the_reload_fails_the_post_check(lab):  # noqa: F811
    sim, dev, img = _setup(lab, "arista_eos")
    sim.after_reload["show port-channel summary"] = FAULTS["arista_eos"]["show port-channel summary"]
    job = lab.job(dev, img)
    assert lab.act(job, "precheck")["status"] == "ready"
    j = lab.act(job, "start")
    assert j["status"] == "failed", _msgs(j)
    lag = _check(j, "post", "post_etherchannel")
    assert lag["status"] == "fail" and "Po49: Et50/1" in lag["detail"]
    assert _check(j, "post", "post_version")["status"] == "pass"


@pytest.mark.parametrize("platform", ["arista_eos", "juniper_junos", "dell_os10", "huawei_vrp"])
def test_full_upgrade_runs_every_check_before_and_after(lab, platform):  # noqa: F811
    sim, dev, img = _setup(lab, platform)
    job = lab.job(dev, img)
    j = lab.act(job, "precheck")
    assert j["status"] == "ready"
    pre = {x["check_id"] for x in j["checks"]["pre"]}
    assert {"environment", "cpu", "memory"} <= pre and "platform_checks" not in pre
    j = lab.act(job, "start")
    assert j["status"] == "completed", _msgs(j)
    for check_id in ("post_interfaces", "post_lldp", "environment"):
        assert _check(j, "post", check_id)["status"] == "pass", check_id


def test_junos_and_huawei_errors_count_as_not_supported():
    assert c._unsupported("error: syntax error, expecting <command>: virtual-chassis")
    assert c._unsupported("Error: Unrecognized command found at '^' position.")
