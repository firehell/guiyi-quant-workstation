"""Explicit offline seam from validated HTDY observations to execution policy.

Not registered with Alert, the API, workers or launchd. A future runtime must
provide the latest native completed observation and its original receipt time;
historical reconstruction or recovered/backfilled windows are not first-seen.
"""

from datetime import datetime
from hashlib import sha256
import json

from app.alerts.evaluators import HtdyOriginalEvaluator
from app.market_data.market_read_service import MarketReadService, MarketReadWindow
from guiyi_quant.htdy_execution import AccountSnapshot, Signal, State, start
from guiyi_quant.reference_trading.htdy import CONTEXT_BARS


def start_operational(account_id: str, at: datetime, snapshot: AccountSnapshot) -> State:
    from app.market_data.operational_universe import load_operational_products

    return start(account_id, tuple(p.upper() for p in load_operational_products()), at, snapshot)


def signal_from_window(
    market_read: MarketReadService, window: MarketReadWindow, *, source_id: str, observed_at: datetime,
) -> Signal:
    if (type(window) is not MarketReadWindow or window.frequency != "60m"
            or len(window.bars) != CONTEXT_BARS):
        raise ValueError("HTDY_EXECUTION_REQUIRES_60M_WINDOW32")
    if not window.notification_eligible:
        raise ValueError("HTDY_EXECUTION_REQUIRES_FIRST_SEEN")
    candidates = HtdyOriginalEvaluator().evaluate_candidates(market_read, window)
    directions = candidates[0].observation_types if candidates else ()
    payload = [{
        "bar_end": bar.bar_end.isoformat(), "trading_day": bar.trading_day.isoformat(),
        "contract": contract, "open": str(bar.open), "high": str(bar.high),
        "low": str(bar.low), "close": str(bar.close), "volume": str(bar.volume),
        "turnover": str(bar.turnover), "open_interest": str(bar.open_interest),
    } for bar, contract in zip(window.bars, window.bar_contracts, strict=True)]
    digest = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return Signal(source_id, window.symbol.upper(), window.contract, window.cutoff,
                  observed_at, window.bars[-2].bar_end, directions, digest)
