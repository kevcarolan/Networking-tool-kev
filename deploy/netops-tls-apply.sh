#!/usr/bin/env bash
# Installs the certificate saved by the setup screen / Settings page for nginx.
# Run as root by netops-tls.service whenever /var/lib/netops/tls/netops.crt changes
# (netops-tls.path). The web app can only *propose* a certificate: this script checks
# it, copies it to /etc/netops/tls/ (root only), tests nginx and reloads it. On any
# problem the certificate in use stays as it was.
set -euo pipefail

SRC="${NETOPS_TLS_SRC:-/var/lib/netops/tls}"   # overridable for the tests only
DST="${NETOPS_TLS_DST:-/etc/netops/tls}"
STATUS="$SRC/apply-status"

status() {  # one line the GUI shows; written via rename so a planted symlink is replaced, not followed
  local tmp
  tmp="$(mktemp "$SRC/.apply-status.XXXXXX")"
  printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" > "$tmp"
  chmod 0644 "$tmp"
  mv -f "$tmp" "$STATUS"
  logger -t netops-tls "$1"
  echo "$1"
}

fail() { status "refused: $1"; exit 1; }

for f in netops.crt netops.key; do
  [[ -f "$SRC/$f" && ! -L "$SRC/$f" ]] || fail "$SRC/$f is missing or not a plain file"
  (( $(stat -c %s "$SRC/$f") < 200000 )) || fail "$f is too large"
done

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
install -m 0600 "$SRC/netops.crt" "$work/netops.crt"
install -m 0600 "$SRC/netops.key" "$work/netops.key"

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
subject="$(openssl x509 -in "$DST/netops.crt" -noout -subject | sed 's/^subject= *//')"
until="$(openssl x509 -in "$DST/netops.crt" -noout -enddate | sed 's/^notAfter=//')"
status "applied: $subject, valid until $until"
