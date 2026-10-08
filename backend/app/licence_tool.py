"""Make licences (for the owner only; customers never need this).

    python -m app.licence_tool keygen --out ~/licence-signing.key
        Once: makes the signing key. Keep the .key file secret and backed up (password
        vault). Put the public key it prints in backend/app/core/licence_keys.txt and commit it.

    python -m app.licence_tool sign --key ~/licence-signing.key --customer "Acme Ltd" \\
            --expires 2027-10-31 --devices 500 [--install-id 1A2B-3C4D-5E6F-7A8B] --out acme.lic
        A customer licence. --install-id ties it to one server (shown on its Settings page).

    python -m app.licence_tool sign --key ~/licence-signing.key --internal --out internal.lic
        Your own licence for testing: no end date, any number of devices.

    python -m app.licence_tool show acme.lic
        Check a licence and print what it says.
"""

import argparse
import datetime
import os
import secrets
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.core import licence


def _keygen(args) -> int:
    out = Path(args.out).expanduser()
    if out.exists():
        print(f"{out} already exists: not overwriting a signing key", file=sys.stderr)
        return 1
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption())
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(pem)
    public = key.public_key().public_bytes(serialization.Encoding.Raw,
                                           serialization.PublicFormat.Raw)
    print(f"Signing key written to {out}. Keep it secret and backed up: anyone with it can "
          f"make licences, and without it you can't make new ones.\n")
    print("Add this line to backend/app/core/licence_keys.txt and commit it:\n")
    print(licence._b64(public))
    return 0


def _load_key(path: str) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(Path(path).expanduser().read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise SystemExit("That isn't a licence signing key")
    return key


def make(key: Ed25519PrivateKey, customer: str, expires: datetime.date | None,
         max_devices: int | None, install_id: str = "", kind: str = "customer") -> str:
    payload = {"v": 1, "id": secrets.token_hex(4).upper(), "customer": customer,
               "issued": datetime.date.today().isoformat(),
               "expires": expires.isoformat() if expires else None,
               "max_devices": max_devices, "install_id": install_id or None, "kind": kind}
    data = licence.signed_bytes(payload)
    return licence.encode(payload, key.sign(data))


def _sign(args) -> int:
    key = _load_key(args.key)
    if args.internal:
        text = make(key, args.customer or "Internal use (not for resale)", None, None,
                    args.install_id, kind="internal")
    else:
        if not args.customer or not args.expires or not args.devices:
            print("A customer licence needs --customer, --expires and --devices "
                  "(or use --internal)", file=sys.stderr)
            return 2
        text = make(key, args.customer, datetime.date.fromisoformat(args.expires),
                    args.devices, args.install_id)
    if args.out:
        Path(args.out).write_text(text)
        print(f"Licence written to {args.out}")
    else:
        print(text, end="")
    return 0


def _show(args) -> int:
    try:
        payload = licence.parse(Path(args.file).read_text())
    except licence.LicenceError as exc:
        print(f"Not valid: {exc}", file=sys.stderr)
        return 1
    for k in ("id", "customer", "kind", "issued", "expires", "max_devices", "install_id"):
        print(f"{k:12} {payload.get(k) if payload.get(k) is not None else '-'}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.licence_tool",
                                     description="Make and check licences")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("keygen", help="make the signing key (once)")
    p.add_argument("--out", required=True)
    p.set_defaults(func=_keygen)
    p = sub.add_parser("sign", help="make a licence")
    p.add_argument("--key", required=True)
    p.add_argument("--customer", default="")
    p.add_argument("--expires", help="last day the licence is valid, YYYY-MM-DD")
    p.add_argument("--devices", type=int, help="most devices in the inventory")
    p.add_argument("--install-id", default="", help="tie the licence to one server")
    p.add_argument("--internal", action="store_true", help="no end date, any number of devices")
    p.add_argument("--out")
    p.set_defaults(func=_sign)
    p = sub.add_parser("show", help="check a licence")
    p.add_argument("file")
    p.set_defaults(func=_show)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
