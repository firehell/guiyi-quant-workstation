from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
import json

import pytest

from guiyi_quant.newow.product_adapters import replay_step, seed_replay_state
from guiyi_quant.reference_trading import ReferenceState, StreamIdentity
from guiyi_quant.reference_trading.adapters import AdapterCheckpoint
from guiyi_quant.reference_trading.strategy_checkpoint import (
    adapter_checkpoint_from_json,
    adapter_checkpoint_to_json,
)
from guiyi_quant.subing_reference import (
    ReferenceBar,
    ReferenceSegment,
    replay_subing_step,
    seed_subing_replay_state,
)


@pytest.fixture
def product_cases():
    from newow.product_fixtures import ProductCases

    return ProductCases()


def _stream(strategy: str) -> StreamIdentity:
    return StreamIdentity(
        strategy_code=strategy, formula_versions=("v1",), profile_id="default",
        reference_model_version="reference-v1", futures_adaptation_version="futures-v1",
        product="RB", frequency="1d", series_kind="actual_dominant",
        recording_mode="historical_replay", observation_policy_version=None,
    )


def test_full_newow_strategy_checkpoint_round_trips_and_rejects_wrong_stream(product_cases) -> None:
    case = product_cases.primitive_input("trend", "1d")
    identity = case.identity
    state = seed_replay_state()
    for bar in case.bars:
        state, _frame, _diagnostics = replay_step(identity, state, bar)
    at = case.bars[-1].bar.bar_end
    stream = _stream("newow-trend")
    checkpoint = AdapterCheckpoint(
        state, at, "abc", "RB2601", "owner", "owner", stream, ReferenceState.flat(stream),
    )

    encoded = adapter_checkpoint_to_json(checkpoint, strategy_schema="newow_product_replay_v1")
    restored = adapter_checkpoint_from_json(
        encoded, expected_stream=stream, expected_strategy_schema="newow_product_replay_v1",
    )

    assert restored == checkpoint
    with pytest.raises(ValueError, match="stream"):
        adapter_checkpoint_from_json(
            encoded, expected_stream=_stream("other"),
            expected_strategy_schema="newow_product_replay_v1",
        )


def test_full_subing_strategy_checkpoint_round_trips_after_indicator_warmup() -> None:
    at = datetime(2026, 1, 1, 15, tzinfo=UTC)
    prices = [100] * 50 + [120, 80, 120, 80]
    bars = tuple(
        ReferenceBar(at + timedelta(hours=index), (at + timedelta(hours=index)).date(), Decimal(price))
        for index, price in enumerate(prices)
    )
    segment = ReferenceSegment("RB2601", "owner", bars, bars[0].trading_day, bars[-1].trading_day)
    state = seed_subing_replay_state()
    for bar in bars:
        state, *_ = replay_subing_step(
            "RB", segment, "1d", False, state, bar,
            since=bars[0].trading_day, through=bars[-1].trading_day,
        )
    assert state.reference_state is not None
    stream = state.reference_state.stream
    checkpoint = AdapterCheckpoint(
        state, bars[-1].bar_end, "abc", "RB2601", "owner", "owner", stream, state.reference_state,
    )

    restored = adapter_checkpoint_from_json(
        adapter_checkpoint_to_json(checkpoint, strategy_schema="subing_replay_v1"),
        expected_stream=stream,
        expected_strategy_schema="subing_replay_v1",
    )

    assert restored == checkpoint


@pytest.mark.parametrize("cut_fraction", (1, 2, 3))
def test_newow_checkpoint_restore_continues_with_exact_tail_parity(
    product_cases, cut_fraction,
) -> None:
    case = product_cases.primitive_input("main_rise", "1d")
    cut = len(case.bars) * cut_fraction // 4

    uninterrupted = seed_replay_state()
    expected_tail = []
    for index, bar in enumerate(case.bars):
        uninterrupted, frame, diagnostics = replay_step(case.identity, uninterrupted, bar)
        if index >= cut:
            expected_tail.append((frame, diagnostics))

    prefix = seed_replay_state()
    for bar in case.bars[:cut]:
        prefix, _frame, _diagnostics = replay_step(case.identity, prefix, bar)
    stream = _stream("newow-main-rise")
    checkpoint = AdapterCheckpoint(
        prefix, case.bars[cut - 1].bar.bar_end, "prefix", case.bars[cut - 1].bar.physical_contract,
        case.bars[cut - 1].bar.segment_id, case.bars[cut - 1].calculation_segment_id,
        stream, ReferenceState.flat(stream),
    )
    restored = adapter_checkpoint_from_json(
        adapter_checkpoint_to_json(checkpoint, strategy_schema="newow_product_replay_v1"),
        expected_stream=stream, expected_strategy_schema="newow_product_replay_v1",
    )
    actual_tail = []
    state = restored.strategy_state
    for bar in case.bars[cut:]:
        state, frame, diagnostics = replay_step(case.identity, state, bar)
        actual_tail.append((frame, diagnostics))

    assert actual_tail == expected_tail

    encoded = adapter_checkpoint_to_json(
        checkpoint, strategy_schema="newow_product_replay_v1",
    )
    assert '"frames"' not in encoded
    assert '"actions"' not in encoded
    assert '"trades"' not in encoded


def test_adapter_checkpoint_rejects_checksum_tampering_and_unknown_fields() -> None:
    stream = _stream("subing")
    checkpoint = AdapterCheckpoint(seed_subing_replay_state(), stream=stream, reference_state=ReferenceState.flat(stream))
    encoded = adapter_checkpoint_to_json(checkpoint, strategy_schema="subing_replay_v1")
    with pytest.raises(ValueError, match="checksum"):
        adapter_checkpoint_from_json(
            encoded.replace('"subing_replay_v1"', '"subing_replay_v2"'),
            expected_stream=stream, expected_strategy_schema="subing_replay_v1",
        )
    with pytest.raises(ValueError, match="unknown"):
        adapter_checkpoint_from_json(
            encoded[:-1] + ',"unknown":1}', expected_stream=stream,
            expected_strategy_schema="subing_replay_v1",
        )


def test_adapter_checkpoint_rejects_bool_disguised_as_integer() -> None:
    stream = _stream("subing")
    checkpoint = AdapterCheckpoint(
        seed_subing_replay_state(), stream=stream,
        reference_state=ReferenceState.flat(stream),
    )
    payload = json.loads(
        adapter_checkpoint_to_json(checkpoint, strategy_schema="subing_replay_v1")
    )
    payload["strategy_state"]["fields"]["processed_count"] = True
    body = {key: value for key, value in payload.items() if key != "checksum_sha256"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    payload["checksum_sha256"] = sha256(canonical.encode()).hexdigest()
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    with pytest.raises(ValueError, match="integer"):
        adapter_checkpoint_from_json(
            encoded, expected_stream=stream,
            expected_strategy_schema="subing_replay_v1",
        )
