"""Serial native transport composition; SDK types are supplied by the pinned runner."""

from datetime import timedelta
from pathlib import Path
import sqlite3
import re
import tempfile

from ..htdy_account_execution.codec import digest
from ..htdy_account_execution.scheduling import (
    execution_candidates,
    desired_action,
    executable_price,
)
from . import Adapter, Journal, Session
from .credentials import CredentialStore
from .facts import (
    bind_contract,
    native_product_id,
    quote_from_native_batch,
    execution_input,
)
from .inventory import read_snapshot


class ReadJournal(Journal):
    """Reuse dispatch identity readers with a genuinely read-only SQLite handle."""

    def __init__(self, path, account):
        path = Path(path)
        if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
            raise ValueError("PRIVATE_DISPATCH_JOURNAL_REQUIRED")
        with path.open("rb") as stream:
            header = stream.read(20)
        if header[:16] != b"SQLite format 3\x00" or header[18:20] != b"\x01\x01":
            raise ValueError("READ_ONLY_JOURNAL_MODE_UNSUPPORTED")
        self.conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        self.conn.execute("PRAGMA query_only=ON")
        if self.conn.execute("SELECT account,schema FROM identity").fetchall() != [
            (account, "simnow_dispatch_v1")
        ]:
            self.conn.close()
            raise ValueError("DISPATCH_IDENTITY_MISMATCH")


