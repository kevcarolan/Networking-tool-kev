# Monitoring

The **Monitoring** page shows which devices are up, which are down, and which need a look.
The server checks every device in the inventory once a minute:

* **ping** (ICMP echo), for the response time;
* **SNMP** (v2c or v3), for the device's name, description and uptime.

Every 5 minutes it also reads each SNMP device's **interfaces**: status, speed, traffic in
and out, errors and discards.

It is read-only. It only asks (ICMP echo, SNMP GET) and never changes anything on a device.
There is no SNMP SET and no trap receiver: the devices' own messages go to the **Syslog** page.

Health readings (CPU, memory, temperature, fans, power supplies) come in a later release.

## What the statuses mean

| Status | Meaning |
|---|---|
| **Up** | It answers |
| **Warning** | It answers, but something needs a look: SNMP fails (wrong community or user, an access list), it doesn't answer ping but SNMP works, or it missed a check (*1 of 2 before it counts as down*) |
| **Down** | No answer to ping or SNMP for 2 checks in a row (about two minutes; *Settings › Site and defaults*) |
| **Can't check** | Nothing to check it with: ping is off and it has no SNMP profile |
| **Not monitored** | Switched off for this device, or the device is disabled in the inventory |
| **maintenance** (as well) | The device is in a calendar window (change, maintenance or outage, for the device, its site, or every site) or an upgrade job is under way on it. What happens is recorded, but not emailed |

The poller also notes these events:

* when a device went **down** and came back **up**, and for how long;
* when it **restarted** (its SNMP uptime went back near zero);
* when SNMP **stopped** or **started** answering;
* when a **port went down** or came back. This is only for ports with a description set on
  the device (as uplinks and links usually have) and port-channels. Ports without a
  description, usually access ports, come and go all day and aren't events.

The page shows the last 24 hours. Each device's window shows its last 90 days.

## Setting it up

1. **Devices:** set up SNMP on each device. On the Monitoring page, click
   **Help: set up devices**, choose the platform, check the server address, and copy the
   config. Every platform has an SNMPv3 example: a read-only user with SHA authentication
   and AES encryption, only allowed from this server. There is also an SNMPv2c fallback for
   devices that can't do v3. The same examples are in [Platform configs](#platform-configs)
   below.
2. **SNMP profiles:** click **SNMP profiles** › **+ Add profile**. Enter the same user and
   passwords, or community, that you set on the devices, and tick *The default for devices
   without their own*. **Test on this device** asks one device straight away. Profiles need
   the *credentials* level for Devices and credentials, like device passwords. The passwords
   are encrypted and never shown again.
3. **Devices on another profile:** for example, older devices on SNMPv2c. Tick them in the
   list, choose the profile in the bar that appears, and click **Use this SNMP profile**.
   This needs the *addresses* level, because it decides which device a secret is sent to.
4. **The server's firewall** must allow outgoing ping and UDP 161 to the devices
   (`DEVICE_NETS` in `deploy/hardening/nftables.conf`; both rules are in it). Any firewall
   between the server and the devices must allow the same.

Every change appears within a minute.

## Using it

* **The list:** the worst first. Click a tile (Down, Warning…) to show only those. Each row
  shows the response time, how long the device has been up, how many checks it answered in
  the last 7 days, and since when it has been in its status.
* **A device:** click it to open its window:
  * the response-time graph for 6 hours to 1 year. The line is the average, the band is the
    worst, and red marks along the bottom are checks with no answer;
  * how many checks it answered today, over 7 days, 30 days and a year;
  * what it says about itself, and its events.

  People with *manage* can switch it, its ping or its SNMP off here, or choose its profile.
* **A device's interfaces:** under the graph in the device window, every port as last read:
  its description, status (and since when), speed, how full it is (the busier direction),
  traffic in and out, and errors and discards a minute. You can sort it busiest first, errors
  first or down first, and choose to show switched-off ports too. Click a port for its
  traffic graph, from 6 hours to a year. The dashed red line is the port's speed. Errors and
  discards get their own graph when there are any.
* **Busiest ports** and **Ports with errors or discards**, under the list, cover every
  device. Click one for its graph.
