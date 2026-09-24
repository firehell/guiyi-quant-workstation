from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from guiyi_quant.reference_trading import BoundaryReason, ReferenceBoundary, StreamIdentity
from guiyi_quant.reference_trading.adapters import strategy_input_fingerprint

from app.reference_trading.inputs import (
    HistoricalInputBar, _insert_boundaries, _owned_newow_interruptions,
)
from app.reference_trading.service import (
    NewowHistoricalPayload,
    _advance_batch,
    _seed_checkpoint,
)


@pytest.fixture
def product_cases():
    from newow.product_fixtures import ProductCases

    return ProductCases()


@pytest.mark.parametrize("strategy", ("trend", "oscillation", "main_rise"))
@pytest.mark.parametrize("frequency", ("1d", "1w", "60m"))
def test_newow_supported_matrix_advances_with_real_p2_adapter(
    product_cases, strategy: str, frequency: str,
) -> None:
    case = product_cases.primitive_input(strategy, frequency)
    stream = StreamIdentity(
        strategy_code=f"newow_{strategy}",
        formula_versions=case.identity.formula_versions,
        profile_id=case.identity.profile_id,
        reference_model_version="newow_reference_v3",
        futures_adaptation_version="newow_futures_v1",
        product=case.identity.product,
        frequency=frequency,
        series_kind=case.identity.series_kind,
        recording_mode="historical_replay",
        observation_policy_version=None,
    )
    bars = tuple(
        HistoricalInputBar(
            item.bar.bar_end,
            item.bar.trading_day,
            item.bar.physical_contract,
            item.bar.segment_id,
            item.calculation_segment_id,
            item.bar.close,
            strategy_input_fingerprint({
                "bar_end": item.bar.bar_end,
                "source": item.source_bar_sha256,
            }),
            NewowHistoricalPayload(case.identity, item),
        )
        for item in case.bars
    )

    checkpoint, schema = _seed_checkpoint(stream)
    for start in range(0, len(bars), 23):
        checkpoint, sources, transitions, schema = _advance_batch(
            stream, checkpoint, bars[start:start + 23],
        )
        assert len(transitions) == len(bars[start:start + 23])

    assert schema == "newow_product_replay_v1"
    assert checkpoint.computed_through == bars[-1].bar_end
    assert checkpoint.reference_state is not None
    assert checkpoint.strategy_state.input_progress


def test_newow_boundary_without_matching_bar_is_an_explicit_replay_event(product_cases) -> None:
    case = product_cases.primitive_input("trend", "1d")
    stream = StreamIdentity(
        strategy_code="newow_trend",
        formula_versions=case.identity.formula_versions,
        profile_id=case.identity.profile_id,
        reference_model_version="newow_reference_v3",
        futures_adaptation_version="newow_futures_v1",
        product=case.identity.product,
        frequency="1d",
        series_kind=case.identity.series_kind,
        recording_mode="historical_replay",
        observation_policy_version=None,
    )
    bars = [
        HistoricalInputBar(
            item.bar.bar_end,
            item.bar.trading_day,
            item.bar.physical_contract,
            item.bar.segment_id,
            item.calculation_segment_id,
            item.bar.close,
            strategy_input_fingerprint({"bar_end": item.bar.bar_end, "source": item.source_bar_sha256}),
            NewowHistoricalPayload(case.identity, item),
        )
        for item in case.bars
    ]
    anchor = bars[len(bars) // 2]
    effective_at = anchor.bar_end + timedelta(seconds=1)
    assert all(item.bar_end != effective_at for item in bars)
    boundary = ReferenceBoundary(
        stream,
        BoundaryReason.DATA_INTERRUPTED,
        anchor.physical_contract,
        anchor.owner_segment_id,
        anchor.calculation_segment_id,
        effective_at,
        anchor.trading_day,
    )

    replay = _insert_boundaries(bars, (boundary,))

    explicit = [item for item in replay if not item.strategy_input]
    assert len(explicit) == 1
    assert explicit[0].boundaries[0].bar_end == effective_at

    same_bar = ReferenceBoundary(
        stream,
        BoundaryReason.DATA_INTERRUPTED,
        anchor.physical_contract,
        anchor.owner_segment_id,
        anchor.calculation_segment_id,
        anchor.bar_end,
        anchor.trading_day,
    )
    merged = _insert_boundaries(list(bars), (same_bar,))
    matching = [item for item in merged if item.bar_end == anchor.bar_end]
    assert len(matching) == 1
    assert matching[0].strategy_input is True
    assert matching[0].boundaries == (same_bar,)
    assert matching[0].fingerprint != anchor.fingerprint


def test_quality_gap_before_first_owner_bar_has_no_invented_price(product_cases) -> None:
    case = product_cases.primitive_input("trend", "1d")
    stream = StreamIdentity(
        "newow_trend", case.identity.formula_versions, case.identity.profile_id,
        "newow_reference_v3", "newow_futures_v1", case.identity.product,
        "1d", case.identity.series_kind, "historical_replay", None,
    )
    prior, later = case.bars[:2]

    def input_bar(item, *, contract=None, owner=None):
        return HistoricalInputBar(
            item.bar.bar_end, item.bar.trading_day,
            contract or item.bar.physical_contract,
            owner or item.bar.segment_id,
            owner or item.calculation_segment_id,
            item.bar.close,
            strategy_input_fingerprint({"bar_end": item.bar.bar_end}),
            NewowHistoricalPayload(case.identity, item),
        )

    first = input_bar(prior)
    second = input_bar(later, contract="RB2701", owner="new-owner")
    gap = ReferenceBoundary(
        stream, BoundaryReason.DATA_INTERRUPTED,
        second.physical_contract, second.owner_segment_id,
        second.calculation_segment_id,
        second.bar_end - timedelta(hours=1), second.trading_day,
    )
    replay = _insert_boundaries([first, second], (gap,))
    assert [item.bar_end for item in replay] == [first.bar_end, gap.bar_end, second.bar_end]
    assert replay[1].strategy_input is False
    assert replay[1].reference_price is None
    assert replay[1].boundaries == (gap,)


def test_pre_owner_warmup_gap_remains_source_evidence_without_trade_boundary() -> None:
    owners = (
        SimpleNamespace(contract="OI2609", start_trading_day=date(2026, 4, 15)),
        SimpleNamespace(contract="OI2611", start_trading_day=date(2026, 8, 19)),
    )
    boundary = SimpleNamespace(
        old_contract="OI2609", old_segment_id="old-owner",
        new_contract="OI2611", new_segment_id="new-owner",
        effective_trading_day=date(2026, 8, 19),
    )
    warmup_gap = SimpleNamespace(
        physical_contract="OI2611", segment_id="new-owner",
        trading_day=date(2025, 11, 17),
    )
    owned_gap = SimpleNamespace(
        physical_contract="OI2611", segment_id="new-owner",
        trading_day=date(2026, 8, 20),
    )
    read = SimpleNamespace(
        owners=owners, boundaries=(boundary,),
        data_interruptions=(warmup_gap, owned_gap), replay_bars=(),
    )
    assert _owned_newow_interruptions(read) == (owned_gap,)
    with pytest.raises(ValueError, match="REFERENCE_BOUNDARY_OWNER_CONFLICT"):
        _owned_newow_interruptions(SimpleNamespace(
            owners=owners, boundaries=(boundary,),
            data_interruptions=(SimpleNamespace(
                physical_contract="OI2611", segment_id="unknown",
                trading_day=date(2026, 8, 20),
            ),), replay_bars=(),
        ))
