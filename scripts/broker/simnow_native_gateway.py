"""Optional CTP gateway; imported only by isolated controlled CLI, never Runtime."""

from datetime import datetime, UTC
from contextlib import contextmanager
from types import SimpleNamespace
import importlib.util
from pathlib import Path
import threading
import time
import re

_SOURCE = Path(__file__).with_name("simnow_readonly.py")
_spec = importlib.util.spec_from_file_location("guiyi_simnow_readonly", _SOURCE)
_readonly = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_readonly)
tdapi = _readonly.tdapi

_FIELDS = {
    "instrument": (
        "InstrumentID",
        "ExchangeID",
        "ProductID",
        "ProductClass",
        "DeliveryYear",
        "DeliveryMonth",
        "OpenDate",
        "ExpireDate",
        "StartDelivDate",
        "IsTrading",
        "VolumeMultiple",
        "PriceTick",
        "MinLimitOrderVolume",
        "MaxLimitOrderVolume",
    ),
    "margin": (
        "InstrumentID",
        "ExchangeID",
        "BrokerID",
        "InvestorID",
        "InvestorRange",
        "HedgeFlag",
        "IsRelative",
        "LongMarginRatioByMoney",
        "LongMarginRatioByVolume",
        "ShortMarginRatioByMoney",
        "ShortMarginRatioByVolume",
    ),
    "commission": (
        "InstrumentID",
        "ExchangeID",
        "BrokerID",
        "InvestorID",
        "InvestorRange",
        "OpenRatioByMoney",
        "OpenRatioByVolume",
        "CloseRatioByMoney",
        "CloseRatioByVolume",
        "CloseTodayRatioByMoney",
        "CloseTodayRatioByVolume",
    ),
    "book": (
        "InstrumentID",
        "ExchangeID",
        "TradingDay",
        "ActionDay",
        "UpdateTime",
        "UpdateMillisec",
        "BidPrice1",
        "AskPrice1",
        "BidVolume1",
        "AskVolume1",
        "LowerLimitPrice",
        "UpperLimitPrice",
    ),
    "settlement": ("BrokerID", "InvestorID", "ConfirmDate", "ConfirmTime"),
}
_TYPES = {
    "instrument": "CThostFtdcQryInstrumentField",
    "margin": "CThostFtdcQryInstrumentMarginRateField",
    "commission": "CThostFtdcQryInstrumentCommissionRateField",
    "book": "CThostFtdcQryDepthMarketDataField",
    "settlement": "CThostFtdcQrySettlementInfoConfirmField",
    "confirm": "CThostFtdcSettlementInfoConfirmField",
}
_METHODS = {
    "instrument": "ReqQryInstrument",
    "margin": "ReqQryInstrumentMarginRate",
    "commission": "ReqQryInstrumentCommissionRate",
    "book": "ReqQryDepthMarketData",
    "settlement": "ReqQrySettlementInfoConfirm",
    "confirm": "ReqSettlementInfoConfirm",
}


