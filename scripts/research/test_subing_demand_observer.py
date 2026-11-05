import unittest,json
from copy import deepcopy
from decimal import Decimal
from subing_demand_observer import Observer,gross

L=[dict(id='base',side='LONG',price='100',quantity=1)]
def e(kind,day='2025-01-06',mark='100',**kw):
    prev={'2025-01-06':'2025-01-03','2025-01-07':'2025-01-06','2025-01-08':'2025-01-07','2025-01-09':'2025-01-08'}[day]
    tm=day+'T07:00:00+00:00'
    if kind=='NEXT_OPEN':tm=prev+'T13:00:00+00:00'
    event=dict(event_id=kind+day,contract='JM2601',kind=kind,trading_day=day,previous_trading_day=prev,
               observed_at=tm if kind!='NEXT_OPEN' else tm.replace('13:00','13:01'),price_at=tm,
               layers=deepcopy(L),position_id='round1',regime='RANGE',mark=mark,multiplier='60',
               session_day_end=day+'T07:00:00+00:00',next_open=day+'T13:00:00+00:00')
    event.update(kw);return event

class Tests(unittest.TestCase):
    def test_gross_excludes_fees_realized_and_closed_layers(self):
        self.assertEqual(gross(L,'101','60'),Decimal(60))
        self.assertEqual(gross([dict(id='x',side='SHORT',price='100',quantity=2)],'99','60'),Decimal(120))
        self.assertEqual(gross([],'99','60'),Decimal(0))

    def test_dayend_records_and_rechecks_open_profit(self):
        o=Observer('JM2601');self.assertEqual(o.apply(e('DAY_END',mark='99'))['demand'],'RECORD_ONLY')
        p=o.apply(e('NEXT_OPEN','2025-01-07',mark='101'))
        self.assertEqual(p['demand'],'HOLD_NO_ADD');self.assertFalse(o.exit_required)
        self.assertGreater(p['observed_at'],p['price_at'])

    def test_three_days_zero_then_open_zero_exits(self):
        o=Observer('JM2601')
        for day,nxt in [('2025-01-06','2025-01-07'),('2025-01-07','2025-01-08'),('2025-01-08','2025-01-09')]:
            p=o.apply(e('DAY_END',day));self.assertEqual(p['demand'],'RECORD_ONLY')
            p=o.apply(e('NEXT_OPEN',nxt))
        self.assertEqual(p['nonpositive_range_days'],3)
        self.assertEqual(p['reason'],'RANGE_THREE_NONPOSITIVE_DAYS')

    def test_first_open_loss_and_obligation_sticky(self):
        o=Observer('JM2601');o.apply(e('DAY_END'))
        p=o.apply(e('NEXT_OPEN','2025-01-07',mark='99'));self.assertEqual(p['reason'],'RANGE_OPEN_GROSS_LOSS')
        p=o.apply(e('BAR','2025-01-07',mark='102'));self.assertEqual(p['demand'],'EXIT_OBLIGATION')

    def test_duplicate_restart_conflict_and_atomicity(self):
        o=Observer('JM2601');first=e('DAY_END');a=o.apply(first)
        restored=Observer.restore(json.loads(json.dumps(o.checkpoint())))
        self.assertTrue(restored.apply(first)['duplicate']);self.assertEqual(restored.streak,1)
        before=restored.checkpoint()
        with self.assertRaises(ValueError):restored.apply(dict(first,mark='101'))
        self.assertEqual(before,restored.checkpoint())
        nxt=e('NEXT_OPEN','2025-01-07',mark='99')
        self.assertEqual(o.apply(nxt),restored.apply(nxt))

    def test_intraday_break_is_not_next_day_open(self):
        o=Observer('JM2601');o.apply(e('DAY_END'))
        with self.assertRaises(ValueError):o.apply(e('NEXT_OPEN','2025-01-07',price_at='2025-01-07T05:30:00+00:00',observed_at='2025-01-07T05:31:00+00:00'))

    def test_partial_position_and_new_round_reset(self):
        o=Observer('JM2601');o.apply(e('DAY_END'))
        p=o.apply(e('NEXT_OPEN','2025-01-07',layers=[dict(id='add',side='LONG',price='101',quantity=1)],mark='102'))
        self.assertEqual(p['gross_remaining'],'60');self.assertEqual(o.streak,1)
        o.apply(e('BAR','2025-01-07',layers=[],position_id=None));self.assertEqual(o.streak,0)

    def test_trend_resets_streak_and_gap_rejected(self):
        o=Observer('JM2601');o.apply(e('DAY_END'));o.apply(e('NEXT_OPEN','2025-01-07',regime='TREND_UP',mark='99'))
        self.assertEqual(o.streak,0);self.assertFalse(o.exit_required)
        with self.assertRaises(ValueError):o.apply(e('BAR','2025-01-09'))

    def test_day_end_cannot_overwrite_missing_open(self):
        o=Observer('JM2601');o.apply(e('DAY_END'));before=o.checkpoint()
        with self.assertRaises(ValueError):o.apply(e('DAY_END','2025-01-07'))
        self.assertEqual(before,o.checkpoint())

    def test_untrusted_day_end_does_not_count(self):
        o=Observer('JM2601');before=o.checkpoint()
        with self.assertRaises(ValueError):o.apply(e('DAY_END',data_ready=False))
        self.assertEqual(before,o.checkpoint())

    def test_missing_day_end_is_not_counted_across(self):
        o=Observer('JM2601');o.apply(e('DAY_END'));o.apply(e('NEXT_OPEN','2025-01-07'))
        o.apply(e('BAR','2025-01-07'));before=o.checkpoint()
        with self.assertRaises(ValueError):o.apply(e('BAR','2025-01-08'))
        self.assertEqual(before,o.checkpoint())

    def test_returned_result_cannot_mutate_cached_history(self):
        o=Observer('JM2601');event=e('DAY_END');result=o.apply(event)
        result['nonpositive_range_days']=999
        self.assertEqual(o.apply(event)['nonpositive_range_days'],1)

    def test_missing_open_cannot_be_skipped(self):
        o=Observer('JM2601');o.apply(e('DAY_END'))
        with self.assertRaises(ValueError):o.apply(e('BAR','2025-01-07'))

if __name__=='__main__':unittest.main()
