"""Demo mode: the whole product on a simulated network, for showing it without real devices.

    python -m app.demo                 # http://127.0.0.1:8710, data in ./demo-data
    python -m app.demo --reset         # start again from a fresh demo network
    python -m app.demo --port 8720 --data /tmp/netops-demo

Sign in as ``demo`` / ``demo-password``. Backups, version checks, circuit scans and upgrade
jobs (live ones too) all run against the simulator in app/demo/simnet.py; nothing is sent
to a real device, and the device addresses are documentation addresses that are never
routed. The upgrade worker runs inside this process. Syslog messages are made up
(app/demo/syslog.py): three days of history, then one every few seconds. Uses its own data folder, never the
real one, and needs no licence.
"""

import argparse
import logging
import shutil
import threading
from pathlib import Path

import uvicorn
from fastapi.testclient import TestClient

from app.core import licence
from app.core.config import REPO_ROOT, Settings
from app.demo import seed
from app.demo import syslog as demo_syslog
from app.main import create_app
from app.worker import UpgradeWorker


def settings_for(data: Path, port: int) -> Settings:
    return Settings(
        _env_file=None, data_dir=data, port=port, host="127.0.0.1",
        session_https_only=False, ldap_url="", local_admin_password_hash="",
        upgrade_live_platforms=seed.LIVE_PLATFORMS, upgrade_settle_seconds=10,
        upgrade_poll_seconds=5, upgrade_reload_timeout_min=10, circuit_scan_schedule="",
    ).prepare()


def build(data: Path, port: int, net=None, scheduler: bool = True) -> tuple:
    """The demo app, its simulated network and the in-process upgrade worker."""
    settings = settings_for(data, port)
    net = net or seed.build_network()
    app = create_app(settings, fetcher=seed.fetcher, fw_collector=net.show, upgrade_io=net,
                     start_scheduler=scheduler)
    app.state.demo = True
    svc = app.state.job_service
    svc.sleep, svc.monotonic = net.sleep, net.monotonic
    return app, net, UpgradeWorker(settings, svc)


def resume(net) -> None:
    """After a restart: the simulated devices run what they ran when the demo stopped
    (an upgrade done in the demo stays done)."""
    from sqlalchemy import select

    from app.core.db import session_scope
    from app.core.models import Device
    from app.tools.firmware_upgrade.models import DeviceFacts

    with session_scope() as db:
        for name, version in db.execute(select(Device.name, DeviceFacts.version)
                                        .join(DeviceFacts, DeviceFacts.device_id == Device.id)):
            if name in net.devices and version:
                net.devices[name].version = version


def first_run(app, net) -> dict | None:
    """Fill an empty demo database, then read every device once."""
    with TestClient(app) as client:
        if client.get("/api/setup/status").json().get("needed") is False:
            return None
        info = seed.seed(client, app.state.settings, net)
        for device_id in info["ids"].values():
            app.state.backup_service.run(device_id)
            app.state.firmware_service.check(device_id)
        app.state.circuit_scan.scan("demo")
    return info


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.demo",
                                     description="The product on a simulated network")
    parser.add_argument("--data", type=Path, default=REPO_ROOT / "demo-data",
                        help="the demo's own data folder (default: ./demo-data)")
    parser.add_argument("--port", type=int, default=8710)
    parser.add_argument("--reset", action="store_true", help="start from a fresh demo network")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.reset and args.data.exists():
        if not (args.data / ".netops-demo").exists():
            raise SystemExit(f"{args.data} isn't a demo data folder: not deleting it")
        shutil.rmtree(args.data)
    args.data.mkdir(parents=True, exist_ok=True)
    marker = args.data / ".netops-demo"
    if not marker.exists():
        if any(args.data.iterdir()):
            raise SystemExit(f"{args.data} already holds other data: use an empty folder")
        marker.write_text("Demo data (python -m app.demo). Safe to delete.\n")

    licence.DEVELOPMENT = True  # the demo never needs a licence
    app, net, worker = build(args.data, args.port, scheduler=False)
    info = first_run(app, net)
    if info is None:
        resume(net)
    # The first run's TestClient closed the app; build it again (same network) to serve it.
    app, net, worker = build(args.data, args.port, net)
    threading.Thread(target=worker.run_forever, name="demo-worker", daemon=True).start()
    demo_syslog.start(app.state.settings, threading.Event())  # history, then a trickle

    url = f"http://127.0.0.1:{args.port}"
    print(f"\n  Demo running on {url}  (sign in as {seed.ADMIN_USER} / {seed.ADMIN_PASSWORD})")
    if info:
        print(f"  Wall display: {url}/display/#key={info['display_key']}")
    else:
        print("  Wall display: add one on Settings > Wall displays (the first link was shown "
              "on the first run)")
    print("  Everything runs against a simulated network. Ctrl+C to stop.\n")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
