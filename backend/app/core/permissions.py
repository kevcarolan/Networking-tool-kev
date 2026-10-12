"""What each user may do: a level per area of the tool, plus the admin flag.

Levels within an area are ordered: each one includes the ones before it. An admin has
the highest level everywhere and also manages users and reads the activity log.

    inventory  view < manage < addresses < credentials
                                        devices; who may decide where a device account is sent
    backups    none < view < run < configs < manage
    firmware   none < view < manage     versions, standards, image library, upgrade settings
    upgrades   none < view < dry_run < live
    circuits   none < view < manage
"""

AREAS: dict[str, dict] = {
    "inventory": {"label": "Devices and credentials", "levels": {
        "view": "See devices",
        "manage": "Also edit device details (name, platform, site, notes, schedule) and "
                  "delete devices",
        "addresses": "Also add devices and change a device's address or credential profile "
                     "(this decides where a device account's password is sent)",
        "credentials": "Also add, change and delete credential profiles"}},
    "backups": {"label": "Config backups", "levels": {
        "none": "No access",
        "view": "See backup status and history",
        "run": "Also run a backup now",
        "configs": "Also read stored configs and diffs (they contain secrets)",
        "manage": "Also change backup schedules"}},
    "firmware": {"label": "Firmware", "levels": {
        "none": "No access",
        "view": "See versions, standards and the image library",
        "manage": "Also check versions, upload images, set standards and upgrade settings"}},
    "upgrades": {"label": "Upgrade jobs", "levels": {
        "none": "No access",
        "view": "See jobs and reports",
        "dry_run": "Also plan and run dry-run jobs",
        "live": "Also plan and run live upgrades"}},
    "circuits": {"label": "Circuits", "levels": {
        "none": "No access",
        "view": "See the circuit list and exports",
        "manage": "Also upload the list and scan the network"}},
}

LEVELS: dict[str, list[str]] = {a: list(d["levels"]) for a, d in AREAS.items()}

PRESETS: dict[str, dict] = {
    "viewer": {"label": "Viewer", "admin": False, "perms": {
        "inventory": "view", "backups": "view", "firmware": "view", "upgrades": "view",
        "circuits": "view"}},
    "operator": {"label": "Backup operator", "admin": False, "perms": {
        "inventory": "view", "backups": "run", "firmware": "view", "upgrades": "view",
        "circuits": "view"}},
    "upgrader": {"label": "Upgrader", "admin": False, "perms": {
        "inventory": "view", "backups": "configs", "firmware": "view", "upgrades": "live",
        "circuits": "view"}},
    "admin": {"label": "Administrator", "admin": True, "perms": {a: lv[-1] for a, lv in LEVELS.items()}},
}


def normalise(perms: dict | None) -> dict[str, str]:
    """Every area with a valid level (unknown or missing -> the lowest level)."""
    perms = perms or {}
    return {a: perms.get(a) if perms.get(a) in lv else lv[0] for a, lv in LEVELS.items()}


def full() -> dict[str, str]:
    return {a: lv[-1] for a, lv in LEVELS.items()}


def at_least(perms: dict, area: str, level: str) -> bool:
    order = LEVELS[area]
    have = perms.get(area, order[0])
    return have in order and order.index(have) >= order.index(level)


def describe(perms: dict, admin: bool) -> str:
    if admin:
        return "Administrator"
    return ", ".join(f"{AREAS[a]['label']}: {perms.get(a, LEVELS[a][0])}" for a in LEVELS)
