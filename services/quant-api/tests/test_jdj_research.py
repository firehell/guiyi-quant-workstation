from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from decimal import Decimal
from typing import get_args
from datetime import UTC, date, datetime, timedelta

import pytest

from app.market_data.jdj_context import JdjContextError
from app.market_data.jdj_events import (
    JdjDirection,
    JdjKeyLevelBreakoutTriggerEvent,
    JdjTrendFollowTriggerEvent,
    JdjTrendReentryTriggerEvent,
    JdjTriggerEvent,
    JdjSetupKind,
    _canonical_trend_follow_event_id,
)
from app.market_data.jdj_research import (
    JdjResearchRequest,
    JdjResearchResult,
    JdjSourceUnavailableError,
)
from app.market_data.price_outcome import PriceHorizonEvaluation


_TREND_FOLLOW = "jdj_trend_follow_1m_candidate_v1"


def _trend_follow_event() -> JdjTrendFollowTriggerEvent:
    segment_start = date(2026, 8, 18)
    reaction_at = datetime(2026, 8, 20, 1, 1, tzinfo=UTC)
    observed_at = reaction_at + timedelta(minutes=1)
    trigger_level = Decimal("105")
    return JdjTrendFollowTriggerEvent(
        event_id=_canonical_trend_follow_event_id(
            candidate_id=_TREND_FOLLOW,
            symbol="jm",
            contract="JM2701",
            segment_start_trading_day=segment_start,
            direction=JdjDirection.LONG,
            reaction_at=reaction_at,
            observed_at=observed_at,
            trigger_level=trigger_level,
        ),
        source_kind="jdj_1m",
        setup_kind=JdjSetupKind.TREND_FOLLOW,
        candidate_id=_TREND_FOLLOW,
        source_event_kind="jdj_trend_follow_triggered",
        direction=JdjDirection.LONG,
        symbol="jm",
        contract="JM2701",
        segment_start_trading_day=segment_start,
        trading_day=date(2026, 8, 20),
        observed_at=observed_at,
        segment_bar_index=2,
        trend_snapshot_observed_at=reaction_at - timedelta(minutes=1),
        reaction_at=reaction_at,
        ema20_at_reaction=Decimal("100"),
        trigger_level=trigger_level,
        observation_close=Decimal("102"),
    )


def test_request_freezes_exact_identity_and_normalizes_symbol() -> None:
    request = JdjResearchRequest(
        since=date(2023, 1, 1),
        through=date(2026, 8, 20),
        symbol=" JM ",
        candidate_id=_TREND_FOLLOW,
    )

    assert tuple(field.name for field in fields(request)) == (
        "since",
        "through",
        "symbol",
        "candidate_id",
    )
    assert request.symbol == "jm"
    with pytest.raises(FrozenInstanceError):
        request.symbol = "ag"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("since", "through", "symbol", "candidate_id"),
    (
        (date(2026, 8, 21), date(2026, 8, 20), "jm", _TREND_FOLLOW),
        ("2023-01-01", date(2026, 8, 20), "jm", _TREND_FOLLOW),
        (date(2023, 1, 1), date(2026, 8, 20), "", _TREND_FOLLOW),
        (date(2023, 1, 1), date(2026, 8, 20), "jm2609", _TREND_FOLLOW),
        (date(2023, 1, 1), date(2026, 8, 20), "jm", "unknown"),
    ),
)
def test_request_rejects_invalid_identity(
    since: object,
    through: object,
    symbol: object,
    candidate_id: object,
) -> None:
    with pytest.raises(JdjContextError, match="^JDJ_CONTEXT_INVALID$"):
        JdjResearchRequest(
            since=since,  # type: ignore[arg-type]
            through=through,  # type: ignore[arg-type]
            symbol=symbol,  # type: ignore[arg-type]
            candidate_id=candidate_id,  # type: ignore[arg-type]
        )


def test_trigger_event_alias_is_the_exact_three_event_union() -> None:
    assert get_args(JdjTriggerEvent) == (
        JdjTrendFollowTriggerEvent,
        JdjTrendReentryTriggerEvent,
        JdjKeyLevelBreakoutTriggerEvent,
    )


def test_result_freezes_exact_empty_horizon_summary() -> None:
    zero = PriceHorizonEvaluation(0, None, None, None)
    horizon_summary = {3: zero, 5: zero, 8: zero, 20: zero}

    result = JdjResearchResult(
        candidate_id=_TREND_FOLLOW,
        source_event_kind="jdj_trend_follow_triggered",
        products=("jm",),
        segment_count=0,
        evaluable_bar_count=0,
        trigger_count_long=0,
        trigger_count_short=0,
        horizon_summary=horizon_summary,
        events=(),
    )
    horizon_summary[3] = PriceHorizonEvaluation(
        1,
        Decimal("1"),
        Decimal("2"),
        Decimal("-1"),
    )

    assert tuple(field.name for field in fields(result)) == (
        "candidate_id",
        "source_event_kind",
        "products",
        "segment_count",
        "evaluable_bar_count",
        "trigger_count_long",
        "trigger_count_short",
        "horizon_summary",
        "events",
    )
    assert tuple(result.horizon_summary) == (3, 5, 8, 20)
    assert result.horizon_summary[3] == zero
    with pytest.raises(TypeError):
        result.horizon_summary[3] = zero  # type: ignore[index]


def test_source_unavailable_error_has_stable_redacted_identity() -> None:
    error = JdjSourceUnavailableError()

    assert error.code == "JDJ_SOURCE_UNAVAILABLE"
    assert str(error) == "JDJ_SOURCE_UNAVAILABLE"


def test_result_rejects_trigger_count_drift_from_immutable_events() -> None:
    zero = PriceHorizonEvaluation(0, None, None, None)

    with pytest.raises(JdjContextError, match="^JDJ_CONTEXT_INVALID$"):
        JdjResearchResult(
            candidate_id=_TREND_FOLLOW,
            source_event_kind="jdj_trend_follow_triggered",
            products=("jm",),
            segment_count=1,
            evaluable_bar_count=3,
            trigger_count_long=0,
            trigger_count_short=0,
            horizon_summary={3: zero, 5: zero, 8: zero, 20: zero},
            events=(_trend_follow_event(),),
        )


def test_result_rejects_malformed_horizon_evaluation() -> None:
    zero = PriceHorizonEvaluation(0, None, None, None)
    malformed = PriceHorizonEvaluation(-1, None, None, None)

    with pytest.raises(JdjContextError, match="^JDJ_CONTEXT_INVALID$"):
        JdjResearchResult(
            candidate_id=_TREND_FOLLOW,
            source_event_kind="jdj_trend_follow_triggered",
            products=("jm",),
            segment_count=0,
            evaluable_bar_count=0,
            trigger_count_long=0,
            trigger_count_short=0,
            horizon_summary={3: malformed, 5: zero, 8: zero, 20: zero},
            events=(),
        )
