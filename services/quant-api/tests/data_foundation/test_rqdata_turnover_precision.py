from datetime import UTC, date, datetime
from decimal import Decimal, Inexact, Rounded, localcontext

import pyarrow as pa
import pytest

from app.market_data import rqdata_adapter as adapter
from app.market_data.errors import InfrastructureError
from app.market_data.storage import CANONICAL_SCHEMA


END = datetime(2022, 4, 1, 7, tzinfo=UTC)
DAY = date(2022, 4, 1)


def row(turnover):
    return dict(open='100', high='100', low='100', close='100', volume='1',
                turnover=turnover, open_interest='2')


def test_observed_sc_turnover_is_truncated_and_schema_readable():
    bar = adapter._canonical_bar(row('1.1641532182693481E-10'), END, DAY)
    assert bar.turnover == Decimal('0.000000000116415321')
    pa.Table.from_pylist([dict(bar_end=bar.bar_end, trading_day=bar.trading_day,
                             **{name: getattr(bar, name) for name in
                                ('open', 'high', 'low', 'close', 'volume', 'turnover', 'open_interest')})],
                        schema=CANONICAL_SCHEMA)


@pytest.mark.parametrize('value', [None, '0', '12345678901234567890', '1.123456789012345678', '1.2300'])
def test_existing_turnover_is_unchanged(value):
    expected = None if value is None else Decimal(value)
    actual = adapter._canonical_bar(row(value), END, DAY).turnover
    assert actual == expected
    if actual is not None:
        assert actual.as_tuple() == expected.as_tuple()


def test_turnover_policy_is_independent_of_decimal_context():
    with localcontext() as context:
        context.prec = 2
        context.Emax = 9
        context.Emin = -9
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        actual = adapter._canonical_bar(row('12345678901234567890.123456789012345678999'), END, DAY)
    assert actual.turnover == Decimal('12345678901234567890.123456789012345678')


@pytest.mark.parametrize('value', ['-1E-50', '-1', 'NaN', 'sNaN', 'Infinity', '-Infinity', float('inf')])
def test_invalid_turnover_is_rejected_before_truncation(value):
    with pytest.raises(InfrastructureError):
        adapter._canonical_bar(row(value), END, DAY)


def test_weekly_normalizes_each_day_before_exact_sum():
    rows = tuple((date(2022, 4, day), row('0.0000000000000000009')) for day in (1, 2))
    with localcontext() as context:
        context.prec = 2
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        bar = adapter._aggregate_daily_rows(rows, bar_end=END)
    assert bar.turnover == 0  # Truncating the raw sum would incorrectly produce 1E-18.
    assert bar.volume == 2


@pytest.mark.parametrize('value', ['-1E-50', 'NaN', 'Infinity'])
def test_weekly_invalid_daily_turnover_cannot_cancel_or_disappear(value):
    rows = ((DAY, row(value)), (date(2022, 4, 2), row('1')))
    with pytest.raises(InfrastructureError):
        adapter._aggregate_daily_rows(rows, bar_end=END)


@pytest.mark.parametrize('field', ['open', 'high', 'low', 'close', 'volume', 'open_interest'])
def test_other_fields_remain_exact_and_high_precision_fails_schema(field):
    source = row('1')
    source[field] = '100.0000000000000000001' if field in ('open', 'high', 'low', 'close') else '1.0000000000000000001'
    if field in ('open', 'high', 'low', 'close'):
        source.update({name: source[field] for name in ('open', 'high', 'low', 'close')})
    bar = adapter._canonical_bar(source, END, DAY)
    assert getattr(bar, field) == Decimal(source[field])
    with pytest.raises(pa.ArrowInvalid):
        pa.array([getattr(bar, field)], type=CANONICAL_SCHEMA.field(field).type)


@pytest.mark.parametrize('alias', ['turnover', 'total_turnover', 'amount'])
def test_turnover_aliases_share_policy(alias):
    source = row('1.1641532182693481E-10')
    source[alias] = source.pop('turnover')
    assert adapter._canonical_bar(source, END, DAY).turnover == Decimal('0.000000000116415321')


def test_turnover_integer_overflow_remains_schema_failure():
    bar = adapter._canonical_bar(row('123456789012345678901.123456789012345678999'), END, DAY)
    assert bar.turnover == Decimal('123456789012345678901.123456789012345678')
    with pytest.raises(pa.ArrowInvalid):
        pa.array([bar.turnover], type=CANONICAL_SCHEMA.field('turnover').type)


def test_weekly_normalized_sum_is_exact_under_low_precision_context():
    rows = ((DAY, row('9999999999999999999.1234567890123456789')),
            (date(2022, 4, 2), row('1.0000000000000000009')))
    with localcontext() as context:
        context.prec = 2
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        bar = adapter._aggregate_daily_rows(rows, bar_end=END)
    assert bar.turnover == Decimal('10000000000000000000.123456789012345678')


def test_turnover_truncation_cannot_create_strict_no_trade_source():
    source = dict(open=0, high=0, low=0, close=0, volume=0, turnover='1E-30', open_interest=1)
    with pytest.raises(InfrastructureError, match='RQDATA_WEEKLY_SOURCE_PRICE_INVALID'):
        adapter._aggregate_daily_rows(((DAY, source),), bar_end=END)


@pytest.mark.parametrize('missing', [None, float('nan'), Decimal('NaN')])
def test_nullable_missing_turnover_and_weekly_mixed_sum(missing):
    assert adapter._canonical_bar(row(missing), END, DAY).turnover is None
    all_missing = adapter._aggregate_daily_rows(((DAY, row(missing)),), bar_end=END)
    assert all_missing.turnover is None
    mixed = adapter._aggregate_daily_rows(
        ((DAY, row(missing)), (date(2022, 4, 2), row('1.1641532182693481E-10'))), bar_end=END,
    )
    assert mixed.turnover == Decimal('0.000000000116415321')
