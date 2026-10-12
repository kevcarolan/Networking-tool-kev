"""Syslog: reading device messages, the receiver, the store (one file per day, retention),
the Syslog page's API, the setup help and the demo messages."""

import asyncio
import datetime as dt
import socket
import time

import pytest

from app.core.platforms import PLATFORMS
from app.tools.syslog import howto
from app.tools.syslog.parse import body, parse
from app.tools.syslog.receiver import Receiver, split_frames
from app.tools.syslog.store import Filter, Record, SyslogStore, day_start

# --- reading messages -----------------------------------------------------------------

SAMPLES = [  # (line, severity, facility, host, tag)
    ("<189>45: core-sw1: Oct 12 16:00:01.123 UTC: %SYS-5-CONFIG_I: Configured from console by admin on vty0",
     5, 23, "core-sw1", "%SYS-5-CONFIG_I"),
    ("<187>123: *Mar  1 00:00:12.345: %LINK-3-UPDOWN: Interface GigabitEthernet1/0/1, changed state to down",
     3, 23, "", "%LINK-3-UPDOWN"),
    ("<166>Oct 12 2026 16:00:01: %ASA-6-302013: Built inbound TCP connection 1 for outside:1.2.3.4/5",
     6, 20, "", "%ASA-6-302013"),
    ("<189>: 2026 Oct 12 16:00:01 UTC: %ETHPORT-5-IF_UP: Interface Ethernet1/1 is up", 5, 23, "", "%ETHPORT-5-IF_UP"),
    ("<38>Oct 12 16:00:01 host1 sshd[123]: Accepted password for x", 6, 4, "host1", "sshd"),
    ("<28>Oct 12 16:00:01 sw1 mib2d[1234]: SNMP_TRAP_LINK_DOWN: ifIndex 1", 4, 3, "sw1", "mib2d"),
    ("<165>1 2026-10-12T16:00:01.000Z fw1 sshd 123 ID47 - Failed login", 5, 20, "fw1", "sshd"),
    ("<190>Oct 12 16:00:01 bn-sw1 00076 ports: port 12 is now on-line", 6, 23, "bn-sw1", "ports"),
    ("<30>Oct 12 16:00:01 rtr1 system,info,account: user admin logged in", 6, 3, "rtr1", "system,info,account"),
    ("<190>Oct 12 17:51:24 wh-sw2 dn_alm[1203]: Node.1-Unit.1:PRI [event], Dell EMC (OS10) "
     "%IFM_OSTATE_UP: Interface operational state is up :ethernet1/1/4", 6, 23, "wh-sw2", "%IFM_OSTATE_UP"),
    ('<189>date=2026-10-12 time=16:00:01 devname="fw1" logid="0100032001" level="notice" msg="x"',
     5, 23, "", "fortigate"),
    ("no priority at all", 5, 1, "", ""),
    ("<999>out of range", 5, 1, "", ""),
]


@pytest.mark.parametrize("line, sev, fac, host, tag", SAMPLES)
def test_messages_from_each_kind_of_device_are_read(line, sev, fac, host, tag):
    m = parse(line)
    assert (m.severity, m.facility, m.host, m.tag) == (sev, fac, host, tag)
    if line.startswith("<") and tag:
        assert not m.text.startswith("<")  # the priority is taken off, the rest kept


def test_the_page_shows_the_message_from_its_code_on():
    m = parse(SAMPLES[0][0])
    assert body(m.text, m.tag) == "%SYS-5-CONFIG_I: Configured from console by admin on vty0"
    assert m.text.startswith("45: core-sw1: Oct 12")  # nothing lost


def test_odd_bytes_and_long_messages_are_made_safe():
    m = parse(b"<11>x \x00\x01\x1b[31m caf\xc3\xa9 \xff" + b"A" * 20000)
    assert "\x00" not in m.text and "\x1b" not in m.text and "café" in m.text
    assert len(m.text) <= 8192


def test_tcp_framing_by_length_and_by_line():
    frames, rest = split_frames(b"<34>one\n11 <34>1 two!!<34>three")
    assert frames == [b"<34>one", b"<34>1 two!!"] and rest == b"<34>three"
    frames, rest = split_frames(rest + b"\r\n")
    assert frames == [b"<34>three"] and rest == b""
    frames, rest = split_frames(b"30 <34>short")  # waits for the rest
    assert frames == [] and rest == b"30 <34>short"


