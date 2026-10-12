#!/usr/bin/env bash
# Installs the certificate saved by the setup screen / Settings page for nginx.
# Run as root by netops-tls.service whenever /var/lib/netops/tls/netops.crt changes
# (netops-tls.path). The web app can only *propose* a certificate: this script checks
# it, copies it to /etc/netops/tls/ (root only), tests nginx and reloads it. On any
# problem the certificate in use stays as it was.
#
# $SRC belongs to the unprivileged service account, which could swap files or links in it
# at any moment. So this script never writes there, reads each file once without
# following links (into a root-only folder) and checks only those copies. Its status line
# goes to a root-owned folder ($STATUS_DIR) that the app only reads.
set -euo pipefail
umask 077

SRC="${NETOPS_TLS_SRC:-/var/lib/netops/tls}"   # overridable for the tests only
DST="${NETOPS_TLS_DST:-/etc/netops/tls}"
STATUS_DIR="${NETOPS_TLS_STATUS_DIR:-/var/lib/netops-tls}"
ENV_FILE="${NETOPS_ENV_FILE:-/etc/netops/netops.env}"
MAX=200000

status() {  # one line the GUI shows
  install -d -m 0755 "$STATUS_DIR"
  local tmp
  tmp="$(mktemp "$STATUS_DIR/.apply-status.XXXXXX")"
  printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" > "$tmp"
  chmod 0644 "$tmp"
  mv -f "$tmp" "$STATUS_DIR/apply-status"
  logger -t netops-tls "$1"
  echo "$1"
}

fail() { status "refused: $1"; exit 1; }

[[ -d "$SRC" && ! -L "$SRC" ]] || fail "$SRC is not a folder"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
for f in netops.crt netops.key; do
  # One read, never following a link and never blocking on a pipe; at most MAX+1 bytes.
  dd if="$SRC/$f" of="$work/$f" iflag=nofollow,nonblock bs=$((MAX + 1)) count=1 \
     status=none 2>/dev/null || fail "$f is missing or not a plain file"
  size="$(stat -c %s "$work/$f")"
  (( size > 0 )) || fail "$f is empty"
  (( size <= MAX )) || fail "$f is too large"
done

openssl x509 -in "$work/netops.crt" -noout 2>/dev/null || fail "not a certificate"
openssl x509 -in "$work/netops.crt" -noout -checkend 0 >/dev/null || fail "the certificate has expired"
cert_pub="$(openssl x509 -in "$work/netops.crt" -noout -pubkey)"
key_pub="$(openssl pkey -in "$work/netops.key" -pubout 2>/dev/null)" || fail "the key can't be read"
[[ "$cert_pub" == "$key_pub" ]] || fail "the certificate doesn't belong to the key"

install -d -m 0700 "$DST"
for f in netops.crt netops.key; do
  [[ -f "$DST/$f" ]] && cp -p "$DST/$f" "$DST/$f.prev"
  install -m 0600 "$work/$f" "$DST/$f"   # root:root when run by the service
done

if ! nginx -t >/dev/null 2>&1; then
  for f in netops.crt netops.key; do
    [[ -f "$DST/$f.prev" ]] && mv -f "$DST/$f.prev" "$DST/$f"
  done
  fail "nginx rejected the certificate; the previous one is still in use"
fi
systemctl reload nginx
# Syslog over TLS uses the same certificate, read when the receiver starts.
if grep -Eq '^[[:space:]]*NETOPS_SYSLOG_TLS_PORT=[1-9]' "$ENV_FILE" 2>/dev/null; then
  systemctl try-restart netops-syslog.service || true
fi
subject="$(openssl x509 -in "$DST/netops.crt" -noout -subject | sed 's/^subject= *//')"
until="$(openssl x509 -in "$DST/netops.crt" -noout -enddate | sed 's/^notAfter=//')"
status "applied: $subject, valid until $until"
