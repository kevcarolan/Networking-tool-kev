"""Sample output for the platforms added with multi-vendor support (PR A).

These are written from each vendor's documented output formats, not captured from
real devices. Replace each one with a real capture during lab testing
(docs/upgrade-lab-tests.md), and fix the parser if the real output differs.
"""

# --- backups ---------------------------------------------------------------------

EOS_CONFIG = """! Command: show running-config
! device: leaf1 (DCS-7050SX3-48YC8, EOS-4.30.1F)
! Time: Mon Jan  8 10:00:00 2024
!
hostname leaf1
!
interface Ethernet1
   description server1
!
end
"""

JUNOS_CONFIG = """## Last commit: 2024-01-08 10:00:00 UTC by admin
set version 22.4R3-S2.11
set system host-name ex1
set interfaces ge-0/0/5 unit 0 family ethernet-switching vlan members users
set vlans users vlan-id 10
set vlans voice vlan-id 20
set protocols lldp interface all
{master:0}
"""

FORTIOS_CONFIG = """#config-version=FGT60F-7.2.5-FW-build1517-230606:opmode=0:vdom=0:user=admin
#conf_file_ver=1234567890123456
#buildno=1517
#global_vdom=1
config system global
    set hostname "fw1"
end
config system admin
    edit "admin"
        set password ENC SH2nBbW2fB0Kp1e3T9Zk0pXqk=
    next
end
config vpn ipsec phase1-interface
    edit "to-dc"
        set psksecret ENC Wq8b3k2l9x0VZ/abc==
    next
end
"""

PANOS_CONFIG = """Entering configuration mode
[edit]
set deviceconfig system hostname pa1
set deviceconfig system ip-address 10.0.0.10
set network interface ethernet ethernet1/1 layer3 ip 10.10.0.1/24
set zone trust network layer3 ethernet1/1
set zone untrust network layer3 ethernet1/2
[edit]
Exiting configuration mode
"""

MIKROTIK_CONFIG = """# 2024-01-08 10:00:00 by RouterOS 7.12.1
# software id = AB12-CD34
# model = CCR2004-1G-12S+2XS
/interface bridge add name=bridge1
/ip address add address=10.10.0.1/24 interface=bridge1
/system identity set name=rtr1
"""

XR_CONFIG = """Mon Jan  8 10:00:00.123 UTC
Building configuration...
!! IOS XR Configuration 7.9.2
!! Last configuration change at Mon Jan  8 09:00:00 2024 by admin
!
hostname pe1
interface GigabitEthernet0/0/0/0
 ipv4 address 10.0.0.1 255.255.255.252
!
end
"""

# --- versions --------------------------------------------------------------------

EOS_VERSION = """Arista DCS-7050SX3-48YC8
Hardware version: 11.02
Serial number: JPE12345678
Hardware MAC address: 001c.7300.0001
System MAC address: 001c.7300.0001

Software image version: 4.30.1F
Architecture: x86_64
Internal build version: 4.30.1F-32308478.4301F
Internal build ID: 0c5b1c4e-0000-0000-0000-000000000000

Uptime: 5 weeks, 1 days, 2 hours and 3 minutes
Total memory: 16012760 kB
Free memory: 11012760 kB
"""

EOS_DIR = """Directory of flash:/

       -rwx  1028382542            Jan  8 10:00  EOS-4.30.1F.swi
       -rwx  1012345678            Jan  1 10:00  EOS-4.29.2F.swi

3957301248 bytes total (1916573028 bytes free)
"""

JUNOS_VERSION = """fpc0:
--------------------------------------------------------------------------
Hostname: ex1
Model: ex4400-48p
Junos: 22.4R3-S2.11
JUNOS OS Kernel 64-bit  [20231128.c0a2e1e_builder_stable_12_224]
JUNOS OS libs [20231128.c0a2e1e_builder_stable_12_224]

fpc1:
--------------------------------------------------------------------------
Hostname: ex1
Model: ex4400-48p
Junos: 22.4R3-S2.11
"""

JUNOS_VERSION_OLD = """Hostname: srx1
Model: srx345
JUNOS Software Release [19.4R3-S9.4]
"""

