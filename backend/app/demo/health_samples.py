"""Healthy output for the health-check and snapshot commands (tools/firmware_upgrade/health.py),
per platform, so the demo network and the tests can run a full upgrade with every check.

Written from vendor documentation. Replace each one with a lab capture
(``netops-cli capture <device>``) as the platform is signed off.

FAULTS holds broken versions of some of them for the tests.
"""

from app.demo import samples

ARISTA = {
    "show system environment all": """System temperature status is: Ok
Sensor  Description                       Current Temp  Setpoint  Critical Limit
------- --------------------------------- ------------- --------- ---------------
1       Cpu temp sensor                   41.0C         85C       95C
2       Front-panel temp sensor           26.0C         65C       75C

System cooling status is: Ok
Ambient temperature: 24C
Airflow: frontToBackAirflow
Fan Tray  Status   Speed
--------- -------- -----
1         Ok       42%
2         Ok       42%

Power Supply  Model         Capacity  Input Current  Output Current  Output Power  Status
------------  ------------  --------  -------------  --------------  ------------  ------
1             PWR-500AC-F   500W      0.62A          9.12A           109.4W        Ok
2             PWR-500AC-F   500W      0.60A          8.90A           106.8W        Ok
""",
    "show module": """Module    Type                                    Model                Serial No.
--------- --------------------------------------- -------------------- -----------
1         48-port 25GbE SFP + 8-port 100GbE QSFP  DCS-7050SX3-48YC8    JPE12345678

Module    Status   Uptime            Power off reason
--------- -------- ----------------- ----------------
1         Ok       10 days, 2:03:04  N/A
""",
    "show processes top once": """top - 10:00:00 up 10 days,  2:03,  0 users,  load average: 0.31, 0.35, 0.36
Tasks: 245 total,   1 running, 244 sleeping,   0 stopped,   0 zombie
%Cpu(s):  4.1 us,  1.2 sy,  0.0 ni, 94.5 id,  0.0 wa,  0.1 hi,  0.1 si,  0.0 st
KiB Mem :  8023988 total,  3611200 free,  2803060 used,  1609728 buff/cache
KiB Swap:        0 total,        0 free,        0 used.  4911200 avail Mem
""",
    "show running-config diffs": "",
    "show reload cause": """Reload Cause 1:
-------------------
Reload requested by the user.

Recommended Action:
-------------------
No action necessary.
""",
    "show interfaces status": """Port       Name        Status       Vlan     Duplex Speed  Type            Flags Encapsulation
Et1        server-1    connected    10       full   25G    25GBASE-SR
Et2        server-2    connected    10       full   25G    25GBASE-SR
Et3                    notconnect   1        auto   auto   25GBASE-SR
Et4                    disabled     1        auto   auto   Not Present
Et49/1     to-spine1   connected    in Po49  full   100G   100GBASE-SR4
Et50/1     to-spine2   connected    in Po49  full   100G   100GBASE-SR4
Ma1                    connected    routed   a-full a-1G   10/100/1000
Po49       to-spines   connected    trunk    full   200G   N/A
""",
    "show lldp neighbors": """Last table change time   : 10 days, 2:00:00 ago
Number of table inserts  : 3
Number of table deletes  : 0
Number of table drops    : 0
Number of table age-outs : 0

Port          Neighbor Device ID       Neighbor Port ID    TTL
---------- ------------------------ ---------------------- ---
Et49/1        dc1-spine1.example.net   xe-0/0/1            120
Et50/1        dc1-spine2.example.net   xe-0/0/1            120
Ma1           oob-sw                   Gi1/0/10            120
""",
    "show port-channel summary": """                 Flags
------------------------ ---------------------------- -------------------------
  a - LACP Active          p - LACP Passive           * - static fallback
  U - In Use               D - Down
  + - In-Sync              - - Out-of-Sync            i - incompatible with agg
  P - bundled in Po        s - suspended              G - Aggregable
  I - Individual           S - ShortTimeout           w - wait for agg

Number of channels in use: 1
Number of aggregators: 1

   Port-Channel       Protocol    Ports
------------------ -------------- ------------------
   Po49(U)            LACP(a)     Et49/1(PG+) Et50/1(PG+)
""",
}

