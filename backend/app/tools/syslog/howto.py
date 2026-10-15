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
    {"platform": "snmp_ups", "title": "UPS network card (APC/Schneider NMC, Eaton, Vertiv)", "kind": "gui", "text": """\
In the card's web page: Configuration > Logs > Syslog > Settings (APC NMC; others
under Logging or Notifications):
1. Enable syslog. Server {server}, port 514, protocol UDP.
2. Severity: Informational, so power events (on battery, back on line) are sent.""",
     "notes": "UPS cards send their power events as syslog messages: they appear on the Syslog page."},
    {"platform": "snmp_pdu", "title": "PDU network card", "kind": "gui", "text": """\
In the PDU's web page, Logging or Syslog settings: server {server}, port 514, UDP,
level Informational.""", "notes": ""},
    {"platform": "snmp_env", "title": "Environment probe", "kind": "gui", "text": """\
In the probe's web page, Syslog or Notifications: server {server}, port 514, UDP.""",
     "notes": "Not every probe can send syslog; the sensors on the Monitoring page cover them."},
    {"platform": "snmp_other", "title": "Other SNMP devices", "kind": "gui", "text": """\
In the device's settings, Syslog or Remote logging: server {server}, port 514, UDP,
level Informational.""", "notes": ""},
    {"platform": "", "title": "Linux and others (rsyslog)", "kind": "cli", "text": """\
# /etc/rsyslog.d/90-netops.conf   (then: systemctl restart rsyslog)
*.info @{server}:514""", "notes": "One @ is UDP, @@ is TCP."},
]


# Syslog over TLS (port 6514), for the platforms that can send it. Every device must trust
# the CA that signed the server's certificate, and the certificate must name the address or
# DNS name the device sends to. Platforms without an entry send plain syslog only (or only on
# some releases): keep them on UDP 514 over a trusted network.
TLS_GENERAL = [
    "Syslog over TLS must be switched on on the server first (NETOPS_SYSLOG_TLS_PORT=6514 in "
    "netops.env, and port 6514 allowed in the firewall).",
    "The device checks the server's certificate: load the CA that signed it onto the device, "
    "and send to a name or address that is in the certificate.",
    "Time must be right (NTP), or the certificate check fails.",
]

TLS = {
    "cisco_ios": """\
configure terminal
 crypto pki trustpoint NETOPS-CA
  enrollment terminal
  revocation-check none
 exit
 crypto pki authenticate NETOPS-CA          ! paste the CA certificate (PEM) when asked
 logging host {server} transport tls port 6514
 logging trap informational
end
write memory""",
    "cisco_nxos": """\
configure terminal
 crypto ca trustpoint NETOPS-CA
 crypto ca authenticate NETOPS-CA           ! paste the CA certificate (PEM) when asked
 logging server {server} 6 port 6514 secure use-vrf management
end
copy running-config startup-config""",
    "cisco_asa": """\
configure terminal
 crypto ca trustpoint NETOPS-CA
  enrollment terminal
 crypto ca authenticate NETOPS-CA           ! paste the CA certificate (PEM) when asked
 logging host management {server} tcp/6514 secure
 logging permit-hostdown                    ! keep traffic flowing if the server is down
end
write memory""",
    "juniper_junos": """\
configure
set security pki ca-profile NETOPS-CA ca-identity NETOPS-CA
set security pki trusted-ca-group NETOPS-CAS ca-profiles NETOPS-CA
set system syslog host {server} port 6514 transport tls
set system syslog host {server} tlsdetails trusted-ca-group NETOPS-CAS
set system syslog host {server} any info
commit and-quit
request security pki ca-certificate load ca-profile NETOPS-CA filename /var/tmp/netops-ca.pem""",
    "arista_eos": """\
copy scp:user@host/netops-ca.pem certificate:netops-ca.pem
configure
 management security
  ssl profile NETOPS-SYSLOG
   trust certificate netops-ca.pem
 logging host {server} 6514 protocol tls
 logging ssl-profile NETOPS-SYSLOG
end
write memory""",
    "fortinet_fortios": """\
config log syslogd setting
    set status enable
    set server "{server}"
    set mode reliable
    set port 6514
    set enc-algorithm high
end
# import the CA under System > Certificates > Import > CA Certificate""",
    "paloalto_panos": """\
1. Device > Certificate Management > Certificates > Import: the CA certificate,
   then open it and tick 'Trusted Root CA'.
2. Device > Server Profiles > Syslog > Add: server {server}, transport SSL,
   port 6514, format IETF, facility LOG_USER.
3. Device > Log Settings: add the profile to System and Configuration logs.
4. Commit.""",
    "aruba_aoscx": """\
configure terminal
 crypto pki ta-profile NETOPS-CA
  ta-certificate                            ! paste the CA certificate (PEM), end with END_OF_CERTIFICATE
 exit
 logging {server} tls 6514 severity info vrf mgmt
end
write memory""",
    "": """\
# apt install rsyslog-gnutls; put the CA in /etc/ssl/certs/netops-ca.pem
# /etc/rsyslog.d/90-netops.conf   (then: systemctl restart rsyslog)
global(DefaultNetstreamDriverCAFile="/etc/ssl/certs/netops-ca.pem")
*.info action(type="omfwd" target="{server}" port="6514" protocol="tcp"
              StreamDriver="gtls" StreamDriverMode="1"
              StreamDriverAuthMode="x509/name" StreamDriverPermittedPeers="{server}")""",
}
