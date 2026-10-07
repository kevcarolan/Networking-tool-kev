"""Multi-vendor support (PR A): backups, versions and circuit locations for every
platform added after Cisco and Allied Telesis. Sample output: tests/vendor_samples.py."""

import pytest

from app.core.platforms import PLATFORMS
from app.tools.circuits import live
from app.tools.circuits.importer import normalize_port
from app.tools.config_backup.collector import clean_config
from app.tools.firmware_upgrade import drivers
from app.tools.firmware_upgrade.facts import (_PARSERS, FACT_COMMANDS, compare_versions,
                                              parse_facts, vendor_for)
from tests import firmware_samples as fs
from tests import vendor_samples as s


# --- the platform list ---------------------------------------------------------

def test_every_platform_has_version_checks_and_a_vendor():
    for key, p in PLATFORMS.items():
        assert key in FACT_COMMANDS and key in _PARSERS, key
        assert p.vendor and vendor_for(key) == p.vendor
    assert vendor_for("allied_awplus") == "Allied Telesis" and vendor_for("cisco_xr") == "Cisco"


def test_live_commands_use_known_keys():
    keys = {"mac", "arp", "cdp", "lldp", "lldp_table", "mt_neighbor", "pc"}
    for platform, commands in live.COMMANDS.items():
        assert platform in PLATFORMS and set(commands) <= keys, platform


def test_platforms_without_an_upgrade_driver_yet():
    # AOS-CX and Cisco small business would have to pull the image (not wanted: backups and
    # versions only); Check Point needs an expert-shell account (to be decided). A job
    # can't be created for them.
    assert set(PLATFORMS) - set(drivers.DRIVERS) == {"checkpoint_gaia", "aruba_aoscx", "cisco_smb"}


# --- backups -------------------------------------------------------------------

def test_eos_backup_drops_command_and_time_lines():
    cleaned = clean_config("arista_eos", s.EOS_CONFIG)
    assert "! Time:" not in cleaned and "! Command:" not in cleaned
    assert "! device: leaf1" in cleaned and "hostname leaf1" in cleaned


def test_junos_backup_drops_last_commit_and_vc_banner():
    cleaned = clean_config("juniper_junos", s.JUNOS_CONFIG)
    assert "Last commit" not in cleaned and "{master" not in cleaned
    assert cleaned.startswith("set version 22.4R3-S2.11\n")


def test_fortios_backup_masks_reencrypted_secrets():
    cleaned = clean_config("fortinet_fortios", s.FORTIOS_CONFIG)
    assert "#conf_file_ver" not in cleaned and "#buildno" not in cleaned
    assert "set password ENC <encrypted>" in cleaned
    assert "set psksecret ENC <encrypted>" in cleaned and "Wq8b3k" not in cleaned
    # The next run shows new ciphertext: the backup must not change.
    again = s.FORTIOS_CONFIG.replace("SH2nBbW2fB0Kp1e3T9Zk0pXqk=", "SH2zzzz").replace("Wq8b3k", "Xx")
    assert clean_config("fortinet_fortios", again) == cleaned


def test_panos_backup_keeps_only_the_set_commands():
    cleaned = clean_config("paloalto_panos", s.PANOS_CONFIG)
    assert cleaned.splitlines()[0] == "set deviceconfig system hostname pa1"
    assert "[edit]" not in cleaned and "configuration mode" not in cleaned


def test_routeros_and_xr_backups_drop_timestamps():
    assert "by RouterOS" not in clean_config("mikrotik_routeros", s.MIKROTIK_CONFIG)
    xr = clean_config("cisco_xr", s.XR_CONFIG)
    assert "UTC" not in xr.splitlines()[0] and "Last configuration change" not in xr
    assert "hostname pe1" in xr