JUNOS_HARDWARE = """Hardware inventory:
Item             Version  Part number  Serial number     Description
Chassis                                XN1234567890      EX4400-48P
Routing Engine 0 REV 08   650-104283   XN1234567890      RE-EX4400-48P
FPC 0            REV 08   650-104283   XN1234567890      EX4400-48P
"""

FORTIOS_STATUS = """Version: FortiGate-60F v7.2.5,build1517,230606 (GA.F)
Firmware Signature: certified
Virus-DB: 91.07211(2023-09-21 21:24)
Serial-Number: FGT60FTK2209ABCD
BIOS version: 05000012
System Part-Number: P24331-05
Log hard disk: Not available
Hostname: fw1
Private Encryption: Disable
Operation Mode: NAT
Current virtual domain: root
Max number of virtual domains: 10
Virtual domains status: 1 in NAT mode, 0 in TP mode
Virtual domain configuration: disable
FIPS-CC mode: disable
Current HA mode: a-p, primary
Cluster uptime: 10 days, 2 hours, 3 minutes, 4 seconds
Branch point: 1517
Release Version Information: GA
System time: Mon Jan  8 10:00:00 2024
"""

PANOS_INFO = """
hostname: pa1
ip-address: 10.0.0.10
netmask: 255.255.255.0
mac-address: 00:1b:17:00:00:01
time: Mon Jan  8 10:00:00 2024
uptime: 10 days, 2:03:04
family: 3400
model: PA-3420
serial: 012345678901
sw-version: 10.2.7-h3
app-version: 8790-8436
threat-version: 8790-8436
multi-vsys: off
operational-mode: normal
"""

PANOS_HA_ACTIVE = """
Group 1:
  Mode: Active-Passive
  Local Information:
    Version: 1
    Mode: Active-Passive
    State: active (last 10 days)
    Device Information:
      Management IPv4 Address: 10.0.0.10/24
  Peer Information:
    Connection status: up
    State: passive (last 10 days)
"""

GAIA_VERSION = """Product version Check Point Gaia R81.20
OS build 631
OS kernel version 3.10.0-957.21.3cpx86_64
OS edition 64-bit
"""

GAIA_ASSET = """Platform: QM-6600
Model: Check Point 6600
Serial Number: 1234AB5678
CPU Model: Intel(R) Xeon(R) CPU D-1527
Number of Cores: 8
"""

GAIA_CLUSTER = """
Cluster Mode:   High Availability (Active Up) with IGMP Membership

ID         Unique Address  Assigned Load   State          Name

1 (local)  10.0.0.2        100%            ACTIVE         gw1
2          10.0.0.3        0%              STANDBY        gw2
"""

AOSCX_VERSION = """-----------------------------------------------------------------------------
ArubaOS-CX
(c) Copyright 2017-2023 Hewlett Packard Enterprise Development LP
-----------------------------------------------------------------------------
Version      : FL.10.10.1010
Build Date   : 2023-06-12 18:00:00 UTC
Build ID     : ArubaOS-CX:FL.10.10.1010:abcdef:202306121800
Build SHA    : abcdef0123456789
Hot Patches  :
Active Image : primary

Service OS Version : FL.01.11.0002
BIOS Version       : FL.01.0003
"""

AOSCX_SYSTEM = """Hostname           : cx1
System Description : FL.10.10.1010
System Contact     :
System Location    :

Vendor             : Aruba
Product Name       : JL658A 6300M 24SFP+ 4SFP56 Swch
Chassis Serial Nbr : SG12KLM34N
Base MAC Address   : 08:97:34:00:00:01
ArubaOS-CX Version : FL.10.10.1010
"""

OSSWITCH_VERSION = """Image stamp:    /ws/swbuildm/rel_ukiah_qaoff/code/build/bom(swbuildm_rel_ukiah_qaoff_rel_ukiah)
                Mar 13 2023 13:24:25
                WC.16.11.0012
                1990
Boot Image:     Primary

Boot ROM Version:    WC.17.02.0006
Active Boot ROM:     Primary
"""

OSSWITCH_SYSTEM = """
 Status and Counters - General System Information

  System Name        : sw1
  System Contact     :
  System Location    :

  MAC Age Time (sec) : 300

  Time Zone          : 0
  Daylight Time Rule : None

  Software revision  : WC.16.11.0012        Base MAC Addr      : 98f2b3-000001
  ROM Version        : WC.17.02.0006        Serial Number      : SG9ZKMX123

  Up Time            : 10 days              Memory   - Total   : 339,200,000
  CPU Util (%)       : 3                               Free    : 211,368,960
"""

