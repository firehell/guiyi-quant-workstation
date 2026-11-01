"""Single account coordinator. Automatic startup defaults to broker read-only.

Market and broker transports are injected. No order is retried by this scheduler;
only new *connections* have a durable, bounded retry budget.
"""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
import fcntl
import json
import os
import re
import stat
import tempfile
import time
import uuid

from .. import htdy_account_execution as a
from ..htdy_execution import Owner
from ..htdy_account_execution.codec import digest
from .inbox import SignalInbox
from .inventory import project_readback, native_order, linked_trade, trade_identity
from .evidence import Evidence
from .monitor import MonitorPublisher
from .observe_reconciliation import build_proof


def global_account_lock_directory():
    return Path.home() / "Library/Application Support/GuiyiQuant/SimNowLocks"


@contextmanager
def account_lock(settings):
    if getattr(settings, "schema", 1) == 3:
        raise ValueError("PREPARATION_ONLY")
    with global_account_lock(settings.account_id), _state_lock(settings) as folder:
        yield folder


@contextmanager
def global_account_lock(account_id):
    """The same identity lock also excludes one-shot observe bootstrap readers."""
    if type(account_id) is not str or re.fullmatch(r"[0-9a-f]{64}", account_id) is None:
        raise ValueError("CONTINUOUS_ACCOUNT_SCOPE_MISMATCH")
    directory = global_account_lock_directory()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = directory.stat()
    if (
        directory.is_symlink()
        or directory.resolve() != directory
        or info.st_uid != os.getuid()
        or info.st_mode & 0o077
    ):
        raise ValueError("PRIVATE_ACCOUNT_ROOT_INVALID")
    global_fd = os.open(
        directory / (account_id + ".lock"),
        os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW,
        0o600,
    )
    try:
        info = os.fstat(global_fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
        ):
            raise ValueError("PRIVATE_ACCOUNT_ROOT_INVALID")
        try:
            fcntl.flock(global_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("ACCOUNT_HOST_ALREADY_RUNNING") from None
        yield
    finally:
        os.close(global_fd)


@contextmanager
def _state_lock(settings):
    # Same exact root/file as the existing bounded host. Resolve aliases first.
    base = Path(settings.state_root)
    if getattr(settings, "schema", 1) == 2:
        from .account_binding import existing_account

        existing_account(base, settings.account_id)
    if base.is_symlink():
        raise ValueError("PRIVATE_ACCOUNT_ROOT_INVALID")
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    folder = base / settings.account_id
    folder.mkdir(mode=0o700, exist_ok=True)
    if (
        folder.is_symlink()
        or folder.stat().st_mode & 0o077
        or base.stat().st_mode & 0o077
    ):
        raise ValueError("PRIVATE_ACCOUNT_ROOT_INVALID")
    fd = os.open(folder / "host.lock", os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("ACCOUNT_HOST_ALREADY_RUNNING") from None
        yield folder
    finally:
        os.close(fd)


def publish_status(folder, value):
    """Private atomic health; no secrets, raw exceptions or inferred connectivity."""
    fd, name = tempfile.mkstemp(prefix=".continuous-", dir=folder)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, sort_keys=True, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, folder / "continuous.json")
    finally:
        if os.path.exists(name):
            os.unlink(name)


def retain_failure(folder, run_id, sequence, code, at, diagnostic):
    """One immutable sanitized failure fact, retained before native release."""
    path = folder / ("failure-" + run_id + "-" + str(sequence) + ".json")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(
            dict(
                schema="simnow_continuous_failure_v1",
                code=code,
                at=at.isoformat(),
                diagnostic=diagnostic,
            ),
            stream,
            sort_keys=True,
        )
        stream.flush()
        os.fsync(stream.fileno())


def verify_recovery_ownership(snapshot, bindings, journal, state):
    """Allow known offline fills to be replayed before position/fee projection.

    This is only an ownership gate before settlement; full Host reconciliation
    and fee proof still precede any send. Never require stale local positions to
    equal a snapshot containing a newly filled, already-claimed native order.
    """
    project_readback(
        snapshot, bindings, journal, state, snapshot.at + timedelta(seconds=30)
    )
    known_orders = {o.order_id for o in state.orders}
    for row in snapshot.data["orders"]:
        if native_order(row, journal) not in known_orders:
            raise ValueError("UNEXPLAINED_NATIVE_ORDER")
    known_trades = {f.trade_id for f in state.fills} | set(
        state.initial_readback.confirmed_trade_ids
    )
    for row in snapshot.data["trades"]:
        if trade_identity(row) in known_trades:
            continue
        linked = linked_trade(snapshot, row)
        if journal.find_ref(linked["OrderRef"]) not in known_orders:
            raise ValueError("UNEXPLAINED_NATIVE_TRADE")


_RECOVERY_ERRORS = frozenset({
    "NATIVE_SETTLEMENT_CONFIRMATION_REQUIRED", "NATIVE_SETTLEMENT_IDENTITY_MISMATCH",
    "NATIVE_FACT_QUERY_FAILED", "NATIVE_GATEWAY_FAILED", "NATIVE_READBACK_INVALID",
    "NATIVE_SESSION_IDENTITY_MISMATCH", "CONTINUOUS_ACCOUNT_SCOPE_MISMATCH",
    "ACCOUNT_TAKEOVER_FRESH_READBACK_REQUIRED", "ACCOUNT_PROFILE_ANCHOR_MISMATCH",
    "ACCOUNT_PROFILE_HOST_MISMATCH", "HOST_NATIVE_ACCOUNT_MISMATCH",
    "NATIVE_FUTURE_READBACK", "NATIVE_QUERY_INCOMPLETE", "NATIVE_READBACK_CHANGED_OR_HASH_INVALID",
    "UNEXPLAINED_NATIVE_POSITION", "UNEXPLAINED_NATIVE_ORDER", "UNEXPLAINED_NATIVE_TRADE",
    "NATIVE_POSITION_MARGIN_UNEXPLAINED",
    "NATIVE_FROZEN_WITHOUT_PENDING_ORDER", "LOCAL_STORE_INVALID", "NATIVE_RECOVERY_REQUIRED",
    "NATIVE_FACT_QUERY_REJECTED", "NATIVE_FACT_RESPONSE_IDENTITY", "NATIVE_FACT_ACCOUNT_MISMATCH",
    "NATIVE_SNAPSHOT_CHANGED", "EXISTING_ACCOUNT_JOURNAL_REQUIRED",
})


class Supervisor:
    def __init__(
        self,
        settings,
        products,
        market,
        driver_factory,
        *,
        clock=None,
        sleep=None,
        stopped=None,
    ):
        if settings.mode not in {"observe", "manage", "trade"}:
            raise ValueError("CONTINUOUS_MODE_INVALID")
        self.settings, self.products, self.market = (
            settings,
            tuple(sorted(products)),
            market,
        )
        self.factory = driver_factory
        self.now = clock or (lambda: datetime.now(UTC))
        self.sleep = sleep or time.sleep
        self.stopped = stopped or (lambda: False)
        self.run_id = uuid.uuid4().hex
        self.driver = self.store = self.journal = self.host = None
        self.day = None
        self.observed_state = None
        self.issues = {}
        self.input_diagnostics = {}
        self.input_checks = {}
        self.retry_after = self.now()
        self.blocked_day = None
        self.target_day = None
        self.active_seen = False
        self.prepared = False
        self.recovery_stage = "NOT_STARTED"
        self.account_takeover_pending = getattr(
            settings, "account_takeover_pending", False
        )
        self.ledger_hash = None
        self.session_active = False

    def status(self, code, *, connected=False):
        state = self.store.current() if self.store is not None else None
        opening = bool(
            code == "TRADING"
            and not self.account_takeover_pending
            and self.settings.mode == "trade"
            and self.settings.enabled
            and connected
            and self.prepared
            and self.session_active
            and state is not None
            and state.phase == "READY"
            and state.readback_valid
            and not any(not order.reconciled for order in state.orders)
            and state.readback.at <= self.now() < state.readback.valid_until
            and self.host is not None
            and not self.host.pending
            and not self.host.adapter._faulted
        )
        if self.driver is not None:
            self.input_diagnostics = dict(getattr(self.driver, "input_diagnostics", {}))
            self.input_checks = dict(getattr(self.driver, "input_checks", {}))
        from .input_evidence import input_check_records

        value = dict(
            schema="simnow_continuous_v2",
            run_id=self.run_id,
            mode=self.settings.mode,
            status=code,
            at=self.now().isoformat(),
            connection="LOGGED_IN" if connected else "UNKNOWN",
            trading_day=self.day,
            products=list(self.products),
            issues={**self.market.issues, **self.issues},
            input_diagnostics=self.input_diagnostics,
            dispatch_diagnostic=getattr(self.host, "last_dispatch_diagnostic", None),
            input_checks=input_check_records(self.input_checks, products=self.products),
            auto_order=self.settings.mode == "trade" and self.settings.enabled,
            opening_enabled=opening,
            account_takeover_pending=self.account_takeover_pending,
            broker_e2e_passed=False,
        )
        # Monitoring must not change a trading decision.
        try:
            publish_status(self.folder, value)
            self.monitor.publish(
                "READING" if connected else "STARTING",
                self.now(),
                connection="LOGGED_IN" if connected else "UNKNOWN",
                native_source_id=self.latest_source,
                ledger_hash=self.ledger_hash,
                mode=self.settings.mode,
                opening_enabled=opening,
                host_status=code,
                account_takeover_pending=self.account_takeover_pending,
                observe_reconciliation=(
                    getattr(self, "observe_reconciliation", None)
                    if connected and self.prepared and self.settings.mode == "observe"
                    else None
                ),
            )
        except Exception:
            pass

    def disconnect(self):
        failed = False
        uncertain = bool(
            (self.store is not None and self.store._uncertain)
            or (self.journal is not None and self.journal.uncertain)
        )
        try:
            if self.host is not None and not uncertain:
                try:
                    self.host.adapter.disconnected(self.now())
                except Exception:
                    failed = True
            if self.driver is not None:
                try:
                    self.driver.close()
                except Exception:
                    failed = True
            # Callbacks may only finish staging after the native API is released.
            if self.host is not None and not uncertain:
                try:
                    self.host.adapter.drain()
                except Exception:
                    failed = True
            self.inbox.recover_queue(self.store)
        finally:
            for item in (self.store, self.journal):
                if item is not None:
                    item.close()
            self.driver = self.store = self.journal = self.host = None
            self.prepared = False
            if getattr(self.settings, "account_takeover_pending", False):
                self.account_takeover_pending = True
            self.observe_reconciliation = None
            self.market.activate(self.now())
        if failed:
            if self.target_day:
                self.inbox.block(self.target_day, "CONTINUOUS_CLEANUP_UNCERTAIN")
            raise ValueError("CONTINUOUS_CLEANUP_UNCERTAIN")

    def _ordinary_permit_required(self, day):
        if not getattr(self.settings, "ordinary_takeover_permit", None):
            return False
        from . import ordinary_takeover

        return ordinary_takeover.permit_required(self.settings, day)

    def _ordinary_authority(self, day):
        now = self.now()
        plan = self.market.plan(now)
        if (
            not plan.connect_allowed
            or plan.trading_day is None
            or plan.trading_day.strftime("%Y%m%d") != day
        ):
            raise ValueError("ORDINARY_TAKEOVER_INVALID")
        return self.market.ordinary_takeover_window(day, now)

    def connect(self, day):
        self.target_day = day
        self.active_seen = False
        from . import deployment_connection as permit

        configured = getattr(self.settings, "deployment_connection_permit", None)
        extra_candidate = bool(
            configured and day == permit.DAY and permit.attempts(self.inbox, day) == 3
        )
        if self.inbox.blocked(day) and not extra_candidate:
            raise ValueError(
                "DEPLOYMENT_CONNECTION_INVALID"
                if configured
                else "CONNECTION_BUDGET_EXHAUSTED"
            )
        permit_window = None
        ordinary_window = None
        if self._ordinary_permit_required(day):
            from . import ordinary_takeover

            attempt, ordinary_window = ordinary_takeover.consume(
                self.settings,
                self.inbox,
                self.run_id,
                day,
                self.now(),
                clock=self.now,
                authority=lambda: self._ordinary_authority(day),
            )
        elif configured and day == permit.DAY and permit.attempts(self.inbox, day) >= 3:
            permit_window = permit.consume(
                self.settings, self.inbox, self.run_id, day, self.now(), clock=self.now
            )
            self.deployment_connection_used = True
            attempt = 1
        else:
            attempt = self.inbox.attempt(day)
        self.status("CONNECTING")
        if permit_window:
            permit.connection_time(permit_window, self.now())
        if ordinary_window:
            ordinary_takeover.validate_connection(
                ordinary_window, self.now(), lambda: self._ordinary_authority(day)
            )
            ordinary_takeover.connection_time(ordinary_window, self.now())
        self.driver = self.factory(self.settings, self.folder)
        if permit_window:
            permit.connection_time(permit_window, self.now())
        if ordinary_window:
            ordinary_takeover.validate_connection(
                ordinary_window, self.now(), lambda: self._ordinary_authority(day)
            )
            ordinary_takeover.connection_time(ordinary_window, self.now())
        self.driver.connect()
        self.prepare(day)
        self.retry_after = self.now() + timedelta(seconds=30 * attempt)

    def prepare(self, day):
        self.recovery_stage = "ACCOUNT_SNAPSHOT"
        snapshot = self.driver.snapshot()
        if (
            snapshot.account_id != self.settings.account_id
            or snapshot.trading_day != day
        ):
            raise ValueError("NATIVE_SESSION_IDENTITY_MISMATCH")
        self.day = day
        path = self.folder / "account.sqlite"
        if not path.is_file():
            raise ValueError("EXISTING_ACCOUNT_JOURNAL_REQUIRED")
        self.recovery_stage = "JOURNAL_INSPECTION"
        state = a.LocalStore.inspect(path)
        self.ledger_hash = digest(state)
        if state.account_id != snapshot.account_id or set(
            p.product for p in state.products
        ) != set(self.products):
            raise ValueError("CONTINUOUS_ACCOUNT_SCOPE_MISMATCH")
        self.recovery_stage = "ACCOUNT_BINDINGS"
        bindings = self.driver.bindings_for(state, self.market, self.now(), day)
        if self.settings.mode == "observe":
            self.recovery_stage = "OBSERVE_RECONCILIATION"
            rb, _ = project_readback(
                snapshot,
                bindings,
                self.driver.read_journal,
                state,
                snapshot.at + timedelta(seconds=30),
            )
            tx = a.apply(state, "observe:" + snapshot.source_id, rb)
            if not tx.state.readback_valid:
                raise ValueError("OBSERVATION_ACCOUNT_RECONCILIATION_REQUIRED")
            self.observed_state = state
            self.evidence.append(snapshot)
            self.observe_reconciliation = build_proof(
                state, snapshot, tx.state, self.run_id, self.now()
            )
        else:
            from .journal import Journal
            from .host import Host

            self.recovery_stage = "STORE_OPEN"
            if self.store is None:
                self.store = a.LocalStore(path)
            if self.journal is None:
                self.journal = Journal(
                    self.folder / "dispatch.sqlite", snapshot.account_id
                )
            # Full native account/ownership validation precedes settlement confirmation.
            self.recovery_stage = "MARKET_RECOVERY"
            proofs = self.market.recovery(state, self.now())
            self.recovery_stage = "ACCOUNT_REFRESH"
            snapshot = self.driver.snapshot()
            if (
                snapshot.account_id != self.settings.account_id
                or snapshot.trading_day != day
            ):
                raise ValueError("NATIVE_SESSION_IDENTITY_MISMATCH")
            self.recovery_stage = "OWNERSHIP_VALIDATION"
            verify_recovery_ownership(snapshot, bindings, self.journal, state)
            from .strategy_native import validate_strategy_events

            self.recovery_stage = "ADAPTER_PREPARATION"
            adapter = self.driver.adapter(
                self.store,
                self.journal,
                snapshot,
                self.now(),
                strategy_correlated_native=True,
                native_validator=lambda native: validate_strategy_events(
                    native, self.market.authority, self.journal, self.store.current()
                ),
            )
            adapter.account_takeover_pending = self.account_takeover_pending
            self.recovery_stage = "UNSENT_ORDER_RECOVERY"
            for order in self.store.current().orders:
                if order.status == "PROPOSED" and not self.journal.claimed(
                    order.order_id
                ):
                    adapter.abort_unsent(
                        order.order_id, "RESTART_VERIFIED_NEVER_CLAIMED", self.now()
                    )
            self.recovery_stage = "HOST_CONSTRUCTION"
            self.host = Host(
                self.store,
                self.journal,
                self.evidence,
                adapter,
                self.products,
                continuous=True,
                trade=self.settings.mode == "trade",
                run_id=self.run_id,
                deadline=None,
                account_takeover_pending=self.account_takeover_pending,
                takeover_clock=self.now,
                account_profile=getattr(self.settings, "account_profile", None),
            )
            self.recovery_stage = "ACCOUNT_RECONCILIATION"
            native, recovered = self.host.reconcile(
                self.driver.report, bindings, self.now(), proofs
            )
            if self.account_takeover_pending:
                self.recovery_stage = "TAKEOVER_COMPLETION"
                self.host.complete_takeover(native, recovered, self.now())
                self.account_takeover_pending = False
            if not self.store._needs_recovery:
                self.ledger_hash = digest(self.store.current())
        self.latest_source = (
            snapshot.source_id
        )  # Evidence is durable before publishing the binding.
        self.recovery_stage = "QUEUE_RECOVERY"
        self.market.activate(self.now())
        self.inbox.recover_queue(self.store)
        self.prepared = True
        self.recovery_stage = "READY"

    def cycle(self):
        # Keep an attempt's day through its cleanup/error handling, but do not
        # attribute a later disconnected cycle to that historical connection.
        if self.driver is None:
            self.target_day = None
        now = self.now()
        plan = self.market.plan(now)
        self.session_active = plan.active
        day = plan.trading_day.strftime("%Y%m%d") if plan.trading_day else None
        if day is None:
            self.status("CALENDAR_UNPROVEN")
            return
        closed_readback = bool(
            self.settings.mode == "observe"
            and not plan.active
            and getattr(self.market, "closed_observation_allowed", lambda _now: False)(
                now
            )
        )
        if closed_readback:
            # CLOSED plan.day refers to the next session. Until native evidence
            # has reached that day, retain the original preopen connection rule.
            # An ordinary broker rollover must not poison tomorrow's budget/block.
            latest = self.evidence.latest()
            closed_readback = bool(latest and latest.trading_day == day)
        if self.driver is not None and day != (
            self.day if self.prepared else self.target_day
        ):
            self.disconnect()
        if self.driver is None:
            if getattr(self, "deployment_connection_used", False) and day == "20261030":
                self.status("RECOVERY_BLOCKED")
                return
            if day is None or not (plan.connect_allowed or closed_readback):
                self.status("WAITING_SESSION")
                return
            exception_candidate = bool(
                getattr(self.settings, "deployment_connection_permit", None)
                and day == "20261030"
                and self.inbox.conn.execute(
                    "SELECT count FROM attempts WHERE day=?", (day,)
                ).fetchone()
                == (3,)
            )
            if (
                self.inbox.blocked(day) and not exception_candidate
            ) or now < self.retry_after:
                self.status("RECOVERY_BLOCKED")
                return
            self.connect(day)
        elif not self.prepared:
            self.prepare(day)
        state = self.store.current() if self.store is not None else self.observed_state
        after = {p.product: p.last_bar or state.activated_at for p in state.products}
        self.active_seen = self.active_seen or plan.active
        if self.settings.mode == "observe":
            signals = self.market.poll(self.now(), after) if self.active_seen else ()
            for signal in signals:
                self.inbox.enqueue(signal)
            for signal in self.inbox.pending():
                self.inbox.mark(signal.source_id, "OBSERVED")
            snapshot = self.driver.snapshot()
            if snapshot.trading_day != self.day:
                self.disconnect()
                return
            bindings = self.driver.bindings_for(
                state, self.market, self.now(), self.day
            )
            rb, _ = project_readback(
                snapshot,
                bindings,
                self.driver.read_journal,
                state,
                snapshot.at + timedelta(seconds=30),
            )
            reconciled = a.apply(state, "observe:" + snapshot.source_id, rb).state
            if not reconciled.readback_valid:
                raise ValueError("OBSERVATION_ACCOUNT_RECONCILIATION_REQUIRED")
            self.evidence.append(snapshot)
            self.observe_reconciliation = build_proof(
                state, snapshot, reconciled, self.run_id, self.now()
            )
            self.latest_source = snapshot.source_id
            # Serial round-robin validation; no 60 parallel broker request streams.
            if not closed_readback:
                self.driver.observe_next(
                    self.products, self.market, self.now(), self.day, self.issues
                )
            self.status(
                "OBSERVING_CLOSED" if closed_readback else "OBSERVING", connected=True
            )
            return
        bindings = self.driver.bindings_for(state, self.market, self.now(), self.day)
        recovering = self.host.needs_recovery or state.phase != "READY"
        proofs = (
            self.market.recovery(state, self.now())
            if recovering or state.blocked_products
            else ()
        )
        snapshot = self.driver.snapshot()
        if snapshot.trading_day != self.day:
            self.disconnect()
            return
        _, recovered = self.host.reconcile(
            self.driver.report, bindings, self.now(), proofs if recovering else ()
        )
        self.latest_source = snapshot.source_id
        self.host.adapter.expire_unacknowledged(self.now())
        if (
            recovered is None
            or not recovered.readback_valid
            or recovered.phase != "READY"
        ):
            self.inbox.recover_queue(self.store)
            self._audit_trade_inputs(force_defer=True)
            self.status("ACCOUNT_RECONCILIATION_REQUIRED", connected=True)
            return
        if recovering:
            self.inbox.recover_queue(self.store)
        elif recovered.blocked_products and proofs:
            rb, _ = project_readback(
                snapshot,
                bindings,
                self.journal,
                recovered,
                snapshot.at + timedelta(seconds=30),
            )
            self.store.execute(
                "product-recovery:" + snapshot.source_id,
                a.ProductRecoveryV1(
                    rb,
                    tuple(p for p in proofs if p.product in recovered.blocked_products),
                    tuple(recovered.blocked_products),
                ),
            )
        current = self.store.current()
        for product in self.products:
            try:
                authority = self.market.authority(product, plan.trading_day, self.now())
            except Exception:
                self.issues[product] = "AUTHORITATIVE_INPUT_UNPROVEN"
                continue
            owner = next(p.owner for p in current.products if p.product == product)
            if authority.owner != owner:
                self.store.execute(
                    "portfolio-owner:" + authority.source_id,
                    Owner(product, authority.owner, self.now(), authority.source_id),
                )
        # Native reconciliation and owner changes may advance the account clock.
        # Receive first-seen signals afterwards, retaining their genuine timestamp;
        # never rewrite observed_at just to fit a later account command.
        after = {
            p.product: p.last_bar or current.activated_at
            for p in self.store.current().products
        }
        signals = self.market.poll(self.now(), after) if self.active_seen else ()
        for signal in signals:
            self.inbox.enqueue(signal)
        self.inbox.deliver(self.store)
        if self.settings.mode == "trade":
            facts, bindings = self.driver.execution_for(
                self.store.current(),
                self.market,
                self.now(),
                self.day,
                self.issues,
                opening_allowed=True,
                refresh=self.refresh_before_book,
            )
        else:
            facts, bindings = self.driver.execution_for(
                self.store.current(), self.market, self.now(), self.day, self.issues
            )
        pending = self.host.adapter.drain()
        if self.host.adapter._faulted:
            raise ValueError("NATIVE_ADAPTER_REQUIRES_RECOVERY")
        current = self.store.current()
        if self.settings.mode == "trade" and (
            pending
            or not current.readback_valid
            or current.phase != "READY"
            or not current.readback.at <= self.now() < current.readback.valid_until
        ):
            self._audit_trade_inputs(force_defer=True)
            self.status("ACCOUNT_RECONCILIATION_REQUIRED", connected=True)
            return  # Slow inputs alone must not create a fake disconnection/recovery.
        outcomes = self.host.tick(facts, bindings, self.now())
        if any(
            o in {"SEND_OUTCOME_UNKNOWN", "NOT_ACCEPTED_RECONCILE_REQUIRED"}
            for o in outcomes
        ):
            raise ValueError("NATIVE_ORDER_OUTCOME_REQUIRES_RECOVERY")
        self._audit_trade_inputs()
        if not self.store._needs_recovery:
            self.ledger_hash = digest(self.store.current())
        self.status(
            "TRADING" if self.settings.mode == "trade" else "MANAGING_EXISTING_ONLY",
            connected=True,
        )

    def _audit_trade_inputs(self, *, force_defer=False):
        """Execution/account work wins; idle inputs are observation evidence only."""
        audit = getattr(self.driver, "audit_next", None)
        if self.settings.mode != "trade" or audit is None:
            return
        from ..htdy_account_execution.scheduling import execution_candidates

        # drain() replays journaled callbacks idempotently, without sending orders.
        pending = self.host.adapter.drain() if not force_defer else ()
        if self.host.adapter._faulted:
            raise ValueError("NATIVE_ADAPTER_REQUIRES_RECOVERY")
        current = self.store.current()
        now = self.now()
        obligations = bool(
            force_defer
            or pending
            or self.host.pending
            or self.host.needs_recovery
            or self.store._needs_recovery
            or current.phase != "READY"
            or not current.readback_valid
            or not current.readback.at <= now < current.readback.valid_until
            or any(not order.reconciled for order in current.orders)
        )
        idle = not obligations and not execution_candidates(
            current, opening_allowed=True
        )
        boundary = None
        if idle:
            try:
                boundary = self.market.next_audit_boundary(now)
            except Exception:
                boundary = None
        audit(
            self.products,
            self.market,
            self.day,
            idle=idle,
            obligations_pending=obligations,
            next_boundary=boundary,
        )
        if self.driver.transport_failed:
            raise ValueError("NATIVE_TRANSPORT_FAILED")
        if getattr(self.driver.gateway, "failed", False):
            raise ValueError("NATIVE_GATEWAY_FAILED")

    def refresh_before_book(self):
        """Same-connection complete readback after rates, before the final book."""
        snapshot = self.driver.snapshot()
        if snapshot.trading_day != self.day:
            self.disconnect()
            raise ValueError("NATIVE_SESSION_IDENTITY_MISMATCH")
        bindings = self.driver.bindings_for(
            self.store.current(), self.market, self.now(), self.day
        )
        _, state = self.host.reconcile(self.driver.report, bindings, self.now())
        self.latest_source = snapshot.source_id
        if state is None or not state.readback_valid or state.phase != "READY":
            return None
        # New messages received during the blocking read keep their genuine
        # receipt time, after the account clock has advanced.
        after = {p.product: p.last_bar or state.activated_at for p in state.products}
        for signal in self.market.poll(self.now(), after) if self.active_seen else ():
            self.inbox.enqueue(signal)
        self.inbox.deliver(self.store)
        current = self.store.current()
        return (
            current
            if current.readback.at <= self.now() < current.readback.valid_until
            else None
        )

    def run(self, *, max_cycles=None):
        if not self.settings.enabled:
            return "DISABLED"
        with account_lock(self.settings) as folder:
            self.folder, self.latest_source = folder, None
            self.monitor = MonitorPublisher(
                folder.parent, self.settings.account_id, self.run_id
            )
            self.inbox = SignalInbox(
                folder / "signals.sqlite", self.settings.account_id, self.products
            )
            self.evidence = Evidence(
                folder / "native-evidence.sqlite", self.settings.account_id
            )
            self.market.activate(self.now())
            count = 0
            try:
                from . import deployment_connection as permit

                if getattr(self.settings, "ordinary_takeover_permit", None):
                    from . import ordinary_takeover

                    startup_plan = self.market.plan(self.now())
                    startup_day = (
                        startup_plan.trading_day.strftime("%Y%m%d")
                        if startup_plan.trading_day
                        else None
                    )
                    if self._ordinary_permit_required(startup_day):
                        ordinary_takeover.activate(
                            self.settings,
                            self.inbox,
                            self.run_id,
                            self.now(),
                            clock=self.now,
                        )
                if getattr(self.settings, "deployment_connection_permit", None):
                    startup_plan = self.market.plan(self.now())
                    startup_day = (
                        startup_plan.trading_day.strftime("%Y%m%d")
                        if startup_plan.trading_day
                        else None
                    )
                    if (
                        startup_day == permit.DAY
                        and permit.attempts(self.inbox, permit.DAY) >= 3
                    ):
                        permit.activate(
                            self.settings,
                            self.inbox,
                            self.run_id,
                            self.now(),
                            clock=self.now,
                        )
                while not self.stopped() and (max_cycles is None or count < max_cycles):
                    try:
                        self.cycle()
                    except Exception as exc:
                        if (
                            type(exc) is ValueError
                            and str(exc) == "NATIVE_SNAPSHOT_CHANGED"
                        ):
                            self.status("READBACK_NOT_STABLE", connected=True)
                            count += 1
                            self.sleep(1)
                            continue
                        transport_failure = (
                            type(exc) is ValueError
                            and str(exc)
                            in {
                                "FIRST_LOGIN_NOT_VERIFIED",
                                "NATIVE_GATEWAY_FAILED",
                                "NATIVE_STABLE_SNAPSHOT_REQUIRED",
                                "NATIVE_FACT_QUERY_FAILED",
                                "NATIVE_TRANSPORT_FAILED",
                            }
                            and self.driver is not None
                            and self.driver.transport_failed
                        )
                        code = (
                            str(exc)
                            if isinstance(exc, ValueError)
                            and str(exc)
                            in {
                                "CONNECTION_BUDGET_EXHAUSTED",
                                "EXISTING_ACCOUNT_JOURNAL_REQUIRED",
                                "NATIVE_SESSION_IDENTITY_MISMATCH",
                                "CONTINUOUS_ACCOUNT_SCOPE_MISMATCH",
                                "OBSERVATION_ACCOUNT_RECONCILIATION_REQUIRED",
                                "MANAGEMENT_NATIVE_RECOVERY_REQUIRED",
                                "NATIVE_ORDER_OUTCOME_REQUIRES_RECOVERY",
                                "NATIVE_ADAPTER_REQUIRES_RECOVERY",
                                "CREDENTIAL_UNAVAILABLE",
                                "CREDENTIAL_CORRUPT",
                                "CREDENTIAL_IDENTITY_MISMATCH",
                            }
                            else "CONTINUOUS_RECOVERY_REQUIRED"
                        )
                        self.status(code)
                        # Only transport failures may reconnect. Unknown account/commit/dispatch stops this day.
                        if not transport_failure:
                            # The failed attempt owns this block even when the
                            # calendar has advanced while native calls waited.
                            self.blocked_day = self.target_day
                            if self.blocked_day is None:
                                plan = self.market.plan(self.now())
                                self.blocked_day = (
                                    plan.trading_day.strftime("%Y%m%d")
                                    if plan.trading_day else None
                                )
                            if self.blocked_day:
                                self.inbox.block(self.blocked_day, code)
                        try:
                            diagnostic = (
                                self.driver.failure_diagnostics()
                                if self.driver is not None
                                and hasattr(self.driver, "failure_diagnostics")
                                else dict(stage="DRIVER_UNAVAILABLE")
                            )
                            diagnostic["dispatch"] = getattr(
                                self.host, "last_dispatch_diagnostic", None
                            )
                            diagnostic["recovery_stage"] = self.recovery_stage
                            diagnostic["recovery_error_code"] = (
                                str(exc) if isinstance(exc, ValueError) and str(exc) in _RECOVERY_ERRORS
                                else "RECOVERY_ERROR_UNCLASSIFIED"
                            )
                            retain_failure(
                                self.folder,
                                self.run_id,
                                count,
                                code,
                                self.now(),
                                diagnostic,
                            )
                        except Exception:
                            # An evidence failure cannot silently turn into a fresh login.
                            if self.target_day:
                                self.inbox.block(
                                    self.target_day, "CONTINUOUS_DIAGNOSTIC_UNAVAILABLE"
                                )
                        self.disconnect()
                        self.retry_after = self.now() + timedelta(seconds=60)
                    count += 1
                    if not self.stopped() and (
                        max_cycles is None or count < max_cycles
                    ):
                        self.sleep(1)
            finally:
                try:
                    self.disconnect()
                    self.status("STOPPED")
                    self.monitor.publish(
                        "STOPPED",
                        self.now(),
                        connection="RELEASED",
                        mode=self.settings.mode,
                        opening_enabled=False,
                        host_status="STOPPED",
                        account_takeover_pending=self.account_takeover_pending,
                        native_source_id=self.latest_source,
                        ledger_hash=self.ledger_hash,
                    )
                finally:
                    self.inbox.close()
                    self.evidence.close()
                    self.market.close()
        return "STOPPED"