NXOS = {
    "show environment": """Power Supply:
Voltage: 12 Volts
Power                              Actual        Actual        Total
Supply    Model                    Output     Input    Capacity    Status
-------  -------------------  -----------  -----------  -----------  --------------
1        NXA-PAC-650W-PE           112 W        124 W        650 W     Ok
2        NXA-PAC-650W-PE           108 W        120 W        650 W     Ok

Fan:
---------------------------------------------------------------------------
Fan             Model                Hw     Direction       Status
---------------------------------------------------------------------------
Fan1(sys_fan1)  NXA-FAN-30CFM-B      --     front-to-back   Ok
Fan2(sys_fan2)  NXA-FAN-30CFM-B      --     front-to-back   Ok
Fan_in_PS1      --                   --     front-to-back   Ok

Temperature:
--------------------------------------------------------------------
Module   Sensor        MajorThresh   MinorThres   CurTemp     Status
                       (Celsius)     (Celsius)    (Celsius)
--------------------------------------------------------------------
1        FRONT           80              70          32         Ok
1        BACK            70              42          27         Ok
""",
    "show module": """Mod  Ports             Module-Type                      Model           Status
---  -----  -------------------------------------  ------------------  ----------
1    54     48x10/25G + 6x40/100G Ethernet Module  N9K-C93180YC-FX     active *

Mod  Sw                       Hw    Slot
---  -----------------------  ------  ----
1    9.3(10)                  1.0     NA
""",
    "show system resources": """Load average:   1 minute: 0.42   5 minutes: 0.38   15 minutes: 0.36
Processes:   612 total, 1 running
CPU states  :   3.50% user,   1.50% kernel,   95.00% idle
Memory usage:   24538812K total,   9312340K used,   15226472K free
Current memory status: OK
""",
    "show running-config diff": "",
    "show system reset-reason": """----- reset reason for Supervisor-module 1 (from Supervisor in slot 1) ---
1) At 123456 usecs after Sat Oct  3 02:00:00 2026
    Reason: Reset Requested by CLI command reload
    Service:
    Version: 9.3(10)
""",
    "show interface brief": """--------------------------------------------------------------------------------
Port   VRF          Status IP Address                              Speed    MTU
--------------------------------------------------------------------------------
mgmt0  --           up     192.0.2.11                              1000     1500

--------------------------------------------------------------------------------
Ethernet      VLAN    Type Mode   Status  Reason                   Speed     Port
Interface                                                                    Ch #
--------------------------------------------------------------------------------
Eth1/1        10      eth  access up      none                       10G(D) --
Eth1/2        1       eth  access down    Link not connected         auto(D) --
Eth1/49       1       eth  trunk  up      none                       100G(D) 1
Eth1/50       1       eth  trunk  up      none                       100G(D) 1

--------------------------------------------------------------------------------
Port-channel VLAN    Type Mode   Status  Reason                    Speed   Protocol
Interface
--------------------------------------------------------------------------------
Po1          1       eth  trunk  up      none                       a-100G(D)  lacp
""",
    "show lldp neighbors": """Capability codes:
  (R) Router, (B) Bridge, (T) Telephone, (C) DOCSIS Cable Device
  (W) WLAN Access Point, (P) Repeater, (S) Station, (O) Other
Device ID            Local Intf      Hold-time  Capability  Port ID
core-peer            Eth1/49         120        BR          Ethernet1/49
core-peer            Eth1/50         120        BR          Ethernet1/50
hq-acc-sw1           Eth1/1          120        B           Gi1/0/48
Total entries displayed: 3
""",
    "show port-channel summary": """Flags:  D - Down        P - Up in port-channel (members)
        I - Individual  H - Hot-standby (LACP only)
        s - Suspended   r - Module-removed
        S - Switched    R - Routed
        U - Up (port-channel)
--------------------------------------------------------------------------------
Group Port-       Type     Protocol  Member Ports
      Channel
--------------------------------------------------------------------------------
1     Po1(SU)     Eth      LACP      Eth1/49(P)   Eth1/50(P)
""",
}

