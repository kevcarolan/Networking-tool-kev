#!/usr/bin/env bash
# Installs or upgrades NetOps Tools on an Ubuntu server that can reach the internet.
#
#     sudo git clone <repository> /usr/local/src/netops    # as root: see below
#     cd /usr/local/src/netops && sudo deploy/install-online.sh
#
# To upgrade later:  sudo git pull && sudo deploy/install-online.sh
#
# The copy of the code must belong to root and not be writable by anyone else (checked):
# the installer runs it as root.
#
# It does the same as the air-gapped install (docs/install-airgap.md), on the server
# itself: it installs the Ubuntu packages from Ubuntu's repositories, builds an install
# bundle from this copy of the code (Python packages from PyPI, checked for known
# vulnerabilities), then runs the bundle's install.sh. So both kinds of site install,
# upgrade and roll back in exactly the same way. The bundle is kept in dist/: copy it
# to an air-gapped server of the same Ubuntu release to install the same version there.
#
# Needs outbound HTTPS to the Ubuntu archive and pypi.org / files.pythonhosted.org while
# it runs (the hardened firewall blocks this: see docs/install-online.md).
#
# Options:
#   --skip-os-packages   don't install Ubuntu packages (already installed)
#   ALLOW_VULNS=1        install even if pip-audit reports known vulnerabilities
#   FORCE=1              upgrade even while a live device upgrade is running (don't)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SKIP_OS=""
for arg in "$@"; do
  case "$arg" in
    --skip-os-packages) SKIP_OS=1 ;;
    -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "run with sudo"
. /etc/os-release
[[ "${ID:-}" == "ubuntu" ]] || die "this installer is for Ubuntu; this is ${PRETTY_NAME:-unknown}"
# Everything here runs as root, so the copy of the code must be root's own: anyone who
# could change it (or a folder above it) could otherwise run commands as root.
dir="$REPO_ROOT"
while :; do
  [[ "$(stat -c %u "$dir")" == 0 ]] || die "$dir isn't owned by root: clone the code as root (see docs/install-online.md)"
  [[ "$(stat -c %A "$dir")" != ?????w???? && "$(stat -c %A "$dir")" != ????????w? ]] || \
    [[ -k "$dir" && "$dir" != "$REPO_ROOT" ]] || \
    die "$dir can be changed by other users: clone the code as root into a root-only folder"
  [[ "$dir" == / ]] && break
  dir="$(dirname "$dir")"
done
other="$(find "$REPO_ROOT" \( ! -user root -o -perm -0002 -o -perm -0020 \) -print -quit)"
[[ -z "$other" ]] || die "$other can be changed by other users: clone the code as root"
git -C "$REPO_ROOT" rev-parse --git-dir >/dev/null 2>&1 || \
  die "run it from a git clone of the repository (the install is built from the checked-out commit)"
if [[ -n "$(git -C "$REPO_ROOT" status --porcelain)" ]]; then
  echo "WARNING: this copy has uncommitted changes; they are NOT installed (the install uses the last commit)."
fi

if [[ -z "$SKIP_OS" ]]; then
  say "Ubuntu packages (from Ubuntu's repositories)"
  mapfile -t PKGS < <(sed 's/#.*//' "$REPO_ROOT/deploy/os-packages.txt" | tr -s ' ' '\n' | grep .)
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -q --no-install-recommends "${PKGS[@]}"
fi

say "Building the install bundle"
OUT="$(mktemp -d)"   # root's own folder: nothing else can swap the bundle
WORK="$(mktemp -d)"
trap 'rm -rf "$OUT" "$WORK"' EXIT
SKIP_DEBS=1 DIST_DIR="$OUT" "$REPO_ROOT/deploy/airgap/build-bundle.sh"
BUNDLE_TGZ="$(find "$OUT" -maxdepth 1 -name 'netops-bundle-*.tar.gz' -print -quit)"
[[ -n "$BUNDLE_TGZ" ]] || die "the bundle wasn't built (see above)"

say "Installing"
tar -xzf "$BUNDLE_TGZ" -C "$WORK"
"$WORK"/netops-bundle-*/install.sh --skip-os-packages
install -d -m 0755 "$REPO_ROOT/dist"
cp "$OUT"/netops-bundle-* "$REPO_ROOT/dist/"
BUNDLE_TGZ="$REPO_ROOT/dist/$(basename "$BUNDLE_TGZ")"

echo
echo "The bundle is kept as $BUNDLE_TGZ (with its .sha256 and MANIFEST),"
echo "for your records or to install the same version on an air-gapped server."
