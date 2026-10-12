#!/bin/sh
# Consistent backup of the NetOps database and config archive to
# /var/backups/netops/netops-<label>-<time>.tar.gz, keeping KEEP_DAYS days.
#
# Deliberately NOT included:
#   - /etc/netops/credential.key: keep it in your offline key store, so a stolen
#     backup can't be used to decrypt the device passwords
#   - data/firmware/: images can be downloaded from the vendor again
#   - data/syslog/: the devices' log messages (large, and kept only for a set time anyway)
# Copy /var/backups/netops off the server with your normal backup system.
#
# Runs as root (to write /var/backups/netops), but the database and the config archive
# belong to the service account: they are read as that account (sqlite3 and git never run
# as root on files it controls), and root only packs the result.
set -eu
DATA="${NETOPS_DATA_DIR:-/var/lib/netops}"
DEST=/var/backups/netops
KEEP_DAYS="${KEEP_DAYS:-14}"
LABEL="${1:-manual}"
STAMP="$(date +%Y%m%d-%H%M%S)"
umask 077
mkdir -p "$DEST"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

as_service() {  # run as the service account (when root and the account exists)
  if [ "$(id -u)" = 0 ] && id netops >/dev/null 2>&1; then
    runuser -u netops -- "$@"
  else
    "$@"
  fi
}

[ -f "$DATA/app.db" ] || { echo "No database at $DATA/app.db yet - nothing to back up."; exit 0; }
chmod 0711 "$TMP"  # the service account may pass through to data/, not list or read the rest
mkdir "$TMP/data"
if [ "$(id -u)" = 0 ] && id netops >/dev/null 2>&1; then chown netops "$TMP/data"; fi
chmod 0700 "$TMP/data"
as_service sqlite3 "$DATA/app.db" ".backup '$TMP/data/app.db'"
if [ -d "$DATA/configs/.git" ] && as_service git -C "$DATA/configs" rev-parse --verify -q HEAD >/dev/null; then
  as_service git -C "$DATA/configs" bundle create -q "$TMP/data/configs.gitbundle" --all
fi
cp /etc/netops/netops.env "$TMP/netops.env" 2>/dev/null || true
# (tar stores links as links: a link planted in data/ can't pull another file in)
tar -C "$TMP" -czf "$DEST/netops-$LABEL-$STAMP.tar.gz" --transform 's,^\./data/,./,' .
find "$DEST" -name 'netops-*.tar.gz' -mtime +"$KEEP_DAYS" -delete
# Record when the last backup succeeded (written as the service account, in its folder).
date -u +%FT%TZ | as_service sh -c "cat > '$DATA/last-backup'" 2>/dev/null || true
echo "Backup written: $DEST/netops-$LABEL-$STAMP.tar.gz"
