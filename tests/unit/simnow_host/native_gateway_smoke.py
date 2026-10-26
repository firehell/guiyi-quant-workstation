"""Run with isolated Mac SDK Python; real structs, fake API, zero network."""

from pathlib import Path
import importlib.util
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

ROOT = Path(__file__).parents[3]
spec = importlib.util.spec_from_file_location(
    "native_gateway_smoke_target", ROOT / "scripts/broker/simnow_native_gateway.py"
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
t = m.tdapi


class Api:
    def __init__(self, g):
        self.g = g
        self.calls = []

    def ReqQryInstrument(self, req, rid):
        self.calls.append(("instrument", req, rid))
        row = t.CThostFtdcInstrumentField()
        row.InstrumentID = "rb2701"
        row.ExchangeID = "SHFE"
        row.ProductID = "rb"
        self.g.OnRspQryInstrument(row, t.CThostFtdcRspInfoField(), rid, True)
        return 0

    def ReqQryInstrumentMarginRate(self, req, rid):
        self.calls.append(("margin", req, rid))
        row = t.CThostFtdcInstrumentMarginRateField()
        row.BrokerID = "9999"
        row.InvestorID = ""
        row.InvestorRange = "1"
        row.InstrumentID = req.InstrumentID
        row.ExchangeID = "SHFE"
        row.HedgeFlag = "1"
        row.IsRelative = 0
        row.LongMarginRatioByMoney = 0.1
        row.ShortMarginRatioByMoney = 0.1
        self.g.OnRspQryInstrumentMarginRate(row, t.CThostFtdcRspInfoField(), rid, True)
        return 0

    def ReqQryDepthMarketData(self, req, rid):
        self.calls.append(("book", req, rid))
        row = t.CThostFtdcDepthMarketDataField()
        row.InstrumentID = req.InstrumentID
        self.g.OnRspQryDepthMarketData(row, t.CThostFtdcRspInfoField(), rid, True)
        return 0

    def ReqQrySettlementInfoConfirm(self, req, rid):
        self.calls.append(("settlement", req, rid))
        row = t.CThostFtdcSettlementInfoConfirmField()
        row.BrokerID = "9999"
        row.InvestorID = "000000"
        row.ConfirmDate = "20261027"
        self.g.OnRspQrySettlementInfoConfirm(row, t.CThostFtdcRspInfoField(), rid, True)
        return 0


class Compatibility(unittest.TestCase):
    def setUp(self):
        self.g = m.Gateway("000000", "fixture-only")
        self.g.api = Api(self.g)
        self.pause = patch.object(m.time, "sleep", lambda _: None)
        self.pause.start()

    def tearDown(self):
        self.pause.stop()

    def test_instrument_sdk_request_and_rows(self):
        rows = self.g.query("instrument", exchange="SHFE", product="rb")
        self.assertEqual(rows[0]["InstrumentID"], "rb2701")
        self.assertEqual(self.g.api.calls[0][1].ProductID, "rb")
        self.assertEqual(self.g.api.calls[0][1].ExchangeID, "SHFE")
        self.assertIsInstance(self.g.api.calls[0][1], t.CThostFtdcQryInstrumentField)

    def test_margin_all_investors_scope_is_explicit_and_not_another_account(self):
        rows = self.g.query("margin", "rb2701")
        self.assertEqual(rows[0]["InvestorRange"], "1")
        self.assertNotIn("InvestorID", rows[0])
        self.assertEqual(self.g.api.calls[0][1].InvestorID, "000000")

    def test_book_is_execution_query_not_historical_subscription(self):
        self.g.query("book", "rb2701")
        self.assertIsInstance(
            self.g.api.calls[0][1], t.CThostFtdcQryDepthMarketDataField
        )
        self.assertEqual(len(self.g.api.calls), 1)

    def test_settlement_query_never_calls_confirm(self):
        self.g.query("settlement")
        self.assertEqual([v[0] for v in self.g.api.calls], ["settlement"])

    def test_diagnostics_zero_callback_timeout_stops_without_retry(self):
        calls = []
        self.g.api.ReqQryInstrument = lambda req, rid: calls.append(rid) or 0
        with patch.object(self.g.extra_done, "wait", return_value=False):
            with self.assertRaisesRegex(ValueError, "NATIVE_FACT_QUERY_FAILED"):
                self.g.query("instrument", exchange="SHFE", product="rb")
        d = self.g.query_diagnostics[-1]
        self.assertEqual(len(calls), 1)
        self.assertTrue(d["timed_out"])
        self.assertEqual(d["response_count"], 0)
        self.assertFalse(d["terminal_response_seen"])
        with self.assertRaises(ValueError):
            self.g.query("settlement")
        self.assertEqual(len(calls), 1)

    def test_diagnostics_partial_rows_without_terminator_remain_failed(self):
        def partial(req, rid):
            row = t.CThostFtdcInstrumentField()
            row.ExchangeID = "SHFE"
            row.ProductID = "rb"
            self.g.OnRspQryInstrument(row, t.CThostFtdcRspInfoField(), rid, False)
            return 0
        self.g.api.ReqQryInstrument = partial
        with patch.object(self.g.extra_done, "wait", return_value=False):
            with self.assertRaises(ValueError):
                self.g.query("instrument", exchange="SHFE", product="rb")
        d = self.g.query_diagnostics[-1]
        self.assertEqual(d["data_row_count"], 1)
        self.assertTrue(d["timed_out"])
        self.assertFalse(d["complete"])
        self.assertFalse(d["terminal_response_seen"])

    def test_diagnostics_sdk_rejection_does_not_wait_or_retry(self):
        self.g.api.ReqQryInstrument = lambda req, rid: -2
        with patch.object(self.g.extra_done, "wait") as wait:
            with self.assertRaises(ValueError):
                self.g.query("instrument", exchange="SHFE", product="rb")
        wait.assert_not_called()
        d = self.g.query_diagnostics[-1]
        self.assertEqual(d["sdk_return_code"], -2)
        self.assertFalse(d["timed_out"])
        self.assertFalse(d["complete"])

    def test_diagnostics_server_rejection_no_raw_message(self):
        def rejected(req, rid):
            info = t.CThostFtdcRspInfoField()
            info.ErrorID = 7
            info.ErrorMsg = "private-example"
            self.g.OnRspQryInstrument(None, info, rid, True)
            return 0
        self.g.api.ReqQryInstrument = rejected
        with self.assertRaises(ValueError):
            self.g.query("instrument", exchange="SHFE", product="rb")
        d = self.g.query_diagnostics[-1]
        self.assertEqual(d["callback_error"], "NATIVE_FACT_QUERY_REJECTED")
        self.assertEqual(d["response_count"], 1)
        self.assertTrue(d["terminal_response_seen"])
        self.assertNotIn("private-example", str(d))
        self.assertFalse(d["complete"])

    def test_diagnostics_success_contains_no_account_or_raw_rows(self):
        self.g.query("margin", "rb2701")
        d = self.g.query_diagnostics[-1]
        self.assertTrue(d["complete"])
        self.assertEqual(d["data_row_count"], 1)
        self.assertFalse(d["timed_out"])
        self.assertNotIn("000000", str(d))
        self.assertNotIn("InvestorID", str(d))

    def test_unbounded_instrument_query_rejected_before_sdk(self):
        with self.assertRaisesRegex(ValueError, "BOUNDED_INSTRUMENT_QUERY_REQUIRED"):
            self.g.query("instrument")
        self.assertEqual(self.g.api.calls, [])

    def test_wrong_product_response_fails_closed(self):
        def wrong(req, rid):
            row = t.CThostFtdcInstrumentField()
            row.ExchangeID = "SHFE"
            row.ProductID = "cu"
            self.g.OnRspQryInstrument(row, t.CThostFtdcRspInfoField(), rid, True)
            return 0
        self.g.api.ReqQryInstrument = wrong
        with self.assertRaises(ValueError):
            self.g.query("instrument", exchange="SHFE", product="rb")
        d = self.g.query_diagnostics[-1]
        self.assertEqual(d["callback_error"], "NATIVE_FACT_SCOPE_MISMATCH")
        self.assertEqual(d["data_row_count"], 0)

    def test_disconnect_during_gap_does_not_send_query(self):
        with patch.object(m.time, "sleep", lambda _: self.g.OnFrontDisconnected(1)):
            with self.assertRaisesRegex(ValueError, "NATIVE_GATEWAY_FAILED"):
                self.g.query("instrument", exchange="SHFE", product="rb")
        self.assertEqual(self.g.api.calls, [])

    def test_disconnect_during_request_construction_prevents_send(self):
        real = t.CThostFtdcQryInstrumentField
        def construct():
            self.g.OnFrontDisconnected(1)
            return real()
        with patch.object(t, "CThostFtdcQryInstrumentField", construct):
            with self.assertRaisesRegex(ValueError, "NATIVE_GATEWAY_FAILED"):
                self.g.query("instrument", exchange="SHFE", product="rb")
        self.assertEqual(self.g.api.calls, [])

    def test_login_native_identity_exists_before_completion_waiter(self):
        row = t.CThostFtdcRspUserLoginField()
        row.BrokerID = "9999"
        row.UserID = "000000"
        row.TradingDay = "20261027"
        row.FrontID = 1
        row.SessionID = 2
        row.MaxOrderRef = "10"
        self.g.OnRspUserLogin(row, t.CThostFtdcRspInfoField(), 2, True)
        self.assertTrue(self.g.login_done.is_set())
        self.assertEqual(
            self.g.native_session, dict(front_id=1, session_id=2, max_order_ref=10)
        )

    def test_query_wrong_response_identity_stops(self):
        self.g.extra = dict(kind="margin", id=1, rows=[], complete=False)
        row = t.CThostFtdcInstrumentMarginRateField()
        row.BrokerID = "9999"
        row.InvestorID = "other"
        row.InvestorRange = "3"
        self.g.OnRspQryInstrumentMarginRate(row, t.CThostFtdcRspInfoField(), 1, True)
        self.assertTrue(self.g.failed)

    def test_callback_buffer_copies_ephemeral_struct(self):
        row = t.CThostFtdcOrderField()
        row.OrderRef = "10"
        self.g.OnRtnOrder(row)
        row.OrderRef = "11"
        self.assertEqual(self.g.buffer[0][1].OrderRef, "10")

    def test_callback_errors_never_expose_native_exception(self):
        def bad(*args):
            raise RuntimeError("private-example")

        self.g.execution_adapter = NS(order_callback=bad)
        self.g.OnRtnOrder(t.CThostFtdcOrderField())
        self.assertTrue(self.g.failed)
        self.assertNotIn("private-example", str(self.g.result))


if __name__ == "__main__":
    unittest.main()
