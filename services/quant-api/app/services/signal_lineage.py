from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.db.session import PROJECT_ROOT
from app.data_core.contracts import DataCoreError
from app.services.actual_contract_semantics import load_effective_main_contract_mapping
from app.services.canonical_bar_loader import (
    CanonicalBarLoader,
    shanghai_naive_bound_to_utc,
)
from app.services.profile_lineage import ProfileLineageResolver


@dataclass(frozen=True)
class SignalLineageResolution:
    profile_id: str | None
    market_data_file_id: int | None
    snapshot: dict[str, Any] | None
    blocked_code: str | None = None
    blocked_context: dict[str, Any] | None = None

    @property
    def blocked(self) -> bool:
        return self.blocked_code is not None


PROFILE_BLOCK_CODES = {
    "profile_not_found": "SIGNAL_PROFILE_NOT_FOUND",
    "profile_binding_missing": "SIGNAL_PROFILE_BINDING_MISSING",
    "profile_market_file_missing": "SIGNAL_PROFILE_MARKET_FILE_MISSING",
    "profile_quality_failed": "SIGNAL_PROFILE_QUALITY_BLOCKED",
    "profile_quality_policy_blocked": "SIGNAL_PROFILE_QUALITY_BLOCKED",
    "signal_requires_passed_quality": "SIGNAL_PROFILE_QUALITY_BLOCKED",
    "profile_lineage_incomplete": "SIGNAL_PROFILE_LINEAGE_INCOMPLETE",
    "profile_identity_mismatch": "SIGNAL_PROFILE_IDENTITY_MISMATCH",
    "profile_file_missing": "SIGNAL_PROFILE_FILE_MISSING",
}


