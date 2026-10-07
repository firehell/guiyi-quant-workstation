"""One owner-approved historical source exception; never a generic OHLC repair."""
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pandas as pd

from app.market_data.domain import BarFrequency, CanonicalBar, ContractError, DatasetKey, DatasetKind

RULE_ID = 'pp2405-20230608T210300-high-equals-open-v1'
BAR_END = datetime(2023, 6, 8, 13, 3, tzinfo=UTC)
TRADING_DAY = date(2023, 6, 9)
_ORIGINAL = {'open': '6910', 'high': '6890', 'low': '6890', 'close': '6890', 'volume': '1', 'turnover': '34525', 'open_interest': '1684'}
_CORRECTED = {**_ORIGINAL, 'high': '6910'}

def correct_approved_minute_row(row: dict[str, Any], key: DatasetKey, bar_end: datetime, trading_day: date) -> dict[str, Any]:
    if key.kind is not DatasetKind.CONTRACT or key.symbol != 'pp' or key.series_or_contract != 'PP2405' or key.frequency is not BarFrequency.M1 or bar_end != BAR_END:
        return row
    if trading_day != TRADING_DAY or row.get('order_book_id') != 'PP2405':
        raise ContractError(field='approved_local_correction', reason='source_preimage_mismatch')
    try:
        raw_end = pd.Timestamp(row.get('datetime', row.get('index')))
        if pd.isna(raw_end) or raw_end.nanosecond != 0:
            raise ValueError('timestamp_precision_mismatch')
        raw_end = raw_end.tz_localize('Asia/Shanghai') if raw_end.tzinfo is None else raw_end
        if raw_end.tz_convert('UTC') != pd.Timestamp(BAR_END):
            raise ValueError('timestamp_mismatch')
        values = {field: Decimal(str(row[field])) for field in _ORIGINAL if field != 'turnover'}
        supplied = [Decimal(str(row[field])) for field in ('turnover', 'total_turnover', 'amount') if field in row and row[field] is not None]
        if not supplied or any(value != supplied[0] for value in supplied):
            raise ValueError('alias_mismatch')
        values['turnover'] = supplied[0]
        oi_aliases = [Decimal(str(row[field])) for field in ('open_interest', 'open_oi', 'close_oi') if field in row]
        if any(value != values['open_interest'] for value in oi_aliases):
            raise ValueError('open_interest_alias_mismatch')
        original = {field: Decimal(value) for field, value in _ORIGINAL.items()}
        corrected = {field: Decimal(value) for field, value in _CORRECTED.items()}
        if values == corrected:
            return row
        if values != original:
            raise ValueError('value_mismatch')
    except (KeyError, ValueError, ArithmeticError) as exc:
        raise ContractError(field='approved_local_correction', reason='source_preimage_mismatch') from exc
    return {**row, 'high': Decimal('6910')}

def approved_policy_for_partition(key: DatasetKey, bars: tuple[CanonicalBar, ...]) -> dict[str, Any] | None:
    if key.kind is not DatasetKind.CONTRACT or key.symbol != 'pp' or key.series_or_contract != 'PP2405' or key.frequency is not BarFrequency.M1:
        return None
    matches = [bar for bar in bars if bar.bar_end == BAR_END]
    if not matches:
        return None
    bar = matches[0]
    if bar.trading_day != TRADING_DAY or any(getattr(bar, field) != Decimal(value) for field, value in _CORRECTED.items()):
        raise ContractError(field='approved_local_correction', reason='canonical_policy_mismatch')
    return {'rule_id': RULE_ID, 'authority': 'owner_approved_local_correction', 'approved_on': '2026-10-08', 'contract': 'PP2405', 'bar_end': BAR_END.isoformat(), 'trading_day': TRADING_DAY.isoformat(), 'original': dict(_ORIGINAL), 'corrected': dict(_CORRECTED), 'provider_confirmed': False, 'raw_response_sha256': 'cca15848ed35479e39fb848c2dba0c3723ddeea857ac1d7be7ab767d21b01cb5', 'note': 'Approved policy for this canonical row; upstream response may already match corrected values.'}