class Gateway(_readonly.Probe):
    def __init__(self, user, password, *, initial_funds_timeout=15):
        if type(initial_funds_timeout) is not int or not 15 <= initial_funds_timeout <= 45:
            raise ValueError("INITIAL_FUNDS_TIMEOUT_BOUND_INVALID")
        super().__init__(user, password, environment="first")
        self.initial_funds_timeout = initial_funds_timeout
        self._initial_funds_grace_pending = True
        self.execution_adapter = None
        self.native_session = None
        self.extra = None
        self.extra_done = threading.Event()
        self.extra_counter = 30000
        self.query_diagnostics = []
        self.buffer = []
        self.monitor_progress = None
        self._observe_input_scope = False

    def OnRspUserLogin(self, rsp, info, request_id, last):
        if (
            request_id == 2
            and last
            and rsp is not None
            and info is not None
            and int(info.ErrorID) == 0
        ):
            ref = rsp.MaxOrderRef.strip() or "0"
            if not ref.isascii() or not ref.isdigit():
                self.fail("MAX_ORDER_REF_INVALID")
                return
            self.native_session = dict(
                front_id=int(rsp.FrontID),
                session_id=int(rsp.SessionID),
                max_order_ref=int(ref),
            )
        super().OnRspUserLogin(rsp, info, request_id, last)

    def attach(self, adapter, snapshot):
        with self.lock:
            self.execution_adapter = adapter
            buffered = tuple(self.buffer)
            self.buffer.clear()
        for kind, row, received in buffered:
            if received <= snapshot.at:
                data = snapshot.data
                present = (
                    any(
                        (r["OrderRef"], r["FrontID"], r["SessionID"])
                        == (row.OrderRef, row.FrontID, row.SessionID)
                        for r in data["orders"]
                    )
                    if kind == "order"
                    else any(
                        (r["TradeID"], r["ExchangeID"], r["Direction"])
                        == (row.TradeID, row.ExchangeID, row.Direction)
                        for r in data["trades"]
                    )
                )
                if present:
                    continue
            try:
                getattr(adapter, kind + "_callback")(row, received)
            except Exception:
                self.fail("STARTUP_NATIVE_ACTIVITY_UNEXPLAINED")

    def _stage(self, kind, row):
        with self.lock:
            try:
                fields = _readonly.FIELDS["orders" if kind == "order" else "trades"]
                names = tuple(fields) + ("BrokerID", "InvestorID", "OrderRef")
                payload = {k: getattr(row, k) for k in names}
                when = datetime.now(UTC)
                if self.execution_adapter is None:
                    self.buffer.append((kind, SimpleNamespace(**payload), when))
                    if len(self.buffer) > 10000:
                        self.fail("CALLBACK_BUFFER_LIMIT")
                else:
                    getattr(self.execution_adapter, kind + "_callback")(
                        SimpleNamespace(**payload), when
                    )
            except Exception:
                self.fail("EXECUTION_CALLBACK_BLOCKED")

    def OnRtnOrder(self, row):
        self._stage("order", row)

    def OnRtnTrade(self, row):
        self._stage("trade", row)

    def OnRspOrderInsert(self, row, info, request_id, last):
        if self.execution_adapter is None:
            self.fail("UNEXPECTED_ORDER_RESPONSE")
            return
        try:
            self.execution_adapter.response(
                "SUBMIT",
                row,
                int(info.ErrorID) if info else -1,
                request_id,
                datetime.now(UTC),
            )
        except Exception:
            self.fail("EXECUTION_RESPONSE_BLOCKED")

    def OnErrRtnOrderInsert(self, row, info):
        self.OnRspOrderInsert(row, info, row.RequestID, True)

    def OnRspOrderAction(self, row, info, request_id, last):
        if self.execution_adapter is None:
            self.fail("UNEXPECTED_CANCEL_RESPONSE")
            return
        try:
            self.execution_adapter.response(
                "CANCEL",
                row,
                int(info.ErrorID) if info else -1,
                request_id,
                datetime.now(UTC),
            )
        except Exception:
            self.fail("EXECUTION_RESPONSE_BLOCKED")

    def OnErrRtnOrderAction(self, row, info):
        self.OnRspOrderAction(row, info, row.RequestID, True)

    def OnFrontDisconnected(self, reason):
        if self.execution_adapter:
            self.execution_adapter.disconnected(datetime.now(UTC))
        super().OnFrontDisconnected(reason)
        self.extra_done.set()

    def inventory_diagnostics(self):
        """Protocol counters only; never serialize native account rows or identities."""
        with self.lock:
            result = self.result
            status = result.get("status", "UNKNOWN")
            stage = result.get("error_stage")
            kinds = ("funds", "positions", "orders", "trades")
            stages = {"authenticate", "login", "connect", "disconnect", "query_send", "response_error", "authenticate_response", "login_response", "api_error"} | set(kinds) | {"query_response_" + k for k in kinds}
            value = dict(
                status=status if isinstance(status, str) and re.fullmatch(r"[A-Z_0-9]{1,64}", status) else "UNKNOWN",
                authentication_passed=result.get("authentication_passed") is True,
                login_passed=result.get("login_passed") is True,
                error_stage=stage if stage in stages else None,
                requests=[], queries=[], request_count=len(result.get("requests", ())),
            )
            for key in ("error_id", "return_code"):
                if type(result.get(key)) is int:
                    value[key] = result[key]
            timeout = result.get("timeout_kind")
            if timeout in ("ZERO_QUERY_CALLBACKS", "QUERY_TERMINATOR_MISSING", "TERMINAL_AT_TIMEOUT_BOUNDARY"):
                value["timeout_kind"] = timeout
            for receipt in result.get("requests", ())[-16:]:
                if receipt.get("kind") in {"authenticate", "login", *kinds}:
                    value["requests"].append({k: receipt[k] for k in ("kind", "request_id", "accepted", "return_code") if k in receipt})
            for record in result.get("rounds", ()):
                for kind, query in record.get("queries", {}).items():
                    if kind not in kinds:
                        continue
                    diagnostic = query.get("diagnostics", {})
                    item = dict(round=record["round"], kind=kind, complete=query.get("complete") is True)
                    item.update({k: diagnostic[k] for k in ("response_count", "data_row_count", "terminal_response_seen", "timed_out", "timeout_budget_seconds", "elapsed_seconds") if k in diagnostic})
                    value["queries"].append(item)
            return value

    def snapshot(self):
        if self.monitor_progress is not None:
            self.monitor_progress()
        if self.failed:
            raise ValueError("NATIVE_GATEWAY_FAILED")
        self.result["rounds"] = []
        first = self._initial_funds_grace_pending
        self._initial_funds_grace_pending = False
        if first and self.initial_funds_timeout != 15:
            self.collect(initial_funds_timeout=self.initial_funds_timeout)
        else:
            self.collect()
        if self.failed or self.result["status"] != "READ_ONLY_COMPLETE":
            raise ValueError("NATIVE_STABLE_SNAPSHOT_REQUIRED")
        # Copy sanitized values only; user/password and raw objects never leave gateway.
        import json

        return json.loads(json.dumps(self.result))

    @contextmanager
    def observe_input_queries(self):
        """Optional observe inputs only; never account readback or order requests."""
        with self.lock:
            if self._observe_input_scope:
                raise ValueError('NATIVE_QUERY_SCOPE_REENTRANT')
            self._observe_input_scope = True
        try:
            yield
        finally:
            with self.lock:
                self._observe_input_scope = False

    def query(self, kind, instrument="", *, exchange="", product=""):
        if self.monitor_progress is not None:
            self.monitor_progress()
        if self.failed:
            raise ValueError("NATIVE_GATEWAY_FAILED")
        if kind == "instrument" and (
            exchange not in ("SHFE", "DCE", "CZCE", "CFFEX", "INE", "GFEX")
            or not product.isascii() or not product.isalpha() or not 1 <= len(product) <= 3
        ):
            raise ValueError("BOUNDED_INSTRUMENT_QUERY_REQUIRED")
        if kind in ("margin", "commission") and (
            exchange not in ("SHFE", "DCE", "CZCE", "CFFEX", "INE", "GFEX")
            or not instrument.isascii() or not instrument.isalnum() or len(instrument) > 12
        ):
            raise ValueError("BOUNDED_RATE_QUERY_REQUIRED")
        book_timing = None
        if kind == "book":
            book_timing = dict(book_call_started_at=datetime.now(UTC).isoformat(),
                               book_target_received_at=None, book_terminal_received_at=None)
            book_started = time.monotonic()
        time.sleep(1.1)
        if self.failed:
            raise ValueError("NATIVE_GATEWAY_FAILED")
        req = getattr(tdapi, _TYPES[kind])()
        if kind in ("margin", "commission") and not hasattr(req, "ExchangeID"):
            raise ValueError("NATIVE_RATE_REQUEST_EXCHANGE_UNSUPPORTED")
        for field, value in (
            ("BrokerID", "9999"),
            ("InvestorID", self.user),
            ("InstrumentID", instrument),
            ("HedgeFlag", "1"),
            ("ExchangeID", exchange),
            ("ProductID", product),
        ):
            if hasattr(req, field) and (field not in ("ExchangeID", "ProductID") or kind == "instrument" or (field == "ExchangeID" and kind in ("margin", "commission"))):
                setattr(req, field, value)
        started = time.monotonic()
        result = None
        timed_out = False
        request_id = None
        try:
            with self.lock:
                if self.failed:
                    raise ValueError("NATIVE_GATEWAY_FAILED")
                self.extra_counter += 1
                request_id = self.extra_counter
                self.extra_done.clear()
                self.extra = dict(
                    kind=kind, id=request_id, rows=[], complete=False,
                    exchange=exchange, product=product, response_count=0,
                    terminal_response_seen=False, callback_error=None,
                    book_instrument=instrument if kind == "book" else None,
                    book_timing=book_timing,
                )
                if book_timing is not None:
                    book_timing["book_request_sent_at"] = datetime.now(UTC).isoformat()
                result = getattr(self.api, _METHODS[kind])(req, request_id)
            if result == 0:
                timed_out = not self.extra_done.wait(15)
            with self.lock:
                # Fixed SDK -2/-3 reject before acceptance. Never isolate a
                # contradictory callback, an identity error or an uncertain send.
                if (self._observe_input_scope and kind in {'instrument', 'margin', 'commission', 'book'}
                        and type(result) is int and result in {-2, -3} and not self.failed
                        and self.extra['response_count'] == 0
                        and not self.extra['terminal_response_seen'] and not self.extra['complete']):
                    self.extra['closed'] = True
                    raise ValueError('NATIVE_FACT_QUERY_THROTTLED')
                if result != 0 or timed_out or self.failed or not self.extra["complete"]:
                    self.fail("NATIVE_FACT_QUERY_FAILED")
                    raise ValueError("NATIVE_FACT_QUERY_FAILED")
                if kind in ("margin", "commission"):
                    scope = dict(schema="native_rate_query_scope_v1", kind=kind,
                                 instrument=instrument, exchange=exchange, request_id=request_id)
                    return tuple(dict(row, query_scope=dict(scope)) for row in self.extra["rows"])
                return tuple(self.extra["rows"])
        finally:
            with self.lock:
                if request_id is not None:
                    if book_timing is not None:
                        book_timing["book_returned_at"] = datetime.now(UTC).isoformat()
                        book_timing["book_total_elapsed_seconds"] = round(time.monotonic()-book_started, 6)
                    self.query_diagnostics.append(dict(
                        kind=kind,
                        request_id=request_id,
                        sdk_return_code=result if type(result) is int else None,
                        response_count=self.extra["response_count"],
                        data_row_count=len(self.extra["rows"]),
                        terminal_response_seen=self.extra["terminal_response_seen"],
                        complete=self.extra["complete"],
                        timed_out=timed_out,
                        callback_error=self.extra["callback_error"],
                        **({"response_info_present": self.extra.get("response_info_present")}
                           if kind in {"settlement", "confirm"} else {}),
                        elapsed_seconds=round(time.monotonic()-started, 6),
                        **(book_timing or {}),
                    ))

    def _extra_response(self, kind, row, info, request_id, last):
        with self.lock:
            self._locked_extra_response(kind, row, info, request_id, last)

    def _locked_extra_response(self, kind, row, info, request_id, last):
        try:
            if self.extra is not None:
                self.extra["response_count"] += 1
                self.extra["terminal_response_seen"] |= bool(last)
            if (
                self.extra is None
                or self.extra["kind"] != kind
                or self.extra["id"] != request_id
                or self.extra["complete"]
                or self.extra.get('closed') is True
            ):
                raise ValueError("NATIVE_FACT_RESPONSE_IDENTITY")
            if kind == "book" and self.extra.get("book_timing") is not None:
                timing = self.extra["book_timing"]
                received_at = datetime.now(UTC).isoformat()
                if (row is not None and getattr(row, "InstrumentID", None) == self.extra["book_instrument"]
                        and timing["book_target_received_at"] is None):
                    timing["book_target_received_at"] = received_at
                if last:
                    timing["book_terminal_received_at"] = received_at
            if kind in {"settlement", "confirm"}:
                self.extra["response_info_present"] = info is not None
            if info is not None and int(info.ErrorID):
                raise ValueError("NATIVE_FACT_QUERY_REJECTED")
            if row is not None:
                fields = _FIELDS["settlement" if kind == "confirm" else kind]
                value = {k: getattr(row, k) for k in fields}
                if kind == "instrument" and (
                    value["ExchangeID"] != self.extra["exchange"]
                    or value["ProductID"] != self.extra["product"]
                ):
                    raise ValueError("NATIVE_FACT_SCOPE_MISMATCH")
                if kind in ("margin", "commission", "settlement", "confirm"):
                    all_investors = (
                        kind in ("margin", "commission")
                        and value.get("InvestorRange") == "1"
                        and value["InvestorID"] in ("", self.user)
                    )
                    if value["BrokerID"] != "9999" or not (
                        value["InvestorID"] == self.user or all_investors
                    ):
                        raise ValueError("NATIVE_FACT_ACCOUNT_MISMATCH")
                # Account code stays transient; source facts use the already verified fingerprint.
                value.pop("InvestorID", None)
                self.extra["rows"].append(value)
                if len(self.extra["rows"]) > 100000:
                    raise ValueError("NATIVE_FACT_ROW_LIMIT")
            if last:
                self.extra["complete"] = True
                self.extra_done.set()
        except Exception as exc:
            if self.extra is not None:
                allowed = {
                    "NATIVE_FACT_RESPONSE_IDENTITY", "NATIVE_FACT_QUERY_REJECTED",
                    "NATIVE_FACT_ACCOUNT_MISMATCH", "NATIVE_FACT_ROW_LIMIT", "NATIVE_FACT_SCOPE_MISMATCH",
                }
                self.extra["callback_error"] = str(exc) if type(exc) is ValueError and str(exc) in allowed else "NATIVE_FACT_FIELD_INVALID"
            self.fail("NATIVE_FACT_RESPONSE_INVALID")
            self.extra_done.set()

    def OnRspQryInstrument(self, *args):
        self._extra_response("instrument", *args)

    def OnRspQryInstrumentMarginRate(self, *args):
        self._extra_response("margin", *args)

    def OnRspQryInstrumentCommissionRate(self, *args):
        self._extra_response("commission", *args)

    def OnRspQryDepthMarketData(self, *args):
        self._extra_response("book", *args)

    def OnRspQrySettlementInfoConfirm(self, *args):
        self._extra_response("settlement", *args)

    def OnRspSettlementInfoConfirm(self, *args):
        self._extra_response("confirm", *args)
