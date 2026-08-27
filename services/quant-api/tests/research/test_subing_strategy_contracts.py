from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.market_data.domain import CanonicalBar
from app.market_data.subing_lifecycle import ConfirmationSource
from app.market_data.subing_research import SubingDirection
from app.market_data.subing_strategy.contracts import (
    SubingStrategyAction,
    SubingStrategyActionKind,
    SubingStrategyContractError,
    SubingStrategyEpisode,
    SubingStrategyEpisodeState,
    SubingStrategyFillBasis,
    subing_strategy_action_id,
    subing_strategy_episode_id,
)
from research.subing_strategy_fixtures import action_fixture, aware_dt


STRATEGY_ID = "subing_strategy_v1"
FORMULA_VERSION = "subing_strategy_15m_v1"
SEGMENT_START = date(2026, 1, 5)
BASE_TIME = datetime(2026, 1, 5, 2, 0, tzinfo=UTC)


def _identity_fields(
    *,
    contract: str = "JM2605",
    kind: SubingStrategyActionKind = SubingStrategyActionKind.OPEN_LONG,
    decision_at: datetime = BASE_TIME,
    effective_bar_end: datetime = BASE_TIME + timedelta(minutes=15),
    fill_basis: SubingStrategyFillBasis = SubingStrategyFillBasis.NEXT_BAR_OPEN,
) -> dict[str, object]:
    return {
        "strategy_id": STRATEGY_ID,
        "formula_version": FORMULA_VERSION,
        "symbol": "JM",
        "contract": contract,
        "segment_start_trading_day": SEGMENT_START.isoformat(),
        "opportunity_id": "subing-opportunity:test",
        "kind": kind.value,
        "decision_at": decision_at.isoformat(),
        "effective_bar_end": effective_bar_end.isoformat(),
        "fill_basis": fill_basis.value,
    }


def _action(
    *,
    reference_price: Decimal = Decimal("100"),
    contract: str = "JM2605",
    kind: SubingStrategyActionKind = SubingStrategyActionKind.OPEN_LONG,
    decision_at: datetime = BASE_TIME,
    effective_bar_end: datetime = BASE_TIME + timedelta(minutes=15),
    episode_id: str | None = None,
) -> SubingStrategyAction:
    identity = _identity_fields(
        contract=contract,
        kind=kind,
        decision_at=decision_at,
        effective_bar_end=effective_bar_end,
    )
    action_id = subing_strategy_action_id(identity)
    resolved_episode_id = episode_id or subing_strategy_episode_id(identity)
    is_open = kind in {
        SubingStrategyActionKind.OPEN_LONG,
        SubingStrategyActionKind.OPEN_SHORT,
    }
    return SubingStrategyAction(
        action_id=action_id,
        episode_id=resolved_episode_id,
        strategy_id=STRATEGY_ID,
        formula_version=FORMULA_VERSION,
        kind=kind,
        symbol="JM",
        contract=contract,
        trading_day=SEGMENT_START,
        segment_start_trading_day=SEGMENT_START,
        opportunity_id="subing-opportunity:test",
        decision_at=decision_at,
        effective_open_at=effective_bar_end - timedelta(minutes=15),
        effective_bar_end=effective_bar_end,
        reference_price=reference_price,
        fill_basis=SubingStrategyFillBasis.NEXT_BAR_OPEN,
        confirmation_source=(ConfirmationSource.FORMAL_V1 if is_open else None),
        reason_codes=(() if is_open else ("EMA21_BREACH_LONG",)),
        direction_context_source_day=(SEGMENT_START if is_open else None),
        direction_context_target_day=(SEGMENT_START if is_open else None),
        bound_reference_pivot=None,
    )


def _bar(minutes: int, close: str) -> CanonicalBar:
    price = Decimal(close)
    return CanonicalBar(
        bar_end=BASE_TIME + timedelta(minutes=minutes),
        trading_day=SEGMENT_START,
        open=price,
        high=price + Decimal("1"),
        low=price - Decimal("1"),
        close=price,
        volume=Decimal("1"),
        turnover=None,
        open_interest=None,
    )


