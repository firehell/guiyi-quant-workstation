"""Cross-frequency replay invariants over owned, completed market facts."""

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from app.market_data.domain import BarFrequency, ResolvedContractSegment
from app.market_data.newow.product_query import NewowProductQuery
from app.market_data.newow.product_reader import NewowProductReader
from guiyi_quant.newow.product_adapters import (
    build_product_identity,
    label_calculation_segments,
    replay_step,
    replay_strategy,
    seed_replay_state,
)
from guiyi_quant.newow.product_contracts import DataInterruption
from guiyi_quant.newow.product_identity import InputQualityPolicy, build_segment_id


_STRATEGIES = ("trend", "oscillation", "main_rise")
_FREQUENCIES = ("1w", "1d", "60m")


@pytest.mark.parametrize("strategy", _STRATEGIES)
@pytest.mark.parametrize("frequency", _FREQUENCIES)
def test_completed_prefix_is_unchanged_by_every_future_tail(
    product_cases, strategy, frequency
):
    """Catch formula or adapter code that rewrites an earlier completed frame."""
    case = product_cases.primitive_input(strategy, frequency)
    full = replay_strategy(case.identity, case.bars)

    for end in range(1, len(case.bars) + 1):
        prefix = replay_strategy(case.identity, case.bars[:end])
        assert prefix.frames == full.frames[:end]


@pytest.mark.parametrize("strategy", _STRATEGIES)
@pytest.mark.parametrize("frequency", _FREQUENCIES)
def test_batch_replay_equals_bar_by_bar_prefix_replay(
    product_cases, strategy, frequency
):
    """Catch hidden batch-only state or a special final-Bar code path."""
    case = product_cases.primitive_input(strategy, frequency)
    batch = replay_strategy(case.identity, case.bars)

    incremental_frames = tuple(
        replay_strategy(case.identity, case.bars[:end]).frames[-1]
        for end in range(1, len(case.bars) + 1)
    )

    assert incremental_frames == batch.frames


@pytest.mark.parametrize("strategy", _STRATEGIES)
@pytest.mark.parametrize("frequency", _FREQUENCIES)
def test_public_replay_and_persistable_per_bar_state_share_one_step(
    product_cases, strategy, frequency
):
    """The public wrapper must not have a separate batch-only formula path."""
    case = product_cases.primitive_input(strategy, frequency)
    expected = replay_strategy(case.identity, case.bars).frames
    state = seed_replay_state()
    actual = []
    for item in label_calculation_segments(case.identity, case.bars, ()):
        state, frame, diagnostics = replay_step(case.identity, state, item)
        assert diagnostics == ()
        actual.append(frame)
    assert tuple(actual) == expected
    assert len(state.pairing.source_builds) <= 1


@pytest.mark.parametrize("strategy", _STRATEGIES)
@pytest.mark.parametrize("frequency", _FREQUENCIES)
def test_rebuild_from_the_same_completed_prefix_is_restore_stable(
    product_cases, strategy, frequency
):
    """Catch process-memory state leaking into a replay rebuilt after restart."""
    case = product_cases.primitive_input(strategy, frequency)
    checkpoint = len(case.bars) // 2
    before_restart = replay_strategy(case.identity, case.bars[:checkpoint])

    # Exercise the remaining input between the two calls. A pure replay rebuilt
    # from the checkpoint must not depend on any state retained by that call.
    replay_strategy(case.identity, case.bars)
    after_restart = replay_strategy(case.identity, case.bars[:checkpoint])

    assert after_restart == before_restart


@pytest.mark.parametrize("strategy", _STRATEGIES)
def test_weekly_price_gap_keeps_prefix_incremental_and_rebuild_parity(
    product_cases, strategy
):
    case = product_cases.primitive_input(strategy, "1w")
    split = len(case.bars) // 2
    missing = case.bars[split].bar
    bars = (*case.bars[:split], *case.bars[split + 1:])
    before = bars[split - 1].bar
    after = bars[split].bar
    gap_at = missing.bar_end
    assert before.bar_end < gap_at < after.bar_end
    gap = DataInterruption(
        product=case.identity.product,
        frequency=case.identity.frequency,
        physical_contract=after.physical_contract,
        segment_id=after.segment_id,
        trading_day=missing.trading_day,
        effective_at=gap_at,
        source_identity="market_data_service:weekly_quality:v1:proved-gap",
    )
    batch = replay_strategy(case.identity, bars, data_interruptions=(gap,))
    incremental = tuple(
        replay_strategy(
            case.identity, bars[:end],
            data_interruptions=(gap,) if end > split else (),
        ).frames[-1]
        for end in range(1, len(bars) + 1)
    )
    assert incremental == batch.frames
    assert batch.frames[:split] == replay_strategy(
        case.identity, bars[:split],
    ).frames
    assert gap_at not in {frame.bar.bar.bar_end for frame in batch.frames}
    assert batch.frames[split].bar.calculation_segment_id != before.segment_id
    assert all(
        frame.bar.calculation_segment_id == batch.frames[split].bar.calculation_segment_id
        for frame in batch.frames[split:]
    )
    replay_strategy(case.identity, bars)
    assert replay_strategy(
        case.identity, bars, data_interruptions=(gap,),
    ) == batch


