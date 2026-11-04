import unittest
import pickle
from datetime import datetime,timedelta,timezone
from decimal import Decimal as D
from subing_recent_structure import Bar,Pivot,State,step

T=datetime(2025,1,1,tzinfo=timezone.utc)
def bar(i,c,h=None,l=None):
    return Bar(T+timedelta(minutes=30*i),D(str(h if h is not None else c+1)),D(str(l if l is not None else c-1)),D(str(c)))
def run(bs,state=None):
    s=state or State('JM2601');out=[]
    for b in bs:s,p=step(s,b,contract='JM2601');out.append((s,p))
    return out

class Tests(unittest.TestCase):
    def test_pivot_available_only_after_two_right_bars(self):
        bs=[bar(i,c) for i,c in enumerate([105,106,110,106,105])]
        out=run(bs)
        self.assertFalse(out[3][0].pivots)
        p=out[4][0].pivots[0]
        self.assertEqual((p.at,p.confirmed_at),(bs[2].at,bs[4].at))

    def test_dual_extremum_not_ordered_from_ohlc(self):
        bs=[bar(i,105) for i in range(5)];bs[2]=bar(2,105,120,90)
        self.assertFalse(run(bs)[-1][0].pivots)

    def test_pending_freezes_and_counts_four_closes_not_wicks(self):
        s=State('JM2601',lower=D(100),upper=D(110),boundary_at=T,last_at=T)
        out=run([bar(i,111,112,108) for i in range(1,5)],s)
        self.assertEqual([p['phase'] for _,p in out],['BREAK_PENDING']*3+['BREAK_CONFIRMED'])
        self.assertTrue(all((x.lower,x.upper)==(D(100),D(110)) for x,_ in out))

    def test_boundary_close_fails_without_counting_opposite(self):
        s=State('JM2601',lower=D(100),upper=D(110),boundary_at=T,last_at=T)
        out=run([bar(1,111),bar(2,110),bar(3,99),bar(4,111)],s)
        self.assertEqual(out[1][1]['phase'],'BREAK_FAILED')
        self.assertEqual(out[2][1]['count'],1)
        self.assertEqual(out[3][1]['phase'],'UNKNOWN')

    def test_mirror(self):
        s=State('JM2601',lower=D(100),upper=D(110),last_at=T)
        out=run([bar(i,99,102,98) for i in range(1,5)],s)
        self.assertEqual((out[-1][1]['phase'],out[-1][1]['break_side']),('BREAK_CONFIRMED','DOWN'))

    def test_gap_clears_and_identity_and_time_rejected(self):
        s=State('JM2601',lower=D(100),upper=D(110),last_at=T)
        clean,p=step(s,bar(1,105),contract='JM2601',valid=False)
        self.assertIsNone(clean.lower)
        self.assertEqual(p['phase'],'UNKNOWN')
        with self.assertRaises(ValueError):step(s,bar(1,105),contract='JM2605')
        with self.assertRaises(ValueError):step(s,bar(0,105),contract='JM2601')
        with self.assertRaises(ValueError):step(s,bar(1,105,100,110),contract='JM2601')

    def test_old_edge_events_precede_new_pivot_update(self):
        pivots=tuple(Pivot(side,D(price),T-timedelta(minutes=10-i),T-timedelta(minutes=9-i))
                     for i,(side,price) in enumerate([('HIGH',110),('LOW',100),('HIGH',111),('LOW',101),('HIGH',112),('LOW',102)]))
        prior=(bar(0,105,110,102),bar(1,110,115,104),bar(2,110,121,105),bar(3,109,113,106))
        s=State('JM2601',bars=prior,pivots=pivots,lower=D(100),upper=D(110),boundary_at=T,pending_side='UP',count=4,last_at=prior[-1].at)
        for close,expected in [(95,'UNKNOWN'),(105,'REENTERED')]:
            result,p=step(s,bar(4,close),contract='JM2601')
            self.assertTrue(p['pivot_confirmed_now'])
            self.assertEqual(p['phase'],expected)
            if expected=='UNKNOWN':self.assertIsNone(result.lower)
            else:self.assertEqual((result.lower,result.upper),(D(100),D(110)))

    def test_prefix_future_perturbation_and_serialized_state(self):
        values=[105,106,110,106,105,102,105,108,112,108,105,101,105,109,111,108,105,103]*5
        bs=[bar(i,c) for i,c in enumerate(values)]
        full=run(bs)
        for cut in (8,23,48,65):
            prefix=run(bs[:cut]);self.assertEqual(prefix,full[:cut])
            restored=pickle.loads(pickle.dumps(prefix[-1][0]))
            self.assertEqual(run(bs[cut:],restored),full[cut:])
            altered=bs[:cut]+[bar(i,150+i%5) for i in range(cut,len(bs))]
            self.assertEqual(run(altered)[:cut],full[:cut])
        self.assertTrue(any(s.lower is not None for s,_ in full))
        self.assertTrue(all(p.confirmed_at<=s.last_at for s,_ in full for p in s.pivots))

if __name__=='__main__':unittest.main()
