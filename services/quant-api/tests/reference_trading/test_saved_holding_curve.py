from datetime import datetime
from app.reference_trading.saved_holding_curve import saved_holding_curve


def test_saved_marks_keep_floating_loss_and_clear_without_changing_trade_return():
    trade = dict(reference_trade_id='internal', public_reference_trade_id='public',
        physical_contract='JM2601', owner_segment_id='owner', calculation_segment_id='calc',
        entry_bar_end='2026-01-01T07:00:00+00:00', entry_trading_day='2026-01-01',
        exit_bar_end='2026-01-03T07:00:00+00:00', exit_trading_day='2026-01-03',
        reference_return='5', holding_bars=2, status='CLOSED')
    marks = [dict(trade_id='internal', bar_end=f'2026-01-0{day}T07:00:00+00:00',
        trading_day=f'2026-01-0{day}', holding_bars=day-1, reference_return=value)
        for day, value in [(1, '0'), (2, '-10')]]
    cutoff = datetime.fromisoformat(trade['exit_bar_end'])
    curve = saved_holding_curve([trade], marks, [], '2026-01-01', '2026-01-03', cutoff)
    assert [p['marked_return_percentage_points'] for p in curve['points']] == ['0', '-10', '5']
    assert curve['points'][1]['reference_trade_id'] == 'public'
    assert curve['points'][-1]['closed_return_percentage_points'] == '5'
    assert saved_holding_curve([trade], marks[:1], [], '2026-01-01', '2026-01-03', cutoff) is None
    assert saved_holding_curve([trade], marks, [], '2026-01-02', '2026-01-03', cutoff) is None


def test_interruption_breaks_curve_without_realizing_floating_return():
    trade = dict(reference_trade_id='internal', public_reference_trade_id='public',
        physical_contract='JM2601', owner_segment_id='owner', calculation_segment_id='calc',
        entry_bar_end='2026-01-01T07:00:00+00:00', entry_trading_day='2026-01-01',
        exit_bar_end=None, interrupted_at='2026-01-02T07:00:00+00:00',
        reference_return=None, holding_bars=0, status='ROLLOVER_INTERRUPTED')
    mark = dict(trade_id='internal', bar_end=trade['entry_bar_end'], trading_day='2026-01-01',
        holding_bars=0, reference_return='4')
    curve = saved_holding_curve([trade], [mark], [], '2026-01-01', '2026-01-03',
        datetime.fromisoformat('2026-01-03T07:00:00+00:00'),
        [dict(trading_day='2026-01-02', value=dict(bar_end=trade['interrupted_at']))])
    assert curve['points'][-1]['marked_return_percentage_points'] is None
    assert curve['points'][-1]['closed_return_percentage_points'] == '0'


def test_missing_saved_mark_at_a_known_held_bar_fails_closed():
    trade = dict(reference_trade_id='internal', public_reference_trade_id='public',
        physical_contract='JM2601', owner_segment_id='owner', calculation_segment_id='calc',
        entry_bar_end='2026-01-01T07:00:00+00:00', entry_trading_day='2026-01-01',
        exit_bar_end='2026-01-04T07:00:00+00:00', exit_trading_day='2026-01-04',
        reference_return='5', holding_bars=2, status='CLOSED')
    marks = [dict(trade_id='internal', bar_end=f'2026-01-0{day}T07:00:00+00:00',
        trading_day=f'2026-01-0{day}', holding_bars=index, reference_return='0')
        for index, day in enumerate((1, 3))]
    availability = [dict(trading_day='2026-01-02', value=dict(bar_end='2026-01-02T07:00:00+00:00',
        physical_contract='JM2601', segment_id='owner', calculation_segment_id='calc', status='ready'))]
    assert saved_holding_curve([trade], marks, availability, '2026-01-01', '2026-01-04',
        datetime.fromisoformat(trade['exit_bar_end'])) is None