JUNOS = {
    "show chassis environment": """Class Item                           Status     Measurement
Power FPC 0 Power Supply 0           OK
      FPC 0 Power Supply 1           OK
Temp  FPC 0 CPU                      OK         38 degrees C / 100 degrees F
      FPC 0 PFE                      OK         45 degrees C / 113 degrees F
Fans  FPC 0 Fan Tray 0 Fan 0         OK         Spinning at normal speed
      FPC 0 Fan Tray 0 Fan 1         OK         Spinning at normal speed
""",
    "show chassis alarms": "No alarms currently active\n",
    "show system alarms": "No alarms currently active\n",
    "show virtual-chassis": """Preprovisioned Virtual Chassis
Virtual Chassis ID: 1234.5678.9abc
Virtual Chassis Mode: Enabled
                                                Mstr           Mixed Route Neighbor List
Member ID  Status   Serial No    Model          prio  Role      Mode  Mode ID  Interface
0 (FPC 0)  Prsnt    XX0123456789 qfx5120-48y-8c  129  Master*     N    F
""",
    "show chassis routing-engine": """Routing Engine status:
    Temperature                 38 degrees C / 100 degrees F
    CPU temperature             45 degrees C / 113 degrees F
    DRAM                      3584 MB (4096 MB installed)
    Memory utilization          46 percent
    5 sec CPU utilization:
      User                       4 percent
      Background                 0 percent
      Kernel                     3 percent
      Interrupt                  1 percent
      Idle                      92 percent
    Model                          RE-QFX5120-48Y-8C
    Start time                     2026-10-03 02:00:00 UTC
    Uptime                         10 days, 8 hours, 1 minute, 2 seconds
    Last reboot reason             Router rebooted after a normal shutdown.
    Load averages:                 1 minute   5 minute  15 minute
                                       0.21       0.25       0.26
""",
    "show interfaces terse": """Interface               Admin Link Proto    Local                 Remote
xe-0/0/1                up    up
xe-0/0/1.0              up    up   aenet    --> ae0.0
xe-0/0/2                up    up
xe-0/0/2.0              up    up   aenet    --> ae0.0
xe-0/0/3                up    up
xe-0/0/4                up    down
xe-0/0/5                down  down
ae0                     up    up
ae0.0                   up    up   eth-switch
em0                     up    up
""",
    "show lldp neighbors": """Local Interface    Parent Interface    Chassis Id          Port info          System Name
xe-0/0/1           ae0                 00:1c:73:aa:bb:01   Ethernet49/1       dc1-leaf1
xe-0/0/2           ae0                 00:1c:73:aa:bb:01   Ethernet50/1       dc1-leaf1
xe-0/0/3           -                   00:1c:73:aa:bb:02   Ethernet49/1       dc1-leaf2
""",
    "show lacp interfaces": """Aggregated interface: ae0
    LACP state:       Role   Exp   Def  Dist  Col  Syn  Aggr  Timeout  Activity
      xe-0/0/1       Actor    No    No   Yes  Yes  Yes   Yes     Fast    Active
      xe-0/0/1     Partner    No    No   Yes  Yes  Yes   Yes     Fast    Active
      xe-0/0/2       Actor    No    No   Yes  Yes  Yes   Yes     Fast    Active
      xe-0/0/2     Partner    No    No   Yes  Yes  Yes   Yes     Fast    Active
    LACP protocol:        Receive State  Transmit State          Mux State
      xe-0/0/1                  Current   Fast periodic Collecting distributing
      xe-0/0/2                  Current   Fast periodic Collecting distributing
""",
}

