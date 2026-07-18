from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import duckdb
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import PROJECT_ROOT
from app.models.data_center import DataProfile, DataQualityReport, MarketDataFile, ProfileActiveBinding
from app.services.data_profile_registry import ACTIVE_BINDING_STATUS, DataProfileRegistry
from app.services.rqdata_ingest.quality import RQDATA_CANONICAL_CHECK_RULE_VERSION

ConsumerName = Literal["market", "backtest", "signal", "review"]

INTRADAY_RESEARCH_PROFILE = "intraday_research_v1"
LONG_HORIZON_DAILY_PROFILE = "long_horizon_daily_v1"
LIVE_OBSERVATION_PROFILE = "live_observation_v1"
PASSED_ONLY_POLICY = "passed_only"
ACTIVE_ENTRY_POLICY = "active_entry"


@dataclass(frozen=True)
class ProfileLineage:
    profile_id: str | None
    quality_policy: str | None
    data_version: str | None
    market_data_file_id: int | None
    binding_snapshot: dict[str, Any] | None
    market_file: MarketDataFile | None
    source_interval: str | None = None
    source_interval_basis: str | None = None
    blocked_reason: str | None = None

    @property
    def blocked(self) -> bool:
        return self.blocked_reason is not None

    def payload(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "quality_policy": self.quality_policy,
            "data_version": self.data_version,
            "market_data_file_id": self.market_data_file_id,
            "binding_snapshot": self.binding_snapshot,
            "source_interval": self.source_interval,
            "source_interval_basis": self.source_interval_basis,
            "blocked_reason": self.blocked_reason,
        }


def default_profile_id(*, consumer: ConsumerName, period: str | None, explicit_profile_id: str | None = None) -> str | None:
    if explicit_profile_id:
        return explicit_profile_id.strip()
    if consumer == "market":
        return None
    if period in {"1d", "1w"}:
        return LONG_HORIZON_DAILY_PROFILE
    return INTRADAY_RESEARCH_PROFILE


class ProfileLineageResolver:
    def __init__(self, session: Session, project_root: Path = PROJECT_ROOT) -> None:
        self.session = session
        self.project_root = project_root
        self.registry = DataProfileRegistry(session)

    def resolve(
        self,
        *,
        consumer: ConsumerName,
        symbol: str,
        contract: str,
        period: str,
        profile_id: str | None,
        allow_warning_quality: bool = False,
        allow_non_failed_market_quality: bool = False,
    ) -> ProfileLineage:
        selected_profile_id = default_profile_id(consumer=consumer, period=period, explicit_profile_id=profile_id)
        if not selected_profile_id:
            return ProfileLineage(
                profile_id=None,
                quality_policy=None,
                data_version=None,
                market_data_file_id=None,
                binding_snapshot=None,
                market_file=None,
            )

        profile = self.registry.get_profile(selected_profile_id)
        if profile is None:
            return self._blocked(selected_profile_id, None, None, "profile_not_found")

        binding = self.session.scalar(
            select(ProfileActiveBinding).where(
                ProfileActiveBinding.profile_id == selected_profile_id,
                ProfileActiveBinding.instrument_symbol == symbol,
                ProfileActiveBinding.contract_code == contract,
                ProfileActiveBinding.period == period,
                ProfileActiveBinding.binding_status == ACTIVE_BINDING_STATUS,
            )
        )
        if binding is None:
            return self._blocked(selected_profile_id, profile, None, "profile_binding_missing")

        market_file = self._market_file(binding, symbol=symbol, contract=contract, period=period)
        if market_file is None:
            return self._blocked(selected_profile_id, profile, binding, "profile_market_file_missing")
        if (
            market_file.instrument_symbol != symbol
            or market_file.contract_code != contract
            or market_file.period != period
        ):
            return self._blocked(
                selected_profile_id,
                profile,
                binding,
                "profile_identity_mismatch",
                market_file=market_file,
            )

        quality_block = self._quality_block(
            profile,
            market_file,
            consumer=consumer,
            allow_warning_quality=allow_warning_quality,
            allow_non_failed_market_quality=allow_non_failed_market_quality,
        )
        if quality_block:
            return self._blocked(selected_profile_id, profile, binding, quality_block, market_file=market_file)

        raw_path = Path(market_file.file_path)
        physical_path = raw_path if raw_path.is_absolute() else self.project_root / raw_path
        if not physical_path.is_file():
            return self._blocked(selected_profile_id, profile, binding, "profile_file_missing", market_file=market_file)

        source_interval, source_interval_basis = resolve_source_interval(
            self.session,
            market_file,
            project_root=self.project_root,
        )
        browser_observation = consumer == "market" and allow_non_failed_market_quality
        if source_interval is None and not browser_observation:
            return self._blocked(
                selected_profile_id,
                profile,
                binding,
                "profile_lineage_incomplete",
                market_file=market_file,
                source_interval=None,
                source_interval_basis=source_interval_basis,
            )

        return ProfileLineage(
            profile_id=selected_profile_id,
            quality_policy=profile.quality_policy,
            data_version=market_file.data_version or binding.data_version,
            market_data_file_id=market_file.id,
            binding_snapshot=binding_snapshot(
                binding,
                profile=profile,
                market_file=market_file,
                source_interval=source_interval,
                source_interval_basis=source_interval_basis,
            ),
            market_file=market_file,
            source_interval=source_interval,
            source_interval_basis=source_interval_basis,
        )

    def _market_file(self, binding: ProfileActiveBinding, *, symbol: str, contract: str, period: str) -> MarketDataFile | None:
        if binding.market_data_file_id is not None:
            market_file = self.session.get(MarketDataFile, binding.market_data_file_id)
            if market_file is not None:
                return market_file
        return self.session.scalar(
            select(MarketDataFile).where(
                MarketDataFile.instrument_symbol == symbol,
                MarketDataFile.contract_code == contract,
                MarketDataFile.period == period,
                MarketDataFile.data_version == binding.data_version,
                MarketDataFile.data_role == "primary",
            )
        )

    @staticmethod
    def _quality_block(
        profile: DataProfile,
        market_file: MarketDataFile,
        *,
        consumer: ConsumerName,
        allow_warning_quality: bool,
        allow_non_failed_market_quality: bool,
    ) -> str | None:
        status = (market_file.quality_status or "unchecked").lower()
        if status == "failed":
            return "profile_quality_failed"
        if consumer == "market" and allow_non_failed_market_quality:
            return None
        policy = profile.quality_policy or PASSED_ONLY_POLICY
        if policy == PASSED_ONLY_POLICY and status != "passed":
            if consumer == "backtest" and status == "warning" and allow_warning_quality:
                return None
            return "profile_quality_policy_blocked"
        if consumer == "signal" and status != "passed":
            return "signal_requires_passed_quality"
        return None

    @staticmethod
    def _blocked(
        profile_id: str,
        profile: DataProfile | None,
        binding: ProfileActiveBinding | None,
        reason: str,
        *,
        market_file: MarketDataFile | None = None,
        source_interval: str | None = None,
        source_interval_basis: str | None = None,
    ) -> ProfileLineage:
        return ProfileLineage(
            profile_id=profile_id,
            quality_policy=profile.quality_policy if profile else None,
            data_version=(market_file.data_version if market_file else binding.data_version if binding else None),
            market_data_file_id=market_file.id if market_file else binding.market_data_file_id if binding else None,
            binding_snapshot=(
                binding_snapshot(
                    binding,
                    profile=profile,
                    market_file=market_file,
                    source_interval=source_interval,
                    source_interval_basis=source_interval_basis,
                )
                if binding
                else None
            ),
            market_file=market_file,
            source_interval=source_interval,
            source_interval_basis=source_interval_basis,
            blocked_reason=reason,
        )


