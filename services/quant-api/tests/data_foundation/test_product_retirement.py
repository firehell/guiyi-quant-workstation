from __future__ import annotations

from datetime import date

import pytest

from app.core.env import PROJECT_ROOT
from app.market_data.product_retirement import (
    ProductRetiredError,
    assert_not_retired,
    is_retired,
    load_retired_products,
)


def test_retired_products_file_is_exact_and_disjoint_from_active() -> None:
    retired = load_retired_products()
    assert retired == frozenset({"br", "cs", "ic", "if", "ih", "im", "lu", "nr", "pd", "pt", "rs", "sp"})
    active = {
        line.strip().lower()
        for line in (PROJECT_ROOT / "data/universe/active_products.txt").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    }
    assert len(active) == 57
    assert retired.isdisjoint(active)


def test_assert_not_retired_uses_exact_membership() -> None:
    retired = frozenset({"br", "cs", "ic", "if", "ih", "im", "lu", "nr", "sp"})
    assert_not_retired("jm", retired=retired)
    assert not is_retired("jm", retired=retired)
    with pytest.raises(ProductRetiredError) as exc:
        assert_not_retired("BR", retired=retired)
    assert exc.value.code == "PRODUCT_RETIRED"


@pytest.mark.parametrize(("product", "contract"), [(" PD ", "PD2701"), (" Pt ", "PT2701"), (" RS ", "RS2701")])
def test_retirement_precedes_catalog_and_strategy_reads(product, contract):
    from app.guiyi_cli.data_commands import _active_product
    from app.market_data.domain import ContractTradingDayQuery
    from app.market_data.market_data_service import MarketDataError, MarketDataService
    from app.market_data.newow.market_reference_after_close import latest_formal_reference
    from app.market_data.newow.v2_scope import Scope, validate_formal_scope

    market = MarketDataService(None, None)
    with pytest.raises(MarketDataError, match="PRODUCT_RETIRED"):
        market.latest_dominant_segment(product)
    with pytest.raises(MarketDataError, match="PRODUCT_RETIRED"):
        day = date(2026, 11, 26)
        market.query_contract_trading_days(ContractTradingDayQuery(product, contract, "1d", day, day))
    with pytest.raises(ProductRetiredError, match="PRODUCT_RETIRED"):
        _active_product(product)
    with pytest.raises(ProductRetiredError, match="PRODUCT_RETIRED"):
        latest_formal_reference(product, "trend", "1d", session_factory=None)
    with pytest.raises(ValueError, match="V2_SCOPE_PRODUCT_UNSUPPORTED"):
        validate_formal_scope(Scope("retired-product", (product,), ()))
