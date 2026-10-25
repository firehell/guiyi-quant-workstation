"""CTP request adapter. Inject a logged-in API; nothing logs in or runs itself."""

from datetime import datetime, UTC, timedelta
from functools import wraps
from decimal import Decimal
import re
from zoneinfo import ZoneInfo
from ..htdy_account_execution import model as m
from ..htdy_account_execution.codec import digest
from .model import action_hash, close_offset, valid, ENVIRONMENT, FRONT


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
    def __init__(self, store, journal, sdk, api, user, session):
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
        self._faulted = False

    def _preflight(self, state, effect, binding, inventory, execution, permit, now):
        if self._faulted or self.journal.uncertain:
            raise ValueError("NATIVE_CALLBACK_OR_COMMIT_REQUIRES_RECOVERY")
        s = self.session
        for identity, payload, _ in self.journal.events():
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
        valid(s.at, s.valid_until, now)
        valid(permit.issued_at, permit.expires_at, now)
        valid(binding.at, binding.valid_until, now)
        if (
            (s.environment, s.front) != (ENVIRONMENT, FRONT)
            or s.account_id != state.account_id
            or permit.account_id != state.account_id
            or permit.trading_day != s.trading_day
        ):
            raise ValueError("DISPATCH_IDENTITY_MISMATCH")
        baseline = state.initial_readback
        if (
            baseline.snapshot.balance != Decimal("100000")
            or (
                baseline.source_id.split(":")[1]
                if baseline.source_id.startswith("ctp-inventory:")
                else baseline.snapshot.at.astimezone(
                    ZoneInfo("Asia/Shanghai")
                ).strftime("%Y%m%d")
            )
            < "20261027"
        ):
            raise ValueError("INITIAL_100K_BASELINE_REQUIRED")
        if (
            state.phase != "READY"
            or not state.readback_valid
            or not state.readback.complete
            or state.clock > now
        ):
            raise ValueError("RECONCILED_ACCOUNT_REQUIRED")
        valid(state.readback.at, state.readback.valid_until, now)
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
        valid(execution.session.at, execution.session.valid_until, now)
        if permit.action_hash != action_hash(
            state, effect, s, binding, inventory, execution
        ):
            raise ValueError("ACTION_PLAN_DRIFT")
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

    def dispatch(self, effect, binding, inventory, execution, permit, now):
        """Only once per order/action, including SDK error, crash and unknown result."""
        with self.store.dispatch_guard() as state:
            offset = self._preflight(
                state, effect, binding, inventory, execution, permit, now
            )
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
        if native_time > at or native_time + timedelta(
            seconds=1
        ) <= datetime.fromisoformat(bound["created_at"]):
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
        if filled_at > at:
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
        pending = []
        for event_id, p, received in events:
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
                cmd = m.NativeFill(
                    p["trade_id"],
                    p["order_id"],
                    self.session.account_id,
                    self.journal.find(p["order_id"])["contract"],
                    datetime.fromisoformat(p["filled_at"]),
                    at,
                    Decimal(p["price"]),
                    Decimal(proof["amount"]),
                    1,
                    datetime.fromisoformat(native["request_started_at"]),
                    "ctp-dispatch:" + str(native["request_id"]),
                    p["system_id"],
                )
            else:
                continue
            self.store.execute(event_id, cmd)
        return tuple(pending)