OSSWITCH = {
    "show system power-supply": """Power Supply Status:

  PS#   Model     Serial      State           AC/DC  + V        Wattage   Max
  ----- --------- ----------- --------------- ----------------- --------- ------
  1     JL085A    CN12345678  Powered         AC 120V/240V        45      680
  2                           Not Present     -- ---------           0        0

  1 / 2 supply bays delivering power.
  Total power: 45 W / 680 W
""",
    "show system fans": """Fan Information
  Num  | State       | Failures
-------+-------------+----------
Sys-1  | Fan OK      | 0
Sys-2  | Fan OK      | 0

0 / 2 Fans in Failure State
0 / 2 Fans have been in Failure State
""",
    "show stacking": """Stack ID         : 0100a0b3-c4d5e6f7

MAC Address      : 98f2b3-000001
Stack Topology   : Unknown
Stack Status     : Active
Uptime           : 10d 2h 3m
Software Version : WC.16.11.0012

 Mbr
 ID  Mac Address       Model                                  Pri Status
 --- ----------------- -------------------------------------- --- ---------------
 1   98f2b3-000001     Aruba JL320A 2930M-24G-PoE+ Switch     255 Commander
""",
    "show config status": "Running configuration is the same as the startup configuration.\n",
    "show boot-history": """Mgmt Module 1 -- Saved Crash Information (most recent first):
===============================================================

Mgmt Module 1 -- Boot History (most recent first):
==================================================
Uptime 10d  2:03:04, Boot Reason: Operator Reboot
""",
    "show interfaces brief": """ Status and Counters - Port Status

                  | Intrusion                           Flow  Bcast
  Port  Type      | Alert     Enabled Status Mode       Ctrl  Limit
  ----- --------- + --------- ------- ------ ---------- ----- ------
  1     100/1000T | No        Yes     Up     1000FDx    off   0
  2     100/1000T | No        Yes     Down   1000FDx    off   0
  49    SFP+SR    | No        Yes     Up     10GigFD    off   0
  50    SFP+SR    | No        Yes     Up     10GigFD    off   0
""",
    "show lldp info remote-device": """ LLDP Remote Devices Information

  LocalPort | ChassisId                 PortId PortDescr SysName
  --------- + ------------------------- ------ --------- ----------------------
  49        | 98 f2 b3 00 00 10         49     49        bn-core
  50        | 98 f2 b3 00 00 10         50     50        bn-core
""",
    "show lacp": """                           LACP

          LACP      Trunk     Port                LACP      Admin   Oper
   Port   Enabled   Group     Status    Partner   Status    Key     Key
   ----   -------   -------   -------   -------   -------   ------  ------
   49     Active    Trk1      Up        Yes       Success   0       451
   50     Active    Trk1      Up        Yes       Success   0       451
""",
}

AOS8 = {
    "show alarms all": "Total number of alarms: 0\n",
    "show cpuload": "user 2.3%, system 4.1%, idle 93.6%\n",
    "show memory": "Memory (Kb): total: 4021788, used: 2211180, free: 1810608\n",
    "show switchinfo": "Hostname is mc1\nReboot Cause: User reboot (Intent:cause:register 78:86:50:2)\n",
    "show port status": """Port Status
-----------
Slot-Port  PortType  AdminState  OperState  PoE  Trusted  SpanningTree  PortMode  Speed     Duplex
---------  --------  ----------  ---------  ---  -------  ------------  --------  -----     ------
GE0/0/0    GE        Enabled     Up         N/A  Yes      Disabled      Trunk     1 Gbps    Full
GE0/0/1    GE        Enabled     Up         N/A  Yes      Disabled      Trunk     1 Gbps    Full
GE0/0/2    GE        Enabled     Down       N/A  Yes      Disabled      Access    Auto      Auto
""",
    "show lldp neighbor": """Interface  Neighbor-name  Capabilities  Neighbor-port  TTL
---------  -------------  ------------  -------------  ---
GE0/0/0    core-sw        B:R           Gi1/0/1        120
GE0/0/1    core-sw        B:R           Gi1/0/2        120
""",
}

OS10 = {
    "show environment": """Unit    State          Temperature
-------------------------------------
1       up             43

Thermal sensors
Unit   Sensor-Id       Sensor-name                                    Temperature
------------------------------------------------------------------------------
1      1               CPU On-Board temp sensor                       35
1      2               Switch board temp sensor                       31
""",
    "show alarms": "Active-alarm details - 0\n-------------------------------------------\n",
    "show processes node-id 1": """top - 10:00:00 up 10 days,  2:03,  1 user,  load average: 0.40, 0.45, 0.41
Tasks: 210 total,   1 running, 209 sleeping,   0 stopped,   0 zombie
%Cpu(s):  5.2 us,  2.1 sy,  0.0 ni, 92.4 id,  0.2 wa,  0.0 hi,  0.1 si,  0.0 st
KiB Mem : 16384000 total,  9011200 free,  5011500 used,  2361300 buff/cache
""",
    "show diff running-configuration startup-configuration": "",
    "show interface status": """---------------------------------------------------------------------------------
Port            Description     Status   Speed    Duplex   Mode Vlan Tagged-Vlans
---------------------------------------------------------------------------------
Eth 1/1/1       server-1        up       25G      full     A    1    -
Eth 1/1/2                       down     0        full     A    1    -
Eth 1/1/49      uplink          up       100G     full     -    -    -
Eth 1/1/50      uplink          up       100G     full     -    -    -
""",
    "show lldp neighbors": """Loc PortID          Rem Host Name          Rem Port Id                    Rem Chassis Id
--------------------------------------------------------------------------------------
ethernet1/1/49      wh-core                ethernet1/1/1                  90:b1:1c:f4:a6:8f
ethernet1/1/50      wh-core                ethernet1/1/2                  90:b1:1c:f4:a6:8f
""",
    "show port-channel summary": """Flags:  D - Down    I - member up but inactive    P - member up and active
        U - Up (port-channel)    F - Fallback Activated
--------------------------------------------------------------------------------
Group Port-Channel           Type     Protocol  Member Ports
--------------------------------------------------------------------------------
10    port-channel10   (U)   Eth      DYNAMIC   1/1/49(P) 1/1/50(P)
""",
}

