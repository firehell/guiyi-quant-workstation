from collections import OrderedDict
from unittest import TestCase

from performance import calculate, daily_returns


class PerformanceTest(TestCase):
    days = ("2026-01-05", "2026-01-06")
    settlements = dict(zip(days, ("110", "99")))

    def test_pnl_and_drawdown_match_independent_arithmetic(self):
        result = calculate(daily_returns(self.days, self.settlements, "100", external_cash_flow=0))
        self.assertAlmostEqual(result["cumulative"], -0.01)
        self.assertAlmostEqual(result["max_drawdown"], 0.1)
        self.assertEqual(result["drawdown_span"], {"trading_days": 1, "ongoing": True})
        self.assertEqual(result["daily_win_rate"], 0.5)

    def test_initial_capital_is_peak_until_recovery(self):
        equity = dict(zip(self.days, ("80", "100")))
        result = calculate(daily_returns(self.days, equity, "100", external_cash_flow=0))
        self.assertAlmostEqual(result["max_drawdown"], 0.2)
        self.assertEqual(result["drawdown_span"], {"trading_days": 2, "ongoing": False})

    def test_zero_denominator_has_no_ratio(self):
        equity = dict.fromkeys(self.days, "100")
        result = calculate(daily_returns(self.days, equity, "100", external_cash_flow=0))
        for name in ("sharpe", "sortino", "calmar"):
            self.assertIsNone(result[name])

    def test_missing_day_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "SETTLEMENT_COVERAGE_MISMATCH"):
            daily_returns(self.days, {self.days[1]: "99"}, "100", external_cash_flow=0)

    def test_reversed_settlements_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "SETTLEMENT_COVERAGE_MISMATCH"):
            daily_returns(self.days, OrderedDict(reversed(list(self.settlements.items()))),
                          "100", external_cash_flow=0)

    def test_cash_flow_requires_a_supported_policy(self):
        for flow in (None, 500):
            with self.assertRaisesRegex(ValueError, "CASH_FLOW_ADJUSTED_SERIES_REQUIRED"):
                daily_returns(self.days, self.settlements, "100", external_cash_flow=flow)

    def test_exactly_one_hundred_percent_is_ambiguous_to_quantstats(self):
        equity = dict.fromkeys(self.days, "200")
        returns = daily_returns(self.days, equity, "100", external_cash_flow=0)
        with self.assertRaisesRegex(ValueError, "QUANTSTATS_RETURN_INPUT_AMBIGUOUS"):
            calculate(returns)
