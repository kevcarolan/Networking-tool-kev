"""Admin command line.

  python -m app.cli hash-password            # for NETOPS_LOCAL_ADMIN_PASSWORD_HASH
  python -m app.cli totp-secret              # two-factor for the break-glass admin:
                                             # NETOPS_LOCAL_ADMIN_TOTP_SECRET and a QR code
  python -m app.cli import-csv devices.csv   # bulk-load devices
  python -m app.cli backup <device-name>     # run one backup now and print the result
  python -m app.cli firmware-check <device-name> [--raw]
                                             # read one device's version and show what was parsed
  python -m app.cli capture <device-name> [--account backup] [--raw] [--out FILE]
                                             # save every read-only command the tools send
                                             # to the device, for parser checks (lab tests)
  python -m app.cli upgrades-running         # list upgrade jobs that are mid-step
                                             # (exit code 3 if a LIVE one is: don't restart
                                             # the worker now)
  python -m app.cli db-status                # database version (migrations); applies
                                             # nothing - the app migrates when it starts

CSV columns: name,address,platform,site,credential,frequency_minutes,notes
(`credential` is the name of an existing credential profile; `site`,
`frequency_minutes` and `notes` are optional).
"""

import argparse
import csv
import getpass
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from app.core.platforms import uses_ssh


def _totp_secret(_args) -> int:
    from app.core import totp
    from app.core.config import get_settings

    settings = get_settings()
    secret = totp.new_secret()
    link = totp.uri(secret, settings.local_admin_user, settings.product_name)
    print("Scan this with the authenticator app (or type the secret in by hand):\n")
    try:
        import segno

        segno.make(link, error="m").terminal(compact=True)
    except Exception:  # noqa: BLE001 - a terminal that can't draw it: the text is enough
        pass
    print(f"\nSecret: {secret}\n\nThen put this line in netops.env and restart the service:\n"
          f"NETOPS_LOCAL_ADMIN_TOTP_SECRET={secret}\n\n"
          "Keep a copy somewhere safe (a sealed envelope, the password vault): without it\n"
          "and the phone, the break-glass account can't sign in until the line is removed.")
    return 0


def _hash_password(_args) -> int:
    from app.core.crypto import hash_password

    pw = getpass.getpass("New local admin password: ")
    if len(pw) < 12:
        print("Use at least 12 characters.", file=sys.stderr)
        return 1
    if pw != getpass.getpass("Repeat: "):
        print("Passwords do not match.", file=sys.stderr)
        return 1
    print(f"NETOPS_LOCAL_ADMIN_PASSWORD_HASH='{hash_password(pw)}'")
    return 0


def _import_csv(args) -> int:
    from fastapi import HTTPException

    from app.core import licence
    from app.core.audit import audit
    from app.core.config import get_settings
    from app.core.db import init_engine, session_scope
    from app.core.inventory import DeviceIn
    from app.core.models import Credential, Device
    from app.tools.config_backup.service import ensure_states
    from app.tools.config_backup.models import BackupState

    from app.core import appsettings

    settings = get_settings()
    init_engine(settings.database_url)
    appsettings.apply(settings)
    created = skipped = 0
    with open(args.file, newline="", encoding="utf-8-sig") as fh, session_scope() as db:
        try:
            room = licence.room_for(db)
        except HTTPException as exc:
            print(exc.detail, file=sys.stderr)
            return 1
        creds = {c.name: c.id for c in db.scalars(select(Credential))}
        existing = set(db.scalars(select(Device.name)))
        for line_no, row in enumerate(csv.DictReader(fh), start=2):
            row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
            try:
                cred_name = row.get("credential", "")
                if cred_name and cred_name not in creds:
                    raise ValueError(f"unknown credential '{cred_name}'")
                data = DeviceIn(name=row.get("name", ""), address=row.get("address", ""),
                                platform=row.get("platform", ""), site=row.get("site", ""),
                                credential_id=creds.get(cred_name), notes=row.get("notes", ""))
                if data.name in existing:
                    print(f"line {line_no}: {data.name} already exists, skipped")
                    skipped += 1
                    continue
                if room is not None and created >= room:
                    print(f"line {line_no}: the licence covers no more devices, skipped",
                          file=sys.stderr)
                    skipped += 1
                    continue
                device = Device(**data.model_dump())
                db.add(device)
                db.flush()
                if uses_ssh(device.platform):  # SNMP-only devices have no backups
                    freq = int(row.get("frequency_minutes") or settings.default_frequency_minutes)
                    db.add(BackupState(device_id=device.id, frequency_minutes=max(15, freq)))
                existing.add(data.name)
                created += 1
            except Exception as exc:  # noqa: BLE001
                print(f"line {line_no}: {exc}", file=sys.stderr)
                skipped += 1
        ensure_states(db, settings.default_frequency_minutes)
        audit(db, getpass.getuser(), "device.import_csv", f"{created} created from {args.file}")
    print(f"Imported {created} device(s), skipped {skipped}.")
    return 0


