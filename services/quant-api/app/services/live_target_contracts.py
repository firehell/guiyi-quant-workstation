from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.data_center import (
    LiveAggregatedBar,
    LiveMinuteBar,
    MainContractMap,
    MarketDataFile,
)
from app.services.market_data_reader import ACTIVE_DATA_ROLE, ACTIVE_PRIMARY_PROVIDERS
from app.services.market_dominant_reader import continuous_contract_for, is_continuous_contract
from app.services.actual_contract_semantics import (
    RULE,
    load_effective_fee_margin_rule,
    load_effective_main_contract_mapping,
    load_effective_trading_parameters,
)

PROVIDER = "rqdata"
TARGET_PRODUCTS = ("jm",)
REQUIRED_HISTORICAL_PERIODS = ("1m", "5m", "15m")


class LiveTargetContractError(ValueError):
    """Raised when a live evaluator request does not match the resolved target contract."""


class LiveTargetContractResolver:
    """Resolve readonly live-listening targets from the active actual-contract metadata chain."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list_targets(self, *, products: tuple[str, ...] = TARGET_PRODUCTS, trade_date: date | None = None) -> dict[str, Any]:
        items = [self.resolve_product(product, trade_date=trade_date) for product in products]
        status = _aggregate_readiness([item["readiness_status"] for item in items])
        payload = {
            "provider": PROVIDER,
            "target_products": list(products),
            "trade_date": trade_date.isoformat() if trade_date else None,
            "readiness_status": status,
            "preview_only": True,
            "writes_strategy_signal": False,
            "writes_signal_event": False,
            "sends_notification": False,
            "auto_order": False,
            "items": items,
        }
        return sanitize_live_targets_payload(payload)

    def resolve_product(self, product: str, *, trade_date: date | None = None) -> dict[str, Any]:
        normalized_product = _normalize_product(product)
        continuous_contract = continuous_contract_for(normalized_product)
        mapping = self._mapping(normalized_product, trade_date=trade_date)
        blocked_reasons: list[str] = []
        actual_contract: str | None = None
        dominant_mapping_date: date | None = None

        if mapping is None:
            blocked_reasons.append("main_contract_map_rank1_missing")
        else:
            dominant_mapping_date = mapping.trade_date
            actual_contract = _actual_contract_or_none(mapping.contract_code)
            if actual_contract is None:
                blocked_reasons.append("main_contract_map_rank1_not_actual_contract")

        parameter_gate = _empty_parameter_gate(normalized_product, actual_contract, dominant_mapping_date)
        historical_coverage: dict[str, Any] = {}
        live_coverage: dict[str, Any] = {}
        if actual_contract is not None and dominant_mapping_date is not None:
            parameter_gate = self._parameter_gate(
                product=normalized_product,
                contract=actual_contract,
                trade_date=dominant_mapping_date,
            )
            if parameter_gate["status"] != "passed":
                blocked_reasons.append("trading_parameter_gate_failed")
            historical_coverage = self._historical_coverage(normalized_product, actual_contract)
            missing_periods = [period for period in REQUIRED_HISTORICAL_PERIODS if not _coverage_passed(historical_coverage.get(period))]
            if missing_periods:
                blocked_reasons.append(f"historical_actual_contract_coverage_missing:{','.join(missing_periods)}")
            live_coverage = self._live_coverage(normalized_product, actual_contract)

        return {
            "product": normalized_product,
            "continuous_contract": continuous_contract,
            "actual_contract": actual_contract,
            "dominant_mapping_date": dominant_mapping_date.isoformat() if dominant_mapping_date else None,
            "provider": PROVIDER,
            "data_role": ACTIVE_DATA_ROLE,
            "required_historical_periods": list(REQUIRED_HISTORICAL_PERIODS),
            "readiness_status": "blocked" if blocked_reasons else "ready",
            "blocked_reasons": blocked_reasons,
            "trading_parameter_status": parameter_gate,
            "historical_coverage": historical_coverage,
            "live_coverage": live_coverage,
            "preview_only": True,
            "writes_strategy_signal": False,
            "writes_signal_event": False,
            "sends_notification": False,
            "auto_order": False,
        }

    def resolve_ready_actual_contract(self, *, product: str, requested_contract: str | None = None) -> dict[str, Any]:
        target = self.resolve_product(product)
        actual_contract = target["actual_contract"]
        if actual_contract is None:
            raise LiveTargetContractError(f"live target actual_contract missing: {', '.join(target['blocked_reasons'])}")
        if target["blocked_reasons"]:
            raise LiveTargetContractError(f"live target not ready: {', '.join(target['blocked_reasons'])}")
        if requested_contract:
            normalized_request = requested_contract.strip()
            if is_continuous_contract(normalized_request):
                raise LiveTargetContractError("live evaluator requires actual_contract; *.MAIN is research-only")
            if normalized_request.upper() != actual_contract.upper():
                raise LiveTargetContractError(f"requested contract {requested_contract} does not match live target {actual_contract}")
        return target

    def _mapping(self, product: str, *, trade_date: date | None) -> MainContractMap | None:
        return load_effective_main_contract_mapping(
            self.session,
            instrument_symbol=product,
            trade_date=trade_date,
            provider=PROVIDER,
            rule=RULE,
            rank=1,
        )

    def _parameter_gate(self, *, product: str, contract: str, trade_date: date) -> dict[str, Any]:
        params = load_effective_trading_parameters(
            self.session,
            contract_code=contract,
            trade_date=trade_date,
            provider=PROVIDER,
        )
        exchange_code = str(getattr(params, "exchange_code", None) or "DCE")
        fee_rule = load_effective_fee_margin_rule(
            self.session,
            contract_code=contract,
            instrument_symbol=product,
            exchange_code=exchange_code,
            trade_date=trade_date,
            provider=PROVIDER,
        )
        values = {
            "price_tick": _first_present(getattr(params, "price_tick", None), getattr(fee_rule, "price_tick", None)),
            "contract_multiplier": _first_present(getattr(params, "contract_multiplier", None), getattr(fee_rule, "volume_multiple", None)),
            "margin": _first_present(getattr(params, "short_margin_ratio", None), getattr(params, "long_margin_ratio", None), getattr(fee_rule, "margin_rate", None)),
            "open_commission": _first_present(getattr(params, "open_commission", None), getattr(fee_rule, "open_fee", None)),
            "close_commission": _first_present(getattr(params, "close_commission", None), getattr(fee_rule, "close_fee", None)),
            "close_today_commission": _first_present(getattr(params, "close_today_commission", None), getattr(fee_rule, "close_today_fee", None)),
            "exchange_code": _first_present(getattr(params, "exchange_code", None), getattr(fee_rule, "exchange_code", None)),
        }
        missing = [
            field
            for field in ("price_tick", "contract_multiplier", "margin", "open_commission", "close_commission", "close_today_commission")
            if values[field] is None
        ]
        if params is not None and fee_rule is not None:
            source = "mixed"
        elif params is not None:
            source = "futures_trading_parameters"
        elif fee_rule is not None:
            source = "fee_margin_rules"
        else:
            source = None
        return {
            "status": "failed" if missing else "passed",
            "source": source,
            "missing_fields": missing,
            "product": product,
            "contract_code": contract,
            "trade_date": trade_date.isoformat(),
            "exchange_code": values["exchange_code"],
        }

    def _historical_coverage(self, product: str, contract: str) -> dict[str, Any]:
        rows = self.session.scalars(
            select(MarketDataFile).where(
                MarketDataFile.provider.in_(tuple(ACTIVE_PRIMARY_PROVIDERS)),
                MarketDataFile.data_type == "bars",
                MarketDataFile.instrument_symbol == product,
                MarketDataFile.contract_code == contract,
                MarketDataFile.data_role == ACTIVE_DATA_ROLE,
                MarketDataFile.quality_status != "failed",
                MarketDataFile.period.is_not(None),
            )
        )
        grouped: dict[str, dict[str, Any]] = {}
        for row in rows:
            period = row.period or ""
            record = grouped.setdefault(
                period,
                {
                    "available": True,
                    "provider": row.provider,
                    "data_type": row.data_type,
                    "data_role": row.data_role,
                    "start_time": row.start_time,
                    "end_time": row.end_time,
                    "latest_bar_time": row.end_time,
                    "row_count": 0,
                    "quality_statuses": [],
                    "data_versions": [],
                },
            )
            record["start_time"] = min(record["start_time"], row.start_time)
            record["end_time"] = max(record["end_time"], row.end_time)
            record["latest_bar_time"] = record["end_time"]
            record["row_count"] += row.row_count or 0
            record["quality_statuses"].append(row.quality_status)
            record["data_versions"].append(row.data_version)
            # file paths are collected only for internal aggregation; never returned on API.

        return {
            period: {
                "available": True,
                "provider": record["provider"],
                "data_type": record["data_type"],
                "data_role": record["data_role"],
                "start_time": _iso(record["start_time"]),
                "end_time": _iso(record["end_time"]),
                "latest_bar_time": _iso(record["latest_bar_time"]),
                "row_count": record["row_count"],
                "quality_status": _aggregate_quality(record["quality_statuses"]),
                "data_version": _join_distinct(record["data_versions"]),
                "file_path": None,
            }
            for period, record in sorted(grouped.items(), key=lambda item: _period_rank(item[0]))
        }

    def _live_coverage(self, product: str, contract: str) -> dict[str, Any]:
        rows = []
        rows.extend(_live_rows(self.session, LiveMinuteBar, product=product, contract=contract))
        rows.extend(_live_rows(self.session, LiveAggregatedBar, product=product, contract=contract))
        grouped: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "available": True,
                "provider": PROVIDER,
                "data_type": "live_db",
                "source_mode": None,
                "start_time": None,
                "end_time": None,
                "latest_bar_time": None,
                "row_count": 0,
                "quality_statuses": [],
                "failed_count": 0,
                "rejected_count": 0,
            }
        )
        for row in rows:
            period = row.period
            record = grouped[period]
            record["provider"] = row.provider
            record["source_mode"] = row.source_mode
            record["start_time"] = row.bar_datetime if record["start_time"] is None else min(record["start_time"], row.bar_datetime)
            record["end_time"] = row.bar_datetime if record["end_time"] is None else max(record["end_time"], row.bar_datetime)
            record["latest_bar_time"] = record["end_time"]
            record["row_count"] += 1
            record["quality_statuses"].append(row.quality_status)
            if row.quality_status == "failed":
                record["failed_count"] += 1
            if row.bar_status == "rejected":
                record["rejected_count"] += 1

        return {
            period: {
                "available": True,
                "provider": record["provider"],
                "data_type": record["data_type"],
                "source_mode": record["source_mode"],
                "start_time": _iso(record["start_time"]),
                "end_time": _iso(record["end_time"]),
                "latest_bar_time": _iso(record["latest_bar_time"]),
                "row_count": record["row_count"],
                "quality_status": _aggregate_quality(record["quality_statuses"]),
                "failed_count": record["failed_count"],
                "rejected_count": record["rejected_count"],
            }
            for period, record in sorted(grouped.items(), key=lambda item: _period_rank(item[0]))
        }


def _live_rows(session: Session, model: type[LiveMinuteBar] | type[LiveAggregatedBar], *, product: str, contract: str) -> list[LiveMinuteBar | LiveAggregatedBar]:
    return list(
        session.scalars(
            select(model).where(
                model.provider == PROVIDER,
                model.instrument_symbol == product,
                model.contract_code == contract,
            )
        )
    )


def _normalize_product(product: str) -> str:
    normalized = (product or "").strip().lower()
    if normalized not in TARGET_PRODUCTS:
        raise LiveTargetContractError("Stage 8.5-8 live target resolver is JM-only")
    return normalized


def _actual_contract_or_none(value: str | None) -> str | None:
    contract = (value or "").strip().upper()
    if not contract or is_continuous_contract(contract) or "." in contract:
        return None
    return contract


def _empty_parameter_gate(product: str, contract: str | None, trade_date: date | None) -> dict[str, Any]:
    return {
        "status": "missing",
        "source": None,
        "missing_fields": ["main_contract_map"],
        "product": product,
        "contract_code": contract,
        "trade_date": trade_date.isoformat() if trade_date else None,
        "exchange_code": None,
    }


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def sanitize_live_targets_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Strip physical paths from live targets API payload (C6-07A)."""

    def _scrub_coverage(coverage: Any) -> Any:
        if not isinstance(coverage, dict):
            return coverage
        cleaned: dict[str, Any] = {}
        for period, item in coverage.items():
            if not isinstance(item, dict):
                cleaned[period] = item
                continue
            row = dict(item)
            row["file_path"] = None
            row.pop("file_paths", None)
            cleaned[period] = row
        return cleaned

    out = dict(payload)
    items = []
    for item in out.get("items") or []:
        if not isinstance(item, dict):
            items.append(item)
            continue
        row = dict(item)
        if "historical_coverage" in row:
            row["historical_coverage"] = _scrub_coverage(row.get("historical_coverage"))
        if "live_coverage" in row:
            row["live_coverage"] = _scrub_coverage(row.get("live_coverage"))
        items.append(row)
    out["items"] = items
    return out


def _coverage_passed(coverage: dict[str, Any] | None) -> bool:
    return bool(coverage and coverage.get("available") and coverage.get("quality_status") == "passed")


def _aggregate_readiness(statuses: list[str]) -> str:
    return "blocked" if "blocked" in statuses else "ready"


def _aggregate_quality(statuses: list[str]) -> str:
    if "failed" in statuses:
        return "failed"
    if "warning" in statuses:
        return "warning"
    if "unchecked" in statuses:
        return "unchecked"
    return "passed" if statuses else "missing"


def _join_distinct(values: list[str | None]) -> str | None:
    distinct = [value for value in dict.fromkeys(values) if value]
    return ",".join(distinct) if distinct else None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _period_rank(period: str) -> tuple[int, str]:
    order = {"1m": 0, "5m": 1, "15m": 2, "30m": 3, "60m": 4, "1d": 5}
    return (order.get(period, 99), period)
