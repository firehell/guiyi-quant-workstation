"""Intraday product identity/capability contracts, independently from daily fixtures."""

from datetime import UTC, datetime
import pytest
from pydantic import TypeAdapter
from guiyi_quant.newow.product_adapters import build_product_identity
from guiyi_quant.newow.product_contracts import ProductFrequency
from app.market_data.newow.product_release import (
    require_open_frequency,
    deferred_frequency_reason,
)
from app.market_data.newow.readiness import ReadinessRequest
from app.schemas.market_newow_product import ProductFrequencyValue


@pytest.mark.parametrize("frequency", ["1m", "15m", "30m", "60m"])
@pytest.mark.parametrize("strategy", ["trend", "oscillation"])
def test_intraday_identity_and_wire_frequency(frequency, strategy):
    identity = build_product_identity("rb", strategy, frequency)
    assert identity.profile_id == f"newow_product_{strategy}_{frequency}_v1"
    assert TypeAdapter(ProductFrequencyValue).validate_python(frequency) == frequency
    assert identity != build_product_identity("rb", strategy, "1d")


@pytest.mark.parametrize("frequency", ["1m", "15m", "30m", "60m"])
def test_intraday_remains_formally_closed_until_pilot_accepted(frequency):
    with pytest.raises(ValueError, match="NEWOW_FREQUENCY_NOT_OPEN"):
        require_open_frequency(ProductFrequency(frequency))
    assert deferred_frequency_reason(ProductFrequency(frequency)) is not None


def test_readiness_default_does_not_expand_when_frequency_enum_grows():
    request = ReadinessRequest(("rb",), datetime(2026, 9, 24, 8, tzinfo=UTC))
    assert tuple(x.value for x in request.frequencies) == ("1w", "1d", "60m")


@pytest.mark.parametrize(
    "frequency,limit,expected_since",
    [("1m", 300, 3), ("15m", 24, 3), ("30m", 13, 2), ("60m", 11, 2)],
)
def test_intraday_chart_window_counts_authoritative_sessions(
    frequency, limit, expected_since
):
    from datetime import date, timedelta
    from types import SimpleNamespace
    from app.market_data.aggregation import SessionWindow
    from app.market_data.newow.product_reader import NewowProductReader

    days = tuple(date(2026, 9, d) for d in (1, 2, 3))
    cutoff = datetime(2026, 9, 4, 8, tzinfo=UTC)

    def sessions(**kwargs):
        start = datetime.combine(kwargs["trading_day"], datetime.min.time(), UTC)
        return (SessionWindow(start, start + timedelta(hours=6)),)

    market = SimpleNamespace(
        completed_trading_days=lambda **kwargs: days, session_windows=sessions
    )
    coverage = SimpleNamespace(
        product_start=lambda product: days[0],
        latest_complete_day=lambda products: days[-1],
    )
    reader = NewowProductReader(
        market, coverage=coverage, active_products=("rb",), now=lambda: cutoff
    )
    window = reader.resolve_chart_window(
        "rb", ProductFrequency(frequency), limit, cutoff
    )
    assert window.since == date(2026, 9, expected_since)
    assert window.through == days[-1]


def test_minute_warmup_scope_never_expands_to_other_periods():
    from app.market_data.historical_data_manager import _contract_warmup_scope
    from app.market_data.domain import BarFrequency

    selected, dependencies, frequencies, planned = _contract_warmup_scope("1m")
    assert (selected, dependencies, frequencies, planned) == (
        "1m",
        (),
        ("1m",),
        (BarFrequency.M1,),
    )


@pytest.mark.parametrize("products", [(), ("rb", "rb"), ("notreal",)])
def test_four_period_audit_rejects_invalid_scope_before_database_access(products):
    from datetime import date
    from scripts.newow_four_period_readonly_audit import audit

    with pytest.raises(ValueError, match="AUDIT_PRODUCT_SCOPE_INVALID"):
        audit(
            since=date(2023, 1, 1),
            day=date(2026, 9, 24),
            timeout_seconds=30,
            products=products,
        )


