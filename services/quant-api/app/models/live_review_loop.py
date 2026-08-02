from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import Base
from app.models.data_center import TimestampMixin, utc_now


class LiveObservationBar(Base, TimestampMixin):
    __tablename__ = "live_observation_bars"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "source_mode",
            "actual_contract",
            "period",
            "trading_day",
            "bar_end",
            "revision",
            "confirmed",
            name="uq_live_observation_bars_natural_key",
        ),
        CheckConstraint("provider = 'rqdata'", name="ck_live_observation_provider"),
        CheckConstraint("product = 'jm'", name="ck_live_observation_product"),
        CheckConstraint("period IN ('1m', '15m')", name="ck_live_observation_period"),
        CheckConstraint("revision >= 0", name="ck_live_observation_revision"),
        CheckConstraint("confirmed = true", name="ck_live_observation_confirmed"),
        CheckConstraint("source_bar_count > 0", name="ck_live_observation_source_count"),
        CheckConstraint("expected_bar_count > 0", name="ck_live_observation_expected_count"),
        CheckConstraint("source_bar_count = expected_bar_count", name="ck_live_observation_complete"),
        CheckConstraint(
            "(period = '1m' AND source_mode = 'rqdata_live_1m_v2' AND source_bar_count = 1) OR "
            "(period = '15m' AND source_mode = 'session_aggregate_15m_v2' AND source_bar_count = 15)",
            name="ck_live_observation_source_contract",
        ),
        CheckConstraint("source_end = bar_end", name="ck_live_observation_source_end"),
        CheckConstraint("low <= open AND low <= close AND high >= open AND high >= close AND low <= high", name="ck_live_observation_ohlc"),
        Index("ix_live_observation_trading_bucket", "trading_day", "actual_contract", "period", "bar_end"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    source_mode: Mapped[str] = mapped_column(String(64), nullable=False)
    product: Mapped[str] = mapped_column(String(32), nullable=False)
    actual_contract: Mapped[str] = mapped_column(String(64), nullable=False)
    trading_day: Mapped[date] = mapped_column(Date, nullable=False)
    period: Mapped[str] = mapped_column(String(16), nullable=False)
    bar_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    open: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    volume: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    open_interest: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    turnover: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    source_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_bar_count: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_bar_count: Mapped[int] = mapped_column(Integer, nullable=False)
    identity_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_digest: Mapped[str] = mapped_column(String(64), nullable=False)


class SignalDecision(Base):
    __tablename__ = "signal_decisions"
    __table_args__ = (
        UniqueConstraint("decision_key", name="uq_signal_decisions_key"),
        CheckConstraint("result_kind IN ('signal', 'no_signal')", name="ck_signal_decisions_result_kind"),
        CheckConstraint(
            "(result_kind = 'signal' AND direction IS NOT NULL AND direction IN ('long', 'short')) OR "
            "(result_kind = 'no_signal' AND direction IS NULL)",
            name="ck_signal_decisions_direction",
        ),
        Index("ix_signal_decisions_bucket", "trading_day", "actual_contract", "bar_end"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    decision_key: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    trading_day: Mapped[date] = mapped_column(Date, nullable=False)
    bar_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    source_mode: Mapped[str] = mapped_column(String(64), nullable=False)
    actual_contract: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_code: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    policy_id: Mapped[str] = mapped_column(String(96), nullable=False)
    parameter_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    input_schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    input_window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    input_window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    dataset_key: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    manifest_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    input_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint_recipe_version: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    result_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    direction: Mapped[str | None] = mapped_column(String(16))
    result_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    result_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class SignalDecisionReconciliation(Base, TimestampMixin):
    __tablename__ = "signal_decision_reconciliations"
    __table_args__ = (
        UniqueConstraint("decision_id", "recipe_version", name="uq_signal_decision_reconciliation"),
        CheckConstraint("attempt_count BETWEEN 0 AND 3", name="ck_signal_decision_reconciliation_attempts"),
        CheckConstraint(
            "outcome IS NULL OR outcome IN ('unchanged', 'data_changed', 'result_changed', 'data_and_result_changed')",
            name="ck_signal_decision_reconciliation_outcome",
        ),
        CheckConstraint(
            "status != 'completed' OR (provider_data_version IS NOT NULL AND provider_request_digest IS NOT NULL)",
            name="ck_signal_decision_reconciliation_provider_lineage",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    decision_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    recipe_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    outcome: Mapped[str | None] = mapped_column(String(40))
    data_changed: Mapped[bool | None] = mapped_column(Boolean)
    result_changed: Mapped[bool | None] = mapped_column(Boolean)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provider_final_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    provider_final_digest: Mapped[str | None] = mapped_column(String(64))
    provider_data_version: Mapped[str | None] = mapped_column(String(128))
    provider_request_digest: Mapped[str | None] = mapped_column(String(64))
    recomputed_result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    recomputed_result_digest: Mapped[str | None] = mapped_column(String(64))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(96))
    error_message: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ResearchSample(Base):
    __tablename__ = "research_samples"
    __table_args__ = (UniqueConstraint("sample_key", name="uq_research_samples_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    sample_key: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    decision_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    review_id: Mapped[int] = mapped_column(Integer, nullable=False)
    reconciliation_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    features: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    outcome: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    labels: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    lineage: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class RetentionRun(Base):
    __tablename__ = "retention_runs"
    __table_args__ = (UniqueConstraint("manifest_digest", name="uq_retention_runs_manifest_digest"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    manifest_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    target_counts: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


@event.listens_for(SignalDecision, "before_update", propagate=True)
def _reject_signal_decision_update(*_: object) -> None:
    raise RuntimeError("SIGNAL_DECISION_IMMUTABLE")
