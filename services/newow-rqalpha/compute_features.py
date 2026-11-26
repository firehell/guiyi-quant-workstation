"""Apply Quant Core to a proven RQAlpha research packet without a Market dependency."""

from datetime import datetime
from itertools import chain
from re import fullmatch

from guiyi_quant.compute import (
    REGISTRY,
    BarSeries,
    CompletedBar,
    FeatureRequest,
    FeatureResult,
    SeriesIdentity,
)

from frozen_market import FrozenMarket


def completed_minute_features(
    market: FrozenMarket,
    requests: tuple[FeatureRequest, ...],
    *,
    source_sha256: str,
    as_of: datetime,
) -> tuple[FeatureResult, ...]:
    """Read research features on the packet's event-time clock.

    Replay already verifies minute coverage and exact Session ownership. Results
    here are analyst inputs. Order timing remains under the existing replay policy.
    """
    if fullmatch(r"[0-9a-f]{64}", source_sha256) is None:
        raise ValueError("RQALPHA_SOURCE_DIGEST_INVALID")
    product = market.contract.rstrip("0123456789").lower()
    segment = f"rqalpha:{market.contract}:{market.window_start}:{market.window_end}"
    identity = SeriesIdentity(product, market.contract, segment, "1m", source_sha256)
    session_ids = chain.from_iterable(
        (session.start.isoformat() for _ in session.minute_ends()) for session in market.sessions
    )
    bars = tuple(
        CompletedBar(
            market.contract, segment, minute.day, session_id, minute.end, minute.end, minute.end,
            float(minute.open), float(minute.high), float(minute.low), float(minute.close),
            float(minute.volume), "VALID",
        )
        for minute, session_id in zip(market.minutes, session_ids, strict=True)
    )
    return REGISTRY.calculate(BarSeries(identity, bars), requests, as_of=as_of, use="backtest")
