from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from app.reference_trading.saved_theoretical import saved_theoretical


def test_saved_theory_uses_peak_close_or_high_and_keeps_public_identity():
    trade = dict(status='CLOSED', entry_trading_day='2026-01-01', exit_trading_day='2026-01-03',
        entry_bar_end='2026-01-01T07:00:00+00:00', exit_bar_end='2026-01-03T07:00:00+00:00',
        physical_contract='AP601', reference_trade_id='internal', public_reference_trade_id='public',
        entry_reference_price='100', holding_bars=2)
    bars = {'AP601': [SimpleNamespace(bar_end=datetime.fromisoformat(f'2026-01-0{day}T07:00:00+00:00'),
        close=Decimal(close), high=Decimal(high)) for day, close, high in [(1,'100','101'),(2,'120','130'),(3,'105','110')]]}
    marks = [dict(trade_id='internal', bar_end=bar.bar_end.isoformat()) for bar in bars['AP601'][:2]]
    ordinary = dict(trade)
    trend = saved_theoretical([trade], marks, bars, 'trend', '2026-01-01','2026-01-03')
    assert trend['sum_return_percentage_points'] == '20.0'
    assert trend['returns'][0]['reference_trade_id'] == 'public'
    assert trend['hindsight'] and not trend['executable']
    assert saved_theoretical([trade], marks, bars, 'oscillation', '2026-01-01','2026-01-03')['sum_return_percentage_points'] == '30.0'
    assert trade == ordinary
    assert saved_theoretical([trade], marks[:1], bars, 'trend','2026-01-01','2026-01-03') is None
    assert saved_theoretical([trade], marks, {'AP601': bars['AP601'][:2]}, 'trend','2026-01-01','2026-01-03') is None
    assert saved_theoretical([dict(trade, status='OPEN')], marks, bars, 'trend','2026-01-01','2026-01-03')['returns'] == []


def test_reader_batches_physical_windows_and_excludes_post_cutoff_bars():
    from app.market_data.newow.product_reader import NewowProductReader
    from app.market_data.domain import BarFrequency
    cutoff = datetime.fromisoformat('2026-01-03T07:00:00+00:00')
    calls = []
    def query(request):
        calls.append(request)
        return SimpleNamespace(bars=(SimpleNamespace(bar_end=cutoff), SimpleNamespace(bar_end=datetime.fromisoformat('2026-01-04T07:00:00+00:00'))))
    reader = object.__new__(NewowProductReader)
    reader._market_data = SimpleNamespace(query_contract_trading_days=query)
    reader._check_cancelled = lambda: None
    trades = [dict(status='CLOSED',physical_contract='AP2601',entry_trading_day='2026-01-01',exit_trading_day='2026-01-03'),
        dict(status='CLOSED',physical_contract='AP2601',entry_trading_day='2026-01-02',exit_trading_day='2026-01-03'),
        dict(status='OPEN',physical_contract='AP2701')]
    result = reader.reference_theoretical_bars('ap','60m',trades,cutoff)
    assert len(calls) == 1 and calls[0].contract == 'AP2601' and calls[0].frequency == BarFrequency.H1
    assert len(result['AP2601']) == 1 and result['AP2601'][0].bar_end == cutoff
