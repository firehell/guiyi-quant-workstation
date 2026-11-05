"""Targeted temporal checks for an offline research hypothesis."""
import unittest
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from subing_box_reentry import State, step, usable_record

class BoxTests(unittest.TestCase):
    def bar(self, s, i, close, *, low=None, high=None, valid=True, contract='JM2601'):
        c = D(str(close))
        return step(s, at=datetime(2025,1,1,tzinfo=timezone.utc)+timedelta(minutes=30*i),
                    contract=contract, close=c, low=D(str(low)) if low is not None else c-1,
                    high=D(str(high)) if high is not None else c+1,
                    seed=(D(100),D(110)) if i==0 else None, valid=valid)

    def test_four_closes_and_wick_reentry(self):
        s,_=self.bar(State(),0,105)
        phases=[]
        for i in range(1,5):
            s,p=self.bar(s,i,111,low=108);phases.append(p)
            self.assertEqual((s.lower,s.upper),(D(100),D(110)))
        self.assertEqual(phases,['BREAK_PENDING']*3+['BREAK_CONFIRMED'])

    def test_close_on_boundary_fails_then_restarts(self):
        s,_=self.bar(State(),0,105)
        for i,c in enumerate([111,111,110,111,111,111,111],1):
            s,p=self.bar(s,i,c)
            if i==3:self.assertEqual(p,'BREAK_FAILED')
            if i==6:self.assertFalse(s.confirmed)
        self.assertTrue(s.confirmed)

    def test_mirror_down_break(self):
        s,_=self.bar(State(),0,105)
        for i in range(1,5):s,p=self.bar(s,i,99,high=102)
        self.assertEqual((p,s.side),('BREAK_CONFIRMED','DOWN'))

    def test_reentry_does_not_rewrite_prior_box(self):
        s,_=self.bar(State(),0,105)
        for i in range(1,5):s,_=self.bar(s,i,99,low=97)
        previous=s
        s,p=self.bar(s,5,103,low=98)
        self.assertEqual(p,'REENTERED_RANGE')
        self.assertEqual(s.lower,D(97))
        self.assertEqual(previous.lower,D(100))
        self.assertTrue(previous.confirmed)

    def test_gap_resets_and_contract_change_rejected(self):
        s,_=self.bar(State(),0,105)
        s,_=self.bar(s,1,111)
        with self.assertRaises(ValueError):self.bar(s,2,111,contract='JM2605')
        s,p=self.bar(s,2,111,valid=False)
        self.assertEqual(p,'UNKNOWN')
        s,p=self.bar(s,3,112)
        self.assertEqual(p,'UNKNOWN')
        self.assertEqual(s.count,0)

    def test_crossed_opposite_edge_is_not_inside_reentry(self):
        s,_=self.bar(State(),0,105)
        for i in range(1,5):s,_=self.bar(s,i,111)
        s,p=self.bar(s,5,95)
        self.assertEqual(p,'UNKNOWN')
        self.assertIsNone(s.lower)

    def test_unknown_archive_record_is_invalid(self):
        self.assertFalse(usable_record(None))
        self.assertFalse(usable_record({'regime':'UNKNOWN','reason':'COVERAGE_INVALID'}))
        self.assertFalse(usable_record({'regime':'RANGE','reason':'INPUT_INVALID'}))
        self.assertTrue(usable_record({'regime':'RANGE','reason':None}))

    def test_prefix_restore_future_perturbation(self):
        closes=[105,111,111,111,111,108,105]
        def replay(values, state=State(), start=0):
            outputs=[]
            for i,c in enumerate(values,start):
                state,p=self.bar(state,i,c);outputs.append((state,p))
            return outputs
        full=replay(closes)
        prefix=replay(closes[:3])
        self.assertEqual(prefix,full[:3])
        restored=State(**asdict(prefix[-1][0]))
        self.assertEqual(replay(closes[3:],restored,3),full[3:])
        perturbed=replay(closes[:3]+[95,95,95,95])
        self.assertEqual(perturbed[:3],full[:3])
        with self.assertRaises(ValueError):self.bar(restored,2,111)

if __name__=='__main__':unittest.main()