@pytest.mark.parametrize("platform, error", [
    ("juniper_junos", "error: syntax error, expecting <command>: configuration\n"),
    ("huawei_vrp", "Error: Unrecognized command found at '^' position.\n"),
    ("mikrotik_routeros", "bad command name export (line 1 column 2)\n"),
    ("aruba_aoscx", "Invalid input: running-configuration\n"),
])
def test_backup_rejects_vendor_error_messages(platform, error):
    from app.tools.config_backup.collector import BackupError
    with pytest.raises(BackupError):
        clean_config(platform, error * 6)


# --- versions ------------------------------------------------------------------

@pytest.mark.parametrize("platform, outputs, expected", [
    ("arista_eos", [s.EOS_VERSION, s.EOS_DIR],
     ("4.30.1F", "DCS-7050SX3-48YC8", "JPE12345678")),
    ("juniper_junos", [s.JUNOS_VERSION, s.JUNOS_HARDWARE],
     ("22.4R3-S2.11", "EX4400-48P", "XN1234567890")),
    ("juniper_junos", [s.JUNOS_VERSION_OLD, fs.INVALID], ("19.4R3-S9.4", "SRX345", None)),
    ("fortinet_fortios", [s.FORTIOS_STATUS], ("7.2.5", "FortiGate-60F", "FGT60FTK2209ABCD")),
    ("paloalto_panos", [s.PANOS_INFO, s.PANOS_HA_ACTIVE], ("10.2.7-h3", "PA-3420", "012345678901")),
    ("checkpoint_gaia", [s.GAIA_VERSION, s.GAIA_ASSET, s.GAIA_CLUSTER],
     ("R81.20", "QM-6600", "1234AB5678")),
    ("aruba_aoscx", [s.AOSCX_VERSION, s.AOSCX_SYSTEM], ("FL.10.10.1010", "JL658A", "SG12KLM34N")),
    ("aruba_osswitch", [s.OSSWITCH_VERSION, s.OSSWITCH_SYSTEM, s.OSSWITCH_MODULES],
     ("WC.16.11.0012", "JL320A", "SG9ZKMX123")),
    ("aruba_aos8", [s.AOS8_VERSION, s.AOS8_INVENTORY], ("8.10.0.7", "Aruba7210", "CW0001234")),
    ("dell_os10", [s.OS10_VERSION, s.OS10_INVENTORY], ("10.5.5.5", "S5248F-ON", "9531XC2")),
    ("extreme_exos", [s.EXOS_VERSION, s.EXOS_SWITCH], ("31.7.1.4", "X465-48W", "1928G-12345")),
    ("mikrotik_routeros", [s.ROUTEROS_RESOURCE, s.ROUTEROS_ROUTERBOARD],
     ("7.12.1", "CCR2004-1G-12S+2XS", "HCQ08ABCDEF")),
    ("ubiquiti_edgeos", [s.EDGEOS_VERSION], ("2.0.9-hotfix.7", "EdgeRouter 4", "7483C2ABCDEF")),
    ("huawei_vrp", [s.VRP_VERSION, s.VRP_ESN],
     ("V200R021C10SPC600", "S5735-L48T4X-A1", "2102351931P0LB000123")),
    ("cisco_xr", [s.XR_VERSION, s.XR_INVENTORY], ("7.9.2", "ASR-9901", "FOC2200ABCD")),
    ("cisco_smb", [s.SMB_VERSION, s.SMB_INVENTORY], ("3.3.0.16", "CBS350-24P-4G-EU", "PSZ24321ABC")),
])
def test_version_model_serial(platform, outputs, expected):
    f = parse_facts(platform, outputs)
    assert (f.version, f.model, f.serial) == expected


