from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.market_data.newow.jm_pilot_research import (
    JMPilotInput,
    adapt_jm_execution_facts,
    run_jm_pilot_research,
)
from guiyi_quant.newow.research_backtest import (
    NewowResearchBar,
    NewowStrategyReplaySegment,
)


def _bar(index: int) -> NewowResearchBar:
    day = date(2026, 1, 5) + timedelta(days=index)
    end = datetime(2026, 1, 5, tzinfo=UTC) + timedelta(days=index)
    return NewowResearchBar(
        product="jm", physical_contract="JM2605", segment_id="jm:JM2605:fixture",
        trading_day=day, bar_end=end, open=Decimal("100"),
        high=Decimal("101"), low=Decimal("99"), close=Decimal("100"),
        volume=100, open_interest=1000, source_identity=f"canonical-jm-{index}",
        observation_eligible=True, completed=True, frequency="5m",
    )


def test_jm_research_fails_closed_without_sourced_execution_facts() -> None:
    bars = tuple(_bar(index) for index in range(5))
    source = JMPilotInput(
        bars=bars,
        replay_segments=(NewowStrategyReplaySegment(bars),),
        requested_since=bars[0].trading_day,
        actual_through=bars[-1].trading_day,
        input_sha256="a" * 64,
    )

    with pytest.raises(ValueError, match="EXECUTION_FACTS_MISSING"):
        run_jm_pilot_research(source, cost_snapshots=(), execution_constraints=())


def test_execution_fact_adapter_preserves_offset_fee_type_and_day_limits() -> None:
    bars = tuple(_bar(index) for index in range(2))
    source = JMPilotInput(
        bars, (NewowStrategyReplaySegment(bars),), bars[0].trading_day,
        bars[-1].trading_day, "a" * 64,
    )
    facts = {
        "schema_version": 1, "source": "rqdata", "plan_hash": "b" * 64,
        "captured_at": "2026-10-11T01:00:00+00:00",
        "contracts": {"JM2605": {
            "start": "2026-01-05", "end": "2026-01-06",
            "instrument": {"contract_multiplier": "60", "tick_size": "0.5"},
            "parameters": [
                {"date": "2026-01-05", "commission_type": "BY_MONEY",
                 "open_commission": "0.0001", "close_commission": "0.0002",
                 "close_commission_today": "0.0003", "long_margin_ratio": "0.1",
                 "trade_unit": "60", "price_unit": "0.5"},
                {"date": "2026-01-06", "commission_type": "BY_VOLUME",
                 "open_commission": "1", "close_commission": "2",
                 "close_commission_today": "3", "long_margin_ratio": "0.1",
                 "trade_unit": "60", "price_unit": "0.5"},
            ],
            "daily": [
                {"date": day.isoformat(), "limit_up": "200", "limit_down": "1",
                 "settlement": "100", "prev_settlement": "100"}
                for day in (bars[0].trading_day, bars[1].trading_day)
            ],
        }},
    }

    snapshots, constraints, identity = adapt_jm_execution_facts(source, facts)

    assert len(snapshots) == 2
    assert snapshots[0].offset_fees.open_rate == Decimal("0.0001")
    assert snapshots[0].offset_fees.close_yesterday_rate == Decimal("0.0002")
    assert snapshots[0].offset_fees.close_today_rate == Decimal("0.0003")
    assert snapshots[1].offset_fees.open_per_contract == Decimal("1")
    assert snapshots[1].offset_fees.close_yesterday_per_contract == Decimal("2")
    assert snapshots[1].offset_fees.close_today_per_contract == Decimal("3")
    assert len(constraints) == 2
    assert len(identity) == 64

    facts["tick_amendment"] = {
        "source": "rqdata.Instrument.tick_size()",
        "captured_at": "2026-10-11T02:00:00+00:00",
        "original_sha256": "c" * 64,
        "ticks": {"JM2605": "0.5"},
    }
    amended, _, _ = adapt_jm_execution_facts(source, facts)
    assert amended[0].captured_at == datetime(2026, 10, 11, 2, tzinfo=UTC)

    facts["contracts"]["JM2605"]["parameters"][0]["close_commission_today"] = None
    with pytest.raises(ValueError, match="EXECUTION_FACTS_MISSING"):
        adapt_jm_execution_facts(source, facts)
