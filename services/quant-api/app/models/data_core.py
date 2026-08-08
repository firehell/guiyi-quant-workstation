from __future__ import annotations

from datetime import UTC, datetime
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class MarketDataset(Base):
    __tablename__ = "market_datasets"
    __table_args__ = (
        UniqueConstraint(
            "kind", "symbol", "series_or_contract", "frequency",
            name="uq_market_datasets_key",
        ),
        CheckConstraint("kind IN ('continuous', 'contract')", name="ck_market_datasets_kind"),
        CheckConstraint(
            "frequency IN ('1m', '5m', '15m', '30m', '60m', '1d', '1w')",
            name="ck_market_datasets_frequency",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    series_or_contract: Mapped[str] = mapped_column(String(64), nullable=False)
    frequency: Mapped[str] = mapped_column(String(8), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MarketPartition(Base):
    __tablename__ = "market_partitions"
    __table_args__ = (
        UniqueConstraint("dataset_id", "year", "month", name="uq_market_partitions_month"),
        CheckConstraint("month BETWEEN 1 AND 12", name="ck_market_partitions_month"),
        CheckConstraint("coverage_start < coverage_end", name="ck_market_partitions_window"),
        CheckConstraint("row_count >= 0", name="ck_market_partitions_row_count"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("market_datasets.id"), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    coverage_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    coverage_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    file_uri: Mapped[str] = mapped_column(Text, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