def test_extra_details():
    eos = parse_facts("arista_eos", [s.EOS_VERSION, s.EOS_DIR])
    assert (eos.flash_total, eos.flash_free) == (3957301248, 1916573028)
    assert parse_facts("fortinet_fortios", [s.FORTIOS_STATUS]).ha_role == "a-p, primary"
    assert parse_facts("paloalto_panos", [s.PANOS_INFO, s.PANOS_HA_ACTIVE]).ha_role == "active"
    assert parse_facts("paloalto_panos", [s.PANOS_INFO, "HA not enabled\n"]).ha_role == "standalone"
    assert parse_facts("checkpoint_gaia", [s.GAIA_VERSION, s.GAIA_ASSET, s.GAIA_CLUSTER]).ha_role == "active"
    mt = parse_facts("mikrotik_routeros", [s.ROUTEROS_RESOURCE, s.ROUTEROS_ROUTERBOARD])
    assert (mt.flash_free, mt.flash_total) == (1036 * 1024 ** 2, 1152 * 1024 ** 2)
    assert parse_facts("aruba_aoscx", [s.AOSCX_VERSION, ""]).image == "primary"
    assert parse_facts("extreme_exos", [s.EXOS_VERSION, s.EXOS_SWITCH]).image == "primary"


def test_version_rejected_or_missing():
    with pytest.raises(ValueError):
        parse_facts("huawei_vrp", ["Error: Unrecognized command found at '^' position.\n"])
    with pytest.raises(ValueError):
        parse_facts("arista_eos", ["nothing useful here\n"])


@pytest.mark.parametrize("older, newer", [
    ("4.29.2F", "4.30.1F"),  # Arista
    ("21.4R3-S5.4", "22.4R3-S2.11"),  # Junos
    ("22.4R3-S2.11", "22.4R3-S3.4"),
    ("10.2.7-h3", "10.2.8"),  # PAN-OS
    ("V200R021C10SPC600", "V200R022C00SPC500"),  # Huawei
    ("FL.10.10.1010", "FL.10.13.1000"),  # AOS-CX
    ("WC.16.10.0009", "WC.16.11.0012"),  # ArubaOS-Switch
    ("R81.10", "R81.20"),  # Check Point
])
def test_vendor_versions_compare(older, newer):
    assert compare_versions(older, newer) == -1 and compare_versions(newer, older) == 1


# --- circuit locations ------------------------------------------------------------

def _macs(platform, out):
    return [(e.mac, e.vlan, e.port_norm) for e in live.mac_table_parser(platform)(out)]


@pytest.mark.parametrize("platform, out, expected", [
    ("arista_eos", s.EOS_MAC, [("00:50:56:a1:00:01", "10", "eth5"), ("00:50:56:a1:00:02", "10", "po10")]),
    ("juniper_junos", s.JUNOS_MAC, [("00:50:56:a1:00:01", "users", "ge-0/0/5"),
                                    ("00:50:56:a1:00:02", "users", "ae0"),
                                    ("00:04:f2:aa:00:01", "voice", "ge-0/0/5")]),
    ("aruba_aoscx", s.AOSCX_MAC, [("00:50:56:a1:00:01", "10", "1/1/5"), ("00:50:56:a1:00:02", "10", "lag1")]),
    ("aruba_osswitch", s.OSSWITCH_MAC, [("00:50:56:a1:00:01", "10", "5"), ("00:50:56:a1:00:02", "10", "trk1")]),
    ("dell_os10", s.OS10_MAC, [("00:50:56:a1:00:01", "1", "eth1/1/5"), ("00:50:56:a1:00:02", "10", "po10")]),
    ("extreme_exos", s.EXOS_FDB, [("00:50:56:a1:00:01", "10", "5"), ("00:50:56:a1:00:02", "10", "49")]),
    ("cisco_smb", s.SMB_MAC, [("00:50:56:a1:00:01", "1", "gi5"), ("00:50:56:a1:00:02", "10", "po1")]),
    ("mikrotik_routeros", s.ROUTEROS_HOSTS, [("00:50:56:a1:00:01", "10", "ether5"),
                                             ("00:50:56:a1:00:02", "10", "ether1")]),
    ("huawei_vrp", s.VRP_MAC, [("00:50:56:a1:00:01", "10", "gi0/0/5"),
                               ("00:50:56:a1:00:02", "10", "eth-trunk1")]),
])
def test_mac_tables(platform, out, expected):
    assert _macs(platform, out) == expected


