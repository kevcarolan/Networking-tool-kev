"""Make licences (for the owner only; customers never need this). See docs/selling.md.

    python -m app.licence_tool keygen --out ~/licence-signing.key
        Once: makes the signing key. Keep the .key file secret and backed up (password
        vault). Put the public key it prints in backend/app/core/licence_keys.txt and commit it.

    python -m app.licence_tool sign --key ~/licence-signing.key --customer "Acme Ltd" \\
            --edition professional --add monitoring --devices 250 --expires 2027-10-31 \\
            --install-id 1A2B-3C4D-5E6F-7A8B --email it@acme.example --stripe cus_123 \\
            --ledger ~/OneDrive/NetCairn/licences.csv --out acme-2027.lic
        A customer licence.
        --edition: essentials, professional or complete (the tools each brings are in
            docs/licensing.md); --add monitoring for the Monitoring add-on. Or pick the
            tools yourself with --modules backups,syslog,...
        --devices: a number (50, 250, 1000...) or "unlimited". Each Meraki organisation
            uses 25 of them (--meraki-devices changes that for this licence).
        --install-id ties it to one server (shown on its Settings page).
        --ledger adds a line to the licence ledger (a CSV file, e.g. in your OneDrive
            folder); the NETCAIRN_LEDGER environment variable sets it once for all commands.

    python -m app.licence_tool sign --key ~/licence-signing.key --from 3F2A91C0 \\
            --expires 2028-10-31 [--devices 1000] [--add monitoring] --out acme-2028.lic
        A renewal or an upgrade: everything is taken from licence 3F2A91C0 in the ledger
        except what you give. The new licence replaces the old one on the customer's server.

    python -m app.licence_tool sign --key ~/licence-signing.key --internal --out internal.lic
        Your own licence for your own servers: no end date, any number of devices, every tool.

    python -m app.licence_tool ledger [--customer acme]
        The licences made so far (newest last).

    python -m app.licence_tool show acme.lic
        Check a licence and print what it says.
"""

import argparse
import csv
import datetime
import os
import secrets
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.core import licence
from app.core.exports import csv_writer

LEDGER_COLUMNS = ["issued", "id", "customer", "email", "stripe", "plan", "edition", "modules", "devices",
                  "meraki_devices", "expires", "install_id", "kind", "replaces", "note", "file"]


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


def make_payload(customer: str, expires: datetime.date | None, max_devices: int | None,
                 install_id: str = "", kind: str = "customer", modules: list[str] | None = None,
                 edition: str = "", meraki_devices: int | None = None) -> dict:
    payload = {"v": 1, "id": secrets.token_hex(4).upper(), "customer": customer,
               "issued": datetime.date.today().isoformat(),
               "expires": expires.isoformat() if expires else None,
               "max_devices": max_devices, "install_id": install_id or None, "kind": kind,
               "modules": licence.licensed_modules({"modules": modules if modules is not None
                                                    else list(licence.MODULES)})}
    if edition:
        payload["edition"] = edition
    if meraki_devices is not None:
        payload["meraki_devices"] = meraki_devices
    return payload


def sign(key: Ed25519PrivateKey, payload: dict) -> str:
    return licence.encode(payload, key.sign(licence.signed_bytes(payload)))


def make(key: Ed25519PrivateKey, customer: str, expires: datetime.date | None,
         max_devices: int | None, install_id: str = "", kind: str = "customer",
         modules: list[str] | None = None, edition: str = "",
         meraki_devices: int | None = None) -> str:
    return sign(key, make_payload(customer, expires, max_devices, install_id, kind, modules,
                                  edition, meraki_devices))


# --- the ledger -------------------------------------------------------------------

def _ledger_path(arg: str) -> Path | None:
    value = arg or os.environ.get("NETCAIRN_LEDGER", "")
    return Path(value).expanduser() if value else None


