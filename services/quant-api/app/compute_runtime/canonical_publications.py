"""Advance explicitly subscribed research windows after verified Market publication."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime
from hashlib import sha256
from pathlib import Path
from threading import RLock

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from guiyi_quant.compute import REGISTRY, BarSeries, CompletedBar, SeriesIdentity

from app.db.readonly import readonly_transaction
from app.market_data.catalog import MarketCatalog
from app.market_data.domain import BarFrequency, ContractTradingDayQuery, canonical_bar_source_sha256
from app.market_data.market_archive import (
    RECEIPT_DIRECTORY, MarketArchiveReceipt, read_archive_receipt, reference_catalog_revision,
)
from app.market_data.market_data_service import MarketDataService
from app.market_data.storage import CanonicalMonthlyStore

from .contracts import ComputeScope, ComputeWindow, FeatureUpdate
from .runtime import ComputeRuntime


@dataclass(frozen=True, slots=True)
class CanonicalResearchWindow:
    """A bounded research prefix for one exact physical owner and frequency."""

    scope: ComputeScope
    since: date
    through: date

    def __post_init__(self) -> None:
        if (type(self.since) is not date or type(self.through) is not date
                or not 0 <= (self.through - self.since).days <= 366):
            raise ValueError("COMPUTE_CANONICAL_WINDOW_INVALID")
        scope = self.scope
        query = ContractTradingDayQuery(scope.product, scope.physical_contract, BarFrequency(scope.frequency),
                                        self.since, self.through)
        if (query.symbol != scope.product or query.contract != scope.physical_contract
                or scope.segment_id != f"contract:{scope.physical_contract}"):
            raise ValueError("COMPUTE_CANONICAL_PHYSICAL_SCOPE_REQUIRED")


@dataclass(frozen=True, slots=True)
class _PublicationState:
    identity: str
    order: tuple[date, datetime]
    product_revision: str
    through: date
    input_digest: str
    updates: tuple[FeatureUpdate, ...]


class CanonicalPublicationCompute:
    """One receipt subscriber for the lifetime of an isolated research consumer."""

    def __init__(
        self, engine: Engine, canonical_root: Path, windows: tuple[CanonicalResearchWindow, ...],
        *, now: Callable[[], datetime],
    ) -> None:
        if not 1 <= len(windows) <= 32:
            raise ValueError("COMPUTE_CANONICAL_SCOPE_LIMIT")
        self.engine = engine
        self.canonical_root = canonical_root
        self._now = now
        self._windows = windows
        self._completed: dict[int, _PublicationState] = {}
        self._lock = RLock()
        self._runtime = ComputeRuntime(REGISTRY, canonical_scopes=tuple(window.scope for window in windows))

    def latest_result(self, target: CanonicalResearchWindow) -> tuple[FeatureUpdate, ...] | None:
        """Read this scope's most recent accepted result with its original identity."""
        with self._lock:
            for index, window in enumerate(self._windows):
                if target == window and (state := self._completed.get(index)) is not None:
                    return state.updates
        return None

    def accept(self, path: Path, day: date) -> tuple[FeatureUpdate, ...]:
        """Read the retained receipt, then publish changed results to the caller."""
        if path.parent != self.canonical_root.parent / RECEIPT_DIRECTORY:
            raise ValueError("COMPUTE_CANONICAL_RECEIPT_PATH_INVALID")
        receipt = read_archive_receipt(path, now=self._now())
        if receipt.trading_day != day:
            raise ValueError("COMPUTE_CANONICAL_RECEIPT_DAY_MISMATCH")
        order = (receipt.trading_day, receipt.finished_at)

        with self._lock:
            staged: dict[int, _PublicationState] = {}
            results = []
            for index, target in enumerate(self._windows):
                product = target.scope.product
                if product not in receipt.revisions or receipt.trading_day < target.since:
                    continue
                prior = self._completed.get(index)
                if prior is not None:
                    if receipt.identity == prior.identity or order < prior.order:
                        continue
                    if order == prior.order:
                        raise ValueError("COMPUTE_CANONICAL_RECEIPT_ORDER_CONFLICT")
                revision = receipt.revisions[product]
                through = min(target.through, receipt.trading_day)
                if prior is not None and revision == prior.product_revision and through == prior.through:
                    digest, updates = prior.input_digest, prior.updates
                else:
                    series, digest = self._load(receipt, target, through=through)
                    if prior is not None and digest == prior.input_digest:
                        updates = prior.updates
                    else:
                        window = ComputeWindow.from_series(series, as_of=receipt.finished_at)
                        if window.bar_count != len(series.bars):
                            raise ValueError("COMPUTE_CANONICAL_WINDOW_UNAVAILABLE")
                        computed = self._runtime.submit_canonical(
                            receipt, window, consumer=target.scope.consumer, load=lambda source=series: source,
                        ).result(timeout=30)
                        # The revised value is first knowable from this receipt.
                        # Preserve the original Bar ends and the internal prefix.
                        updates = tuple(
                            replace(update, point=replace(update.point, available_at=receipt.finished_at))
                            if update.point is not None else update for update in computed
                        )
                        results.extend(updates)
                staged[index] = _PublicationState(receipt.identity, order, revision,
                                                 through, digest, updates)

            if staged:
                # Check current pointers after queued jobs, in a fresh transaction.
                with Session(self.engine) as session, readonly_transaction(session, timeout_seconds=30):
                    for product in sorted({self._windows[index].scope.product for index in staged}):
                        _require_revision(session, receipt, product)
                self._completed.update(staged)
            return tuple(results)

    def _load(
        self, receipt: MarketArchiveReceipt, target: CanonicalResearchWindow, *, through: date,
    ) -> tuple[BarSeries, str]:
        scope = target.scope
        query = ContractTradingDayQuery(
            scope.product, scope.physical_contract, BarFrequency(scope.frequency), target.since, through,
        )
        with Session(self.engine) as session, readonly_transaction(session, timeout_seconds=30):
            _require_revision(session, receipt, scope.product)
            market = MarketDataService(MarketCatalog(session, self.canonical_root),
                                       CanonicalMonthlyStore(self.canonical_root))
            page = market.query_contract_trading_days(query)
            if page.requested_trading_day_window != (target.since, through) or not page.bars:
                raise ValueError("COMPUTE_CANONICAL_WINDOW_UNAVAILABLE")
        source = SeriesIdentity(
            scope.product, scope.physical_contract, scope.segment_id, scope.frequency,
            receipt.revisions[scope.product],
        )
        fingerprint = sha256()
        bars = []
        for bar in page.bars:
            fingerprint.update(bytes.fromhex(canonical_bar_source_sha256(bar)))
            bars.append(CompletedBar(
                scope.physical_contract, scope.segment_id, bar.trading_day, f"historical:{bar.trading_day}",
                bar.bar_end, bar.bar_end, bar.bar_end, float(bar.open), float(bar.high), float(bar.low),
                float(bar.close), float(bar.volume) if bar.volume is not None else None,
                "MISSING" if bar.is_strict_no_trade else "VALID",
            ))
        return BarSeries(source, tuple(bars)), fingerprint.hexdigest()

    def __enter__(self) -> "CanonicalPublicationCompute":
        return self

    def __exit__(self, *_: object) -> None:
        with self._lock:
            self._runtime.close()


def _require_revision(session: Session, receipt: MarketArchiveReceipt, product: str) -> None:
    if reference_catalog_revision(session, product, receipt.trading_day) != receipt.revisions[product]:
        raise ValueError("MARKET_ARCHIVE_SOURCE_CHANGED")
