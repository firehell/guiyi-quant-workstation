from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import pytest

from guiyi_quant.reference_trading.adapters import (
    AdapterCheckpoint,
    CompletedStrategyInput,
    advance_checked,
    strategy_input_fingerprint,
)


@dataclass
class MutableKernel:
    values: list[str]


def _input(at: datetime, fingerprint: str) -> CompletedStrategyInput[str]:
    return CompletedStrategyInput(
        payload=fingerprint,
        bar_end=at,
        trading_day=date(2026, 9, 19),
        physical_contract="RB2601",
        owner_segment_id="owner",
        calculation_segment_id="calc",
        fingerprint=fingerprint,
    )


def test_checked_advance_is_idempotent_and_rejects_conflict_and_older_input() -> None:
    at = datetime(2026, 9, 19, 15, tzinfo=UTC)
    calls = 0

    def step(state: MutableKernel, item: CompletedStrategyInput[str]) -> str:
        nonlocal calls
        calls += 1
        state.values.append(item.payload)
        return item.payload

    seeded = AdapterCheckpoint(MutableKernel([]))
    advanced, outputs = advance_checked(seeded, (_input(at, "a"),), step=step)
    replayed, duplicate_outputs = advance_checked(advanced, (_input(at, "a"),), step=step)

    assert outputs == ("a",)
    assert replayed is advanced
    assert duplicate_outputs == ()
    assert calls == 1
    with pytest.raises(ValueError, match="conflicts"):
        advance_checked(advanced, (_input(at, "b"),), step=step)
    with pytest.raises(ValueError, match="older"):
        advance_checked(advanced, (_input(at - timedelta(days=1), "z"),), step=step)


def test_checked_advance_does_not_mutate_original_state_when_step_fails() -> None:
    at = datetime(2026, 9, 19, 15, tzinfo=UTC)
    seeded = AdapterCheckpoint(MutableKernel(["kept"]))

    def failing(state: MutableKernel, item: CompletedStrategyInput[str]) -> str:
        state.values.append(item.payload)
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        advance_checked(seeded, (_input(at, "bad"),), step=failing)

    assert seeded.strategy_state.values == ["kept"]
    assert seeded.computed_through is None


def test_fingerprint_binds_prices_identity_quality_and_lifecycle_evidence() -> None:
    at = datetime(2026, 9, 19, 15, tzinfo=UTC)
    facts = {
        "ohlc": {"open": "100", "high": "110", "low": "90", "close": "105"},
        "physical_contract": "RB2601",
        "bar_end": at,
        "trading_day": at.date(),
        "frequency": "1d",
        "owner_segment": "owner",
        "calculation_segment": "calc",
        "quality_boundary": "quality-v2",
        "lifecycle_evidence": "evidence-sha256",
    }
    original = strategy_input_fingerprint(facts)

    for key, changed in (
        ("ohlc", {**facts["ohlc"], "close": "106"}),
        ("physical_contract", "RB2605"),
        ("quality_boundary", "quality-v3"),
        ("lifecycle_evidence", "other-evidence"),
    ):
        assert strategy_input_fingerprint({**facts, key: changed}) != original


def test_checked_advance_step_count_grows_only_with_new_bars() -> None:
    at = datetime(2026, 9, 19, 15, tzinfo=UTC)
    calls = 0

    def step(state: MutableKernel, item: CompletedStrategyInput[str]) -> str:
        nonlocal calls
        calls += 1
        state.values.append(item.payload)
        return item.payload

    checkpoint = AdapterCheckpoint(MutableKernel([]))
    first_inputs = tuple(
        _input(at + timedelta(days=index), f"bar-{index}") for index in range(3)
    )
    checkpoint, _ = advance_checked(checkpoint, first_inputs, step=step)
    checkpoint, _ = advance_checked(
        checkpoint,
        (_input(at + timedelta(days=2), "bar-2"), _input(at + timedelta(days=3), "bar-3")),
        step=step,
    )

    assert calls == 4
    assert checkpoint.strategy_state.values == ["bar-0", "bar-1", "bar-2", "bar-3"]