@pytest.mark.parametrize("out", [s.EOS_ARP, s.JUNOS_ARP, s.AOSCX_ARP, s.OSSWITCH_ARP, s.EXOS_IPARP,
                                 s.ROUTEROS_ARP, s.VRP_ARP, s.FORTIOS_ARP, s.PANOS_ARP])
def test_vendor_arp(out):
    assert live.parse_arp(out) == [("10.10.0.6", "00:50:56:a1:00:02")]


@pytest.mark.parametrize("key, out, uplinks", [
    ("lldp", s.EOS_LLDP, {"eth49/1"}),  # the phone on Ethernet5 isn't an uplink
    ("lldp", s.AOSCX_LLDP, {"1/1/49"}),  # nor the access point on 1/1/7
    ("lldp", s.OSSWITCH_LLDP, {"25"}),
    ("lldp", s.OS10_LLDP, {"eth1/1/49"}),
    ("lldp", s.EXOS_LLDP, {"49"}),
    ("lldp", s.VRP_LLDP, {"gi0/0/24"}),
    ("lldp_table", s.JUNOS_LLDP, {"ge-0/0/47", "xe-0/2/0"}),
    ("lldp_table", s.SMB_LLDP, {"gi1/0/49"}),
    ("mt_neighbor", s.ROUTEROS_NEIGHBORS, {"ether1"}),
])
def test_vendor_uplinks(key, out, uplinks):
    assert live.read_device({key: out}).uplinks == uplinks


@pytest.mark.parametrize("platform, mac_out, nbr_key, nbr_out, edge_port", [
    ("arista_eos", s.EOS_MAC, "lldp", s.EOS_LLDP, "Et5"),
    ("juniper_junos", s.JUNOS_MAC, "lldp_table", s.JUNOS_LLDP, "ge-0/0/5.0"),
    ("aruba_aoscx", s.AOSCX_MAC, "lldp", s.AOSCX_LLDP, "1/1/5"),
    ("huawei_vrp", s.VRP_MAC, "lldp", s.VRP_LLDP, "GE0/0/5"),
    ("mikrotik_routeros", s.ROUTEROS_HOSTS, "mt_neighbor", s.ROUTEROS_NEIGHBORS, "ether5"),
])
def test_read_device_keeps_edge_ports_only(platform, mac_out, nbr_key, nbr_out, edge_port):
    r = live.read_device({"mac": mac_out, nbr_key: nbr_out}, platform)
    assert "00:50:56:a1:00:01" in {e.mac for e in r.edge}
    assert {e.port for e in r.edge if e.mac == "00:50:56:a1:00:01"} == {edge_port}
    # learned on the LAG or the uplink: not where the device is
    assert "00:50:56:a1:00:02" not in {e.mac for e in r.edge}


def test_awplus_ports_are_not_port_channels():
    # "port1.0.1" starts with "po" but is an ordinary AlliedWare Plus port.
    r = live.read_device({"mac": fs.AWPLUS_MAC_TABLE}, "allied_awplus")
    assert [e.port for e in r.edge] == ["port1.0.1", "port1.0.24"]
    for agg in ("po1", "sa2", "ae0", "lag1", "trk1", "bond1", "eth-trunk1", "port-channel10"):
        assert live._is_aggregate(agg), agg


@pytest.mark.parametrize("raw, norm", [
    ("Et5", "eth5"), ("Ethernet5", "eth5"), ("ethernet1/1/5", "eth1/1/5"),
    ("ge-0/0/5.0", "ge-0/0/5"), ("ge-0/0/5", "ge-0/0/5"), ("ae0.0", "ae0"),
    ("GE0/0/5", "gi0/0/5"), ("GigabitEthernet0/0/5", "gi0/0/5"), ("XGE0/0/1", "xge0/0/1"),
    ("XGigabitEthernet0/0/1", "xge0/0/1"), ("1/1/5", "1/1/5"), ("Trk1", "trk1"),
])
def test_vendor_port_names(raw, norm):
    assert normalize_port(raw) == norm
