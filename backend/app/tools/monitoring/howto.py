"""Suggested SNMP configs per platform (the Monitoring page's Help button and
docs/monitoring.md). ``{server}`` is replaced with this server's address.

Each one sets up a read-only SNMPv3 user with authentication and encryption (SHA and AES),
allowed to read everything but change nothing, and where the platform can, only from this
server. ``v2c`` is the fallback for devices that can't do SNMPv3: read-only community,
limited to this server. Check the commands against your release before use: they are a
starting point, not tested on every version.
"""

USER = "netops-mon"

GENERAL = [
    "Use SNMPv3 with authentication and encryption (SHA and AES). SNMPv2c sends the "
    "community in clear text: use it only where a device can't do v3.",
    "Read-only. The monitoring never changes anything on a device, so never give it write access.",
    "Let only this server poll the device (an access list), and allow UDP 161 from this server "
    "through any firewall in between.",
    "Use the same user and passwords on every device of a kind, so one SNMP profile covers them "
    "all. Passwords at least 8 characters (12 or more is better).",
    "Replace <AUTH-PASSWORD>, <PRIV-PASSWORD> and <COMMUNITY> with your own, and put the same "
    "values in an SNMP profile on this page.",
]

HOWTO: list[dict] = [
    {"platform": "cisco_ios", "title": "Cisco IOS / IOS-XE", "kind": "cli", "text": f"""\
configure terminal
 ip access-list standard NETOPS-SNMP
  permit host {{server}}
 exit
 snmp-server view NETOPS-RO iso included
 snmp-server group NETOPS-RO v3 priv read NETOPS-RO access NETOPS-SNMP
 snmp-server user {USER} NETOPS-RO v3 auth sha <AUTH-PASSWORD> priv aes 128 <PRIV-PASSWORD>
 snmp-server ifindex persist                ! interface numbers stay the same after a reload
end
write memory""", "v2c": """\
 snmp-server community <COMMUNITY> RO NETOPS-SNMP""",
     "notes": "The user isn't shown in the running config. Check with: show snmp user. "
              "In SNMP profiles choose SHA and AES."},
    {"platform": "cisco_nxos", "title": "Cisco NX-OS", "kind": "cli", "text": f"""\
configure terminal
 ip access-list NETOPS-SNMP
  permit udp {{server}}/32 any
 exit
 snmp-server user {USER} network-operator auth sha <AUTH-PASSWORD> priv aes-128 <PRIV-PASSWORD>
 snmp-server user {USER} use-ipv4acl NETOPS-SNMP
end
copy running-config startup-config""", "v2c": """\
 snmp-server community <COMMUNITY> group network-operator
 snmp-server community <COMMUNITY> use-ipv4acl NETOPS-SNMP""",
     "notes": "network-operator is the read-only role. Check with: show snmp user"},
    {"platform": "cisco_asa", "title": "Cisco ASA", "kind": "cli", "text": f"""\
configure terminal
 snmp-server group NETOPS-RO v3 priv
 snmp-server user {USER} NETOPS-RO v3 auth sha <AUTH-PASSWORD> priv aes 128 <PRIV-PASSWORD>
 snmp-server host management {{server}} version 3 {USER} poll   ! the interface that reaches the server
 snmp-server enable
end
write memory""", "v2c": """\
 snmp-server host management {server} community <COMMUNITY> version 2c poll""",
     "notes": "The ASA only answers the hosts listed with 'snmp-server host ... poll'. "
              "ASA SNMP is always read-only."},
    {"platform": "cisco_ftd", "title": "Cisco FTD (managed by FDM)", "kind": "gui", "text": f"""\
FDM has no SNMP page: set it with the FDM REST API (API Explorer), or FlexConfig on
older releases:
1. SNMPUser: name {USER}, security level PRIV, authentication SHA <AUTH-PASSWORD>,
   encryption AES128 <PRIV-PASSWORD>.
2. SNMPHost: address {{server}}, the interface that reaches it, the user above,
   poll on, traps off.
3. Deploy the changes.""", "v2c": "",
     "notes": "Check the SNMP section of the FDM configuration guide for your release."},
    {"platform": "cisco_xr", "title": "Cisco IOS-XR", "kind": "cli", "text": f"""\
configure
 ipv4 access-list NETOPS-SNMP
  10 permit ipv4 host {{server}} any
 exit
 snmp-server view NETOPS-RO iso included
 snmp-server group NETOPS-RO v3 priv read NETOPS-RO IPv4 NETOPS-SNMP
 snmp-server user {USER} NETOPS-RO v3 auth sha <AUTH-PASSWORD> priv aes 128 <PRIV-PASSWORD>
 snmp-server ifindex persist
commit""", "v2c": """\
 snmp-server community <COMMUNITY> RO IPv4 NETOPS-SNMP""",
     "notes": "Add 'snmp-server vrf <name>' if the server is reached through a management VRF."},
    {"platform": "cisco_smb", "title": "Cisco Catalyst 1200/1300, CBS, SG", "kind": "cli", "text": f"""\
configure terminal
 snmp-server server
 snmp-server view NETOPS-RO iso included
 snmp-server group NETOPS-RO v3 priv read NETOPS-RO
 snmp-server user {USER} NETOPS-RO v3 auth sha <AUTH-PASSWORD> priv <PRIV-PASSWORD>
end
write memory""", "v2c": """\
 snmp-server community <COMMUNITY> ro {server}""",
     "notes": "Or in the web page: SNMP > Views, Groups and Users. Older SG models encrypt "
              "with DES only: choose DES in the SNMP profile for those."},
    {"platform": "allied_awplus", "title": "Allied Telesis AlliedWare Plus", "kind": "cli", "text": f"""\
configure terminal
 snmp-server
 snmp-server view NETOPS-RO 1 included
 snmp-server group NETOPS-RO priv read NETOPS-RO
 snmp-server user {USER} NETOPS-RO auth sha <AUTH-PASSWORD> priv aes <PRIV-PASSWORD>
end
write memory""", "v2c": """\
 access-list 10 permit {server} 0.0.0.0
 snmp-server community <COMMUNITY> ro 10""",
     "notes": "Check with: show snmp-server user"},
    {"platform": "arista_eos", "title": "Arista EOS", "kind": "cli", "text": f"""\
configure
 ip access-list standard NETOPS-SNMP
  permit host {{server}}
 exit
 snmp-server view NETOPS-RO iso included
 snmp-server group NETOPS-RO v3 priv read NETOPS-RO
 snmp-server user {USER} NETOPS-RO v3 auth sha <AUTH-PASSWORD> priv aes <PRIV-PASSWORD>
 snmp-server ipv4 access-list NETOPS-SNMP   ! add  vrf MGMT  if management is in a VRF
 snmp-server vrf MGMT                       ! only if management is in a VRF
end
write memory""", "v2c": """\
 snmp-server community <COMMUNITY> ro NETOPS-SNMP""",
     "notes": "Check with: show snmp user"},
    {"platform": "juniper_junos", "title": "Juniper Junos (EX, QFX, MX, SRX)", "kind": "cli", "text": f"""\
configure
set snmp view NETOPS-RO oid .1 include
set snmp v3 usm local-engine user {USER} authentication-sha authentication-password "<AUTH-PASSWORD>"
set snmp v3 usm local-engine user {USER} privacy-aes128 privacy-password "<PRIV-PASSWORD>"
set snmp v3 vacm security-to-group security-model usm security-name {USER} group NETOPS-RO
set snmp v3 vacm access group NETOPS-RO default-context-prefix security-model usm security-level privacy read-view NETOPS-RO
commit and-quit""", "v2c": """\
set snmp community <COMMUNITY> authorization read-only clients {server}/32""",
     "notes": "SNMPv3 has no client list in Junos: limit who reaches UDP 161 with the "
              "loopback (lo0) firewall filter."},
    {"platform": "fortinet_fortios", "title": "Fortinet FortiGate", "kind": "cli", "text": f"""\
config system snmp sysinfo
    set status enable
end
config system snmp user
    edit "{USER}"
        set queries enable
        set security-level auth-priv
        set auth-proto sha
        set auth-pwd <AUTH-PASSWORD>
        set priv-proto aes
        set priv-pwd <PRIV-PASSWORD>
    next
end
config system interface
    edit "mgmt"                             # the interface the server polls
        append allowaccess snmp
    next
end""", "v2c": """\
config system snmp community
    edit 1
        set name "<COMMUNITY>"
        config hosts
            edit 1
                set ip {server} 255.255.255.255
            next
        end
    next
end""", "notes": "Limit who may reach the interface with a local-in policy or trusted hosts."},
    {"platform": "paloalto_panos", "title": "Palo Alto PAN-OS", "kind": "gui", "text": f"""\
1. Device > Setup > Operations > SNMP Setup: Version V3.
   Views: add NETOPS-RO, OID 1.3.6.1, Include, Mask 0xf0.
   Users: add {USER}, View NETOPS-RO, Authpwd <AUTH-PASSWORD> (SHA),
   Privpwd <PRIV-PASSWORD> (AES).
2. Device > Setup > Interfaces > Management: tick SNMP, and add {{server}}
   under Permitted IP Addresses.
3. Commit.""", "v2c": """\
Device > Setup > Operations > SNMP Setup: Version V2c, SNMP Community String <COMMUNITY>.""",
     "notes": "In the SNMP profile choose SHA and AES."},
    {"platform": "checkpoint_gaia", "title": "Check Point Gaia", "kind": "cli", "text": f"""\
clish
set snmp agent on
set snmp agent-version v3-Only
add snmp usm user {USER} security-level authPriv auth-pass-type SHA1 auth-pass-phrase <AUTH-PASSWORD> privacy-pass-type AES-128 privacy-pass-phrase <PRIV-PASSWORD>
save config""", "v2c": """\
set snmp agent-version any
set snmp community <COMMUNITY> read-only""",
     "notes": "Allow SNMP from this server in the gateway's policy (or the management "
              "interface's host access)."},
    {"platform": "aruba_aoscx", "title": "HPE Aruba AOS-CX", "kind": "cli", "text": f"""\
configure terminal
 snmp-server vrf mgmt
 snmpv3 user {USER} auth sha auth-pass plaintext <AUTH-PASSWORD> priv aes priv-pass plaintext <PRIV-PASSWORD>
end
write memory""", "v2c": """\
 snmp-server community <COMMUNITY>
  access-level ro""",
     "notes": "Use 'snmp-server vrf default' if the server is reached through the data ports. "
              "Limit who reaches UDP 161 with a control-plane access list."},
    {"platform": "aruba_osswitch", "title": "HPE ArubaOS-Switch (ProCurve)", "kind": "cli", "text": f"""\
configure
 snmpv3 enable                              ! asks for an initial user the first time
 snmpv3 user {USER} auth sha <AUTH-PASSWORD> priv aes <PRIV-PASSWORD>
 snmpv3 group operatorauth user {USER} sec-model ver3
end
write memory""", "v2c": """\
 snmp-server community "<COMMUNITY>" operator restricted""",
     "notes": "operatorauth is read-only. Don't use 'ip authorized-managers' just for SNMP: "
              "it also limits SSH and the web page."},
    {"platform": "aruba_aos8", "title": "HPE Aruba Mobility Controller (AOS 8)", "kind": "cli", "text": f"""\
configure terminal
 snmp-server user {USER} auth-prot sha <AUTH-PASSWORD> priv-prot AES <PRIV-PASSWORD>
end
write memory""", "v2c": """\
 snmp-server community <COMMUNITY>""",
     "notes": "On a Conductor, configure it at the level (/md) of the controllers."},
    {"platform": "dell_os10", "title": "Dell SmartFabric OS10", "kind": "cli", "text": f"""\
configure terminal
 snmp-server view NETOPS-RO 1.3.6.1 included
 snmp-server group NETOPS-RO 3 priv read NETOPS-RO
 snmp-server user {USER} NETOPS-RO 3 auth sha <AUTH-PASSWORD> priv aes <PRIV-PASSWORD>
 snmp-server vrf management                 ! leave out if polled through the data ports
end
write memory""", "v2c": """\
 snmp-server community <COMMUNITY> ro""",
     "notes": "Check with: show snmp user"},
    {"platform": "extreme_exos", "title": "Extreme EXOS / Switch Engine", "kind": "cli", "text": f"""\
configure snmpv3 add user {USER} authentication sha <AUTH-PASSWORD> privacy aes <PRIV-PASSWORD>
configure snmpv3 add group NETOPS-RO user {USER} sec-model usm
configure snmpv3 add access NETOPS-RO sec-model usm sec-level priv read-view defaultUserView
enable snmp access snmpv3
save configuration""", "v2c": """\
configure snmp add community readonly <COMMUNITY>
enable snmp access snmp-v1v2c""",
     "notes": "Limit who may poll with 'configure snmp access-profile'."},
    {"platform": "mikrotik_routeros", "title": "MikroTik RouterOS", "kind": "cli", "text": f"""\
/snmp community add name={USER} security=private addresses={{server}}/32 \\
    authentication-protocol=SHA1 authentication-password=<AUTH-PASSWORD> \\
    encryption-protocol=AES encryption-password=<PRIV-PASSWORD> \\
    read-access=yes write-access=no
/snmp set enabled=yes""", "v2c": """\
/snmp community add name=<COMMUNITY> addresses={server}/32 read-access=yes write-access=no""",
     "notes": "In RouterOS an SNMPv3 user is a 'community' with security=private."},
    {"platform": "ubiquiti_edgeos", "title": "Ubiquiti EdgeRouter (EdgeOS)", "kind": "cli", "text": f"""\
configure
set service snmp v3 view NETOPS-RO oid 1
set service snmp v3 group NETOPS-RO view NETOPS-RO
set service snmp v3 group NETOPS-RO mode ro
set service snmp v3 user {USER} group NETOPS-RO
set service snmp v3 user {USER} auth type sha
set service snmp v3 user {USER} auth plaintext-password <AUTH-PASSWORD>
set service snmp v3 user {USER} privacy type aes
set service snmp v3 user {USER} privacy plaintext-password <PRIV-PASSWORD>
commit
save
exit""", "v2c": """\
set service snmp community <COMMUNITY> authorization ro
set service snmp community <COMMUNITY> client {server}""", "notes": ""},
    {"platform": "huawei_vrp", "title": "Huawei VRP (S, CloudEngine, AR)", "kind": "cli", "text": f"""\
system-view
 acl 2001
  rule permit source {{server}} 0
  quit
 snmp-agent
 snmp-agent sys-info version v3
 snmp-agent mib-view included NETOPS-RO iso
 snmp-agent group v3 NETOPS-RO privacy read-view NETOPS-RO acl 2001
 snmp-agent usm-user v3 {USER} group NETOPS-RO
 snmp-agent usm-user v3 {USER} authentication-mode sha      # asks for <AUTH-PASSWORD>
 snmp-agent usm-user v3 {USER} privacy-mode aes128          # asks for <PRIV-PASSWORD>
 quit
save""", "v2c": """\
 snmp-agent sys-info version v2c v3
 snmp-agent community read cipher <COMMUNITY> acl 2001""",
     "notes": "Check with: display snmp-agent usm-user"},
    {"platform": "snmp_ups", "title": "UPS network card (APC/Schneider NMC, Eaton Network-M2, Vertiv)", "kind": "gui", "text": f"""\
In the card's web page (menu names from APC's Network Management Card 2/3; Eaton and
Vertiv cards have the same settings under Network or SNMP):
1. Configuration > Network > SNMPv3 > Access: enable SNMPv3.
2. SNMPv3 > User Profiles: a profile named {USER}, authentication SHA <AUTH-PASSWORD>,
   privacy AES <PRIV-PASSWORD>.
3. SNMPv3 > Access Control: the {USER} profile, NMS IP/Host Name {{server}}, access enabled.
4. SNMPv1 (if you use v2c instead): disable it, or allow only {{server}} with read access.""",
     "v2c": """\
Configuration > Network > SNMPv1 > Access Control: community <COMMUNITY>,
NMS IP {server}, access type Read.""",
     "notes": "UPS-MIB (RFC 1628) and the vendor's MIB (APC PowerNet-MIB, Eaton XUPS-MIB) give the "
              "battery, load and on-battery status: add them as sensors (Monitoring > Sensors, "
              "examples under UPS). Older cards may offer only SHA-1/DES or v1: update the card's firmware."},
    {"platform": "snmp_pdu", "title": "PDU network card (APC/Schneider, Raritan, ServerTech, Eaton)", "kind": "gui", "text": f"""\
In the PDU's web page:
1. SNMP or Network > SNMP: enable SNMPv3, read only (leave SNMPv1 off).
2. Add a user {USER}: authentication SHA <AUTH-PASSWORD>, privacy AES <PRIV-PASSWORD>,
   read only.
3. Allow only this server, {{server}}, where the card has an access list.""",
     "v2c": """\
SNMPv1/v2c: a read-only community <COMMUNITY>, allowed only from {server}.""",
     "notes": "Load per outlet bank and per phase is in the vendor's MIB (APC PowerNet-MIB rPDU2, "
              "Raritan PDU2-MIB, Sentry4-MIB): add the values you want as sensors."},
    {"platform": "snmp_env", "title": "Environment probe (APC NetBotz, AKCP, Geist, HWg)", "kind": "gui", "text": f"""\
In the probe's web page:
1. SNMP settings: enable SNMPv3, user {USER}, authentication SHA <AUTH-PASSWORD>,
   privacy AES <PRIV-PASSWORD>, read only.
2. Allow only this server, {{server}}, where the probe has an access list.""",
     "v2c": """\
A read-only community <COMMUNITY>, allowed only from {server}.""",
     "notes": "Temperature and humidity are in the vendor's MIB: add them as sensors with warning "
              "and critical levels (Monitoring > Sensors, example: Room temperature)."},
    {"platform": "snmp_other", "title": "Other SNMP devices", "kind": "gui", "text": f"""\
In the device's web page or console:
1. Enable SNMPv3 with a read-only user {USER}: authentication SHA <AUTH-PASSWORD>,
   privacy AES <PRIV-PASSWORD>.
2. Allow only this server, {{server}}, to read it.
3. Leave SNMP SET (changes) and traps off.""",
     "v2c": """\
A read-only community <COMMUNITY>, allowed only from {server}.""",
     "notes": "Ping, uptime, interfaces and the standard health MIBs are read if the device has "
              "them; anything else in its MIB can be added as a sensor."},
    {"platform": "", "title": "Linux and others (net-snmp)", "kind": "cli", "text": f"""\
# apt install snmpd
systemctl stop snmpd
net-snmp-create-v3-user -ro -a SHA -A '<AUTH-PASSWORD>' -x AES -X '<PRIV-PASSWORD>' {USER}
# /etc/snmp/snmpd.conf: listen on the management address, e.g.
#   agentAddress udp:10.0.0.5:161
systemctl start snmpd""", "v2c": """\
# /etc/snmp/snmpd.conf
rocommunity <COMMUNITY> {server}""", "notes": "Allow UDP 161 from this server in the host's firewall."},
]