OSSWITCH_MODULES = """
 Status and Counters - Module Information

  Chassis: 2930M-24G-PoE+ JL320A          Serial Number:   SG9ZKMX123
"""

AOS8_VERSION = """Aruba Operating System Software.
ArubaOS (MODEL: Aruba7210), Version 8.10.0.7
Website: http://www.arubanetworks.com
(c) Copyright 2023 Hewlett Packard Enterprise Development LP.
Compiled on 2023-06-01 at 10:00:00 UTC (build 87654) by p4build
ROM: System Bootstrap, Version CPBoot 1.2.2.0 (build 52357)
Switch uptime is 10 days 2 hours 3 minutes 4 seconds
"""

AOS8_INVENTORY = """Supervisor Card slot        : 0
System Serial#               : CW0001234 (Date:01/02/20)
SC Assembly#                 : 2010323A (Rev:01.00)
Power Supply 0               : Present (Ok)
Power Supply 1               : Present (Ok)
Fan Tray                     : Present (OK)
"""

OS10_VERSION = """Dell SmartFabric OS10 Enterprise
Copyright (c) 1999-2023 by Dell Inc. All Rights Reserved.
OS Version: 10.5.5.5
Build Version: 10.5.5.5.123
Build Time: 2023-06-01T10:00:00+0000
System Type: S5248F-ON
Architecture: x86_64
Up Time: 10 days 02:03:04
"""

OS10_INVENTORY = """Product               : S5248F-ON
Description           : S5248F-ON 48x25GbE SFP28, 4x100GbE QSFP28, 2x200GbE QSFP28-DD
Software version      : 10.5.5.5
Product Base          :
Product Serial Number :
Product Part Number   :

Unit Type                 Part Number Rev Piece Part ID          Svc Tag Exprs Svc Code
-----------------------------------------------------------------------------------------
* 1  S5248F-ON            0P1M1R      A00 TW-0P1M1R-28298-998-0012 9531XC2 202 422 627 8
  1  S5248F-ON-PWR-1-AC   0T5FCN      A00 TW-0T5FCN-28298-998-0022
"""

EXOS_VERSION = """Switch      : 800616-00-02 1928G-12345 Rev 2.0 BootROM: 2.0.1.4    IMG: 31.7.1.4
PSU-1       : Internal PSU-1 800617-00-01 1929W-00001
PSU-2       :

Image   : ExtremeXOS version 31.7.1.4 by release-manager
          on Tue Jun  6 10:00:00 EDT 2023
BootROM : 2.0.1.4
Diagnostics : 5.20
"""

EXOS_SWITCH = """SysName:          sw1
SysLocation:
SysContact:       support@example.com
System MAC:       00:04:96:00:00:01
System Type:      X465-48W

Primary ver:      31.7.1.4
Secondary ver:    31.6.1.3

Image Selected:   primary
Image Booted:     primary
"""

ROUTEROS_RESOURCE = """                   uptime: 1w2d3h4m5s
                  version: 7.12.1 (stable)
               build-time: 2023-11-17 11:38:44
         factory-software: 7.1
                 cpu-load: 3%
              free-memory: 3378.6MiB
             total-memory: 4096.0MiB
                      cpu: ARM64
                cpu-count: 4
           free-hdd-space: 1036.0MiB
          total-hdd-space: 1152.0MiB
        architecture-name: arm64
               board-name: CCR2004-1G-12S+2XS
                 platform: MikroTik
"""

ROUTEROS_ROUTERBOARD = """       routerboard: yes
        board-name: CCR2004-1G-12S+2XS
             model: CCR2004-1G-12S+2XS
     serial-number: HCQ08ABCDEF
     firmware-type: al2
  factory-firmware: 7.1
  current-firmware: 7.12.1
  upgrade-firmware: 7.12.1
"""

EDGEOS_VERSION = """Version:      v2.0.9-hotfix.7
Build ID:     5611225
Build on:     06/15/23 10:00
Copyright:    2012-2023 Ubiquiti, Inc.
HW model:     EdgeRouter 4
HW S/N:       7483C2ABCDEF
Uptime:       10:00:00 up 10 days,  2:03,  1 user,  load average: 0.00, 0.01, 0.05
"""