def _backup(args) -> int:
    from app.core.config import get_settings
    from app.core.crypto import CredentialCipher
    from app.core.db import init_engine, session_scope
    from app.core.models import Device
    from app.tools.config_backup.models import BackupRun
    from app.tools.config_backup.service import BackupService
    from app.tools.config_backup.storage import GitConfigStore

    settings = get_settings()
    init_engine(settings.database_url)
    with session_scope() as db:
        device = db.scalar(select(Device).where(Device.name == args.name))
        if device is None:
            print(f"No device named {args.name}", file=sys.stderr)
            return 1
        if not uses_ssh(device.platform):
            print(f"{args.name} is an SNMP-only device: nothing is read from it over SSH",
                  file=sys.stderr)
            return 1
        device_id = device.id
    svc = BackupService(settings, CredentialCipher(settings.credential_key_file),
                        GitConfigStore(settings.configs_dir))
    run_id = svc.run(device_id, f"cli:{getpass.getuser()}")
    with session_scope() as db:
        run = db.get(BackupRun, run_id)
        print(f"{run.status}: {run.message}")
        return 0 if run.status == "success" else 2


def _firmware_check(args) -> int:
    from app.core.config import get_settings
    from app.core.crypto import CredentialCipher
    from app.core.db import init_engine, session_scope
    from app.core.models import Device
    from app.core.ssh import classify_error, run_commands, target_for
    from app.tools.firmware_upgrade.facts import FACT_COMMANDS, parse_facts

    settings = get_settings()
    init_engine(settings.database_url)
    with session_scope() as db:
        device = db.scalar(select(Device).where(Device.name == args.name))
        if device is None:
            print(f"No device named {args.name}", file=sys.stderr)
            return 1
        if not uses_ssh(device.platform):
            print(f"{args.name} is an SNMP-only device: nothing is read from it over SSH",
                  file=sys.stderr)
            return 1
        platform = device.platform
        try:
            target = target_for(device, CredentialCipher(settings.credential_key_file),
                                settings.ssh_timeout, settings.command_timeout)
        except Exception as exc:  # noqa: BLE001
            print(f"failed: {classify_error(exc)[1]}", file=sys.stderr)
            return 2
    commands = FACT_COMMANDS.get(platform)
    if commands is None:
        print(f"Version checks are not supported for {platform}", file=sys.stderr)
        return 1
    try:
        outputs = run_commands(target, commands)
    except Exception as exc:  # noqa: BLE001
        print(f"failed: {classify_error(exc)[1]}", file=sys.stderr)
        return 2
    if args.raw:
        for cmd, out in zip(commands, outputs):
            print(f"===== {cmd} =====\n{out}\n")
    try:
        facts = parse_facts(platform, outputs)
    except ValueError as exc:
        print(f"failed: {exc} (run with --raw to see the output)", file=sys.stderr)
        return 2
    for key, value in vars(facts).items():
        print(f"{key:12} {value if value is not None else '-'}")
    return 0