def test_action_identity_is_stable_when_reference_price_changes() -> None:
    first = _action(reference_price=Decimal("100"))
    second = _action(reference_price=Decimal("101"))

    assert subing_strategy_action_id(first.identity_fields()) == first.action_id
    assert subing_strategy_action_id(second.identity_fields()) == second.action_id
    assert first.action_id == second.action_id


def test_action_identity_changes_for_effective_bar() -> None:
    first = _action(effective_bar_end=BASE_TIME + timedelta(minutes=15))
    second = _action(effective_bar_end=BASE_TIME + timedelta(minutes=30))

    assert first.action_id != second.action_id


def test_next_bar_open_requires_effective_open_at() -> None:
    with pytest.raises(SubingStrategyContractError):
        action_fixture(
            fill_basis=SubingStrategyFillBasis.NEXT_BAR_OPEN,
            effective_open_at=None,
        )


def test_terminal_close_rejects_effective_open_at() -> None:
    with pytest.raises(SubingStrategyContractError):
        action_fixture(
            fill_basis=SubingStrategyFillBasis.SEGMENT_TERMINAL_CLOSE,
            effective_open_at=aware_dt(10, 15),
        )


def test_effective_open_at_does_not_change_action_identity() -> None:
    first = action_fixture(effective_open_at=aware_dt(10, 15))
    second = action_fixture(effective_open_at=aware_dt(10, 16))

    assert first.action_id == second.action_id


def test_episode_rejects_cross_contract_exit() -> None:
    entry = _action()
    exit_action = _action(
        contract="JM2609",
        kind=SubingStrategyActionKind.CLOSE_LONG,
        decision_at=BASE_TIME + timedelta(minutes=30),
        effective_bar_end=BASE_TIME + timedelta(minutes=45),
        episode_id=entry.episode_id,
    )

    with pytest.raises(SubingStrategyContractError):
        SubingStrategyEpisode.from_actions(
            entry_action=entry,
            exit_action=exit_action,
            completed_15m_bars=(_bar(15, "100"), _bar(30, "102")),
            latest_reference_price=None,
        )


def test_closed_episode_derives_holding_count_and_directional_change() -> None:
    entry = _action(reference_price=Decimal("100"))
    exit_action = _action(
        reference_price=Decimal("105"),
        kind=SubingStrategyActionKind.CLOSE_LONG,
        decision_at=BASE_TIME + timedelta(minutes=30),
        effective_bar_end=BASE_TIME + timedelta(minutes=45),
        episode_id=entry.episode_id,
    )

    episode = SubingStrategyEpisode.from_actions(
        entry_action=entry,
        exit_action=exit_action,
        completed_15m_bars=(
            _bar(15, "100"),
            _bar(30, "104"),
            _bar(45, "105"),
        ),
        latest_reference_price=None,
    )

    assert episode.direction is SubingDirection.LONG
    assert episode.state is SubingStrategyEpisodeState.CLOSED
    assert episode.holding_bar_count == 2
    assert episode.reference_change_percent == Decimal("5")
    assert episode.current_reference_change_percent is None
    assert episode.latest_reference_price is None
    assert episode.exit_reason_codes == ("EMA21_BREACH_LONG",)


def test_open_episode_uses_latest_completed_close_as_current_reference() -> None:
    entry = _action(reference_price=Decimal("100"))

    episode = SubingStrategyEpisode.from_actions(
        entry_action=entry,
        exit_action=None,
        completed_15m_bars=(_bar(15, "100"), _bar(30, "98")),
        latest_reference_price=Decimal("98"),
    )

    assert episode.state is SubingStrategyEpisodeState.OPEN
    assert episode.holding_bar_count == 2
    assert episode.reference_change_percent is None
    assert episode.current_reference_change_percent == Decimal("-2")
    assert episode.latest_reference_price == Decimal("98")
    assert episode.exit_reason_codes == ()
