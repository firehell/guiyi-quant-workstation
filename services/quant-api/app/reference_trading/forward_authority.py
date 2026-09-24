"""Resolve forward owner and Session identities from the shared MarketDataService."""

from __future__ import annotations

from datetime import date, datetime

from guiyi_quant.newow.product_identity import (
    build_calculation_segment_id, build_segment_id,
)
from guiyi_quant.reference_trading import StreamIdentity

from app.market_data.market_data_service import MarketDataService
from app.market_data.subing_reference import subing_intraday_owner_segment_id
from app.reference_trading.forward_inputs import ForwardInputUnavailable


class ForwardMarketAuthority:
    def __init__(self, market_data: MarketDataService) -> None:
        self._market_data = market_data

    def owner_segments(
        self, identity: StreamIdentity, contract: str, trading_day: date,
        bar_end: datetime,
    ) -> tuple[str, str]:
        product = identity.product.lower()
        owner = self._market_data.dominant_segment_for_day(product, trading_day)
        if owner.contract != contract or owner.symbol != product:
            raise ForwardInputUnavailable("OWNER_IDENTITY_CONFLICT")
        windows = self._market_data.session_windows(
            symbol=product, trading_day=owner.start_trading_day,
        )
        owner_start = min(window.start for window in windows)
        if owner_start > bar_end:
            raise ForwardInputUnavailable("OWNER_IDENTITY_CONFLICT")
        code = identity.strategy_code.replace("-", "_")
        if code.startswith("newow_") and identity.frequency == "60m":
            owner_id = build_segment_id(product, contract, owner_start)
            return owner_id, build_calculation_segment_id(owner_id)
        if code == "subing_reference" and identity.frequency in {"15m", "30m", "60m"}:
            owner_id = subing_intraday_owner_segment_id(
                product, contract, owner.start_trading_day,
            )
            return owner_id, owner_id
        if code == "htdy" and identity.frequency == "15m":
            owner_id = f"htdy:{product}:{contract}:{owner_start.isoformat()}"
            return owner_id, owner_id
        raise ForwardInputUnavailable("FORWARD_OWNER_UNSUPPORTED")

    def expected_endpoints(
        self, identity: StreamIdentity, contract: str, trading_day: date,
        after: datetime | None, cutoff: datetime,
    ) -> tuple[datetime, ...]:
        product = identity.product.lower()
        owner = self._market_data.dominant_segment_for_day(product, trading_day)
        if owner.contract != contract:
            raise ForwardInputUnavailable("OWNER_IDENTITY_CONFLICT")
        pairs = self._market_data.expected_contract_replay_endpoints(
            symbol=product, contract=contract, frequency=identity.frequency,
            trading_day=trading_day, cutoff=cutoff, after=after,
            since=owner.start_trading_day,
        )
        return tuple(end for end, _day in pairs)
