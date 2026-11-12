"""The shared HTDY reducer owns targets/risk. This boundary owns TqKq I/O facts."""

from datetime import datetime, UTC, timedelta
from pathlib import Path
from ..htdy_account_execution import model as m
from ..htdy_execution import OrderReport
from ..htdy_account_execution.store import LocalStore
from ..htdy_account_execution.codec import digest as command_digest
from ..htdy_account_execution.reducer import start, never_active
from .journal import Journal, digest
from .gateway import SubmissionNotSent, decimal, quantity, instant_ns

TERMINAL = {"FILLED", "CANCELLED", "REJECTED"}


class Controller:
    def __init__(self, root, account_id, products, gateway):
        self.root = Path(root)
        self.account_id = account_id
        self.products = tuple(products)
        self.gateway = gateway
        self.clock = lambda: datetime.now(UTC)
        self.journal = Journal(self.root / "dispatch.sqlite", account_id)
        self.store = None
        self.identity = "TQKQ:" + account_id + ":htdy_tqkq_v1"
        path = self.root / "account.sqlite"
        if path.exists():
            self.store = LocalStore(path, execution_identity=self.identity)
        self.symbols = {}
        for payload in self.journal.events("symbol"):
            self.symbols[payload["symbol"]] = (payload["product"], payload["contract"])
        self.last_snapshot = None

    def bind_symbol(self, symbol, product, contract):
        if product not in self.products:
            raise ValueError("TQ_PRODUCT_NOT_AUTHORIZED")
        prior = self.symbols.get(symbol)
        if prior is not None and prior != (product, contract):
            raise ValueError("TQ_SYMBOL_IDENTITY_DRIFT")
        if any(
            v == (product, contract) and k != symbol for k, v in self.symbols.items()
        ):
            raise ValueError("TQ_SYMBOL_AMBIGUOUS")
        self.journal.event(
            "symbol",
            dict(symbol=symbol, product=product, contract=contract),
            datetime.now(UTC),
        )
        self.symbols[symbol] = (product, contract)

    def bootstrap(self, snapshot, at):
        if self.store is not None:
            return
        if snapshot["positions"] or any(
            o["state"] not in TERMINAL for o in snapshot["orders"]
        ):
            raise ValueError("TQ_INITIAL_ACCOUNT_NOT_FLAT")
        rb = self.readback(snapshot, at)
        self.store = LocalStore(
            self.root / "account.sqlite",
            start(self.account_id, self.products, at, rb),
            execution_identity=self.identity,
        )
        self.journal.event("baseline", snapshot, at)

    def readback(self, snapshot, at):
        if snapshot["account_id"] != self.account_id:
            raise ValueError("TQ_ACCOUNT_IDENTITY_MISMATCH")
        mappings = self.journal.mappings()
        orders = tuple(
            OrderReport(
                mappings.get(o["order_id"], "external:" + o["order_id"]), o["state"]
            )
            for o in snapshot["orders"]
        )
        positions = []
        for p in snapshot["positions"]:
            if p["symbol"] not in self.symbols:
                raise ValueError("TQ_EXTERNAL_POSITION")
            product, contract = self.symbols[p["symbol"]]
            long = p["pos_long_today"] + p["pos_long_his"]
            short = p["pos_short_today"] + p["pos_short_his"]
            if long + short != 1:
                raise ValueError("TQ_ONE_LOT_INVENTORY_REQUIRED")
            positions.append(m.Position(product, contract, 1 if long else -1))
        if len({p.product for p in positions}) != len(positions):
            raise ValueError("TQ_MULTIPLE_PHYSICAL_POSITIONS")
        a = snapshot["account"]
        source = "tq-readback:" + digest(
            {"snapshot": snapshot, "recorded_at": at.isoformat()}
        )
        snap = m.AccountSnapshot(
            self.account_id,
            at,
            decimal(a["balance"], positive=True),
            decimal(a["available"]),
            tuple(positions),
            orders,
            tuple(o.order_id for o in orders if o.status in {"CANCELLED", "REJECTED"}),
        )
        return m.Readback(
            snap,
            decimal(a["margin"]),
            decimal(a["frozen_margin"]),
            decimal(a["frozen_commission"]),
            (),
            tuple("tq-trade:" + t["trade_id"] for t in snapshot["trades"]),
            source,
            at + timedelta(seconds=10),
            True,
        )

    def synchronize(self, snapshot, at):
        if self.store is None:
            self.bootstrap(snapshot, at)
        self.journal.event("snapshot", snapshot, at)
        mappings = self.journal.mappings()
        state = self.store.current()
        if any(not order.reconciled for order in state.orders):
            self._finish_recorded_unsent(snapshot, state, at)
            state = self.store.current()
        known_fills = {f.trade_id: f for f in state.fills}
        initial_trades = set(state.initial_readback.confirmed_trade_ids)
        native_orders = {o["order_id"]: o for o in snapshot["orders"]}
        for trade in sorted(
            snapshot["trades"], key=lambda t: (t["trade_date_time"], t["trade_id"])
        ):
            tid = "tq-trade:" + trade["trade_id"]
            if tid in initial_trades:
                continue
            oid = mappings.get(trade["order_id"])
            if oid is None:
                raise ValueError("TQ_EXTERNAL_TRADE")
            order = next(
                (o for o in self.store.current().orders if o.order_id == oid), None
            )
            if order is None:
                raise ValueError("TQ_ORDER_JOURNAL_MISSING")
            symbol = trade["exchange_id"] + "." + trade["instrument_id"]
            if (
                self.symbols.get(symbol) != (order.product, order.contract)
                or trade["direction"] != order.side
                or quantity(trade["volume"]) != 1
            ):
                raise ValueError("TQ_FILL_CORRELATION_INVALID")
            claim = self.journal.submit_payload(oid)
            if trade["offset"] != claim["offset"]:
                raise ValueError("TQ_FILL_OFFSET_INVALID")
            price = decimal(trade["price"], positive=True)
            filled = instant_ns(trade["trade_date_time"])
            if tid in known_fills:
                old = known_fills[tid]
                if (old.order_id, old.price, old.filled_at) != (oid, price, filled):
                    raise ValueError("TQ_TRADE_IDENTITY_DRIFT")
                continue
            if trade["order_id"] not in native_orders:
                raise ValueError("TQ_FILL_ORDER_PROOF_MISSING")
            # Public TqSdk Trade does not contain commission: retain unknown,
            # with the actual aggregate commission in every account snapshot.
            fill = m.TqKqFill(
                tid,
                oid,
                self.account_id,
                order.contract,
                filled,
                at,
                price,
                None,
                1,
                trade["trade_id"],
                trade["order_id"],
                snapshot["snapshot_id"],
            )
            self.store.execute("fill:" + tid, fill)
            known_fills[tid] = fill
        for native in snapshot["orders"]:
            oid = mappings.get(native["order_id"])
            if oid is None:
                continue  # apply_readback independently rejects any new external order.
            order = next(
                (o for o in self.store.current().orders if o.order_id == oid), None
            )
            if order is None:
                raise ValueError("TQ_ORDER_JOURNAL_MISSING")
            if quantity(native["volume_orign"]) != 1:
                raise ValueError("TQ_ORDER_VOLUME_DRIFT")
            symbol = native["exchange_id"] + "." + native["instrument_id"]
            if (
                self.symbols.get(symbol) != (order.product, order.contract)
                or native["direction"] != order.side
            ):
                raise ValueError("TQ_ORDER_CORRELATION_INVALID")
            claim = self.journal.submit_payload(oid)
            if native["offset"] != claim["offset"]:
                raise ValueError("TQ_ORDER_OFFSET_INVALID")
            if native.get("price_type") != "LIMIT" or decimal(
                native.get("limit_price"), positive=True
            ) != decimal(claim["price"], positive=True):
                raise ValueError("TQ_ORDER_PRICE_DRIFT")
            status = native["state"]
            if status == "UNKNOWN":
                cancel = self.journal.db.execute(
                    "SELECT at FROM claims WHERE kind='CANCEL' AND order_id=?", (oid,)
                ).fetchone()
                anchor = (
                    datetime.fromisoformat(cancel[0]) if cancel else order.created_at
                )
                if at - anchor <= timedelta(seconds=10):
                    raise ValueError("TQ_AWAITING_ORDER_FACTS")
                raise ValueError("TQ_ORDER_OUTCOME_UNKNOWN")
            source = "tq-order:" + digest(native)
            key = "order:" + source
            if self.store.receipt(key) is not None:
                continue
            accepted = order.accepted_at or (at if status == "WORKING" else None)
            self.store.execute(
                key, m.OrderUpdate(self.account_id, oid, at, source, status, accepted)
            )
        missing = set(mappings) - set(native_orders)
        for native_id in missing:
            order = next(
                (
                    o
                    for o in self.store.current().orders
                    if o.order_id == mappings[native_id]
                ),
                None,
            )
            if order is None or not order.reconciled:
                if order is not None and at - order.created_at <= timedelta(seconds=10):
                    raise ValueError("TQ_AWAITING_ORDER_FACTS")
                raise ValueError("TQ_SEND_OUTCOME_UNKNOWN")
        state = self.store.current()
        for order in state.orders:
            native_id = next(
                (n for n, c in mappings.items() if c == order.order_id), None
            )
            native = native_orders.get(native_id)
            if (
                native
                and native["state"] == "FILLED"
                and not any(f.order_id == order.order_id for f in state.fills)
            ):
                if (
                    order.terminal_at is not None
                    and at - order.terminal_at <= timedelta(seconds=10)
                ):
                    raise ValueError("TQ_AWAITING_TRADE_FACTS")
                raise ValueError("TQ_TRADE_FACTS_TIMEOUT")
        rb = self.readback(snapshot, at)
        if sorted(rb.snapshot.positions, key=lambda p: p.product) != sorted(
            state.positions, key=lambda p: p.product
        ):
            latest = max((f.recorded_at for f in state.fills), default=None)
            if latest is not None and at - latest <= timedelta(seconds=10):
                raise ValueError("TQ_AWAITING_ACCOUNT_FACTS")
            raise ValueError("TQ_POSITION_MISMATCH")
        if self.store.current().phase == "READY":
            self.store.execute("readback:" + rb.source_id, rb)
        # Reopening always requires an explicit Recover with authoritative source
        # proofs. Never turn a reopened empty projection into a new account.
        self.last_snapshot = snapshot
        return rb

    def owner(self, product, contract, at, source):
        cmd = m.Owner(product, contract, at, source)
        self.store.execute("owner:" + source, cmd)

    def signal(self, signal, *, processed_at=None, closed_at=None):
        key = "tq-signal:" + signal.source_id
        prior = next((a.command for a in self.store.current().audit if a.command_id == key), None)
        if prior is not None:
            original = prior.signal if type(prior) in (m.TqKqObservedSignalV1, m.TqKqClosedSignalV1) else prior
            if original != signal:
                raise ValueError("TQ_SIGNAL_IDENTITY_DRIFT")
            return
        at = processed_at or datetime.now(UTC)
        command = (m.TqKqObservedSignalV1(signal, at) if closed_at is None
                   else m.TqKqClosedSignalV1(signal, at, closed_at))
        self.store.execute(key, command)

    def resume_never_active(self, rb, at):
        if (
            not never_active(self.store.current())
            or rb.snapshot.positions or rb.snapshot.orders or rb.confirmed_trade_ids
            or rb.used_margin or rb.frozen_margin or rb.frozen_fee
            or not rb.at <= at < rb.valid_until
            or self.journal.db.execute("SELECT COUNT(*) FROM claims").fetchone()[0] != 0
        ):
            return False
        proof = digest({"account_id": self.account_id, "claims": []})
        cmd = m.TqKqResumeEmptyV1(rb, proof)
        self.store.execute("tq-empty-resume:" + command_digest(cmd), cmd)
        return True

    def recover(self, rb, proofs):
        cmd = m.Recover(rb, tuple(proofs))
        self.store.execute("tq-recover:" + command_digest(cmd), cmd)
        if self.store.current().phase != "READY":
            raise ValueError("TQ_ACCOUNT_RECONCILIATION_REQUIRED")

    def tick(self, inputs, at, *, opening_allowed, stopping=False):
        cmd = m.TqKqTick(at, tuple(inputs), opening_allowed, stopping=stopping)
        tx = self.store.execute("tq-tick:" + command_digest(cmd), cmd)
        for effect in tx.effects:
            fact = next(
                (i for i in inputs if i.instrument.contract == effect.order.contract),
                None,
            )
            if fact is None:
                raise ValueError("TQ_EXECUTION_FACT_MISSING")
            self.dispatch(
                effect, fact, datetime.now(UTC), opening_allowed=opening_allowed
            )
        return tx

    def dispatch(self, effect, fact, at, *, opening_allowed):
        try:
            return self._dispatch(effect, fact, at, opening_allowed=opening_allowed)
        except SubmissionNotSent as error:
            self.abort_unsent(effect.order.order_id, str(error), native_id=error.native_id)
            return "LOCAL_NOT_SENT"

    def _finish_recorded_unsent(self, snapshot, state, at):
        native_ids = {row["order_id"] for row in (*snapshot["orders"], *snapshot["trades"])}
        pending = {order.order_id: order for order in state.orders if not order.reconciled}
        for payload in self.journal.events("local_not_sent"):
            if payload.get("version") != 1 or payload.get("order_id") not in pending:
                continue
            if (set(payload) != {"version", "order_id", "native_id", "reason"}
                    or payload["reason"] not in {"TQ_OPPONENT_PRICE_DRIFT", "TQ_SUBMIT_EXPIRED_NO_SEND"}):
                raise ValueError("TQ_UNSENT_PROOF_CONFLICT")
            if payload.get("native_id") in native_ids:
                raise ValueError("TQ_UNSENT_NATIVE_CONFLICT")
            self.abort_unsent(payload["order_id"], payload["reason"], native_id=payload["native_id"], at=at)

    def abort_unsent(self, order_id, reason, *, native_id=None, at=None):
        def proven(_state):
            claim = self.journal.db.execute(
                "SELECT native_id FROM claims WHERE order_id=? AND kind='SUBMIT'", (order_id,)
            ).fetchone()
            return claim == ((native_id,) if native_id is not None else None)

        evidence = {"version": 1, "order_id": order_id, "native_id": native_id, "reason": reason}
        if not proven(None):
            raise ValueError("TQ_UNSENT_PROOF_CONFLICT")
        at = self.clock() if at is None else at
        source = self.journal.event("local_not_sent", evidence, at)
        return self.store.execute(
            "tq-abort-unsent:" + order_id,
            m.AbortUnsent(self.account_id, order_id, at, source, reason),
            unsent_proof=proven,
        )

    def _dispatch(self, effect, fact, at, *, opening_allowed):
        from ..htdy_account_execution.scheduling import executable_price

        order = effect.order
        self.gateway.assert_continuity()
        with self.store.dispatch_guard() as state:
            at = self.clock()
            current = next(
                (o for o in state.orders if o.order_id == order.order_id), None
            )
            if current != order or not state.readback_valid or state.phase != "READY":
                raise ValueError("TQ_DISPATCH_STATE_DRIFT")
            if effect.kind == "SUBMIT" and (
                order.instrument_source != fact.instrument.source_id
                or order.session_source != fact.session.source_id
                or fact.quote is None
                or order.quote_source != fact.quote.source_id
            ):
                raise ValueError("TQ_DISPATCH_FACT_DRIFT")
            if not state.readback.at <= at < state.readback.valid_until:
                if effect.kind == "SUBMIT" and at >= state.readback.valid_until:
                    raise SubmissionNotSent("TQ_SUBMIT_EXPIRED_NO_SEND")
                raise ValueError("TQ_ACCOUNT_STALE")
            if not fact.session.at <= at < fact.session.valid_until:
                raise ValueError("TQ_SESSION_STALE")
            symbol = next(
                (
                    s
                    for s, p in self.symbols.items()
                    if p == (order.product, order.contract)
                ),
                None,
            )
            if symbol is None:
                raise ValueError("TQ_SYMBOL_UNBOUND")
            offset = order.offset
            if effect.kind == "CANCEL":
                if not order.cancel_sent or not fact.session.can_cancel:
                    raise ValueError("TQ_CANCEL_NOT_QUALIFIED")
                native = next(
                    (
                        n
                        for n, c in self.journal.mappings().items()
                        if c == order.order_id
                    ),
                    None,
                )
                if native is None:
                    raise ValueError("TQ_CANCEL_ORDER_UNPROVEN")
                payload = {"symbol": symbol, "order_id": order.order_id}
            elif effect.kind == "SUBMIT":
                if (
                    order.status != "PROPOSED"
                    or order.cancel_sent
                    or not fact.session.can_trade
                ):
                    raise ValueError("TQ_SUBMIT_NOT_QUALIFIED")
                price = executable_price(fact, order.side, at)
                if price is None:
                    raise SubmissionNotSent("TQ_SUBMIT_EXPIRED_NO_SEND")
                if price != order.price:
                    raise ValueError("TQ_OPPONENT_PRICE_DRIFT")
                if order.offset == "OPEN" and (
                    not opening_allowed
                    or at >= fact.session.final_close_at - timedelta(seconds=60)
                ):
                    raise ValueError("TQ_OPENING_DISABLED")
                if order.offset == "CLOSE" and symbol.split(".")[0] in {"SHFE", "INE"}:
                    p = next(
                        (
                            p
                            for p in self.last_snapshot["positions"]
                            if p["symbol"] == symbol
                        ),
                        None,
                    )
                    if p is None:
                        raise ValueError("TQ_CLOSE_POSITION_MISSING")
                    side = "long" if order.side == "SELL" else "short"
                    today = p["pos_" + side + "_today"]
                    his = p["pos_" + side + "_his"]
                    if today + his != 1:
                        raise ValueError("TQ_CLOSE_INVENTORY_INVALID")
                    offset = "CLOSETODAY" if today == 1 else "CLOSE"
                payload = {
                    "symbol": symbol,
                    "side": order.side,
                    "offset": offset,
                    "volume": 1,
                    "price": str(order.price),
                    "profile": "htdy_tqkq_v1",
                }
            else:
                raise ValueError("TQ_EFFECT_INVALID")
            native_claim = self.journal.claim(effect.kind, order.order_id, payload, at)
            if native_claim is None:
                return "ALREADY_CLAIMED_NO_SEND"
            if effect.kind == "CANCEL":
                self.gateway.cancel(native)
            else:
                checked = getattr(self.gateway, "submit_checked", None)
                if checked is None:
                    self.gateway.submit(symbol, order, offset, native_claim)
                else:
                    deadline = min(state.readback.valid_until, fact.session.valid_until,
                                   fact.instrument.valid_until, fact.quote.valid_until,
                                   fact.session.final_close_at - timedelta(seconds=60)
                                   if order.offset == "OPEN" else fact.session.final_close_at)
                    try:
                        checked(symbol, order, offset, native_claim, deadline)
                    except SubmissionNotSent as error:
                        if error.native_id != native_claim:
                            raise ValueError("TQ_UNSENT_PROOF_CONFLICT") from error
                        raise
            # Queued is not sent, accepted or filled; wait_update/remote facts
            # alone can advance those stages. Any thrown/unknown result is held.
            self.journal.event(
                "queued", {"kind": effect.kind, "order_id": order.order_id}, at
            )
            return "QUEUED_AWAIT_REMOTE"

    def close(self):
        if self.store is not None:
            self.store.close()
        self.journal.close()
