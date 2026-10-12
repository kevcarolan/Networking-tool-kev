"""Syslog messages for the demo: three days of history across the demo devices, then a
new message every few seconds, so the Syslog page's filters, counts and timeline have
something real to show.

Each message is written the way that platform writes it (Cisco %CODES, Junos daemons,
MikroTik topics, ...) and goes through the real parser. A few incidents run through the
background noise:

* the night before last: BGP between dc1-spine1 and dc1-leaf3 drops (hold timer expired),
  the uplink flaps, and both come back two minutes later;
* yesterday afternoon: a power supply fails on hq-core1 and the vPC keepalive is lost;
* this morning: someone tries passwords on hq-fw1 and dc1-spine2 from 203.0.113.66;
* two hours ago: BPDU guard shuts a user port on hq-acc-sw3 (someone plugged in a switch);
* a VPN tunnel on bn-rtr1 keeps failing to come up;
* a wireless access point (192.0.2.250) that isn't in the inventory sends messages too.
"""

import random
import threading
import time

from app.demo import seed
from app.tools.syslog.parse import parse
from app.tools.syslog.receiver import Receiver
from app.tools.syslog.store import Record, SyslogStore

UNKNOWN_AP = "192.0.2.250"
_MON = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _stamp(ts: float) -> str:
    t = time.gmtime(ts)
    return f"{_MON[t.tm_mon - 1]} {t.tm_mday:2d} {t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d}"


def _line(platform: str, name: str, sev: int, code: str, text: str, ts: float, seq: int) -> str:
    """One message as the platform sends it (facility local7 unless the platform differs)."""
    t = _stamp(ts)
    if platform == "cisco_ios":
        return f"<{184 + sev}>{seq}: {name}: {t}.{int(ts * 1000) % 1000:03d} UTC: %{code}: {text}"
    if platform == "cisco_nxos":
        y = time.gmtime(ts).tm_year
        return f"<{184 + sev}>: {y} {t} UTC: %{code}: {text}"
    if platform == "cisco_asa":
        y = time.gmtime(ts).tm_year
        return f"<{160 + sev}>{t[:6]} {y} {t[7:]}: %ASA-{sev}-{code}: {text}"
    if platform == "arista_eos":
        return f"<{184 + sev}>{t} {name} {code.split(':')[0]}: %{code.split(':')[1]}: {text}"
    if platform == "juniper_junos":
        return f"<{24 + sev}>{t} {name} {code}: {text}"  # facility daemon
    if platform == "aruba_osswitch":
        return f"<{184 + sev}>{t} {name} {code}: {text}"
    if platform == "mikrotik_routeros":
        return f"<{24 + sev}>{t} {name} {code}: {text}"
    if platform == "allied_awplus":
        return f"<{184 + sev}>{t} {name} {code}: {text}"
    if platform == "dell_os10":
        return f"<{184 + sev}>{t} {name} dn_alm[1203]: Node.1-Unit.1:PRI [event], Dell EMC (OS10) %{code}: {text}"
    return f"<{184 + sev}>{t} {name} {code}: {text}"