@pytest.mark.parametrize("frequency", ["1m", "15m", "30m", "60m"])
@pytest.mark.parametrize("strategy", ["trend", "oscillation"])
def test_minute_replay_is_prefix_and_incremental_invariant(
    product_cases, frequency, strategy
):
    from dataclasses import replace
    from datetime import timedelta
    from guiyi_quant.newow.product_contracts import ProductBar
    from guiyi_quant.newow.product_adapters import (
        replay_strategy,
        replay_step,
        seed_replay_state,
    )

    daily = product_cases.primitive_input(strategy, "1d")
    identity = build_product_identity("rb", strategy, frequency)
    width = int(frequency.removesuffix("m"))
    first = datetime(2026, 1, 5, 1, tzinfo=UTC)
    bars = tuple(
        ProductBar(
            replace(
                b.bar,
                bar_end=first + timedelta(minutes=(i + 1) * width),
                trading_day=(first + timedelta(minutes=(i + 1) * width)).date(),
            ),
            frequency,
        )
        for i, b in enumerate(daily.bars)
    )
    full = replay_strategy(identity, bars)
    assert full.frames and full.actions
    for n in (1, 9, 10, 11, len(bars) // 2, len(bars)):
        assert replay_strategy(identity, bars[:n]).frames == full.frames[:n]
    state = seed_replay_state()
    frames = []
    for bar in bars:
        state, frame, _ = replay_step(identity, state, bar)
        if frame is not None:
            frames.append(frame)
    assert tuple(frames) == full.frames


@pytest.mark.parametrize("frequency", ["1m", "15m", "30m", "60m"])
def test_reference_coverage_accepts_multiple_completed_bars_in_one_trading_day(
    product_cases, frequency
):
    from dataclasses import replace
    from datetime import timedelta
    from types import SimpleNamespace
    from guiyi_quant.newow.product_contracts import ProductBar
    from guiyi_quant.newow.product_adapters import replay_strategy
    from app.market_data.newow.product_service import _reference_coverage_intervals

    daily = product_cases.primitive_input("trend", "1d")
    day = daily.bars[0].bar.trading_day
    bars = tuple(
        ProductBar(
            replace(
                b.bar,
                trading_day=day,
                bar_end=datetime(2026, 1, 5, 1, tzinfo=UTC) + timedelta(minutes=i + 1),
            ),
            frequency,
        )
        for i, b in enumerate(daily.bars)
    )
    replay = replay_strategy(build_product_identity("rb", "trend", frequency), bars)
    read = SimpleNamespace(
        frequency=ProductFrequency(frequency),
        data_interruptions=(),
        owners=(),
        boundaries=(),
    )
    intervals = _reference_coverage_intervals(read, replay, day, day)
    assert intervals
    assert all(
        item.physical_contract == bars[0].bar.physical_contract for item in intervals
    )


def test_saved_availability_excludes_physical_prefix_of_future_owner():
    from types import SimpleNamespace
    from app.market_data.domain import ResolvedContractSegment
    from app.market_data.newow.product_reader import NewowProductReader
    from guiyi_quant.newow.product_identity import build_segment_id
    from app.market_data.aggregation import SessionWindow
    from datetime import time, date

    owners = (ResolvedContractSegment("RB2701", date(2026, 9, 1), date(2026, 9, 3)),
              ResolvedContractSegment("RB2701", date(2026, 9, 8), date(2026, 9, 10)))
    def sessions(*, symbol, trading_day):
        return (SessionWindow(datetime.combine(trading_day, time(1), UTC),
                              datetime.combine(trading_day, time(7), UTC)),)
    reader = object.__new__(NewowProductReader)
    reader._market_data = SimpleNamespace(session_windows=sessions)
    points = [{"trading_day": "2026-09-02", "value": {
        "physical_contract": owner.contract,
        "segment_id": build_segment_id("rb", owner.contract, sessions(symbol="rb", trading_day=owner.start_trading_day)[0].start),
    }} for owner in owners]
    assert reader.reference_owned_points("rb", points, owners) == points[:1]


def test_snapshot_requires_shared_verified_market_source_or_bar():
    from app.market_data.newow.snapshot_cache import SnapshotCache
    market = {'canonical-source|1m|cutoff': 'a' * 64}
    assert SnapshotCache._proofs_compatible(market, dict(market))
    assert not SnapshotCache._proofs_compatible(market, {'canonical-source|1m|cutoff': 'b' * 64})
    assert not SnapshotCache._proofs_compatible(market, {'canonical-source|15m|cutoff': 'a' * 64})
    assert not SnapshotCache._proofs_compatible({'owner|x': 'a'}, {'owner|x': 'a'})
