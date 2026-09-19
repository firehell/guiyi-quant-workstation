import pytest

from scripts.newow_remaining19_audit import parse_products


def test_parse_products_is_ordered_unique_and_bounded_to_remaining19():
    assert parse_products(["j", "pg", "si"]) == ("j", "pg", "si")
    with pytest.raises(ValueError, match="REMAINING19_SCOPE_INVALID"):
        parse_products(["j", "j"])
    with pytest.raises(ValueError, match="REMAINING19_SCOPE_INVALID"):
        parse_products(["au"])
