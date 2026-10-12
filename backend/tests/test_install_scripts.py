"""The install scripts: valid shell, and the Ubuntu package list both installers read."""

import subprocess
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
SCRIPTS = sorted(DEPLOY.glob("*.sh")) + sorted((DEPLOY / "airgap").glob("*.sh"))


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_scripts_are_valid_shell(script):
    assert subprocess.run(["bash", "-n", str(script)], capture_output=True).returncode == 0


def test_both_installers_read_the_same_package_list():
    cmd = "mapfile -t P < <(sed 's/#.*//' deploy/os-packages.txt | tr -s ' ' '\\n' | grep .); echo ${P[*]}"
    packages = subprocess.run(["bash", "-c", cmd], cwd=DEPLOY.parent, capture_output=True,
                              text=True, check=True).stdout.split()
    assert {"python3-venv", "git", "sqlite3", "nginx", "openssl"} <= set(packages)
    for script in ("install-online.sh", "airgap/build-bundle.sh"):
        assert "deploy/os-packages.txt" in (DEPLOY / script).read_text()


def test_the_wall_display_has_its_own_port_only():
    main = (DEPLOY / "nginx-netops.conf").read_text()
    assert "location ^~ /display/ { return 404; }" in main
    assert "location ^~ /api/display/ { return 404; }" in main
    wall = (DEPLOY / "nginx-netops-display.conf").read_text()
    assert "listen 8443 ssl;" in wall and "location / { return 404; }" in wall
    proxied = [line.split()[2] for line in wall.splitlines()
               if line.strip().startswith("location") and "{" in line and "return" not in line]
    assert proxied == ["/display/", "/api/display/data"]
    assert "tcp dport 8443 ip saddr $DISPLAY_NETS accept" in (
        DEPLOY / "hardening" / "nftables.conf").read_text()