EXOS = {
    "show power": """PowerSupply 1 information:
 State:             Powered On
 PartInfo:          PS-1 1234567890 800-12345-01
PowerSupply 2 information:
 State:             Powered On
 PartInfo:          PS-2 1234567891 800-12345-01
""",
    "show fans": """FanTray information:
 State:                Operational
 NumFan:               4
 Fan-1:                Operational at 6120 RPM
 Fan-2:                Operational at 6080 RPM
""",
    "show stacking": """Stack Topology is a Daisy-Chain
Active Topology is a Daisy-Chain
Node MAC Address    Slot  Stack State  Role     Flags
------------------  ----  -----------  -------  ---
*00:04:96:11:22:33  1     Active       Master   CA-
 00:04:96:11:22:34  2     Active       Backup   CA-
""",
    "show cpu-monitoring": """CPU Utilization Statistics - Monitored every 5 seconds
-----------------------------------------------------------------------
Process      5    10   30   1    5    30   1    Max       Total
            secs secs secs min  mins mins hour         User/System
-----------------------------------------------------------------------
System        n/a  n/a  0.9  0.4  0.3  0.6  0.3   9.1       0.13   0.06
""",
    "show memory": """System Memory Information
-------------------------
 Total DRAM (KB): 1048576
 System     (KB): 30736
 User       (KB): 563628
 Free       (KB): 454212
""",
    "show ports no-refresh": """Port Summary
Port  Display              VLAN Name          Port  Link  Speed  Duplex
#     String               (or # VLANs)       State State Actual Actual
==================================================================
1:1                        Default            E     A     1000   FULL
1:2                        Default            E     R
1:49                       (0002)             E     A     10G    FULL
1:50                       (0002)             E     A     10G    FULL
""",
    "show lldp neighbors": """Neighbor Neighbor               Neighbor
Port     Chassis ID             Port ID            TTL    Age   System Name
===============================================================================
1:49     00:04:96:AA:BB:CC      1:49               120    10    core-sw
1:50     00:04:96:AA:BB:CC      1:50               120    10    core-sw
""",
    "show sharing": """Load Sharing Monitor
Config    Current Agg     Min    Ld Share  Dist  Ld Share  Agg Link  Link Up
Master    Master  Control Active Algorithm Flags Group     Mbr State Transitions
================================================================================
   1:49     1:49   LACP       1    L2        A     1:49      Y     A        1
                                   L2              1:50      Y     A        1
""",
}

