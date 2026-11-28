"""Newow directory metadata and exact, committed ReferenceTrading reads."""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy.exc import SQLAlchemyError

from app.market_data.newow.market_reference_after_close import (
    _acknowledged_routes, _current_scope_receipt, latest_formal_reference, latest_reference, present_saved_chart,
)
from app.market_data.market_archive import current_retained_receipt, formal_archive_root
from app.market_data.newow.product_release import CAPABILITY_SCHEMA_VERSION, OPEN_INTRADAY_PRODUCTS, OPEN_WEEKLY_PRODUCTS
from app.market_data.newow.capability_contracts import capability_response
from app.market_data.operational_universe import load_active_products, load_operational_products
from app.reference_trading.health import read_worker_health_summary
from app.reference_trading.historical_refresh import canonical_newow_history_identity
from app.reference_trading.query import HistoricalReferenceQuery, QueryConflict
from app.reference_trading.recording_scope import FREQUENCIES

from .reads import projection, version

CAPABILITY = "Newow Product / ReferenceTrading scope"
RUNTIME = "ReferenceTrading worker health"
BINDINGS = "ReferenceTrading stream registration"
EVIDENCE = "ReferenceTrading saved result"


class Newow:
    def __init__(self, sessions, *, receipt_only=False, formal=False):
        self.sessions = sessions
        self.reader = HistoricalReferenceQuery(sessions, market_scope=True)
        self.receipt_only = receipt_only
        self.formal = formal

    def capability(self, strategy):
        if self.receipt_only:
            products = load_operational_products()
            return {frequency: products for frequency in FREQUENCIES}
        contract = capability_response(CAPABILITY_SCHEMA_VERSION)
        periods = contract["strategy_frequencies"].get(strategy.owner_key, contract["open_frequencies"])
        active = set(load_active_products())
        inventory = {"1w": OPEN_WEEKLY_PRODUCTS, "1d": sorted(active)}
        return {frequency: sorted(active.intersection(inventory.get(frequency, OPEN_INTRADAY_PRODUCTS)))
                for frequency in periods}

    def overview(self, strategy):
        return {
            "source": CAPABILITY,
            "capability": self.capability(strategy),
            "capability_version": "market_archive_scope" if self.receipt_only else CAPABILITY_SCHEMA_VERSION,
            "input_requirements": ["completed", "actual_dominant", "Canonical / MarketDataService"],
            "allowed_uses": ["reference_trading"],
            "result_owner": "ReferenceTrading",
        }

    def runtime(self):
        if self.receipt_only and not self.formal:
            return projection(RUNTIME, "UNKNOWN", diagnostic="ISOLATED_WORKER_STATUS_UNAVAILABLE")
        if self.formal:
            return _formal_runtime()
        data = read_worker_health_summary()
        worker_status = data["status"]
        return projection(
            RUNTIME, {"disabled": "DISABLED", "not_ready": "BLOCKED", "ready": "AVAILABLE"}.get(
                worker_status, "UNVERIFIED",
            ), source_as_of=data.get("observed_at"), heartbeat_at=data.get("observed_at"),
            domain_status=worker_status, diagnostic=data.get("stage"),
            generation=data.get("generation"), watermark=data.get("last_success"),
        )

    def bindings(self, strategy, product, frequency):
        if not product:
            return projection(BINDINGS, "SELECTION_REQUIRED")
        identity = canonical_newow_history_identity(product, strategy.owner_key, frequency)
        versions = [*(version("formula", item, CAPABILITY) for item in identity.formula_versions),
                    version("profile", identity.profile_id, CAPABILITY),
                    version("reference_model", identity.reference_model_version, CAPABILITY)]
        try:
            historical = self.reader.stream_for(identity)
            forward = [] if self.receipt_only else self.reader.streams(
                strategy=identity.strategy_code, product=product, frequency=frequency, mode="forward_observation",
            )
        except (OSError, SQLAlchemyError, QueryConflict) as error:
            return projection(
                BINDINGS, "UNAVAILABLE", references=versions,
                diagnostic=error.code if isinstance(error, QueryConflict) else "REFERENCE_SCHEMA_UNAVAILABLE",
            )
        return projection(
            BINDINGS, "REGISTERED" if historical or forward else "NOT_REGISTERED",
            read_at=datetime.now(UTC), series_kind=identity.series_kind, references=versions,
            historical=historical, forward=forward,
        )

    def evidence(self, strategy, product, frequency):
        if not product:
            return projection(EVIDENCE, "SELECTION_REQUIRED")
        if self.receipt_only and not self.formal:
            # The isolated service must retain its existing archive admission.
            from app.market_data.composition import canonical_root
            from app.market_data.market_archive import require_isolated_archive
            from app.redis_connections import REDIS_URL
            with self.sessions() as session:
                require_isolated_archive(session.get_bind().url, REDIS_URL, canonical_root())
        result = None
        current_status = current_diagnostic = None
        if self.formal:
            try:
                result = latest_formal_reference(product, strategy.owner_key, frequency, session_factory=self.sessions)
                current_status = "PUBLISHED" if result is not None else "NOT_PUBLISHED"
            except (OSError, ValueError, SQLAlchemyError):
                current_status = "UNAVAILABLE"
                current_diagnostic = "MARKET_REFERENCE_CURRENT_UNAVAILABLE"
        current = {"current_publication": current_status, "current_diagnostic": current_diagnostic}
        if result is None:
            try:
                result = latest_reference(product, strategy.owner_key, frequency, session_factory=self.sessions)
            except ValueError as error:
                if str(error) != "MARKET_REFERENCE_RESULT_INVALID":
                    raise
                return projection(EVIDENCE, "UNAVAILABLE", diagnostic="MARKET_REFERENCE_RESULT_INVALID", **current)
        if result is None:
            return projection(EVIDENCE, current_status or "NOT_PUBLISHED", diagnostic=current_diagnostic, **current)
        status = "PUBLISHED" if current_status == "PUBLISHED" else "HISTORICAL_RESULT"
        through = date.fromisoformat(result["through"])
        window = {"since": through, "through": through, "cutoff": result["cutoff"]}
        try:
            trades = self.reader.trades(result["stream_id"], limit=8, **window)
            if (trades["revision_id"], trades["seq"]) != (result["revision_id"], result["seq"]):
                return projection(EVIDENCE, "UNVERIFIED", diagnostic="REFERENCE_SNAPSHOT_CHANGED")
            chart = present_saved_chart(
                self.reader, result["stream_id"], snapshot=trades["snapshot"],
                bar_from=result["cutoff"] - timedelta(days=7), bar_through=result["cutoff"], **window,
            )
        except QueryConflict as error:
            return projection(EVIDENCE, "UNAVAILABLE", diagnostic=error.code)
        return projection(
            EVIDENCE, status, source_as_of=result["computed_at"], result=result,
            action_trading_day=through, trade_cutoff=result["cutoff"],
            presentation_status=chart["main_status"],
            actions=[item for frame in chart["frames"] for item in frame["actions"]][-8:],
            hints=[item for frame in chart["frames"] for item in frame["hints"]][-8:],
            reference_trades=trades["items"],
            more_trades=trades["next_cursor"] is not None, dependencies=strategy.dependencies, **current,
        )



