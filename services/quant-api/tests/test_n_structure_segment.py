from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from app.research.n_structure import n_structure_segment as segment_module
from app.market_data.domain import CanonicalBar
from app.research.n_structure.n_structure_policy import load_n_structure_policy


_CONTRACT = "JM2701"
_SEGMENT_START = date(2026, 8, 3)
_TRADING_DAY = date(2026, 8, 19)
_START = datetime(2026, 8, 19, 1, 5, tzinfo=UTC)
_VALUES = (
    ("10", "9"),
    ("9", "8.5"),
    ("8.5", "8"),
    ("9.5", "8.2"),
    ("12", "9"),
    ("11", "8.8"),
    ("13", "9"),
    ("14", "10"),
    ("13", "9.5"),
    ("15", "10"),
)


def _bars() -> tuple[CanonicalBar, ...]:
    result: list[CanonicalBar] = []
    for index, (high, low) in enumerate(_VALUES):
        high_value = Decimal(high)
        low_value = Decimal(low)
        midpoint = (high_value + low_value) / Decimal(2)
        result.append(
            CanonicalBar(
                bar_end=_START + timedelta(minutes=5 * index),
                trading_day=_TRADING_DAY,
                open=midpoint,
                high=high_value,
                low=low_value,
                close=midpoint,
                volume=Decimal("100"),
                turnover=None,
                open_interest=None,
            )
        )
    return tuple(result)


def test_segment_evaluator_runs_each_n_layer_once(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls = {"swing": 0, "pattern": 0, "structure": 0}
    original_swing = segment_module.reduce_n_swings
    original_pattern = segment_module._evaluate_n_patterns_from_exact_swings
    original_structure = (
        segment_module._evaluate_n_market_structure_from_exact_facts
    )

    def counted_swing(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls["swing"] += 1
        return original_swing(*args, **kwargs)

    def counted_pattern(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls["pattern"] += 1
        return original_pattern(*args, **kwargs)

    def counted_structure(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls["structure"] += 1
        return original_structure(*args, **kwargs)

    monkeypatch.setattr(segment_module, "reduce_n_swings", counted_swing)
    monkeypatch.setattr(
        segment_module,
        "_evaluate_n_patterns_from_exact_swings",
        counted_pattern,
    )
    monkeypatch.setattr(
        segment_module,
        "_evaluate_n_market_structure_from_exact_facts",
        counted_structure,
    )

    trace = segment_module.evaluate_n_structure_segment(
        _bars(),
        contract=_CONTRACT,
        segment_start_trading_day=_SEGMENT_START,
        segment_end_trading_day=_TRADING_DAY,
        policy=load_n_structure_policy(),
    )

    assert calls == {"swing": 1, "pattern": 1, "structure": 1}
    assert trace.swings.pivots
    assert trace.patterns.patterns
    assert len(trace.structures.snapshots) == len(_VALUES)
