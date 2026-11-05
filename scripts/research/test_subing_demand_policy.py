import unittest
from dataclasses import replace
from decimal import Decimal as D
from subing_demand_policy import Facts,project

class Tests(unittest.TestCase):
    def test_confirmed_range_does_not_itself_clear_profitable_position(self):
        # Synthetic gross amount tests the agreed C04 action semantics, not its PnL.
        for side in ('LONG','SHORT'):
            f=Facts(side,'RANGE',phase='BAR_CLOSE',gross_remaining=D('1'),nonpositive_range_days=3,add_ready=True)
            self.assertEqual(project(f).kind,'HOLD_NO_ADD')
            self.assertEqual(project(replace(f,all_exit_required=True)).kind,'EXIT_OBLIGATION')

    def test_day_end_records_even_loss(self):
        for gross in ('-100','0','100'):
            f=Facts('LONG','RANGE',phase='DAY_END',gross_remaining=D(gross),nonpositive_range_days=3)
            self.assertEqual(project(f).kind,'RECORD_ONLY')

    def test_next_open_rechecks_current_gross(self):
        f=Facts('LONG','RANGE',phase='NEXT_OPEN_AFTER_DAY_END',nonpositive_range_days=3)
        self.assertEqual(project(replace(f,gross_remaining=D(1))).kind,'HOLD_NO_ADD')
        self.assertEqual(project(replace(f,gross_remaining=D(0))).reason,'RANGE_THREE_NONPOSITIVE_DAYS')
        self.assertEqual(project(replace(f,gross_remaining=D(-1))).reason,'RANGE_OPEN_GROSS_LOSS')
        self.assertEqual(project(replace(f,gross_remaining=D(0),nonpositive_range_days=2)).kind,'HOLD_NO_ADD')

    def test_loss_rule_only_applies_to_confirmed_range(self):
        for regime in ('TREND_UP','TREND_DOWN','UNKNOWN'):
            p=project(Facts('SHORT',regime,phase='NEXT_OPEN_AFTER_DAY_END',gross_remaining=D(-100)))
            self.assertNotEqual(p.kind,'EXIT_REQUIRED')

    def test_preexisting_exit_not_cancelled_by_profit_or_unknown(self):
        f=Facts('LONG','UNKNOWN',gross_remaining=D(100),all_exit_required=True,data_ready=False)
        self.assertEqual(project(f).kind,'EXIT_OBLIGATION')
        self.assertEqual(project(f).execution,'EXECUTION_FACTS_MISSING')
        self.assertEqual(project(replace(f,execution_ready=True)).execution,'AWAIT_LATER_EXECUTION')

    def test_pending_break_blocks_new_exposure_both_directions(self):
        for side in ('UP','DOWN'):
            self.assertEqual(project(Facts('FLAT','TREND_UP',pending_break=side,first_entry_ready=True)).kind,'WAIT_CONFIRMATION')
            self.assertEqual(project(Facts('LONG','TREND_UP',pending_break=side,add_ready=True)).kind,'HOLD_NO_ADD')

    def test_range_blocks_first_entry_and_add(self):
        self.assertEqual(project(Facts('FLAT','RANGE',first_entry_ready=True)).kind,'WAIT')
        self.assertEqual(project(Facts('LONG','RANGE',add_ready=True)).kind,'HOLD_NO_ADD')

    def test_existing_risk_overrides_pending_break(self):
        f=Facts('SHORT','RANGE',pending_break='UP',all_exit_required=True)
        self.assertEqual(project(f).kind,'EXIT_OBLIGATION')

    def test_no_pnl_defaults_or_unknown_counter(self):
        f=Facts('LONG','RANGE',phase='NEXT_OPEN_AFTER_DAY_END')
        self.assertEqual(project(f).kind,'REVIEW_REQUIRED')
        self.assertEqual(project(replace(f,gross_remaining=D(0))).kind,'REVIEW_REQUIRED')
        self.assertEqual(project(replace(f,gross_remaining=D(-1))).kind,'EXIT_REQUIRED')

    def test_mirror_add_and_no_automatic_reverse(self):
        self.assertEqual(project(Facts('SHORT','TREND_DOWN',add_ready=True)).kind,'CHECK_ADD_ELIGIBILITY')
        self.assertEqual(project(Facts('SHORT','TREND_UP',first_entry_ready=True)).kind,'HOLD_NO_ADD')

    def test_current_exit_supersedes_pending_nonexit(self):
        f=Facts('LONG','RANGE',phase='NEXT_OPEN_AFTER_DAY_END',gross_remaining=D(-1),action_pending=True)
        self.assertEqual(project(f).kind,'EXIT_REQUIRED')
        self.assertEqual(project(replace(f,gross_remaining=D(1))).kind,'MANAGE_PENDING')

    def test_full_exit_overrides_reduction_but_missing_pnl_preserves_it(self):
        f=Facts('LONG','RANGE',phase='NEXT_OPEN_AFTER_DAY_END',gross_remaining=D(-1),reduce_required=True)
        self.assertEqual(project(f).kind,'EXIT_REQUIRED')
        self.assertEqual(project(replace(f,gross_remaining=None)).kind,'REDUCE_OBLIGATION')

    def test_invalid_numeric_facts(self):
        for gross in (1.2,D('NaN'),D('Infinity')):
            with self.assertRaises(ValueError):project(Facts('LONG','RANGE',gross_remaining=gross))
        with self.assertRaises(ValueError):project(Facts('LONG','RANGE',nonpositive_range_days=True))

if __name__=='__main__':unittest.main()