def binding_snapshot(
    binding: ProfileActiveBinding,
    *,
    profile: DataProfile | None = None,
    market_file: MarketDataFile | None = None,
    source_interval: str | None = None,
    source_interval_basis: str | None = None,
) -> dict[str, Any]:
    return {
        "profile_id": binding.profile_id,
        "instrument_symbol": binding.instrument_symbol,
        "contract_code": binding.contract_code,
        "contract_role": binding.contract_role,
        "period": binding.period,
        "data_version": binding.data_version,
        "market_data_file_id": binding.market_data_file_id,
        "binding_status": binding.binding_status,
        "activated_at": binding.activated_at.isoformat() if binding.activated_at else None,
        "superseded_at": binding.superseded_at.isoformat() if binding.superseded_at else None,
        "updated_at": binding.updated_at.isoformat() if binding.updated_at else None,
        "quality_policy": profile.quality_policy if profile else None,
        "provider": market_file.provider if market_file else profile.provider if profile else None,
        "data_role": market_file.data_role if market_file else None,
        "quality_status": market_file.quality_status if market_file else None,
        "file_data_version": market_file.data_version if market_file else None,
        "source_interval": source_interval,
        "source_interval_basis": source_interval_basis,
    }


def resolve_source_interval(
    session: Session,
    market_file: MarketDataFile,
    *,
    project_root: Path = PROJECT_ROOT,
) -> tuple[str | None, str | None]:
    """Resolve immutable source-period provenance without rewriting the asset."""
    raw_path = Path(market_file.file_path)
    path = raw_path if raw_path.is_absolute() else project_root / raw_path
    if path.is_file():
        try:
            with duckdb.connect(database=":memory:") as connection:
                columns = {
                    str(row[0])
                    for row in connection.execute("describe select * from read_parquet(?)", [str(path)]).fetchall()
                }
                if "source_interval" in columns:
                    values = [
                        str(row[0])
                        for row in connection.execute(
                            "select distinct cast(source_interval as varchar) from read_parquet(?) "
                            "where source_interval is not null order by 1",
                            [str(path)],
                        ).fetchall()
                    ]
                    if len(values) == 1:
                        return values[0], "parquet_column"
                    return None, "parquet_column_ambiguous"
        except (duckdb.Error, OSError):
            return None, "parquet_unreadable"

    if market_file.period == "1m":
        return "1m", "base_period_identity"

    report = session.scalar(
        select(DataQualityReport)
        .where(DataQualityReport.file_id == market_file.id)
        .order_by(DataQualityReport.created_at.desc(), DataQualityReport.id.desc())
        .limit(1)
    )
    details = report.details if report is not None and isinstance(report.details, dict) else {}
    check_mode = str(details.get("check_mode") or "")
    if "raw_to_standard" in check_mode:
        return market_file.period, "direct_asset_period"
    if (
        market_file.period in {"1d", "1w"}
        and str(market_file.data_version or "").startswith("rq_acb_")
        and details.get("actual_contract_bars_pilot") is True
        and details.get("source") == "rqdata"
        and details.get("check_rule_version") == RQDATA_CANONICAL_CHECK_RULE_VERSION
    ):
        return market_file.period, "actual_contract_direct_period_contract"
    return None, "unresolved"
