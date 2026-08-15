from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from app.execution_review.contracts import (
    ExecutionReviewContractError,
    load_product_trade_multipliers,
    validate_execution_reasons,
    validate_not_executed,
    validate_review,
)
from app.market_data.operational_universe import load_active_products


def test_not_executed_requires_primary_reason() -> None:
    with pytest.raises(ExecutionReviewContractError, match="PRIMARY_REASON_REQUIRED"):
        validate_not_executed(primary_reason=None, secondary_reasons=(), note=None)


def test_other_reason_requires_note() -> None:
    with pytest.raises(ExecutionReviewContractError, match="OTHER_NOTE_REQUIRED"):
        validate_not_executed(
            primary_reason="OTHER",
            secondary_reasons=(),
            note="  ",
        )


def test_secondary_reasons_are_unique_and_exclude_primary() -> None:
    with pytest.raises(ExecutionReviewContractError, match="SECONDARY_REASON_DUPLICATE"):
        validate_not_executed(
            primary_reason="TOO_LATE",
            secondary_reasons=("POOR_LOCATION", "POOR_LOCATION"),
            note=None,
        )

    with pytest.raises(ExecutionReviewContractError, match="SECONDARY_REASON_PRIMARY"):
        validate_not_executed(
            primary_reason="TOO_LATE",
            secondary_reasons=("TOO_LATE",),
            note=None,
        )


def test_executed_requires_at_least_one_reason() -> None:
    with pytest.raises(ExecutionReviewContractError, match="EXECUTION_REASON_REQUIRED"):
        validate_execution_reasons(())


def test_unknown_reason_or_review_tag_is_rejected() -> None:
    with pytest.raises(ExecutionReviewContractError, match="UNKNOWN_DECISION_REASON"):
        validate_not_executed(
            primary_reason="MADE_UP",
            secondary_reasons=(),
            note=None,
        )

    with pytest.raises(ExecutionReviewContractError, match="UNKNOWN_EXECUTION_REASON"):
        validate_execution_reasons(("MADE_UP",))

    with pytest.raises(ExecutionReviewContractError, match="UNKNOWN_REVIEW_TAG"):
        validate_review(
            signal_execution_adherence="ALIGNED",
            entry_tags=("MADE_UP",),
            holding_tags=("NORMAL",),
            exit_tags=("NORMAL",),
            market_context_tags=("TREND",),
            psychology_tags=("NONE",),
        )


@pytest.mark.parametrize(
    ("group", "values"),
    [
        ("entry_tags", ("REASONABLE", "TOO_LATE")),
        ("holding_tags", ("NORMAL", "UNPLANNED_ADD")),
        ("exit_tags", ("NORMAL", "STOP_DELAYED")),
        ("psychology_tags", ("NONE", "HESITATION")),
    ],
)
def test_review_normal_tags_are_mutually_exclusive(
    group: str,
    values: tuple[str, ...],
) -> None:
    payload = {
        "entry_tags": ("REASONABLE",),
        "holding_tags": ("NORMAL",),
        "exit_tags": ("NORMAL",),
        "market_context_tags": ("TREND",),
        "psychology_tags": ("NONE",),
    }
    payload[group] = values

    with pytest.raises(ExecutionReviewContractError, match="REVIEW_TAG_CONFLICT"):
        validate_review(signal_execution_adherence="ALIGNED", **payload)


def test_review_requires_every_structured_group() -> None:
    with pytest.raises(ExecutionReviewContractError, match="REVIEW_TAG_REQUIRED"):
        validate_review(
            signal_execution_adherence="ALIGNED",
            entry_tags=("REASONABLE",),
            holding_tags=("NORMAL",),
            exit_tags=("NORMAL",),
            market_context_tags=(),
            psychology_tags=("NONE",),
        )


def test_multiplier_loader_normalizes_and_returns_missing_as_none(
    tmp_path: Path,
) -> None:
    path = tmp_path / "multipliers.csv"
    path.write_text("product,multiplier\n JM ,60\nec,50\n", encoding="utf-8")

    loaded = load_product_trade_multipliers(path)

    assert loaded == {"jm": Decimal("60"), "ec": Decimal("50")}
    assert all(isinstance(value, Decimal) for value in loaded.values())
    assert loaded.get("rb") is None


@pytest.mark.parametrize(
    "content",
    [
        "symbol,multiplier\njm,60\n",
        "product,multiplier\njm,60\nJM,60\n",
        "product,multiplier\njm,0\n",
        "product,multiplier\njm,-1\n",
        "product,multiplier\njm,NaN\n",
        "product,multiplier\njm,not-a-number\n",
        "product,multiplier\n,60\n",
    ],
)
def test_multiplier_loader_fails_closed_for_malformed_reference(
    tmp_path: Path,
    content: str,
) -> None:
    path = tmp_path / "multipliers.csv"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(ExecutionReviewContractError, match="MULTIPLIER_REFERENCE_INVALID"):
        load_product_trade_multipliers(path)


def test_tracked_multiplier_reference_is_an_active_subset() -> None:
    project_root = Path(__file__).resolve().parents[3]
    reference = load_product_trade_multipliers(
        project_root / "data/reference/product_trade_multipliers.csv"
    )
    active = set(load_active_products())

    assert reference == {
        "ec": Decimal("50"),
        "j": Decimal("100"),
        "jm": Decimal("60"),
        "lc": Decimal("1"),
        "rb": Decimal("10"),
        "si": Decimal("5"),
        "sr": Decimal("10"),
    }
    assert set(reference) <= active
    assert tuple(sorted(active - set(reference))) == (
        "a",
        "ag",
        "al",
        "ao",
        "ap",
        "au",
        "b",
        "bu",
        "bz",
        "c",
        "cf",
        "cj",
        "cu",
        "eb",
        "eg",
        "fg",
        "fu",
        "hc",
        "i",
        "jd",
        "l",
        "lh",
        "m",
        "ma",
        "ni",
        "oi",
        "p",
        "pb",
        "pd",
        "pf",
        "pg",
        "pk",
        "pl",
        "pp",
        "pr",
        "ps",
        "pt",
        "px",
        "rm",
        "rs",
        "ru",
        "sa",
        "sc",
        "sf",
        "sh",
        "sm",
        "sn",
        "ss",
        "ta",
        "ur",
        "v",
        "y",
        "zn",
    )
