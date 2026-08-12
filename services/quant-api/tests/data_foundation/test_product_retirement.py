from __future__ import annotations

import pytest

from app.core.env import PROJECT_ROOT
from app.market_data.product_retirement import (
    ProductRetiredError,
    assert_not_retired,
    is_retired,
    load_retired_products,
)


def test_retired_products_file_is_exact_nine_and_disjoint_from_active() -> None:
    retired = load_retired_products()
    assert retired == frozenset({"br", "cs", "ic", "if", "ih", "im", "lu", "nr", "sp"})
    active = {
        line.strip().lower()
        for line in (PROJECT_ROOT / "data/universe/active_products.txt").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    }
    assert len(active) == 60
    assert retired.isdisjoint(active)


def test_assert_not_retired_uses_exact_membership() -> None:
    retired = frozenset({"br", "cs", "ic", "if", "ih", "im", "lu", "nr", "sp"})
    assert_not_retired("jm", retired=retired)
    assert not is_retired("jm", retired=retired)
    with pytest.raises(ProductRetiredError) as exc:
        assert_not_retired("BR", retired=retired)
    assert exc.value.code == "PRODUCT_RETIRED"
