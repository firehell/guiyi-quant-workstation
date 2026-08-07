from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.models.signal import SignalEvent

ALLOWED_EVENT_TYPES = {"signal_created", "signal_changed"}
ALLOWED_PROVIDERS = {"rqdata", "local_parquet"}
REQUIRED_SIGNAL_STATUS = "entry_signal"
REQUIRED_DATA_ROLE = "primary"
REQUIRED_QUALITY_STATUS = "passed"
SENSITIVE_KEY_PARTS = ("webhook", "token", "password", "passwd", "secret", "cookie")
RETIRED_HTDY_STRATEGY_CODE = "htdy_original_realtime_first_seen"
RETIRED_HTDY_SOURCE_MODE = "live_realtime_repainting"


def evaluate_stage9_signal_event_gate(event: SignalEvent) -> dict[str, Any]:
    """Return the readonly Stage 9 notification gate decision for a signal event."""
    blocked_reasons = _blocked_reasons(event)
    return {
        "allowed": not blocked_reasons,
        "blocked_reasons": blocked_reasons,
        "delivery_allowed": not blocked_reasons,
        "delivery_blocked_reasons": list(blocked_reasons),
        "payload_basis": _payload_basis(event),
    }


def _blocked_reasons(event: SignalEvent) -> list[str]:
    reasons: list[str] = []
    if event.event_type not in ALLOWED_EVENT_TYPES:
        reasons.append(f"event_type_not_allowed:{event.event_type}")
    if event.signal_status != REQUIRED_SIGNAL_STATUS:
        reasons.append(f"signal_status_not_entry_signal:{event.signal_status}")
    if not _string_value(event.product):
        reasons.append("product_missing")
    if not _string_value(event.continuous_contract):
        reasons.append("continuous_contract_missing")

    actual_contract = _string_value(event.actual_contract)
    if not actual_contract:
        reasons.append("actual_contract_missing")
    elif _is_continuous_contract(actual_contract):
        reasons.append("actual_contract_is_continuous_contract")

    if event.dominant_mapping_date is None:
        reasons.append("dominant_mapping_date_missing")
    if event.bar_end is None:
        reasons.append("bar_end_missing")
    if event.trigger_price is None:
        reasons.append("trigger_price_missing")
    elif event.trigger_price <= 0:
        reasons.append("trigger_price_not_positive")

    provider = _string_value(event.provider)
    if provider not in ALLOWED_PROVIDERS:
        reasons.append(f"provider_not_allowed:{provider or 'missing'}")
    if event.data_role != REQUIRED_DATA_ROLE:
        reasons.append(f"data_role_not_primary:{event.data_role or 'missing'}")

    quality_status = _quality_status_value(event.quality_status)
    if quality_status != REQUIRED_QUALITY_STATUS:
        reasons.append(f"quality_status_not_passed:{quality_status}")
    if (
        event.strategy_name == RETIRED_HTDY_STRATEGY_CODE
        or event.source_mode == RETIRED_HTDY_SOURCE_MODE
    ):
        reasons.append("htdy_realtime_retired")
        return reasons
    signal = (event.payload or {}).get("signal")
    features = signal.get("features") if isinstance(signal, dict) else None
    if isinstance(features, dict) and (
        features.get("future_looking") is True
        or features.get("repainting_accepted") is True
    ):
        reasons.append("future_repainting_event_not_allowed")
    reasons.extend(_formal_lineage_blocked_reasons(event))
    return reasons



def _formal_lineage_blocked_reasons(event: SignalEvent) -> list[str]:
    lineage = (event.payload or {}).get("formal_lineage")
    if not isinstance(lineage, dict):
        return ["formal_lineage_missing"]
    primary = lineage.get("primary")
    contract = lineage.get("contract")
    bar = lineage.get("bar")
    if not isinstance(primary, dict) or not isinstance(contract, dict) or not isinstance(bar, dict):
        return ["formal_lineage_invalid"]
    reasons: list[str] = []
    if lineage.get("schema_version") != "signal_review_lineage_v1":
        reasons.append("formal_lineage_schema_invalid")
    if lineage.get("resolver_name") != "ProfileLineageResolver" or lineage.get("resolver_contract_version") != "signal_profile_v1":
        reasons.append("formal_lineage_resolver_invalid")
    if lineage.get("quality_policy") != "passed_only":
        reasons.append("formal_lineage_quality_policy_invalid")
    if not event.profile_id or event.market_data_file_id is None:
        reasons.append("formal_lineage_columns_missing")
    if primary.get("profile_id") != event.profile_id or primary.get("market_data_file_id") != event.market_data_file_id:
        reasons.append("formal_lineage_asset_mismatch")
    if primary.get("provider") != event.provider or primary.get("data_role") != event.data_role:
        reasons.append("formal_lineage_source_mismatch")
    if primary.get("quality_status") != "passed":
        reasons.append("formal_lineage_quality_not_passed")
    if contract.get("continuous_contract") != event.continuous_contract or contract.get("actual_contract") != event.actual_contract:
        reasons.append("formal_lineage_contract_mismatch")
    mapping_date = event.dominant_mapping_date.isoformat() if event.dominant_mapping_date else None
    if contract.get("dominant_mapping_date") != mapping_date:
        reasons.append("formal_lineage_mapping_mismatch")
    bar_end = event.bar_end.isoformat() if event.bar_end else None
    if bar.get("bar_end") != bar_end or bar.get("trigger_price") != event.trigger_price:
        reasons.append("formal_lineage_bar_mismatch")
    confirmation_mode = bar.get("confirmation_mode")
    if event.source_mode == "live_confirmed":
        if confirmation_mode != "live_confirmed" or bar.get("bar_status") != "confirmed":
            reasons.append("formal_lineage_bar_unconfirmed")
        if not isinstance(bar.get("live_bar_id"), int) or not isinstance(bar.get("live_bar_revision"), int):
            reasons.append("formal_lineage_live_bar_identity_missing")
    elif confirmation_mode != "historical_canonical":
        reasons.append("formal_lineage_historical_bar_unconfirmed")
    return reasons


def _payload_basis(event: SignalEvent) -> dict[str, Any]:
    return {
        "notice_scope": "observation_only",
        "trading_instruction": "not_trading_instruction",
        "auto_order": False,
        "event_key": event.event_key,
        "event_type": event.event_type,
        "signal_id": event.signal_id,
        "strategy_name": event.strategy_name,
        "strategy_version": event.strategy_version,
        "product": event.product,
        "continuous_contract": event.continuous_contract,
        "actual_contract": event.actual_contract,
        "dominant_mapping_date": _iso(event.dominant_mapping_date),
        "exchange": event.exchange,
        "period": event.period,
        "bar_end": _iso(event.bar_end),
        "trigger_price": event.trigger_price,
        "provider": event.provider,
        "source": event.source,
        "data_role": event.data_role,
        "quality_status": _sanitize(event.quality_status or {}),
        "direction": event.direction,
        "signal_status": event.signal_status,
        "score_bucket": event.score_bucket,
        "source_payload": _sanitize(event.payload or {}),
    }


def _quality_status_value(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("status") or "missing")
    if value is None:
        return "missing"
    return str(value)


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _is_sensitive_text(key_text):
                continue
            clean[key_text] = _sanitize(item)
        return clean
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, str) and _is_sensitive_text(value):
        return "[redacted]"
    return value


def _is_sensitive_text(value: str) -> bool:
    normalized = value.lower()
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)


def _is_continuous_contract(value: str) -> bool:
    return value.strip().lower().endswith(".main")


def _string_value(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
