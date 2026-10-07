"""Keeps what the switches report (MAC and ARP tables) and answers "where is this MAC"."""

from collections import defaultdict
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.tools.circuits.live import DeviceRead, Seen
from app.tools.circuits.models import DeviceScanState, LiveArp, LiveMac, MacLastSeen


def _state(db: Session, device_id: int) -> DeviceScanState:
    st = db.get(DeviceScanState, device_id)
    if st is None:
        st = DeviceScanState(device_id=device_id)
        db.add(st)
    return st


def save_read(db: Session, device_id: int, read: DeviceRead, now: datetime | None = None) -> None:
    """Replace the device's tables with this read. A table that couldn't be read
    (None) keeps its previous rows."""
    now = now or utcnow()
    st = _state(db, device_id)
    st.last_attempt = st.last_success = now
    st.last_error = ""
    if read.macs is not None:
        db.execute(delete(LiveMac).where(LiveMac.device_id == device_id))
        db.add_all(LiveMac(device_id=device_id, mac_norm=e.mac, vlan=e.vlan, port=e.port,
                           port_norm=e.port_norm, uplink=e.uplink, seen_at=now)
                   for e in read.macs)
        st.mac_count = len(read.macs)
        for e in read.edge:
            last = db.get(MacLastSeen, e.mac)
            if last is None:
                db.add(MacLastSeen(mac_norm=e.mac, device_id=device_id, port=e.port,
                                   vlan=e.vlan, seen_at=now))
            else:
                last.device_id, last.port, last.vlan, last.seen_at = device_id, e.port, e.vlan, now
    if read.arps is not None:
        db.execute(delete(LiveArp).where(LiveArp.device_id == device_id))
        db.add_all(LiveArp(device_id=device_id, ip=ip, mac_norm=mac, seen_at=now)
                   for ip, mac in read.arps)
        st.arp_count = len(read.arps)
    db.flush()


def save_failure(db: Session, device_id: int, error: str, now: datetime | None = None) -> None:
    st = _state(db, device_id)
    st.last_attempt, st.last_error = now or utcnow(), (error or "failed")[:2000]


class LiveIndex:
    """Everything needed to locate circuits, loaded once per request."""

    def __init__(self, db: Session):
        self.edges: dict[str, list[Seen]] = defaultdict(list)
        self.seen_at: dict[int, datetime] = {}
        for m in db.scalars(select(LiveMac).where(LiveMac.uplink.is_(False))):
            self.edges[m.mac_norm].append(Seen(m.device_id, m.port, m.port_norm, m.vlan))
        self.arp: dict[str, str] = {}
        for a in db.scalars(select(LiveArp).order_by(LiveArp.seen_at)):
            self.arp[a.ip] = a.mac_norm  # newest wins
        self.last_seen: dict[str, MacLastSeen] = {
            r.mac_norm: r for r in db.scalars(select(MacLastSeen))}
        self.scanned: dict[int, DeviceScanState] = {
            s.device_id: s for s in db.scalars(select(DeviceScanState))}

    @property
    def has_data(self) -> bool:
        return bool(self.scanned)
