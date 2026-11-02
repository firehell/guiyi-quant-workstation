"""Read-only chart window from a fixed, fully validated physical lifecycle prefix."""
from dataclasses import asdict, replace
from datetime import datetime
from decimal import Decimal
from typing import Callable

from guiyi_quant.indicators import subing_range, subing_trend
from .domain import BarFrequency, ContractTradingDayQuery, SeriesPageQuery, SeriesKind
from .new_subing_research import payload_hash, validate_series


class DynamicRangeError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def chart_window(market, *, symbol: str, contract: str, frequency: str,
                 start: datetime, end: datetime, check: Callable[[], None] = lambda: None) -> dict:
    if frequency not in ('30m', '1d'):
        raise DynamicRangeError('DYNAMIC_RANGE_FREQUENCY_UNSUPPORTED')
    if any(t.tzinfo is None or t.utcoffset() is None for t in (start, end)) or start > end:
        raise DynamicRangeError('DYNAMIC_RANGE_WINDOW_INVALID')
    query = SeriesPageQuery(SeriesKind.CONTRACT, symbol, BarFrequency(frequency),
                            end, 1, contract)
    symbol, contract = query.symbol, query.contract
    check()
    source = market.contract_source_evidence(symbol=symbol, contract=contract,
        frequency=query.frequency, before=end)
    tail = market.query_page_inclusive(query)
    if not tail.bars or tail.bars[-1].bar_end != end:
        raise DynamicRangeError('DYNAMIC_RANGE_CANONICAL_ENDPOINT_MISSING')
    day = tail.bars[-1].trading_day
    expected = market.expected_contract_replay_endpoints(symbol=symbol, contract=contract,
        frequency=query.frequency, trading_day=day, cutoff=end)
    if not expected or len(expected) > 30000:
        raise DynamicRangeError('DYNAMIC_RANGE_PREFIX_UNAVAILABLE')
    visible = [t for t, _ in expected if t >= start]
    if not visible or visible[0] != start or visible[-1] != end or len(visible) > 2000:
        raise DynamicRangeError('DYNAMIC_RANGE_WINDOW_INVALID')
    check()
    result = market.query_contract_trading_days(ContractTradingDayQuery(
        symbol, contract, query.frequency, expected[0][1], day))
    if result.bars and result.coverage != (result.bars[0].bar_end, result.bars[-1].bar_end):
        raise DynamicRangeError('DYNAMIC_RANGE_COVERAGE_INVALID')
    # Read a complete authoritative trading day, but never evaluate its future suffix.
    bars = tuple(b for b in result.bars if b.bar_end <= end)
    result = replace(result, bars=bars, coverage=(bars[0].bar_end, bars[-1].bar_end) if bars else None)
    validate_series(result, product=symbol, contract=contract, frequency=query.frequency, expected=expected)
    trend = subing_trend.initial_state(contract, frequency)
    state = subing_range.initial_state(contract, frequency)
    points = []
    for index, bar in enumerate(bars):
        if index % 128 == 0:
            check()
        trend, tp = subing_trend.step(trend, contract=contract, frequency=frequency,
            bar_end=bar.bar_end, high=float(bar.high), low=float(bar.low), close=float(bar.close))
        state, point = subing_range.step(state, contract=contract, frequency=frequency,
            bar_end=bar.bar_end, high=bar.high, low=bar.low, close=bar.close,
            atr=Decimal(str(tp.atr14)) if tp.atr14 is not None else None, trend_direction=tp.direction)
        if bar.bar_end >= start:
            points.append(dict(time=bar.bar_end.isoformat(), contract=contract,
                open=bar.open, high=bar.high, low=bar.low, close=bar.close,
                **{k: v for k, v in asdict(point).items() if k != 'at'}))
    check()
    if source != market.contract_source_evidence(symbol=symbol, contract=contract,
            frequency=query.frequency, before=end):
        raise DynamicRangeError('DYNAMIC_RANGE_SOURCE_CHANGED')
    check()
    return dict(version=subing_range.VERSION, trend_version=subing_trend.VERSION,
        profile='bounded_confirmed', source_proof=dict(
            lifecycle_hash=payload_hash({k: source[k] for k in ('contract','frequency','listed_date','expired_date')}),
            partitions={f"{p['year']}-{p['month']}": payload_hash(p) for p in source['partitions']}),
        symbol=symbol, contract=contract, frequency=frequency,
        prefix_start=bars[0].bar_end, source_hash=payload_hash(source), points=points)
