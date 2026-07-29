from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest


def _event(
    event_id: int,
    *,
    version: str = "v1.1",
    bar_end: datetime | None = None,
    decision_bucket_end: datetime | None = None,
):
    decision_bucket_end = decision_bucket_end or datetime(
        2026, 7, 29, 6, 15, tzinfo=UTC
    )
    return SimpleNamespace(
        id=event_id,
        signal_id=event_id + 100,
        event_type="signal_created",
        source_mode="live_realtime_repainting",
        strategy_name="htdy_original_realtime_first_seen",
        strategy_version=version,
        product="jm",
        actual_contract="JM2609",
        period="15m",
        bar_end=bar_end or datetime(2026, 7, 29, 1, 15, tzinfo=UTC),
        dominant_mapping_date=date(2026, 7, 29),
        payload={
            "formal_lineage": {
                "indicator": {
                    "signal_policy": (
                        "htdy_original_xma_15m_close_first_seen_v1"
                    ),
                    "partial_allowed": False,
                    "live_confirmed_required": True,
                    "decision_trigger": "confirmed_15m_close",
                },
                "live_detection_snapshot": {
                    "decision_bucket_end": decision_bucket_end.isoformat()
                },
            },
        },
    )


def test_bounded_dispatch_selects_only_exact_window_events_and_caps_at_23() -> None:
    """Break caught: broad autosend or more than 23 messages in one day."""

    from app.services.htdy_s6_10_one_day_notifications import (
        select_bounded_delivery_events,
    )

    events = [_event(index) for index in range(1, 26)]
    events.extend(
        (
            _event(26, version="v1.0"),
            SimpleNamespace(**{**_event(27).__dict__, "event_type": "signal_changed"}),
        )
    )
    selected, capped, blocked = select_bounded_delivery_events(
        events,
        trading_day=date(2026, 7, 29),
        already_notified_event_ids={2},
        limit=23,
    )

    assert [event.id for event in selected] == [
        1,
        *range(3, 25),
    ]
    assert [event.id for event in capped] == [25]
    assert {event.id for event in blocked} == {26, 27}


def test_bounded_authorization_expires_at_window_end_and_keeps_global_autosend_false() -> None:
    """Break caught: reusing one-day authorization after its exact window."""

    from app.services.htdy_s6_10_one_day_notifications import (
        authorize_one_day_event,
    )

    event = _event(7)
    now = datetime(2026, 7, 29, 6, tzinfo=UTC)
    authorization = authorize_one_day_event(
        event=event,
        event_sha256="a" * 64,
        rendered_message_sha256="b" * 64,
        dedupe_key="enterprise_wechat:signal_event:7",
        now=now,
        window_end=datetime(2026, 7, 29, 8, tzinfo=UTC),
        global_autosend_enabled=False,
    )

    assert authorization.event_id == 7
    assert authorization.max_attempts == 3
    assert authorization.retry_deadline == datetime(
        2026, 7, 29, 8, tzinfo=UTC
    )
    assert authorization.authorization_scope == "s6_10_one_day_bounded"


def test_bounded_dispatch_fails_before_db_or_http_when_redis_is_down() -> None:
    from app.services.htdy_s6_10_one_day_notifications import (
        dispatch_bounded_one_day,
    )

    with pytest.raises(ValueError, match="FAIL_CLOSED"):
        dispatch_bounded_one_day(
            None,
            delivery_service=SimpleNamespace(
                now=datetime(2026, 7, 29, 6, tzinfo=UTC)
            ),
            trading_day=date(2026, 7, 29),
            window_end=datetime(2026, 7, 29, 8, tzinfo=UTC),
            parent_hash="a" * 64,
            global_autosend_enabled=False,
            redis_ready=False,
        )


def test_remaining_window_blocks_events_before_activation_allowlist() -> None:
    from app.services.htdy_s6_10_one_day_notifications import (
        select_bounded_delivery_events,
    )

    before_activation = _event(
        1,
        decision_bucket_end=datetime(2026, 7, 29, 1, 15, tzinfo=UTC),
    )
    allowed_close = datetime(2026, 7, 29, 1, 30, tzinfo=UTC)
    allowed = _event(
        2,
        bar_end=datetime(2026, 7, 28, 13, 45, tzinfo=UTC),
        decision_bucket_end=allowed_close,
    )

    selected, capped, blocked = select_bounded_delivery_events(
        [before_activation, allowed],
        trading_day=date(2026, 7, 29),
        already_notified_event_ids=set(),
        allowed_bucket_ends={allowed_close},
    )

    assert [event.id for event in selected] == [2]
    assert capped == []
    assert [event.id for event in blocked] == [1]


def test_remaining_window_requires_explicit_decision_bucket_end() -> None:
    """Historical events must never inherit a new delivery authorization."""

    from app.services.htdy_s6_10_one_day_notifications import (
        select_bounded_delivery_events,
    )

    missing = _event(1)
    missing.payload["formal_lineage"].pop("live_detection_snapshot")
    allowed_close = datetime(2026, 7, 29, 1, 30, tzinfo=UTC)

    selected, capped, blocked = select_bounded_delivery_events(
        [missing],
        trading_day=date(2026, 7, 29),
        already_notified_event_ids=set(),
        allowed_bucket_ends={allowed_close},
    )

    assert selected == []
    assert capped == []
    assert [event.id for event in blocked] == [1]


def test_dispatch_selection_blocks_wrong_rank1_actual_contract() -> None:
    from app.services.htdy_s6_10_one_day_notifications import (
        select_bounded_delivery_events,
    )

    wrong = _event(9)
    wrong.actual_contract = "JM2611"
    selected, capped, blocked = select_bounded_delivery_events(
        [wrong],
        trading_day=date(2026, 7, 29),
        already_notified_event_ids=set(),
        actual_contract="JM2609",
    )

    assert selected == []
    assert capped == []
    assert blocked == [wrong]
