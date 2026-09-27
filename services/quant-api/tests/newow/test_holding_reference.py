from dataclasses import replace
from decimal import Decimal

from guiyi_quant.newow.holding_reference import holding_reference_curve, reference_trade_rows
from guiyi_quant.newow.reference_statistics import PerformanceWindow
from guiyi_quant.newow.reference_trades import ReferenceTradeProjector


def test_curve_marks_entry_and_each_holding_bar_without_changing_realized(product_cases):
    case = product_cases.closed()
    projection = ReferenceTradeProjector().project(case.replay, (), case.as_of)
    window = PerformanceWindow(case.entry.trading_day, case.exit.trading_day, case.as_of)
    result = holding_reference_curve(reference_trade_rows(projection.trades), case.bars, window)
    points = result['points']
    assert len(points) == 2
    assert Decimal(points[0]['closed_return_percentage_points']) == 0
    assert Decimal(points[0]['floating_return_pct']) == 0
    assert Decimal(points[-1]['closed_return_percentage_points']) == 10
    assert Decimal(points[-1]['floating_return_pct']) == 0
    assert Decimal(points[-1]['marked_return_percentage_points']) == 10


def test_open_curve_is_floating_and_cutoff_excludes_future_close(product_cases):
    case = product_cases.closed()
    cutoff = case.entry.bar_end
    projection = ReferenceTradeProjector().project(case.replay, (), cutoff)
    bars = (replace(case.bars[0], bar=replace(case.bars[0].bar, close=Decimal('105'))), *case.bars[1:])
    result = holding_reference_curve(reference_trade_rows(projection.trades), bars,
        PerformanceWindow(case.entry.trading_day, case.exit.trading_day, cutoff))
    assert len(result['points']) == 1
    point = result['points'][0]
    assert Decimal(point['closed_return_percentage_points']) == 0
    assert Decimal(point['floating_return_pct']) == 5
    assert point['status'] == 'HOLDING'
    assert projection.trades[0].status == 'OPEN'


def test_curve_never_values_on_other_owner_or_initial_window_entry(product_cases):
    case = product_cases.closed()
    projection = ReferenceTradeProjector().project(case.replay, (), case.entry.bar_end)
    other = replace(case.bars[0], calculation_segment_id='different')
    window = PerformanceWindow(case.entry.trading_day, case.exit.trading_day, case.as_of)
    assert holding_reference_curve(reference_trade_rows(projection.trades), (other,), window) is None
    later = PerformanceWindow(case.exit.trading_day, case.exit.trading_day, case.as_of)
    result = holding_reference_curve(reference_trade_rows(projection.trades), case.bars, later)
    assert all(Decimal(p['marked_return_percentage_points']) == 0 for p in result['points'])


def test_complete_holding_path_retains_intermediate_drawdown_and_owner_break(product_cases):
    from datetime import timedelta
    case = product_cases.closed()
    middle = replace(case.bars[0], bar=replace(case.bars[0].bar,
        bar_end=case.entry.bar_end + timedelta(hours=1), close=Decimal('95'), low=Decimal('90')))
    bars = (case.bars[0], middle, case.bars[-1])
    replay = product_cases.replay(case.identity, bars, (case.entry, case.exit), ('BUILD', 'HOLD', 'CLEAR'))
    projection = ReferenceTradeProjector().project(replay, (), case.as_of)
    result = holding_reference_curve(reference_trade_rows(projection.trades), bars,
        PerformanceWindow(case.entry.trading_day, case.exit.trading_day, case.as_of))
    assert [Decimal(point['marked_return_percentage_points']) for point in result['points']] == [0, -5, 10]
    assert result['points'][1]['entry_trading_day'] == case.entry.trading_day.isoformat()
    assert result['points'][1]['closed_return_percentage_points'] == '0'

    interrupted = product_cases.interrupted()
    projection = ReferenceTradeProjector().project(interrupted.replay, interrupted.boundaries, interrupted.as_of)
    new_owner = replace(interrupted.bars[-1], bar=replace(interrupted.bars[-1].bar,
        bar_end=interrupted.boundaries[0].effective_at + timedelta(hours=1),
        trading_day=interrupted.boundaries[0].effective_trading_day,
        physical_contract='RB2610', segment_id=interrupted.boundaries[0].new_segment_id),
        calculation_segment_id=interrupted.boundaries[0].new_segment_id)
    result = holding_reference_curve(reference_trade_rows(projection.trades), (*interrupted.bars, new_owner),
        PerformanceWindow(interrupted.entry.trading_day, interrupted.as_of.date(), interrupted.as_of))
    assert result is not None
    assert any(point['status'] == 'INTERRUPTED' and point['marked_return_percentage_points'] is None
               for point in result['points'])
    assert all(Decimal(point['closed_return_percentage_points']) == 0 for point in result['points'])
