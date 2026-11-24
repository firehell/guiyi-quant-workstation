"""Validate an immutable V2 candidate; activation is a host responsibility."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from guiyi_quant.newow.decision_adapter import DECISION_FREQUENCIES, V2Strategy
from guiyi_quant.newow.product_contracts import ProductFrequency

from app.market_data.domain import normalize_contract_for_symbol
from app.market_data.operational_universe import load_active_products, load_operational_products
from app.market_data.product_retirement import load_retired_products, normalize_symbol


@dataclass(frozen=True, slots=True)
class Deployment:
    product: str
    strategy: V2Strategy
    frequency: ProductFrequency
    draining: bool = False

    def __post_init__(self) -> None:
        product = normalize_symbol(self.product)
        frequency = ProductFrequency(self.frequency)
        if not product or frequency not in DECISION_FREQUENCIES or type(self.draining) is not bool:
            raise ValueError("V2_SCOPE_DEPLOYMENT_INVALID")
        object.__setattr__(self, "product", product)
        object.__setattr__(self, "strategy", V2Strategy(self.strategy))
        object.__setattr__(self, "frequency", frequency)


@dataclass(frozen=True, slots=True)
class Scope:
    revision: str
    market_products: tuple[str, ...]
    deployments: tuple[Deployment, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "market_products", tuple(map(normalize_symbol, self.market_products)))
        object.__setattr__(self, "deployments", tuple(self.deployments))


def validate_scope(
    candidate: Scope, *, supported: Iterable[str], retired: Iterable[str],
    isolated: bool = False,
) -> Scope:
    """Validate the whole candidate, including owners already draining."""
    market_limit, deployment_limit = (70, 20) if isolated else (60, 16)
    market = set(candidate.market_products)
    traded = {deployment.product for deployment in candidate.deployments}
    if not candidate.revision or "" in market or len(market) != len(candidate.market_products):
        raise ValueError("V2_SCOPE_MARKET_INVALID")
    if len(market) > market_limit or len(traded) > deployment_limit:
        raise ValueError("V2_SCOPE_CAPACITY_EXCEEDED")
    if market.intersection(retired) or not market.issubset(supported):
        raise ValueError("V2_SCOPE_PRODUCT_UNSUPPORTED")
    if len(traded) != len(candidate.deployments) or not traded.issubset(market):
        raise ValueError("V2_SCOPE_OWNER_CONFLICT")
    return candidate


def validate_formal_scope(candidate: Scope) -> Scope:
    active = frozenset(load_active_products())
    operational = active.intersection(load_operational_products())
    return validate_scope(candidate, supported=operational, retired=load_retired_products())


def physical_subscription_count(scope: Scope, subscriptions: Mapping[str, Iterable[str]]) -> int:
    """Count old and new physical subscriptions separately from product slots."""
    if set(subscriptions) != set(scope.market_products):
        raise ValueError("V2_SCOPE_SUBSCRIPTIONS_INVALID")
    count = 0
    for product, values in subscriptions.items():
        contracts = tuple(values)
        if len(set(contracts)) != len(contracts) or any(
            normalize_contract_for_symbol(product, contract) != contract for contract in contracts
        ):
            raise ValueError("V2_SCOPE_SUBSCRIPTIONS_INVALID")
        count += len(contracts)
    return count
