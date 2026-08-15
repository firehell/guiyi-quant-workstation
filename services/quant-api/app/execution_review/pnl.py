"""Zero-I/O Decimal-only position and Estimated Gross PnL calculations."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.execution_review.contracts import EPISODE_DIRECTIONS, EXECUTION_TYPES


@dataclass(frozen=True, slots=True)
class ExecutionFact:
    """One execution ordered solely by its episode-local sequence number."""

    sequence_no: int
    execution_type: str
    price: Decimal
    quantity: int


@dataclass(frozen=True, slots=True)
class PositionState:
    """Derived position state and manual-fact-based gross PnL estimate."""

    remaining_quantity: int
    average_cost: Decimal | None
    realized_points: Decimal
    realized_gross_pnl: Decimal | None


class ExecutionTopologyError(ValueError):
    """A stable fail-closed timeline or Decimal input error."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def calculate_position_state(
    *,
    direction: str,
    executions: Sequence[ExecutionFact],
    multiplier: Decimal | None,
) -> PositionState:
    """Replay a complete timeline in deterministic ``sequence_no`` order."""

    _validate_direction(direction)
    _validate_multiplier(multiplier)
    if not executions:
        raise ExecutionTopologyError("TIMELINE_EMPTY")

    for fact in executions:
        _validate_fact(fact)
    sequence_numbers = tuple(fact.sequence_no for fact in executions)
    if len(sequence_numbers) != len(set(sequence_numbers)):
        raise ExecutionTopologyError("SEQUENCE_DUPLICATE")
    if tuple(sorted(sequence_numbers)) != tuple(range(1, len(executions) + 1)):
        raise ExecutionTopologyError("SEQUENCE_GAP")

    ordered = tuple(sorted(executions, key=lambda fact: fact.sequence_no))
    if ordered[0].execution_type != "OPEN":
        raise ExecutionTopologyError("OPEN_REQUIRED")

    remaining = 0
    average_cost: Decimal | None = None
    realized_points = Decimal("0")
    closed = False

    for fact in ordered:
        if closed:
            raise ExecutionTopologyError("EXECUTION_AFTER_CLOSE")
        if fact.execution_type == "OPEN":
            if fact.sequence_no != 1:
                raise ExecutionTopologyError("OPEN_REPEATED")
            remaining = fact.quantity
            average_cost = fact.price
            continue
        if fact.execution_type == "ADD":
            assert average_cost is not None
            total_cost = average_cost * remaining + fact.price * fact.quantity
            remaining += fact.quantity
            average_cost = total_cost / remaining
            continue
        if fact.execution_type == "REDUCE":
            if fact.quantity >= remaining:
                raise ExecutionTopologyError("REDUCE_QUANTITY_INVALID")
            assert average_cost is not None
            realized_points += _realized_points(
                direction=direction,
                average_cost=average_cost,
                exit_price=fact.price,
                quantity=fact.quantity,
            )
            remaining -= fact.quantity
            continue
        if fact.execution_type == "CLOSE":
            if fact.quantity != remaining:
                raise ExecutionTopologyError("CLOSE_QUANTITY_INVALID")
            assert average_cost is not None
            realized_points += _realized_points(
                direction=direction,
                average_cost=average_cost,
                exit_price=fact.price,
                quantity=fact.quantity,
            )
            remaining = 0
            average_cost = None
            closed = True
            continue
        raise ExecutionTopologyError("EXECUTION_TYPE_INVALID")

    gross_pnl = None if multiplier is None else realized_points * multiplier
    return PositionState(
        remaining_quantity=remaining,
        average_cost=average_cost,
        realized_points=realized_points,
        realized_gross_pnl=gross_pnl,
    )


def calculate_roll_estimate(
    *,
    direction: str,
    position: PositionState,
    exit_price: Decimal,
    multiplier: Decimal | None,
) -> Decimal | None:
    """Estimate gross PnL for only the remaining open quantity."""

    _validate_direction(direction)
    _validate_decimal(exit_price, "PRICE_INVALID")
    _validate_multiplier(multiplier)
    if position.remaining_quantity <= 0 or position.average_cost is None:
        raise ExecutionTopologyError("POSITION_NOT_OPEN")
    if multiplier is None:
        return None
    return _realized_points(
        direction=direction,
        average_cost=position.average_cost,
        exit_price=exit_price,
        quantity=position.remaining_quantity,
    ) * multiplier


def _validate_direction(direction: str) -> None:
    if direction not in EPISODE_DIRECTIONS:
        raise ExecutionTopologyError("DIRECTION_INVALID")


def _validate_multiplier(multiplier: Decimal | None) -> None:
    if multiplier is not None:
        _validate_decimal(multiplier, "MULTIPLIER_INVALID")


def _validate_fact(fact: ExecutionFact) -> None:
    if type(fact.sequence_no) is not int or fact.sequence_no <= 0:
        raise ExecutionTopologyError("SEQUENCE_INVALID")
    if fact.execution_type not in EXECUTION_TYPES:
        raise ExecutionTopologyError("EXECUTION_TYPE_INVALID")
    _validate_decimal(fact.price, "PRICE_INVALID")
    if type(fact.quantity) is not int or fact.quantity <= 0:
        raise ExecutionTopologyError("QUANTITY_INVALID")


def _validate_decimal(value: object, code: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
        raise ExecutionTopologyError(code)


def _realized_points(
    *,
    direction: str,
    average_cost: Decimal,
    exit_price: Decimal,
    quantity: int,
) -> Decimal:
    difference = (
        exit_price - average_cost
        if direction == "LONG"
        else average_cost - exit_price
    )
    return difference * quantity
