from __future__ import annotations

from copy import deepcopy
from datetime import date

import pytest


SHA = {
    "deployment_receipt_sha256": "1" * 64,
    "s6_07_final_receipt_sha256": "2" * 64,
    "service_bundle_sha256": "3" * 64,
    "source_sha256": "4" * 64,
    "policy_sha256": "5" * 64,
    "writer_sha256": "6" * 64,
}
RUNTIME_COMMIT = "7" * 40
BASELINE = {
    "strategy_signals": 10,
    "signal_events": 20,
    "signal_notifications": 30,
    "signal_scan_tasks": 40,
    "orders": 0,
    "trades": 0,
}


def _parent():
    from app.services.htdy_s6_08_schema_v3 import (
        build_parent_authorization,
    )

    return build_parent_authorization(
        trading_days=[
            date(2026, 7, 27),
            date(2026, 7, 28),
        ],
        runtime_commit=RUNTIME_COMMIT,
        database_revision="20260721_0025",
        **SHA,
    )


def _child():
    from app.services.htdy_s6_08_schema_v3 import (
        build_daily_child_authorization,
    )

    parent = _parent()
    return parent, build_daily_child_authorization(
        parent_packet=parent,
        parent_approval_hash=parent["packet_hash"],
        trading_day=date(2026, 7, 27),
        actual_contract="JM2609",
        mapping_sha256="8" * 64,
        baseline_counts=BASELINE,
    )


def test_parent_packet_is_schema_v3_hash_bound_and_bounded_to_five_days() -> None:
    from app.services.htdy_s6_08_schema_v3 import (
        HtDySchemaV3GateError,
        canonical_packet_hash,
    )

    packet = _parent()

    assert packet["schema_version"] == 3
    assert packet["packet_type"] == "htdy_s6_08_bounded_parent"
    assert packet["packet_hash"] == canonical_packet_hash(packet)
    assert packet["trading_days"] == ["2026-07-27", "2026-07-28"]
    assert packet["strategy"]["strategy_code"] == "htdy_original_realtime_first_seen"
    assert packet["event_contract"]["allowed_event_types"] == ["signal_created"]
    assert packet["event_contract"]["signal_changed_allowed"] is False
    assert packet["scope"]["signal_notifications"] == "forbidden"
    assert packet["scope"]["auto_order"] is False

    from app.services.htdy_s6_08_schema_v3 import build_parent_authorization

    with pytest.raises(HtDySchemaV3GateError, match="trading_days_bounded"):
        build_parent_authorization(
            trading_days=[
                date(2026, 7, day)
                for day in range(20, 26)
            ],
            runtime_commit=RUNTIME_COMMIT,
            database_revision="20260721_0025",
            **SHA,
        )


def test_parent_verifier_rejects_schema_v2_and_every_bound_hash_drift() -> None:
    from app.services.htdy_s6_08_schema_v3 import (
        HtDySchemaV3GateError,
        verify_parent_authorization,
    )

    parent = _parent()
    current = deepcopy(parent["bindings"])
    verify_parent_authorization(
        parent,
        approval_hash=parent["packet_hash"],
        current_bindings=current,
    )

    old = deepcopy(parent)
    old["schema_version"] = 2
    with pytest.raises(HtDySchemaV3GateError, match="schema_version"):
        verify_parent_authorization(
            old,
            approval_hash=parent["packet_hash"],
            current_bindings=current,
        )

    for key in SHA:
        drifted = deepcopy(current)
        drifted[key] = "9" * 64
        with pytest.raises(HtDySchemaV3GateError, match="binding_drift"):
            verify_parent_authorization(
                parent,
                approval_hash=parent["packet_hash"],
                current_bindings=drifted,
            )


