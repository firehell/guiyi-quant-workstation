from __future__ import annotations

from decimal import Decimal

import pytest

from app.execution_review.pnl import (
    ExecutionFact,
    ExecutionTopologyError,
    calculate_position_state,
    calculate_roll_estimate,
)


def _fact(sequence_no: int, kind: str, price: str, quantity: int) -> ExecutionFact:
    return ExecutionFact(sequence_no, kind, Decimal(price), quantity)


def test_long_open_add_reduce_close_uses_sequence_and_weighted_average_cost() -> None:
    executions = (
        _fact(4, "CLOSE", "130", 1),
        _fact(2, "ADD", "110", 1),
        _fact(1, "OPEN", "100", 1),
        _fact(3, "REDUCE", "120", 1),
    )

    state = calculate_position_state(
        direction="LONG",
        executions=executions,
        multiplier=Decimal("10"),
    )

    assert state.remaining_quantity == 0
    assert state.average_cost is None
    assert state.realized_points == Decimal("40")
    assert state.realized_gross_pnl == Decimal("400")


def test_short_is_mirrored() -> None:
    state = calculate_position_state(
        direction="SHORT",
        executions=(
            _fact(1, "OPEN", "100", 1),
            _fact(2, "ADD", "90", 1),
            _fact(3, "REDUCE", "80", 1),
            _fact(4, "CLOSE", "70", 1),
        ),
        multiplier=Decimal("10"),
    )

    assert state.realized_points == Decimal("40")
    assert state.realized_gross_pnl == Decimal("400")


@pytest.mark.parametrize(
    ("executions", "code"),
    [
        ((_fact(1, "OPEN", "100", 1), _fact(1, "ADD", "110", 1)), "SEQUENCE_DUPLICATE"),
        ((_fact(1, "OPEN", "100", 1), _fact(3, "ADD", "110", 1)), "SEQUENCE_GAP"),
        ((_fact(0, "OPEN", "100", 1),), "SEQUENCE_INVALID"),
        ((_fact(1, "ADD", "100", 1),), "OPEN_REQUIRED"),
        ((_fact(1, "OPEN", "100", 1), _fact(2, "OPEN", "110", 1)), "OPEN_REPEATED"),
    ],
)
def test_sequence_and_open_topology_fail_closed(
    executions: tuple[ExecutionFact, ...],
    code: str,
) -> None:
    with pytest.raises(ExecutionTopologyError, match=code):
        calculate_position_state(
            direction="LONG",
            executions=executions,
            multiplier=Decimal("10"),
        )


@pytest.mark.parametrize(
    ("executions", "code"),
    [
        (
            (_fact(1, "OPEN", "100", 1), _fact(2, "REDUCE", "110", 1)),
            "REDUCE_QUANTITY_INVALID",
        ),
        (
            (_fact(1, "OPEN", "100", 1), _fact(2, "CLOSE", "110", 2)),
            "CLOSE_QUANTITY_INVALID",
        ),
        (
            (
                _fact(1, "OPEN", "100", 1),
                _fact(2, "CLOSE", "110", 1),
                _fact(3, "ADD", "120", 1),
            ),
            "EXECUTION_AFTER_CLOSE",
        ),
    ],
)
def test_over_reduce_reverse_and_post_close_execution_fail_closed(
    executions: tuple[ExecutionFact, ...],
    code: str,
) -> None:
    with pytest.raises(ExecutionTopologyError, match=code):
        calculate_position_state(
            direction="LONG",
            executions=executions,
            multiplier=Decimal("10"),
        )


def test_missing_multiplier_keeps_points_but_amount_unavailable() -> None:
    state = calculate_position_state(
        direction="LONG",
        executions=(
            _fact(1, "OPEN", "100", 2),
            _fact(2, "REDUCE", "110", 1),
        ),
        multiplier=None,
    )

    assert state.remaining_quantity == 1
    assert state.average_cost == Decimal("100")
    assert state.realized_points == Decimal("10")
    assert state.realized_gross_pnl is None
    assert (
        calculate_roll_estimate(
            direction="LONG",
            position=state,
            exit_price=Decimal("120"),
            multiplier=None,
        )
        is None
    )


def test_roll_estimate_values_only_remaining_quantity() -> None:
    state = calculate_position_state(
        direction="LONG",
        executions=(
            _fact(1, "OPEN", "100", 2),
            _fact(2, "REDUCE", "110", 1),
        ),
        multiplier=Decimal("10"),
    )

    estimate = calculate_roll_estimate(
        direction="LONG",
        position=state,
        exit_price=Decimal("120"),
        multiplier=Decimal("10"),
    )

    assert state.realized_gross_pnl == Decimal("100")
    assert estimate == Decimal("200")


@pytest.mark.parametrize(
    ("direction", "executions", "multiplier", "code"),
    [
        ("FLAT", (_fact(1, "OPEN", "100", 1),), Decimal("10"), "DIRECTION_INVALID"),
        ("LONG", (), Decimal("10"), "TIMELINE_EMPTY"),
        ("LONG", (ExecutionFact(1, "OPEN", 100.0, 1),), Decimal("10"), "PRICE_INVALID"),
        ("LONG", (_fact(1, "OPEN", "0", 1),), Decimal("10"), "PRICE_INVALID"),
        ("LONG", (_fact(1, "OPEN", "100", 0),), Decimal("10"), "QUANTITY_INVALID"),
        ("LONG", (_fact(1, "OPEN", "100", 1),), Decimal("0"), "MULTIPLIER_INVALID"),
    ],
)
def test_invalid_scalar_inputs_fail_closed(
    direction: str,
    executions: tuple[ExecutionFact, ...],
    multiplier: Decimal | None,
    code: str,
) -> None:
    with pytest.raises(ExecutionTopologyError, match=code):
        calculate_position_state(
            direction=direction,
            executions=executions,
            multiplier=multiplier,
        )
