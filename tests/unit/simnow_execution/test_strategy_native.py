"""Session authority binds the event's actual product and physical contract."""
from datetime import date
from types import SimpleNamespace as NS
import pytest
from guiyi_quant.simnow_execution.strategy_native import validate_strategy_events


def facts():
    order = dict(OrderRef='11', FrontID=1, SessionID=2, TradingDay='20261102',
        InstrumentID='al2611', ExchangeID='SHFE', Direction='1', CombOffsetFlag='4',
        CombHedgeFlag='1', VolumeTotalOriginal=1, LimitPrice='1000', OrderSysID='sys',
        InsertDate='20261030', InsertTime='21:01:00')
    trade = dict(TradingDay='20261102', InstrumentID='al2611', ExchangeID='SHFE',
        OrderSysID='sys', TradeDate='20261030', TradeTime='21:01:01')
    bound = dict(native='al2611', exchange='SHFE', trading_day='20261102', side='SELL',
                 offset='4', price='1000')
    journal = NS(find_ref=lambda *_:'order', find=lambda _:bound, events=lambda:())
    state = NS(orders=(NS(order_id='order',product='AL',contract='AL2611'),))
    return NS(data={'orders':[order],'trades':[trade]}), journal, state


def test_friday_night_uses_monday_day_and_old_physical_contract():
    snapshot, journal, state = facts()
    seen = []
    def authority(product, day, raw, contract):
        seen.append((product,day,raw,contract))
        return NS(owner='AL2612',contract=contract,exchange='SHFE',
                  session=NS(contract=contract,can_trade=True))
    validate_strategy_events(snapshot,authority,journal,state)
    assert len(seen) == 2
    assert all(product=='AL' and day==date(2026,11,2) and contract=='AL2611'
               and raw.date()==date(2026,10,30) for product,day,raw,contract in seen)


@pytest.mark.parametrize('bad', ['closed','contract','exchange','unowned'])
def test_unproven_session_or_ownership_stops_correlation(bad):
    snapshot,journal,state = facts()
    if bad=='unowned':
        state.orders=()
    def authority(*args):
        return NS(contract='AL2612' if bad=='contract' else 'AL2611',
                  exchange='DCE' if bad=='exchange' else 'SHFE',
                  session=NS(contract='AL2611',can_trade=bad!='closed'))
    with pytest.raises(ValueError,match='NATIVE_EVENT_(OWNERSHIP|SESSION)_UNPROVEN'):
        validate_strategy_events(snapshot,authority,journal,state)
