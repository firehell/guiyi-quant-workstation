"""Historical single-contract features and same-session price observations."""

from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal

from app.backtest_center.codec import digest
from app.db.readonly import readonly_transaction
from app.market_data.catalog import MarketCatalog
from app.market_data.composition import canonical_root
from app.market_data.domain import BarFrequency, ContractTradingDayQuery, canonical_bar_source_sha256
from app.market_data.market_data_service import MarketDataService
from app.market_data.storage import CanonicalMonthlyStore
from app.research_center.inputs import ResearchError
from guiyi_quant.compute import REGISTRY, BarSeries, CompletedBar, FeatureRequest, SeriesIdentity


def market_input(db, requested, kind):
    query = ContractTradingDayQuery(
        requested.product, requested.contract, BarFrequency(requested.frequency), requested.since, requested.through
    )
    root = canonical_root()
    with readonly_transaction(db, timeout_seconds=8):
        market = MarketDataService(MarketCatalog(db, root), CanonicalMonthlyStore(root))
        result = market.query_contract_trading_days(query)
        if result.requested_trading_day_window != (query.since, query.through):
            raise ResearchError("MARKET_WINDOW_OUTSIDE_CONTRACT")
        if not result.bars or len(result.bars) > 8_000:
            raise ResearchError("MARKET_SAMPLE_BUDGET_OR_COVERAGE")
        windows = {day: market.session_windows(symbol=query.symbol, trading_day=day)
                   for day in {bar.trading_day for bar in result.bars}}
    bars = result.bars
    if bars[-1].bar_end > datetime.now(UTC) or any(bar.is_strict_no_trade or min(bar.low, bar.open, bar.close) <= 0 for bar in bars):
        raise ResearchError("COMPLETED_VALID_BARS_REQUIRED")
    revision = digest([canonical_bar_source_sha256(bar) for bar in bars])
    segment = f"physical:{query.contract}"
    completed = []
    for bar in bars:
        sessions = [window for window in windows[bar.trading_day] if window.start < bar.bar_end <= window.end]
        if len(sessions) != 1:
            raise ResearchError("MARKET_SESSION_UNPROVEN")
        completed.append(CompletedBar(
            query.contract, segment, bar.trading_day, sessions[0].start.isoformat(),
            bar.bar_end, bar.bar_end, bar.bar_end, float(bar.open), float(bar.high), float(bar.low),
            float(bar.close), float(bar.volume), "VALID",
        ))
    identity = SeriesIdentity(query.symbol, query.contract, segment, query.frequency.value, revision)
    feature_id = requested.feature if kind == "factor" else "breakout"
    series, = REGISTRY.calculate(
        BarSeries(identity, tuple(completed)), [FeatureRequest(feature_id)],
        as_of=completed[-1].available_at, use="research",
    )
    markers = {marker.confirmation_bar_end: marker for marker in series.markers}
    samples, excluded = [], Counter()
    for index, (bar, point) in enumerate(zip(bars, series.points, strict=True)):
        marker = markers.get(bar.bar_end) if kind == "event" else None
        if kind == "event" and marker is None:
            continue
        if not point.values:
            excluded[str(point.status)] += 1
            continue
        anchor = index + (3 if kind == "event" else 0)
        first, last = anchor + 1, anchor + 2
        if last >= len(bars) or completed[last].session_id != completed[index].session_id:
            excluded["LABEL_WINDOW_UNAVAILABLE"] += 1
            continue
        target = bars[last].close / bars[first].open - Decimal(1)
        row = {
            "at": bar.bar_end.isoformat(), "trading_day": bar.trading_day.isoformat(),
            "signal_available_at": point.available_at.isoformat(),
            "available_at": completed[anchor].available_at.isoformat(),
            "session_id": completed[index].session_id, "anchor_at": bars[anchor].bar_end.isoformat(),
            "label_available_at": bars[last].bar_end.isoformat(),
            "label": str(target), "label_open": str(bars[first].open), "label_close": str(bars[last].close),
        }
        if marker:
            direction = 1 if marker.kind == "breakout" else -1
            level = Decimal(str(marker.price))
            row.update(
                event=marker.kind, threshold=str(level), label=str(target * direction),
                confirmed=all((candidate.close - level) * direction > 0 for candidate in bars[index + 1:anchor + 1]),
            )
        else:
            feature_key = {"trend_direction": "atr_normalized_slope", "macd": "histogram"}.get(feature_id, "value")
            value = float(point.values[feature_key])
            if feature_id in ("atr", "stddev", "macd"):
                value /= float(bar.close)
            if feature_id.startswith("ema"):
                value = float(bar.close) / value - 1
            row["feature"] = value
        samples.append(row)
    return {
        "source": {"kind": kind, "product": query.symbol, "contract": query.contract, "frequency": query.frequency.value,
                   "since": query.since.isoformat(), "through": query.through.isoformat(),
                   "data_revision": revision, "segment": segment, "feature": feature_id,
                   "formula_version": series.identity.formula_version},
        "policy": {"version": "same_session_price_observation_v1", "clock": "canonical_completed_bar_end",
                   "executable": False, "confirmation_bars": 3 if kind == "event" else 0,
                   "label_horizon_bars": 2},
        "coverage": {"bars": len(bars), "samples": len(samples), "excluded": dict(excluded)},
        "trading_days": sorted({bar.trading_day.isoformat() for bar in bars}),
        "samples": samples,
    }
