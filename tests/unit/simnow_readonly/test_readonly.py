"""Protocol fixtures only: no Init, provider connection, or real credentials."""

import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace as Obj
import unittest

PATH = Path(__file__).resolve().parents[3] / "scripts/broker/simnow_readonly.py"
spec = importlib.util.spec_from_file_location("simnow_readonly", PATH)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
USER = "000000"
DAY = "20261023"


def row(kind, **changes):
    values = {
        name: (0 if typ in ("i", "d") else "") for name, typ in m.FIELDS[kind].items()
    }
    values.update(BrokerID="9999", InvestorID=USER, AccountID=USER, TradingDay=DAY)
    if kind == "funds":
        values.update(CurrencyID="CNY", Balance=20000000, Available=20000000)
    else:
        values.update(InstrumentID="ag2612", ExchangeID="SHFE")
    if kind == "positions":
        values.update(PosiDirection="2", PositionDate="1", HedgeFlag="1")
    if kind == "orders":
        values.update(OrderRef="1", OrderStatus="5", FrontID=1, SessionID=1)
    if kind == "trades":
        values.update(TradeID="1", Direction="0", Volume=1)
    values.update(changes)
    return Obj(**values)


class FixtureApi:
    def __init__(self, probe, data=None):
        self.probe = probe
        self.data = data or {"funds": [row("funds")]}
        self.calls = []
        self.return_code = 0
        self.error_code = 0
        self.skip_last = False
        self.mutate_second = False

    def ReqAuthenticate(self, req, identity):
        self.calls.append("authenticate")
        return 0

    def ReqUserLogin(self, req, identity, length, info):
        assert length == 0 and info is None
        self.calls.append("login")
        return 0

    def query(self, kind, req, identity):
        self.calls.append(kind)
        if self.return_code:
            return self.return_code
        data = self.data.get(kind, [])
        if self.mutate_second and identity >= 120 and kind == "funds":
            data = [row("funds", Available=19999999)]
        for record in data:
            self.probe.receive(
                kind, record, Obj(ErrorID=self.error_code), identity, False
            )
        if not self.skip_last:
            self.probe.receive(kind, None, Obj(ErrorID=self.error_code), identity, True)
        return 0

    def ReqQryTradingAccount(self, req, identity):
        return self.query("funds", req, identity)

    def ReqQryInvestorPosition(self, req, identity):
        return self.query("positions", req, identity)

    def ReqQryOrder(self, req, identity):
        return self.query("orders", req, identity)

    def ReqQryTrade(self, req, identity):
        return self.query("trades", req, identity)


