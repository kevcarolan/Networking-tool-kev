"""Lab capture: only read-only commands, addresses replaced consistently, what the tools
read, and the file format."""

from datetime import datetime, timezone

import pytest

from app import cli
from app.core.platforms import PLATFORMS
from app.tools.firmware_upgrade import capture
from app.tools.firmware_upgrade import checks as ck
from tests import firmware_samples as s
from tests.test_upgrade_jobs import IOS_OUT


@pytest.mark.parametrize("platform", sorted(PLATFORMS))
def test_every_platform_captures_only_read_only_commands(platform):
    commands = capture.capture_commands(platform)
    assert commands, platform
    assert all(capture.is_read_only(c) for c in commands.values())
    # never the full configuration (it holds secrets): that is the backup's job
    assert not set(PLATFORMS[platform].backup_commands) & set(commands.values())
    assert "show running-config" not in commands.values()


@pytest.mark.parametrize("command", [
    "configure terminal", "conf t", "copy scp: flash:", "delete flash:old.bin", "reload",
    "install add file flash:x.bin activate commit", "request system software install",
    "write memory", "clear mac address-table", "set system boot", "boot system flash:x",
    "execute reboot", "/system reboot", "/ip arp remove 0", "show run | redirect flash:x",
    "show tech | tee flash:t.txt", "show version > flash:v.txt"])
def test_changes_are_never_read_only(command):
    assert not capture.is_read_only(command)


def test_the_same_address_always_gets_the_same_stand_in():
    m = capture.Masker()
    out = m("10.20.34.1 0011.2233.4455\n10.20.34.9 00:11:22:33:44:55\n255.255.255.0 0.0.0.0 "
            "127.0.0.1 224.0.0.5 10.99.1.1")
    lines = out.splitlines()
    assert lines[0].split()[1] == "0200.0000.0001" and lines[1].split()[1] == "02:00:00:00:00:01"
    a, b = lines[0].split()[0], lines[1].split()[0]
    assert a.rsplit(".", 1)[0] == b.rsplit(".", 1)[0] and a.endswith(".1") and b.endswith(".9")
    assert "10.20.34" not in out and "255.255.255.0 0.0.0.0 127.0.0.1 224.0.0.5" in out
    assert "10.99.1.1" not in out


class _Target:
    name = "core-sw1"


def _collector(outputs):
    calls = []

    def run(target, commands):
        calls.extend(commands)
        return [outputs.get(c, "% Invalid input detected at '^' marker.") for c in commands]
    return run, calls


def test_capture_file_and_what_the_tools_read():
    run, calls = _collector(IOS_OUT)
    text, lines = capture.capture(_Target(), "cisco_ios", run, "upgrade", ck.Thresholds(),
                                  now=datetime(2026, 10, 12, 15, 30, tzinfo=timezone.utc))
    assert len(calls) == len(set(calls))  # each command once
    assert any("version 17.09.04a" in line for line in lines)
    assert any(line.startswith("Check cpu: ") for line in lines)
    assert "# platform: cisco_ios (Cisco IOS / IOS-XE)" in text
    assert "captured: 2026-10-12 15:30 UTC, with the upgrade account" in text
    assert "10.20.34.1" not in text  # from 'show ip interface brief'
    assert set(capture.parse_file(text)) == set(calls)

    raw, _ = capture.capture(_Target(), "cisco_ios", run, "backup", ck.Thresholds(), raw=True)
    assert "10.20.34.1" in raw and "as on the device (--raw)" in raw
    assert capture.parse_file(raw)["show version"].strip() == s.IOS_XE_VERSION.strip()


def test_cli_capture(app, admin, device, settings, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
    run, calls = _collector(IOS_OUT)
    monkeypatch.setattr("app.core.ssh.run_commands", run)
    out = tmp_path / "cap.txt"
    assert cli.main(["capture", "core-sw1", "--out", str(out)]) == 0
    printed = capsys.readouterr()
    assert "No upgrade account set" in printed.err and "with the backup account" in out.read_text()
    assert f"Saved to {out}" in printed.out and oct(out.stat().st_mode)[-3:] == "600"
    assert cli.main(["capture", "nope"]) == 1
