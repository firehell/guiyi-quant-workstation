"""Optional CTP gateway; imported only by isolated controlled CLI, never Runtime."""

from datetime import datetime, UTC
from types import SimpleNamespace
import importlib.util
from pathlib import Path
import threading
import time

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
    def __init__(self, user, password):
        super().__init__(user, password, environment="first")
        self.execution_adapter = None
        self.native_session = None
        self.extra = None
        self.extra_done = threading.Event()
        self.extra_counter = 30000
        self.query_diagnostics = []
        self.buffer = []
        self.monitor_progress = None

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

    def snapshot(self):
        if self.monitor_progress is not None:
            self.monitor_progress()
        if self.failed:
            raise ValueError("NATIVE_GATEWAY_FAILED")
        self.result["rounds"] = []
        self.collect()
        if self.failed or self.result["status"] != "READ_ONLY_COMPLETE":
            raise ValueError("NATIVE_STABLE_SNAPSHOT_REQUIRED")
        # Copy sanitized values only; user/password and raw objects never leave gateway.
        import json

        return json.loads(json.dumps(self.result))

    def query(self, kind, instrument=""):
        if self.monitor_progress is not None:
            self.monitor_progress()
        if self.failed:
            raise ValueError("NATIVE_GATEWAY_FAILED")
        time.sleep(1.1)
        self.extra_counter += 1
        request_id = self.extra_counter
        self.extra_done.clear()
        self.extra = dict(kind=kind, id=request_id, rows=[], complete=False)
        req = getattr(tdapi, _TYPES[kind])()
        for field, value in (
            ("BrokerID", "9999"),
            ("InvestorID", self.user),
            ("InstrumentID", instrument),
            ("HedgeFlag", "1"),
        ):
            if hasattr(req, field):
                setattr(req, field, value)
        started = time.monotonic()
        self.extra.update(response_count=0, terminal_response_seen=False, callback_error=None)
        result = None
        timed_out = False
        try:
            result = getattr(self.api, _METHODS[kind])(req, request_id)
            if result == 0:
                timed_out = not self.extra_done.wait(15)
            if result != 0 or timed_out or self.failed or not self.extra["complete"]:
                self.fail("NATIVE_FACT_QUERY_FAILED")
                raise ValueError("NATIVE_FACT_QUERY_FAILED")
            return tuple(self.extra["rows"])
        finally:
            with self.lock:
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
                    elapsed_seconds=round(time.monotonic()-started, 6),
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
            ):
                raise ValueError("NATIVE_FACT_RESPONSE_IDENTITY")
            if info is not None and int(info.ErrorID):
                raise ValueError("NATIVE_FACT_QUERY_REJECTED")
            if row is not None:
                fields = _FIELDS["settlement" if kind == "confirm" else kind]
                value = {k: getattr(row, k) for k in fields}
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
                    "NATIVE_FACT_ACCOUNT_MISMATCH", "NATIVE_FACT_ROW_LIMIT",
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
