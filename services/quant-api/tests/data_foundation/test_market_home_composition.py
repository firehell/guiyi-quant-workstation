from __future__ import annotations

import pytest

from app.market_data.market_home_overview import MarketHomeOverviewError
from app.market_data.errors import InfrastructureError
from app.market_data.operational_universe import ActiveUniverseError
from app.market_data.product_taxonomy import ProductTaxonomyError


def test_home_overview_composition_maps_active_universe_failure(monkeypatch) -> None:
    from app.market_data import composition

    monkeypatch.setattr(
        composition,
        "load_active_products",
        lambda: (_ for _ in ()).throw(ActiveUniverseError()),
    )

    with pytest.raises(MarketHomeOverviewError, match="MARKET_HOME_AUTHORITY_UNAVAILABLE"):
        composition.build_market_home_overview_service(object())


def test_home_overview_composition_maps_taxonomy_failure(monkeypatch) -> None:
    from app.market_data import composition

    monkeypatch.setattr(
        composition,
        "load_product_taxonomy",
        lambda: (_ for _ in ()).throw(ProductTaxonomyError()),
    )

    with pytest.raises(MarketHomeOverviewError, match="MARKET_HOME_AUTHORITY_UNAVAILABLE"):
        composition.build_market_home_overview_service(object())


def test_home_overview_composition_maps_coverage_construction_failure(monkeypatch) -> None:
    from app.market_data import composition

    monkeypatch.setattr(
        "app.market_data.coverage_source.DatabaseCoverageSource",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            InfrastructureError("HISTORY_FLOOR_INVALID")
        ),
    )

    with pytest.raises(MarketHomeOverviewError, match="MARKET_HOME_AUTHORITY_UNAVAILABLE"):
        composition.build_market_home_overview_service(object())
