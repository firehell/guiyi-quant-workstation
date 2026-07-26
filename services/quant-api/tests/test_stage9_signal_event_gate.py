from datetime import date, datetime
import json

from app.models.signal import SignalEvent
from app.signal.stage9_gate import evaluate_stage9_signal_event_gate


def test_stage9_gate_allows_entry_event_with_actual_contract_context() -> None:
    event = _event(
        payload={
            "signal": {
                "webhook_url": "redacted",
                "reason": "test signal",
            }
        }
    )

    result = evaluate_stage9_signal_event_gate(event)

    assert result["allowed"] is True
    assert result["blocked_reasons"] == []
    assert result["payload_basis"]["notice_scope"] == "observation_only"
    assert result["payload_basis"]["trading_instruction"] == "not_trading_instruction"
    assert result["payload_basis"]["actual_contract"] == "JM2609"
    assert _contains_no_secret_words(result["payload_basis"])


def test_stage9_gate_blocks_missing_actual_contract() -> None:
    event = _event(actual_contract=None)

    result = evaluate_stage9_signal_event_gate(event)

    assert result["allowed"] is False
    assert "actual_contract_missing" in result["blocked_reasons"]


def test_stage9_gate_blocks_main_contract_as_actual_contract() -> None:
    event = _event(actual_contract="jm.MAIN")

    result = evaluate_stage9_signal_event_gate(event)

    assert result["allowed"] is False
    assert "actual_contract_is_continuous_contract" in result["blocked_reasons"]


def test_stage9_gate_blocks_missing_bar_or_trigger_price() -> None:
    event = _event(bar_end=None, trigger_price=None)

    result = evaluate_stage9_signal_event_gate(event)

    assert result["allowed"] is False
    assert "bar_end_missing" in result["blocked_reasons"]
    assert "trigger_price_missing" in result["blocked_reasons"]


def test_stage9_gate_blocks_non_passed_quality_status() -> None:
    event = _event(quality_status={"status": "warning"})

    result = evaluate_stage9_signal_event_gate(event)

    assert result["allowed"] is False
    assert "quality_status_not_passed:warning" in result["blocked_reasons"]


def test_stage9_gate_rejects_non_exact_future_repainting_event() -> None:
    event = _event(
        payload={
            "signal": {
                "features": {
                    "future_looking": True,
                    "repainting_accepted": True,
                }
            }
        }
    )

    result = evaluate_stage9_signal_event_gate(event)

    assert result["allowed"] is False
    assert "future_repainting_event_not_allowed" in result["blocked_reasons"]


def _event(**overrides) -> SignalEvent:
    values = {
        "event_key": "signal_created:jm:JM2609:15m:20260707T150000",
        "event_type": "signal_created",
        "signal_id": 1,
        "task_no": "task-stage9-gate",
        "source_mode": "live_confirmed",
        "strategy_name": "jm_v1b_daily_direction_fast_entry",
        "strategy_version": "v1b.0",
        "watchlist_code": "jm_v1b",
        "symbol": "jm",
        "contract": "JM2609",
        "product": "jm",
        "continuous_contract": "jm.MAIN",
        "actual_contract": "JM2609",
        "dominant_mapping_date": date(2026, 7, 7),
        "exchange": "DCE",
        "period": "15m",
        "signal_time": datetime(2026, 7, 7, 15, 0),
        "bar_start": datetime(2026, 7, 7, 14, 45),
        "bar_end": datetime(2026, 7, 7, 15, 0),
        "trigger_price": 1234.5,
        "provider": "rqdata",
        "source": "live_db_actual_contract",
        "direction": "long",
        "signal_status": "entry_signal",
        "lifecycle_status": "new",
        "score_bucket": 80,
        "data_role": "primary",
        "quality_status": {"status": "passed"},
        "payload": {"signal": {"reason": "test signal"}},
        "profile_id": "live_observation_v1",
        "market_data_file_id": 101,
    }
    values.update(overrides)
    payload = dict(values.get("payload") or {})
    payload.setdefault("formal_lineage", _formal_lineage())
    values["payload"] = payload
    return SignalEvent(**values)


def _formal_lineage() -> dict:
    return {
        "schema_version": "signal_review_lineage_v1",
        "resolver_name": "ProfileLineageResolver",
        "resolver_contract_version": "signal_profile_v1",
        "quality_policy": "passed_only",
        "primary": {
            "profile_id": "live_observation_v1",
            "market_data_file_id": 101,
            "provider": "rqdata",
            "data_role": "primary",
            "quality_status": "passed",
        },
        "contract": {
            "continuous_contract": "jm.MAIN",
            "actual_contract": "JM2609",
            "dominant_mapping_date": "2026-07-07",
        },
        "bar": {
            "bar_start": "2026-07-07T14:45:00",
            "bar_end": "2026-07-07T15:00:00",
            "trigger_price": 1234.5,
            "confirmation_mode": "live_confirmed",
            "bar_status": "confirmed",
            "live_bar_id": 501,
            "live_bar_revision": 1,
            "confirmed_at": "2026-07-07T15:00:01+00:00",
        },
    }


def _contains_no_secret_words(payload: dict) -> bool:
    text = json.dumps(payload, ensure_ascii=False, default=str).lower()
    return not any(secret in text for secret in ("webhook", "token", "password", "cookie", "secret"))