# Everyday messages per platform: (severity, code, text). {p} = a port, {u} = a user,
# {ip} = a client address, {n} = a number.
NOISE = {
    "cisco_ios": [
        (5, "LINEPROTO-5-UPDOWN", "Line protocol on Interface GigabitEthernet1/0/{p}, changed state to down"),
        (3, "LINK-3-UPDOWN", "Interface GigabitEthernet1/0/{p}, changed state to down"),
        (3, "LINK-3-UPDOWN", "Interface GigabitEthernet1/0/{p}, changed state to up"),
        (5, "LINEPROTO-5-UPDOWN", "Line protocol on Interface GigabitEthernet1/0/{p}, changed state to up"),
        (5, "SYS-5-CONFIG_I", "Configured from console by {u} on vty0 ({ip})"),
        (5, "SEC_LOGIN-5-LOGIN_SUCCESS", "Login Success [user: {u}] [Source: {ip}] [localport: 22]"),
        (5, "DOT1X-5-SUCCESS", "Authentication successful for client (0050.56{n:02x}.12ab) on Interface Gi1/0/{p}"),
        (5, "ILPOWER-5-POWER_GRANTED", "Interface Gi1/0/{p}: Power granted"),
        (4, "SW_MATM-4-MACFLAP_NOTIF", "Host 0050.5600.{n:04x} in vlan 40 is flapping between port Gi1/0/{p} and port Gi1/0/48"),
        (4, "CDP-4-NATIVE_VLAN_MISMATCH", "Native VLAN mismatch discovered on GigabitEthernet1/0/48 (1), with hq-core1 Ethernet1/{p} (10)."),
        (6, "DHCP_SNOOPING-6-BINDING", "Added binding for 192.0.2.{n} on Gi1/0/{p} vlan 60"),
    ],
    "cisco_nxos": [
        (5, "ETHPORT-5-IF_UP", "Interface Ethernet1/{p} is up in mode access"),
        (5, "ETHPORT-5-IF_DOWN_LINK_FAILURE", "Interface Ethernet1/{p} is down (Link failure)"),
        (5, "VSHD-5-VSHD_SYSLOG_CONFIG_I", "Configured from vty by {u} on {ip}@pts/0"),
        (5, "HSRP_ENGINE-5-STATECHANGE", "Vlan{n} Grp 1 state Standby -> Active"),
        (6, "AUTHPRIV-6-SYSTEM_MSG", "pam_unix(aaa:session): session opened for user {u}"),
        (4, "ETHPORT-4-IF_SFP_WARNING", "Interface Ethernet1/{p}, Low Rx Power Warning"),
    ],
    "cisco_asa": [
        (6, "302013", "Built inbound TCP connection {n}991 for outside:{ip}/5{n}21 (192.0.2.30/443) to inside:192.0.2.30/443"),
        (6, "302014", "Teardown TCP connection {n}991 for outside:{ip}/5{n}21 to inside:192.0.2.30/443 duration 0:00:{n:02d} bytes 4{n}12 TCP FINs"),
        (4, "106023", 'Deny tcp src outside:{ip}/4{n}11 dst inside:192.0.2.40/3389 by access-group "outside_in" [0x0, 0x0]'),
        (6, "113039", "Group <vpn-users> User <{u}> IP <{ip}> AnyConnect parent session started."),
        (4, "113019", "Group = vpn-users, Username = {u}, IP = {ip}, Session disconnected. Session Type: SSL, Duration: 0h:4{n}m:12s, Reason: User Requested"),
        (5, "111008", "User '{u}' executed the 'write memory' command."),
        (6, "605005", "Login permitted from {ip}/5{n}22 to inside:192.0.2.12/ssh for user \"{u}\""),
    ],
    "arista_eos": [
        (5, "Ebra:LINEPROTO-5-UPDOWN", "Line protocol on Interface Ethernet{p}, changed state to up"),
        (5, "Ebra:LINEPROTO-5-UPDOWN", "Line protocol on Interface Ethernet{p}, changed state to down"),
        (5, "ConfigAgent:SYS-5-CONFIG_I", "Configured from console by {u} on vty3 ({ip})"),
        (4, "Lldp:LLDP-4-NEIGHBOR_NEW", "LLDP neighbor with chassisId 0050.56{n:02x}.4411 and portId \"Ethernet{p}\" added on interface Ethernet{p}"),
        (6, "Aaa:AAA-6-EXEC_CMD", "user {u} with priv-lvl 15 ran command 'show interfaces status'"),
    ],
    "juniper_junos": [
        (4, "mib2d[1801]", "SNMP_TRAP_LINK_DOWN: ifIndex 5{n}, ifAdminStatus up(1), ifOperStatus down(2), ifName xe-0/0/{p}"),
        (6, "mib2d[1801]", "SNMP_TRAP_LINK_UP: ifIndex 5{n}, ifAdminStatus up(1), ifOperStatus up(1), ifName xe-0/0/{p}"),
        (5, "mgd[4410]", "UI_COMMIT: User '{u}' requested 'commit' operation (comment: none)"),
        (6, "sshd[4421]", "Accepted password for {u} from {ip} port 5{n}12 ssh2"),
        (5, "rpd[2101]", "RPD_OSPF_NBRUP: OSPF neighbor 198.51.100.{n} (realm ospf-v2 xe-0/0/{p}.0 area 0.0.0.0) state changed from Loading to Full due to LoadDone"),
    ],
    "aruba_osswitch": [
        (6, "00076 ports", "port {p} is now on-line"),
        (4, "00077 ports", "port {p} is now off-line"),
        (5, "00179 mgr", "SME SSH from {ip} - MANAGER Mode"),
        (4, "00435 ports", "port {p} is Blocked by STP"),
        (6, "00090 lldp", "PVID mismatch on port {p}(VID 1)with peer device port 49(VID 10)"),
    ],
    "mikrotik_routeros": [
        (6, "system,info,account", "user {u} logged in from {ip} via ssh"),
        (6, "interface,info", "ether{p} link up (speed 1G, full duplex)"),
        (4, "interface,warning", "ether{p} link down"),
        (6, "dhcp,info", "dhcp1 assigned 198.51.100.{n} to 4C:5E:0C:{n:02X}:11:22"),
        (5, "system,info", "config changed by {u}"),
    ],
    "allied_awplus": [
        (5, "NSM[1438]", "Port up notification received for port1.0.{p}"),
        (4, "NSM[1438]", "Port down notification received for port1.0.{p}"),
        (5, "IMISH[2533]", "configure terminal (user {u} from {ip})"),
        (6, "SSH[2211]", "Accepted password for {u} from {ip}"),
        (4, "EPSR[1559]", "EPSR ring 1: link on port1.0.24 failed, ring broken"),
    ],
    "dell_os10": [
        (5, "IFM_OSTATE_UP", "Interface operational state is up :ethernet1/1/{p}"),
        (4, "IFM_OSTATE_DN", "Interface operational state is down :ethernet1/1/{p}"),
        (5, "SYS_LOGIN", "User {u} logged in from {ip}"),
        (6, "CFG_CHANGE", "Configuration changed by {u} ({n} lines)"),
    ],
}

