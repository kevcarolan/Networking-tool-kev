"""Suggested configs for sending syslog to this server, per platform (the Syslog page's
Help button and docs/syslog.md). ``{server}`` is replaced with the server's address.

Each one sends severity informational and up (debug is too much for a central log), uses
the management interface as the source (so the message matches the device's inventory
address), and adds timestamps. Check the commands against your release before use: they
are a starting point, not tested on every version.
"""

GENERAL = [
    "Send from the management address that is in the inventory (the 'source interface'): "
    "messages from any other address show as an unknown sender.",
    "Use NTP on every device, so the device's own timestamps line up. The page sorts by the "
    "time the server received each message.",
    "Severity informational is a good level. Debug can flood the log.",
    "UDP 514 is the default. Allow the devices in the server's firewall (SYSLOG_SOURCES).",
]

HOWTO: list[dict] = [
    {"platform": "cisco_ios", "title": "Cisco IOS / IOS-XE", "kind": "cli", "text": """\
configure terminal
 service timestamps log datetime msec localtime show-timezone
 logging origin-id hostname
 logging source-interface Vlan10            ! your management interface
 logging host {server}                      ! add  vrf Mgmt-vrf  if management is in a VRF
 logging trap informational
end
write memory""", "notes": "Check with: show logging"},
    {"platform": "cisco_nxos", "title": "Cisco NX-OS", "kind": "cli", "text": """\
configure terminal
 logging server {server} 6 use-vrf management
 logging source-interface mgmt0
 logging timestamp milliseconds
 logging origin-id hostname
end
copy running-config startup-config""", "notes": "6 = informational. Check with: show logging server"},
    {"platform": "cisco_asa", "title": "Cisco ASA", "kind": "cli", "text": """\
configure terminal
 logging enable
 logging timestamp
 logging device-id hostname
 logging trap informational
 logging host management {server}           ! the interface name that reaches the server
end
write memory""", "notes": "Keep UDP. ASA over TCP blocks new connections when the server can't be "
                          "reached, unless 'logging permit-hostdown' is set. Informational includes "
                          "every connection built and torn down, which can be a lot; use "
                          "'logging trap notifications' for a quieter log."},
    {"platform": "cisco_ftd", "title": "Cisco FTD (managed by FDM)", "kind": "gui", "text": """\
1. Objects > Syslog Servers > +: IP address {server}, protocol UDP, port 514,
   reach it through the Management interface (or the data interface that routes to it).
2. Device > System Settings > Logging Settings:
   Remote Server: on, Syslog server: the one above, Severity: Informational.
3. Deploy the changes.""", "notes": "Connection events are sent from each access rule's Logging "
                                    "settings; leave them off unless you need them."},
    {"platform": "cisco_xr", "title": "Cisco IOS-XR", "kind": "cli", "text": """\
configure
 logging {server} vrf default severity info
 logging source-interface MgmtEth0/RP0/CPU0/0
 service timestamps log datetime msec show-timezone
commit""", "notes": "Use the management VRF's name instead of 'default' if it has one."},
    {"platform": "cisco_smb", "title": "Cisco Catalyst 1200/1300, CBS, SG", "kind": "cli", "text": """\
configure terminal
 logging host {server} severity informational
 logging source-interface vlan 1            ! your management VLAN
end
write memory""", "notes": "Or in the web page: Administration > System Log > Remote Log Servers."},
    {"platform": "allied_awplus", "title": "Allied Telesis AlliedWare Plus", "kind": "cli", "text": """\
configure terminal
 log host {server}
 log host {server} level informational
 log host source vlan1                      ! your management interface
end
write memory""", "notes": "Check with: show log config"},
    {"platform": "arista_eos", "title": "Arista EOS", "kind": "cli", "text": """\
configure
 logging host {server}                      ! or: logging vrf MGMT host {server}
 logging source-interface Management1       ! or: logging vrf MGMT source-interface Management1
 logging trap informational
end
write memory""", "notes": "Check with: show logging"},
    {"platform": "juniper_junos", "title": "Juniper Junos (EX, QFX, MX, SRX)", "kind": "cli", "text": """\
configure
set system syslog host {server} any info
set system syslog host {server} interactive-commands any
set system syslog host {server} source-address 10.0.0.1      # the management address
set system syslog time-format millisecond
commit and-quit""", "notes": "On an SRX, firewall session logs are a separate stream "
                              "(security log); leave them off unless you need them."},
    {"platform": "fortinet_fortios", "title": "Fortinet FortiGate", "kind": "cli", "text": """\
config log syslogd setting
    set status enable
    set server "{server}"
    set mode udp
    set port 514
    set facility local7
    set source-ip 10.0.0.1                  # the management address
end
config log syslogd filter
    set severity information
end""", "notes": "Traffic logs follow each policy's logging setting and can be a lot; "
                  "'set forward-traffic disable' in the filter keeps only events."},
    {"platform": "paloalto_panos", "title": "Palo Alto PAN-OS", "kind": "gui", "text": """\
1. Device > Server Profiles > Syslog > Add: name 'netops', server {server},
   transport UDP, port 514, format BSD, facility LOG_USER.
2. Device > Log Settings: add the profile to System and Configuration logs
   (all severities, or informational and up).
3. Device > Setup > Services > Service Route Configuration: send Syslog from the
   management interface (the default).
4. Commit.""", "notes": "Traffic and threat logs are sent through Log Forwarding profiles on the "
                         "security rules; leave them off unless you need them."},
    {"platform": "checkpoint_gaia", "title": "Check Point Gaia", "kind": "cli", "text": """\
clish
add syslog log-remote-address {server} level info
save config""", "notes": "This sends the gateway's own operating-system log. Firewall traffic "
                          "logs are sent from the management server with Log Exporter."},
    {"platform": "aruba_aoscx", "title": "HPE Aruba AOS-CX", "kind": "cli", "text": """\
configure terminal
 logging {server} udp 514 severity info vrf mgmt
end
write memory""", "notes": "Use 'vrf default' if the server is reached through the data ports."},
    {"platform": "aruba_osswitch", "title": "HPE ArubaOS-Switch (ProCurve)", "kind": "cli", "text": """\
configure
 logging {server}
 logging facility local7
 logging severity info
end
write memory""", "notes": "Check with: show debug  (the syslog destination is listed there)"},
    {"platform": "aruba_aos8", "title": "HPE Aruba Mobility Controller (AOS 8)", "kind": "cli", "text": """\
configure terminal
 logging {server} severity informational
 logging level informational system
end
write memory""", "notes": "On a Conductor, configure it at the level (/md) that should send."},
    {"platform": "dell_os10", "title": "Dell SmartFabric OS10", "kind": "cli", "text": """\
configure terminal
 logging server {server} severity log-info vrf management
end
write memory""", "notes": "Leave out 'vrf management' if the server is reached through the data ports."},
    {"platform": "extreme_exos", "title": "Extreme EXOS / Switch Engine", "kind": "cli", "text": """\
configure syslog add {server}:514 vr VR-Mgmt local7
enable log target syslog {server}:514 vr VR-Mgmt local7
configure log target syslog {server}:514 vr VR-Mgmt local7 filter DefaultFilter severity Info
save configuration""", "notes": "Use VR-Default if the server is reached through the data ports."},
    {"platform": "mikrotik_routeros", "title": "MikroTik RouterOS", "kind": "cli", "text": """\
/system logging action add name=netops target=remote remote={server} remote-port=514 bsd-syslog=yes
/system logging add topics=critical action=netops
/system logging add topics=error action=netops
/system logging add topics=warning action=netops
/system logging add topics=info action=netops""", "notes": "Check with: /system logging print"},
    {"platform": "ubiquiti_edgeos", "title": "Ubiquiti EdgeRouter (EdgeOS)", "kind": "cli", "text": """\
configure
set system syslog host {server} facility all level info
commit
save
exit""", "notes": ""},
    {"platform": "huawei_vrp", "title": "Huawei VRP (S, CloudEngine, AR)", "kind": "cli", "text": """\
system-view
 info-center enable
 info-center loghost source Vlanif10        # your management interface
 info-center loghost {server} level informational
 info-center timestamp log date precision-time millisecond
 quit
save""", "notes": "Check with: display info-center"},
    {"platform": "", "title": "Linux and others (rsyslog)", "kind": "cli", "text": """\
# /etc/rsyslog.d/90-netops.conf   (then: systemctl restart rsyslog)
*.info @{server}:514""", "notes": "One @ is UDP, @@ is TCP."},
]
