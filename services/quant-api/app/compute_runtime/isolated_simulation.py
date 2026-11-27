"""Attach owned Live computation to the isolated simulation composition."""

from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .owned_live import OwnedLiveCommit, OwnedLiveScope, verify_tick_original

if TYPE_CHECKING:
    from app.market_data.domain import CanonicalBar
    from app.market_data.observation_stream import ObservationStream
    from app.subing_model.factors import Factors
    from app.subing_portfolio_journal import PortfolioJournal

    from .runtime import ComputeRuntime


def require_isolated_database(url, *, database: str) -> None:
    if (url.get_backend_name() != "postgresql" or url.host != "127.0.0.1"
            or url.database != database or url.port in (None, 5432) or url.query):
        raise ValueError("COMPUTE_LIVE_ISOLATION_REQUIRED")


def require_isolated_market_binding(market_url, redis, canonical_root: Path) -> None:
    from app.market_data.market_foundation_scope import require_isolated_market_tick

    require_isolated_database(market_url, database="guiyi_market_foundation")
    endpoint = redis.connection_pool.connection_kwargs
    if (endpoint.get("host") != "127.0.0.1" or endpoint.get("port") in (None, 6379)
            or canonical_root.name != "canonical" or not canonical_root.is_absolute()
            or not canonical_root.is_dir() or canonical_root.resolve() != canonical_root):
        raise ValueError("COMPUTE_LIVE_ISOLATION_REQUIRED")
    require_isolated_market_tick(redis, canonical_root.parent, market_url)


def paper_live_scopes(day: date, contexts: Mapping) -> tuple[OwnedLiveScope, ...]:
    return tuple(OwnedLiveScope("subing_simulation", product, context["contract"], period, day)
                 for product, context in contexts.items() for period in ("30m", "60m")
                 if context["expected_" + period])


class PaperLiveFactors:
    """Use the original warmed Factors object in the native Paper worker."""

    def __init__(
        self, runtime: "ComputeRuntime", stream: "ObservationStream", factor: "Factors",
        context: Mapping, day: date, product: str,
    ) -> None:
        if factor.contract != context["contract"]:
            raise ValueError("PAPER_LIVE_FACTOR_OWNER_MISMATCH")
        self._runtime = runtime
        self._stream = stream
        self._factor = factor
        self._day = day
        self._product = product
        self._scopes = {scope.frequency: scope for scope in paper_live_scopes(day, {product: context})}
        self._predecessors = {}
        for period in self._scopes:
            ends = [datetime.fromisoformat(value) for value in context["expected_" + period]]
            if (any(endpoint.utcoffset() is None for endpoint in ends)
                    or any(left >= right for left, right in zip(ends, ends[1:]))):
                raise ValueError("PAPER_LIVE_ENDPOINTS_INVALID")
            self._predecessors[period] = dict(zip(ends, (None, *ends[:-1]), strict=True))

    @property
    def frame(self):
        return self._factor.frame

    @property
    def hourly(self):
        return self._factor.hourly

    @property
    def structure_point(self):
        return self._factor.structure_point

    def observation(self, candle: "CanonicalBar", day_end_window: bool):
        original = self._original("1m", candle)
        verify_tick_original(original, self._product, self._factor.contract, "1m", self._day)
        return self._factor.observation(candle, day_end_window)

    def _original(self, frequency: str, candle: "CanonicalBar"):
        from app.subing_model.pipeline import bar

        if candle.trading_day != self._day:
            raise ValueError("PAPER_LIVE_ENDPOINT_UNPROVEN")
        contract = self._factor.contract
        original = self._stream.read_original(
            self._day, f"{self._day}:{contract}:{frequency}:{candle.bar_end.isoformat()}",
        )
        if bar(original.data) != candle:
            raise ValueError("PAPER_LIVE_ORIGINAL_MISMATCH")
        return original

    def step(self, frequency: str, candle: "CanonicalBar"):
        if candle.bar_end not in self._predecessors.get(frequency, {}):
            raise ValueError("PAPER_LIVE_ENDPOINT_UNPROVEN")
        scope = self._scopes[frequency]
        commit = OwnedLiveCommit.from_original(
            scope, self._original(frequency, candle), previous_bar_end=self._predecessors[frequency][candle.bar_end],
        )
        # A failed or uncertain step bubbles out to the existing worker. A new
        # owner must warm from verified history before attempting that input again.
        return self._runtime.submit_owned_live(
            commit, owner=self._factor, run=lambda: self._factor.step(frequency, candle),
        ).result(timeout=10).result


def bind_paper_live_factors(
    runtime: "ComputeRuntime", stream: "ObservationStream", journal: "PortfolioJournal",
    day: date, contexts: Mapping, factors: Mapping, *, market_url, canonical_root: Path,
) -> dict[str, PaperLiveFactors]:
    """Wrap factor calls only. The native worker still owns the journal and its cursor."""
    require_isolated_database(journal.store.engine.url, database="guiyi_subing_development_test")
    require_isolated_market_binding(market_url, stream.redis, canonical_root)
    if stream.kind != "completed" or set(journal.products) != set(contexts) or set(factors) != set(contexts):
        raise ValueError("PAPER_LIVE_SCOPE_MISMATCH")
    return {product: PaperLiveFactors(runtime, stream, factors[product], context, day, product)
            for product, context in contexts.items()}