USERS = ("jsmith", "akumar", "netops", "mlee", "admin")
CLIENTS = ("192.0.2.10", "192.0.2.11", "198.51.100.20", "198.51.100.21")


def _fill(text: str, rng: random.Random) -> str:
    return text.format(p=rng.randint(1, 48), u=rng.choice(USERS), ip=rng.choice(CLIENTS),
                       n=rng.randint(1, 99))


def _incidents(now: float) -> list[tuple[float, str, int, str, str]]:
    """(time, device, severity, code, text) of the stories above."""
    day = 86400
    out = []
    t = now - 2 * day - (now % day) + 3 * 3600 + 12 * 60  # the night before last, 03:12 UTC
    out += [
        (t, "dc1-spine1", 3, "rpd[2101]", "BGP_IO_ERROR_CLOSE_SESSION: BGP peer 198.51.100.13 (External AS 65013): Hold timer expired"),
        (t + 1, "dc1-spine1", 4, "rpd[2101]", "bgp_peer_mgmt_clear: NOTIFICATION sent to 198.51.100.13 (External AS 65013): code 4 (Hold Timer Expired Error)"),
        (t + 2, "dc1-leaf3", 3, "Rib:BGP-3-NOTIFICATION", "received from neighbor 198.51.100.44 (VRF default AS 65100) 4/0 (Hold Timer Expired Error/Unspecified)"),
        (t + 2, "dc1-leaf3", 5, "Rib:BGP-5-ADJCHANGE", "peer 198.51.100.44 (VRF default AS 65100) old state Established event HoldTimerExpired new state Idle"),
        (t + 3, "dc1-leaf3", 3, "Ebra:LINK-3-UPDOWN", "Interface Ethernet49/1, changed state to down"),
        (t + 4, "dc1-spine1", 4, "mib2d[1801]", "SNMP_TRAP_LINK_DOWN: ifIndex 533, ifAdminStatus up(1), ifOperStatus down(2), ifName et-0/0/3"),
        (t + 95, "dc1-leaf3", 3, "Ebra:LINK-3-UPDOWN", "Interface Ethernet49/1, changed state to up"),
        (t + 96, "dc1-spine1", 6, "mib2d[1801]", "SNMP_TRAP_LINK_UP: ifIndex 533, ifAdminStatus up(1), ifOperStatus up(1), ifName et-0/0/3"),
        (t + 128, "dc1-leaf3", 5, "Rib:BGP-5-ADJCHANGE", "peer 198.51.100.44 (VRF default AS 65100) old state OpenConfirm event Established new state Established"),
        (t + 129, "dc1-spine1", 5, "rpd[2101]", "BGP_PEER_STATE_CHANGED: BGP peer 198.51.100.13 (External AS 65013) changed state from OpenConfirm to Established (event RecvKeepAlive)"),
    ]
    t = now - day - (now % day) + 14 * 3600 + 5 * 60  # yesterday 14:05 UTC
    out += [
        (t, "hq-core1", 2, "PLATFORM-2-PS_FAIL", "Power supply 2 failed or shut down (Serial number QCS2215A0BC)"),
        (t + 1, "hq-core1", 2, "PLATFORM-2-PS_RED_MODE_CHG", "Power supply redundancy mode changed to non-redundant"),
        (t + 40, "hq-core2", 2, "VPC-2-PEER_KEEP_ALIVE_RECV_FAIL", "In domain 10, VPC peer keep-alive receive has failed"),
        (t + 41, "hq-core1", 2, "VPC-2-PEER_KEEP_ALIVE_SEND_FAIL", "In domain 10, VPC peer keep-alive send has failed"),
        (t + 300, "hq-core2", 5, "VPC-5-PEER_KEEP_ALIVE_RECV_SUCCESS", "In domain 10, vPC peer keep-alive receive is successful"),
        (t + 1800, "hq-core1", 5, "PLATFORM-5-PS_OK", "Power supply 2 ok (Serial number QCS2215A0BC)"),
    ]
    t = now - (now % day) + 6 * 3600 + 40 * 60  # today 06:40 UTC (or yesterday's, if earlier)
    if t > now - 600:
        t -= day
    for i in range(18):
        out.append((t + i * 7, "hq-fw1", 6, "605004",
                    f'Login denied from 203.0.113.66/5{i:02d}01 to outside:198.51.100.1/ssh for user "{("admin", "root", "cisco")[i % 3]}"'))
        out.append((t + i * 7 + 3, "dc1-spine2", 4, "sshd[5310]",
                    f"SSHD_LOGIN_FAILED: Login failed for user '{('admin', 'root', 'test')[i % 3]}' from host '203.0.113.66'"))
    out.append((t + 140, "hq-fw1", 4, "106023",
                'Deny tcp src outside:203.0.113.66/51411 dst inside:192.0.2.12/22 by access-group "outside_in" [0x0, 0x0]'))
    t = now - 5 * 3600  # five hours ago: the firewall pair loses its failover link
    out += [
        (t, "hq-fw1", 1, "105006", "(Primary) Link status 'Up' on interface failover-link"),
        (t + 2, "hq-fw1", 1, "105005", "(Primary) Lost Failover communications with mate on interface failover-link"),
        (t + 30, "hq-fw1", 1, "105006", "(Primary) Link status 'Up' on interface failover-link"),
        (t + 600, "wh-sw1", 0, "ALM_TEMP_CRITICAL", "Unit 1 temperature 96C is above the critical limit: shutting down in 60 seconds"),
        (t + 640, "wh-sw1", 1, "ALM_FAN_STATUS", "Fan tray 2 failed"),
        (t + 700, "wh-sw1", 5, "SYS_REBOOT", "System is rebooting (reason: temperature)"),
    ]
    t = now - 2 * 3600  # two hours ago
    out += [
        (t, "hq-acc-sw3", 2, "SPANTREE-2-BLOCK_BPDUGUARD", "Received BPDU on port GigabitEthernet1/0/14 with BPDU Guard enabled. Disabling port."),
        (t + 1, "hq-acc-sw3", 4, "PM-4-ERR_DISABLE", "bpduguard error detected on Gi1/0/14, putting Gi1/0/14 in err-disable state"),
        (t + 2, "hq-acc-sw3", 3, "LINK-3-UPDOWN", "Interface GigabitEthernet1/0/14, changed state to down"),
        (t + 900, "hq-acc-sw3", 5, "SYS-5-CONFIG_I", "Configured from console by mlee on vty0 (192.0.2.10)"),
        (t + 905, "hq-acc-sw3", 3, "LINK-3-UPDOWN", "Interface GigabitEthernet1/0/14, changed state to up"),
    ]
    for k in range(0, 3 * 24, 3):  # every 3 hours for three days
        out.append((now - k * 3600 - 777, "bn-rtr1", 3, "ipsec,error",
                    "phase1 negotiation failed due to time up 198.51.100.1[500]<=>203.0.113.9[500]"))
    return out


