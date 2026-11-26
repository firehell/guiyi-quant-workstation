from dataclasses import replace
from decimal import Decimal

import pytest

from guiyi_quant.lms405 import Bar
from guiyi_quant.lms405.portfolio_tasks import Book
from lms405_iron_original_exit import CONTRACT, evidence_gate
from lms405_right_side_study import FIVE, US, at


def test_iron_exit_proxy_requires_the_latest_strictly_known_revision_before_the_shape():
    known = at("2026-10-21T17:18")
    start = at("2026-10-21T21:00")
    old = dict(known_at=known - FIVE, edge=Decimal("680"), state="RANGE", role="DIVIDER", revision="old")
    latest = old | dict(known_at=known, edge=Decimal("686.5"), revision="latest")
    close = Decimal("686.5")
    shape = Bar(CONTRACT, start + FIVE, close, close, close, close, start=start)
    confirm = Bar(CONTRACT, start + 2 * FIVE, close, close, close, close, start=shape.end)
    decision_at = confirm.end + US
    book = Book(CONTRACT, "old-short", "SHORT", start - FIVE)
    evaluate = evidence_gate((old, latest), allow_price_proxy=True)

    assert evaluate(book, shape, confirm, decision_at)["revision"] == "latest"
    assert not evaluate(book, shape, confirm, decision_at)["admitted"]
    confirm_up = replace(confirm, close=Decimal(687), high=Decimal(687))
    assert evaluate(book, shape, confirm_up, decision_at)["admitted"]
    unknown_at_shape_start = latest | dict(known_at=shape.start)
    check = evidence_gate((old, unknown_at_shape_start), allow_price_proxy=True)
    assert check(book, shape, confirm_up, decision_at)["reason"] == "SHAPE_PRECEDES_PUBLISHED_REFERENCE"
    check = evidence_gate((old, latest | dict(known_at=decision_at)), allow_price_proxy=True)
    assert check(book, shape, confirm_up, decision_at)["revision"] == "old"

    assert evaluate(replace(book, direction="LONG"), shape, confirm_up, decision_at)["admitted"]
    assert evaluate(replace(book, contract="I2609"), shape, confirm_up, decision_at)["admitted"]
    with pytest.raises(ValueError, match="IRON_EXIT_CONTRACT_MISMATCH"):
        evaluate(book, shape, replace(confirm_up, contract="I2609"), decision_at)
    assert not evidence_gate((latest,), allow_price_proxy=False)(book, shape, confirm_up, decision_at)["admitted"]