class NativePortfolio:
    def __init__(
        self, settings, folder, module, connector, *, now, initial_funds_timeout=45
    ):
        if (
            type(initial_funds_timeout) is not int
            or not 15 <= initial_funds_timeout <= 45
        ):
            raise ValueError("INITIAL_FUNDS_TIMEOUT_BOUND_INVALID")
        self.settings, self.folder, self.module, self.connector = (
            settings,
            folder,
            module,
            connector,
        )
        self.now = now
        self.initial_funds_timeout = initial_funds_timeout
        self.gateway = self.flow = self.read_journal = None
        self.report = None
        self.cache = {}
        self.last_facts = {}
        self.cursor = 0
        self.stage = "NOT_CONNECTED"

    def connect(self):
        self.stage = "CREDENTIAL_LOAD"
        credentials = CredentialStore().load(self.settings.account_id)
        if self.initial_funds_timeout == 15:
            self.gateway = self.module.Gateway(credentials.user, credentials.password)
        else:
            self.gateway = self.module.Gateway(
                credentials.user,
                credentials.password,
                initial_funds_timeout=self.initial_funds_timeout,
            )
        del credentials
        self.flow = tempfile.TemporaryDirectory(prefix="guiyi-continuous-flow-")
        self.stage = "NATIVE_LOGIN"
        self.connector(self.gateway, self.module.tdapi, self.flow.name)
        self.stage = "DISPATCH_IDENTITY_READ"
        self.read_journal = ReadJournal(
            self.folder / "dispatch.sqlite", self.settings.account_id
        )

    def failure_diagnostics(self):
        return dict(
            stage=self.stage,
            inventory=self.gateway.inventory_diagnostics()
            if self.gateway is not None
            else None,
        )

    @property
    def transport_failed(self):
        if self.gateway is None:
            return False
        status = self.gateway.result.get("status")
        if not self.gateway.failed:
            return bool(
                status in {"WAITING_CONNECTION", "WAITING_AUTH", "WAITING_LOGIN"}
                and not self.gateway.login_done.is_set()
            )
        if status in {"FRONT_DISCONNECTED", "QUERY_TIMEOUT", "LOGIN_TIMEOUT"}:
            return True
        return bool(
            status == "NATIVE_FACT_QUERY_FAILED"
            and self.gateway.extra is not None
            and not self.gateway.extra.get("callback_error")
            and self.gateway.query_diagnostics
            and self.gateway.query_diagnostics[-1].get("timed_out") is True
        )

    def snapshot(self):
        self.stage = "ACCOUNT_SNAPSHOT"
        self.gateway.query_diagnostics.clear()
        try:
            self.report = self.gateway.snapshot()
        except ValueError:
            if (
                not self.gateway.failed
                and self.gateway.result.get("status") == "SNAPSHOT_CHANGED"
            ):
                raise ValueError("NATIVE_SNAPSHOT_CHANGED") from None
            raise
        return read_snapshot(self.report, now=self.now())

    def binding(self, product, contract, market, now, day):
        from datetime import datetime

        authority = market.authority(
            product, datetime.strptime(day, "%Y%m%d").date(), now, contract
        )
        key = (day, authority.contract)
        cached = self.cache.get(key)
        if cached is None or now >= cached[0].valid_until:
            rows = self.gateway.query(
                "instrument",
                exchange=authority.exchange,
                product=native_product_id(product, authority.exchange),
            )
            binding, metadata = bind_contract(
                authority.contract,
                authority.exchange,
                rows,
                self.now(),
                self.now() + timedelta(minutes=5),
                day,
            )
            cached = binding, metadata
            self.cache[key] = cached
        return cached

    def bindings_for(self, state, market, now, day):
        contracts = {(p.product, p.contract) for p in state.positions}
        contracts |= {(o.product, o.contract) for o in state.orders if not o.reconciled}
        return tuple(
            self.binding(p, c, market, self.now(), day)[0] for p, c in sorted(contracts)
        )

    def facts(self, product, contract, market, day):
        return self.finish_facts(
            self.prepare_facts(product, contract, market, day), market, day
        )

    def prepare_facts(self, product, contract, market, day):
        bound, metadata = self.binding(product, contract, market, self.now(), day)
        mar = self.gateway.query("margin", bound.native, exchange=bound.exchange)
        com = self.gateway.query("commission", bound.native, exchange=bound.exchange)
        if len(mar) != 1 or len(com) != 1:
            raise ValueError("NATIVE_RATE_FACTS_INCOMPLETE")
        return bound, metadata, mar[0], com[0]

    def finish_facts(self, prepared, market, day, *, opening=False):
        from datetime import datetime

        bound, metadata, margin, commission = prepared
        product = re.match(r"[A-Z]+", bound.canonical)[0]
        # Query book last, so rate queries cannot silently consume its three-second TTL.
        rows = self.gateway.query("book", bound.native)
        received = self.now()
        quote = quote_from_native_batch(bound, rows, day, received)
        auth = market.authority(
            product, datetime.strptime(day, "%Y%m%d").date(), received, bound.canonical
        )
        if opening and auth.owner != bound.canonical:
            raise ValueError("AUTHORITATIVE_OWNER_CHANGED")
        fact = execution_input(
            bound, metadata, margin, commission, quote, auth.session, self.now()
        )
        self.last_facts[bound.canonical] = fact
        return bound, fact

    def observe_next(self, products, market, now, day, issues):
        product = products[self.cursor % len(products)]
        self.cursor += 1
        try:
            self.facts(product, None, market, day)
        except Exception:
            if self.transport_failed:
                raise ValueError("NATIVE_TRANSPORT_FAILED") from None
            issues[product] = "EXECUTION_INPUT_UNPROVEN"
        else:
            issues.pop(product, None)

    def execution_for(
        self, state, market, now, day, issues, *, opening_allowed=False, refresh=None
    ):
        if (
            type(opening_allowed) is not bool
            or opening_allowed
            and not callable(refresh)
        ):
            raise ValueError("TRADE_ACCOUNT_REFRESH_REQUIRED")
        candidates = execution_candidates(state, opening_allowed=opening_allowed)
        # Serialize execution, including metadata/book acquisition. A quote obtained
        # for one contract must not age behind 59 other broker queries.
        bindings, facts = [], []
        failed = []
        for candidate in candidates:
            product, contract = candidate.product, candidate.contract
            try:
                if opening_allowed:
                    prepared = self.prepare_facts(product, contract, market, day)
                else:
                    binding, fact = self.facts(product, contract, market, day)
            except Exception:
                if self.transport_failed:
                    raise ValueError("NATIVE_TRANSPORT_FAILED") from None
                issues[product] = "EXECUTION_INPUT_UNPROVEN"
                if any(
                    o.contract == contract and not o.reconciled for o in state.orders
                ):
                    cancel_facts, cancel_bindings = self.cancel_facts(
                        state, market, day, contract
                    )
                    if cancel_facts:
                        return cancel_facts, cancel_bindings
                failed.append(candidate)
                continue
            if opening_allowed:
                # Refresh runs outside per-product error handling. Unknown account
                # outcomes must stop the host, never masquerade as a missing quote.
                current = refresh()
                if current is None:
                    return (), ()
                current_candidates = tuple(
                    c
                    for c in execution_candidates(current, opening_allowed=True)
                    if c not in failed
                )
                if not current_candidates or current_candidates[0] != candidate:
                    return (
                        (),
                        (),
                    )  # Target/order changed while querying; replan next cycle.
                try:
                    binding, fact = self.finish_facts(
                        prepared, market, day, opening=candidate.offset == "OPEN"
                    )
                except Exception:
                    if self.transport_failed:
                        raise ValueError("NATIVE_TRANSPORT_FAILED") from None
                    issues[product] = "EXECUTION_INPUT_UNPROVEN"
                    failed.append(candidate)
                    # Pending orders may still need an unpriced cancellation.
                    if any(not o.reconciled for o in current.orders):
                        return self.cancel_facts(current, market, day, contract)
                    continue
            if opening_allowed and not any(not o.reconciled for o in current.orders):
                target = next(p for p in current.products if p.product == product)
                action = desired_action(current, target)
                cutoff = (
                    candidate.offset == "OPEN"
                    and fact.session.at <= self.now() < fact.session.valid_until
                    and self.now()
                    >= fact.session.final_close_at - timedelta(seconds=60)
                )
                if not cutoff and (
                    action is None
                    or executable_price(fact, action[2], self.now()) is None
                ):
                    issues[product] = "EXECUTION_INPUT_TEMPORARILY_UNAVAILABLE"
                    failed.append(candidate)
                    continue
            issues.pop(product, None)
            bindings.append(binding)
            facts.append(fact)
            break
        return tuple(facts), tuple(bindings)

    def cancel_facts(self, state, market, day, contract):
        from datetime import datetime

        # A CANCEL needs original identity and a current binding/Session, not
        # refreshed rates or a price. Recover the instrument from the immutable
        # Tick that created this order; expired historical rates are never used
        # for a replacement submission (quote is explicitly absent).
        order = next(
            (o for o in state.orders if o.contract == contract and not o.reconciled),
            None,
        )
        if order is None:
            return (), ()
        from ..htdy_account_execution import ExecutionInput

        instrument = next(
            (
                f.instrument
                for audit in reversed(getattr(state, "audit", ()))
                for f in getattr(audit.command, "inputs", ())
                if type(f) is ExecutionInput
                and f.instrument.contract == contract
                and f.instrument.source_id == order.instrument_source
            ),
            None,
        )
        if instrument is None:
            return (), ()
        auth = market.authority(
            instrument.product,
            datetime.strptime(day, "%Y%m%d").date(),
            self.now(),
            contract,
        )
        binding = self.binding(instrument.product, contract, market, self.now(), day)[0]
        return (ExecutionInput(instrument, auth.session, None),), (binding,)

    def adapter(
        self,
        store,
        journal,
        snapshot,
        now,
        *,
        close_only=False,
        correlated_native=False,
        strategy_correlated_native=False,
        native_validator=None,
    ):
        from datetime import datetime, time
        from zoneinfo import ZoneInfo

        if (
            type(close_only) is not bool
            or type(correlated_native) is not bool
            or type(strategy_correlated_native) is not bool
            or correlated_native
            and (not close_only or strategy_correlated_native)
            or strategy_correlated_native
            and not callable(native_validator)
        ):
            raise ValueError("NATIVE_CAPABILITY_INVALID")

        settlement = self.gateway.query("settlement")
        if len(settlement) != 1 or settlement[0]["ConfirmDate"] != snapshot.trading_day:
            settlement = self.gateway.query("confirm")
            if (
                len(settlement) != 1
                or settlement[0]["ConfirmDate"] != snapshot.trading_day
            ):
                raise ValueError("NATIVE_SETTLEMENT_CONFIRMATION_REQUIRED")
        session = Session(
            snapshot.account_id,
            "SIMNOW_FIRST",
            self.gateway.front,
            snapshot.trading_day,
            **self.gateway.native_session,
            login_source_id="native-login:"
            + digest(
                (snapshot.account_id, snapshot.trading_day, self.gateway.native_session)
            ),
            settlement_source_id="native-settlement:" + digest(settlement),
            at=self.now(),
            valid_until=datetime.combine(
                datetime.strptime(snapshot.trading_day, "%Y%m%d").date()
                + timedelta(days=1),
                time.min,
                tzinfo=ZoneInfo("Asia/Shanghai"),
            ),
        )
        capabilities = (
            dict(close_only=close_only, correlated_native=correlated_native)
            if close_only or correlated_native
            else {}
        )
        if strategy_correlated_native:
            capabilities.update(
                strategy_correlated_native=True, native_validator=native_validator
            )
        adapter = Adapter(
            store,
            journal,
            self.module.tdapi,
            self.gateway.api,
            self.gateway.user,
            session,
            **capabilities,
        )
        if correlated_native or strategy_correlated_native:
            adapter.correlate_snapshot(snapshot)
        self.gateway.attach(adapter, snapshot)
        return adapter

    def close(self):
        try:
            if self.gateway is not None and self.gateway.api is not None:
                self.gateway.api.RegisterSpi(None)
                self.gateway.api.Release()
        finally:
            if self.gateway is not None:
                self.gateway.user = self.gateway.password = ""
            if self.read_journal is not None:
                self.read_journal.close()
                self.read_journal = None
            if self.flow is not None:
                self.flow.cleanup()
                self.flow = None