* **The network map** (Sites, or the Monitoring page's **Network map** button) colours each
  device: green up, orange warning, red down. Each line shows the load at its busier end:
  green, orange from 50%, red from 80%. Click a line for the traffic at both ends.
* **The wall display** has a *Monitoring* page: counts, who is down and for how long,
  warnings, the last day's events, the busiest ports and the ports with errors. It shows names, sites and times only; never addresses
  or messages. The overview gains a *Devices down* tile, and each site's tile says how many
  of its devices are down.
* **Email alerts:** on *Settings › Email alerts*, give a recipient **Devices down or up**.
  They get one email per check with what went down, came back or restarted, and described
  ports that went down or came back. Anything in a maintenance window is left out.

## Settings

On *Settings › Site and defaults*:

| Setting | Default | |
|---|---|---|
| Check every device every (seconds) | 60 | 30 to 3600 |
| Down after this many checks without an answer | 2 | 1 to 10 |
| Keep every check for (days) | 35 | For the graphs. The daily totals (availability) are kept for a year |
| Read the interfaces every (seconds) | 300 | 60 to 3600 |
| Keep every interface reading for (days) | 7 | 2 to 35. After that, the average and peak of each hour are kept for 13 months |

Only in `netops.env`: `NETOPS_MONITOR_WORKERS` (50), the number of devices checked at the same time.

## How it works

* **Its own service:** `netops-monitor`, running as the `netops` account with no extra
  rights. Ping uses the kernel's ping sockets, which Ubuntu allows for every group
  (`net.ipv4.ping_group_range`). If a server forbids them, the page says so and devices are
  checked with SNMP only.
* **Its own files:** in `/var/lib/netops/monitoring/`, not the main database:
  * `state.db`: each device's state and interfaces, the events and the daily totals;
  * one file per day with every check, for the graphs;
  * `ifd-<day>.db`: every interface reading of that day;
  * `ifh-<month>.db`: interfaces per hour (average and peak);
  * `status.json`: the poller's heartbeat.

  Only the poller writes. The web app reads.
* **Restarts:** the poller carries on where it was after a restart or an upgrade of the
  platform.
* **Size:**
  * checks: about 30 bytes each. 500 devices every minute is about 25 MB a day, so roughly
    1 GB for the 35 days kept;
  * interfaces: about 10 KB per port a day (5 MB a day for 500 ports). 3,000 ports is about
    30 MB a day, so roughly 200 MB for 7 days, plus about 100 MB a month for the hourly figures.
* **Counters:** the 64-bit counters (ifXTable) where the device has them, else the 32-bit
  ones. Those wrap after 4 GB, about 34 seconds at 1 Gb/s, so a fast port without 64-bit
  counters reads too low. A counter that goes backwards after a restart gives no rate for
  that interval. Reading the interfaces needs SNMP; ping alone gives only up and down.
* **The one exception:** the only thing that asks a device from the web app itself is a
  profile's **Test** button, and only for someone allowed to manage SNMP profiles.

## Permissions

The **Monitoring** area on the Users page:

* **none**;
* **view**: see the page, the map colours and the events;
* **manage**: also switch monitoring, ping or SNMP on and off per device.

Users added before monitoring existed get **view**. SNMP profiles follow *Devices and
credentials*:

* **credentials** to add, change or delete them;
* **addresses** to choose a device's profile.

## Licence

Monitoring is its own module in the licence (`monitoring`). Licences made before it existed
list their modules and so don't include it; the trial does.

## Troubleshooting

| What you see | Look at |
|---|---|
| "The monitoring poller isn't running" | `systemctl status netops-monitor`; `journalctl -u netops-monitor -n 50` |
| A device is **down** but works | Ping and UDP 161 from this server: the server's firewall (`DEVICE_NETS`), any firewall between, the device's access lists |
| **Warning: SNMP: No answer (timed out)** | The community or user doesn't match (a wrong v2c community is silently ignored), the device's SNMP access list doesn't allow this server, or UDP 161 is blocked |
| **Warning: wrong SNMPv3 authentication / encryption password** | The profile's passwords or protocols don't match the device. Cisco's AES-192/256 are "AES-192-C"/"AES-256-C" in the profile |
| **Warning: the device doesn't know this SNMPv3 user** | The user isn't set up on the device, or was lost in a reload (some platforms don't save SNMPv3 users in the startup config) |
| **Warning: no reply to ping, but SNMP answers** | A firewall that drops ping: switch ping off for that device |
| A device has no interfaces, or "Can't read the interfaces" | The SNMP view must include IF-MIB (the configs in the help allow everything read-only). Very large tables (thousands of VLAN interfaces) take a while: 1,000 interfaces per device are read, physical ones first |
| A port's traffic looks too low or jumps | 32-bit counters wrapping on a fast port: check that the device answers ifXTable (SNMPv2c or v3, not v1). On Cisco, `snmp-server ifindex persist` keeps port numbers the same after a reload |
| "ping isn't allowed on this server" | `sysctl net.ipv4.ping_group_range` must include the netops group (`0 2147483647`, `deploy/hardening/sysctl-netops.conf`) |

## Platform configs

The page's **Help: set up devices** shows these, with the server address filled in
(`app/tools/monitoring/howto.py`). They are a starting point: check the commands against
your release.

### Cisco IOS / IOS-XE

```
configure terminal
 ip access-list standard NETOPS-SNMP
  permit host <server>
 exit
 snmp-server view NETOPS-RO iso included
 snmp-server group NETOPS-RO v3 priv read NETOPS-RO access NETOPS-SNMP
 snmp-server user netops-mon NETOPS-RO v3 auth sha <AUTH-PASSWORD> priv aes 128 <PRIV-PASSWORD>
 snmp-server ifindex persist                ! interface numbers stay the same after a reload
end
write memory
```

SNMPv2c instead (only if v3 isn't possible):

```
 snmp-server community <COMMUNITY> RO NETOPS-SNMP
```

The user isn't shown in the running config. Check with: show snmp user. In SNMP profiles choose SHA and AES.

### Cisco NX-OS

```
configure terminal
 ip access-list NETOPS-SNMP
  permit udp <server>/32 any
 exit
 snmp-server user netops-mon network-operator auth sha <AUTH-PASSWORD> priv aes-128 <PRIV-PASSWORD>
 snmp-server user netops-mon use-ipv4acl NETOPS-SNMP
end
copy running-config startup-config
```

SNMPv2c instead (only if v3 isn't possible):

```
 snmp-server community <COMMUNITY> group network-operator
 snmp-server community <COMMUNITY> use-ipv4acl NETOPS-SNMP
```

network-operator is the read-only role. Check with: show snmp user

### Cisco ASA

```
configure terminal
 snmp-server group NETOPS-RO v3 priv
 snmp-server user netops-mon NETOPS-RO v3 auth sha <AUTH-PASSWORD> priv aes 128 <PRIV-PASSWORD>
 snmp-server host management <server> version 3 netops-mon poll   ! the interface that reaches the server
 snmp-server enable
end
write memory
```

SNMPv2c instead (only if v3 isn't possible):

```
 snmp-server host management <server> community <COMMUNITY> version 2c poll
```

The ASA only answers the hosts listed with 'snmp-server host ... poll'. ASA SNMP is always read-only.

### Cisco FTD (managed by FDM)

```
FDM has no SNMP page: set it with the FDM REST API (API Explorer), or FlexConfig on
older releases:
1. SNMPUser: name netops-mon, security level PRIV, authentication SHA <AUTH-PASSWORD>,
   encryption AES128 <PRIV-PASSWORD>.
2. SNMPHost: address <server>, the interface that reaches it, the user above,
   poll on, traps off.
3. Deploy the changes.
```

Check the SNMP section of the FDM configuration guide for your release.

### Cisco IOS-XR

```
configure
 ipv4 access-list NETOPS-SNMP
  10 permit ipv4 host <server> any
 exit
 snmp-server view NETOPS-RO iso included
 snmp-server group NETOPS-RO v3 priv read NETOPS-RO IPv4 NETOPS-SNMP
 snmp-server user netops-mon NETOPS-RO v3 auth sha <AUTH-PASSWORD> priv aes 128 <PRIV-PASSWORD>
 snmp-server ifindex persist
commit
```

SNMPv2c instead (only if v3 isn't possible):

```
 snmp-server community <COMMUNITY> RO IPv4 NETOPS-SNMP
```

Add 'snmp-server vrf <name>' if the server is reached through a management VRF.

### Cisco Catalyst 1200/1300, CBS, SG

```
configure terminal
 snmp-server server
 snmp-server view NETOPS-RO iso included
 snmp-server group NETOPS-RO v3 priv read NETOPS-RO
 snmp-server user netops-mon NETOPS-RO v3 auth sha <AUTH-PASSWORD> priv <PRIV-PASSWORD>
end
write memory
```

SNMPv2c instead (only if v3 isn't possible):

```
 snmp-server community <COMMUNITY> ro <server>
```

Or in the web page: SNMP > Views, Groups and Users. Older SG models encrypt with DES only: choose DES in the SNMP profile for those.

### Allied Telesis AlliedWare Plus

```
configure terminal
 snmp-server
 snmp-server view NETOPS-RO 1 included
 snmp-server group NETOPS-RO priv read NETOPS-RO
 snmp-server user netops-mon NETOPS-RO auth sha <AUTH-PASSWORD> priv aes <PRIV-PASSWORD>
end
write memory
```

SNMPv2c instead (only if v3 isn't possible):

```
 access-list 10 permit <server> 0.0.0.0
 snmp-server community <COMMUNITY> ro 10
```

Check with: show snmp-server user

### Arista EOS

```
configure
 ip access-list standard NETOPS-SNMP
  permit host <server>
 exit
 snmp-server view NETOPS-RO iso included
 snmp-server group NETOPS-RO v3 priv read NETOPS-RO
 snmp-server user netops-mon NETOPS-RO v3 auth sha <AUTH-PASSWORD> priv aes <PRIV-PASSWORD>
 snmp-server ipv4 access-list NETOPS-SNMP   ! add  vrf MGMT  if management is in a VRF
 snmp-server vrf MGMT                       ! only if management is in a VRF
end
write memory
```

SNMPv2c instead (only if v3 isn't possible):

```
 snmp-server community <COMMUNITY> ro NETOPS-SNMP
```

Check with: show snmp user

### Juniper Junos (EX, QFX, MX, SRX)

```
configure
set snmp view NETOPS-RO oid .1 include
set snmp v3 usm local-engine user netops-mon authentication-sha authentication-password "<AUTH-PASSWORD>"
set snmp v3 usm local-engine user netops-mon privacy-aes128 privacy-password "<PRIV-PASSWORD>"
set snmp v3 vacm security-to-group security-model usm security-name netops-mon group NETOPS-RO
set snmp v3 vacm access group NETOPS-RO default-context-prefix security-model usm security-level privacy read-view NETOPS-RO
commit and-quit
```

SNMPv2c instead (only if v3 isn't possible):

```
set snmp community <COMMUNITY> authorization read-only clients <server>/32
```

SNMPv3 has no client list in Junos: limit who reaches UDP 161 with the loopback (lo0) firewall filter.

### Fortinet FortiGate

```
config system snmp sysinfo
    set status enable
end
config system snmp user
    edit "netops-mon"
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
end
```

SNMPv2c instead (only if v3 isn't possible):

```
config system snmp community
    edit 1
        set name "<COMMUNITY>"
        config hosts
            edit 1
                set ip <server> 255.255.255.255
            next
        end
    next
end
```

Limit who may reach the interface with a local-in policy or trusted hosts.

### Palo Alto PAN-OS

```
1. Device > Setup > Operations > SNMP Setup: Version V3.
   Views: add NETOPS-RO, OID 1.3.6.1, Include, Mask 0xf0.
   Users: add netops-mon, View NETOPS-RO, Authpwd <AUTH-PASSWORD> (SHA),
   Privpwd <PRIV-PASSWORD> (AES).
2. Device > Setup > Interfaces > Management: tick SNMP, and add <server>
   under Permitted IP Addresses.
3. Commit.
```

SNMPv2c instead (only if v3 isn't possible):

```
Device > Setup > Operations > SNMP Setup: Version V2c, SNMP Community String <COMMUNITY>.
```

In the SNMP profile choose SHA and AES.

### Check Point Gaia

```
clish
set snmp agent on
set snmp agent-version v3-Only
add snmp usm user netops-mon security-level authPriv auth-pass-type SHA1 auth-pass-phrase <AUTH-PASSWORD> privacy-pass-type AES-128 privacy-pass-phrase <PRIV-PASSWORD>
save config
```

SNMPv2c instead (only if v3 isn't possible):

```
set snmp agent-version any
set snmp community <COMMUNITY> read-only
```

Allow SNMP from this server in the gateway's policy (or the management interface's host access).

### HPE Aruba AOS-CX

```
configure terminal
 snmp-server vrf mgmt
 snmpv3 user netops-mon auth sha auth-pass plaintext <AUTH-PASSWORD> priv aes priv-pass plaintext <PRIV-PASSWORD>
end
write memory
```

SNMPv2c instead (only if v3 isn't possible):

```
 snmp-server community <COMMUNITY>
  access-level ro
```

Use 'snmp-server vrf default' if the server is reached through the data ports. Limit who reaches UDP 161 with a control-plane access list.

### HPE ArubaOS-Switch (ProCurve)

```
configure
 snmpv3 enable                              ! asks for an initial user the first time
 snmpv3 user netops-mon auth sha <AUTH-PASSWORD> priv aes <PRIV-PASSWORD>
 snmpv3 group operatorauth user netops-mon sec-model ver3
end
write memory
```

SNMPv2c instead (only if v3 isn't possible):

```
 snmp-server community "<COMMUNITY>" operator restricted
```

operatorauth is read-only. Don't use 'ip authorized-managers' just for SNMP: it also limits SSH and the web page.

### HPE Aruba Mobility Controller (AOS 8)

```
configure terminal
 snmp-server user netops-mon auth-prot sha <AUTH-PASSWORD> priv-prot AES <PRIV-PASSWORD>
end
write memory
```

SNMPv2c instead (only if v3 isn't possible):

```
 snmp-server community <COMMUNITY>
```

On a Conductor, configure it at the level (/md) of the controllers.

### Dell SmartFabric OS10

```
configure terminal
 snmp-server view NETOPS-RO 1.3.6.1 included
 snmp-server group NETOPS-RO 3 priv read NETOPS-RO
 snmp-server user netops-mon NETOPS-RO 3 auth sha <AUTH-PASSWORD> priv aes <PRIV-PASSWORD>
 snmp-server vrf management                 ! leave out if polled through the data ports
end
write memory
```

SNMPv2c instead (only if v3 isn't possible):

```
 snmp-server community <COMMUNITY> ro
```

Check with: show snmp user

### Extreme EXOS / Switch Engine

```
configure snmpv3 add user netops-mon authentication sha <AUTH-PASSWORD> privacy aes <PRIV-PASSWORD>
configure snmpv3 add group NETOPS-RO user netops-mon sec-model usm
configure snmpv3 add access NETOPS-RO sec-model usm sec-level priv read-view defaultUserView
enable snmp access snmpv3
save configuration
```

SNMPv2c instead (only if v3 isn't possible):

```
configure snmp add community readonly <COMMUNITY>
enable snmp access snmp-v1v2c
```

Limit who may poll with 'configure snmp access-profile'.

### MikroTik RouterOS

```
/snmp community add name=netops-mon security=private addresses=<server>/32 \
    authentication-protocol=SHA1 authentication-password=<AUTH-PASSWORD> \
    encryption-protocol=AES encryption-password=<PRIV-PASSWORD> \
    read-access=yes write-access=no
/snmp set enabled=yes
```

SNMPv2c instead (only if v3 isn't possible):

```
/snmp community add name=<COMMUNITY> addresses=<server>/32 read-access=yes write-access=no
```

In RouterOS an SNMPv3 user is a 'community' with security=private.

### Ubiquiti EdgeRouter (EdgeOS)

```
configure
set service snmp v3 view NETOPS-RO oid 1
set service snmp v3 group NETOPS-RO view NETOPS-RO
set service snmp v3 group NETOPS-RO mode ro
set service snmp v3 user netops-mon group NETOPS-RO
set service snmp v3 user netops-mon auth type sha
set service snmp v3 user netops-mon auth plaintext-password <AUTH-PASSWORD>
set service snmp v3 user netops-mon privacy type aes
set service snmp v3 user netops-mon privacy plaintext-password <PRIV-PASSWORD>
commit
save
exit
```

SNMPv2c instead (only if v3 isn't possible):

```
set service snmp community <COMMUNITY> authorization ro
set service snmp community <COMMUNITY> client <server>
```

### Huawei VRP (S, CloudEngine, AR)

```
system-view
 acl 2001
  rule permit source <server> 0
  quit
 snmp-agent
 snmp-agent sys-info version v3
 snmp-agent mib-view included NETOPS-RO iso
 snmp-agent group v3 NETOPS-RO privacy read-view NETOPS-RO acl 2001
 snmp-agent usm-user v3 netops-mon group NETOPS-RO
 snmp-agent usm-user v3 netops-mon authentication-mode sha      # asks for <AUTH-PASSWORD>
 snmp-agent usm-user v3 netops-mon privacy-mode aes128          # asks for <PRIV-PASSWORD>
 quit
save
```

SNMPv2c instead (only if v3 isn't possible):

```
 snmp-agent sys-info version v2c v3
 snmp-agent community read cipher <COMMUNITY> acl 2001
```

Check with: display snmp-agent usm-user

### Linux and others (net-snmp)

```
# apt install snmpd
systemctl stop snmpd
net-snmp-create-v3-user -ro -a SHA -A '<AUTH-PASSWORD>' -x AES -X '<PRIV-PASSWORD>' netops-mon
# /etc/snmp/snmpd.conf: listen on the management address, e.g.
#   agentAddress udp:10.0.0.5:161
systemctl start snmpd
```

SNMPv2c instead (only if v3 isn't possible):

```
# /etc/snmp/snmpd.conf
rocommunity <COMMUNITY> <server>
```

Allow UDP 161 from this server in the host's firewall.
