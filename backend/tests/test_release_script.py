"""deploy/release.py: which versions get a tag and a GitHub release, and on which commit."""

import importlib.util
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[2]
spec = importlib.util.spec_from_file_location("release", ROOT / "deploy" / "release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)

CHANGELOG = """# What's new

## 2.2.0 (not released yet)

- Editions

## 2.1.0 (2026-10-15)

**New**
- SNMP-only devices

## 2.0.0 (2026-10-14)

- The first release
"""


def test_only_dated_versions_with_their_notes():
    found = release.dated_versions(CHANGELOG)
    assert [(v, d) for v, d, _, _ in found] == [("2.1.0", "2026-10-15"), ("2.0.0", "2026-10-14")]
    assert found[0][2] == "## 2.1.0 (2026-10-15)" and found[0][3] == "**New**\n- SNMP-only devices"


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_tags_the_commit_that_dated_the_version(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")

    def commit(version, changelog, msg):
        (repo / "VERSION").write_text(version + "\n")
        (repo / "CHANGELOG.md").write_text(changelog)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", msg)
        return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()

    commit("2.1.0", "## 2.1.0 (not released yet)\n- a\n", "work")
    released = commit("2.1.0", "## 2.1.0 (2026-10-15)\n- a\n", "Release 2.1.0")
    commit("2.2.0", "## 2.2.0 (not released yet)\n\n## 2.1.0 (2026-10-15)\n- a\n", "next")
    monkeypatch.setattr(release, "ROOT", repo)
    todo = release.plan()
    assert [(r["tag"], r["sha"]) for r in todo] == [("v2.1.0", released)] and todo[0]["notes"] == "- a"
    _git(repo, "tag", "v2.1.0", released)
    assert release.plan() == []  # already released: nothing to do
    # a version dated in a commit whose VERSION file says something else is refused
    commit("2.1.0", "## 2.2.0 (2026-11-01)\n\n## 2.1.0 (2026-10-15)\n- a\n", "dated too early")
    assert release.plan() == []