VRP = {
    "display power": """-------------------------------------------------------------------------------
Slot    PowerID  Online   Mode   State      Power(W)
-------------------------------------------------------------------------------
0       PWR1     Present  AC     Supply     350.00
0       PWR2     Present  AC     Supply     350.00
""",
    "display fan": """-------------------------------------------------------------------------------
 Slot  FanID   Online    Status    Speed     Mode     Airflow
-------------------------------------------------------------------------------
 0     1       Present   Normal    50%       Auto     Side-to-Back
 0     2       Present   Normal    50%       Auto     Side-to-Back
""",
    "display alarm active": """Sequence   AlarmId    Severity Date Time  Description
------------------------------------------------------------------------
""",
    "display device": """S5735-L48T4X-A1's Device status:
-------------------------------------------------------------------------------
Slot  Sub  Type                     Online    Power    Register     Status   Role
-------------------------------------------------------------------------------
0     -    S5735-L48T4X-A1          Present   PowerOn  Registered   Normal   Master
""",
    "display cpu-usage": """CPU Usage Stat. Cycle: 60 (Second)
CPU Usage            : 8% Max: 33%
CPU Usage Stat. Time : 2026-10-13  10:00:00
""",
    "display memory-usage": """Memory utilization statistics at 2026-10-13 10:00:00+00:00
System Total Memory Is: 1073741824 bytes
Total Memory Used Is: 412316860 bytes
Memory Using Percentage Is: 38%
""",
    "display reboot-info": """Info: The reboot information is:
Times       Reboot Type       Reboot Time (DST)
------------------------------------------------------------------------
1           USER              2026-10-03 02:00:00
""",
    "display interface brief": """PHY: Physical
*down: administratively down
^down: standby
(l): loopback
(s): spoofing
InUti/OutUti: input utility/output utility
Interface                   PHY      Protocol  InUti OutUti   inErrors  outErrors
Eth-Trunk1                  up       up        0.01%  0.01%          0          0
  GigabitEthernet0/0/47     up       up        0.01%  0.01%          0          0
  GigabitEthernet0/0/48     up       up        0.01%  0.01%          0          0
GigabitEthernet0/0/1        up       up        0.12%  0.05%          0          0
GigabitEthernet0/0/2        down     down         0%     0%          0          0
GigabitEthernet0/0/3        *down    down         0%     0%          0          0
MEth0/0/1                   up       up        0.01%  0.01%          0          0
""",
    "display lldp neighbor brief": """Local Intf       Neighbor Dev             Neighbor Intf             Exptime(s)
GE0/0/47         core-sw                  GE0/0/1                   104
GE0/0/48         core-sw                  GE0/0/2                   104
""",
    "display eth-trunk": """Eth-Trunk1's state information is:
WorkingMode: NORMAL           Hash arithmetic: According to SIP-XOR-DIP
Least Active-linknumber: 1    Max Bandwidth-affected-linknumber: 8
Operate status: up            Number Of Up Port In Trunk: 2
--------------------------------------------------------------------------------
PortName                      Status      Weight
GigabitEthernet0/0/47         Up          1
GigabitEthernet0/0/48         Up          1
""",
}

XR = {
    "show environment power": """================================================================================
CHASSIS LEVEL POWER INFO: 0
================================================================================
   Total output power capacity (Group 0 + Group 1) :    2000W +        0W
   Total output power required                     :     850W
   Total power input                               :     420W
   Total power output                              :     360W

================================================================================
   Power       Supply         ------Input----   ------Output---     Status
   Module      Type            Volts     Amps    Volts     Amps
================================================================================
   0/PM0       2kW-AC          230.0     0.9     12.0     15.0      OK
   0/PM1       2kW-AC          230.0     0.9     12.0     15.0      OK
""",
    "show environment fan": """=====================================================
                                           Fan speed (rpm)
Location     FRU Type                      FAN_0    FAN_1
-----------------------------------------------------
0/FT0        NC55-A1-FAN-FW                 7200     7140
0/FT1        NC55-A1-FAN-FW                 7230     7170
""",
    "show alarms brief system active": """------------------------------------------------------------------------------------
Active Alarms
------------------------------------------------------------------------------------
Location        Severity     Group            Set Time                   Description
------------------------------------------------------------------------------------
""",
    "show platform": """Node              Type                       State                    Config state
--------------------------------------------------------------------------------
0/RP0/CPU0        NCS-55A1-24H(Active)       IOS XR RUN               NSHUT
0/PM0             NC55-1200W-ACFW            OPERATIONAL              NSHUT
0/PM1             NC55-1200W-ACFW            OPERATIONAL              NSHUT
0/FT0             NC55-A1-FAN-FW             OPERATIONAL              NSHUT
0/FT1             NC55-A1-FAN-FW             OPERATIONAL              NSHUT
""",
    "show processes cpu | include CPU utilization":
        "CPU utilization for one minute: 3%; five minutes: 4%; fifteen minutes: 4%\n",
    "show memory summary": """node:      node0_RP0_CPU0
------------------------------------------------------------------
Physical Memory: 16384M total (12000M available)
 Application Memory : 15800M (11500M available)
 Image: 4M (bootram: 0M)
""",
    "show ipv4 interface brief": """Interface                      IP-Address      Status          Protocol Vrf-Name
Loopback0                      10.0.0.1        Up              Up       default
MgmtEth0/RP0/CPU0/0            192.0.2.31      Up              Up       default
HundredGigE0/0/0/0             10.1.1.1        Up              Up       default
HundredGigE0/0/0/1             unassigned      Shutdown        Down     default
Bundle-Ether1                  10.1.2.1        Up              Up       default
""",
    "show lldp neighbors": """Capability codes:
        (R) Router, (B) Bridge, (T) Telephone, (C) DOCSIS Cable Device
Device ID       Local Intf               Hold-time  Capability     Port ID
pe2             HundredGigE0/0/0/0       120        R              HundredGigE0/0/0/0

Total entries displayed: 1
""",
    "show bundle brief": """Name   | IG     | State       | LACP | BFD |   Links   | Local b/w, |
       |        |             |      |     |  act/stdby/cfgd | kbps       |
-------|--------|-------------|------|-----|-----------|------------|
BE1      -        Up            On     Off   2 / 0 / 2   200000000
""",
}

