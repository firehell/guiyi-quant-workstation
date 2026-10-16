"""Read-only, exact-window input adapter for new_subing_v1.

No provider calls, repair, writes, Live fallback, or consumer-local resolver.
confirmed_at=bar_end is an explicit retrospective completed-bar reconstruction,
not a claim about historical provider publication or natural detection time.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import re
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from app.market_data.actual_dominant_research import ActualDominantResearchSegmentLoader
from app.market_data.domain import BarFrequency, ContractTradingDayQuery, MarketSeriesResult
from guiyi_quant.paper import FeeSchedule

if TYPE_CHECKING:
    from app.market_data.market_data_service import MarketDataService
    from guiyi_quant.new_subing import ExecutionBar, StrategyBar

PRODUCTS = ('al', 'rb', 'ta')
SINCE = date(2024, 10, 14)
THROUGH = date(2026, 10, 9)
SHANGHAI = ZoneInfo('Asia/Shanghai')
REQUIRED_FREQUENCIES = (BarFrequency.M1, BarFrequency.M5, BarFrequency.M15, BarFrequency.D1)


class NewSubingInputError(ValueError):
    def __init__(self, code: str, *, diagnostic: dict[str, object] | None = None):
        self.code = code
        self.diagnostic = diagnostic or {}
        super().__init__(code)


def _wire(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        return {str(k): _wire(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_wire(v) for v in value]
    return value


def payload_hash(value: object) -> str:
    return sha256(json.dumps(_wire(value), ensure_ascii=False, sort_keys=True,
                             separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def safe_diagnostic(exc: Exception, *, product: str, stage: str) -> dict[str, object]:
    """Only typed public identities/counts; never exception text, SQL or paths."""
    code = getattr(exc, 'code', 'DATA_INSUFFICIENT')
    if not isinstance(code, str) or not code.replace('_', '').isalnum() or not code.isupper():
        code = 'DATA_INSUFFICIENT'
    result: dict[str, object] = {'symbol': product, 'stage': stage, 'code': code}
    reason = getattr(exc, 'reason', None)
    if isinstance(reason, str) and reason.replace('_', '').isalnum() and reason.isupper():
        result['reason'] = reason
    context = getattr(exc, 'context', None) or getattr(exc, 'diagnostic', None)
    if isinstance(context, Mapping):
        for key in ('symbol', 'contract', 'frequency', 'trading_day', 'cutoff', 'since',
                    'through', 'expected_count', 'actual_count', 'first_missing_endpoint'):
            if key in context and isinstance(context[key], (str, int, date, datetime)):
                result[key] = _wire(context[key])
    return result


def fact_decimal(value: object, *, positive: bool = False) -> Decimal:
    if not isinstance(value, str):
        raise NewSubingInputError('EXECUTION_FACTS_MISSING')
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise NewSubingInputError('EXECUTION_FACTS_MISSING') from None
    if not number.is_finite() or (number <= 0 if positive else number < 0):
        raise NewSubingInputError('EXECUTION_FACTS_MISSING')
    return number


def validate_series(result: MarketSeriesResult, *, product: str, contract: str,
                    frequency: BarFrequency, expected: Sequence[tuple[datetime, date]]) -> None:
    identity: dict[str, object] = {'symbol': product, 'series_kind': 'contract', 'contract': contract,
                'frequency': frequency.value}
    if any(result.request_identity.get(k) != v for k, v in identity.items()):
        raise NewSubingInputError('DATA_CONFLICT', diagnostic=identity)
    actual = tuple((bar.bar_end, bar.trading_day) for bar in result.bars)
    if actual != tuple(expected):
        missing = next((t for t in expected if t not in set(actual)), None)
        raise NewSubingInputError('DATA_INSUFFICIENT', diagnostic={**identity,
            'expected_count':len(expected), 'actual_count':len(actual),
            'first_missing_endpoint': missing[0].isoformat() if missing else None})
    if not actual or result.coverage != (actual[0][0], actual[-1][0]):
        raise NewSubingInputError('DATA_CONFLICT', diagnostic=identity)
    if any(right[0] <= left[0] for left, right in zip(actual, actual[1:])):
        raise NewSubingInputError('DATA_CONFLICT', diagnostic=identity)
    if any(bar.close <= 0 or bar.low <= 0 for bar in result.bars):
        raise NewSubingInputError('DATA_INSUFFICIENT', diagnostic=identity)


@dataclass(frozen=True)
class NewSubingInput:
    product: str
    since: date
    through: date
    bars_by_frequency: Mapping[str, tuple[StrategyBar, ...]]
    minute_bars: tuple[StrategyBar, ...]
    input_snapshot_hash: str
    diagnostics: Mapping[str, object]


def load_new_subing_inputs(market: MarketDataService, *, product: str,
                          since: date = SINCE, through: date = THROUGH) -> NewSubingInput:
    """MDS proves owners, lifecycle endpoint equality and Session identity."""
    from guiyi_quant.new_subing import StrategyBar

    if product not in PRODUCTS or type(since) is not date or type(through) is not date or since > through:
        raise NewSubingInputError('RESEARCH_QUERY_INVALID')
    stage = 'rank1_owners'
    context: dict[str, object] = {}
    try:
        owners = ActualDominantResearchSegmentLoader(market).owner_segments(
            symbol=product, since=since, through=through)
        by_frequency: dict[str, list[StrategyBar]] = {f.value: [] for f in (*REQUIRED_FREQUENCIES, BarFrequency.W1)}
        session_cache: dict[date, tuple] = {}
        context_gaps: list[dict[str, object]] = []
        source_evidence: list[dict[str, object]] = []

        def windows(day: date):
            if day not in session_cache:
                value = tuple(market.session_windows(symbol=product, trading_day=day))
                if not value or any(s.start >= s.end for s in value):
                    raise NewSubingInputError('DATA_INSUFFICIENT', diagnostic={
                        'symbol':product,'trading_day':day.isoformat(),'reason':'TRADING_SESSION_MISSING'})
                session_cache[day] = value
            return session_cache[day]

        for owner in owners:
            own_since, own_through = max(since, owner.start_trading_day), min(through, owner.end_trading_day)
            stage = 'session'
            cutoff = max(s.end for s in windows(own_through))
            for frequency in (*REQUIRED_FREQUENCIES, BarFrequency.W1):
                stage = 'execution_clock' if frequency is BarFrequency.M1 else 'physical_prefix'
                context = {'symbol':product,'contract':owner.contract,'frequency':frequency.value,
                           'since':own_since,'through':own_through}
                try:
                    expected = market.expected_contract_replay_endpoints(
                        symbol=product, contract=owner.contract, frequency=frequency,
                        trading_day=own_through, cutoff=cutoff,
                        since=own_since if frequency is BarFrequency.M1 else None)
                    if not expected:
                        raise NewSubingInputError('DATA_INSUFFICIENT', diagnostic=context)
                    result = market.query_contract_trading_days(ContractTradingDayQuery(
                        product,owner.contract,frequency,expected[0][1],own_through))
                    validate_series(result,product=product,contract=owner.contract,
                                    frequency=frequency,expected=expected)
                except Exception as exc:
                    if frequency is not BarFrequency.W1:
                        raise
                    # Weekly facts are optional context, never an implicit entry Gate.
                    context_gaps.append({**context,**safe_diagnostic(exc,product=product,stage='weekly_context')})
                    continue
                records = []
                for bar in result.bars:
                    day_windows = windows(bar.trading_day)
                    containing = [s for s in day_windows if s.start < bar.bar_end <= s.end]
                    if len(containing) != 1:
                        raise NewSubingInputError('DATA_CONFLICT', diagnostic=context)
                    session = containing[0]
                    def phase(s):
                        local = s.start.astimezone(SHANGHAI)
                        return 'night' if local.hour >= 18 or local.hour < 6 else 'day'
                    major_start = min(s.start for s in day_windows if phase(s)==phase(session))
                    close_at = max(s.end for s in day_windows)
                    record = [owner.contract,frequency.value,*_wire([
                        bar.bar_end,bar.trading_day,bar.open,bar.high,bar.low,bar.close,
                        bar.volume,bar.open_interest,major_start,close_at])]
                    source_id = payload_hash(record)
                    scoped = own_since <= bar.trading_day <= own_through
                    by_frequency[frequency.value].append(StrategyBar(
                        product=product,physical_contract=owner.contract,frequency=frequency.value,
                        bar_end=bar.bar_end,trading_day=bar.trading_day,open=bar.open,high=bar.high,
                        low=bar.low,close=bar.close,volume=bar.volume,open_interest=bar.open_interest,
                        source_identity=source_id,confirmed_at=bar.bar_end,
                        observation_eligible=scoped,session_open_at=major_start,session_close_at=close_at))
                    records.append(record)
                source_evidence.append({'contract':owner.contract,'frequency':frequency.value,
                    'owner_since':owner.start_trading_day,'owner_through':own_through,
                    'count':len(records),'records_hash':payload_hash(records),
                    'request_identity':result.request_identity})
        frozen = {k:tuple(sorted(v,key=lambda b:(b.bar_end,b.physical_contract))) for k,v in by_frequency.items()}
        minute_bars = tuple(b for b in frozen['1m'] if b.observation_eligible)
        if not minute_bars or minute_bars[0].trading_day != since or minute_bars[-1].trading_day != through:
            raise NewSubingInputError('DATA_INSUFFICIENT',diagnostic={'symbol':product,'since':since,'through':through})
        identity = {'product':product,'since':since,'through':through,'sources':source_evidence}
        return NewSubingInput(product,since,through,frozen,minute_bars,payload_hash(identity),{
            'input_counts':{**{k:len(v) for k,v in frozen.items()},'1m':len(minute_bars)},
            'weekly_context_gaps':context_gaps,'time_model':'retrospective_completed_bar_reconstruction',
            'source_evidence':_wire(source_evidence)})
    except NewSubingInputError as exc:
        raise NewSubingInputError(exc.code,diagnostic={**context,**safe_diagnostic(exc,product=product,stage=stage)}) from None
    except Exception as exc:
        raise NewSubingInputError('DATA_INSUFFICIENT',diagnostic={**context,**safe_diagnostic(exc,product=product,stage=stage)}) from None


def load_execution_facts(raw: Mapping[str, object] | None, *, product: str,
                         bars: Sequence[StrategyBar]) -> tuple[tuple[ExecutionBar, ...], str]:
    """Exact dated provider snapshots; no inferred tick/margin/fee defaults."""
    if not raw or not bars:
        raise NewSubingInputError('EXECUTION_FACTS_MISSING')
    from guiyi_quant.new_subing import ExecutionBar, ExecutionFacts

    try:
        if raw['schema_version'] != 1 or raw['source'] != 'rqdata':
            raise ValueError
        plan_hash = raw.get('plan_hash')
        if not isinstance(plan_hash, str) or not re.fullmatch(r'[0-9a-f]{64}', plan_hash):
            raise ValueError
        captured_at = datetime.fromisoformat(str(raw['captured_at']))
        if captured_at.tzinfo is None or captured_at > datetime.now(UTC):
            raise ValueError
        contracts = raw['contracts']
        if not isinstance(contracts, dict) or set(contracts) != {b.physical_contract for b in bars}:
            raise ValueError
        snapshot_hash = payload_hash(raw)
        required: dict[str,set[date]] = {}
        for bar in bars:
            required.setdefault(bar.physical_contract,set()).add(bar.trading_day)
        facts = {}
        for contract, days in required.items():
            body = contracts[contract]
            instrument = body['instrument']
            if instrument.get('order_book_id') != contract or not contract.startswith(product.upper()):
                raise ValueError
            tick = fact_decimal(instrument['tick_size'],positive=True)
            multiplier = fact_decimal(instrument['contract_multiplier'],positive=True)
            parameters, daily = body['parameters'], body['daily']
            p_by_day = {date.fromisoformat(p['date']):p for p in parameters}
            d_by_day = {date.fromisoformat(p['date']):p for p in daily}
            if len(p_by_day)!=len(parameters) or len(d_by_day)!=len(daily) or set(p_by_day)!=days or set(d_by_day)!=days:
                raise ValueError
            for day in days:
                p,d = p_by_day[day],d_by_day[day]
                for key in ('long_margin_ratio', 'short_margin_ratio'):
                    if fact_decimal(p[key], positive=True) > 1:
                        raise ValueError
                if p['commission_type'] not in ('by_money','by_volume'):
                    raise ValueError
                money = p['commission_type']=='by_money'
                fee_values = [fact_decimal(p[k]) for k in ('open_commission','close_commission','close_commission_today')]
                source_id = payload_hash([snapshot_hash,contract,day])
                pairs = [(n,Decimal('0')) if money else (Decimal('0'),n) for n in fee_values]
                fees = FeeSchedule(open_rate=pairs[0][0], open_per_contract=pairs[0][1],
                    close_rate=pairs[1][0], close_per_contract=pairs[1][1],
                    close_today_rate=pairs[2][0], close_today_per_contract=pairs[2][1],
                    source_id=source_id)
                facts[(contract,day)] = ExecutionFacts(
                    physical_contract=contract,trading_day=day,tick_size=tick,multiplier=multiplier,
                    prev_settlement=fact_decimal(d['prev_settlement'],positive=True),
                    long_margin_ratio=fact_decimal(p['long_margin_ratio'],positive=True),
                    short_margin_ratio=fact_decimal(p['short_margin_ratio'],positive=True),
                    limit_up=fact_decimal(d['limit_up'],positive=True),
                    limit_down=fact_decimal(d['limit_down'],positive=True),fees=fees,source_id=source_id)
        return tuple(ExecutionBar(bar=b,facts=facts[(b.physical_contract,b.trading_day)]) for b in bars),snapshot_hash
    except (KeyError,TypeError,AttributeError,ValueError,InvalidOperation):
        raise NewSubingInputError('EXECUTION_FACTS_MISSING',diagnostic={'symbol':product}) from None