class ReadOnlyTests(unittest.TestCase):
    def probe(self, data=None, logged=True):
        p = m.Probe(USER, "dummy-not-a-real-password")
        p.api = FixtureApi(p, data)
        if logged:
            p.day = DAY
            p.result.update(
                login_passed=True, authentication_passed=True, trading_day=DAY
            )
        return p

    def collect(self, p):
        p.collect(gap=0, query_timeout=0)
        return p.result

    def test_environment_is_explicitly_bound_to_fixed_front(self):
        p = m.Probe(USER, "dummy-not-a-real-password", environment="first")
        self.assertEqual(p.result["environment"], "SIMNOW_FIRST")
        self.assertEqual(p.front, "tcp://182.254.243.31:30001")
        self.assertEqual(p.result["front"], p.front)
        self.assertFalse(p.result["execution_eligible"])

    def test_arbitrary_environment_or_address_is_rejected(self):
        for value in ("live", "tcp://example.invalid:1", "FIRST"):
            with self.assertRaises(ValueError):
                m.Probe(USER, "dummy-not-a-real-password", environment=value)

    def test_first_environment_does_not_fallback_on_disconnect(self):
        p = m.Probe(USER, "dummy-not-a-real-password", environment="first")
        p.api = FixtureApi(p)
        p.OnFrontDisconnected(4097)
        p.OnFrontConnected()
        self.assertEqual(p.api.calls, [])
        self.assertEqual(p.result["front"], "tcp://182.254.243.31:30001")

    def test_first_snapshot_does_not_claim_test_copy_or_ledger(self):
        p = m.Probe(USER, "dummy-not-a-real-password", environment="first")
        p.api = FixtureApi(p)
        p.day = DAY
        p.result["login_passed"] = True
        result = self.collect(p)
        self.assertEqual(result["source_scope"], "FIRST_ENVIRONMENT_READBACK")
        self.assertFalse(result["ledger_reconciled"])
        test = self.probe()
        self.assertNotEqual(
            result["account_fingerprint"], test.result["account_fingerprint"]
        )

    def test_reset_acceptance_rejects_test_environment_copy(self):
        p = self.probe()
        self.collect(p)
        check = m.check_funding_reset(p.result, "100000", "20261027")
        self.assertFalse(check["passed"])
        self.assertIn("FIRST_ENVIRONMENT_REQUIRED", check["reasons"])

    def test_reset_acceptance_rejects_early_trading_day(self):
        p = self.probe()
        self.collect(p)
        p.result["environment"] = "SIMNOW_FIRST"
        p.result["front"] = "tcp://182.254.243.31:30001"
        p.result["source_scope"] = "FIRST_ENVIRONMENT_READBACK"
        check = m.check_funding_reset(p.result, "100000", "20261027")
        self.assertIn("EFFECTIVE_TRADING_DAY_NOT_REACHED", check["reasons"])

    def test_reset_acceptance_requires_exact_funds_and_flat_account(self):
        p = m.Probe(USER, "dummy", environment="first")
        p.api = FixtureApi(
            p,
            {
                "funds": [
                    row(
                        "funds", TradingDay="20261027", Balance=100000, Available=100000
                    )
                ]
            },
        )
        p.day = "20261027"
        p.result.update(
            login_passed=True, authentication_passed=True, trading_day=p.day
        )
        self.collect(p)
        check = m.check_funding_reset(p.result, "100000", "20261027")
        self.assertTrue(check["passed"])
        self.assertFalse(p.result["execution_eligible"])
        p.result["rounds"][1]["queries"]["funds"]["rows"][0]["Available"] = "99999"
        self.assertFalse(
            m.check_funding_reset(p.result, "100000", "20261027")["passed"]
        )

    def test_reset_acceptance_never_accepts_incomplete_readback(self):
        p = self.probe()
        self.assertFalse(
            m.check_funding_reset(p.result, "100000", "20261027")["passed"]
        )

    def test_complete_empty_account_requires_all_eight_queries(self):
        p = self.probe()
        result = self.collect(p)
        self.assertEqual(result["status"], "READ_ONLY_COMPLETE")
        self.assertEqual(p.api.calls, list(m.FIELDS) * 2)
        self.assertTrue(result["account_empty_observed"])
        self.assertFalse(result["execution_eligible"])
        self.assertFalse(result["ledger_reconciled"])
        self.assertFalse(result["atomic_snapshot"])
        self.assertTrue(
            all(q["complete"] for r in result["rounds"] for q in r["queries"].values())
        )

    def test_margin_without_position_is_not_an_empty_account(self):
        p = self.probe({"funds": [row("funds", CurrMargin=1000, FrozenMargin=500)]})
        result = self.collect(p)
        self.assertFalse(result["account_empty_observed"])
        self.assertIn("MARGIN_WITHOUT_REPORTED_POSITION", result["inventory_warnings"])

    def test_frozen_commission_prevents_empty_account(self):
        p = self.probe({"funds": [row("funds", FrozenCommission=10)]})
        result = self.collect(p)
        self.assertFalse(result["account_empty_observed"])
        self.assertIn(
            "FROZEN_FUNDS_WITHOUT_WORKING_ORDER", result["inventory_warnings"]
        )

    def test_missing_completion_never_means_zero_rows(self):
        p = self.probe()
        p.api.skip_last = True
        result = self.collect(p)
        self.assertEqual(result["status"], "QUERY_TIMEOUT")
        self.assertNotIn("account_empty_observed", result)
        self.assertEqual(p.api.calls, ["funds"])

    def test_empty_funds_is_invalid(self):
        p = self.probe({"funds": []})
        self.assertEqual(self.collect(p)["status"], "FUNDS_ROW_COUNT_INVALID")

    def test_query_error_stops_remaining_queries(self):
        p = self.probe()
        p.api.error_code = 7
        self.assertEqual(self.collect(p)["status"], "QUERY_REJECTED")
        self.assertEqual(p.api.calls, ["funds"])

    def test_send_not_accepted_does_not_wait(self):
        p = self.probe()
        p.api.return_code = -2
        self.assertEqual(self.collect(p)["status"], "REQUEST_NOT_ACCEPTED")
        self.assertFalse(p.result["requests"][0]["accepted"])

    def test_multipart_response_retains_rows(self):
        p = self.probe(
            {
                "funds": [row("funds")],
                "positions": [
                    row("positions", PosiDirection="2", Position=1),
                    row("positions", PosiDirection="3", Position=1),
                    row("positions", PosiDirection="2", PositionDate="2", Position=2),
                ],
            }
        )
        result = self.collect(p)
        self.assertEqual(result["status"], "READ_ONLY_COMPLETE")
        self.assertEqual(result["position_rows_nonzero"], 3)
        self.assertFalse(result["account_empty_observed"])

    def test_identity_mismatch_is_not_persisted(self):
        p = self.probe({"funds": [row("funds", AccountID="other-account")]})
        self.assertEqual(self.collect(p)["status"], "LOCAL_ERROR")
        self.assertNotIn("other-account", str(p.result))

    def test_wrong_trading_day_blocked(self):
        p = self.probe({"funds": [row("funds", TradingDay="20261022")]})
        self.assertEqual(self.collect(p)["status"], "LOCAL_ERROR")

    def test_nan_money_is_rejected(self):
        p = self.probe({"funds": [row("funds", Balance=float("nan"))]})
        self.assertEqual(self.collect(p)["status"], "LOCAL_ERROR")

    def test_float_not_used_for_money_serialization(self):
        r = m.checked_row("funds", row("funds", Available=12.34), USER, DAY)
        self.assertEqual(r["Available"], "12.34")
        self.assertNotIn("AccountID", r)

    def test_duplicate_rows_blocked(self):
        p = self.probe(
            {"funds": [row("funds")], "positions": [row("positions"), row("positions")]}
        )
        self.assertEqual(self.collect(p)["status"], "DUPLICATE_QUERY_ROW")

    def test_changed_second_pass_is_not_stable(self):
        p = self.probe()
        p.api.mutate_second = True
        result = self.collect(p)
        self.assertEqual(result["status"], "SNAPSHOT_CHANGED")
        self.assertFalse(result["account_empty_observed"])
        self.assertNotEqual(*result["round_hashes"])

    def test_unknown_order_is_counted_as_blocking(self):
        p = self.probe(
            {"funds": [row("funds")], "orders": [row("orders", OrderStatus="a")]}
        )
        result = self.collect(p)
        self.assertEqual(result["working_or_unknown_orders"], 1)
        self.assertFalse(result["account_empty_observed"])

    def test_cancelled_order_is_retained_and_not_working(self):
        p = self.probe(
            {"funds": [row("funds")], "orders": [row("orders", OrderStatus="5")]}
        )
        result = self.collect(p)
        self.assertEqual(result["working_or_unknown_orders"], 0)
        self.assertEqual(len(result["rounds"][0]["queries"]["orders"]["rows"]), 1)

    def test_trade_rows_are_not_fabricated_as_positions(self):
        p = self.probe({"funds": [row("funds")], "trades": [row("trades")]})
        result = self.collect(p)
        self.assertTrue(result["account_empty_observed"])
        self.assertFalse(result["ledger_reconciled"])

    def test_incorrect_request_id_fails_closed(self):
        p = self.probe()
        p.begin_query("funds", 110)
        p.receive("positions", row("positions"), None, 999, True)
        self.assertEqual(p.result["status"], "UNEXPECTED_QUERY_RESPONSE")

    def test_disconnect_stops_without_relogin(self):
        p = self.probe()
        p.OnFrontDisconnected(4097)
        p.OnFrontConnected()
        self.assertEqual(p.result["status"], "FRONT_DISCONNECTED")
        self.assertEqual(p.api.calls, [])

    def test_auth_and_login_once(self):
        p = self.probe(logged=False)
        p.OnFrontConnected()
        p.OnFrontConnected()
        p.OnRspAuthenticate(Obj(), Obj(ErrorID=0), 1, True)
        p.OnRspAuthenticate(Obj(), Obj(ErrorID=0), 1, True)
        self.assertEqual(p.api.calls, ["authenticate", "login"])
        p.OnRspUserLogin(
            Obj(BrokerID="9999", UserID=USER, TradingDay=DAY), Obj(ErrorID=0), 2, True
        )
        self.assertTrue(p.login_done.is_set())
        self.assertFalse(p.failed)
        self.assertEqual(p.password, "")

    def test_login_wrong_identity(self):
        p = self.probe(logged=False)
        p.OnRspUserLogin(
            Obj(BrokerID="9999", UserID="wrong", TradingDay=DAY),
            Obj(ErrorID=0),
            2,
            True,
        )
        self.assertEqual(p.result["status"], "LOGIN_IDENTITY_MISMATCH")

    def test_callback_exception_contains_no_text(self):
        p = self.probe()

        def failure():
            raise TypeError("PRIVATE-VALUE-DO-NOT-PRINT")

        p.guard("fixture", failure)
        self.assertEqual(p.result["exception_type"], "TypeError")
        self.assertNotIn("PRIVATE-VALUE", str(p.result))

    def test_no_queries_without_login(self):
        p = self.probe(logged=False)
        p.begin_query("funds", 110)
        self.assertTrue(p.failed)
        self.assertEqual(p.api.calls, [])

    def test_request_allowlist(self):
        tree = ast.parse(PATH.read_text())
        attrs = {
            n.attr
            for n in ast.walk(tree)
            if isinstance(n, ast.Attribute) and n.attr.startswith("Req")
        }
        self.assertEqual(
            attrs,
            {
                "ReqAuthenticate",
                "ReqUserLogin",
                "ReqQryTradingAccount",
                "ReqQryInvestorPosition",
                "ReqQryOrder",
                "ReqQryTrade",
            },
        )


if __name__ == "__main__":
    unittest.main()
