"""CTP request adapter. Inject a logged-in API; nothing logs in or runs itself."""

from datetime import datetime, UTC, timedelta
from functools import wraps
from time import monotonic
from decimal import Decimal
import re
from types import SimpleNamespace
from zoneinfo import ZoneInfo
from ..htdy_account_execution import model as m
from ..htdy_account_execution.codec import digest
from .model import action_hash, close_offset, valid, ENVIRONMENT, FRONT
from .inventory import Snapshot, native_hash
from .account_profile import AccountProfile, validate_profile


_DISPATCH_CODES = frozenset({
    "ACCOUNT_PROFILE_INVALID", "ACCOUNT_PROFILE_ANCHOR_MISMATCH", "ACCOUNT_PROFILE_HOST_MISMATCH", "INITIAL_100K_BASELINE_REQUIRED",
    "ACTION_PLAN_DRIFT", "CANCEL_NOT_QUALIFIED", "CLOSE_ONLY_NATIVE_ADAPTER", "DISPATCH_IDENTITY_MISMATCH",
    "EXECUTION_CONTRACT_MISMATCH", "LIVE_QUOTE_REQUIRED", "NATIVE_CALLBACK_OR_COMMIT_REQUIRES_RECOVERY",
    "OPEN_EXPIRED", "OPEN_RESERVATION_REQUIRED", "OPPONENT_PRICE_DRIFT", "PERSISTED_EFFECT_REQUIRED",
    "RECONCILED_ACCOUNT_REQUIRED", "SUBMIT_NOT_QUALIFIED", "UNDRAINED_NATIVE_FACTS_REQUIRE_RECONCILIATION",
    "ACCOUNT_TAKEOVER_PENDING", "NATIVE_PRICE_PRECISION_LOSS", "NATIVE_FACT_STALE",
    "ONE_LOT_NATIVE_INVENTORY_REQUIRED", "CLOSE_POSITION_MISMATCH",
})
_DISPATCH_OUTCOMES = frozenset({"ALREADY_CLAIMED_NO_SEND", "REQUEST_ACCEPTED_AWAIT_NATIVE",
    "NOT_ACCEPTED_RECONCILE_REQUIRED", "SEND_OUTCOME_UNKNOWN"})


def dispatch_failure_code(error):
    """Only enumerated local failure codes may cross the diagnostic boundary."""
    if type(error) is ValueError and len(error.args) == 1 and type(error.args[0]) is str and error.args[0] in _DISPATCH_CODES:
        return error.args[0]
    return "DISPATCH_FAILED"


def dispatch_diagnostic(method):
    @wraps(method)
    def measured(self, *args, **kwargs):
        started = monotonic()
        self._dispatch_stage = "DISPATCH_START"
        code = "DISPATCH_FAILED"
        try:
            result = method(self, *args, **kwargs)
            code = result if result in _DISPATCH_OUTCOMES else "DISPATCH_COMPLETED"
            return result
        except Exception as error:
            code = dispatch_failure_code(error)
            raise
        finally:
            self.last_dispatch_diagnostic = {"stage": self._dispatch_stage, "code": code,
                "elapsed_ms": round(max(0, monotonic() - started) * 1000, 3)}
    return measured


