"""Shared Newow test configuration."""

import pytest


@pytest.fixture
def product_cases():
    from .product_fixtures import ProductCases

    return ProductCases()
