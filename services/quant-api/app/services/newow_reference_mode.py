"""Explicit opt-in for the isolated disk/DB-backed Newow reference deployment."""

import os
from urllib.parse import urlsplit


def market_foundation_isolated() -> bool:
    return os.getenv("GUIYI_NEWOW_REFERENCE_MODE") == "market_foundation_isolated"


def after_market_only() -> bool:
    return os.getenv("GUIYI_NEWOW_REFERENCE_MODE") == "after_market_isolated" or market_foundation_isolated()

def market_reference_receipts_only() -> bool:
    from app.market_data.market_foundation_scope import formal_tick_requested

    return after_market_only() or formal_tick_requested()


def require_isolated_redis(url: str) -> None:
    try:
        address = urlsplit(url)
        if (address.scheme == "redis" and address.hostname == "127.0.0.1"
                and address.port not in (None, 6379) and not address.query and not address.fragment):
            return
    except ValueError:
        pass
    raise ValueError("BACKTEST_ISOLATED_REDIS_REQUIRED")
