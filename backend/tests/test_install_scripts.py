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
