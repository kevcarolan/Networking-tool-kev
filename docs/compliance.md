# Config compliance

Rules every backed-up config is checked against: "every switch has an NTP server", "no
Telnet", "SSH version 2"... Open it from **Config backups › Compliance**.

## Rules

A rule has:

* a **name**, and what it checks (shown to everyone);
* a **kind**:
  * **must have**: every line listed must be in the config;
  * **must not have**: any line listed fails it;
* the **config lines**, one per line. Without **patterns**, a line matches when it is the
  same as a config line, ignoring spaces at either end. With **patterns** (regular
  expressions), each one is searched in every config line: `^ntp server ` finds any NTP
  server, `transport input (telnet|all)` finds Telnet on a vty line;
* the **platforms** and **sites** it applies to (none ticked: all);
* a **severity**: *critical* or *warning*;
* **on** or off.

**Add example rules (Cisco IOS)** adds a starting set: NTP server set, syslog to a server,
SSH version 2, no Telnet, no plain HTTP server, passwords encrypted, AAA, no default SNMP
communities. Change or delete them to suit the site.

## When configs are checked

* After every successful backup, on the config just saved.
* When a rule is added or changed, every device's latest config straight away.
* **Check now** checks every device's latest config again. No device is contacted: the
  stored configs are used.

## The results

* **Config backups › Compliance:** tiles (rules, devices compliant, devices failing,
  critical failures), every failure (device, rule, since when), and every rule with how
  many devices pass and fail it. **Export CSV** for an audit.
* A device's **History › Compliance** tab: each rule that applies, pass or fail.
* The device list shows **⚠ N compliance rule(s)** under a device that fails any.
* The missing or offending **config lines** are shown only to people with
  **Config backups: read configs**, because configs hold secrets. Everyone else sees pass
  or fail.
* **Email alerts › Compliance:** an email when a device starts failing a rule (once per
  failure; config lines are never put in the email).
* The wall display's overview and sites pages count devices failing compliance; the
  report has a compliance section.

## Who can do what

| Permission | Compliance |
|---|---|
| Config backups: view | See the rules and pass or fail, export |
| Config backups: run | Also **Check now** |
| Config backups: read configs | Also see the config lines in the results |
| Config backups: manage | Also add, change and delete rules |

Compliance is part of the Config backups licence. Every rule change is in the activity
report.
