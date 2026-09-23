from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from app.reference_trading.forward_authority import ForwardMarketAuthority
from app.reference_trading.forward_inputs import ForwardInputUnavailable
from guiyi_quant.newow.product_identity import build_segment_id
from guiyi_quant.reference_trading import RecordingMode, StreamIdentity


def _identity(code="newow_trend", frequency="60m"):
    return StreamIdentity(code, ("f1",), "p1", "r1", "a1", "rb", frequency,
                          "actual_dominant", RecordingMode.FORWARD_OBSERVATION, "o1")


class Market:
    contract = "RB2610"

    def dominant_segment_for_day(self, symbol, trading_day):
        assert symbol == "rb" and trading_day == date(2026, 9, 23)
        return SimpleNamespace(symbol="rb", contract=self.contract,
                               start_trading_day=date(2026, 9, 21))

    def session_windows(self, *, symbol, trading_day):
        assert symbol == "rb" and trading_day == date(2026, 9, 21)
        return (SimpleNamespace(start=datetime(2026, 9, 20, 13, tzinfo=UTC)),)

    def expected_contract_replay_endpoints(self, **kwargs):
        assert kwargs["since"] == date(2026, 9, 21)
        return ((kwargs["cutoff"], kwargs["trading_day"]),)


def test_strategy_specific_owner_identity_uses_true_rank1_start_and_session():
    market = Market()
    authority = ForwardMarketAuthority(market)
    day = date(2026, 9, 23)
    end = datetime(2026, 9, 23, 1, tzinfo=UTC)
    owner, calc = authority.owner_segments(_identity(), "RB2610", day, end)
    assert owner == build_segment_id("rb", "RB2610", datetime(2026, 9, 20, 13, tzinfo=UTC))
    assert calc == owner
    subing_owner, subing_calc = authority.owner_segments(
        _identity("subing-reference", "15m"), "RB2610", day, end,
    )
    assert subing_owner == subing_calc and subing_owner != owner
    assert authority.expected_endpoints(_identity(), "RB2610", day, None, end) == (end,)


def test_owner_conflict_fails_closed():
    authority = ForwardMarketAuthority(Market())
    with pytest.raises(ForwardInputUnavailable, match="OWNER_IDENTITY_CONFLICT"):
        authority.owner_segments(
            _identity(), "RB2701", date(2026, 9, 23),
            datetime(2026, 9, 23, 1, tzinfo=UTC),
        )
