"""Monitoring settings kept in the main database: SNMP profiles (the community or SNMPv3
account devices are polled with) and each device's monitoring choices.

What the poller finds (up/down, response times, events) is not here: it lives in the
poller's own files (store.py), written only by the poller service.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, utcnow

VERSIONS = {"2c": "SNMPv2c (community)", "3": "SNMPv3 (user, authentication, encryption)"}
LEVELS = {"authPriv": "Authentication and encryption", "authNoPriv": "Authentication only",
          "noAuthNoPriv": "Neither (user name only)"}


class SnmpProfile(Base):
    """A named SNMP login shared by many devices, e.g. "switches-v3". The secrets are
    encrypted with the credential key, like device passwords, and never shown again."""

    __tablename__ = "mon_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    version: Mapped[str] = mapped_column(String(5), default="3")
    community_enc: Mapped[str] = mapped_column(Text, default="")  # v2c
    username: Mapped[str] = mapped_column(String(100), default="")  # v3
    level: Mapped[str] = mapped_column(String(20), default="authPriv")  # v3
    auth_protocol: Mapped[str] = mapped_column(String(10), default="SHA")
    auth_key_enc: Mapped[str] = mapped_column(Text, default="")
    priv_protocol: Mapped[str] = mapped_column(String(10), default="AES")
    priv_key_enc: Mapped[str] = mapped_column(Text, default="")
    port: Mapped[int] = mapped_column(Integer, default=161)
    timeout: Mapped[int] = mapped_column(Integer, default=2)  # seconds per try
    retries: Mapped[int] = mapped_column(Integer, default=1)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)  # devices without their own
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    updated_by: Mapped[str] = mapped_column(String(200), default="")


class MonitorTarget(Base):
    """A device's monitoring choices. A device without a row is monitored with the
    defaults: ping on, SNMP with the default profile."""

    __tablename__ = "mon_targets"

    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"),
                                           primary_key=True)
    monitored: Mapped[bool] = mapped_column(Boolean, default=True)
    ping: Mapped[bool] = mapped_column(Boolean, default=True)
    snmp: Mapped[bool] = mapped_column(Boolean, default=True)
    profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("mon_profiles.id", ondelete="SET NULL"), nullable=True)  # None: the default
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    updated_by: Mapped[str] = mapped_column(String(200), default="")


class MerakiOrg(Base):
    """A Meraki organisation read through the Dashboard API (meraki.py). The API key is
    encrypted with the credential key and never shown again."""

    __tablename__ = "mon_meraki"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)  # what the page calls it
    base_url: Mapped[str] = mapped_column(String(200), default="https://api.meraki.com/api/v1")
    org_id: Mapped[str] = mapped_column(String(50), default="")
    org_name: Mapped[str] = mapped_column(String(200), default="")
    api_key_enc: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    updated_by: Mapped[str] = mapped_column(String(200), default="")
