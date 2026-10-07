"""Upgrade drivers, one per platform. To support a new design, add a path to a driver
(or a new driver) - the job engine, GUI and report pick it up from here."""

from app.tools.firmware_upgrade.drivers.allied_awplus import AlliedAwplusDriver
from app.tools.firmware_upgrade.drivers.arista_eos import AristaEosDriver
from app.tools.firmware_upgrade.drivers.aruba_aos8 import ArubaAos8Driver
from app.tools.firmware_upgrade.drivers.aruba_osswitch import ArubaOsSwitchDriver
from app.tools.firmware_upgrade.drivers.base import UpgradeDriver, UpgradePath
from app.tools.firmware_upgrade.drivers.cisco_asa import CiscoAsaDriver
from app.tools.firmware_upgrade.drivers.cisco_ftd import CiscoFtdDriver
from app.tools.firmware_upgrade.drivers.cisco_ios import CiscoIosDriver
from app.tools.firmware_upgrade.drivers.cisco_nxos import CiscoNxosDriver
from app.tools.firmware_upgrade.drivers.cisco_xr import CiscoXrDriver
from app.tools.firmware_upgrade.drivers.dell_os10 import DellOs10Driver
from app.tools.firmware_upgrade.drivers.extreme_exos import ExtremeExosDriver
from app.tools.firmware_upgrade.drivers.fortinet_fortios import FortinetFortiosDriver
from app.tools.firmware_upgrade.drivers.huawei_vrp import HuaweiVrpDriver
from app.tools.firmware_upgrade.drivers.juniper_junos import JuniperJunosDriver
from app.tools.firmware_upgrade.drivers.mikrotik_routeros import MikrotikRouterosDriver
from app.tools.firmware_upgrade.drivers.paloalto_panos import PaloaltoPanosDriver
from app.tools.firmware_upgrade.drivers.ubiquiti_edgeos import UbiquitiEdgeosDriver

DRIVERS: dict[str, UpgradeDriver] = {d.platform: d for d in (
    CiscoIosDriver(), CiscoNxosDriver(), CiscoAsaDriver(), CiscoFtdDriver(), AlliedAwplusDriver(),
    # built from vendor documentation; lab sign-off needed before live use
    AristaEosDriver(), JuniperJunosDriver(), ArubaOsSwitchDriver(), ArubaAos8Driver(),
    DellOs10Driver(), ExtremeExosDriver(), HuaweiVrpDriver(), CiscoXrDriver(),
    MikrotikRouterosDriver(), UbiquitiEdgeosDriver(), FortinetFortiosDriver(),
    PaloaltoPanosDriver())}


def for_platform(platform: str) -> UpgradeDriver | None:
    return DRIVERS.get(platform)


def default_path(platform: str, facts: dict, preferred: str = "", has_peer: bool = False) -> str:
    driver = DRIVERS.get(platform)
    if driver is None:
        return ""
    if preferred and driver.path(preferred):
        return preferred
    if hasattr(driver, "default_path"):
        return driver.default_path(facts)
    pair = next((p.id for p in driver.paths if p.units == 2), None)
    return pair if has_peer and pair else driver.paths[0].id


def catalogue() -> list[dict]:
    return [{"platform": d.platform, "paths": [vars(p) for p in d.paths]} for d in DRIVERS.values()]


__all__ = ["DRIVERS", "UpgradeDriver", "UpgradePath", "catalogue", "default_path", "for_platform"]
