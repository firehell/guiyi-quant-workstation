from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.db.session import PROJECT_ROOT
from app.models.data_center import LiveAggregatedBar
from app.services.actual_contract_semantics import load_effective_main_contract_mapping
from app.services.live_signal_context import historical_context_hash
from app.services.market_data_reader import MarketDataReader
from app.services.profile_lineage import ProfileLineageResolver
from app.services.rqdata_ingest.parquet import sha256_file


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
        self.reader = MarketDataReader(session, project_root=project_root)

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
                rows = self.reader.load_bars_from_market_file(
                    market_data_file_id=market_file.id,
                    symbol=symbol,
                    contract=actual_contract,
                    period=period,
                    start=bar_end,
                    end=bar_end,
                )
            except ValueError:
                return self._blocked("SIGNAL_CONFIRMED_BAR_MISSING", context)
            if len(rows) != 1:
                return self._blocked("SIGNAL_CONFIRMED_BAR_MISSING", context)
            if float(rows[0]["close"]) != float(trigger_price):
                return self._blocked("SIGNAL_TRIGGER_PRICE_MISMATCH", context)
        elif confirmation_mode == "live_confirmed":
            context_check = self._verify_historical_context(
                context_payload=historical_context,
                market_file=market_file,
                symbol=symbol,
                actual_contract=actual_contract,
                period=period,
                context=context,
            )
            if context_check is not None:
                return context_check
            live_bar_id = confirmation_payload.get("live_bar_id")
            live_revision = confirmation_payload.get("live_bar_revision")
            if not isinstance(live_bar_id, int) or not isinstance(live_revision, int):
                return self._blocked("SIGNAL_BAR_NOT_CONFIRMED", context)
            live_bar = self.session.get(LiveAggregatedBar, live_bar_id)
            if live_bar is None:
                return self._blocked("SIGNAL_CONFIRMED_BAR_MISSING", context)
            if (
                live_bar.instrument_symbol != symbol
                or live_bar.contract_code != actual_contract
                or live_bar.period != period
                or live_bar.revision != live_revision
                or _naive(live_bar.bar_datetime) != _naive(bar_end)
            ):
                return self._blocked("SIGNAL_LIVE_BAR_IDENTITY_MISMATCH", context)
            if (
                live_bar.provider != "rqdata"
                or live_bar.bar_status != "confirmed"
                or live_bar.quality_status != "passed"
                or live_bar.confirmed_at is None
            ):
                return self._blocked("SIGNAL_BAR_NOT_CONFIRMED", context)
            if float(live_bar.close) != float(trigger_price):
                return self._blocked("SIGNAL_TRIGGER_PRICE_MISMATCH", context)
            confirmation_payload = {
                "confirmation_mode": "live_confirmed",
                "bar_status": live_bar.bar_status,
                "live_bar_id": live_bar.id,
                "live_bar_revision": live_bar.revision,
                "confirmed_at": live_bar.confirmed_at.isoformat(),
            }
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
            "context_contract_version": "historical_live_context_v1" if confirmation_mode == "live_confirmed" else None,
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
        if confirmation_mode == "live_confirmed":
            snapshot["historical_context"] = dict(historical_context or {})
            snapshot["live_trigger"] = {
                "live_bar_id": confirmation_payload["live_bar_id"],
                "live_bar_revision": confirmation_payload["live_bar_revision"],
                "confirmed_at": confirmation_payload["confirmed_at"],
                "actual_contract": actual_contract,
                "dominant_mapping_date": dominant_mapping_date.isoformat(),
            }
        return SignalLineageResolution(
            profile_id=lineage.profile_id,
            market_data_file_id=market_file.id,
            snapshot=snapshot,
        )

    def _verify_historical_context(
        self,
        *,
        context_payload: dict[str, Any] | None,
        market_file: Any,
        symbol: str,
        actual_contract: str,
        period: str,
        context: dict[str, Any],
    ) -> SignalLineageResolution | None:
        if not isinstance(context_payload, dict) or context_payload.get("status") != "ready":
            return self._blocked("SIGNAL_HISTORICAL_CONTEXT_MISSING", context)
        expected = {
            "historical_context_file_id": market_file.id,
            "historical_context_data_version": market_file.data_version,
            "historical_context_file_checksum": market_file.checksum,
            "actual_contract": actual_contract,
        }
        if any(context_payload.get(field) != value for field, value in expected.items()):
            return self._blocked("SIGNAL_HISTORICAL_CONTEXT_IDENTITY_MISMATCH", context)
        raw_path = Path(market_file.file_path)
        physical_path = raw_path if raw_path.is_absolute() else self.project_root / raw_path
        if not market_file.checksum or not physical_path.is_file() or sha256_file(physical_path) != market_file.checksum:
            return self._blocked("SIGNAL_HISTORICAL_CONTEXT_FILE_DRIFT", context)
        try:
            start = datetime.fromisoformat(str(context_payload["historical_context_start"]))
            end = datetime.fromisoformat(str(context_payload["historical_context_end"]))
            expected_count = int(context_payload["historical_context_bar_count"])
            rows = self.reader.load_bars_from_market_file(
                market_data_file_id=market_file.id,
                symbol=symbol,
                contract=actual_contract,
                period=period,
                start=start,
                end=end,
                passed_only=True,
                expected_provider=market_file.provider,
                expected_data_role="primary",
                expected_quality_status="passed",
                expected_data_version=market_file.data_version,
                expected_checksum=market_file.checksum,
            )
        except (KeyError, TypeError, ValueError):
            return self._blocked("SIGNAL_HISTORICAL_CONTEXT_INVALID", context)
        if len(rows) != expected_count or historical_context_hash(rows) != context_payload.get("historical_context_hash"):
            return self._blocked("SIGNAL_HISTORICAL_CONTEXT_HASH_MISMATCH", context)
        return None

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
