# Versions and releases

## The version number

**MAJOR.MINOR.PATCH**, e.g. 2.1.0. It lives in one place, the `VERSION` file at the top of
the repository, and everything else reads it: the top bar after signing in, the report,
`netops-cli version`, the bundle's name and the installer.

| Change | Example | When |
|---|---|---|
| **Patch** | 2.1.0 → 2.1.1 | Fixes only. Safe to install at any time |
| **Minor** | 2.1.1 → 2.2.0 | New features (one or several merged pull requests) |
| **Major** | 2.x → 3.0.0 | Something needs a manual step on upgrade: a new Ubuntu release, a `netops.env` change, a new licence format. The changelog says what to do |

The version is **not** shown on pages anyone can reach without signing in (the sign-in
page, `/api/health`): an exact version tells an attacker which known problems to try.

## Day to day

* Branches and pull requests keep descriptive names (`snmp-only`, `meraki-api`), never a
  version number: a branch doesn't know which release it will land in.
* `VERSION` holds the **next** version to be released, and `CHANGELOG.md` has a section for
  it marked "(not released yet)". Every pull request that changes what people see adds a
  line there, in plain words.
* A bundle built from a commit that isn't a release is named
  `netops-bundle-2.1.0-dev.<date>.<commit>.tar.gz`: a build on the way to 2.1.0, fine for
  the lab, not for a customer.

## Making a release

A **merge** puts a change into `main`; a **release** marks one point of `main` as a version
(a tag, `v2.1.0`, and a GitHub release with its notes) for customers to install. Not every
merge is a release: you choose when to ship.

1. A pull request "Release 2.1.0": the changelog heading gets the date instead of "(not
   released yet)". Nothing else.
2. Merge it. That's all: the **Release** workflow (`.github/workflows/release.yml`, which
   runs `deploy/release.py`) sees the dated heading with no tag yet, tags the commit that
   dated it `v2.1.0` and makes the GitHub release with that changelog section as its
   notes, within a minute or two. Check it under **Releases** on GitHub. (`python3
   deploy/release.py --dry-run` shows what it would do.)
3. Build the bundle from the tag (`git checkout v2.1.0`, then `deploy/airgap/build-bundle.sh`):
   it is named `netops-bundle-2.1.0.tar.gz`.
4. Straight after (or with the next feature), a pull request sets `VERSION` to the next version (usually the next
   minor, 2.2.0) with a new "(not released yet)" section in the changelog.

A fix for an installed version: branch from its tag, fix, set `VERSION` to the patch
(2.1.1), and release it the same way.

## Upgrading a site

Install the new bundle as in the install guide. The installer says "Upgrading from 2.0.0 to
2.1.0", backs up and switches, and puts the old release back if the new one doesn't start.
It refuses an **older** bundle than the one installed: the older code wouldn't know the
newer database (`ALLOW_DOWNGRADE=1` only with a database backup taken on that older
version). `netops-cli version` on the server, or the top bar, shows what is installed.
