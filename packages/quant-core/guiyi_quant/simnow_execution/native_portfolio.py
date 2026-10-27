"""Serial native transport composition; SDK types are supplied by the pinned runner."""

from datetime import timedelta
from dataclasses import replace
from pathlib import Path
import sqlite3
import tempfile

from ..htdy_account_execution.codec import digest
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
    def __init__(self, settings, folder, module, connector, *, now):
        self.settings, self.folder, self.module, self.connector = (
            settings,
            folder,
            module,
            connector,
        )
        self.now = now
        self.gateway = self.flow = self.read_journal = None
        self.report = None
        self.cache = {}
        self.last_facts = {}
        self.cursor = 0

    def connect(self):
        credentials = CredentialStore().load(self.settings.account_id)
        self.gateway = self.module.Gateway(credentials.user, credentials.password)
        del credentials
        self.flow = tempfile.TemporaryDirectory(prefix="guiyi-continuous-flow-")
        self.connector(self.gateway, self.module.tdapi, self.flow.name)
        self.read_journal = ReadJournal(
            self.folder / "dispatch.sqlite", self.settings.account_id
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
        from datetime import datetime

        bound, metadata = self.binding(product, contract, market, self.now(), day)
        mar = self.gateway.query("margin", bound.native, exchange=bound.exchange)
        com = self.gateway.query("commission", bound.native, exchange=bound.exchange)
        if len(mar) != 1 or len(com) != 1:
            raise ValueError("NATIVE_RATE_FACTS_INCOMPLETE")
        # Query book last, so rate queries cannot silently consume its three-second TTL.
        rows = self.gateway.query("book", bound.native)
        received = self.now()
        quote = quote_from_native_batch(bound, rows, day, received)
        auth = market.authority(
            product, datetime.strptime(day, "%Y%m%d").date(), received, bound.canonical
        )
        fact = execution_input(
            bound, metadata, mar[0], com[0], quote, auth.session, self.now()
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

    def execution_for(self, state, market, now, day, issues):
        # No OPEN capability this phase: query only existing obligations, one live order globally.
        contracts = {(o.product, o.contract) for o in state.orders if not o.reconciled}
        if not contracts:
            closing = {p.product for p in state.products if p.must_close or p.rolling}
            closing |= {
                held.product
                for held in state.positions
                if any(
                    p.product == held.product and p.desired != held.quantity
                    for p in state.products
                )
            }
            contracts = {
                (p.product, p.contract) for p in state.positions if p.product in closing
            }
        # Serialize execution, including metadata/book acquisition. A quote obtained
        # for one contract must not age behind 59 other broker queries.
        contracts = sorted(contracts)
        bindings, facts = [], []
        for product, contract in sorted(contracts):
            try:
                binding, fact = self.facts(product, contract, market, day)
            except Exception:
                if self.transport_failed:
                    raise ValueError("NATIVE_TRANSPORT_FAILED") from None
                issues[product] = "EXECUTION_INPUT_UNPROVEN"
                # Cancels need current Session and proven instrument, but no new price.
                cached = self.last_facts.get(contract)
                if (
                    cached is not None
                    and self.now() < cached.instrument.valid_until
                    and any(
                        o.contract == contract and not o.reconciled
                        for o in state.orders
                    )
                ):
                    from datetime import datetime

                    auth = market.authority(
                        product,
                        datetime.strptime(day, "%Y%m%d").date(),
                        self.now(),
                        contract,
                    )
                    bindings.append(
                        self.binding(product, contract, market, self.now(), day)[0]
                    )
                    facts.append(replace(cached, session=auth.session, quote=None))
                    break
                continue
            issues.pop(product, None)
            bindings.append(binding)
            facts.append(fact)
            break
        return tuple(facts), tuple(bindings)

    def adapter(self, store, journal, snapshot, now):
        from datetime import datetime, time
        from zoneinfo import ZoneInfo

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
        adapter = Adapter(
            store,
            journal,
            self.module.tdapi,
            self.gateway.api,
            self.gateway.user,
            session,
        )
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