AWPLUS = {
    "show system environment": """Environment Monitoring Status
Overall Status: Normal

Resource ID: 1  Name: x930-28GTX
ID  Sensor (Units)                         Reading  Low Limit High Limit Status
1   Fan: Fan 1 (Rpm)                       6923     3000      -          Ok
2   Voltage: 2.5V (Volts)                  2.506    2.243     2.744      Ok
3   Temp: Internal (Degrees C)             38       -         80         Ok
""",
    "show stack": """Virtual Chassis Stacking summary information

ID  Pending ID MAC address         Priority Status           Role
1   -          0000.cd28.0001      128      Ready            Active Master
""",
    "show cpu": """Stack member 1:

CPU averages:
  1 second: 6%, 20 seconds: 4%, 60 seconds: 3%
System load averages:
  1 minute: 0.12, 5 minutes: 0.14, 15 minutes: 0.15
""",
    "show memory": "Stack member 1:\n\nRAM total: 1022540 kB; free: 597720 kB; buffers: 51632 kB\n",
    "show reboot history": """<date>     <time>   <type>     <description>
-----------------------------------------------
2026-10-03 02:00:00 Expected   User Request
""",
    "show interface brief": """Interface             Status          Protocol
port1.0.1             admin up        running
port1.0.2             admin up        down
port1.0.27            admin up        running
port1.0.28            admin up        running
po1                   admin up        running
vlan1                 admin up        running
""",
    "show lldp neighbors": """Local Port    Chassis ID          Port ID               TTL    Name
port1.0.27    0000.cd29.0001      port1.0.1             104    bs-core
port1.0.28    0000.cd29.0001      port1.0.2             104    bs-core
""",
    "show etherchannel": """ ----------------------------------------------------------------------------
 Channel Group 1
   Aggregator po1 (IfIndex 4601)
   Admin Key: 0001 - Oper Key 0001
     Link: port1.0.27 (IfIndex 5027) sync: 1
     Link: port1.0.28 (IfIndex 5028) sync: 1
""",
}

ROUTEROS = {
    "/system health print": """Columns: NAME, VALUE, TYPE
#  NAME         VALUE  TYPE
0  temperature  44     C
1  fan1-speed   5520   RPM
2  psu1-state   ok
3  psu2-state   ok
""",
    "/interface print terse": """ 0  R  name=ether1 default-name=ether1 type=ether mtu=1500
 1  R  name=sfp-sfpplus1 default-name=sfp-sfpplus1 type=ether mtu=1500
 2  R  name=sfp-sfpplus2 default-name=sfp-sfpplus2 type=ether mtu=1500
 3  X  name=ether2 default-name=ether2 type=ether mtu=1500
 4     name=ether3 default-name=ether3 type=ether mtu=1500
""",
    "/ip neighbor print terse": (
        " 0 interface=sfp-sfpplus1 mac-address=48:A9:8A:00:00:01 identity=bn-sw1 "
        "platform=ArubaOS version=16.11\n"
        " 1 interface=sfp-sfpplus2 mac-address=48:A9:8A:00:00:02 identity=bn-sw2 "
        "platform=ArubaOS version=16.11\n"),
}

