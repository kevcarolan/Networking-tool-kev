"""Reading one syslog message as devices send it.

Devices differ: RFC 5424 (``<PRI>1 TIMESTAMP HOST APP ...``), the older RFC 3164
(``<PRI>Oct 12 16:00:01 host tag: text``), Cisco IOS/NX-OS/ASA with their own counters
and ``%FAC-SEV-MNEMONIC`` codes, FortiGate ``key=value`` lines. Only the priority (and so
the severity and facility) is read strictly. The rest of the line is kept as it came,
so nothing is lost; the host name and a short tag (``%LINK-3-UPDOWN``, ``sshd``) are
picked out when they can be found, for display and search.

The sender is always the source address of the packet or connection, never the host
name in the message, which any sender can write.
"""

import re
from dataclasses import dataclass

SEVERITIES = ("emergency", "alert", "critical", "error", "warning", "notice", "info", "debug")
LABELS = ("Emergency", "Alert", "Critical", "Error", "Warning", "Notice", "Informational", "Debug")
FACILITIES = ("kern", "user", "mail", "daemon", "auth", "syslog", "lpr", "news", "uucp", "cron",
              "authpriv", "ftp", "ntp", "audit", "alert", "clock", "local0", "local1", "local2",
              "local3", "local4", "local5", "local6", "local7")

MAX_LENGTH = 8192  # longer messages are cut (a UDP packet can't carry much more anyway)

_PRI = re.compile(r"^<(\d{1,3})>")
_RFC5424 = re.compile(r"^1 (\S+) (\S+) (\S+) (\S+) (\S+) ")
_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
# "Oct 12 16:00:01", "Oct  2 2026 16:00:01", "*Oct 12 16:00:01.123", "2026 Oct 12 16:00:01"
_STAMP = re.compile(r"^\*?(?:\d{4} )?" + _MONTH + r"\s+\d{1,2}(?: \d{4})? \d\d:\d\d:\d\d(?:\.\d+)?"
                    r"(?: [A-Z]{2,5})?:? ")
_CISCO_CODE = re.compile(r"%([A-Z][A-Z0-9_]*(?:-[A-Z0-9_]+)?)-([0-7])-([A-Z0-9_]+)")
_TAG = re.compile(r"^([A-Za-z0-9_./-]{1,48})(?:\[\d+\])?: ")
_HOST_THEN_TAG = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.-]{0,62}) (?=[A-Za-z0-9_./-]{1,48}(?:\[\d+\])?: )")
_KV_LEVEL = re.compile(r'\blevel="?(emergency|alert|critical|error|warning|notice|information|debug)')


@dataclass
class Message:
    severity: int  # 0 emergency .. 7 debug
    facility: int
    host: str  # the host name written in the message, if any (not trusted)
    tag: str  # program or message code, e.g. "%LINK-3-UPDOWN", "sshd"
    text: str  # the message without its priority


def parse(raw: bytes | str) -> Message:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    line = raw.replace("\x00", "").strip("\r\n ")[:MAX_LENGTH]
    line = "".join(c if c >= " " or c == "\t" else " " for c in line)
    m = _PRI.match(line)
    if m and int(m.group(1)) <= 191:
        pri = int(m.group(1))
        rest = line[m.end():]
    else:
        pri, rest = 13, line  # RFC 3164: no priority means user.notice
    severity, facility = pri & 7, pri >> 3
    host, tag = "", ""

    m5 = _RFC5424.match(rest)
    if m5:
        host = "" if m5.group(2) == "-" else m5.group(2)
        tag = "" if m5.group(3) == "-" else m5.group(3)
    else:
        body = rest.lstrip(": ")
        body = re.sub(r"^\d+: ", "", body)  # Cisco sequence number
        stamp = _STAMP.match(body)
        if stamp:
            body = body[stamp.end():]
            h = _HOST_THEN_TAG.match(body)  # "host tag: text"
            if h:
                host, body = h.group(1), body[h.end():]
        else:
            h = re.match(r"^([A-Za-z0-9][A-Za-z0-9_.-]{0,62}): ", body)  # IOS "host: stamp"
            if h and _STAMP.match(body[h.end():]):
                host = h.group(1)
        t = _TAG.match(body)
        if t:
            tag = t.group(1)

    code = _CISCO_CODE.search(rest[:200])
    if code:
        tag = f"%{code.group(1)}-{code.group(2)}-{code.group(3)}"
    elif not tag:
        kv = _KV_LEVEL.search(rest)
        if kv and "logid=" in rest:
            tag = "fortigate"
    return Message(severity=severity, facility=facility, host=host[:64], tag=tag[:64],
                   text=rest.strip().lstrip(": "))


def severity_label(sev: int) -> str:
    return LABELS[sev] if 0 <= sev < len(LABELS) else str(sev)


def facility_name(fac: int) -> str:
    return FACILITIES[fac] if 0 <= fac < len(FACILITIES) else str(fac)
