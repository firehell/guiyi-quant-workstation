import pytest

from scripts import newow_remaining19_audit as audit
from scripts.newow_remaining19_audit import parse_products, proposed_unit_batches


def test_parse_products_is_ordered_unique_and_bounded_to_remaining19(monkeypatch):
    # Exercise the frozen utility with an explicit historical scope; the current
    # released scope has no remaining candidates and must stay closed below.
    monkeypatch.setattr(audit, "REMAINING_WEEKLY_V2_PRODUCTS", ("j", "pg", "si"))
    assert parse_products(["j", "pg", "si"]) == ("j", "pg", "si")
    with pytest.raises(ValueError, match="REMAINING19_SCOPE_INVALID"):
        parse_products(["j", "j"])
    with pytest.raises(ValueError, match="REMAINING19_SCOPE_INVALID"):
        parse_products(["au"])


def test_current_remaining19_scope_stays_closed_after_all_products_graduate():
    assert audit.REMAINING_WEEKLY_V2_PRODUCTS == ()
    for products in (["j"], ["pg"], ["si"], ["j", "pg", "si"], []):
        with pytest.raises(ValueError, match="REMAINING19_SCOPE_INVALID"):
            parse_products(products)


def test_proposed_unit_batches_bind_current_plan_hash_and_split_at_twenty():
    targets = [
        {
            "symbol": "pg",
            "contract": f"PG{2501 + index}",
            "frequency": "1w",
            "through": "2026-09-18",
            "status": "PROPOSED",
            "plan_sha256": f"{index:064x}",
        }
        for index in range(21)
    ]

    batches = proposed_unit_batches({"repair_targets": targets})

    assert [len(batch) for batch in batches] == [20, 1]
    assert batches[0][0] == {
        "symbol": "pg",
        "contract": "PG2501",
        "through": "2026-09-18",
        "frequency": "1w",
        "expected_plan_sha256": "0" * 64,
    }
