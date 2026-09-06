from dataclasses import replace

from guiyi_quant.newow.product_adapters import build_product_identity, replay_strategy
from guiyi_quant.newow.product_contracts import MainState, ProductFrequency

from app.market_data.newow.source_facts import (
    build_composite_inputs,
    target_absorb_gap_sources,
)


def _replays(product_cases, strategy: str):
    result = {}
    for frequency in ProductFrequency:
        case = product_cases.primitive_input(strategy, frequency)
        identity = build_product_identity("rb", strategy, frequency)
        result[frequency] = replay_strategy(identity, case.bars)
    return result


def test_server_constructs_each_composite_role_from_its_own_replay(product_cases):
    trend = _replays(product_cases, "trend")
    oscillation = _replays(product_cases, "oscillation")
    as_of = min(replay.frames[-1].bar.bar.bar_end for replay in trend.values())

    result = build_composite_inputs(trend, oscillation, as_of)

    assert result.evidence is not None
    assert [source.role for source in result.sources] == [
        "trend_weekly",
        "trend_daily",
        "trend_hourly",
        "oscillation_weekly",
        "oscillation_daily",
        "oscillation_hourly",
    ]
    assert all(source.source_category == "strategy_replay" for source in result.sources)
    assert all(source.dependency_sha256 for source in result.sources)
    assert result.evidence.oscillation_daily is not None


def test_unavailable_frame_does_not_become_a_verified_current_fact(product_cases):
    trend = _replays(product_cases, "trend")
    oscillation = _replays(product_cases, "oscillation")
    as_of = min(replay.frames[-1].bar.bar.bar_end for replay in trend.values())
    daily = oscillation[ProductFrequency.DAILY]
    selected_index = max(
        index
        for index, frame in enumerate(daily.frames)
        if frame.bar.bar.bar_end <= as_of
    )
    unavailable = replace(
        daily.frames[selected_index], main_state=MainState.UNAVAILABLE
    )
    frames = list(daily.frames)
    frames[selected_index] = unavailable
    oscillation[ProductFrequency.DAILY] = replace(
        daily,
        frames=tuple(frames),
        actions=tuple(action for frame in frames for action in frame.actions),
        hints=tuple(hint for frame in frames for hint in frame.hints),
    )

    result = build_composite_inputs(trend, oscillation, as_of)

    assert result.evidence is None
    source = next(item for item in result.sources if item.role == "oscillation_daily")
    assert source.status == "unavailable"


def test_unproven_target_roles_remain_explicit_evidence_gaps(product_cases):
    as_of = product_cases.primitive_input("trend", "1d").bars[-1].bar.bar_end
    sources = target_absorb_gap_sources(as_of)
    assert {source.role for source in sources} >= {
        "previous_close",
        "cross_weekly_buy",
        "target_daily",
    }
    assert all(source.status == "evidence_required" for source in sources)
