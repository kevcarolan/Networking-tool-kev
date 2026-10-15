#!/usr/bin/env python3
"""Publish releases from CHANGELOG.md (run by .github/workflows/release.yml on every push
to main; see docs/releasing.md).

Every version whose changelog heading has a date ("## 2.1.0 (2026-10-15)") and has no tag
yet gets one: the tag v2.1.0 on the commit that put that date in the changelog (the
"Release 2.1.0" pull request), and a GitHub release titled 2.1.0 with that section of the
changelog as its notes. The commit's VERSION file must say the same version, or nothing is
made. A heading "(not released yet)" is skipped. Run again, it does nothing new.

    python3 deploy/release.py --dry-run     # what it would do, nothing changed

The workflow then builds each new release's install bundle on Ubuntu and attaches it to the
release; the owner's PC copies it into OneDrive (deploy/windows/Sync-NetCairnRelease.ps1).
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEADING = re.compile(r"^## (\d+\.\d+\.\d+) \((\d{4}-\d{2}-\d{2})\)\s*$")


def dated_versions(changelog: str) -> list[tuple[str, str, str, str]]:
    """(version, date, heading line, notes) for every released (dated) section."""
    out, current, lines = [], None, []
    for line in changelog.splitlines() + ["## end"]:
        if line.startswith("## "):
            if current:
                out.append((*current, "\n".join(lines).strip()))
            m = HEADING.match(line)
            current, lines = ((m.group(1), m.group(2), line.rstrip()) if m else None), []
        elif current:
            lines.append(line)
    return out


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def has_tag(tag: str) -> bool:
    return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "-q", "--verify", f"refs/tags/{tag}"],
                          capture_output=True).returncode == 0


def release_commit(heading: str) -> str:
    """The first commit that put this exact heading (with its date) in the changelog."""
    found = git("log", "--format=%H", "--reverse", "-S", heading, "--", "CHANGELOG.md").split()
    return found[0] if found else ""


def plan() -> list[dict]:
    todo = []
    for version, date, heading, notes in dated_versions((ROOT / "CHANGELOG.md").read_text(encoding="utf-8")):
        tag = f"v{version}"
        if has_tag(tag):
            continue
        sha = release_commit(heading)
        if not sha:
            print(f"{tag}: no commit adds '{heading}', skipped", file=sys.stderr)
            continue
        at = git("show", f"{sha}:VERSION").strip()
        if at != version:
            print(f"{tag}: commit {sha[:7]} has VERSION {at}, not {version}: skipped", file=sys.stderr)
            continue
        todo.append({"tag": tag, "version": version, "date": date, "sha": sha, "notes": notes})
    return todo


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Tag and publish the releases dated in CHANGELOG.md")
    p.add_argument("--dry-run", action="store_true", help="only say what would be made")
    args = p.parse_args(argv)
    todo = plan()
    if not todo:
        print("Nothing to release: every dated version in CHANGELOG.md has its tag.")
    for r in todo:
        print(f"{r['tag']} on {r['sha'][:7]} ({r['date']})")
        if args.dry_run:
            continue
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as fh:
            fh.write(r["notes"] + "\n\nInstall or upgrade: docs/install-airgap.md. "
                     "The install bundle and its SHA-256 come from your supplier.\n")
        subprocess.run(["gh", "release", "create", r["tag"], "--target", r["sha"],
                        "--title", r["version"], "--notes-file", fh.name], check=True, cwd=ROOT)
    write_output([] if args.dry_run else [r["tag"] for r in todo])
    return 0


def write_output(tags: list[str]) -> None:
    """Tell the workflow which releases were made, so it builds their bundles."""
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
            fh.write(f"tags={json.dumps(tags)}\n")


if __name__ == "__main__":
    raise SystemExit(main())
