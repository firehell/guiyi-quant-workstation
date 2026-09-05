"""Pure proof contract for the page-v2 rank-1 as-known gate.

The provider's dated rule=2 mapping is checked against the complete prior
trading-day physical-contract universe.  This proves a causal reconstruction;
it deliberately does not claim a provider publication timestamp.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import re


_CONTRACT = re.compile(r"[A-Z]+\d{3,4}\Z")


class Rank1AsKnownError(ValueError):
    """Fail-closed validation error without a partial rank1 fallback."""

    def __init__(self) -> None:
        super().__init__("NEWOW_RANK1_AS_KNOWN_INVALID")


@dataclass(frozen=True, slots=True)
class Rank1PhysicalFact:
    contract: str
    volume: Decimal
    open_interest: Decimal

    def __post_init__(self) -> None:
        if (
            not _CONTRACT.fullmatch(self.contract)
            or not isinstance(self.volume, Decimal)
            or not isinstance(self.open_interest, Decimal)
            or not self.volume.is_finite()
            or not self.open_interest.is_finite()
            or self.volume < 0
            or self.open_interest < 0
        ):
            raise Rank1AsKnownError


@dataclass(frozen=True, slots=True)
class Rank1CausalInput:
    product: str
    decision_trading_day: date
    source_trading_day: date
    source_bar_end: datetime
    decision_session_open: datetime
    universe_contracts: tuple[str, ...]
    physical_facts: tuple[Rank1PhysicalFact, ...]
    rqdata_rule2_contract: str
    main_contract_map_contract: str

    def __post_init__(self) -> None:
        if (
            not re.fullmatch(r"[a-z]+", self.product)
            or type(self.decision_trading_day) is not date
            or type(self.source_trading_day) is not date
            or self.source_trading_day >= self.decision_trading_day
            or self.source_bar_end.tzinfo is None
            or self.source_bar_end.utcoffset() is None
            or self.decision_session_open.tzinfo is None
            or self.decision_session_open.utcoffset() is None
            or self.source_bar_end >= self.decision_session_open
            or not self.universe_contracts
            or self.universe_contracts != tuple(sorted(set(self.universe_contracts)))
            or any(
                not _contract_for_product(contract, self.product)
                for contract in self.universe_contracts
            )
            or not self.physical_facts
            or any(not isinstance(fact, Rank1PhysicalFact) for fact in self.physical_facts)
            or tuple(sorted(fact.contract for fact in self.physical_facts))
            != self.universe_contracts
            or not _contract_for_product(self.rqdata_rule2_contract, self.product)
            or not _contract_for_product(self.main_contract_map_contract, self.product)
        ):
            raise Rank1AsKnownError


@dataclass(frozen=True, slots=True)
class Rank1AsKnownRecord:
    product: str
    decision_trading_day: date
    source_trading_day: date
    contract: str
    source_bar_end: datetime
    decision_session_open: datetime


def validate_rank1_as_known(
    inputs: tuple[Rank1CausalInput, ...],
) -> tuple[Rank1AsKnownRecord, ...]:
    """Require an unambiguous prior-day double winner matching both authorities."""

    if not inputs:
        raise Rank1AsKnownError
    seen: set[tuple[str, date]] = set()
    records: list[Rank1AsKnownRecord] = []
    for item in inputs:
        if not isinstance(item, Rank1CausalInput):
            raise Rank1AsKnownError
        identity = (item.product, item.decision_trading_day)
        if identity in seen:
            raise Rank1AsKnownError
        seen.add(identity)
        winner = _double_winner(item.physical_facts)
        if (
            winner is None
            or winner != item.rqdata_rule2_contract
            or winner != item.main_contract_map_contract
        ):
            raise Rank1AsKnownError
        records.append(
            Rank1AsKnownRecord(
                product=item.product,
                decision_trading_day=item.decision_trading_day,
                source_trading_day=item.source_trading_day,
                contract=winner,
                source_bar_end=item.source_bar_end,
                decision_session_open=item.decision_session_open,
            )
        )
    return tuple(records)


def _double_winner(facts: tuple[Rank1PhysicalFact, ...]) -> str | None:
    maximum_volume = max(fact.volume for fact in facts)
    maximum_open_interest = max(fact.open_interest for fact in facts)
    volume_winners = tuple(
        fact.contract for fact in facts if fact.volume == maximum_volume
    )
    interest_winners = tuple(
        fact.contract for fact in facts if fact.open_interest == maximum_open_interest
    )
    if len(volume_winners) != 1 or len(interest_winners) != 1:
        return None
    return volume_winners[0] if volume_winners == interest_winners else None


def _contract_for_product(contract: str, product: str) -> bool:
    return bool(_CONTRACT.fullmatch(contract) and contract.startswith(product.upper()))