def _ap_line(ts: float, rng: random.Random) -> str:
    sev, text = rng.choice([(6, "wlan: client 4c:5e:0c:aa:bb:01 associated on 5GHz"),
                            (4, "wlan: radio 2.4GHz channel changed 6 -> 11 (interference)"),
                            (6, "wlan: client 4c:5e:0c:aa:bb:07 disassociated (inactivity)"),
                            (3, "dhcp: no lease received for client 4c:5e:0c:aa:bb:09")])
    return f"<{8 + sev}>{_stamp(ts)} ap-lobby hostapd: {text}"


def history(now: float | None = None, days: int = 3, per_hour: int = 30,
            seed_value: int = 7) -> list[Record]:
    """The demo's past messages: background noise plus the incidents, oldest first."""
    now = now or time.time()
    rng = random.Random(seed_value)
    by_name = {d.name: (i, d) for i, d in enumerate(seed.DEVICES)}
    lines: list[tuple[float, str, str]] = []  # (time, sender, raw line)
    seq = 1000
    for _ in range(days * 24 * per_hour):
        ts = now - rng.uniform(60, days * 86400)
        i, d = rng.choice(list(by_name.values()))
        sev, code, text = rng.choice(NOISE[d.platform])
        seq += 1
        lines.append((ts, seed.address(i), _line(d.platform, d.name, sev, code, _fill(text, rng), ts, seq)))
    for ts, name, sev, code, text in _incidents(now):
        i, d = by_name[name]
        seq += 1
        lines.append((ts, seed.address(i), _line(d.platform, d.name, sev, code, text, ts, seq)))
    for _ in range(days * 40):
        ts = now - rng.uniform(60, days * 86400)
        lines.append((ts, UNKNOWN_AP, _ap_line(ts, rng)))
    records = []
    for ts, src, raw in sorted(lines):
        m = parse(raw)
        records.append(Record(ts, src, m.severity, m.facility, m.host, m.tag, m.text))
    return records


def start(settings, stop: threading.Event, every: float = 4.0) -> threading.Thread:
    """Fill an empty store with the history, then send a new message every few seconds
    through the real receiver code (so the page's receiver status shows it running)."""
    store = SyslogStore(settings.syslog_dir)
    if not store.days():
        store.write(history())
        store.close()
    receiver = Receiver(settings, store)
    receiver.write_status()  # the page shows the receiver running straight away

    def run():
        rng = random.Random()
        seq = 9000
        while not stop.wait(every):
            seq += 1
            if rng.random() < 0.08:
                receiver.accept(_ap_line(time.time(), rng).encode(), UNKNOWN_AP)
            else:
                i, d = rng.choice(list(enumerate(seed.DEVICES)))
                sev, code, text = rng.choice(NOISE[d.platform])
                raw = _line(d.platform, d.name, sev, code, _fill(text, rng), time.time(), seq)
                receiver.accept(raw.encode(), seed.address(i))
            receiver.flush()
            receiver.write_status()

    thread = threading.Thread(target=run, name="demo-syslog", daemon=True)
    thread.start()
    return thread