def read_ledger(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return [{k: (v or "").lstrip("'") for k, v in row.items()} for row in csv.DictReader(fh)]


def add_to_ledger(path: Path, row: dict) -> None:
    """One line per licence made. Text that looks like a formula is kept as text."""
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as fh:
        w = csv_writer(fh)
        if new:
            w.writerow(LEDGER_COLUMNS)
        w.writerow([row.get(c, "") for c in LEDGER_COLUMNS])


def _devices(text: str | None) -> tuple[bool, int | None]:
    """'250' -> (True, 250); 'unlimited' -> (True, None); None -> (False, None)."""
    if text is None or text == "":
        return False, None
    if str(text).lower() in ("unlimited", "none", "0"):
        return True, None
    n = int(text)
    if n < 1:
        raise ValueError
    return True, n


def _sign(args) -> int:
    key = _load_key(args.key)
    ledger = _ledger_path(args.ledger)
    base: dict = {}
    if args.from_id:
        if not ledger:
            print("--from needs the ledger (--ledger or NETCAIRN_LEDGER)", file=sys.stderr)
            return 2
        base = next((r for r in reversed(read_ledger(ledger)) if r["id"] == args.from_id.upper()), {})
        if not base:
            print(f"Licence {args.from_id} isn't in {ledger}", file=sys.stderr)
            return 2
    if args.internal:
        payload = make_payload(args.customer or "Internal use (not for resale)", None, None,
                               args.install_id, kind="internal")
    else:
        customer = args.customer or base.get("customer", "")
        expires = args.expires or ""
        try:
            given, max_devices = _devices(args.devices)
            if not given and base:
                given, max_devices = _devices(base.get("devices") or "unlimited")
        except ValueError:
            print("--devices is a number of devices, or 'unlimited'", file=sys.stderr)
            return 2
        if not customer or not expires or not given:
            print("A customer licence needs --customer, --expires and --devices (or --from a "
                  "licence in the ledger, or --internal)", file=sys.stderr)
            return 2
        edition = args.edition or ("" if args.modules else base.get("edition", ""))
        if edition and edition not in licence.EDITIONS:
            print(f"Unknown edition {edition}: choose {', '.join(licence.EDITIONS)}", file=sys.stderr)
            return 2
        if args.modules:
            modules = [m.strip() for m in args.modules.split(",") if m.strip()]
        elif edition:
            modules = list(licence.EDITIONS[edition][1])
        elif base.get("modules"):
            modules = base["modules"].split()
        else:
            modules = list(licence.MODULES)
        if base and not args.edition and not args.modules:  # keep the add-ons bought before
            modules += [m for m in base.get("modules", "").split() if m in licence.ADDONS]
        for add in [a.strip() for a in (args.add or "").split(",") if a.strip()]:
            if add not in licence.ADDONS:
                print(f"Unknown add-on {add}: choose {', '.join(licence.ADDONS)}", file=sys.stderr)
                return 2
            modules.append(add)
        unknown = [m for m in modules if m not in licence.MODULES]
        if unknown or not modules:
            print(f"Unknown module(s): {', '.join(unknown) or '(none given)'}. Choose from: "
                  f"{', '.join(licence.MODULES)}", file=sys.stderr)
            return 2
        meraki = args.meraki_devices if args.meraki_devices is not None else (
            int(base["meraki_devices"]) if base.get("meraki_devices") else None)
        payload = make_payload(customer, datetime.date.fromisoformat(expires), max_devices,
                               args.install_id or base.get("install_id", ""), modules=modules,
                               edition=edition, meraki_devices=meraki)
    text = sign(key, payload)
    if args.out:
        Path(args.out).write_text(text)
        print(f"Licence {payload['id']} written to {args.out}")
    else:
        print(text, end="")
    if ledger:
        add_to_ledger(ledger, {
            "issued": payload["issued"], "id": payload["id"], "customer": payload["customer"],
            "email": args.email or base.get("email", ""), "stripe": args.stripe or base.get("stripe", ""),
            "plan": licence.edition_label(payload), "edition": payload.get("edition", ""),
            "modules": " ".join(payload["modules"]),
            "devices": payload["max_devices"] or "unlimited",
            "meraki_devices": payload.get("meraki_devices") or "", "expires": payload["expires"] or "",
            "install_id": payload["install_id"] or "", "kind": payload["kind"],
            "replaces": base.get("id", ""), "note": args.note, "file": args.out or ""})
        print(f"Added to the ledger {ledger}", file=sys.stderr)
    elif not args.internal:
        print("Not in a ledger: give --ledger (or set NETCAIRN_LEDGER) to keep a record", file=sys.stderr)
    return 0


def _ledger(args) -> int:
    path = _ledger_path(args.ledger)
    if not path:
        print("Which ledger? Give --ledger or set NETCAIRN_LEDGER", file=sys.stderr)
        return 2
    rows = read_ledger(path)
    if args.customer:
        rows = [r for r in rows if args.customer.lower() in r["customer"].lower()]
    replaced = {r["replaces"] for r in rows if r.get("replaces")}
    for r in rows:
        mark = " (replaced)" if r["id"] in replaced else ""
        print(f"{r['issued']}  {r['id']}  {r['customer'][:30]:30}  {r['plan'][:32]:32}  "
              f"{r['devices']:>9} devices  until {r['expires'] or 'no end'}  {r['install_id'] or '-'}{mark}")
    if not rows:
        print("No licences" + (f" for {args.customer}" if args.customer else ""))
    return 0


def _show(args) -> int:
    try:
        payload = licence.parse(Path(args.file).read_text())
    except licence.LicenceError as exc:
        print(f"Not valid: {exc}", file=sys.stderr)
        return 1
    for k in ("id", "customer", "kind", "issued", "expires", "max_devices", "install_id"):
        print(f"{k:12} {payload.get(k) if payload.get(k) is not None else '-'}")
    print(f"{'edition':12} {licence.edition_label(payload)}")
    print(f"{'modules':12} {', '.join(licence.licensed_modules(payload))}")
    print(f"{'meraki':12} {payload.get('meraki_devices', licence.MERAKI_DEVICES)} devices per organisation")
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
    p.add_argument("--devices", help="most devices: a number, or 'unlimited'")
    p.add_argument("--edition", default="", help=f"one of: {', '.join(licence.EDITIONS)}")
    p.add_argument("--add", default="", help=f"add-ons, comma separated: {', '.join(licence.ADDONS)}")
    p.add_argument("--modules", default="",
                   help=f"instead of an edition, the tools it unlocks: {','.join(licence.MODULES)}")
    p.add_argument("--meraki-devices", type=int, help=f"devices per Meraki organisation (default {licence.MERAKI_DEVICES})")
    p.add_argument("--install-id", default="", help="tie the licence to one server")
    p.add_argument("--email", default="", help="the customer's contact (ledger only)")
    p.add_argument("--stripe", default="", help="the Stripe customer or subscription ID (ledger only)")
    p.add_argument("--note", default="", help="a note for the ledger")
    p.add_argument("--from", dest="from_id", default="", help="renew or upgrade this licence from the ledger")
    p.add_argument("--ledger", default="", help="the ledger CSV (or set NETCAIRN_LEDGER)")
    p.add_argument("--internal", action="store_true", help="no end date, any number of devices")
    p.add_argument("--out")
    p.set_defaults(func=_sign)
    p = sub.add_parser("ledger", help="list the licences made")
    p.add_argument("--ledger", default="")
    p.add_argument("--customer", default="")
    p.set_defaults(func=_ledger)
    p = sub.add_parser("show", help="check a licence")
    p.add_argument("file")
    p.set_defaults(func=_show)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
