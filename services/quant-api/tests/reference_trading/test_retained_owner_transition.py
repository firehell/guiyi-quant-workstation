from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.reference_trading.repository import RepositoryConflict

OLD_DAY = date(2026, 10, 21)
DAY = date(2026, 10, 22)
OLD_END = datetime(2026, 10, 21, 7, tzinfo=UTC)
NEW_START = datetime(2026, 10, 21, 13, tzinfo=UTC)


def case():
    old = SimpleNamespace(
        symbol="pg",
        contract="PG2611",
        start_trading_day=date(2026, 9, 21),
        end_trading_day=OLD_DAY,
    )
    new = SimpleNamespace(
        symbol="pg", contract="PG2612", start_trading_day=DAY, end_trading_day=DAY
    )
    market = SimpleNamespace(
        previous_trading_day=lambda *a: OLD_DAY,
        dominant_segment_for_day=lambda symbol, day: old if day == OLD_DAY else new,
        session_windows=lambda **kw: (
            [SimpleNamespace(start=OLD_END - timedelta(hours=6), end=OLD_END)]
            if kw["trading_day"] == OLD_DAY
            else [SimpleNamespace(start=NEW_START, end=NEW_START + timedelta(hours=2))]
        ),
        expected_contract_replay_endpoints=lambda **kw: [(OLD_END, OLD_DAY)],
    )
    identity = SimpleNamespace(
        product="pg", frequency="60m", strategy_code="newow_trend"
    )
    cp = SimpleNamespace(
        computed_through=OLD_END,
        physical_contract="PG2611",
        owner_segment_id="old-owner",
        calculation_segment_id="old-calc",
    )
    authority = SimpleNamespace(
        owner_segments=lambda identity, contract, *args: (
            ("old-owner", "old-calc")
            if contract == "PG2611"
            else ("new-owner", "new-calc")
        )
    )
    return market, authority, identity, cp, new


def prove(values):
    from app.reference_trading.retained_owner_transition import (
        prove_rank1_owner_transition,
    )

    market, authority, identity, cp, _ = values
    return prove_rank1_owner_transition(
        market,
        authority,
        identity,
        cp,
        previous_day=OLD_DAY,
        trading_day=DAY,
        knowledge_at=NEW_START + timedelta(hours=4),
    )


def test_exact_two_rank1_segments_prove_explicit_boundary():
    transition = prove(case())
    assert transition.contract == "PG2612"
    assert transition.owner_segment_id == "new-owner"
    assert transition.proof["version"] == "retained_rank1_owner_transition_v1"
    assert transition.proof["old_terminal"] == OLD_END.isoformat()


@pytest.mark.parametrize(
    "failure",
    ["oldtail", "wrong_old_contract", "nonadjacent", "not_new_owner", "old_owner"],
)
def test_unproven_transition_cannot_replace_baseline_contract(failure):
    values = case()
    market, authority, _, cp, new = values
    if failure == "oldtail":
        cp.computed_through -= timedelta(hours=1)
    if failure == "wrong_old_contract":
        cp.physical_contract = "PG2610"
    if failure == "nonadjacent":
        market.previous_trading_day = lambda *a: date(2026, 10, 20)
    if failure == "not_new_owner":
        new.start_trading_day = OLD_DAY
    if failure == "old_owner":
        authority.owner_segments = lambda *a: ("wrong", "wrong")
    with pytest.raises(RepositoryConflict):
        prove(values)
