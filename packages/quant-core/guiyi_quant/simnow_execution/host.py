"""Shared account reconciliation and scoped execution; no scheduler or broker login."""

from datetime import timedelta
from types import SimpleNamespace
from dataclasses import asdict
from decimal import Decimal
from .. import htdy_account_execution as a
from .inventory import read_snapshot, project_readback, native_order, linked_trade
from .finance import actual_fee, performance
from .model import Permit, action_hash


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
    ):
        if type(continuous) is not bool:
            raise ValueError("HOST_MODE_INVALID")
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
        self.product = product
        self.products = products
        self.continuous = continuous
        self.max_submits = max_submits
        self.run_id = run_id
        self.deadline = deadline
        self.submits = 0
        self.inventory = ()
        self.pending = ()
        self.needs_recovery = store.current().phase != "READY"
        self.baseline = evidence.snapshots()[0] if evidence.snapshots() else None
        self.last_fee_status = "NO_NEW_TRADE"
        self._fee_pairs_scanned = 0

    def reconcile(self, report, bindings, now, proofs=()):
        snapshot = read_snapshot(report, now=now)
        if snapshot.account_id != self.adapter.session.account_id:
            raise ValueError("HOST_NATIVE_ACCOUNT_MISMATCH")
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
        for index in range(len(history) - 1):
            left, right = history[index], history[index + 1]
            fees, reason = actual_fee(left, right, self.store.current(), self.journal)
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
        tx = self.store.execute("native-reconcile:" + snapshot.source_id, command)
        self.needs_recovery = (
            not tx.state.readback_valid
            or tx.state.phase != "READY"
            or not self.continuous
            and self.product in tx.state.blocked_products
        )
        return snapshot, tx.state

    def submit_effects(self, effects, bindings, facts, now):
        effects = tuple(effects)
        # Validate the whole batch before any claim or request is possible.
        if any(e.order.product not in self.products for e in effects):
            raise ValueError("CONTROLLED_PRODUCT_SCOPE_VIOLATION")
        if self.continuous and any(
            e.kind == "SUBMIT" and e.order.offset == "OPEN" for e in effects
        ):
            raise ValueError("CONTINUOUS_OPEN_NOT_AUTHORIZED")
        outcomes = []
        for effect in effects:
            state = self.store.current()
            if self.continuous and self.journal.claimed(
                effect.order.order_id, effect.kind
            ):
                outcomes.append("ALREADY_CLAIMED_NO_SEND")
                continue
            if (
                not self.continuous
                and effect.kind == "SUBMIT"
                and (now >= self.deadline or self.submits >= self.max_submits)
            ):
                self.adapter.abort_unsent(
                    effect.order.order_id, "RUN_BUDGET_EXHAUSTED", now
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
            if effect.kind == "SUBMIT":
                self.submits += 1
            try:
                outcomes.append(
                    self.adapter.dispatch(
                        effect, binding, inventory, execution, permit, now
                    )
                )
            except Exception:
                if effect.kind == "SUBMIT" and not self.journal.claimed(
                    effect.order.order_id
                ):
                    self.adapter.abort_unsent(
                        effect.order.order_id, "LOCAL_PREFLIGHT_FAILED", now
                    )
                raise
        return tuple(outcomes)

    def tick(self, facts, bindings, now):
        facts = tuple(facts)
        if any(f.instrument.product not in self.products for f in facts):
            raise ValueError("CONTROLLED_PRODUCT_SCOPE_VIOLATION")
        tx = self.store.execute(
            "host-tick:" + self.run_id + ":" + now.isoformat(),
            a.ManagedTickV1(now, facts) if self.continuous else a.Tick(now, facts),
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
        return self.submit_effects(tx.effects + pending, bindings, facts, now)

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
