"""Exact physical-prefix MDS inputs for independent futures research; no provider I/O."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
import re
from types import MappingProxyType

from app.market_data.actual_dominant_research import ActualDominantResearchSegmentLoader
from app.market_data.domain import BarFrequency, ContractTradingDayQuery
from app.market_data.new_subing_research import (
    NewSubingInputError, fact_decimal, payload_hash, safe_diagnostic, validate_series,
    load_execution_facts as _load_execution_facts,
)
from guiyi_quant.newow_futures.contracts import Bar, ExecutionBar, PRODUCTS

SINCE = date(2024, 10, 14)
THROUGH = date(2026, 10, 19)
FREQUENCIES = tuple(BarFrequency)
NewowFuturesInputError = NewSubingInputError


@dataclass(frozen=True)
class NewowFuturesInput:
    product: str
    since: date
    through: date
    bars_by_frequency: Mapping[str, tuple[Bar, ...]]
    minute_bars: tuple[Bar, ...]
    input_snapshot_hash: str
    diagnostics: Mapping[str, object]
    gaps_by_frequency: Mapping[str, tuple[dict, ...]]


def load_newow_futures_inputs(market, *, product: str,
                             since: date = SINCE, through: date = THROUGH) -> NewowFuturesInput:
    """MDS owns rank1, endpoints, sessions, quality and canonical physical reads.

    Each physical prefix is all-or-nothing. Missing frequencies are retained as
    explicit gaps; they never shorten another frequency or the requested window.
    """
    if product not in PRODUCTS or type(since) is not date or type(through) is not date or since > through:
        raise NewowFuturesInputError('RESEARCH_QUERY_INVALID')
    try:
        owners = ActualDominantResearchSegmentLoader(market).owner_segments(
            symbol=product, since=since, through=through)
    except Exception as exc:
        raise NewowFuturesInputError('DATA_INSUFFICIENT', diagnostic=safe_diagnostic(
            exc, product=product, stage='rank1_owners')) from None
    values: dict[str, list[Bar]] = {f.value: [] for f in FREQUENCIES}
    gaps: dict[str, list[dict]] = {f.value: [] for f in FREQUENCIES}
    evidence = []
    sessions = {}

    def windows(day):
        if day not in sessions:
            result = tuple(market.session_windows(symbol=product, trading_day=day))
            if not result or any(s.start >= s.end for s in result):
                raise NewowFuturesInputError('DATA_INSUFFICIENT', diagnostic={
                    'trading_day':day, 'reason':'TRADING_SESSION_MISSING'})
            if any(a.end > b.start for a,b in zip(result,result[1:])):
                raise NewowFuturesInputError('DATA_CONFLICT')
            sessions[day] = result
        return sessions[day]

    for owner in owners:
        own_since, own_through = max(since, owner.start_trading_day), min(through, owner.end_trading_day)
        # One identity across frequencies, independent of frequency-specific hashes.
        owner_id = payload_hash([product, owner.contract, owner.start_trading_day, owner.end_trading_day])
        calculation_id = payload_hash(['mds_exact_physical_prefix_v1', owner_id])
        for frequency in FREQUENCIES:
            context = {'symbol':product, 'contract':owner.contract, 'frequency':frequency.value,
                       'since':own_since.isoformat(), 'through':own_through.isoformat()}
            try:
                cutoff = max(s.end for s in windows(own_through))
                expected = market.expected_contract_replay_endpoints(
                    symbol=product, contract=owner.contract, frequency=frequency,
                    trading_day=own_through, cutoff=cutoff,
                    since=own_since if frequency is BarFrequency.M1 else None)
                if not expected:
                    raise NewowFuturesInputError('DATA_INSUFFICIENT')
                result = market.query_contract_trading_days(ContractTradingDayQuery(
                    product, owner.contract, frequency, expected[0][1], own_through))
                validate_series(result, product=product, contract=owner.contract,
                                frequency=frequency, expected=expected)
                records, converted = [], []
                for bar in result.bars:
                    day_windows = windows(bar.trading_day)
                    containing = [s for s in day_windows if s.start < bar.bar_end <= s.end]
                    if len(containing) != 1:
                        raise NewowFuturesInputError('DATA_CONFLICT')
                    record = [owner_id, frequency.value, bar.bar_end, bar.trading_day,
                              bar.open, bar.high, bar.low, bar.close, bar.volume,
                              bar.open_interest, containing[0].start, max(s.end for s in day_windows)]
                    converted.append(Bar(
                        product=product, physical_contract=owner.contract, frequency=frequency.value,
                        bar_end=bar.bar_end, trading_day=bar.trading_day, open=bar.open,
                        high=bar.high, low=bar.low, close=bar.close, volume=bar.volume,
                        source_identity=payload_hash(record), confirmed_at=bar.bar_end,
                        observation_eligible=own_since <= bar.trading_day <= own_through,
                        open_interest=bar.open_interest, session_open_at=containing[0].start,
                        session_close_at=max(s.end for s in day_windows),
                        owner_segment_id=owner_id, calculation_segment_id=calculation_id))
                    records.append(record)
                values[frequency.value].extend(converted)
                evidence.append({**context, 'owner_segment_id':owner_id,
                    'calculation_segment_id':calculation_id, 'count':len(records),
                    'records_hash':payload_hash(records), 'request_identity':dict(result.request_identity)})
            except Exception as exc:
                gaps[frequency.value].append({**context, **safe_diagnostic(
                    exc, product=product, stage='exact_physical_prefix')})
    frozen = {f:tuple(sorted(bars,key=lambda b:(b.bar_end,b.owner))) for f,bars in values.items()}
    minute = tuple(b for b in frozen['1m'] if b.observation_eligible)
    complete = not gaps['1m'] and bool(minute)
    gap_wire = {f:tuple(rows) for f,rows in gaps.items()}
    identity = {'product':product, 'since':since, 'through':through,
                'sources':evidence, 'gaps_by_frequency':gap_wire}
    return NewowFuturesInput(product,since,through,MappingProxyType(frozen),minute,
        payload_hash(identity),MappingProxyType({
            'input_counts':{f:len(rows) for f,rows in frozen.items()},
            'minute_complete':complete, 'source_evidence':evidence,
            'time_model':'retrospective_completed_bar_reconstruction'}),MappingProxyType(gap_wire))


def load_execution_facts(raw: Mapping[str, object] | None, *, product: str,
                         bars: Sequence[Bar]) -> tuple[tuple[ExecutionBar, ...], str]:
    executions, snapshot_hash = _load_execution_facts(raw, product=product, bars=bars)
    return tuple(ExecutionBar(item.bar,item.facts) for item in executions),snapshot_hash


def load_reference_ticks(raw: Mapping[str, object] | None, *, product: str,
                         bars: Sequence[Bar]) -> dict[tuple[str,date],Decimal]:
    """Provider instrument identity survives partial fee coverage; never guess a tick."""
    try:
        if not raw or raw['schema_version'] != 1 or raw['source'] != 'rqdata':
            raise ValueError()
        if not re.fullmatch(r'[0-9a-f]{64}', str(raw['plan_hash'])):
            raise ValueError()
        captured = datetime.fromisoformat(str(raw['captured_at']))
        if captured.tzinfo is None or captured > datetime.now(UTC):
            raise ValueError()
        contracts = raw['contracts']
        result = {}
        for bar in bars:
            contract = bar.physical_contract
            if not re.fullmatch(product.upper()+r'\d{3,4}', contract):
                raise ValueError()
            instrument = contracts[contract]['instrument']
            if instrument['order_book_id'] != contract:
                raise ValueError()
            result[(contract,bar.trading_day)] = fact_decimal(instrument['tick_size'],positive=True)
        if not result:
            raise ValueError()
        return result
    except (KeyError,TypeError,AttributeError,ValueError):
        raise NewowFuturesInputError('EXECUTION_FACTS_MISSING') from None
