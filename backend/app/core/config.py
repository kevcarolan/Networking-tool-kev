"""Application settings, read from environment variables prefixed ``NETOPS_``
(or from a ``.env`` file in the working directory)."""

import os
import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import PrivateAttr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NETOPS_", env_file=".env", extra="ignore")

    # Product name shown in the browser title, the page header and reports.
    product_name: str = "NetCairn"
    # The customer or site, shown next to the product name and in reports (Settings page)
    site_name: str = ""

    # The settings given in netops.env or the environment (recorded before the Settings
    # page fills in its own values; see app/core/appsettings.py)
    _from_env: frozenset[str] | None = PrivateAttr(default=None)

    # Where 'python -m app' listens (development and trials). Not 8000, which other
    # local tools often use. The installed service (systemd + nginx) also uses 8710.
    host: str = "127.0.0.1"
    port: int = 8710
    # Where the root certificate service (deploy/netops-tls-apply.sh) writes its result
    tls_status_file: Path = Path("/var/lib/netops-tls/apply-status")

    # The wall display's own HTTPS port (nginx). Only used to show the display link; the
    # nginx site and the host firewall must use the same number.
    display_port: int = 8443

    # Storage: SQLite database and the git repository of device configs live here.
    data_dir: Path = REPO_ROOT / "data"
    # Key used to encrypt device credentials. Keep it OUTSIDE data_dir in
    # production (e.g. /etc/netops/credential.key) and back it up separately.
    credential_key_file: Path | None = None
    # Key used to sign login session cookies. Generated on first run if unset.
    secret_key: str = ""

    # Web sessions
    session_https_only: bool = False
    session_max_age_hours: int = 12
    # Interactive API docs at /docs. Off by default: they describe every endpoint
    # and aren't needed to run the tools.
    api_docs: bool = False

    # Active Directory / LDAP
    ldap_url: str = ""  # e.g. ldaps://dc1.corp.local
    ldap_domain: str = ""  # e.g. corp.local  (users log in as "jsmith")
    ldap_base_dn: str = ""  # e.g. DC=corp,DC=local
    ldap_admin_group: str = ""  # DN of the group allowed to make changes
    ldap_viewer_group: str = ""  # DN of the read-only group; empty = any domain user
    ldap_ca_file: str = ""  # CA bundle for validating the DC certificate
    ldap_upgrader_group: str = ""  # DN of the group allowed to run upgrades; empty = admins

    # Local break-glass admin (works even if AD is down). Leave the hash empty to disable.
    local_admin_user: str = "admin"
    local_admin_password_hash: str = ""
    local_admin_totp_secret: str = ""  # two-factor for the break-glass admin (totp.py)

    # Config backup tool
    scheduler_enabled: bool = True
    scheduler_tick_seconds: int = 30
    backup_workers: int = 10
    default_frequency_minutes: int = 1440
    failure_retry_minutes: int = 60
    ssh_timeout: int = 30
    command_timeout: int = 180
    history_retention_days: int = 90
    viewers_can_read_configs: bool = False
    require_two_factor: bool = False  # local users must set up two-factor sign-in

    # Firmware tool
    firmware_check_minutes: int = 1440  # how often each device's version is re-read
    firmware_workers: int = 5
    firmware_max_upload_mb: int = 4096
    # Uploads stop while this much disk is still free (MB)
    firmware_keep_free_mb: int = 2048

    # Upgrade jobs
    upgrade_workers: int = 2
    upgrade_cpu_warn: int = 80  # % CPU (5 min) above which a pre-check warns
    upgrade_mem_warn: int = 85  # % memory used above which a pre-check warns
    upgrade_flash_factor: float = 1.1  # free flash needed = image size x factor
    upgrade_flash_factor_install: float = 2.2  # IOS-XE install mode expands the image
    upgrade_backup_max_age_hours: int = 24
    # Platforms (or platform:path) allowed to make real changes, comma-separated,
    # e.g. "cisco_ios" or "cisco_ios,cisco_ftd:fdm_ha". Empty = every job is a dry run.
    upgrade_live_platforms: str = ""
    upgrade_abort_timer_min: int = 120  # IOS-XE: reverts by itself unless committed in time
    upgrade_reload_timeout_min: int = 30  # how long to wait for a device to come back
    upgrade_settle_seconds: int = 120  # wait after SSH is back before the post-checks
    upgrade_copy_timeout_min: int = 60  # image copy and install commands
    upgrade_poll_seconds: int = 15  # how often to test whether a reloading device is back
    upgrade_worker_poll_seconds: float = 2.0  # how often the worker looks for new requests
    upgrade_require_worker: bool = True  # refuse job actions while the worker isn't running

    def live_allowed(self, platform: str, path: str) -> bool:
        allowed = {p.strip() for p in self.upgrade_live_platforms.split(",") if p.strip()}
        return platform in allowed or f"{platform}:{path}" in allowed

    # Circuit list tool
    circuits_max_upload_mb: int = 25
    # When to read every device's MAC and ARP tables (server local time), e.g. "daily 03:00"
    # or "daily 02:00". Empty = no scheduled scan (upgrade jobs still read their device).
    circuit_scan_schedule: str = "daily 03:00"  # every night, when the network is quiet
    circuit_scan_workers: int = 5

    # Syslog (the receiver is its own service, netops-syslog; app/tools/syslog/receiver.py)
    syslog_udp_port: int = 514  # 0 = don't listen on UDP
    syslog_tcp_port: int = 514  # 0 = don't listen on TCP
    syslog_bind: str = "0.0.0.0"  # "::" for IPv6 and IPv4
    # Syslog over TLS (RFC 5425), usually 6514; 0 = off. The certificate is the web
    # server's (handed to the service by systemd, LoadCredential) unless these name others.
    syslog_tls_port: int = 0
    syslog_tls_cert: str = ""
    syslog_tls_key: str = ""
    syslog_tls_client_ca: str = ""  # set: every device must show a certificate from this CA
    syslog_keep_days: int = 30  # Settings page
    syslog_max_gb: int = 20  # Settings page; the oldest days go first
    syslog_inventory_only: bool = False  # Settings page: drop senders not in the inventory
    syslog_keep_free_mb: int = 2048  # stop storing while this much disk is still free
    syslog_rate_per_source: int = 2000  # messages a second from one sender; more are dropped


    def record_env(self) -> frozenset[str]:
        """The settings given in netops.env or the environment (not defaults)."""
        if self._from_env is None:
            self._from_env = frozenset(self.model_fields_set)
        return self._from_env

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.data_dir / 'app.db'}"

    @property
    def configs_dir(self) -> Path:
        return self.data_dir / "configs"

    @property
    def firmware_dir(self) -> Path:
        return self.data_dir / "firmware"

    @property
    def syslog_dir(self) -> Path:
        return self.data_dir / "syslog"

    def prepare(self) -> "Settings":
        """Create the data directory and fill in generated secrets."""
        self.record_env()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if self.credential_key_file is None:
            self.credential_key_file = self.data_dir / "credential.key"
        if not self.secret_key:
            self.secret_key = _read_or_create_secret(self.data_dir / "session.key")
        return self


def _read_or_create_secret(path: Path) -> str:
    if path.exists():
        return path.read_text().strip()
    value = secrets.token_urlsafe(48)
    _write_private(path, value)
    return value


def _write_private(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(value)


@lru_cache
def get_settings() -> Settings:
    return Settings().prepare()
