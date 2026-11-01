"""Shared account reconciliation and scoped execution; no scheduler or broker login."""

from datetime import datetime, UTC, timedelta
from types import SimpleNamespace
from dataclasses import asdict
from decimal import Decimal
from .. import htdy_account_execution as a
from .inventory import read_snapshot, project_readback, native_order, linked_trade
from .finance import actual_fee, performance
from .model import Permit, action_hash
from .adapter import dispatch_clock
from .account_profile import AccountProfile, validate_profile


class Host:
    def __init__(
        self,
        store,
        journal,
        evidence,
        adapter,
        product,
        *,
        max_submits=1,
        run_id,
        deadline,
        continuous=False,
        manual_test_id=None,
        close_only=False,
        native_validator=None,
        trade=False,
        account_takeover_pending=False,
        takeover_clock=None,
        account_profile=None,
    ):
        if type(account_takeover_pending) is not bool or type(continuous) is not bool:
            raise ValueError("HOST_MODE_INVALID")
        if (
            type(trade) is not bool
            or trade
            and (
                not continuous
                or manual_test_id is not None
                or close_only
                or not getattr(adapter, "strategy_correlated_native", False)
            )
        ):
            raise ValueError("HOST_TRADE_MODE_INVALID")
        strategy_native = getattr(adapter, "strategy_correlated_native", False)
        if type(close_only) is not bool or (
            getattr(adapter, "correlated_native", False)
            and not strategy_native
            and (not close_only or not callable(native_validator))
        ):
            raise ValueError("CLOSE_ONLY_NATIVE_VALIDATOR_REQUIRED")
        if strategy_native and (
            manual_test_id is not None or not callable(adapter.native_validator)
        ):
            raise ValueError("STRATEGY_NATIVE_VALIDATOR_REQUIRED")
        if manual_test_id is not None and (
            type(manual_test_id) is not str
            or not manual_test_id.startswith("manual:")
            or continuous
            or product != "RB"
        ):
            raise ValueError("MANUAL_TEST_SCOPE_INVALID")
        if type(max_submits) is not int or not 1 <= max_submits <= 3:
            raise ValueError("BOUNDED_SUBMIT_BUDGET_REQUIRED")
        products = (product,) if type(product) is str else product
        if (
            type(products) is not tuple
            or not products
            or any(type(p) is not str for p in products)
            or len(set(products)) != len(products)
            or set(products) - {p.product for p in store.current().products}
            or not continuous
            and type(product) is not str
        ):
            raise ValueError("CONTROLLED_PRODUCT_SCOPE_VIOLATION")
        self.store, self.journal, self.evidence, self.adapter = (
            store,
            journal,
            evidence,
            adapter,
        )
        if (account_profile is not None and type(account_profile) is not AccountProfile
            or (account_profile or AccountProfile()) != (getattr(adapter, "account_profile", None) or AccountProfile())):
            raise ValueError("ACCOUNT_PROFILE_HOST_MISMATCH")
        if account_profile is not None:
            validate_profile(account_profile, store.current())
        self.account_profile = account_profile
        self.last_dispatch_diagnostic = None
        self.product = product
        self.products = products
        self.continuous = continuous
        self.trade = trade
        self.manual_test_id = manual_test_id
        self.close_only = close_only
        self.native_validator = native_validator
        self.max_submits = max_submits
        self.run_id = run_id
        self.deadline = deadline
        self.submits = 0
        self.inventory = ()
        self.pending = ()
        self.account_takeover_pending = account_takeover_pending
        self.takeover_clock = takeover_clock or (lambda: datetime.now(UTC))
        self.needs_recovery = (
            account_takeover_pending or store.current().phase != "READY"
        )
        self.baseline = evidence.snapshots()[0] if evidence.snapshots() else None
        self.last_fee_status = "NO_NEW_TRADE"
        self._fee_pairs_scanned = 0

    def reconcile(self, report, bindings, now, proofs=()):
        snapshot = read_snapshot(report, now=now)
        if (
            self.account_takeover_pending
            and not snapshot.at
            <= self.takeover_clock()
            < snapshot.at + timedelta(seconds=30)
        ):
            raise ValueError("ACCOUNT_TAKEOVER_FRESH_READBACK_REQUIRED")
        if snapshot.account_id != self.adapter.session.account_id:
            raise ValueError("HOST_NATIVE_ACCOUNT_MISMATCH")
        if getattr(self.adapter, "correlated_native", False):
            if not getattr(self.adapter, "strategy_correlated_native", False):
                self.native_validator(snapshot)
            self.adapter.correlate_snapshot(snapshot)
        self.evidence.append(snapshot)
        data = snapshot.data
        # Collector has verified account ownership; do not forward raw private codes into persistence.
        for row in data["orders"]:
            identity = native_order(row, self.journal)
            if identity.startswith("external:"):
                continue
            values = {**row, "BrokerID": "9999", "InvestorID": self.adapter._user}
            self.adapter.order_callback(SimpleNamespace(**values), snapshot.at)
        for row in data["trades"]:
            try:
                linked = linked_trade(snapshot, row)
                self.journal.find_ref(linked["OrderRef"])
            except ValueError:
                continue  # Full snapshot retained; unknown trade blocks Readback.
            self.adapter.trade_callback(
                SimpleNamespace(
                    **linked, BrokerID="9999", InvestorID=self.adapter._user
                ),
                snapshot.at,
            )
        # Every new Host replays history, including crash-before-fee. A continuous
        # Host subsequently scans only newly appended adjacent snapshot pairs.
        first_pair = self._fee_pairs_scanned if self.continuous else 0
        history = (
            self.evidence.snapshots(after=first_pair)
            if self.continuous
            else self.evidence.snapshots()
        )
        # Native callbacks and fee() only stage dispatch-journal facts. The
        # account stays unchanged until drain(), so decode its verified state
        # once rather than once per retained snapshot pair during recovery.
        fee_state = self.store.current()
        for index in range(len(history) - 1):
            left, right = history[index], history[index + 1]
            fees, reason = actual_fee(left, right, fee_state, self.journal)
            self.last_fee_status = reason
            for fee in fees:
                self.adapter.fee(fee, right.at)
            if self.continuous:
                self._fee_pairs_scanned = first_pair + index + 1
        self.pending = self.adapter.drain()
        if self.pending:
            return snapshot, None
        state = self.store.current()
        rb, inventory = project_readback(
            snapshot, bindings, self.journal, state, now + timedelta(seconds=30)
        )
        self.inventory = inventory
        if snapshot.at < state.clock:
            return snapshot, None
        command = (
            a.Recover(rb, proofs)
            if self.needs_recovery or state.phase != "READY"
            else rb
        )
        if (
            self.account_takeover_pending
            and not snapshot.at
            <= self.takeover_clock()
            < snapshot.at + timedelta(seconds=30)
        ):
            raise ValueError("ACCOUNT_TAKEOVER_FRESH_READBACK_REQUIRED")
        tx = self.store.execute("native-reconcile:" + snapshot.source_id, command)
        self.needs_recovery = (
            not tx.state.readback_valid
            or tx.state.phase != "READY"
            or not self.continuous
            and self.manual_test_id is None
            and self.product in tx.state.blocked_products
        )
        return snapshot, tx.state

    def complete_takeover(self, snapshot, state, now):
        session = self.adapter.session
        if (
            state is None
            or state != self.store.current()
            or self.store._needs_recovery
            or self.needs_recovery
            or state.phase != "READY"
            or not state.readback_valid
            or not state.readback.complete
            or state.readback.source_id != snapshot.source_id
            or state.readback.snapshot.at != snapshot.at
            or state.account_id != snapshot.account_id
            or snapshot.trading_day != session.trading_day
            or not snapshot.at <= now < snapshot.at + timedelta(seconds=30)
            or not state.readback.snapshot.at <= now < state.readback.valid_until
            or not session.at <= now < session.valid_until
            or not session.login_source_id
            or not session.settlement_source_id
            or self.pending
            or self.adapter._faulted
            or any(not order.reconciled for order in state.orders)
        ):
            raise ValueError("ACCOUNT_TAKEOVER_FRESH_READBACK_REQUIRED")
        fresh = self.takeover_clock()
        if not (
            snapshot.at <= fresh < snapshot.at + timedelta(seconds=30)
            and state.readback.snapshot.at <= fresh < state.readback.valid_until
            and session.at <= fresh < session.valid_until
        ):
            raise ValueError("ACCOUNT_TAKEOVER_FRESH_READBACK_REQUIRED")
        self.adapter.account_takeover_pending = False
        self.account_takeover_pending = False

    def submit_effects(self, effects, bindings, facts, now):
        if getattr(self, "account_takeover_pending", False):
            raise ValueError("ACCOUNT_TAKEOVER_PENDING")
        fresh = dispatch_clock(now, getattr(self.adapter, "clock", None))
        effects = tuple(effects)
        # Validate the whole batch before any claim or request is possible.
        if any(e.order.product not in self.products for e in effects):
            raise ValueError("CONTROLLED_PRODUCT_SCOPE_VIOLATION")
        if self.close_only and any(
            e.kind == "SUBMIT" and e.order.offset != "CLOSE" for e in effects
        ):
            raise ValueError("CLOSE_ONLY_OPEN_FORBIDDEN")
        if (
            self.continuous
            and not self.trade
            and any(e.kind == "SUBMIT" and e.order.offset == "OPEN" for e in effects)
        ):
            raise ValueError("CONTINUOUS_OPEN_NOT_AUTHORIZED")
        if self.manual_test_id is not None:
            if any(e.order.signal_id != self.manual_test_id for e in effects):
                raise ValueError("MANUAL_TEST_SCOPE_INVALID")
            opening = [
                e for e in effects if e.kind == "SUBMIT" and e.order.offset == "OPEN"
            ]
            previous = [
                o
                for o in self.store.current().orders
                if o.offset == "OPEN"
                and o.signal_id == self.manual_test_id
                and self.journal.claimed(o.order_id)
            ]
            if opening and (len(opening) != 1 or previous):
                raise ValueError("MANUAL_OPEN_ALREADY_CLAIMED")
        outcomes = []
        for effect in effects:
            state = self.store.current()
            if self.journal.claimed(effect.order.order_id, effect.kind):
                outcomes.append("ALREADY_CLAIMED_NO_SEND")
                continue
            if (
                not self.continuous
                and effect.kind == "SUBMIT"
                and (self.manual_test_id is None or effect.order.offset == "OPEN")
                and (fresh() >= self.deadline or self.submits >= self.max_submits)
            ):
                self.adapter.abort_unsent(
                    effect.order.order_id, "RUN_BUDGET_EXHAUSTED", fresh()
                )
                outcomes.append("RUN_BUDGET_EXHAUSTED_NO_SEND")
                continue
            binding = next(b for b in bindings if b.canonical == effect.order.contract)
            execution = next(
                f for f in facts if f.instrument.contract == effect.order.contract
            )
            inventory = next(
                (i for i in self.inventory if i.contract == effect.order.contract), None
            )
            permit = Permit(
                "run:" + self.run_id + ":" + effect.kind + ":" + effect.order.order_id,
                state.account_id,
                self.adapter.session.trading_day,
                action_hash(
                    state, effect, self.adapter.session, binding, inventory, execution
                ),
                now,
                now + timedelta(seconds=3),
            )
            # A claimed or unknown send consumes the bounded budget too.
            if effect.kind == "SUBMIT" and (
                self.manual_test_id is None or effect.order.offset == "OPEN"
            ):
                self.submits += 1
            try:
                outcomes.append(
                    self.adapter.dispatch(
                        effect, binding, inventory, execution, permit, fresh()
                    )
                )
                self.last_dispatch_diagnostic = getattr(self.adapter, "last_dispatch_diagnostic", None)
            except Exception:
                self.last_dispatch_diagnostic = getattr(self.adapter, "last_dispatch_diagnostic", None)
                if effect.kind == "SUBMIT" and not self.journal.claimed(
                    effect.order.order_id
                ):
                    self.adapter.abort_unsent(
                        effect.order.order_id, "LOCAL_PREFLIGHT_FAILED", fresh()
                    )
                raise
        return tuple(outcomes)

    def tick(self, facts, bindings, now):
        if getattr(self, "account_takeover_pending", False):
            raise ValueError("ACCOUNT_TAKEOVER_PENDING")
        fresh = dispatch_clock(now, getattr(self.adapter, "clock", None))
        facts = tuple(facts)
        if any(f.instrument.product not in self.products for f in facts):
            raise ValueError("CONTROLLED_PRODUCT_SCOPE_VIOLATION")
        tx = self.store.execute(
            "host-tick:" + self.run_id + ":" + now.isoformat(),
            a.ContinuousTradeTickV1(now, facts)
            if self.trade
            else a.ManagedTickV1(now, facts)
            if self.continuous
            else a.Tick(now, facts),
        )
        pending = tuple(
            a.Effect("CANCEL", o)
            for o in tx.state.orders
            if o.product in self.products
            and o.status == "CANCEL_PENDING"
            and o.cancel_sent
            and not o.reconciled
            and not self.journal.claimed(o.order_id, "CANCEL")
            and all(e.order.order_id != o.order_id for e in tx.effects)
        )
        return self.submit_effects(tx.effects + pending, bindings, facts, fresh())

    def summary(self, snapshot):
        state = self.store.current()
        values = asdict(performance(self.baseline or snapshot, snapshot))
        values = {k: str(v) if isinstance(v, Decimal) else v for k, v in values.items()}
        return dict(
            account_id=state.account_id,
            phase=state.phase,
            readback_valid=state.readback_valid,
            position_projection_complete=state.readback_valid
            and state.phase == "READY"
            and not self.pending
            and not state.unresolved_fill_ids,
            positions=[asdict(p) for p in state.positions],
            orders=[
                dict(
                    order_id=o.order_id,
                    contract=o.contract,
                    side=o.side,
                    offset=o.offset,
                    status=o.status,
                    reconciled=o.reconciled,
                    native_claimed=self.journal.claimed(o.order_id),
                )
                for o in state.orders
            ],
            reservations=[
                dict(
                    order_id=r.order_id,
                    margin=str(r.margin),
                    fee=str(r.fee),
                    released=r.released,
                )
                for r in state.reservations
            ],
            closing_obligations=[
                p.product for p in state.products if p.must_close or p.rolling
            ],
            fills=[
                dict(
                    trade_id=f.trade_id,
                    order_id=f.order_id,
                    contract=f.contract,
                    price=str(f.price),
                    fee=str(f.fee),
                    filled_at=f.filled_at.isoformat(),
                    recorded_at=f.recorded_at.isoformat(),
                    native_precision_seconds=getattr(f, "native_precision_seconds", 0),
                )
                for f in state.fills
            ],
            unresolved_fills=list(state.unresolved_fill_ids),
            pending_fees_or_identity=list(self.pending),
            fee_status=self.last_fee_status,
            submit_budget_used=self.submits,
            performance=values,
            auto_order=False,
            broker_e2e_passed=False,
        )
