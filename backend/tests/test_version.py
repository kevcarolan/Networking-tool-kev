"""The product version (VERSION, app/version.py, docs/releasing.md): read from one file,
shown only after sign-in, in the report and the CLI; the bundle and installer use it."""

import re
import subprocess
from pathlib import Path

from app import version
from app.cli import main as cli

ROOT = Path(__file__).parents[2]


def test_one_version_file(tmp_path):
    text = (ROOT / "VERSION").read_text().strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+", text) and version.VERSION == text
    assert version.parse("2.10.3") == (2, 10, 3) and version.parse("2.1.0-dev.20261015.abc") == (2, 1, 0)
    assert version.parse("20261014-a5fa5a2") is None
    (tmp_path / "VERSION").write_text("two point one")
    assert version.read(tmp_path / "VERSION") == "dev" and version.read(tmp_path / "missing") == "dev"
    changelog = (ROOT / "CHANGELOG.md").read_text()
    assert f"## {text} (not released yet)" in changelog or f"## {text} (" in changelog


def test_shown_after_sign_in_but_not_before(client, admin):
    assert admin.get("/api/auth/me").json()["version"] == version.VERSION
    assert "version" not in admin.get("/api/health").json()
    anon = client.__class__(client.app)
    assert version.VERSION not in anon.get("/").text  # the sign-in page
    rep = admin.get("/api/reports", params={"days": 7}).json()
    assert ("Version", version.VERSION) in [tuple(r) for r in rep["sections"][0]["rows"]]


def test_cli_prints_it(capsys):
    assert cli(["version"]) == 0
    assert capsys.readouterr().out.strip() == version.VERSION


def test_the_installer_refuses_an_older_version():
    script = (ROOT / "deploy" / "airgap" / "install.sh").read_text()
    fn = next(line for line in script.splitlines() if line.startswith("semver()"))
    check = fn + '''
check() { new_v="$(semver "$1" || true)"; old_v="$(semver "$2" || true)"
  if [[ -n "$old_v" && ( -z "$new_v" || "$new_v" < "$old_v" ) ]]; then echo refused; else echo ok; fi; }
for pair in "2.1.0 2.0.0" "2.0.0 2.1.0" "2.10.0 2.9.3" "2.1.0-dev.1.abc 2.1.0" "2.1.0 20261014-a5fa5a2" "20261020-abc 2.1.0"; do
  check $pair; done'''
    out = subprocess.run(["bash", "-c", check], capture_output=True, text=True, check=True).stdout.split()
    assert out == ["ok", "refused", "ok", "ok", "ok", "refused"]
    assert "ALLOW_DOWNGRADE" in script and "Upgrading from $RUNNING to $VERSION" in script
    bundle = (ROOT / "deploy" / "airgap" / "build-bundle.sh").read_text()
    assert "< VERSION" in bundle and '-dev.$(date -u +%Y%m%d).$COMMIT' in bundle