class SignalFormalLineageResolver:
    """Signal-specific fail-closed checks layered on the shared Profile resolver."""

    def __init__(self, session: Session, project_root: Path = PROJECT_ROOT) -> None:
        self.session = session
        self.project_root = project_root
        self.profile_resolver = ProfileLineageResolver(session)
        self.reader = CanonicalBarLoader(session)

    def resolve(
        self,
        *,
        profile_id: str,
        symbol: str,
        continuous_contract: str,
        actual_contract: str,
        period: str,
        dominant_mapping_date: date,
        bar_start: datetime,
        bar_end: datetime,
        trigger_price: float,
        source_mode: str,
        confirmation: dict[str, Any],
        context_assets: list[dict[str, Any]] | None = None,
        historical_context: dict[str, Any] | None = None,
    ) -> SignalLineageResolution:
        del historical_context  # live_confirmed historical context path retired
        context = self._context(
            profile_id=profile_id,
            symbol=symbol,
            actual_contract=actual_contract,
            period=period,
            dominant_mapping_date=dominant_mapping_date,
        )
        if not actual_contract or actual_contract.upper().endswith(".MAIN"):
            return self._blocked("SIGNAL_ACTUAL_CONTRACT_REQUIRED", context)

        mapping = load_effective_main_contract_mapping(
            self.session,
            instrument_symbol=symbol,
            trade_date=dominant_mapping_date,
        )
        if mapping is None:
            return self._blocked("SIGNAL_DOMINANT_MAPPING_MISSING", context)
        if mapping.contract_code.upper() != actual_contract.upper():
            return self._blocked("SIGNAL_DOMINANT_MAPPING_MISMATCH", context)

        lineage = self.profile_resolver.resolve(
            consumer="signal",
            symbol=symbol,
            contract=actual_contract,
            period=period,
            profile_id=profile_id,
            allow_warning_quality=False,
        )
        if lineage.blocked:
            return self._blocked(PROFILE_BLOCK_CODES.get(str(lineage.blocked_reason), "SIGNAL_PROFILE_BLOCKED"), context)
        market_file = lineage.market_file
        if market_file is None or lineage.market_data_file_id is None:
            return self._blocked("SIGNAL_PROFILE_MARKET_FILE_MISSING", context)
        if (
            market_file.instrument_symbol != symbol
            or market_file.contract_code != actual_contract
            or market_file.period != period
            or market_file.data_version != lineage.data_version
        ):
            return self._blocked("SIGNAL_PROFILE_IDENTITY_MISMATCH", context)
        if market_file.provider not in {"rqdata", "local_parquet"} or market_file.data_role != "primary":
            return self._blocked("SIGNAL_PROFILE_IDENTITY_MISMATCH", context)
        if market_file.quality_status != "passed":
            return self._blocked("SIGNAL_PROFILE_QUALITY_BLOCKED", context)
        path = Path(market_file.file_path)
        path = path if path.is_absolute() else self.project_root / path
        if not path.is_file():
            return self._blocked("SIGNAL_PROFILE_FILE_MISSING", context)

        confirmation_payload = dict(confirmation)
        confirmation_mode = str(confirmation_payload.get("confirmation_mode") or "")
        if confirmation_mode == "historical_canonical":
            if _naive(market_file.start_time) > _naive(bar_start) or _naive(market_file.end_time) < _naive(bar_end):
                return self._blocked("SIGNAL_PROFILE_RANGE_NOT_COVERED", context)
            try:
                rows = self.reader.load_bars(
                    symbol,
                    actual_contract,
                    period,
                    start=shanghai_naive_bound_to_utc(bar_start),
                    end=shanghai_naive_bound_to_utc(bar_end),
                )
            except DataCoreError:
                return self._blocked("SIGNAL_CONFIRMED_BAR_MISSING", context)
            if len(rows) != 1:
                return self._blocked("SIGNAL_CONFIRMED_BAR_MISSING", context)
            if float(rows[0]["close"]) != float(trigger_price):
                return self._blocked("SIGNAL_TRIGGER_PRICE_MISMATCH", context)
        else:
            return self._blocked("SIGNAL_BAR_NOT_CONFIRMED", context)

        primary = {
            **(lineage.binding_snapshot or {}),
            "profile_id": lineage.profile_id,
            "market_data_file_id": market_file.id,
            "instrument_symbol": market_file.instrument_symbol,
            "contract_code": market_file.contract_code,
            "period": market_file.period,
            "data_version": lineage.data_version,
            "provider": market_file.provider,
            "data_role": market_file.data_role,
            "quality_status": market_file.quality_status,
            "coverage_start": market_file.start_time.isoformat(),
            "coverage_end": market_file.end_time.isoformat(),
            "checksum": market_file.checksum,
        }
        snapshot = {
            "schema_version": "signal_review_lineage_v1",
            "resolver_name": "ProfileLineageResolver",
            "resolver_contract_version": "signal_profile_v1",
            "context_contract_version": None,
            "quality_policy": "passed_only",
            "source_mode": source_mode,
            "primary": primary,
            "context_assets": list(context_assets or []),
            "contract": {
                "continuous_contract": continuous_contract,
                "actual_contract": actual_contract,
                "dominant_mapping_date": dominant_mapping_date.isoformat(),
                "mapping_id": mapping.id,
                "mapping_data_version": mapping.data_version,
            },
            "bar": {
                "bar_start": bar_start.isoformat(),
                "bar_end": bar_end.isoformat(),
                "trigger_price": float(trigger_price),
                **confirmation_payload,
            },
        }
        return SignalLineageResolution(
            profile_id=lineage.profile_id,
            market_data_file_id=market_file.id,
            snapshot=snapshot,
        )

    @staticmethod
    def _context(
        *,
        profile_id: str,
        symbol: str,
        actual_contract: str,
        period: str,
        dominant_mapping_date: date,
    ) -> dict[str, Any]:
        return {
            "profile_id": profile_id,
            "instrument_symbol": symbol,
            "actual_contract": actual_contract,
            "period": period,
            "dominant_mapping_date": dominant_mapping_date.isoformat(),
        }

    @staticmethod
    def _blocked(code: str, context: dict[str, Any]) -> SignalLineageResolution:
        return SignalLineageResolution(
            profile_id=context.get("profile_id"),
            market_data_file_id=None,
            snapshot=None,
            blocked_code=code,
            blocked_context=context,
        )


def _naive(value: datetime) -> datetime:
    return value.replace(tzinfo=None)
