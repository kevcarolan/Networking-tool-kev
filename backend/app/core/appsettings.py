"""Settings made in the GUI (first-run setup, Settings page), kept in the app_settings table.

Only the Active Directory settings live here. netops.env always wins: a value set there is
used as it is, and the GUI shows it as "set in netops.env". The stored value is used only
where netops.env leaves the setting empty.
"""

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
