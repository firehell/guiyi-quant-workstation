"""One-shot SimNow inventory: authentication/login plus four read-only queries.

Optional isolated dependency: openctp-ctp==6.7.7.1, Mac ARM64 only. No Runtime hooks.
CTP queries are not an atomic database snapshot. Two equal passes only prove bounded
readback stability; they do not reconcile an execution ledger or authorize trading.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import warnings
from datetime import datetime
from decimal import Decimal
from importlib.metadata import version
from zoneinfo import ZoneInfo

from openctp_ctp import tdapi

ENVIRONMENTS = {
    "api-test": (
        "SIMNOW_API_TEST",
        "tcp://182.254.243.31:40001",
        "API_TEST_COPY_NOT_FIRST_ENVIRONMENT",
    ),
    "first": (
        "SIMNOW_FIRST",
        "tcp://182.254.243.31:30001",
        "FIRST_ENVIRONMENT_READBACK",
    ),
}
BROKER = "9999"
SCHEMA = "simnow_readonly_inventory_v1"
QUERY_GAP = 1.1
# Records retain all native position dimensions; never net LONG/SHORT or today/yesterday.
FIELDS = {
    "funds": {
        "CurrencyID": "s",
        "TradingDay": "s",
        "Balance": "d",
        "Available": "d",
        "CurrMargin": "d",
        "FrozenMargin": "d",
        "FrozenCommission": "d",
        "Commission": "d",
        "CloseProfit": "d",
        "PositionProfit": "d",
        "PreBalance": "d",
        "Deposit": "d",
        "Withdraw": "d",
    },
    "positions": {
        "InstrumentID": "s",
        "ExchangeID": "s",
        "PosiDirection": "s",
        "HedgeFlag": "s",
        "PositionDate": "s",
        "Position": "i",
        "TodayPosition": "i",
        "YdPosition": "i",
        "LongFrozen": "i",
        "ShortFrozen": "i",
        "UseMargin": "d",
        "PositionProfit": "d",
        "TradingDay": "s",
    },
    "orders": {
        "InstrumentID": "s",
        "ExchangeID": "s",
        "OrderSysID": "s",
        "FrontID": "i",
        "SessionID": "i",
        "OrderRef": "s",
        "OrderStatus": "s",
        "OrderSubmitStatus": "s",
        "Direction": "s",
        "CombOffsetFlag": "s",
        "CombHedgeFlag": "s",
        "LimitPrice": "d",
        "VolumeTotalOriginal": "i",
        "VolumeTraded": "i",
        "VolumeTotal": "i",
        "TradingDay": "s",
        "InsertDate": "s",
        "InsertTime": "s",
    },
    "trades": {
        "InstrumentID": "s",
        "ExchangeID": "s",
        "TradeID": "s",
        "OrderSysID": "s",
        "Direction": "s",
        "OffsetFlag": "s",
        "HedgeFlag": "s",
        "Price": "d",
        "Volume": "i",
        "TradingDay": "s",
        "TradeDate": "s",
        "TradeTime": "s",
    },
}
KEYS = {
    "funds": ("CurrencyID",),
    "positions": (
        "ExchangeID",
        "InstrumentID",
        "PosiDirection",
        "HedgeFlag",
        "PositionDate",
    ),
    "orders": ("FrontID", "SessionID", "OrderRef"),
    "trades": ("ExchangeID", "TradeID", "Direction", "TradingDay"),
}
QUERY_TYPES = {
    "funds": "CThostFtdcQryTradingAccountField",
    "positions": "CThostFtdcQryInvestorPositionField",
    "orders": "CThostFtdcQryOrderField",
    "trades": "CThostFtdcQryTradeField",
}


def stamp():
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def checked_row(kind, row, user, day):
    if row.BrokerID != BROKER:
        raise ValueError("IDENTITY_MISMATCH")
    owner = row.AccountID if kind == "funds" else row.InvestorID
    if owner != user:
        raise ValueError("IDENTITY_MISMATCH")
    result = {}
    for field, data_type in FIELDS[kind].items():
        raw = getattr(row, field)
        if data_type == "d":
            number = Decimal(str(raw))
            if not number.is_finite() or abs(number) > Decimal("1e30"):
                raise ValueError("INVALID_NUMBER")
            result[field] = str(number)
        elif data_type == "i":
            if type(raw) is not int or raw < 0:
                raise ValueError("INVALID_QUANTITY")
            result[field] = raw
        else:
            if (
                not isinstance(raw, str)
                or len(raw) > 128
                or any(ord(c) < 32 for c in raw)
            ):
                raise ValueError("INVALID_TEXT")
            result[field] = raw
    if result["TradingDay"] != day:
        raise ValueError("TRADING_DAY_MISMATCH")
    if kind == "funds" and result["CurrencyID"] != "CNY":
        raise ValueError("CURRENCY_MISMATCH")
    if kind != "funds" and not result["InstrumentID"]:
        raise ValueError("MISSING_INSTRUMENT")
    if kind == "positions" and (
        result["PosiDirection"] not in ("1", "2", "3")
        or result["PositionDate"] not in ("1", "2")
    ):
        raise ValueError("UNKNOWN_POSITION_TYPE")
    return result


class Probe(tdapi.CThostFtdcTraderSpi):
    def __init__(self, user, password, *, environment="api-test"):
        if environment not in ENVIRONMENTS:
            raise ValueError("UNSUPPORTED_SIMNOW_ENVIRONMENT")
        environment_id, self.front, self.source_scope = ENVIRONMENTS[environment]
        super().__init__()
        self.user, self.password, self.api = user, password, None
        self.lock = threading.RLock()
        self.login_done = threading.Event()
        self.query_done = threading.Event()
        self.failed = False
        self.auth_attempted = self.login_attempted = False
        self.current = None
        self.day = None
        self.result = {
            "schema": SCHEMA,
            "environment": environment_id,
            "front": self.front,
            "broker_id": BROKER,
            "account_fingerprint": digest([environment_id, BROKER, user]),
            "started_at": stamp(),
            "status": "WAITING_CONNECTION",
            "authentication_passed": False,
            "login_passed": False,
            "requests": [],
            "rounds": [],
            "atomic_snapshot": False,
            "execution_eligible": False,
            "ledger_reconciled": False,
            "order_requests": 0,
        }

    def fail(self, status, **safe):
        if not self.failed:
            self.result.update(status=status, **safe)
        self.failed = True
        self.login_done.set()
        self.query_done.set()

    def guard(self, stage, action):
        with self.lock:
            if self.failed:
                return
            try:
                action()
            except Exception as exc:
                # Never include exception text, response objects, or secrets.
                self.fail(
                    "LOCAL_ERROR", error_stage=stage, exception_type=type(exc).__name__
                )

    def request(self, name, request_id, call):
        receipt = {
            "kind": name,
            "request_id": request_id,
            "attempted_at": stamp(),
            "accepted": False,
        }
        self.result["requests"].append(receipt)
        ret = int(call())
        receipt.update(return_code=ret, accepted=ret == 0)
        if ret != 0:
            self.fail("REQUEST_NOT_ACCEPTED", error_stage=name, return_code=ret)

    def OnFrontConnected(self):
        def action():
            if self.auth_attempted:
                return
            self.auth_attempted = True
            req = tdapi.CThostFtdcReqAuthenticateField()
            req.BrokerID, req.UserID = BROKER, self.user
            req.AppID, req.AuthCode = "simnow_client_test", "0" * 16
            self.result["status"] = "WAITING_AUTH"
            self.request("authenticate", 1, lambda: self.api.ReqAuthenticate(req, 1))

        self.guard("authenticate", action)

    def OnRspAuthenticate(self, rsp, info, request_id, last):
        def action():
            if request_id != 1 or self.login_attempted:
                return
            if info is None:
                self.fail("AUTH_RESPONSE_INVALID")
            elif int(info.ErrorID):
                self.fail("AUTH_REJECTED", error_id=int(info.ErrorID))
            elif last and rsp is not None:
                self.result["authentication_passed"] = True
                self.login_attempted = True
                req = tdapi.CThostFtdcReqUserLoginField()
                req.BrokerID, req.UserID, req.Password = (
                    BROKER,
                    self.user,
                    self.password,
                )
                self.result["status"] = "WAITING_LOGIN"
                # Pinned Mac 6.7.7.1 ABI. No disabled authentication or invented terminal data.
                self.request("login", 2, lambda: self.api.ReqUserLogin(req, 2, 0, None))
            elif last:
                self.fail("AUTH_RESPONSE_INVALID")

        self.guard("authenticate_response", action)

    def OnRspUserLogin(self, rsp, info, request_id, last):
        def action():
            if request_id != 2 or self.result["login_passed"]:
                return
            if info is None:
                self.fail("LOGIN_RESPONSE_INVALID")
            elif int(info.ErrorID):
                self.fail("LOGIN_REJECTED", error_id=int(info.ErrorID))
            elif last:
                if rsp is None or rsp.BrokerID != BROKER or rsp.UserID != self.user:
                    self.fail("LOGIN_IDENTITY_MISMATCH")
                    return
                day = rsp.TradingDay
                if (
                    not isinstance(day, str)
                    or len(day) != 8
                    or not day.isascii()
                    or not day.isdigit()
                ):
                    self.fail("LOGIN_TRADING_DAY_INVALID")
                    return
                datetime.strptime(day, "%Y%m%d")
                self.day = day
                self.password = ""
                self.result.update(
                    login_passed=True, trading_day=day, status="LOGIN_PASSED"
                )
                self.login_done.set()

        self.guard("login_response", action)

    def OnFrontDisconnected(self, reason):
        self.guard(
            "disconnect", lambda: self.fail("FRONT_DISCONNECTED", reason=int(reason))
        )

    def OnRspError(self, info, request_id, last):
        self.guard(
            "api_error",
            lambda: self.fail(
                "API_ERROR", error_id=int(info.ErrorID) if info is not None else -1
            ),
        )

    def begin_query(self, kind, request_id):
        def action():
            if not self.result["login_passed"] or (
                self.current and not self.current["complete"]
            ):
                raise ValueError("QUERY_SEQUENCE_INVALID")
            self.query_done.clear()
            self.current = {
                "kind": kind,
                "request_id": request_id,
                "started_at": stamp(),
                "rows": {},
                "complete": False,
            }
            req = getattr(tdapi, QUERY_TYPES[kind])()
            req.BrokerID, req.InvestorID = BROKER, self.user
            if kind == "funds":
                req.CurrencyID = "CNY"
            calls = {
                "funds": self.api.ReqQryTradingAccount,
                "positions": self.api.ReqQryInvestorPosition,
                "orders": self.api.ReqQryOrder,
                "trades": self.api.ReqQryTrade,
            }
            self.result["status"] = "QUERYING_" + kind.upper()
            self.request(kind, request_id, lambda: calls[kind](req, request_id))

        self.guard("query_send", action)

    def receive(self, kind, row, info, request_id, last):
        def action():
            current = self.current
            if not current or request_id != current["request_id"]:
                self.fail("UNEXPECTED_QUERY_RESPONSE")
                return
            if current["kind"] != kind or current["complete"]:
                self.fail("UNEXPECTED_QUERY_RESPONSE")
                return
            if info is not None and int(info.ErrorID):
                self.fail(
                    "QUERY_REJECTED", error_stage=kind, error_id=int(info.ErrorID)
                )
                return
            if row is not None:
                clean = checked_row(kind, row, self.user, self.day)
                key = tuple(clean[field] for field in KEYS[kind])
                if key in current["rows"]:
                    self.fail("DUPLICATE_QUERY_ROW", error_stage=kind)
                    return
                current["rows"][key] = clean
                if len(current["rows"]) > 100000:
                    self.fail("QUERY_ROW_LIMIT", error_stage=kind)
                    return
            if last:
                if kind == "funds" and len(current["rows"]) != 1:
                    self.fail("FUNDS_ROW_COUNT_INVALID")
                    return
                current.update(complete=True, completed_at=stamp())
                self.query_done.set()

        self.guard("query_response_" + kind, action)

    def OnRspQryTradingAccount(self, row, info, request_id, last):
        self.receive("funds", row, info, request_id, last)

    def OnRspQryInvestorPosition(self, row, info, request_id, last):
        self.receive("positions", row, info, request_id, last)

    def OnRspQryOrder(self, row, info, request_id, last):
        self.receive("orders", row, info, request_id, last)

    def OnRspQryTrade(self, row, info, request_id, last):
        self.receive("trades", row, info, request_id, last)

    def collect(self, gap=QUERY_GAP, query_timeout=15):
        for round_number in (1, 2):
            record = {"round": round_number, "started_at": stamp(), "queries": {}}
            self.result["rounds"].append(record)
            for index, kind in enumerate(FIELDS):
                time.sleep(gap)
                if self.failed:
                    return
                self.begin_query(kind, 100 + round_number * 10 + index)
                if not self.query_done.wait(query_timeout):
                    with self.lock:
                        self.fail("QUERY_TIMEOUT", error_stage=kind)
                with self.lock:
                    if self.current:
                        current = self.current
                        record["queries"][kind] = {
                            "complete": current["complete"],
                            "started_at": current["started_at"],
                            "completed_at": current.get("completed_at"),
                            "rows": sorted(current["rows"].values(), key=canonical),
                        }
                    if self.failed:
                        return
            record["completed_at"] = stamp()
        with self.lock:
            if self.failed:
                return
            payloads = [
                {kind: record["queries"][kind]["rows"] for kind in FIELDS}
                for record in self.result["rounds"]
            ]
            stable = payloads[0] == payloads[1]
            current = payloads[1]
            # Terminal raw CTP states: filled, partial-not-queueing, not-queueing, cancelled.
            active = [
                o
                for o in current["orders"]
                if o["OrderStatus"] not in ("0", "2", "4", "5")
            ]
            holdings = [
                p
                for p in current["positions"]
                if p["Position"] or p["LongFrozen"] or p["ShortFrozen"]
            ]
            funds = current["funds"][0]
            encumbered = any(
                Decimal(funds[field]) != 0
                for field in ("CurrMargin", "FrozenMargin", "FrozenCommission")
            )
            inventory_warnings = []
            if Decimal(funds["CurrMargin"]) != 0 and not any(
                p["Position"] for p in holdings
            ):
                inventory_warnings.append("MARGIN_WITHOUT_REPORTED_POSITION")
            if (
                any(
                    Decimal(funds[field]) != 0
                    for field in ("FrozenMargin", "FrozenCommission")
                )
                and not active
            ):
                inventory_warnings.append("FROZEN_FUNDS_WITHOUT_WORKING_ORDER")
            self.result.update(
                status="READ_ONLY_COMPLETE" if stable else "SNAPSHOT_CHANGED",
                bounded_readback_stable=stable,
                round_hashes=[digest(payload) for payload in payloads],
                position_rows_nonzero=len(holdings),
                working_or_unknown_orders=len(active),
                account_empty_observed=stable
                and not holdings
                and not active
                and not encumbered,
                inventory_warnings=inventory_warnings,
                source_scope=self.source_scope,
            )


def check_funding_reset(result, expected_balance, effective_trading_day):
    """Verify a completed in-memory readback; never authorize orders or resubmit reset."""
    expected = Decimal(expected_balance)
    if not expected.is_finite() or expected <= 0:
        raise ValueError("INVALID_EXPECTED_BALANCE")
    datetime.strptime(effective_trading_day, "%Y%m%d")
    if len(effective_trading_day) != 8:
        raise ValueError("INVALID_EFFECTIVE_DAY")
    reasons = []
    if (result.get("environment"), result.get("front"), result.get("source_scope")) != (
        "SIMNOW_FIRST",
        ENVIRONMENTS["first"][1],
        "FIRST_ENVIRONMENT_READBACK",
    ):
        reasons.append("FIRST_ENVIRONMENT_REQUIRED")
    day = result.get("trading_day", "")
    if not isinstance(day, str) or len(day) != 8 or day < effective_trading_day:
        reasons.append("EFFECTIVE_TRADING_DAY_NOT_REACHED")
    if (
        result.get("status") != "READ_ONLY_COMPLETE"
        or result.get("login_passed") is not True
        or result.get("authentication_passed") is not True
    ):
        reasons.append("COMPLETE_READBACK_REQUIRED")
    try:
        rounds = result["rounds"]
        if len(rounds) != 2:
            raise ValueError("TWO_ROUNDS_REQUIRED")
        payloads = []
        for record in rounds:
            queries = record["queries"]
            if set(queries) != set(FIELDS) or not all(
                q["complete"] is True for q in queries.values()
            ):
                raise ValueError("QUERY_INCOMPLETE")
            payload = {kind: queries[kind]["rows"] for kind in FIELDS}
            if len(payload["funds"]) != 1:
                raise ValueError("FUNDS_INVALID")
            funds = payload["funds"][0]
            if funds["TradingDay"] != day or funds["CurrencyID"] != "CNY":
                raise ValueError("FUND_IDENTITY_INVALID")
            if any(Decimal(funds[f]) != expected for f in ("Balance", "Available")):
                reasons.append("TARGET_FUNDS_NOT_OBSERVED")
            if any(
                Decimal(funds[f]) != 0
                for f in ("CurrMargin", "FrozenMargin", "FrozenCommission")
            ):
                reasons.append("FUNDS_STILL_ENCUMBERED")
            if any(
                p["Position"] or p["LongFrozen"] or p["ShortFrozen"]
                for p in payload["positions"]
            ):
                reasons.append("POSITION_NOT_FLAT")
            if any(
                o["OrderStatus"] not in ("0", "2", "4", "5") for o in payload["orders"]
            ):
                reasons.append("WORKING_OR_UNKNOWN_ORDERS")
            payloads.append(payload)
        if payloads[0] != payloads[1] or result["round_hashes"] != [
            digest(p) for p in payloads
        ]:
            reasons.append("READBACK_NOT_STABLE_OR_HASH_MISMATCH")
    except (KeyError, TypeError, ValueError, ArithmeticError):
        reasons.append("READBACK_INVALID_OR_INCOMPLETE")
    return {
        "passed": not reasons,
        "reasons": sorted(set(reasons)),
        "expected_balance_cny": str(expected),
        "effective_trading_day": effective_trading_day,
        "execution_eligible": False,
    }


def report_path():
    root = Path(__file__).resolve().parents[2]
    folder = root / "output" / "simnow-readonly"
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not folder.resolve().is_relative_to(root):
        raise ValueError("OUTPUT_OUTSIDE_WORKSPACE")
    return folder / (
        "snapshot-"
        + datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d-%H%M%S-%f")
        + ".json"
    )


def main():
    parser = argparse.ArgumentParser(description="SimNow一次性账户只读核验，无交易权限")
    parser.add_argument(
        "--environment",
        choices=tuple(ENVIRONMENTS),
        default="api-test",
        help="api-test=历史账户副本；first=第一套模拟交易环境。固定前置，不自动fallback",
    )
    parser.add_argument(
        "--expected-balance", type=Decimal, help="重置目标资金，只读验收，不修改资金"
    )
    parser.add_argument("--not-before-trading-day", help="官网回执生效交易日 YYYYMMDD")
    options = parser.parse_args()
    if (options.expected_balance is None) != (options.not_before_trading_day is None):
        parser.error("资金目标与官网生效日必须同时提供")
    if options.expected_balance is not None:
        if options.environment != "first":
            parser.error("资金重置验收必须显式选择first环境")
        try:
            check_funding_reset(
                {}, options.expected_balance, options.not_before_trading_day
            )
        except (ValueError, ArithmeticError, TypeError):
            parser.error("目标资金或生效日格式无效")
    if not sys.stdin.isatty():
        raise SystemExit("请在本机交互终端运行；不接受管道凭据。")
    if sys.platform != "darwin" or version("openctp-ctp") != "6.7.7.1":
        raise SystemExit("SDK版本/平台不匹配，未读取凭据、未连接。")
    environment_id, front, _ = ENVIRONMENTS[options.environment]
    print(
        f"SimNow只读核验：{environment_id} {front}；认证/登录各一次，四类查询各两轮。"
    )
    print(
        "不下单、不撤单、不确认结算；密码不保存。测试环境结果不能代替第一套环境验收。"
    )
    user = input("投资者代码（数字）: ").strip()
    if not user.isascii() or not user.isdigit() or not 1 <= len(user) <= 15:
        raise SystemExit("投资者代码格式不合格，未连接。")
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        password = getpass.getpass("交易密码（隐藏输入）: ")
    if not password or len(password.encode()) > 40:
        raise SystemExit("密码为空或超长，未连接。")
    target = report_path()
    probe = Probe(user, password, environment=options.environment)
    user = password = ""
    saved_out, saved_err = os.dup(1), os.dup(2)
    with tempfile.TemporaryDirectory(prefix="guiyi-simnow-readonly-") as flow:
        with open(os.devnull, "w") as sink:
            os.dup2(sink.fileno(), 1)
            os.dup2(sink.fileno(), 2)
            try:
                probe.api = tdapi.CThostFtdcTraderApi.CreateFtdcTraderApi(flow + "/")
                probe.api.RegisterSpi(probe)
                probe.api.RegisterFront(probe.front)
                probe.api.Init()
                if not probe.login_done.wait(25):
                    with probe.lock:
                        probe.fail("LOGIN_TIMEOUT", error_stage=probe.result["status"])
                if not probe.failed:
                    probe.collect()
            except Exception as exc:
                probe.fail(
                    "LOCAL_ERROR",
                    error_stage="runner",
                    exception_type=type(exc).__name__,
                )
            finally:
                try:
                    if probe.api is not None:
                        probe.api.RegisterSpi(None)
                        probe.api.Release()
                finally:
                    probe.user = probe.password = ""
                    os.dup2(saved_out, 1)
                    os.dup2(saved_err, 2)
                    os.close(saved_out)
                    os.close(saved_err)
    probe.result["finished_at"] = stamp()
    if options.expected_balance is not None:
        probe.result["funding_reset_acceptance"] = check_funding_reset(
            probe.result, options.expected_balance, options.not_before_trading_day
        )
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as output:
        json.dump(probe.result, output, ensure_ascii=False, indent=2)
    print("结果：", probe.result["status"])
    if "funding_reset_acceptance" in probe.result:
        acceptance = probe.result["funding_reset_acceptance"]
        print("资金重置生效验收：", "通过" if acceptance["passed"] else "待验/未通过")
        print("原因：", ", ".join(acceptance["reasons"]) or "两轮第一套读回均符合目标")
    print("完整核验记录：", target)
    print("查询未完成、异常或数据变化都不表示账户空仓；本次始终不具备下单资格。")
    accepted = probe.result.get("funding_reset_acceptance", {}).get("passed", True)
    return 0 if probe.result["status"] == "READ_ONLY_COMPLETE" and accepted else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyboardInterrupt, EOFError):
        print("已取消；不会自动重试。")
    except Exception:
        print("核验异常停止；未输出可能包含凭据的异常文本。")
        raise SystemExit(1)
