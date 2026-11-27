"""Validation and deterministic identities for historical market inputs."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import re
from typing import Any

from app.market_data.domain import BarFrequency, MarketSeriesResult
from guiyi_quant.paper import FeeSchedule
from guiyi_quant.subing_inputs import ExecutionBar, ExecutionFacts, StrategyBar


class ResearchInputError(ValueError):
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
        raise ResearchInputError('EXECUTION_FACTS_MISSING')
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise ResearchInputError('EXECUTION_FACTS_MISSING') from None
    if not number.is_finite() or (number <= 0 if positive else number < 0):
        raise ResearchInputError('EXECUTION_FACTS_MISSING')
    return number


def validate_series(result: MarketSeriesResult, *, product: str, contract: str,
                    frequency: BarFrequency, expected: Sequence[tuple[datetime, date]],
                    allow_daily_no_trade: bool = False) -> None:
    identity: dict[str, object] = {'symbol': product, 'series_kind': 'contract', 'contract': contract,
                'frequency': frequency.value}
    if any(result.request_identity.get(k) != v for k, v in identity.items()):
        raise ResearchInputError('DATA_CONFLICT', diagnostic=identity)
    actual = tuple((bar.bar_end, bar.trading_day) for bar in result.bars)
    if actual != tuple(expected):
        missing = next((t for t in expected if t not in set(actual)), None)
        raise ResearchInputError('DATA_INSUFFICIENT', diagnostic={**identity,
            'expected_count':len(expected), 'actual_count':len(actual),
            'first_missing_endpoint': missing[0].isoformat() if missing else None})
    if not actual or result.coverage != (actual[0][0], actual[-1][0]):
        raise ResearchInputError('DATA_CONFLICT', diagnostic=identity)
    if any(right[0] <= left[0] for left, right in zip(actual, actual[1:])):
        raise ResearchInputError('DATA_CONFLICT', diagnostic=identity)
    priced = result.bars
    if allow_daily_no_trade and frequency is BarFrequency.D1:
        priced = tuple(bar for bar in priced if not bar.is_strict_no_trade)
    if not priced or any(bar.close <= 0 or bar.low <= 0 for bar in priced):
        raise ResearchInputError('DATA_INSUFFICIENT', diagnostic=identity)


def load_execution_facts(raw: Mapping[str, object] | None, *, product: str,
                         bars: Sequence[StrategyBar]) -> tuple[tuple[ExecutionBar, ...], str]:
    """Exact dated provider snapshots; no inferred tick/margin/fee defaults."""
    if not raw or not bars:
        raise ResearchInputError('EXECUTION_FACTS_MISSING')
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
        raise ResearchInputError('EXECUTION_FACTS_MISSING',diagnostic={'symbol':product}) from None
