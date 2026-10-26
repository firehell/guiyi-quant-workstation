"""Normal Market-process historical preparation; no Reference/provider coupling."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import re
from pathlib import Path
from threading import Event, Thread

from app.market_data.contract_preparation import (
    ContractPreparation, FREQUENCIES, PreparationDemand, PreparationPlan, PreparationError, _digest, _safe_code, enqueue_request,
)
from app.market_data.market_phase import MarketPhase


def contract_preparation_state_path():
    # Stable across approved release worktree switches; never rooted in checkout.
    return Path.home() / "Library/Application Support/GuiyiQuant/market-contract-preparation.json"


def build_contract_preparation_requester(*, state_path=None):
    """Safe consumer rendezvous, deliberately constructing no provider or manager."""
    path = Path(state_path) if state_path is not None else contract_preparation_state_path()
    return lambda product, contract, trading_day, frequencies: enqueue_request(
        path, product, contract, trading_day, frequencies,
    )


def discover_demands(*, now, products, resolver, scopes, dominant, contract_fact, completed_day):
    """Current/near Session plus its closed observation owner; no guessed rank."""
    demands = []
    for product in products:
        if product not in scopes:
            continue
        days = set()
        closed_now = False
        for instant in (now, now + timedelta(minutes=30)):
            phase = resolver.resolve(product, instant)
            if instant == now:
                closed_now = phase.phase is MarketPhase.CLOSED
            if phase.phase is MarketPhase.UNKNOWN:
                raise ValueError("CONTRACT_PREPARATION_AUTHORITY_UNAVAILABLE")
            if phase.phase in {MarketPhase.TRADING, MarketPhase.BREAK}:
                if phase.trading_day is None:
                    raise ValueError("CONTRACT_PREPARATION_AUTHORITY_UNAVAILABLE")
                days.add(phase.trading_day)
        cutoff = None
        if closed_now:
            # CLOSED.trading_day is a civil/display fact. Recovery after a night
            # close uses only the existing resolver's latest started Session.
            owner = resolver.completed_observation_trading_day(product, now)
            if owner is None:
                if not days:
                    raise ValueError("CONTRACT_PREPARATION_AUTHORITY_UNAVAILABLE")
            else:
                cutoff = completed_day(product)
                if type(cutoff) is not date or cutoff > owner:
                    raise ValueError("CONTRACT_PREPARATION_AUTHORITY_UNAVAILABLE")
                if cutoff < owner:
                    days.add(owner)
                # cutoff == owner is a completed close, not a next-day demand.
        for day in sorted(days):
            if cutoff is None:
                cutoff = completed_day(product)
            contract = dominant(product, day)
            fact = contract_fact(product, contract)
            frequencies, fingerprint = scopes[product]
            demands.append(PreparationDemand(
                product, contract, day, fact.listed_date, fact.expired_date,
                cutoff, frequencies, fingerprint,
            ))
    return tuple(demands)


def enabled_consumer_scopes(session, products):
    """Read existing enabled scopes; no new rule, scope, or strategy semantics."""
    from sqlalchemy import select
    from app.alerts.models import AlertRule
    from app.alerts.registry import get_alert_rule_definition
    from app.reference_trading.models import ReferenceStream
    facts = {product: [] for product in products}
    frequencies = {product: set() for product in products}
    streams = session.scalars(select(ReferenceStream).where(
        ReferenceStream.enabled.is_(True), ReferenceStream.recording_mode == "forward_observation",
        ReferenceStream.product.in_(products),
    )).all()
    for stream in streams:
        if stream.frequency not in FREQUENCIES:
            raise ValueError("CONTRACT_PREPARATION_SCOPE_INVALID")
        frequencies[stream.product].add(stream.frequency)
        facts[stream.product].append(("reference", stream.stream_id, stream.frequency,
                                      stream.activation_generation, stream.identity_hash))
    rules = session.scalars(select(AlertRule).where(AlertRule.enabled.is_(True))).all()
    for rule in rules:
        definition = get_alert_rule_definition(rule.rule_code)
        stored = rule.scope_product_frequencies
        if not isinstance(stored, dict):
            raise ValueError("CONTRACT_PREPARATION_SCOPE_INVALID")
        for product, selected in stored.items():
            if (product not in frequencies or not isinstance(selected, list) or not selected
                    or any(value not in definition.input_frequencies for value in selected)):
                raise ValueError("CONTRACT_PREPARATION_SCOPE_INVALID")
            frequencies[product].update(selected)
            facts[product].append(("alert", rule.rule_code, sorted(selected)))
    return {product: (tuple(freq for freq in FREQUENCIES if freq in selected), _digest(sorted(facts[product])))
            for product, selected in frequencies.items() if selected}


def build_contract_preparation(session_factory, *, canonical_root, products, state_path=None, manager_factory=None, clock=None):
    """Native plan/apply composition, using independent sessions for MDS readback."""
    from app.market_data.catalog import MarketCatalog
    from app.market_data.composition import build_historical_data_manager, build_database_coverage_source
    from app.market_data.market_data_service import MarketDataService
    from app.market_data.storage import CanonicalMonthlyStore
    from app.market_data.historical_data_manager import ContractWarmupRequest
    from app.market_data.market_phase import MarketPhaseResolver
    from app.market_data.domain import BarFrequency, ContractTradingDayQuery
    from app.market_data.domain import RQDATA_INTRADAY_HISTORY_START
    actual_clock = clock or (lambda: datetime.now(UTC))
    manager_factory = manager_factory or build_historical_data_manager
    products = tuple(products)
    root = Path(canonical_root).resolve()
    path = Path(state_path) if state_path is not None else contract_preparation_state_path()
    # Database identity remains private: only its hash is persisted.
    with session_factory() as session:
        binding_id = _digest({"catalog": session.get_bind().url.render_as_string(hide_password=True),
                              "canonical_root": str(root), "products": sorted(products)})

    def read_service(session):
        return MarketDataService(MarketCatalog(session, root), CanonicalMonthlyStore(root))

    def admitted(session, now, selected_products):
        catalog = MarketCatalog(session, root)
        coverage = build_database_coverage_source(session)
        data = read_service(session)
        return discover_demands(
            now=now, products=selected_products, resolver=MarketPhaseResolver(session),
            scopes=enabled_consumer_scopes(session, products),
            dominant=lambda product, day: data.dominant_segment_for_day(product, day).contract,
            contract_fact=catalog.contract_fact,
            completed_day=lambda product: coverage.latest_complete_day_with_refresh_at((product,), now=now)[0],
        )

    waiting_authority = {}

    def discover(now):
        demands, waiting = [], {}
        for product in products:
            # Normal discovery isolates independent operational products. A
            # missing published rank1/Session/contract fact grants no attempt and
            # cannot prevent another product's proved identity from preparing.
            try:
                with session_factory() as session:
                    demands.extend(admitted(session, now, (product,)))
            except Exception as error:
                code = _safe_code(error)
                waiting[product] = {"product": product, "status": "WAITING_AUTHORITY",
                                    "reason": code if code != "CONTRACT_PREPARATION_FAILED"
                                    else "CONTRACT_PREPARATION_AUTHORITY_UNAVAILABLE"}
        waiting_authority.clear()
        waiting_authority.update(waiting)
        return tuple(demands)

    def native_request(demand, frequency, *, apply=False, plan_sha256=None):
        return ContractWarmupRequest(demand.product, demand.contract, demand.through,
                                     frequency=frequency, apply=apply, expected_plan_sha256=plan_sha256)

    def plan(demand, frequency, check):
        with session_factory() as session:
            manager = manager_factory(session, data_root=root)
            frozen = manager.contract_warmup(native_request(demand, frequency), check_budget=check).plan
            if (frozen.listed_date != demand.listed_date or frozen.expired_date != demand.expired_date
                    or frozen.requested_through != demand.through):
                raise ValueError("CONTRACT_PREPARATION_IDENTITY_DRIFT")
            return PreparationPlan(frozen.plan_sha256, frozen.provider_request_count, frozen.expected_bar_count)

    def apply(demand, frequency, frozen, reserve, check):
        with session_factory() as session:
            manager = manager_factory(session, data_root=root)
            def before_apply():
                # One fresh read-only authority transaction under the native
                # global lease. Queued work cannot reuse an earlier Session/day,
                # lifecycle, rank1, scope or completed-cutoff admission.
                from app.db.readonly import readonly_transaction
                with session_factory() as authority_session, readonly_transaction(authority_session, timeout_seconds=20):
                    current = admitted(authority_session, actual_clock(), (demand.product,))
                    if demand not in current:
                        raise PreparationError("CONTRACT_PREPARATION_AUTHORITY_DRIFT")
                reserve()
            receipt = manager.contract_warmup(
                native_request(demand, frequency, apply=True, plan_sha256=frozen.plan_sha256),
                before_apply=before_apply, check_budget=check,
            )
            reasons = {item.get("reason_code") for item in receipt.failures}
            if reasons == {"maintenance_locked"}:
                return {"status": "busy"}
            reason = next(iter(reasons)) if len(reasons) == 1 else None
            return {"status": receipt.status, "applied": receipt.applied, "reason": reason}

    def readback(demand, frequency):
        # Fresh transaction, fresh MDS/store; no stale ORM/cache proof from apply.
        with session_factory() as session:
            manager = manager_factory(session, data_root=root)
            frozen = manager.contract_warmup(native_request(demand, frequency)).plan
            if frozen.target_windows:
                return False
            data = read_service(session)
            data.query_contract_trading_days(ContractTradingDayQuery(
                demand.product, demand.contract, BarFrequency(frequency),
                max(demand.listed_date, RQDATA_INTRADAY_HISTORY_START)
                if frequency in {"1m", "5m", "15m", "30m", "60m"} else demand.listed_date, demand.through,
            ))
            return True

    preparation = ContractPreparation(state_path=path, binding_id=binding_id,
                                      discover=discover, plan=plan, apply=apply, readback=readback)
    preparation.authority_waiting = lambda: tuple(dict(waiting_authority[product]) for product in sorted(waiting_authority))
    return preparation


class ContractPreparationWorker:
    """One background thread in Market process, separate from quotes/Reference."""
    def __init__(self, preparation, *, interval=60, clock=None):
        self.preparation = preparation
        self.interval = interval
        self.clock = clock or (lambda: datetime.now(UTC))
        self._stop = Event()
        self._thread = None
        self.error = None
        self._summary = {"error": None, "counts": {}, "active": [], "active_truncated": False, "budgets": {},
                         "authority_waiting": [], "authority_waiting_truncated": False}
        if hasattr(preparation, "on_write"):
            preparation.on_write = self._cache_state
        self._original_apply = preparation.apply if hasattr(preparation, "apply") else None
        if self._original_apply is not None:
            def guarded_apply(demand, frequency, frozen, reserve, check):
                def boundary():
                    if self._stop.is_set():
                        raise PreparationError("CONTRACT_PREPARATION_SHUTDOWN")
                    check()
                return self._original_apply(demand, frequency, frozen, reserve, boundary)
            preparation.apply = guarded_apply

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(target=self._run, name="market-contract-preparation", daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            try:
                self.error = self.preparation.tick(self.clock())
            except Exception:
                self.error = "CONTRACT_PREPARATION_FAILED"
            try:
                self._cache_state(self.preparation.snapshot())
            except Exception:
                self._summary = {"error": "CONTRACT_PREPARATION_STATE_INVALID", "counts": {},
                                 "active": [], "active_truncated": False, "budgets": {},
                                 "authority_waiting": [], "authority_waiting_truncated": False}
            self._stop.wait(self.interval)

    def stop(self, *, timeout=5):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            if self._thread.is_alive():
                raise RuntimeError("CONTRACT_PREPARATION_DRAIN_PENDING")

    def _cache_state(self, state):
        """Background-only in-memory summary; durable publication calls this per unit."""
        counts, active = {}, []
        for request in state["requests"].values():
            identity = request.get("identity", {})
            for frequency, unit in request["units"].items():
                status = unit["status"]
                counts[status] = counts.get(status, 0) + 1
                if status == "READY":
                    continue
                reason = unit.get("reason")
                if reason is not None and (not isinstance(reason, str) or not re.fullmatch(r"[A-Z_]{1,100}", reason)):
                    reason = "CONTRACT_PREPARATION_READBACK_REQUIRED"
                active.append({"product": identity["product"], "contract": identity["contract"],
                               "trading_day": identity["trading_day"], "frequency": frequency,
                               "status": status, "reason": reason})
        priority = {"INFLIGHT": 0, "WAITING_SOURCE": 1, "WAITING_LEASE": 2, "PENDING": 3, "WAITING_DEPENDENCY": 4}
        active.sort(key=lambda item: (priority.get(item["status"], 5),
                                     -date.fromisoformat(item["trading_day"]).toordinal(), item["product"], item["frequency"]))
        budgets = {day: {field: state["budgets"][day][field] for field in ("requests", "bars")}
                   for day in sorted(state.get("budgets", {}))[-3:]}
        authority_waiting = (self.preparation.authority_waiting()
                             if hasattr(self.preparation, "authority_waiting") else ())
        if authority_waiting:
            counts["WAITING_AUTHORITY"] = len(authority_waiting)
        self._summary = {"error": self.error, "counts": counts, "active": active[:16],
                         "active_truncated": len(active) > 16, "budgets": budgets,
                         "authority_waiting": [dict(item) for item in authority_waiting[:16]],
                         "authority_waiting_truncated": len(authority_waiting) > 16}

    def snapshot(self):
        # Quote/heartbeat threads only copy this bounded cache. No filesystem,
        # Catalog, archive, provider or cross-process lock access is permitted.
        summary = self._summary
        return {"running": self._thread is not None and self._thread.is_alive(),
                "error": summary["error"], "counts": dict(summary["counts"]),
                "active": [dict(item) for item in summary["active"]],
                "active_truncated": summary["active_truncated"],
                "budgets": {day: dict(value) for day, value in summary["budgets"].items()},
                "authority_waiting": [dict(item) for item in summary["authority_waiting"]],
                "authority_waiting_truncated": summary["authority_waiting_truncated"]}
