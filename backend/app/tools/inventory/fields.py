"""The inventory's columns, keeping it in step with the devices, and checking input.

``STANDARD`` lists the built-in columns (label, group, kind). Admins add their own
(``AssetField``); their values live in ``Asset.custom``. The page, the import and the
export all use the same list, so a column added here appears everywhere.

For a managed row (linked to a device), the model, serial number and software version
come from the device's own output (the firmware tool's version check) when the row
leaves them empty; what someone typed always wins.
"""

import datetime as dt
import json
import re
from dataclasses import asdict, dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

TYPES = ("switch", "router", "firewall", "wireless controller", "access point", "load balancer",
         "server", "storage", "virtual host", "rack", "PDU", "UPS", "patch panel",
         "media converter", "camera", "phone", "printer", "other")
STATUSES = ("in service", "spare", "planned", "faulty", "retired")
KINDS = ("text", "number", "date", "choice")


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    group: str
    kind: str = "text"  # text, number, date, choice
    choices: tuple[str, ...] = ()
    default_shown: bool = False
    auto: str = ""  # filled from the device when empty: "facts.model", ...
    max_length: int = 200


STANDARD: tuple[Field, ...] = (
    Field("name", "Name", "Identity", default_shown=True),
    Field("type", "Type", "Identity", "choice", TYPES, default_shown=True),
    Field("role", "Role", "Identity"),
    Field("manufacturer", "Manufacturer", "Identity", default_shown=True, auto="vendor"),
    Field("model", "Model", "Identity", default_shown=True, auto="facts.model"),
    Field("serial", "Serial number", "Identity", default_shown=True, auto="facts.serial"),
    Field("asset_tag", "Asset tag", "Identity"),
    Field("os", "OS / platform", "Software", auto="platform"),
    Field("version", "Version", "Software", default_shown=True, auto="facts.version"),
    Field("mgmt_ip", "Management IP", "Network", default_shown=True, auto="address"),
    Field("mgmt_vlan", "Management VLAN", "Network", max_length=20),
    Field("mac", "MAC address", "Network", max_length=50),
    Field("site", "Site", "Location", default_shown=True, auto="site"),
    Field("building", "Building", "Location"),
    Field("floor", "Floor", "Location", max_length=50),
    Field("room", "Room", "Location"),
    Field("rack", "Rack", "Location", default_shown=True),
    Field("rack_position", "Position (U)", "Location", "number"),
    Field("rack_units", "Height (U)", "Location", "number"),
    Field("rack_face", "Rack face", "Location", "choice", ("front", "rear")),
    Field("rack_depth", "Depth", "Location", "choice", ("full", "half")),
    Field("status", "Status", "Lifecycle", "choice", STATUSES, default_shown=True),
    Field("purchase_date", "Purchase date", "Lifecycle", "date"),
    Field("warranty_end", "Warranty end", "Lifecycle", "date"),
    Field("support_contract", "Support contract", "Lifecycle"),
    Field("end_of_support", "End of support", "Lifecycle", "date"),
    Field("supplier", "Supplier", "Lifecycle"),
    Field("owner", "Owner / team", "Other"),
    Field("notes", "Notes", "Other", max_length=5000),
)
BY_KEY = {f.key: f for f in STANDARD}


def custom_fields(db: Session, model=None) -> list[Field]:
    """The admins' columns: the inventory's (AssetField) or another list's (``model``)."""
    if model is None:
        from app.tools.inventory.models import AssetField as model

    return [Field(f"x_{c.key}", c.label, "Custom", c.kind, tuple(json.loads(c.choices or "[]")))
            for c in db.scalars(select(model).order_by(model.position, model.id))]


def all_fields(db: Session) -> list[Field]:
    return [*STANDARD, *custom_fields(db)]


def describe(fields: list[Field]) -> list[dict]:
    return [{**asdict(f), "choices": list(f.choices)} for f in fields]


def slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:40] or "column"


# --- values --------------------------------------------------------------------------------

