"""Newow directory metadata and exact, committed ReferenceTrading reads."""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy.exc import SQLAlchemyError

from app.market_data.newow.market_reference_after_close import (
    latest_formal_reference, latest_reference, present_saved_chart,
)
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
        data = read_worker_health_summary(include_receipts=True)
        worker_status = data["status"]
        receipt_status = data.get("reference_receipts")
        auth = data["binding_status"]
        if data.get("heartbeat_stale"):
            status = "STALE"
        elif auth == "UNKNOWN":
            status = "UNKNOWN"
        elif worker_status == "unverified":
            status = "UNVERIFIED"
        elif receipt_status is not None or self.formal and auth == "ENABLED":
            status = {"waiting_archive": "WAITING", "calculating": "WAITING",
                      "pending": "WAITING", "current": "AVAILABLE",
                      "unavailable": "BLOCKED"}.get(receipt_status, "UNKNOWN")
        else:
            status = {"disabled": "DISABLED", "not_ready": "BLOCKED",
                      "ready": "AVAILABLE"}.get(worker_status, "UNKNOWN")
        return projection(
            RUNTIME, status, source_as_of=data.get("observed_at"),
            heartbeat_at=data.get("observed_at"), domain_status=receipt_status or worker_status,
            diagnostic=data.get("failure_code") or data.get("stage"),
            generation=data.get("generation"), deployment=data.get("deployment"), commit=data.get("commit"),
            authorization={"status": auth}, worker_status=worker_status,
            watermark=data.get("last_success"),
            diagnostics={key: data[key] for key in ("blocked_count", "blocked_counts", "pending_keys", "canonical_compute")
                         if key in data},
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
        if self.formal:
            result = latest_formal_reference(product, strategy.owner_key, frequency, session_factory=self.sessions)
        current = result is not None
        if result is None:
            result = latest_reference(product, strategy.owner_key, frequency, session_factory=self.sessions)
        if result is None:
            return projection(EVIDENCE, "NOT_PUBLISHED")
        status = "PUBLISHED" if current else "HISTORICAL_RESULT"
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
            current_publication=("PUBLISHED" if current else "NOT_PUBLISHED") if self.formal else None,
            action_trading_day=through, trade_cutoff=result["cutoff"],
            presentation_status=chart["main_status"],
            actions=[item for frame in chart["frames"] for item in frame["actions"]][-8:],
            hints=[item for frame in chart["frames"] for item in frame["hints"]][-8:],
            reference_trades=trades["items"],
            more_trades=trades["next_cursor"] is not None, dependencies=strategy.dependencies,
        )
