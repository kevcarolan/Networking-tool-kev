"""Settings made in the GUI (first-run setup, Settings page), kept in the app_settings table.

Two kinds, and netops.env always wins for both (the GUI shows those as "set in netops.env"):

* **Active Directory** (``LDAP_KEYS``): the stored value is used where netops.env leaves the
  setting empty (``effective``).
* **Site and defaults** (``OPTIONS``): the customer or site name and the day-to-day defaults.
  ``apply`` copies the stored values onto the running Settings, unless netops.env sets them.
  The web app applies them at start and on every save; the worker on every heartbeat.

Settings that are safety gates (live upgrade platforms, the break-glass admin, ports,
secrets) stay in netops.env only: changing them needs root on the server.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db import session_scope, utcnow

LDAP_KEYS = ("ldap_url", "ldap_domain", "ldap_base_dn", "ldap_admin_group",
             "ldap_viewer_group", "ldap_upgrader_group", "ldap_ca_file")
SETUP_DONE = "setup_completed_at"


def stored(db: Session) -> dict[str, str]:
    from app.core.models import AppSetting

    return {row.key: row.value for row in db.query(AppSetting).all()}


def save(db: Session, values: dict[str, str], username: str) -> None:
    from app.core.models import AppSetting

    for key, value in values.items():
        row = db.get(AppSetting, key)
        if row is None:
            db.add(AppSetting(key=key, value=value, updated_by=username))
        else:
            row.value, row.updated_by, row.updated_at = value, username, utcnow()


def from_env(settings: Settings) -> set[str]:
    """The AD settings netops.env sets (these can't be changed in the GUI)."""
    return {k for k in LDAP_KEYS if getattr(settings, k)}


def effective(settings: Settings, db: Session | None = None) -> Settings:
    """The settings with the stored AD values filled in where netops.env has none."""
    if db is None:
        with session_scope() as own:
            return effective(settings, own)
    values = stored(db)
    update = {k: values[k] for k in LDAP_KEYS if not getattr(settings, k) and values.get(k)}
    return settings.model_copy(update=update) if update else settings


# --- site and defaults ----------------------------------------------------------------

@dataclass(frozen=True)
class Option:
    key: str
    label: str
    kind: type  # str, int or bool
    low: int = 0
    high: int = 0
    help: str = ""


OPTIONS = (
    Option("site_name", "Customer or site name", str, high=100,
           help="Shown next to the product name and on upgrade reports"),
    Option("default_frequency_minutes", "Backup every (minutes), for new devices", int, 15, 10080),
    Option("failure_retry_minutes", "Retry a failed backup or version check after (minutes)", int, 5, 1440),
    Option("history_retention_days", "Keep backup and check history for (days)", int, 7, 3650,
           help="Config versions themselves are always kept"),
    Option("firmware_check_minutes", "Read each device's software version every (minutes)", int, 60, 10080),
    Option("circuit_scan_schedule", "Circuit location scan", str, high=40,
           help="'sun 02:00', 'daily 02:00' (server time), or empty for none"),
    Option("viewers_can_read_configs", "Viewers may read device configs", bool,
           help="Configs contain password hashes and keys"),
    Option("upgrade_cpu_warn", "Upgrade pre-check: warn above CPU (%)", int, 1, 100),
    Option("upgrade_mem_warn", "Upgrade pre-check: warn above memory used (%)", int, 1, 100),
    Option("upgrade_backup_max_age_hours", "Take a fresh backup before an upgrade if older than (hours)",
           int, 1, 720),
)
OPTION_KEYS = tuple(o.key for o in OPTIONS)


def check_option(option: Option, value) -> str:
    """The value as stored text; raises ValueError with a message for the GUI."""
    if option.kind is bool:
        if not isinstance(value, bool):
            raise ValueError(f"{option.label}: yes or no")
        return "true" if value else "false"
    if option.kind is int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{option.label}: a whole number")
        if not option.low <= value <= option.high:
            raise ValueError(f"{option.label}: between {option.low} and {option.high}")
        return str(value)
    text = str(value).strip()
    if len(text) > option.high:
        raise ValueError(f"{option.label}: at most {option.high} characters")
    if option.key == "circuit_scan_schedule":
        from app.tools.circuits.scan import parse_schedule

        parse_schedule(text)  # raises ValueError with the expected format
    return text


def _typed(option: Option, text: str):
    if option.kind is bool:
        return text == "true"
    return int(text) if option.kind is int else text


def apply(settings: Settings, db: Session | None = None) -> None:
    """Copy the stored site settings and defaults onto ``settings`` (netops.env wins)."""
    if db is None:
        with session_scope() as own:
            return apply(settings, own)
    locked = settings.record_env()
    values = stored(db)
    for option in OPTIONS:
        if option.key in locked:
            continue
        if option.key in values:
            value = _typed(option, values[option.key])
        else:
            value = Settings.model_fields[option.key].default
        if getattr(settings, option.key) != value:
            setattr(settings, option.key, value)