def test_daily_child_binds_one_permitted_day_actual_mapping_and_baseline() -> None:
    from app.services.htdy_s6_08_schema_v3 import (
        canonical_packet_hash,
        verify_daily_child_authorization,
    )

    parent, child = _child()

    assert child["schema_version"] == 3
    assert child["packet_type"] == "htdy_s6_08_exact_daily_child"
    assert child["parent_packet_hash"] == parent["packet_hash"]
    assert child["packet_hash"] == canonical_packet_hash(child)
    assert child["trading_day"] == "2026-07-27"
    assert child["actual_contract"] == "JM2609"
    assert child["baseline_counts"] == BASELINE

    verify_daily_child_authorization(
        child,
        approval_hash=child["packet_hash"],
        parent_packet=parent,
        parent_approval_hash=parent["packet_hash"],
        current_trading_day=date(2026, 7, 27),
        current_actual_contract="JM2609",
        current_mapping_sha256="8" * 64,
        current_counts=BASELINE,
    )


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("day", date(2026, 7, 29), "child_day_not_authorized"),
        ("contract", "jm.MAIN", "actual_contract"),
        ("mapping", "9" * 64, "mapping_drift"),
        (
            "counts",
            {**BASELINE, "signal_events": 21},
            "baseline_drift",
        ),
    ],
)
def test_daily_child_fails_closed_on_scope_or_runtime_drift(
    field: str,
    value: object,
    code: str,
) -> None:
    from app.services.htdy_s6_08_schema_v3 import (
        HtDySchemaV3GateError,
        build_daily_child_authorization,
        verify_daily_child_authorization,
    )

    parent = _parent()
    if field == "day":
        with pytest.raises(HtDySchemaV3GateError, match=code):
            build_daily_child_authorization(
                parent_packet=parent,
                parent_approval_hash=parent["packet_hash"],
                trading_day=value,
                actual_contract="JM2609",
                mapping_sha256="8" * 64,
                baseline_counts=BASELINE,
            )
        return
    if field == "contract":
        with pytest.raises(HtDySchemaV3GateError, match=code):
            build_daily_child_authorization(
                parent_packet=parent,
                parent_approval_hash=parent["packet_hash"],
                trading_day=date(2026, 7, 27),
                actual_contract=value,
                mapping_sha256="8" * 64,
                baseline_counts=BASELINE,
            )
        return

    _, child = _child()
    kwargs = {
        "current_trading_day": date(2026, 7, 27),
        "current_actual_contract": "JM2609",
        "current_mapping_sha256": "8" * 64,
        "current_counts": BASELINE,
    }
    if field == "mapping":
        kwargs["current_mapping_sha256"] = value
    else:
        kwargs["current_counts"] = value
    with pytest.raises(HtDySchemaV3GateError, match=code):
        verify_daily_child_authorization(
            child,
            approval_hash=child["packet_hash"],
            parent_packet=parent,
            parent_approval_hash=parent["packet_hash"],
            **kwargs,
        )


def _event(*, event_type: str = "signal_created") -> dict[str, object]:
    return {
        "event_key": f"{event_type}:htdy-first-seen:{'a' * 64}:created",
        "event_type": event_type,
        "source_mode": "live_realtime_repainting",
        "strategy_name": "htdy_original_realtime_first_seen",
        "strategy_version": "v1.0",
        "product": "jm",
        "actual_contract": "JM2609",
        "dominant_mapping_date": "2026-07-27",
        "period": "15m",
        "direction": "long",
        "payload": {
            "formal_lineage": {
                "schema_version": "signal_review_lineage_v2",
                "indicator": {
                    "indicator_code": "huotian_dayou_original_v0",
                    "indicator_version": "original-v0",
                    "signal_policy": "htdy_original_xma_15m_first_seen_v1",
                    "future_looking": True,
                    "repainting_accepted": True,
                    "first_seen_no_retraction": True,
                    "live_confirmed_required": False,
                    "partial_allowed": True,
                    "confirmed_allowed": True,
                    "historical_backtest_allowed": False,
                    "notification_ready": False,
                    "auto_order": False,
                },
            },
        },
    }


def test_execution_verifier_accepts_created_only_and_zero_forbidden_deltas() -> None:
    from app.services.htdy_s6_08_schema_v3 import verify_daily_execution

    _, child = _child()
    final_counts = {
        **BASELINE,
        "strategy_signals": 11,
        "signal_events": 21,
    }

    result = verify_daily_execution(
        child,
        approval_hash=child["packet_hash"],
        events=[_event()],
        final_counts=final_counts,
    )

    assert result == {
        "status": "passed",
        "gate": "HTDY_S6_08_SCHEMA_V3_CODE_VERIFIED",
        "trading_day": "2026-07-27",
        "created_events": 1,
        "forbidden_write_deltas": {
            "signal_notifications": 0,
            "signal_scan_tasks": 0,
            "orders": 0,
            "trades": 0,
        },
    }


def test_execution_verifier_requires_at_least_one_natural_created_event() -> None:
    from app.services.htdy_s6_08_schema_v3 import (
        HtDySchemaV3GateError,
        verify_daily_execution,
    )

    _, child = _child()
    with pytest.raises(HtDySchemaV3GateError, match="event_required"):
        verify_daily_execution(
            child,
            approval_hash=child["packet_hash"],
            events=[],
            final_counts=BASELINE,
        )


@pytest.mark.parametrize(
    ("events", "final_counts", "code"),
    [
        (
            [_event(event_type="signal_changed")],
            {**BASELINE, "strategy_signals": 11, "signal_events": 21},
            "event_contract",
        ),
        (
            [_event()],
            {
                **BASELINE,
                "strategy_signals": 11,
                "signal_events": 21,
                "signal_notifications": 31,
            },
            "forbidden_write_delta",
        ),
        (
            [_event()],
            {**BASELINE, "strategy_signals": 12, "signal_events": 21},
            "allowed_write_delta",
        ),
    ],
)
def test_execution_verifier_rejects_changed_event_or_any_counter_drift(
    events: list[dict[str, object]],
    final_counts: dict[str, int],
    code: str,
) -> None:
    from app.services.htdy_s6_08_schema_v3 import (
        HtDySchemaV3GateError,
        verify_daily_execution,
    )

    _, child = _child()
    with pytest.raises(HtDySchemaV3GateError, match=code):
        verify_daily_execution(
            child,
            approval_hash=child["packet_hash"],
            events=events,
            final_counts=final_counts,
        )
