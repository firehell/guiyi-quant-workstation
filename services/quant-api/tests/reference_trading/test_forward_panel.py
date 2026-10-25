from datetime import date
from decimal import Decimal

import pytest

from app.reference_trading.forward_panel import forward_panel
from app.reference_trading.query import QueryConflict


def trade(key, status='CLOSED', value='1.25', day='2026-10-01', owner='one'):
    return dict(reference_trade_id=key, status=status, reference_return=value,
                entry_trading_day=day, entry_bar_end=f'{day}T01:00:00+00:00',
                exit_trading_day=day, exit_bar_end=f'{day}T02:00:00+00:00',
                physical_contract='JM2701', owner_segment_id=owner,
                calculation_segment_id=owner)


class Query:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def trades(self, stream_id, **kwargs):
        self.calls.append(kwargs)
        start = int(kwargs.get('cursor') or 0)
        rows = self.rows[start:start + 2]
        return dict(items=rows, next_cursor=str(start + 2) if start + 2 < len(self.rows) else None,
                    snapshot='frozen', revision_id='r', seq=3,
                    stream=dict(recording_mode='forward_observation', stream_id=stream_id),
                    window=dict(since='2026-10-01', through='2026-10-25'), coverage={})

    def summary(self, stream_id, **kwargs):
        closed = [r for r in self.rows if r['status'] == 'CLOSED' and r['entry_trading_day'] >= '2026-10-01']
        return dict(snapshot='frozen', closed_count=len(closed),
                    open_count=sum(r['status'] == 'OPEN' and r['entry_trading_day'] >= '2026-10-01' for r in self.rows),
                    interrupted_count=sum(r['status'] not in ('CLOSED', 'OPEN') and r['entry_trading_day'] >= '2026-10-01' for r in self.rows),
                    initial_count=sum(r['entry_trading_day'] < '2026-10-01' for r in self.rows),
                    sum_return_percentage_points=str(sum((Decimal(r['reference_return']) for r in closed), Decimal(0))))


def read(query):
    return forward_panel(query, 's', since=date(2026, 10, 1), through=date(2026, 10, 25))


def test_full_curve_uses_only_in_window_closed_and_decimal_not_float():
    q = Query([trade('pre', value='99', day='2026-09-30'), trade('a', value='0.1'),
               trade('b', value='0.2'), trade('c', value='-0.4', owner='two'),
               trade('open', 'OPEN', None), trade('break', 'ROLLOVER_INTERRUPTED', None)])
    result = read(q)
    assert result['summary']['sum_return_percentage_points'] == '-0.1'
    assert result['drawdown_percentage_points'] == '0.4'
    assert result['total_curve_points'] == 3
    assert result['curve'][-1]['value'] == '-0.1'
    assert result['curve'][0]['segment'] != result['curve'][-1]['segment']
    assert len(result['page']['items']) == 2
    assert all(call.get('snapshot_token') == 'frozen' for call in q.calls[1:])


def test_snapshot_mismatch_and_unproven_complete_curve_fail_closed():
    class Changed(Query):
        def summary(self, *args, **kwargs):
            return dict(snapshot='changed', closed_count=1, sum_return_percentage_points='1.25')
    with pytest.raises(QueryConflict, match='SNAPSHOT_CONFLICT'):
        read(Changed([trade('a')]))
    class WrongSum(Query):
        def summary(self, *args, **kwargs):
            return {**super().summary(*args, **kwargs), 'sum_return_percentage_points': '100'}
    with pytest.raises(QueryConflict, match='SUMMARY_DATA_CONFLICT'):
        read(WrongSum([trade('a')]))


def test_empty_does_not_create_curve_or_annualization():
    result = read(Query([]))
    assert result['curve'] == []
    assert result['drawdown_percentage_points'] is None
    assert 'annualized_pct' not in result


def test_replay_stream_cannot_enter_realtime_panel():
    class Replay(Query):
        def trades(self, *args, **kwargs):
            page = super().trades(*args, **kwargs)
            page['stream']['recording_mode'] = 'historical_replay'
            return page
    with pytest.raises(QueryConflict, match='MODE_NOT_AVAILABLE'):
        read(Replay([]))


def test_http_panel_is_read_only_and_rejects_unknown_parameters(monkeypatch):
    from fastapi.testclient import TestClient
    from app.api import reference_trading as api
    from app.main import app
    monkeypatch.setattr(api, '_query', Query([trade('a')]))
    client = TestClient(app)
    path = '/api/v1/reference-trading/streams/s/panel'
    params = dict(since='2026-10-01', through='2026-10-25')
    response = client.get(path, params=params)
    assert response.status_code == 200
    assert response.json()['summary']['sum_return_percentage_points'] == '1.25'
    assert client.get(path, params={**params, 'mode': 'historical_replay'}).status_code == 422
    assert client.post(path, json=params).status_code == 405


def test_duplicate_first_page_and_incomplete_counts_are_rejected():
    with pytest.raises(QueryConflict, match='CURSOR_CONFLICT'):
        read(Query([trade('same'), trade('same')]))
    class WrongCount(Query):
        def summary(self, *args, **kwargs):
            return {**super().summary(*args, **kwargs), 'open_count': 99}
    with pytest.raises(QueryConflict, match='SUMMARY_DATA_CONFLICT'):
        read(WrongCount([trade('a')]))


def test_sampling_keeps_complete_metrics_and_budget_is_fail_closed(monkeypatch):
    import app.reference_trading.forward_panel as module
    monkeypatch.setattr(module, 'MAX_CURVE_POINTS', 4)
    result = read(Query([trade(str(i), value='0.1') for i in range(9)]))
    assert len(result['curve']) == 4
    assert result['total_curve_points'] == 9
    assert result['summary']['sum_return_percentage_points'] == '0.9'
    monkeypatch.setattr(module, 'MAX_TRADES', 4)
    with pytest.raises(QueryConflict, match='QUERY_BUDGET_EXCEEDED'):
        read(Query([trade(str(i)) for i in range(6)]))