VRP_VERSION = """Huawei Versatile Routing Platform Software
VRP (R) software, Version 5.170 (S5735 V200R021C10SPC600)
Copyright (C) 2000-2022 HUAWEI TECH Co., Ltd.
HUAWEI S5735-L48T4X-A1 Routing Switch uptime is 10 days, 2 hours, 3 minutes
"""

VRP_ESN = """ESN of slot 0: 2102351931P0LB000123
"""

XR_VERSION = """Mon Jan  8 10:00:00.123 UTC
Cisco IOS XR Software, Version 7.9.2
Copyright (c) 2013-2023 by Cisco Systems, Inc.

Build Information:
 Built By     : ingunawa
 Built On     : Wed Jun  7 10:00:00 UTC 2023
 Version      : 7.9.2

cisco ASR9K (Intel(R) Xeon(R) CPU D-1530 @ 2.40GHz) processor with 32GB of memory
pe1 uptime is 10 weeks, 2 days, 3 hours
"""

XR_INVENTORY = """Mon Jan  8 10:00:00.456 UTC
NAME: "Rack 0", DESCR: "ASR-9901 AC Chassis"
PID: ASR-9901, VID: V01, SN: FOC2200ABCD

NAME: "0/RSP0/CPU0", DESCR: "ASR 9901 Route Switch Processor"
PID: ASR-9901-RP, VID: V01, SN: FOC2200EFGH
"""

SMB_VERSION = """Active-image: flash://system/images/image_cbs_ros_3.3.0.16_release_cbs_ros_3.3_950_377_134.bin
  Version: 3.3.0.16
  MD5 Digest: 0123456789abcdef0123456789abcdef
  Date: 07-Jun-2023
  Time: 10:00:00
Inactive-image: flash://system/images/image_cbs_ros_3.2.0.84_release_cbs_ros_3.2_950_377_134.bin
  Version: 3.2.0.84
  MD5 Digest: fedcba9876543210fedcba9876543210
"""

SMB_INVENTORY = """NAME: "1"   DESCR: "CBS350-24P-4G 24-Port Gigabit PoE Managed Switch"
PID: CBS350-24P-4G-EU   VID: V01   SN: PSZ24321ABC
"""

# --- MAC, ARP and neighbour tables ---------------------------------------------------

EOS_MAC = """          Mac Address Table
------------------------------------------------------------------

Vlan    Mac Address       Type        Ports      Moves   Last Move
----    -----------       ----        -----      -----   ---------
  10    0050.56a1.0001    DYNAMIC     Et5        1       0:01:02 ago
  10    0050.56a1.0002    DYNAMIC     Po10       1       2 days, 3:04:05 ago
  10    001c.7300.0099    STATIC      Router
Total Mac Addresses for this criterion: 3
"""

EOS_LLDP = """Interface Ethernet49/1 detected 1 LLDP neighbors:

  Neighbor 001c.7300.0001/"Ethernet1" age 12 seconds
  Discovered 5 days, 1:02:03 ago; Last changed 5 days, 1:02:03 ago
  - Chassis ID type: MAC address (4)
    Chassis ID     : 001c.7300.0001
  - Port ID type: Interface name (5)
    Port ID        : "Ethernet1"
  - System Name: "spine1"
  - System Capabilities : Bridge, Router
    Enabled Capabilities: Bridge, Router

Interface Ethernet5 detected 1 LLDP neighbors:

  Neighbor 0004.f2aa.0001/"1" age 20 seconds
  - System Name: "SEP0004F2AA0001"
  - System Capabilities : Bridge, Telephone
    Enabled Capabilities: Bridge, Telephone
"""

EOS_ARP = """
VRF: default
Address         Age (sec)  Hardware Addr   Interface
10.10.0.6         0:00:42  0050.56a1.0002  Vlan10, Port-Channel10
10.10.0.99              -  incomplete      Vlan10
"""

JUNOS_MAC = """MAC flags (S - static MAC, D - dynamic MAC, L - locally learned, P - Persistent static
           SE - statistics enabled, NM - non configured MAC, R - remote PE MAC, O - ovsdb MAC)


Ethernet switching table : 3 entries, 3 learned
Routing instance : default-switch
   Vlan                MAC                 MAC         Age    Logical                NH        RTR
   name                address             flags              interface              Index     ID
   users               00:50:56:a1:00:01   D             -   ge-0/0/5.0             0         0
   users               00:50:56:a1:00:02   D             -   ae0.0                  0         0
   voice               00:04:f2:aa:00:01   D             -   ge-0/0/5.0             0         0
"""

