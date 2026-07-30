from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


def _lower_sha256_check(column: str) -> str:
    residue = column
    for character in "0123456789abcdef":
        residue = f"replace({residue}, '{character}', '')"
    return (
        f"length({column}) = 64"
        f" AND {column} = lower({column})"
        f" AND length({residue}) = 0"
    )


class MarketDataset(Base):
    __tablename__ = "market_datasets"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "data_type",
            "instrument_symbol",
            "contract_code",
            "period",
            name="uq_market_datasets_dataset_key",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    data_type: Mapped[str] = mapped_column(String(32), nullable=False)
    instrument_symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    contract_code: Mapped[str] = mapped_column(String(64), nullable=False)
    period: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )


class MarketPartition(Base):
    __tablename__ = "market_partitions"
    __table_args__ = (
        UniqueConstraint(
            "dataset_id",
            "coverage_start",
            "coverage_end",
            "manifest_version",
            name="uq_market_partitions_exact_identity",
        ),
        CheckConstraint(
            "coverage_start < coverage_end",
            name="ck_market_partitions_half_open_window",
        ),
        CheckConstraint(
            "row_count >= 0",
            name="ck_market_partitions_row_count_nonnegative",
        ),
        CheckConstraint(
            _lower_sha256_check("manifest_digest"),
            name="ck_market_partitions_manifest_digest_sha256",
        ),
        CheckConstraint(
            _lower_sha256_check("checksum"),
            name="ck_market_partitions_checksum_sha256",
        ),
        CheckConstraint(
            "overlap_reason IS NULL OR overlap_reason IN "
            "('version_replacement', 'repair_overlay', 'rollover_transition')",
            name="ck_market_partitions_overlap_reason",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_id: Mapped[int] = mapped_column(
        ForeignKey("market_datasets.id"),
        nullable=False,
    )
    coverage_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    coverage_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    manifest_version: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_uri: Mapped[str] = mapped_column(Text, nullable=False)
    manifest_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    file_uri: Mapped[str] = mapped_column(Text, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    overlap_reason: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )


class DataGap(Base):
    __tablename__ = "data_gaps"
    __table_args__ = (
        UniqueConstraint(
            "dataset_id",
            "gap_start",
            "gap_end",
            name="uq_data_gaps_exact_window",
        ),
        CheckConstraint(
            "gap_start < gap_end",
            name="ck_data_gaps_half_open_window",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_id: Mapped[int] = mapped_column(
        ForeignKey("market_datasets.id"),
        nullable=False,
    )
    gap_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    gap_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
