import pytest

from scripts.newow_remaining19_audit import parse_products, proposed_unit_batches


def test_parse_products_is_ordered_unique_and_bounded_to_weekly_v2_scope():
    assert parse_products(["pf", "rs", "sr"]) == ("pf", "rs", "sr")
    with pytest.raises(ValueError, match="REMAINING19_SCOPE_INVALID"):
        parse_products(["pf", "pf"])
    with pytest.raises(ValueError, match="REMAINING19_SCOPE_INVALID"):
        parse_products(["au"])


def test_proposed_unit_batches_bind_current_plan_hash_and_split_at_twenty():
    targets = [
        {
            "symbol": "pf",
            "contract": f"PF{2501 + index}",
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
        "symbol": "pf",
        "contract": "PF2501",
        "through": "2026-09-18",
        "frequency": "1w",
        "expected_plan_sha256": "0" * 64,
    }