JUNOS_LLDP = """Local Interface    Parent Interface    Chassis Id          Port info          System Name
ge-0/0/47          -                   00:1c:73:00:00:01   Ethernet1          spine1
xe-0/2/0           ae0                 2c:6b:f5:00:00:01   xe-0/2/0           core1
ge-0/0/5           -                   00:04:f2:aa:00:01   eth0               phone-101
"""

JUNOS_ARP = """MAC Address       Address         Interface         Flags
00:50:56:a1:00:02 10.10.0.6       irb.10 [ae0.0]    none
Total entries: 1
"""

AOSCX_MAC = """MAC age-time            : 300 seconds
Number of MAC addresses : 2

MAC Address          VLAN     Type                      Port
--------------------------------------------------------------
00:50:56:a1:00:01    10       dynamic                   1/1/5
00:50:56:a1:00:02    10       dynamic                   lag1
"""

AOSCX_LLDP = """LLDP Neighbor Information
=========================

Port                           : 1/1/49
Neighbor Entries               : 1
Neighbor Chassis-Name          : core1
Neighbor Chassis-ID            : 08:97:34:00:00:01
Chassis Capabilities Available : Bridge, Router
Chassis Capabilities Enabled   : Bridge, Router
Neighbor Port-ID               : 1/1/1

Port                           : 1/1/7
Neighbor Entries               : 1
Neighbor Chassis-Name          : ap-floor1
Neighbor Chassis-ID            : 20:4c:03:00:00:01
Chassis Capabilities Available : Bridge, WLAN
Chassis Capabilities Enabled   : WLAN
Neighbor Port-ID               : eth0
"""

AOSCX_ARP = """IPv4 Address     MAC                Port         Physical Port    State      VRF
---------------------------------------------------------------------------------
10.10.0.6        00:50:56:a1:00:02  vlan10       1/1/5            reachable  default
"""

OSSWITCH_MAC = """
 Status and Counters - Port Address Table

  MAC Address   Port   VLAN
  ------------- ------ ----
  005056-a10001 5      10
  005056-a10002 Trk1   10
"""

OSSWITCH_LLDP = """
 LLDP Remote Device Information Detail

  Local Port   : 25
  ChassisType  : mac-address
  ChassisId    : 00 1c 73 00 00 01
  PortType     : local
  PortId       : 49
  SysName      : core1

  System Capabilities Supported  : bridge, router
  System Capabilities Enabled    : bridge, router

 ------------------------------------------------------------------------------
  Local Port   : 7
  SysName      : SEP0004F2AA0001

  System Capabilities Supported  : bridge, telephone
  System Capabilities Enabled    : bridge, telephone
"""

OSSWITCH_ARP = """
 IP ARP table

  IP Address       MAC Address       Type    Port
  ---------------  ----------------- ------- ----
  10.10.0.6        005056-a10002     dynamic 5
"""

OS10_MAC = """VlanId        Mac Address           Type          Interface
1             00:50:56:a1:00:01     dynamic       ethernet1/1/5
10            00:50:56:a1:00:02     dynamic       port-channel10
"""

OS10_LLDP = """Remote Chassis ID Subtype: Mac address (4)
Remote Chassis ID: 00:1c:73:00:00:01
Remote Port Subtype: Interface name (5)
Remote Port ID: Ethernet1
Local Port ID: ethernet1/1/49
Remote System Name: spine1
Existing System Capabilities: Bridge Router
Enabled System Capabilities: Bridge Router
---------------------------------------------------------------------------
"""

EXOS_FDB = """MAC                     VLAN Name( Tag)  Age  Flags         Port / Virtual Port List
------------------------------------------------------------------------------------------------------
00:50:56:a1:00:01       users(0010) 0000  d m           5
00:50:56:a1:00:02       users(0010) 0000  d m           49

Flags : d - Dynamic, s - Static, p - Permanent, n - NetLogin, m - MAC, i - IP,
"""