def check_value(field: Field, value):
    """The value as stored, or ValueError with a message for the page."""
    if value is None or (isinstance(value, str) and not value.strip()):
        if field.key == "name":
            raise ValueError("Name: required")
        return None if field.kind in ("number", "date") else ""
    if field.kind == "number":
        try:
            number = int(str(value).strip())
        except ValueError:
            raise ValueError(f"{field.label}: a whole number") from None
        if not 0 <= number <= 10_000_000:
            raise ValueError(f"{field.label}: 0 or more")
        return number
    if field.kind == "date":
        if isinstance(value, dt.datetime):
            return value.date()
        if isinstance(value, dt.date):
            return value
        text = str(value).strip()
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%d-%m-%Y"):
            try:
                return dt.datetime.strptime(text[:10], fmt).date()
            except ValueError:
                continue
        raise ValueError(f"{field.label}: a date (YYYY-MM-DD or DD/MM/YYYY)")
    text = str(value).strip()
    if field.kind == "choice" and field.choices:
        match = next((c for c in field.choices if c.lower() == text.lower()), None)
        if match is None:
            raise ValueError(f"{field.label}: one of {', '.join(field.choices)}")
        return match
    if len(text) > field.max_length:
        raise ValueError(f"{field.label}: at most {field.max_length} characters")
    return text


def apply(asset, values: dict, fields: list[Field]) -> list[str]:
    """Set the given values (standard and custom) on ``asset``. Returns the labels changed."""
    by_key = {f.key: f for f in fields}
    custom = json.loads(asset.custom or "{}")
    changed = []
    for key, raw in values.items():
        field = by_key.get(key)
        if field is None:
            raise ValueError(f"Unknown column '{key}'")
        value = check_value(field, raw)
        if key.startswith("x_"):
            stored = value.isoformat() if isinstance(value, dt.date) else value
            if custom.get(key[2:], "" if field.kind not in ("number", "date") else None) != stored:
                custom[key[2:]] = stored
                changed.append(field.label)
        elif getattr(asset, key) != value:
            setattr(asset, key, value)
            changed.append(field.label)
    asset.custom = json.dumps({k: v for k, v in custom.items() if v not in (None, "")})
    return changed


# --- in step with the devices ----------------------------------------------------------------

def sync_devices(db: Session) -> int:
    """Give every device a row: link a matching inventory-only row (same name, or the same
    address) or make a new one. Returns how many rows were linked or made."""
    from app.core.models import Device
    from app.tools.inventory.models import Asset

    existing = set(db.scalars(select(Device.id)))
    for gone in db.scalars(select(Asset).where(Asset.device_id.is_not(None),
                                               Asset.device_id.not_in(existing))):
        gone.device_id = None  # the device was deleted: its details stay, inventory only
    db.flush()
    linked = set(db.scalars(select(Asset.device_id).where(Asset.device_id.is_not(None))))
    loose = list(db.scalars(select(Asset).where(Asset.device_id.is_(None))))
    done = 0
    for device in db.scalars(select(Device).where(Device.id.not_in(linked) if linked else True)):
        match = next((a for a in loose if a.name.lower() == device.name.lower()), None) or \
            next((a for a in loose if a.mgmt_ip and a.mgmt_ip == device.address), None)
        if match:
            match.device_id = device.id
            loose.remove(match)
        else:
            db.add(Asset(device_id=device.id, name=device.name, type=_guess_type(device.platform),
                         status="in service", updated_by="inventory"))
        done += 1
    if done:
        db.flush()
    return done


def _guess_type(platform: str) -> str:
    if platform in ("cisco_asa", "cisco_ftd", "fortinet_fortios", "paloalto_panos",
                    "checkpoint_gaia"):
        return "firewall"
    if platform in ("aruba_aos8",):
        return "wireless controller"
    if platform in ("cisco_xr", "mikrotik_routeros", "ubiquiti_edgeos"):
        return "router"
    return "switch"


def device_values(device, facts) -> dict:
    """What the tools know about a managed row's device (shown where the row is empty)."""
    from app.core.platforms import PLATFORMS
    from app.tools.firmware_upgrade.facts import vendor_for

    p = PLATFORMS.get(device.platform)
    return {"vendor": vendor_for(device.platform), "platform": p.label if p else device.platform,
            "address": device.address, "site": device.site,
            "facts.model": facts.model if facts else None,
            "facts.serial": facts.serial if facts else None,
            "facts.version": facts.version if facts else None}
