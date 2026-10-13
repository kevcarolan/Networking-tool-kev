from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, utcnow

SUCCESS, FAILED, RUNNING, NEVER = "success", "failed", "running", "never"


class BackupState(Base):
    """Backup schedule and latest result for one device."""

    __tablename__ = "backup_state"

    device_id: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True
    )
    frequency_minutes: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_status: Mapped[str] = mapped_column(String(20), default=NEVER)
    last_attempt: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_success: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_change: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    config_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    last_commit: Mapped[str | None] = mapped_column(String(64), nullable=True)


class BackupRun(Base):
    """One backup attempt (kept for NETOPS_HISTORY_RETENTION_DAYS)."""

    __tablename__ = "backup_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    trigger: Mapped[str] = mapped_column(String(100))  # "schedule" or "manual:<user>"
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=RUNNING)
    changed: Mapped[bool] = mapped_column(Boolean, default=False)
    commit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    message: Mapped[str] = mapped_column(Text, default="")


class ComplianceRule(Base):
    """A rule every backed-up config is checked against (``compliance.py``)."""

    __tablename__ = "compliance_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(10), default="must")  # must / must_not
    lines: Mapped[str] = mapped_column(Text)  # one per line: each must (not) be in the config
    regex: Mapped[bool] = mapped_column(Boolean, default=False)
    platforms: Mapped[str] = mapped_column(Text, default="[]")  # JSON list; empty = all
    sites: Mapped[str] = mapped_column(Text, default="[]")  # JSON list of site names; empty = all
    severity: Mapped[str] = mapped_column(String(10), default="warning")  # critical / warning
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    updated_by: Mapped[str] = mapped_column(String(200), default="")


class ComplianceResult(Base):
    """The latest result of one rule on one device."""

    __tablename__ = "compliance_results"

    device_id: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True)
    rule_id: Mapped[int] = mapped_column(
        ForeignKey("compliance_rules.id", ondelete="CASCADE"), primary_key=True)
    passed: Mapped[bool] = mapped_column(Boolean)
    detail: Mapped[str] = mapped_column(Text, default="")  # missing or offending config lines
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    failing_since: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
