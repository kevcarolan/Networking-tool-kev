"""Maintenance calendar: planned changes, maintenance, outages and change freezes that
people add. Upgrade jobs' windows are read from the jobs themselves."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, utcnow

KINDS = {"change": "Change", "maintenance": "Maintenance", "outage": "Outage",
         "freeze": "Change freeze"}


class CalendarEvent(Base):
    __tablename__ = "cal_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20), default="change")
    start: Mapped[datetime] = mapped_column(DateTime, index=True)  # UTC
    end: Mapped[datetime] = mapped_column(DateTime, index=True)
    sites: Mapped[str] = mapped_column(Text, default="[]")  # JSON site names; empty = every site
    devices: Mapped[str] = mapped_column(Text, default="[]")  # JSON device ids
    change_ref: Mapped[str] = mapped_column(String(100), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_by: Mapped[str] = mapped_column(String(200), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
