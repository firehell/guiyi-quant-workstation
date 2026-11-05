from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace as S
from copy import deepcopy

from app.market_data.newow.path_calendar import apply_path_date, read_path_calendar

ORIGIN = date(2026, 1, 30)
NOW = datetime(2026, 1, 30, 7, tzinfo=UTC)


def context(rows=None, sessions=None):
    return dict(identity="a" * 64, reason=None, origin=ORIGIN,
                rows=rows or {ORIGIN+timedelta(days=i): i not in (1, 2, 3) for i in range(10)},
                sessions=sessions or (lambda _: [S(start=NOW, end=NOW+timedelta(hours=1))]))


def path(remain=.83, unit="个交易日"):
    return dict(buys=[1, 2], sells=[3], eta=dict(status="ready", base=5, remain=remain, elapsed=1, ratio=.5, samples=2,
        unit=unit, date=None, date_status="unavailable", date_reason="CALENDAR_PROOF_UNAVAILABLE", date_source=None))


def test_positive_fraction_advances_past_closed_days_and_zero_stays():
    p=path(); apply_path_date(p,context(),ORIGIN)
    assert p["eta"]["date"] == "2026-02-03"
    assert p["eta"]["date_source"]["origin_trading_day"] == "2026-01-30"
    p=path(0); apply_path_date(p,context(),ORIGIN)
    assert p["eta"]["date"] == "2026-01-30"


def test_weekly_ceiling_then_authoritative_open_day():
    p=path(.5,"周");apply_path_date(p,context(),ORIGIN)
    assert p["eta"]["date"] == "2026-02-03"


def test_missing_rows_session_or_horizon_preserve_duration_and_historical_points():
    for ctx,remain,reason in [(context({ORIGIN:True}),1,"CALENDAR_INCOMPLETE"),
        (context(sessions=lambda _:[]),1,"SESSION_INCOMPLETE"),
        (context(),367,"CALENDAR_HORIZON_EXCEEDED"), (None,1,"CALENDAR_PROOF_UNAVAILABLE")]:
        p=path(remain);before=deepcopy(p);apply_path_date(p,ctx,ORIGIN)
        assert p['eta']['date'] is None and p['eta']['date_reason']==reason
        assert p['eta']['remain']==before['eta']['remain'] and p['buys']==before['buys']


class Market:
    def __init__(self): self.closed=False; self.calls=[]
    def previous_trading_day(self,product,origin): return origin-timedelta(days=1)
    def calendar_day_facts(self,**kw):
        self.calls.append(kw)
        return tuple((ORIGIN+timedelta(days=i), i!=1 or self.closed) for i in range(4))
    def historical_metadata_evidence(self,**kw):
        self.calls.append(kw)
        return {"sessions":"exact-source-v1", "calendar": [[str(d), opened] for d, opened in self.calendar_day_facts()]}
    def session_windows(self,**kw): return [S(start=NOW,end=NOW+timedelta(hours=1))]


def test_partial_future_horizon_can_prove_a_complete_near_prefix_and_identity_changes():
    market=Market();c=read_path_calendar(market,product='jm',origin=ORIGIN,as_of=NOW,now=NOW)
    assert c['reason'] is None
    assert market.calls[0]['through']==ORIGIN+timedelta(days=366)
    assert market.calls[1]['through']==ORIGIN+timedelta(days=3)
    p=path(1);apply_path_date(p,c,ORIGIN);assert p['eta']['date']=='2026-02-01'
    market.closed=True
    changed=read_path_calendar(market,product='jm',origin=ORIGIN,as_of=NOW,now=NOW)
    assert changed['identity']!=c['identity']


def test_historical_asof_does_not_claim_current_catalog_was_known_then():
    market=Market();c=read_path_calendar(market,product='jm',origin=ORIGIN,as_of=NOW,now=NOW+timedelta(days=1))
    assert c['reason']=='HISTORICAL_CALENDAR_PROOF_MISSING' and market.calls==[]


def test_previous_calendar_dependency_is_part_of_identity_and_late_correction_fails_closed():
    market=Market()
    market.historical_metadata_evidence=lambda **kw: {"since":str(kw['since']),"revision":"v1", "calendar": [[str(d), opened] for d, opened in market.calendar_day_facts()]}
    c=read_path_calendar(market,product='jm',origin=ORIGIN,as_of=NOW,now=NOW)
    market.previous_trading_day=lambda *_: ORIGIN-timedelta(days=2)
    other=read_path_calendar(market,product='jm',origin=ORIGIN,as_of=NOW,now=NOW)
    assert c['identity']!=other['identity']
    market.historical_metadata_evidence=lambda **kw:{"since":str(kw['since']),"revision":"v2"}
    p=path(1);apply_path_date(p,c,ORIGIN)
    assert p['eta']['date'] is None and p['eta']['date_reason']=='CALENDAR_SOURCE_CHANGED'


def test_calendar_corrected_between_rows_and_metadata_cannot_prove_old_open_day():
    market = Market()
    original = market.historical_metadata_evidence
    def corrected(**kw):
        result = original(**kw)
        result["calendar"][2][1] = False
        return result
    market.historical_metadata_evidence = corrected
    ctx = read_path_calendar(market, product="jm", origin=ORIGIN, as_of=NOW, now=NOW)
    assert ctx["reason"] == "CALENDAR_SOURCE_CHANGED"