def callback_guard(method):
    @wraps(method)
    def guarded(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except Exception:
            self._faulted = True
            # Preserve a fixed fault fact, never exception text or raw callback objects.
            at = kwargs.get("at", args[-1] if args else None)
            if not isinstance(at, datetime) or at.tzinfo is None:
                at = datetime.now(UTC)
            if method.__name__ == "trade_callback" and args:
                row = args[0]
                raw = {}
                for name in (
                    "TradingDay",
                    "ExchangeID",
                    "InstrumentID",
                    "OrderRef",
                    "OrderSysID",
                    "TradeID",
                    "Direction",
                    "OffsetFlag",
                    "HedgeFlag",
                    "TradeDate",
                    "TradeTime",
                    "Price",
                    "Volume",
                ):
                    value = getattr(row, name, None)
                    if type(value) in (str, int, float) and len(str(value)) <= 128:
                        raw[name] = str(value)
                self.journal.event(
                    "ctp-quarantine:" + digest(raw),
                    dict(kind="quarantine", fields=raw),
                    at,
                )
            self.journal.event(
                "ctp-fault:" + digest((method.__name__, at)),
                dict(kind="fault", operation=method.__name__),
                at,
            )
            raise ValueError("NATIVE_CALLBACK_BLOCKED") from None

    return guarded


class Adapter:
    def __init__(self, store, journal, sdk, api, user, session, *,
                 close_only=False, correlated_native=False,
                 strategy_correlated_native=False, native_validator=None, account_takeover_pending=False, account_profile=None):
        if (type(account_takeover_pending) is not bool or type(close_only) is not bool or type(correlated_native) is not bool
            or type(strategy_correlated_native) is not bool
            or correlated_native and (not close_only or strategy_correlated_native)
            or strategy_correlated_native and not callable(native_validator)
        ):
            raise ValueError("NATIVE_CAPABILITY_INVALID")
        if re.fullmatch(r"[0-9]{1,16}", user) is None:
            raise ValueError("INVESTOR_FORMAT_INVALID")
        # The existing read-only tool's environment-scoped identity algorithm.
        import hashlib
        import json

        fingerprint = hashlib.sha256(
            json.dumps(
                [ENVIRONMENT, "9999", user],
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        if session.account_id != fingerprint or journal.account_id != fingerprint:
            raise ValueError("ACCOUNT_FINGERPRINT_MISMATCH")
        self.store, self.journal, self.sdk, self.api = store, journal, sdk, api
        self._user, self.session = user, session
        if account_profile is not None and type(account_profile) is not AccountProfile:
            raise ValueError("ACCOUNT_PROFILE_INVALID")
        self.account_profile = account_profile
        self.last_dispatch_diagnostic = None
        self._faulted = False
        self.account_takeover_pending = account_takeover_pending
        self.close_only = close_only
        self.strategy_correlated_native = strategy_correlated_native
        self.correlated_native = correlated_native or strategy_correlated_native
        self.native_validator = native_validator
        self._correlated_snapshot = None

    def correlate_snapshot(self, snapshot):
        """Bind callback admission to one complete native two-round readback."""
        if not self.correlated_native:
            raise ValueError("NATIVE_CORRELATION_NOT_ENABLED")
        if type(snapshot) is not Snapshot or (
            snapshot.account_id, snapshot.trading_day
        ) != (self.session.account_id, self.session.trading_day):
            raise ValueError("NATIVE_CORRELATION_IDENTITY_INVALID")
        data = snapshot.data
        expected = "ctp-inventory:" + snapshot.trading_day + ":" + native_hash((
            snapshot.account_id, snapshot.trading_day, data, snapshot.at.isoformat()
        ))
        if snapshot.source_id != expected:
            raise ValueError("NATIVE_CORRELATION_SOURCE_INVALID")
        if self.strategy_correlated_native:
            # Validate raw event dates against authoritative sessions before the
            # snapshot can qualify any callback, including callbacks on attach.
            self.native_validator(snapshot)
        orders = {}
        for row in data["orders"]:
            try:
                order_id = self.journal.find_ref(
                    row["OrderRef"], row["FrontID"], row["SessionID"]
                )
            except ValueError:
                continue
            bound = self.journal.find(order_id)
            if (
                row["InstrumentID"], row["ExchangeID"], row["TradingDay"],
                row["Direction"], row["CombOffsetFlag"], row["CombHedgeFlag"],
                row["VolumeTotalOriginal"], Decimal(row["LimitPrice"]),
            ) != (
                bound["native"], bound["exchange"], bound["trading_day"],
                "0" if bound["side"] == "BUY" else "1", bound["offset"],
                "1", 1, Decimal(bound["price"]),
            ):
                raise ValueError("NATIVE_CORRELATION_ORDER_MISMATCH")
            known_systems = {
                payload["system_id"] for _, payload, _ in self.journal.events()
                if payload["kind"] == "order" and payload["order_id"] == order_id
                and payload["system_id"]
            }
            if known_systems and known_systems != {row["OrderSysID"].strip()}:
                raise ValueError("NATIVE_CORRELATION_SYSTEM_ID_CONFLICT")
            orders[order_id] = row
        trades = {}
        for row in data["trades"]:
            matches = [
                (order_id, order)
                for order_id, order in orders.items()
                if order["ExchangeID"] == row["ExchangeID"]
                and order["OrderSysID"].strip()
                and order["OrderSysID"].strip() == row["OrderSysID"].strip()
            ]
            if len(matches) > 1:
                raise ValueError("NATIVE_CORRELATION_TRADE_AMBIGUOUS")
            if len(matches) == 1:
                order_id, order = matches[0]
                if (
                    row["TradingDay"], row["InstrumentID"], row["Direction"],
                    row["OffsetFlag"], row["HedgeFlag"], row["Volume"],
                ) != (
                    snapshot.trading_day, order["InstrumentID"],
                    order["Direction"], order["CombOffsetFlag"], "1", 1,
                ) or not row["TradeID"].strip():
                    raise ValueError("NATIVE_CORRELATION_TRADE_MISMATCH")
                key = ":".join((snapshot.trading_day, row["ExchangeID"],
                                row["TradeID"].strip(), row["Direction"]))
                trades[key] = (order_id, row)
        self._correlated_snapshot = snapshot, orders, trades
        resolved = {
            payload["pending_id"] for _, payload, _ in self.journal.events()
            if payload["kind"] == "correlation"
        }
        for event_id, payload, received in self.journal.events():
            if payload["kind"] not in ("unverified_order", "unverified_trade") or event_id in resolved:
                continue
            kind = payload["kind"].removeprefix("unverified_")
            row = SimpleNamespace(**payload["fields"], BrokerID="9999", InvestorID=self._user)
            matched = self._in_correlated_order(row) if kind == "order" else self._in_correlated_trade(row)
            covered = (
                kind == "order"
                and datetime.fromisoformat(received) <= snapshot.at
                and self._covered_intermediate_order(row, payload["order_id"])
            )
            if matched:
                getattr(self, kind + "_callback")(row, datetime.fromisoformat(received))
            if matched or covered:
                self.journal.event(
                    "ctp-correlation:" + event_id,
                    dict(kind="correlation", pending_id=event_id, source_id=snapshot.source_id),
                    snapshot.at,
                )

    def _buffer_unverified(self, kind, row, at):
        if sum(p["kind"].startswith("unverified_") for _, p, _ in self.journal.events()) >= 10000:
            raise ValueError("NATIVE_CALLBACK_BUFFER_LIMIT")
        fields = (
            ("BrokerID", "InvestorID", "TradingDay", "OrderRef", "FrontID",
             "SessionID", "InstrumentID", "ExchangeID", "Direction",
             "CombOffsetFlag", "CombHedgeFlag", "LimitPrice",
             "VolumeTotalOriginal", "VolumeTraded", "VolumeTotal",
             "OrderStatus", "OrderSubmitStatus", "OrderSysID", "InsertDate",
             "InsertTime")
            if kind == "order" else
            ("BrokerID", "InvestorID", "TradingDay", "OrderRef", "InstrumentID",
             "ExchangeID", "Direction", "OffsetFlag", "HedgeFlag", "Volume",
             "Price", "TradeDate", "TradeTime", "TradeID", "OrderSysID")
        )
        captured = {name: getattr(row, name, None) for name in fields
                    if name not in ("BrokerID", "InvestorID")}
        order_id = self.journal.find_ref(
            row.OrderRef, row.FrontID, row.SessionID
        ) if kind == "order" else self.journal.find_ref(row.OrderRef)
        if kind == "trade":
            known = {
                p["system_id"] for _, p, _ in self.journal.events()
                if p["kind"] == "order" and p["order_id"] == order_id and p["system_id"]
            }
            if known and known != {row.OrderSysID.strip()}:
                raise ValueError("NATIVE_TRADE_SYSTEM_ID_CONFLICT")
        else:
            known = {
                p["system_id"] for _, p, _ in self.journal.events()
                if p["kind"] == "order" and p["order_id"] == order_id and p["system_id"]
            }
            if known and row.OrderSysID.strip() and known != {row.OrderSysID.strip()}:
                raise ValueError("NATIVE_ORDER_SYSTEM_ID_CONFLICT")
        payload = dict(kind="unverified_" + kind, order_id=order_id, fields=captured)
        self.journal.event("ctp-unverified:" + digest(payload), payload, at)

    def _covered_intermediate_order(self, row, order_id):
        if self._correlated_snapshot is None:
            return False
        snapshot, orders, _ = self._correlated_snapshot
        terminal = orders.get(order_id)
        if terminal is None:
            return False
        filled = (
            terminal["OrderStatus"] == "0"
            and terminal["VolumeTraded"] == 1
            and terminal["VolumeTotal"] == 0
        )
        ended_without_fill = (
            terminal["OrderStatus"] in ("2", "4", "5")
            and terminal["VolumeTraded"] == 0
            and terminal["VolumeTotal"] in (0, 1)
        )
        if not (filled or ended_without_fill) or (
            row.OrderStatus not in ("3", "a")
            or row.VolumeTraded != 0
            or row.VolumeTotal not in (0, 1)
        ):
            return False
        return all(getattr(row, field) == terminal[field] for field in (
            "OrderRef", "FrontID", "SessionID", "InstrumentID", "ExchangeID",
            "TradingDay", "Direction", "CombOffsetFlag", "CombHedgeFlag",
            "VolumeTotalOriginal",
        )) and Decimal(str(row.LimitPrice)) == Decimal(terminal["LimitPrice"]) and (
            not row.OrderSysID.strip() or row.OrderSysID.strip() == terminal["OrderSysID"].strip()
        )

    def _in_correlated_order(self, row):
        if self._correlated_snapshot is None:
            return False
        try:
            _, orders, _ = self._correlated_snapshot
            order_id = self.journal.find_ref(row.OrderRef, row.FrontID, row.SessionID)
            original = orders.get(order_id)
            return original is not None and all(
                getattr(row, name, None) == original[name]
                for name in (
                    "OrderRef", "FrontID", "SessionID", "InstrumentID", "ExchangeID",
                    "TradingDay", "Direction", "CombOffsetFlag", "CombHedgeFlag",
                    "OrderStatus", "OrderSubmitStatus", "VolumeTotalOriginal",
                    "VolumeTraded", "VolumeTotal", "OrderSysID", "InsertDate", "InsertTime",
                )
            ) and Decimal(str(row.LimitPrice)) == Decimal(original["LimitPrice"])
        except (ValueError, TypeError, AttributeError, KeyError):
            return False

    def _in_correlated_trade(self, row):
        if self._correlated_snapshot is None:
            return False
        try:
            _, _, trades = self._correlated_snapshot
            key = ":".join((row.TradingDay, row.ExchangeID, row.TradeID.strip(), row.Direction))
            match = trades.get(key)
            return match is not None and all(
                getattr(row, name, None) == match[1][name]
                for name in (
                    "TradingDay", "ExchangeID", "InstrumentID", "TradeID", "OrderSysID",
                    "Direction", "OffsetFlag", "HedgeFlag", "TradeDate", "TradeTime", "Volume",
                )
            ) and Decimal(str(row.Price)) == Decimal(match[1]["Price"])
        except (ValueError, TypeError, AttributeError, KeyError):
            return False

    def _preflight(self, state, effect, binding, inventory, execution, permit, now):
        self._dispatch_stage = "NATIVE_FACT_DRAIN"
        if self.close_only and effect.order.offset == "OPEN":
            raise ValueError("CLOSE_ONLY_NATIVE_ADAPTER")
        if self._faulted or self.journal.uncertain:
            raise ValueError("NATIVE_CALLBACK_OR_COMMIT_REQUIRES_RECOVERY")
        s = self.session
        journal_events = self.journal.events()
        resolved = {
            payload["pending_id"] for _, payload, _ in journal_events
            if payload["kind"] == "correlation"
        }
        for identity, payload, _ in journal_events:
            if payload["kind"] == "correlation" or (
                payload["kind"].startswith("unverified_") and identity in resolved
            ):
                continue
            intermediate = (
                payload["kind"] == "order"
                and payload["submit"] in ("0", "1", "2")
                and payload["status"] in ("3", "a")
            )
            if (
                payload["kind"] not in ("fee",)
                and not intermediate
                and self.store.receipt(identity) is None
            ):
                raise ValueError("UNDRAINED_NATIVE_FACTS_REQUIRE_RECONCILIATION")
        self._dispatch_stage = "SESSION_FRESHNESS"
        valid(s.at, s.valid_until, now)
        self._dispatch_stage = "PERMIT_FRESHNESS"
        valid(permit.issued_at, permit.expires_at, now)
        self._dispatch_stage = "BINDING_FRESHNESS"
        valid(binding.at, binding.valid_until, now)
        self._dispatch_stage = "ACCOUNT_IDENTITY"
        if (
            (s.environment, s.front) != (ENVIRONMENT, FRONT)
            or s.account_id != state.account_id
            or permit.account_id != state.account_id
            or permit.trading_day != s.trading_day
        ):
            raise ValueError("DISPATCH_IDENTITY_MISMATCH")
        self._dispatch_stage = "ACCOUNT_PROFILE"
        validate_profile(self.account_profile, state)
        self._dispatch_stage = "ACCOUNT_READBACK"
        if (
            state.phase != "READY"
            or not state.readback_valid
            or not state.readback.complete
            or state.clock > now
        ):
            raise ValueError("RECONCILED_ACCOUNT_REQUIRED")
        valid(state.readback.at, state.readback.valid_until, now)
        self._dispatch_stage = "PERSISTED_EFFECT"
        o = effect.order
        if (
            effect.kind not in ("SUBMIT", "CANCEL")
            or o not in state.orders
            or o.contract != binding.canonical
            or o.quantity != 1
        ):
            raise ValueError("PERSISTED_EFFECT_REQUIRED")
        if (
            execution.instrument.contract != o.contract
            or execution.session.contract != o.contract
        ):
            raise ValueError("EXECUTION_CONTRACT_MISMATCH")
        self._dispatch_stage = "EXECUTION_FRESHNESS"
        valid(execution.session.at, execution.session.valid_until, now)
        self._dispatch_stage = "ACTION_PLAN"
        if permit.action_hash != action_hash(
            state, effect, s, binding, inventory, execution
        ):
            raise ValueError("ACTION_PLAN_DRIFT")
        self._dispatch_stage = "ORDER_QUALIFICATION"
        if effect.kind == "CANCEL":
            if (
                not o.cancel_sent
                or o.reconciled
                or o.status in ("CANCELLED", "REJECTED", "FILLED")
                or not execution.session.can_cancel
            ):
                raise ValueError("CANCEL_NOT_QUALIFIED")
            return None
        if (
            o.status != "PROPOSED"
            or o.cancel_required
            or o.cancel_sent
            or not execution.session.can_trade
        ):
            raise ValueError("SUBMIT_NOT_QUALIFIED")
        if o.offset == "OPEN" and (
            o.signal_id in state.abandoned
            or (execution.session.final_close_at - now).total_seconds() <= 60
        ):
            raise ValueError("OPEN_EXPIRED")
        valid(execution.instrument.at, execution.instrument.valid_until, now)
        quote = execution.quote
        if quote is None or quote.contract != o.contract:
            raise ValueError("LIVE_QUOTE_REQUIRED")
        valid(quote.at, quote.valid_until, now)
        price = quote.ask if o.side == "BUY" else quote.bid
        volume = quote.ask_volume if o.side == "BUY" else quote.bid_volume
        if (
            price != o.price
            or volume < 1
            or not quote.lower_limit <= price <= quote.upper_limit
            or price % execution.instrument.tick_size
        ):
            raise ValueError("OPPONENT_PRICE_DRIFT")
        if o.offset == "OPEN":
            reservations = [
                r
                for r in state.reservations
                if r.order_id == o.order_id and not r.released
            ]
            if len(reservations) != 1:
                raise ValueError("OPEN_RESERVATION_REQUIRED")
            return "0"
        return close_offset(binding, inventory, o.side, now)

    @dispatch_diagnostic
    def dispatch(self, effect, binding, inventory, execution, permit, now):
        """Only once per order/action, including SDK error, crash and unknown result."""
        if getattr(self, "account_takeover_pending", False):
            raise ValueError("ACCOUNT_TAKEOVER_PENDING")
        self._dispatch_stage = "LEDGER_GUARD"
        with self.store.dispatch_guard() as state:
            offset = self._preflight(
                state, effect, binding, inventory, execution, permit, now
            )
            self._dispatch_stage = "REQUEST_BUILD"
            o = effect.order
            # No user/account number or SDK object enters persistent payloads.
            payload = dict(
                contract=o.contract,
                native=binding.native,
                exchange=binding.exchange,
                side=o.side,
                offset=offset,
                price=str(o.price),
                trading_day=self.session.trading_day,
                account_id=state.account_id,
                action_hash=permit.action_hash,
                created_at=o.created_at.isoformat(),
                request_started_at=now.isoformat(),
            )
            # Construct everything fallible before taking the durable send claim.
            if effect.kind == "SUBMIT":
                req = self.sdk.CThostFtdcInputOrderField()
                req.BrokerID, req.InvestorID, req.UserID = (
                    "9999",
                    self._user,
                    self._user,
                )
                req.InstrumentID, req.ExchangeID = binding.native, binding.exchange
                req.Direction, req.CombOffsetFlag, req.CombHedgeFlag = (
                    ("0" if o.side == "BUY" else "1"),
                    offset,
                    "1",
                )
                req.OrderPriceType, req.LimitPrice, req.VolumeTotalOriginal = (
                    "2",
                    float(o.price),
                    1,
                )
                req.TimeCondition, req.VolumeCondition, req.MinVolume = "3", "1", 1
                req.ContingentCondition, req.ForceCloseReason = "1", "0"
                req.IsAutoSuspend, req.UserForceClose = 0, 0
                if Decimal(str(req.LimitPrice)) != o.price:
                    raise ValueError("NATIVE_PRICE_PRECISION_LOSS")
            else:
                native = self.journal.find(o.order_id)
                req = self.sdk.CThostFtdcInputOrderActionField()
                req.BrokerID, req.InvestorID, req.UserID = (
                    "9999",
                    self._user,
                    self._user,
                )
                req.InstrumentID, req.ExchangeID = binding.native, binding.exchange
                req.OrderRef, req.FrontID, req.SessionID = (
                    native["order_ref"],
                    native["front_id"],
                    native["session_id"],
                )
                req.ActionFlag = "0"
            self._dispatch_stage = "DISPATCH_CLAIM"
            claim = self.journal.claim(
                effect.kind + ":" + o.order_id,
                o.order_id,
                effect.kind,
                payload,
                self.session,
                permit.intent_id,
            )
            if claim is None:
                return "ALREADY_CLAIMED_NO_SEND"
            action_id, ref, request_id = claim
            if effect.kind == "SUBMIT":
                req.OrderRef = ref
            req.RequestID = request_id
            self._dispatch_stage = "SDK_REQUEST"
            try:
                result = (
                    self.api.ReqOrderInsert
                    if effect.kind == "SUBMIT"
                    else self.api.ReqOrderAction
                )(req, request_id)
                outcome = (
                    "REQUEST_ACCEPTED_AWAIT_NATIVE"
                    if type(result) is int and result == 0
                    else "NOT_ACCEPTED_RECONCILE_REQUIRED"
                )
            except Exception:
                outcome = "SEND_OUTCOME_UNKNOWN"
            self._dispatch_stage = "DISPATCH_RESULT"
            self.journal.result(action_id, outcome)
            if outcome != "REQUEST_ACCEPTED_AWAIT_NATIVE":
                self.journal.event(
                    "ctp-send-unknown:" + str(action_id),
                    dict(kind="uncertain", order_id=o.order_id),
                    now,
                )
            return outcome

    def abort_unsent(self, order_id, reason, now):
        proof = "dispatch-never-claimed:" + digest(
            (self.journal.account_id, order_id, reason)
        )
        return self.store.execute(
            "abort-unsent:" + order_id,
            m.AbortUnsent(self.session.account_id, order_id, now, proof, reason),
            unsent_proof=lambda state: not self.journal.claimed(order_id),
        )

    def _identity(self, row, trading_day):
        if (
            row.BrokerID != "9999"
            or row.InvestorID != self._user
            or row.TradingDay != trading_day
        ):
            raise ValueError("NATIVE_CALLBACK_IDENTITY_MISMATCH")

    @callback_guard
    def response(self, kind, row, error_id, request_id, at):
        """Handle OnRsp/OnErrRtn insert/action errors; success is not acceptance."""
        m.time(at)
        if type(error_id) is not int or error_id < 0:
            raise ValueError("NATIVE_ERROR_ID_INVALID")
        order_id, expected_kind = self.journal.request_order(request_id)
        if (
            kind != expected_kind
            or row.BrokerID != "9999"
            or row.InvestorID != self._user
        ):
            raise ValueError("NATIVE_RESPONSE_IDENTITY")
        native = self.journal.find(order_id)
        if (row.OrderRef, row.InstrumentID) != (native["order_ref"], native["native"]):
            raise ValueError("NATIVE_RESPONSE_ORDER_MISMATCH")
        if not error_id:
            return
        payload = dict(
            kind="reject" if kind == "SUBMIT" else "uncertain",
            order_id=order_id,
            error_id=error_id,
        )
        self.journal.event(
            "ctp-response:" + str(request_id) + ":" + str(error_id), payload, at
        )

    def disconnected(self, at):
        m.time(at)
        self.journal.event(
            "ctp-disconnect:" + at.isoformat(), dict(kind="disconnect"), at
        )

    def expire_unacknowledged(self, now):
        """Bounded caller check, not a background timer or resend policy."""
        for order in self.store.current().orders:
            if (
                order.status == "PROPOSED"
                and order.accepted_at is None
                and (now - order.created_at).total_seconds() >= 25
            ):
                self.journal.find(order.order_id)
                self.journal.event(
                    "ctp-ack-missing:" + order.order_id,
                    dict(kind="uncertain", order_id=order.order_id),
                    now,
                )

    @callback_guard
    def order_callback(self, row, at):
        """Stage whitelisted native facts only; safe during synchronous SDK callback."""
        m.time(at)
        order_id = self.journal.find_ref(row.OrderRef, row.FrontID, row.SessionID)
        bound = self.journal.find(order_id)
        self._identity(row, bound["trading_day"])
        if (
            row.InstrumentID,
            row.ExchangeID,
            row.Direction,
            row.CombOffsetFlag,
            row.CombHedgeFlag,
        ) != (
            bound["native"],
            bound["exchange"],
            "0" if bound["side"] == "BUY" else "1",
            bound["offset"],
            "1",
        ):
            raise ValueError("NATIVE_CALLBACK_ORDER_MISMATCH")
        if (
            Decimal(str(row.LimitPrice)) != Decimal(bound["price"])
            or type(row.VolumeTotalOriginal) is not int
            or row.VolumeTotalOriginal != 1
        ):
            raise ValueError("NATIVE_CALLBACK_PRICE_OR_QUANTITY")
        if (
            type(row.VolumeTraded) is not int
            or type(row.VolumeTotal) is not int
            or (row.VolumeTraded, row.VolumeTotal) not in ((0, 1), (1, 0), (0, 0))
        ):
            raise ValueError("NATIVE_CALLBACK_QUANTITY")
        status = row.OrderStatus
        submit = row.OrderSubmitStatus
        if submit not in ("0", "1", "2", "3", "4", "5", "6") or status not in (
            "0",
            "1",
            "2",
            "3",
            "4",
            "5",
            "a",
            "b",
            "c",
        ):
            raise ValueError("NATIVE_STATUS_UNKNOWN")
        if (status == "0") != (row.VolumeTraded == 1):
            raise ValueError("NATIVE_FILL_STATUS_CONFLICT")
        native_time = datetime.strptime(
            row.InsertDate + row.InsertTime, "%Y%m%d%H:%M:%S"
        ).replace(tzinfo=ZoneInfo("Asia/Shanghai"))
        if self.correlated_native and not self._in_correlated_order(row):
            self._buffer_unverified("order", row, at)
            return None  # Await a complete native readback; never infer from a stream.
        if not self.correlated_native and (native_time > at or native_time + timedelta(
            seconds=1
        ) <= datetime.fromisoformat(bound["created_at"])):
            raise ValueError("NATIVE_ACCEPTANCE_TIME_INVALID")
        payload = dict(
            kind="order",
            order_id=order_id,
            status=status,
            submit=submit,
            traded=row.VolumeTraded,
            remaining=row.VolumeTotal,
            system_id=row.OrderSysID.strip(),
            native_time=native_time.isoformat(),
        )
        event_id = "ctp-order:" + digest(payload)
        self.journal.event(event_id, payload, at)
        return event_id

    @callback_guard
    def trade_callback(self, row, at):
        m.time(at)
        order_id = self.journal.find_ref(row.OrderRef)
        bound = self.journal.find(order_id)
        self._identity(row, bound["trading_day"])
        if (
            row.InstrumentID,
            row.ExchangeID,
            row.Direction,
            row.OffsetFlag,
            row.HedgeFlag,
        ) != (
            bound["native"],
            bound["exchange"],
            "0" if bound["side"] == "BUY" else "1",
            bound["offset"],
            "1",
        ):
            raise ValueError("NATIVE_TRADE_ORDER_MISMATCH")
        if type(row.Volume) is not int or row.Volume != 1:
            raise ValueError("NATIVE_TRADE_QUANTITY")
        price = Decimal(str(row.Price))
        m.money(price, True)
        if (bound["side"] == "BUY" and price > Decimal(bound["price"])) or (
            bound["side"] == "SELL" and price < Decimal(bound["price"])
        ):
            raise ValueError("NATIVE_FILL_OUTSIDE_LIMIT")
        filled_at = datetime.strptime(
            row.TradeDate + row.TradeTime, "%Y%m%d%H:%M:%S"
        ).replace(tzinfo=ZoneInfo("Asia/Shanghai"))
        if not self.correlated_native and filled_at > at:
            raise ValueError("NATIVE_TRADE_TIME_INVALID")
        trade_key = ":".join(
            (
                bound["trading_day"],
                bound["exchange"],
                row.TradeID.strip(),
                row.Direction,
            )
        )
        if not row.TradeID.strip() or not row.OrderSysID.strip():
            raise ValueError("NATIVE_TRADE_ID_MISSING")
        if self.correlated_native and not self._in_correlated_trade(row):
            self._buffer_unverified("trade", row, at)
            return None
        payload = dict(
            kind="trade",
            order_id=order_id,
            trade_id=trade_key,
            system_id=row.OrderSysID.strip(),
            filled_at=filled_at.isoformat(),
            price=str(price),
            fee=None,
        )
        self.journal.event("ctp-trade:" + trade_key, payload, at)
        return trade_key

    def fee(self, proof, at):
        # Native trade callbacks have no fee; never substitute an estimated commission.
        self.journal.event(
            "ctp-fee:" + proof.trade_id,
            dict(
                kind="fee",
                trade_id=proof.trade_id,
                amount=str(proof.amount),
                source_id=proof.source_id,
            ),
            at,
        )

    def drain(self):
        """Replay staged facts idempotently into the account journal. No sends."""
        events = self.journal.events()
        fees = {p["trade_id"]: p for _, p, _ in events if p["kind"] == "fee"}
        resolved = {
            p["pending_id"] for _, p, _ in events if p["kind"] == "correlation"
        }
        pending = []
        for event_id, p, received in events:
            if p["kind"] == "correlation":
                continue
            if p["kind"].startswith("unverified_"):
                if event_id not in resolved:
                    if self.strategy_correlated_native and p["kind"] == "unverified_trade":
                        # A known one-lot trade report conservatively relocks a
                        # cancelled order's occupancy. It is NOT a priced Fill:
                        # the pending fact still blocks sends until full proof.
                        known = next(o for o in self.store.current().orders
                                     if o.order_id == p["order_id"])
                        if known.status != "FILLED":
                            identity = "ctp-known-unverified-fill:" + event_id
                            self.store.execute(identity, m.OrderUpdate(
                                self.session.account_id, known.order_id,
                                max(datetime.fromisoformat(received), self.store.current().clock),
                                identity, "FILLED",
                            ))
                    pending.append(event_id)
                continue
            if self.store.receipt(event_id) is not None:
                continue
            at = datetime.fromisoformat(received)
            if p["kind"] in ("disconnect", "fault", "quarantine"):
                cmd = m.Disconnect(max(at, self.store.current().clock))
            elif p["kind"] in ("reject", "uncertain"):
                cmd = m.OrderUpdate(
                    self.session.account_id,
                    p["order_id"],
                    at,
                    event_id,
                    "REJECTED" if p["kind"] == "reject" else "UNKNOWN",
                )
            elif p["kind"] == "order":
                if p["submit"] == "4":
                    status = "REJECTED"
                elif p["status"] == "0":
                    status = "FILLED"
                elif p["status"] in ("2", "4", "5"):
                    status = "CANCELLED"
                elif p["status"] == "3" and p["submit"] == "3":
                    status = "WORKING"
                elif p["submit"] in ("0", "1", "2") and p["status"] in ("3", "a"):
                    continue
                else:
                    status = "UNKNOWN"
                existing = next(
                    o
                    for o in self.store.current().orders
                    if o.order_id == p["order_id"]
                )
                accepted = existing.accepted_at
                if accepted is None and status == "WORKING":
                    # InsertTime is insertion, not exchange acceptance: use first observed accepted callback.
                    accepted = at
                cmd = m.OrderUpdate(
                    self.session.account_id,
                    p["order_id"],
                    at,
                    event_id,
                    status,
                    accepted,
                )
            elif p["kind"] == "trade":
                proof = fees.get(p["trade_id"])
                correlated = None
                if self.correlated_native:
                    if self._correlated_snapshot is None:
                        pending.append(p["trade_id"])
                        continue
                    snapshot, orders, trades = self._correlated_snapshot
                    correlated = trades.get(p["trade_id"])
                    if correlated is None or correlated[0] != p["order_id"]:
                        pending.append(p["trade_id"])
                        continue
                    native_order = orders[p["order_id"]]
                    native_trade = correlated[1]
                    if (
                        p["system_id"] != native_order["OrderSysID"].strip()
                        or p["system_id"] != native_trade["OrderSysID"].strip()
                        or native_order["OrderStatus"] != "0"
                        or native_order["VolumeTraded"] != 1
                        or native_order["VolumeTotal"] != 0
                        or p["filled_at"] != datetime.strptime(
                            native_trade["TradeDate"] + native_trade["TradeTime"],
                            "%Y%m%d%H:%M:%S",
                        ).replace(tzinfo=ZoneInfo("Asia/Shanghai")).isoformat()
                        or Decimal(p["price"]) != Decimal(native_trade["Price"])
                    ):
                        pending.append(p["trade_id"])
                        continue
                system_ids = {
                    v["system_id"]
                    for _, v, _ in events
                    if v["kind"] == "order"
                    and v["order_id"] == p["order_id"]
                    and v["system_id"]
                }
                if proof is None or system_ids != {p["system_id"]}:
                    if system_ids == {p["system_id"]}:
                        known = next(
                            o
                            for o in self.store.current().orders
                            if o.order_id == p["order_id"]
                        )
                        if known.status != "FILLED":
                            identity = "ctp-known-pending-fill:" + p["trade_id"]
                            self.store.execute(
                                identity,
                                m.OrderUpdate(
                                    self.session.account_id,
                                    p["order_id"],
                                    at,
                                    identity,
                                    "FILLED",
                                ),
                            )
                    pending.append(p["trade_id"])
                    continue
                native = self.journal.find(p["order_id"])
                fill_type = (
                    m.StrategyCorrelatedNativeFillV1 if self.strategy_correlated_native
                    else m.CorrelatedNativeFillV1 if self.correlated_native else m.NativeFill
                )
                correlation = {}
                if self.correlated_native:
                    if not proof["source_id"].startswith("ctp-commission-delta:") or (
                        native["order_ref"], native["front_id"], native["session_id"]
                    ) != (
                        native_order["OrderRef"], native_order["FrontID"],
                        native_order["SessionID"],
                    ):
                        pending.append(p["trade_id"])
                        continue
                    correlation = dict(
                        readback_source_id=snapshot.source_id,
                        native_order_ref=native_order["OrderRef"],
                        native_front_id=native_order["FrontID"],
                        native_session_id=native_order["SessionID"],
                    )
                cmd = fill_type(
                    p["trade_id"],
                    p["order_id"],
                    self.session.account_id,
                    self.journal.find(p["order_id"])["contract"],
                    datetime.fromisoformat(p["filled_at"]),
                    max(at, snapshot.at) if self.correlated_native else at,
                    Decimal(p["price"]),
                    Decimal(proof["amount"]),
                    1,
                    datetime.fromisoformat(native["request_started_at"]),
                    "ctp-dispatch:" + str(native["request_id"]),
                    p["system_id"],
                    **correlation,
                )
            else:
                continue
            self.store.execute(event_id, cmd)
        return tuple(pending)
