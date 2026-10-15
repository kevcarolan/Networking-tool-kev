"""The public website (website/) builds, and its links and images point at real files."""

import importlib.util
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[2]
spec = importlib.util.spec_from_file_location("site_build", ROOT / "website" / "build.py")
site_build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(site_build)


def test_builds_with_working_links(tmp_path, monkeypatch):
    monkeypatch.setattr(site_build, "OUT", tmp_path / "public")
    pages = site_build.build()
    assert {"index.html", "pricing.html", "trial.html", "privacy.html"} <= set(pages)
    for page in pages:
        text = (tmp_path / "public" / page).read_text()
        assert "{{" not in text
        for ref in re.findall(r'(?:href|src|srcset)="([^"#:?]+)"', text):
            assert (tmp_path / "public" / ref).exists(), f"{page} links to missing {ref}"
    assert (tmp_path / "public" / ".htaccess").exists()


def test_website_stays_out_of_the_install_bundle():
    # build-bundle.sh packs the app with `git archive`, which honours export-ignore.
    out = subprocess.run(["git", "-C", str(ROOT), "check-attr", "export-ignore", "website/build.py"],
                         capture_output=True, text=True, check=True).stdout
    assert out.strip().endswith("set")