# --- the store ------------------------------------------------------------------------

def _rec(ts, src="10.0.0.1", sev=6, text="hello", tag="x"):
    return Record(ts, src, sev, 23, "", tag, text)


@pytest.fixture
def store(tmp_path):
    s = SyslogStore(tmp_path / "syslog")
    yield s
    s.close()


def test_one_file_per_day_and_search_across_days_newest_first(store):
    d1 = day_start(dt.date(2026, 10, 10))
    store.write([_rec(d1 + i * 3600, text=f"day1 {i}") for i in range(24)])
    store.write([_rec(d1 + 86400 + i * 3600, text=f"day2 {i}") for i in range(24)])
    assert store.days() == [dt.date(2026, 10, 10), dt.date(2026, 10, 11)]
    f = Filter(d1, d1 + 2 * 86400)
    seen, cursor = [], None
    while True:
        rows, cursor = store.search(f, limit=10, before=cursor)
        seen += [r["text"] for r in rows]
        if not cursor:
            break
    assert len(seen) == 48 and seen[0] == "day2 23" and seen[-1] == "day1 0"
    assert len(set(seen)) == 48  # no repeats across pages or days


def test_filters_by_sender_severity_text_and_time(store):
    t = day_start(dt.date(2026, 10, 10)) + 3600
    store.write([_rec(t, "10.0.0.1", 3, "Gi1/0/5 down", "%LINK-3-UPDOWN"),
                 _rec(t + 1, "10.0.0.2", 4, "100%_full disk"),
                 _rec(t + 2, "10.0.0.3", 6, "login ok"),
                 _rec(t + 7200, "10.0.0.1", 2, "PSU failed")])
    def texts(**kw):
        return [r["text"] for r in store.search(Filter(t - 10, t + 10000, **kw))[0]]

    assert texts(sources=["10.0.0.1"]) == ["PSU failed", "Gi1/0/5 down"]
    assert texts(exclude=["10.0.0.1", "10.0.0.2"]) == ["login ok"]
    assert texts(severities=[0, 1, 2, 3]) == ["PSU failed", "Gi1/0/5 down"]
    assert texts(text="%LINK") == ["Gi1/0/5 down"]  # the code too
    assert texts(text="100%_") == ["100%_full disk"]  # % and _ are plain characters
    assert texts(text="GI1/0/5") == ["Gi1/0/5 down"]  # any case
    assert texts(sources=[]) == []
    assert [r["text"] for r in store.search(Filter(t - 10, t + 100))[0]] == \
        ["login ok", "100%_full disk", "Gi1/0/5 down"]


def test_counts_and_timeline(store):
    t = day_start(dt.date(2026, 10, 10))
    store.write([_rec(t + 10, sev=3), _rec(t + 20, sev=3), _rec(t + 3700, sev=4, src="10.0.0.9")])
    s = store.summary(Filter(t, t + 7200), buckets=2)
    assert s["severity"][3] == 2 and s["severity"][4] == 1
    assert s["sources"] == {"10.0.0.1": 2, "10.0.0.9": 1}
    assert s["timeline"][0][3] == 2 and s["timeline"][1][4] == 1


def test_old_days_go_first_by_age_and_by_size(store):
    today = dt.date(2026, 10, 12)
    for back in range(5):
        day = today - dt.timedelta(days=back)
        store.write([_rec(day_start(day) + 60, text="x" * 2000) for _ in range(50)])
    store.close()
    assert store.prune(keep_days=3, max_bytes=10**9, today=today) == \
        [dt.date(2026, 10, 8), dt.date(2026, 10, 9)]
    one_day = store.size(today)
    assert store.prune(keep_days=30, max_bytes=one_day + 10, today=today) == \
        [dt.date(2026, 10, 10), dt.date(2026, 10, 11)]
    assert store.days() == [today]
    assert store.prune(keep_days=30, max_bytes=1, today=today) == []  # never today


# --- the receiver ---------------------------------------------------------------------

@pytest.fixture
def receiver(settings, store):
    return Receiver(settings, store)


def test_one_chatty_sender_is_limited_the_others_not(receiver, settings):
    settings.syslog_rate_per_source = 50
    for _ in range(500):
        receiver.accept(b"<14>flood", "10.0.0.66")
    receiver.accept(b"<14>quiet one", "10.0.0.7")
    assert receiver.counts["dropped_rate"] >= 400
    assert any(r.src == "10.0.0.7" for r in receiver.queue)
    receiver.flush()
    assert 51 <= receiver.counts["stored"] <= 60 and not receiver.queue


