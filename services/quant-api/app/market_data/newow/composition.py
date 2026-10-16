"""Shared Newow reader/service assembly with explicit consumer policies.

The caller owns MDS/coverage snapshot lifetime and selects context quality,
clock, cancellation budget, caches and reference authority. No release or HTTP
policy is selected here.
"""

from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from datetime import datetime

from guiyi_quant.newow.product_contracts import ProductFrequency
from guiyi_quant.newow.product_identity import InputQualityPolicy

from app.market_data.market_data_service import MarketDataService

from .inflight import InFlightCoordinator
from .product_reader import NewowProductReader, ProductCoverage
from .product_service import NewowProductService
from .resource_gate import HeavyResourceGate
from .snapshot_cache import SnapshotCache


@dataclass(frozen=True)
class NewowComposition:
    market_data: MarketDataService
    coverage: ProductCoverage
    active_products: Collection[str]
    quality_policy: InputQualityPolicy
    now: Callable[[], datetime] | None = None
    context_quality_policy: (
        Callable[[str, ProductFrequency], InputQualityPolicy] | None
    ) = None
    budget_cancelled: Callable[[], bool] | None = None

    def reader(
        self,
        context: Sequence[ProductFrequency] = (),
        cancelled: Callable[[], bool] | None = None,
    ) -> NewowProductReader:
        if self.budget_cancelled is not None:
            consumer_cancelled = cancelled
            budget_cancelled = self.budget_cancelled

            def cancelled():
                return budget_cancelled() or (
                    consumer_cancelled is not None and consumer_cancelled()
                )

        return NewowProductReader(
            self.market_data,
            coverage=self.coverage,
            active_products=self.active_products,
            context_frequencies=context,
            now=self.now,
            cancelled=cancelled,
            input_quality_policy=self.quality_policy,
            context_quality_policy=self.context_quality_policy if context else None,
        )

    def service(
        self,
        *,
        cancelled: Callable[[], bool] | None,
        cache: SnapshotCache | None = None,
        heavy_gate: HeavyResourceGate | None = None,
        persisted_reference_gate: HeavyResourceGate | None = None,
        inflight: InFlightCoordinator | None = None,
        persisted_reference: Callable | None = None,
        reuse_read_inputs: bool = False,
    ) -> NewowProductService:
        return NewowProductService(
            self.reader,
            cache=cache,
            heavy_gate=heavy_gate,
            persisted_reference_gate=persisted_reference_gate,
            inflight=inflight,
            now=self.now,
            cancelled=cancelled,
            quality_policy=self.quality_policy,
            persisted_reference=persisted_reference,
            reuse_read_inputs=reuse_read_inputs,
        )