def _capture(args) -> int:
    import os

    from app.core.config import get_settings
    from app.core.crypto import CredentialCipher
    from app.core.db import init_engine, session_scope
    from app.core.models import Credential, Device
    from app.core.ssh import classify_error, run_commands, target_for
    from app.tools.firmware_upgrade import capture
    from app.tools.firmware_upgrade import checks as ck
    from app.tools.firmware_upgrade.models import DeviceUpgradeSettings

    settings = get_settings()
    init_engine(settings.database_url)
    with session_scope() as db:
        device = db.scalar(select(Device).where(Device.name == args.name))
        if device is None:
            print(f"No device named {args.name}", file=sys.stderr)
            return 1
        if not uses_ssh(device.platform):
            print(f"{args.name} is an SNMP-only device: nothing is read from it over SSH",
                  file=sys.stderr)
            return 1
        cred, account = None, "backup"
        s = db.get(DeviceUpgradeSettings, device.id)
        if args.account == "upgrade" and s and s.upgrade_credential_id:
            cred, account = db.get(Credential, s.upgrade_credential_id), "upgrade"
        elif args.account == "upgrade":
            print("No upgrade account set for this device: using the backup account "
                  "(some health checks may need the upgrade account)", file=sys.stderr)
        try:
            target = target_for(device, CredentialCipher(settings.credential_key_file),
                                settings.ssh_timeout, settings.command_timeout, credential=cred)
        except Exception as exc:  # noqa: BLE001
            print(f"failed: {classify_error(exc)[1]}", file=sys.stderr)
            return 2
        platform, name = device.platform, device.name
    th = ck.Thresholds(settings.upgrade_cpu_warn, settings.upgrade_mem_warn)
    try:
        text, lines = capture.capture(target, platform, run_commands, account, th, raw=args.raw)
    except Exception as exc:  # noqa: BLE001
        print(f"failed: {classify_error(exc)[1]}", file=sys.stderr)
        return 2
    out = Path(args.out) if args.out else (
        settings.data_dir / "captures" / f"{name}-{datetime.now():%Y%m%d-%H%M}.txt")
    out.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(text)
    for line in lines:
        print(line)
    print(f"\nSaved to {out}" + ("" if args.out else f"  (show it with: sudo cat {out})"))
    return 0


def _upgrades_running(_args) -> int:
    from app.core.config import get_settings
    from app.core.db import init_engine, session_scope
    from app.core.models import Device
    from app.tools.firmware_upgrade.jobs import pending_request
    from app.tools.firmware_upgrade.models import BUSY_STATES, UpgradeJob

    settings = get_settings()
    init_engine(settings.database_url)
    live = 0
    with session_scope() as db:
        for job in db.scalars(select(UpgradeJob)):
            req = pending_request(db, job.id)
            if job.status not in BUSY_STATES and not (req and req.claimed_at):
                continue
            name = db.get(Device, job.device_id).name
            mode = "dry run" if job.dry_run else "LIVE"
            print(f"#{job.id} {name}: {job.status} ({mode}) {job.current_step}")
            live += not job.dry_run
    if not live:
        print("No live upgrade is running.")
    return 3 if live else 0


def _db_status(_args) -> int:
    from sqlalchemy import create_engine, inspect

    from app.core import migrate
    from app.core.config import get_settings

    settings = get_settings()
    engine = create_engine(settings.database_url)
    head = migrate.head_revision()
    tables = set(inspect(engine).get_table_names())
    current = migrate.current_revision(engine) if "alembic_version" in tables else None
    print(f"Database:  {settings.data_dir / 'app.db'}")
    print(f"Version:   {current or ('none (from before migrations)' if tables else 'empty')}")
    print(f"Latest:    {head}")
    print("Up to date." if current == head else
          "The app brings it up to date when it starts (a copy is kept first).")
    return 0


def _version(args) -> int:
    from app.version import VERSION

    print(VERSION)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("hash-password").set_defaults(func=_hash_password)
    sub.add_parser("totp-secret").set_defaults(func=_totp_secret)
    p = sub.add_parser("import-csv")
    p.add_argument("file")
    p.set_defaults(func=_import_csv)
    p = sub.add_parser("backup")
    p.add_argument("name")
    p.set_defaults(func=_backup)
    p = sub.add_parser("firmware-check")
    p.add_argument("name")
    p.add_argument("--raw", action="store_true", help="also print the raw command output")
    p.set_defaults(func=_firmware_check)
    p = sub.add_parser("capture", help="save every read-only command's output from a device")
    p.add_argument("name")
    p.add_argument("--account", choices=("upgrade", "backup"), default="upgrade")
    p.add_argument("--raw", action="store_true", help="keep IP and MAC addresses")
    p.add_argument("--out", help="file to write (default: the data folder's captures/)")
    p.set_defaults(func=_capture)
    sub.add_parser("upgrades-running").set_defaults(func=_upgrades_running)
    sub.add_parser("db-status").set_defaults(func=_db_status)
    sub.add_parser("version", help="the installed version").set_defaults(func=_version)
    args = parser.parse_args(argv)
    if args.cmd not in ("hash-password", "totp-secret"):
        from app.core import ssh
        from app.core.config import get_settings

        ssh.use_known_hosts(get_settings().data_dir / "known_hosts")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