def test_only_inventory_devices_when_set(app, admin, device, settings, receiver):
    settings.syslog_inventory_only = True
    from app.core import appsettings
    from app.core.db import session_scope

    with session_scope() as db:
        appsettings.save(db, {"syslog_inventory_only": "true"}, "test")
    receiver.housekeeping()
    receiver.accept(b"<14>from the device", "::ffff:10.0.0.1")  # IPv4 written as IPv6
    receiver.accept(b"<14>from a stranger", "10.9.9.9")
    assert [r.src for r in receiver.queue] == ["10.0.0.1"]
    assert receiver.counts["dropped_unknown"] == 1


def test_storing_stops_while_the_disk_is_nearly_full(receiver, settings, monkeypatch):
    import shutil as sh

    monkeypatch.setattr(sh, "disk_usage", lambda p: type("U", (), {"free": 10 * 2**20})())
    receiver.check_space()
    assert "disk" in receiver.full
    receiver.accept(b"<14>lost", "10.0.0.1")
    assert receiver.counts["dropped_full"] == 1 and not receiver.queue
    assert receiver.status()["stopped_reason"] == receiver.full


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_receives_over_udp_and_tcp(settings, store):
    settings.syslog_bind = "127.0.0.1"
    settings.syslog_udp_port = settings.syslog_tcp_port = _free_port()
    rx = Receiver(settings, store)
    rx.housekeeping = lambda: None  # no database in this test (settings, inventory)

    async def run():
        task = asyncio.create_task(rx.serve())
        await asyncio.sleep(0.3)
        port = settings.syslog_udp_port
        u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        u.sendto(b"<187>%LINK-3-UPDOWN: Interface Gi1/0/1, changed state to down", ("127.0.0.1", port))
        u.close()
        r, w = await asyncio.open_connection("127.0.0.1", port)
        w.write(b"<38>Oct 12 16:00:01 h sshd[1]: over tcp\n15 <34>1 - h a - -")
        await w.drain()
        w.close()
        await asyncio.sleep(1.5)
        rx.stop()
        await task

    asyncio.run(run())
    rows, _ = store.search(Filter(time.time() - 60, time.time() + 60))
    assert sorted(r["tag"] for r in rows) == ["%LINK-3-UPDOWN", "a", "sshd"]
    assert (store.dir / "status.json").exists()


# --- the API ----------------------------------------------------------------------------

@pytest.fixture
def messages(settings, device):
    now = time.time()
    s = SyslogStore(settings.syslog_dir)
    s.write([_rec(now - 60, "10.0.0.1", 3, "%LINK-3-UPDOWN: Gi1/0/5 down", "%LINK-3-UPDOWN"),
             _rec(now - 50, "10.0.0.1", 6, "login ok", "sshd"),
             _rec(now - 40, "192.0.2.250", 4, "ap radio warning", "hostapd"),
             _rec(now - 3 * 86400, "10.0.0.1", 2, "old PSU failure")])
    s.close()
    return now


def test_search_by_device_severity_and_text(admin, device, messages):
    r = admin.get("/api/syslog/messages").json()
    assert [m["text"] for m in r["rows"]] == ["ap radio warning", "login ok",
                                              "%LINK-3-UPDOWN: Gi1/0/5 down"]
    assert r["rows"][1]["device"] == "core-sw1" and r["rows"][0]["device"] is None
    assert r["rows"][2]["severity"] == "error" and r["rows"][2]["message"].startswith("%LINK")
    one = admin.get("/api/syslog/messages", params={"device": device["id"]}).json()["rows"]
    assert {m["src"] for m in one} == {"10.0.0.1"}
    unknown = admin.get("/api/syslog/messages", params={"device": "unknown"}).json()["rows"]
    assert [m["src"] for m in unknown] == ["192.0.2.250"]
    bad = admin.get("/api/syslog/messages", params={"severities": "0,1,2,3"}).json()["rows"]
    assert [m["sev"] for m in bad] == [3]
    assert admin.get("/api/syslog/messages", params={"q": "radio"}).json()["rows"][0]["tag"] == "hostapd"
    week = admin.get("/api/syslog/messages", params={
        "since": dt.datetime.fromtimestamp(messages - 7 * 86400, dt.UTC).isoformat()}).json()
    assert len(week["rows"]) == 4


