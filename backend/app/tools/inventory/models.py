"""Network inventory: one row per thing (switch, server, rack, UPS, ...), and the columns an
admin added (custom fields).

A row linked to a device (``device_id``) is *managed*: the tools back it up, check its
firmware and so on. Every device appears here by itself (``fields.sync_devices``). Rows
without a device are *inventory only* and don't count towards the licence.
"""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, utcnow


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int | None] = mapped_column(
        ForeignKey("devices.id", ondelete="SET NULL"), nullable=True, unique=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    type: Mapped[str] = mapped_column(String(50), default="")
    role: Mapped[str] = mapped_column(String(100), default="")
    manufacturer: Mapped[str] = mapped_column(String(100), default="")
    model: Mapped[str] = mapped_column(String(100), default="")
    serial: Mapped[str] = mapped_column(String(100), default="", index=True)
    asset_tag: Mapped[str] = mapped_column(String(100), default="")
    os: Mapped[str] = mapped_column(String(100), default="")
    version: Mapped[str] = mapped_column(String(100), default="")
    mgmt_ip: Mapped[str] = mapped_column(String(255), default="")
    mgmt_vlan: Mapped[str] = mapped_column(String(20), default="")
    mac: Mapped[str] = mapped_column(String(50), default="")
    site: Mapped[str] = mapped_column(String(100), default="")
    building: Mapped[str] = mapped_column(String(100), default="")
    floor: Mapped[str] = mapped_column(String(50), default="")
    room: Mapped[str] = mapped_column(String(100), default="")
    rack: Mapped[str] = mapped_column(String(100), default="")
    rack_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rack_units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="in service")
    purchase_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    warranty_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    support_contract: Mapped[str] = mapped_column(String(200), default="")
    end_of_support: Mapped[date | None] = mapped_column(Date, nullable=True)
    supplier: Mapped[str] = mapped_column(String(200), default="")
    owner: Mapped[str] = mapped_column(String(200), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    custom: Mapped[str] = mapped_column(Text, default="{}")  # JSON: custom field key -> value
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    updated_by: Mapped[str] = mapped_column(String(200), default="")


class AssetField(Base):
    """A column an admin added for this site."""
    __tablename__ = "asset_fields"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(50), unique=True)
    label: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(10), default="text")  # text, number, date, choice
    choices: Mapped[str] = mapped_column(Text, default="[]")  # JSON list, for "choice"
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