EXOS_LLDP = """-----------------------------------------------------------------------------
LLDP Port 49 detected 1 neighbor
  Neighbor: 00:04:96:00:00:01/49, age 30 seconds
    - Chassis ID type: MAC address (4); Chassis ID: 00:04:96:00:00:01
    - Port ID type: ifName (5); Port ID: "1:49"
    - System Name: "core1"
    - System Capabilities : "Bridge, Router"
      Enabled Capabilities: "Bridge, Router"
-----------------------------------------------------------------------------
"""

EXOS_IPARP = """VR             Destination      Mac                Age  Static  VLAN          VID   Port
VR-Default     10.10.0.6        00:50:56:a1:00:02     4      NO  users         10    5
"""

SMB_MAC = """Aging time is 300 sec

    Vlan          Mac Address         Port       Type
-------- --------------------- ---------- ----------
   1        00:50:56:a1:00:01       gi5      dynamic
   10       00:50:56:a1:00:02       Po1      dynamic
   1        64:00:6a:00:00:01        0        self
"""

SMB_LLDP = """System capability supported: Bridge, Router
  Port      Device ID          Port ID       System Name    Capabilities  TTL
--------- ----------------- ------------- --------------- ------------ -----
gi1/0/49  00:1c:73:00:00:01   Ethernet1      spine1           B, R        91
gi1/0/5   00:04:f2:aa:00:01   1              phone-101        B, T        115
"""

ROUTEROS_HOSTS = """Flags: X - disabled, I - invalid, D - dynamic, L - local, E - external
 0   D mac-address=00:50:56:A1:00:01 vid=10 on-interface=ether5 bridge=bridge1 age=1m2s
 1   D mac-address=00:50:56:A1:00:02 vid=10 on-interface=ether1 bridge=bridge1 age=3s
 2  DL mac-address=64:D1:54:00:00:01 on-interface=bridge1 bridge=bridge1
"""

ROUTEROS_NEIGHBORS = """ 0 interface=ether1,bridge1 address=10.0.0.1 mac-address=64:D1:54:00:00:99 identity=core1 platform=MikroTik version=7.12.1 system-caps=bridge,router system-caps-enabled=bridge,router interface-name=ether2
 1 interface=ether5,bridge1 address=10.10.0.50 mac-address=00:04:F2:AA:00:01 identity=phone-101 system-caps=bridge,telephone system-caps-enabled=telephone
"""

ROUTEROS_ARP = """Flags: X - disabled, I - invalid, H - DHCP, D - dynamic, P - published, C - complete
 0 DC address=10.10.0.6 mac-address=00:50:56:A1:00:02 interface=bridge1 published=no
"""

VRP_MAC = """-------------------------------------------------------------------------------
MAC Address    VLAN/VSI/BD   Learned-From        Type
-------------------------------------------------------------------------------
0050-56a1-0001 10/-/-        GE0/0/5             dynamic
0050-56a1-0002 10/-/-        Eth-Trunk1          dynamic
-------------------------------------------------------------------------------
Total items displayed = 2
"""

VRP_LLDP = """GigabitEthernet0/0/24 has 1 neighbor(s):

Neighbor index :1
Chassis type   :MAC address
Chassis ID     :0050-56a1-0aaa
Port ID type   :Interface name
Port ID        :GigabitEthernet0/0/1
System name         :core1
System capabilities supported   :bridge router
System capabilities enabled     :bridge router

GigabitEthernet0/0/5 has 0 neighbor(s)
"""

VRP_ARP = """IP ADDRESS      MAC ADDRESS     EXPIRE(M) TYPE        INTERFACE      VPN-INSTANCE
                                          VLAN/CEVLAN PVC
------------------------------------------------------------------------------
10.10.0.6       0050-56a1-0002  20        D-0         GE0/0/5
                                          10/-
"""

FORTIOS_ARP = """Address           Age(min)   Hardware Addr      Interface
10.10.0.6         0          00:50:56:a1:00:02 internal
"""

PANOS_ARP = """
maximum of entries supported :      2500
default timeout:                    1800 seconds
total ARP entries in table :        1

status: s - static, c - complete, e - expiring, i - incomplete

interface         ip address      hw address        port              status   ttl
--------------------------------------------------------------------------------
ethernet1/1       10.10.0.6       00:50:56:a1:00:02 ethernet1/1       c        1700
"""
