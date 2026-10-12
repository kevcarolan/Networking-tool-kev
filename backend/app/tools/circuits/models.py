"""Master circuit list tables (prefix ``ct_``). Every upload is kept as an
import; exactly one import is "active" and is the current circuit list."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, utcnow

PENDING, ACTIVE, SUPERSEDED = "pending", "active", "superseded"


class CircuitImport(Base):
    __tablename__ = "ct_imports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    sheet: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(20), default=PENDING, index=True)
    uploaded_by: Mapped[str] = mapped_column(String(200))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    committed_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[str] = mapped_column(Text, default="{}")  # JSON: columns, diff, samples


class Circuit(Base):
    """One row of the circuit list: an end device and the switch port it uses."""

    __tablename__ = "ct_circuits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    import_id: Mapped[int] = mapped_column(
        ForeignKey("ct_imports.id", ondelete="CASCADE"), index=True)
    row_no: Mapped[int] = mapped_column(Integer)  # row number in the spreadsheet

    # SERVICE
    ip_partition: Mapped[str] = mapped_column(String(200), default="")
    service: Mapped[str] = mapped_column(String(200), default="")
    # DEVICE INFORMATION
    eng_prefix: Mapped[str] = mapped_column(String(255), default="")
    device_name: Mapped[str] = mapped_column(String(255), default="")
    device_type: Mapped[str] = mapped_column(String(255), default="")
    manufacturer: Mapped[str] = mapped_column(String(255), default="")
    mac: Mapped[str] = mapped_column(String(100), default="")
    # LOCATION
    floor: Mapped[str] = mapped_column(String(200), default="")
    room: Mapped[str] = mapped_column(String(200), default="")
    # IP DETAILS
    ip: Mapped[str] = mapped_column(String(100), default="")
    mask: Mapped[str] = mapped_column(String(100), default="")
    gateway: Mapped[str] = mapped_column(String(100), default="")
    # NETWORK PORT
    vlan: Mapped[str] = mapped_column(String(50), default="")
    conn_type: Mapped[str] = mapped_column(String(100), default="")
    port: Mapped[str] = mapped_column(String(100), default="")
    switch: Mapped[str] = mapped_column(String(255), default="")
    # DRAWING DETAILS
    drawing_number: Mapped[str] = mapped_column(String(255), default="")
    drawing_ref: Mapped[str] = mapped_column(String(255), default="")

    # Derived, for matching
    switch_norm: Mapped[str] = mapped_column(String(255), default="", index=True)
    port_norm: Mapped[str] = mapped_column(String(100), default="")
    mac_norm: Mapped[str] = mapped_column(String(20), default="")
    warnings: Mapped[str] = mapped_column(Text, default="")  # "; "-separated
    # The admins' own columns (CircuitField): {"<key>": "value"}
    custom: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")


class CircuitField(Base):
    """A column an admin added to the circuit list. Uploads read it by its name."""

    __tablename__ = "ct_fields"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(50), unique=True)
    label: Mapped[str] = mapped_column(String(100))
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# --- live location: what the switches report (MAC and ARP tables) ------------------

class CircuitScan(Base):
    """One read of the MAC/ARP tables: the weekly scan, a manual scan or an upgrade job."""

    __tablename__ = "ct_scans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trigger: Mapped[str] = mapped_column(String(200))  # schedule / manual:<user> / upgrade-job:<id>
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    devices_ok: Mapped[int] = mapped_column(Integer, default=0)
    devices_failed: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[str] = mapped_column(Text, default="")  # "device: error" lines


class LiveMac(Base):
    """A MAC address in a device's MAC table at its last successful read."""

    __tablename__ = "ct_live_mac"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    mac_norm: Mapped[str] = mapped_column(String(20), index=True)
    vlan: Mapped[str] = mapped_column(String(50), default="")
    port: Mapped[str] = mapped_column(String(100), default="")
    port_norm: Mapped[str] = mapped_column(String(100), default="")
    uplink: Mapped[bool] = mapped_column(default=False)
    seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class LiveArp(Base):
    """An IP -> MAC entry in a device's ARP table at its last successful read."""

    __tablename__ = "ct_live_arp"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    ip: Mapped[str] = mapped_column(String(100), index=True)
    mac_norm: Mapped[str] = mapped_column(String(20))
    seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class MacLastSeen(Base):
    """Where a MAC was last seen on an edge port, kept after it disappears."""

    __tablename__ = "ct_mac_last_seen"

    mac_norm: Mapped[str] = mapped_column(String(20), primary_key=True)
    device_id: Mapped[int | None] = mapped_column(
        ForeignKey("devices.id", ondelete="SET NULL"), nullable=True)
    port: Mapped[str] = mapped_column(String(100), default="")
    vlan: Mapped[str] = mapped_column(String(50), default="")
    seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DeviceScanState(Base):
    """The last read of one device's tables (for "last scanned" and errors)."""

    __tablename__ = "ct_device_scan"

    device_id: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True)
    last_attempt: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_success: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    mac_count: Mapped[int] = mapped_column(Integer, default=0)
    arp_count: Mapped[int] = mapped_column(Integer, default=0)