@pytest.mark.parametrize("strategy", _STRATEGIES)
def test_weekly_v2_gap_keeps_prefix_batch_and_restart_parity(product_cases, strategy):
    case = product_cases.primitive_input(strategy, "1w")
    identity = build_product_identity(
        case.identity.product,
        strategy,
        "1w",
        input_quality_policy=InputQualityPolicy.WEEKLY_V2,
    )
    split = len(case.bars) // 2
    missing = case.bars[split].bar
    bars = (*case.bars[:split], *case.bars[split + 1:])
    gap = DataInterruption(
        product=identity.product,
        frequency=identity.frequency,
        physical_contract=missing.physical_contract,
        segment_id=missing.segment_id,
        trading_day=missing.trading_day,
        effective_at=missing.bar_end,
        source_identity="market_data_service:weekly_quality:v2:proved-gap",
    )

    batch = replay_strategy(identity, bars, data_interruptions=(gap,))
    incremental = tuple(
        replay_strategy(
            identity,
            bars[:end],
            data_interruptions=(gap,) if end > split else (),
        ).frames[-1]
        for end in range(1, len(bars) + 1)
    )
    prefix = replay_strategy(identity, bars[:split])

    assert incremental == batch.frames
    assert batch.frames[:split] == prefix.frames
    assert all(
        frame.bar.calculation_segment_id.endswith(
            "|input-quality:newow_weekly_input_quality_v2"
        )
        for frame in batch.frames
    )
    replay_strategy(identity, bars)
    assert replay_strategy(identity, bars, data_interruptions=(gap,)) == batch


@pytest.mark.parametrize("strategy", _STRATEGIES)
@pytest.mark.parametrize("reuse_contract", [False, True], ids=["rollover", "reentry"])
def test_each_authoritative_owner_segment_restarts_all_strategy_state(
    product_cases, strategy, reuse_contract
):
    """Catch recursive or pairing state crossing a contract/owner boundary."""
    case = product_cases.primitive_input(strategy, "1d")
    first = case.bars
    contract = first[0].bar.physical_contract if reuse_contract else "RB2801"
    second_segment = build_segment_id(
        case.identity.product,
        contract,
        datetime(2026, 10, 1, tzinfo=UTC),
    )
    second = tuple(
        replace(
            product_bar,
            bar=replace(
                product_bar.bar,
                physical_contract=contract,
                segment_id=second_segment,
                source_identity=f"owned:task5:{strategy}:{reuse_contract}:{index}",
            ),
        )
        for index, product_bar in enumerate(case.bars)
    )

    combined = replay_strategy(case.identity, first + second)
    fresh_second = replay_strategy(case.identity, second)

    assert combined.frames[len(first) :] == fresh_second.frames
    # Replay now adds an independent calculation-segment identity; the source
    # Bar and owner must still be unchanged by the reset.
    assert tuple(frame.bar.bar for frame in combined.frames[len(first) :]) == tuple(
        item.bar for item in second
    )


def test_owned_sc_weekly_shape_keeps_zero_bar_owner_and_sc2303_prefix(product_cases):
    """Catch W1 owner-set equality or warm-up borrowed from the zero-Bar owner."""
    _, original_query, fake = product_cases.paged_reader(
        prefix_bars=2,
        page_size=2000,
        frequency="1w",
    )
    sc2303_prefix = fake.physical[("RB2605", BarFrequency.W1)]
    fake.segments = (
        ResolvedContractSegment("SC2302", date(2023, 1, 2), date(2023, 1, 5)),
        ResolvedContractSegment("SC2303", date(2023, 1, 6), date(2023, 1, 9)),
    )
    fake.actual = {BarFrequency.W1: (sc2303_prefix[-1],)}
    fake.physical = {("SC2303", BarFrequency.W1): sc2303_prefix}
    fake.expected_physical = dict(fake.physical)
    reader = NewowProductReader(
        fake,
        coverage=fake.coverage,
        active_products=("sc",),
        now=lambda: fake.as_of,
    )
    query = NewowProductQuery(
        product="sc",
        strategy=original_query.strategy,
        frequency="1w",
        since=date(2023, 1, 2),
        through=date(2023, 1, 9),
        performance_since=date(2023, 1, 2),
        performance_through=date(2023, 1, 9),
    )

    result = reader.load(query, fake.as_of)

    assert [owner.contract for owner in result.owners] == ["SC2302", "SC2303"]
    assert [request.contract for request in fake.physical_page_requests] == ["SC2303"]
    assert [bar.bar.physical_contract for bar in result.replay_bars] == [
        "SC2303",
        "SC2303",
    ]
    assert [bar.bar.observation_eligible for bar in result.replay_bars] == [False, True]
    assert [bar.bar.bar_end for bar in result.replay_bars] == [
        bar.bar_end for bar in sc2303_prefix
    ]
    assert fake.coverage_requests == [
        (
            "sc",
            "SC2303",
            BarFrequency.W1,
            sc2303_prefix[-1].trading_day,
            sc2303_prefix[-1].bar_end,
            None,
        )
    ]


def test_owned_60m_same_day_bars_do_not_use_legacy_d1_day_order(product_cases):
    """Catch applying the legacy D1 strictly-increasing-day rule to 60m."""
    reader, query, fake = product_cases.paged_reader(
        prefix_bars=8,
        page_size=2000,
        frequency="60m",
    )

    result = reader.load(query, fake.as_of)
    replay = replay_strategy(
        product_cases.primitive_input("trend", "60m").identity,
        result.replay_bars,
    )

    assert [bar.bar.trading_day for bar in result.replay_bars[:4]] == [
        date(2023, 1, 2),
        date(2023, 1, 2),
        date(2023, 1, 2),
        date(2023, 1, 2),
    ]
    assert [bar.bar.bar_end.hour for bar in result.replay_bars[:4]] == [2, 3, 4, 5]
    assert len(replay.frames) == 8
