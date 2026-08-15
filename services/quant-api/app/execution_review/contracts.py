"""Frozen Execution Review vocabularies and reference-data validation."""

from __future__ import annotations

import csv
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app.market_data.operational_universe import load_active_products
from app.market_data.product_retirement import normalize_symbol


MULTIPLIER_POLICY_ID = "product_trade_multipliers_v1"

DECISION_DISPOSITIONS = frozenset({"EXECUTED", "NOT_EXECUTED"})
EPISODE_DIRECTIONS = frozenset({"LONG", "SHORT"})
EXECUTION_TYPES = frozenset({"OPEN", "ADD", "REDUCE", "CLOSE"})
CLOSE_REASONS = frozenset({"EXECUTION_NET_ZERO", "DOMINANT_ROLL"})
REVIEW_ADHERENCE_VALUES = frozenset({"ALIGNED", "DEVIATED"})

NOT_EXECUTED_REASONS = frozenset(
    {
        "WORK_MISSED",
        "TOO_LATE",
        "PRICE_ACTION_REJECTED",
        "POOR_LOCATION",
        "POOR_RISK_REWARD",
        "EXISTING_SAME_DIRECTION_TRADE",
        "EXISTING_OPPOSITE_DIRECTION_TRADE",
        "RISK_CAPACITY",
        "HESITATION",
        "OTHER",
    }
)
EXECUTION_REASON_TAGS = frozenset(
    {
        "HIGHER_TIMEFRAME_ALIGNED",
        "KEY_LEVEL_BREAKOUT",
        "PULLBACK_RECONFIRMED",
        "VOLUME_CONFIRMED",
        "MULTITF_STRUCTURE_ALIGNED",
        "LOCATION_ACCEPTABLE",
        "OTHER",
    }
)
STOP_BASES = frozenset(
    {"EMA", "PREVIOUS_BAR_EXTREME", "RANGE_BOUNDARY", "MOVE_ORIGIN", "OTHER"}
)

ENTRY_REVIEW_TAGS = frozenset(
    {
        "REASONABLE",
        "TOO_EARLY",
        "TOO_LATE",
        "CHASED",
        "BREAKOUT_CONFIRMATION_INSUFFICIENT",
    }
)
HOLDING_REVIEW_TAGS = frozenset(
    {"NORMAL", "COULD_NOT_HOLD", "REDUCED_TOO_EARLY", "UNPLANNED_ADD", "MISSED_VALID_ADD"}
)
EXIT_REVIEW_TAGS = frozenset(
    {
        "NORMAL",
        "STOP_DELAYED",
        "STOP_MOVED",
        "PROFIT_TO_LOSS",
        "EXIT_TOO_EARLY",
        "MISSED_PROFIT_REDUCTION",
    }
)
MARKET_CONTEXT_REVIEW_TAGS = frozenset(
    {
        "WITH_HIGHER_TIMEFRAME",
        "AGAINST_HIGHER_TIMEFRAME",
        "VALID_BREAKOUT",
        "FALSE_BREAKOUT",
        "RANGE",
        "TREND",
    }
)
PSYCHOLOGY_REVIEW_TAGS = frozenset(
    {"NONE", "HESITATION", "LOSS_AVERSION", "FOMO", "REVENGE", "PREDICTION_BIAS", "OVERTRADING"}
)


