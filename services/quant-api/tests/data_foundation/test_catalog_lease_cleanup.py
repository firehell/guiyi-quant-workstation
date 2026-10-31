from types import SimpleNamespace

import pytest

from app.market_data.catalog import _PostgresMaintenanceLease


@pytest.mark.parametrize('result,error,invalidated', [(True, None, False), (False, None, True), (None, RuntimeError('connection lost'), True), (None, KeyboardInterrupt(), True)])
def test_unverified_unlock_discards_connection(result, error, invalidated):
    events = []
    def execute(*_):
        events.append('unlock')
        if error is not None:
            raise error
        return SimpleNamespace(scalar_one=lambda: result)
    lease = _PostgresMaintenanceLease(SimpleNamespace(execute=execute,
        invalidate=lambda: events.append('invalidate'), close=lambda: events.append('close')),
        close_on_release=True)
    if invalidated:
        with pytest.raises(BaseException):
            lease.release()
    else:
        lease.release()
    assert events == (['unlock', 'invalidate', 'close'] if invalidated else ['unlock', 'close'])
    lease.release()
    assert events.count('unlock') == 1