def test_pages_of_messages(admin, settings, device):
    now = time.time()
    s = SyslogStore(settings.syslog_dir)
    s.write([_rec(now - 1000 + i, text=f"m{i}") for i in range(25)])
    s.close()
    first = admin.get("/api/syslog/messages", params={"limit": 10}).json()
    second = admin.get("/api/syslog/messages", params={"limit": 10, "before": first["next"]}).json()
    assert first["rows"][0]["text"] == "m24" and second["rows"][0]["text"] == "m14"


def test_counts_name_the_devices(admin, device, messages):
    s = admin.get("/api/syslog/summary").json()
    assert s["severity"][3] == 1 and s["severity"][4] == 1 and s["severity"][6] == 1
    assert s["devices"] == [{"device_id": device["id"], "device": "core-sw1", "count": 2,
                             "addresses": ["10.0.0.1"]}]
    assert s["unknown"] == [{"source": "192.0.2.250", "count": 1}]
    assert sum(sum(b) for b in s["timeline"]) == 3


def test_download_is_plain_text_and_in_the_activity_log(admin, device, messages):
    r = admin.get("/api/syslog/export.log")
    assert r.headers["content-type"].startswith("text/plain")
    lines = r.text.splitlines()
    assert len(lines) == 3 and " 10.0.0.1 core-sw1 error local7 %LINK-3-UPDOWN" in lines[0]
    assert admin.get("/api/audit").json()[0]["action"] == "syslog.export"


def test_bad_periods_are_refused(admin):
    assert admin.get("/api/syslog/messages", params={
        "since": "2026-10-12T10:00:00Z", "until": "2026-10-12T09:00:00Z"}).status_code == 422
    assert admin.get("/api/syslog/messages", params={
        "since": "2020-01-01T00:00:00Z", "until": "2026-01-01T00:00:00Z"}).status_code == 422
    assert admin.get("/api/syslog/messages", params={"severities": "9"}).status_code == 422
    assert admin.get("/api/syslog/messages", params={"before": "x"}).status_code == 422


def test_status_shows_whether_the_receiver_runs(admin, settings, store):
    assert admin.get("/api/syslog/status").json()["running"] is False
    Receiver(settings, SyslogStore(settings.syslog_dir)).write_status()
    s = admin.get("/api/syslog/status").json()
    assert s["running"] is True and s["keep_days"] == 30 and s["max_bytes"] == 20 * 2**30


def test_who_may_see_syslog(app, admin, messages):
    from fastapi.testclient import TestClient

    from tests.test_users import _add, _login

    _add(admin, "nolog", permissions={"syslog": "none"})
    _add(admin, "older")  # saved without a syslog level, like users made before it existed
    with TestClient(app) as c:
        _login(c, "nolog")
        assert c.get("/api/syslog/messages").status_code == 403
        _login(c, "older")
        assert c.get("/api/syslog/messages").status_code == 200


def test_settings_page_has_the_limits(admin):
    keys = {o["key"] for o in admin.get("/api/setup/options").json()}
    assert {"syslog_keep_days", "syslog_max_gb", "syslog_inventory_only"} <= keys


# --- setup help and the demo --------------------------------------------------------------

def test_help_covers_every_platform(admin):
    r = admin.get("/api/syslog/howto").json()
    covered = {p["platform"] for p in r["platforms"]}
    assert set(PLATFORMS) <= covered
    assert all("{server}" in p["text"] for p in howto.HOWTO)
    assert r["server"] == "testserver"


def test_demo_messages_show_every_severity_and_parse():
    from collections import Counter

    from app.demo import seed
    from app.demo.syslog import UNKNOWN_AP, history

    records = history(now=day_start(dt.date(2026, 10, 12)) + 15 * 3600)
    sev = Counter(r.sev for r in records)
    assert all(sev[s] for s in range(7))  # emergency to informational
    assert all(r.tag for r in records)
    senders = {r.src for r in records}
    assert UNKNOWN_AP in senders
    assert {seed.address(i) for i in range(len(seed.DEVICES))} <= senders
    texts = " ".join(r.text for r in records)
    for story in ("Hold timer expired", "PS_FAIL", "BLOCK_BPDUGUARD", "203.0.113.66",
                  "phase1 negotiation failed", "Lost Failover communications"):
        assert story in texts