class ExecutionReviewContractError(ValueError):
    """A stable fail-closed domain-contract error."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def validate_not_executed(
    *,
    primary_reason: str | None,
    secondary_reasons: Sequence[str],
    note: str | None,
) -> None:
    """Validate the complete NOT_EXECUTED reason contract."""

    if primary_reason is None or not primary_reason.strip():
        raise ExecutionReviewContractError("PRIMARY_REASON_REQUIRED")
    primary = primary_reason
    if primary not in NOT_EXECUTED_REASONS:
        raise ExecutionReviewContractError("UNKNOWN_DECISION_REASON")
    secondary = tuple(secondary_reasons)
    if any(item not in NOT_EXECUTED_REASONS for item in secondary):
        raise ExecutionReviewContractError("UNKNOWN_DECISION_REASON")
    if len(secondary) != len(set(secondary)):
        raise ExecutionReviewContractError("SECONDARY_REASON_DUPLICATE")
    if primary in secondary:
        raise ExecutionReviewContractError("SECONDARY_REASON_PRIMARY")
    if primary == "OTHER" and (note is None or not note.strip()):
        raise ExecutionReviewContractError("OTHER_NOTE_REQUIRED")


def validate_execution_reasons(reasons: Sequence[str]) -> None:
    """Validate the required fixed execution-reason vocabulary."""

    exact_reasons = tuple(reasons)
    if not exact_reasons:
        raise ExecutionReviewContractError("EXECUTION_REASON_REQUIRED")
    if any(item not in EXECUTION_REASON_TAGS for item in exact_reasons):
        raise ExecutionReviewContractError("UNKNOWN_EXECUTION_REASON")
    if len(exact_reasons) != len(set(exact_reasons)):
        raise ExecutionReviewContractError("EXECUTION_REASON_DUPLICATE")


def validate_review(
    *,
    signal_execution_adherence: str,
    entry_tags: Sequence[str],
    holding_tags: Sequence[str],
    exit_tags: Sequence[str],
    market_context_tags: Sequence[str],
    psychology_tags: Sequence[str],
) -> None:
    """Validate all five required structured-review groups."""

    if signal_execution_adherence not in REVIEW_ADHERENCE_VALUES:
        raise ExecutionReviewContractError("UNKNOWN_REVIEW_ADHERENCE")
    groups = (
        (tuple(entry_tags), ENTRY_REVIEW_TAGS, "REASONABLE"),
        (tuple(holding_tags), HOLDING_REVIEW_TAGS, "NORMAL"),
        (tuple(exit_tags), EXIT_REVIEW_TAGS, "NORMAL"),
        (tuple(market_context_tags), MARKET_CONTEXT_REVIEW_TAGS, None),
        (tuple(psychology_tags), PSYCHOLOGY_REVIEW_TAGS, "NONE"),
    )
    for values, allowed, neutral in groups:
        if not values:
            raise ExecutionReviewContractError("REVIEW_TAG_REQUIRED")
        if any(value not in allowed for value in values):
            raise ExecutionReviewContractError("UNKNOWN_REVIEW_TAG")
        if len(values) != len(set(values)):
            raise ExecutionReviewContractError("REVIEW_TAG_DUPLICATE")
        if neutral is not None and neutral in values and len(values) > 1:
            raise ExecutionReviewContractError("REVIEW_TAG_CONFLICT")


def load_product_trade_multipliers(path: Path) -> dict[str, Decimal]:
    """Load verified CNY PnL scaling factors for an active-product subset."""

    try:
        if not path.is_file() or path.is_symlink():
            raise ExecutionReviewContractError("MULTIPLIER_REFERENCE_INVALID")
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != ["product", "multiplier"]:
                raise ExecutionReviewContractError("MULTIPLIER_REFERENCE_INVALID")
            rows = tuple(reader)
        active = frozenset(load_active_products())
        result: dict[str, Decimal] = {}
        for row in rows:
            if set(row) != {"product", "multiplier"}:
                raise ExecutionReviewContractError("MULTIPLIER_REFERENCE_INVALID")
            product = normalize_symbol(row["product"])
            value = Decimal(str(row["multiplier"]).strip())
            if (
                not product
                or product not in active
                or product in result
                or not value.is_finite()
                or value <= 0
            ):
                raise ExecutionReviewContractError("MULTIPLIER_REFERENCE_INVALID")
            result[product] = value
        return result
    except ExecutionReviewContractError:
        raise
    except (OSError, csv.Error, InvalidOperation, KeyError, TypeError, ValueError) as exc:
        raise ExecutionReviewContractError("MULTIPLIER_REFERENCE_INVALID") from exc