EDGEOS = {
    "show system memory": "Total: 2002308\nFree:  1503104\nUsed:  499204\n",
    "show interfaces": """Codes: S - State, L - Link, u - Up, D - Down, A - Admin Down
Interface    IP Address                        S/L  Description
---------    ----------                        ---  -----------
eth0         192.0.2.41/24                     u/u  WAN
eth1         10.0.1.1/24                       u/u  LAN
eth2         -                                 A/D
lo           127.0.0.1/8                       u/u
switch0      -                                 u/u
""",
    "show lldp neighbors": """-------------------------------------------------------------------------------
LLDP neighbors:
-------------------------------------------------------------------------------
Interface:    eth1, via: LLDP, RID: 1, Time: 10 days, 02:03:04
  Chassis:
    ChassisID:    mac 00:11:22:33:44:55
    SysName:      lan-sw
-------------------------------------------------------------------------------
""",
}

ASA = {
    "show cpu usage": samples.ASA_CPU,
    "show memory": samples.ASA_MEM,
    "show environment": """Cooling Fans:
-----------------------------------
  Chassis Fans:
  --------------------------------
    Cooling Fan 1: 9200 RPM - OK (Fan Speed Normal)
    Cooling Fan 2: 9150 RPM - OK (Fan Speed Normal)

Power Supplies:
-----------------------------------
  Left PS: Present - OK
  Right PS: Present - OK

Temperature:
-----------------------------------
  Processors:
  --------------------------------
    Processor 1: 42.0 C - OK (CPU1 Core Temperature)
""",
    "show port-channel summary": """Flags:  D - down        P - bundled in port-channel
        I - stand-alone s - suspended
        U - in use      N - not in use, no aggregation/nameif
Number of channel-groups in use: 1
Group  Port-channel  Protocol  Span-cluster  Ports
------+-------------+---------+------------+------------------------------------
1      Po1(U)            LACP          No     Gi0/0(P)   Gi0/1(P)
""",
}

HEALTHY: dict[str, dict[str, str]] = {
    "arista_eos": ARISTA, "cisco_nxos": NXOS, "juniper_junos": JUNOS,
    "aruba_osswitch": OSSWITCH, "aruba_aos8": AOS8, "dell_os10": OS10, "extreme_exos": EXOS,
    "huawei_vrp": VRP, "cisco_xr": XR, "allied_awplus": AWPLUS, "mikrotik_routeros": ROUTEROS,
    "ubiquiti_edgeos": EDGEOS, "cisco_asa": ASA,
}

# Broken versions, for the tests: platform -> command -> output.
FAULTS: dict[str, dict[str, str]] = {
    "arista_eos": {
        "show system environment all": ARISTA["show system environment all"].replace(
            "2             PWR-500AC-F   500W      0.60A          8.90A           106.8W        Ok",
            "2             PWR-500AC-F   500W      0.00A          0.00A           0.0W          powerLoss"),
        "show running-config diffs": """--- system:/running-config
+++ session:/running-config
@@ -40,3 +40,5 @@
 interface Ethernet4
+   description test port
+   shutdown
""",
        "show port-channel summary": ARISTA["show port-channel summary"].replace(
            "Et50/1(PG+)", "Et50/1(G)"),
        "show reload cause": ARISTA["show reload cause"].replace(
            "Reload requested by the user.", "The system rebooted due to a Power Loss"),
    },
    "cisco_nxos": {
        "show module": NXOS["show module"].replace("N9K-C93180YC-FX     active *",
                                                   "N9K-C93180YC-FX     failure"),
        "show system resources": NXOS["show system resources"].replace("95.00% idle", "4.00% idle"),
    },
    "juniper_junos": {
        "show chassis alarms": """1 alarms currently active
Alarm time               Class  Description
2026-10-13 09:12:01 UTC  Major  FPC 0 PEM 1 Not Powered
""",
        "show chassis environment": JUNOS["show chassis environment"].replace(
            "FPC 0 Fan Tray 0 Fan 1         OK         Spinning at normal speed",
            "FPC 0 Fan Tray 0 Fan 1         Failed"),
        "show lacp interfaces": JUNOS["show lacp interfaces"].replace(
            "xe-0/0/2                  Current   Fast periodic Collecting distributing",
            "xe-0/0/2                  Defaulted Fast periodic           Attached"),
    },
}
