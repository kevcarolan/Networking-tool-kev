"""Platform entry point.  Run with:  uvicorn --factory app.main:create_app"""

import html
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.core import (alerts, appsettings, auth, display, inventory, licence, reports, search,
                      setup, ssh, twofactor, users)
from app.core.config import Settings, get_settings
from app.core.crypto import CredentialCipher
from app.core.db import init_engine, session_scope
from app.core.ssh import run_commands
from app.tools.config_backup import api as backup_api
from app.tools.config_backup.collector import fetch_config
from app.tools.config_backup.service import BackupService
from app.tools.config_backup.storage import GitConfigStore
from app.tools.circuits import api as circuits_api
from app.tools.calendar import api as calendar_api
from app.tools.circuits.scan import CircuitScanService
from app.tools.circuits import topology as topology_api
from app.tools.firmware_upgrade import api as firmware_api
from app.tools.firmware_upgrade import jobs_api
from app.tools.firmware_upgrade.deviceio import DeviceIO
from app.tools.firmware_upgrade.jobs import JobService
from app.tools.firmware_upgrade.service import FirmwareService
from app.tools.inventory import api as inventory_api
from app.tools.config_backup import compliance as compliance_api
from app.tools.inventory import layout as layout_api
from app.tools.inventory import sites as sites_api
from app.tools.monitoring import api as monitoring_api
from app.tools.syslog import api as syslog_api
from app.version import VERSION

STATIC_DIR = Path(__file__).parent / "static"

_SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
}


def create_app(settings: Settings | None = None, fetcher=fetch_config,
               start_scheduler: bool | None = None, fw_collector=run_commands,
               upgrade_io: DeviceIO | None = None, mailer=None, snmp_client=None,
               meraki_fetch=None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    init_engine(settings.database_url)
    cipher = CredentialCipher(settings.credential_key_file)
    store = GitConfigStore(settings.configs_dir)
    backup_service = BackupService(settings, cipher, store, fetcher=fetcher)
    firmware_service = FirmwareService(settings, cipher, collector=fw_collector)
    circuit_scan = CircuitScanService(settings, cipher, collector=fw_collector)
    alert_service = alerts.AlertService(settings, cipher, mailer or alerts.smtp_send)
    upgrade_io = upgrade_io or DeviceIO(fw_collector)
    # Upgrade jobs run in the separate worker process (app.worker); the web app only
    # queues requests. This instance is for tests and the CLI.
    job_service = JobService(settings, cipher, backup_service, io=upgrade_io)
    run_scheduler = settings.scheduler_enabled if start_scheduler is None else start_scheduler

    setup.ensure_token(settings)
    ssh.use_known_hosts(settings.data_dir / "known_hosts")  # devices' SSH host keys
    appsettings.apply(settings)  # site settings and defaults from the Settings page
    with session_scope() as db:
        licence.ensure_install(db)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        backup_service.recover_interrupted()
        firmware_service.recover_interrupted()
        if run_scheduler:
            backup_service.start()
            firmware_service.start()
            circuit_scan.start()
            alert_service.start()
        yield
        backup_service.stop()
        firmware_service.stop()
        circuit_scan.stop()
        alert_service.stop()

    docs = settings.api_docs
    app = FastAPI(title=settings.product_name, version=VERSION, lifespan=lifespan, redoc_url=None,
                  docs_url="/docs" if docs else None,
                  openapi_url="/openapi.json" if docs else None)
    app.state.settings = settings
    app.state.cipher = cipher
    app.state.authenticator = auth.Authenticator(settings)
    app.state.login_throttle = auth.LoginThrottle()
    app.state.address_throttle = auth.LoginThrottle(max_failures=30)  # any names, one address
    app.state.backup_service = backup_service
    app.state.firmware_service = firmware_service
    app.state.circuit_scan = circuit_scan
    app.state.alert_service = alert_service
    app.state.job_service = job_service
    app.state.upgrade_io = upgrade_io
    app.state.snmp_client = snmp_client  # None: real SNMP (the profile Test button)
    app.state.meraki_fetch = meraki_fetch  # None: real HTTPS to the Meraki Dashboard API

    app.add_middleware(
        SessionMiddleware, secret_key=settings.secret_key, session_cookie="netops_session",
        max_age=settings.session_max_age_hours * 3600, same_site="strict",
        https_only=settings.session_https_only,
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        for key, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        # Browsers check with the server before using a page or script they kept (a quick
        # "not modified" when it is the same), so an update is seen without clearing caches.
        response.headers.setdefault("Cache-Control", "no-cache")
        return response

    app.include_router(auth.router)
    app.include_router(twofactor.router)
    app.include_router(inventory.router)
    app.include_router(users.router)
    app.include_router(setup.router)
    app.include_router(licence.router)
    app.include_router(display.admin_router)
    app.include_router(display.router)
    app.include_router(alerts.router)
    app.include_router(reports.router)
    app.include_router(search.router)
    app.include_router(inventory_api.router)  # part of every licence
    app.include_router(sites_api.router)  # part of every licence
    app.include_router(layout_api.router)  # part of every licence
    app.include_router(calendar_api.router)  # part of every licence
    app.include_router(backup_api.router)
    app.include_router(compliance_api.router)  # the backups licence, on the router itself
    # The tools a licence can leave out (licence.MODULES): refused unless unlocked.
    app.include_router(firmware_api.router, dependencies=[Depends(licence.module("firmware"))])
    app.include_router(jobs_api.router, dependencies=[Depends(licence.module("upgrades"))])
    app.include_router(circuits_api.router, dependencies=[Depends(licence.module("circuits"))])
    app.include_router(topology_api.router, dependencies=[Depends(licence.module("circuits"))])
    app.include_router(syslog_api.router, dependencies=[Depends(licence.module("syslog"))])
    app.include_router(monitoring_api.router, dependencies=[Depends(licence.module("monitoring"))])

    @app.get("/api/health", include_in_schema=False)
    def health():
        return {"ok": True}

    # The page shell carries the product name, filled in once here so it shows
    # before any script runs (also on the login screen).
    index_page = (STATIC_DIR / "index.html").read_text(encoding="utf-8").replace(
        "{{product_name}}", html.escape(settings.product_name))

    @app.get("/", include_in_schema=False)
    @app.get("/index.html", include_in_schema=False)
    def index():
        return HTMLResponse(index_page)

    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app