def _formal_runtime():
    """Project only the bound worker's heartbeat and acknowledged current receipt."""
    from app.runtime_bindings import resolve_service_binding
    from app.runtime_deployment import owner_process_matches
    from app.runtime_handover import read_service_state

    service = "reference-worker"
    binding = resolve_service_binding(service)
    if binding is None or not binding.enabled:
        return projection(RUNTIME, "DISABLED" if binding is not None else "UNKNOWN",
                          authorization={"status": "DISABLED" if binding is not None else "UNKNOWN"})
    identity = {"generation": binding.generation, "deployment": binding.tag, "commit": binding.commit,
                "authorization": {"status": "ENABLED"}}
    state = read_service_state(service)
    if not state or state.get("generation") != binding.generation or not isinstance(state.get("at"), str):
        return projection(RUNTIME, "UNVERIFIED", diagnostic="REFERENCE_WORKER_IDENTITY_UNPROVEN", **identity)
    stamp = datetime.fromisoformat(state["at"])
    if stamp.tzinfo is None:
        return projection(RUNTIME, "UNVERIFIED", diagnostic="REFERENCE_WORKER_HEARTBEAT_INVALID", **identity)
    now = datetime.now(UTC)
    heartbeat = stamp.isoformat()
    proof = state.get("proof", {})
    receipt_status = proof.get("reference_receipts")
    ready = state.get("ready") is True
    facts = {**identity, "heartbeat_at": heartbeat, "heartbeat_status": "ready" if ready else "not_ready",
             "domain_status": receipt_status, "worker_status": "ready" if ready else "not_ready",
             "diagnostics": {"canonical_compute": proof.get("canonical_compute")}}
    watermark = None
    diagnostic = proof.get("failure_code")
    if not 0 <= (now - stamp).total_seconds() <= 60:
        status = "STALE"
    elif state.get("phase") != "active" or not owner_process_matches(state, binding):
        status = "UNVERIFIED"
        diagnostic = "REFERENCE_WORKER_IDENTITY_UNPROVEN"
    elif not ready or receipt_status == "unavailable":
        status = "BLOCKED"
    elif receipt_status in {"waiting_archive", "calculating", "pending"}:
        status = "WAITING"
    elif receipt_status == "current":
        root = formal_archive_root()
        receipt = _current_scope_receipt(current_retained_receipt(root, now=now), set(load_operational_products()))
        if receipt is not None and _acknowledged_routes(root, receipt.identity):
            status = "AVAILABLE"
            watermark = {"trading_day": receipt.trading_day.isoformat(), "archived_at": receipt.finished_at.isoformat(),
                         "receipt": receipt.identity}
        else:
            status = "UNVERIFIED"
            diagnostic = "REFERENCE_ARCHIVE_ACK_UNPROVEN"
    else:
        status = "UNKNOWN"
    return projection(RUNTIME, status, source_as_of=heartbeat, diagnostic=diagnostic, watermark=watermark, **facts)
