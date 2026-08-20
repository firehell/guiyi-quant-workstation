from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.market_data.market_data_service import MarketDataError
from app.market_data.multi_candidate_robustness_service import (
    MultiCandidateRobustnessService,
    MultiCandidateRobustnessSourceError,
)
from app.market_data.multi_candidate_robustness_policy import (
    load_multi_candidate_robustness_protocol,
)
from app.market_data.n_structure_research_service import NStructureResearchRequest
from app.market_data.n_structure_policy import load_n_structure_policy
from app.market_data.n_structure_research_service import NStructureResearchService
from app.market_data.subing_lifecycle_research_service import LifecycleResearchRequest


def _horizons(value: Decimal | None = None) -> dict[int, SimpleNamespace]:
    return {
        horizon: SimpleNamespace(
            sample_count=int(value is not None),
            median_directional_return_bps=value,
            median_mfe_bps=value,
            median_mae_bps=value,
        )
        for horizon in (3, 5, 8)
    }


class _Runner:
    def __init__(self, kind: str, failures: dict[str, Exception] | None = None) -> None:
        self.kind = kind
        self.failures = failures or {}
        self.requests: list[object] = []

    def run(self, request: object) -> SimpleNamespace:
        self.requests.append(request)
        symbol = request.symbol
        if symbol in self.failures:
            raise self.failures[symbol]
        if self.kind == "subing":
            return SimpleNamespace(
                products=(symbol,),
                funnel_counts={"ENTRY_CONFIRMED": int(symbol == "jm")},
                evaluable_boundary_count=2,
                horizon_summary=_horizons(Decimal("1") if symbol == "jm" else None),
            )
        return SimpleNamespace(
            products=(symbol,),
            completed_n_counts={"up": int(symbol == "jm"), "down": 0},
            evaluable_bar_count=4,
            horizon_summary=_horizons(Decimal("-1") if symbol == "jm" else None),
        )


class _FailingLoader:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def load(self, **_kwargs: object) -> object:
        raise self.error


def _service(
    *,
    subing: object | None = None,
    n: object | None = None,
) -> MultiCandidateRobustnessService:
    return MultiCandidateRobustnessService(
        load_multi_candidate_robustness_protocol(),
        subing_research=subing or _Runner("subing"),
        n_research=n or _Runner("n"),
    )


def test_cross_symbol_matrix_retains_exact_120_cells_and_requests() -> None:
    subing = _Runner("subing")
    n = _Runner("n")
    results, summaries = _service(subing=subing, n=n)._cross_symbol_results()
    products = load_multi_candidate_robustness_protocol().cross_symbol_products

    assert len(results) == 120
    assert tuple((row.candidate_id, row.symbol) for row in results[:60]) == tuple(
        ("subing_lifecycle_v2_candidate_v1", symbol) for symbol in products
    )
    assert tuple((row.candidate_id, row.symbol) for row in results[60:]) == tuple(
        ("n_structure_5m_candidate_v1", symbol) for symbol in products
    )
    assert all(
        request.since == date(2023, 1, 1)
        and request.through == date(2026, 8, 18)
        for request in (*subing.requests, *n.requests)
    )
    assert isinstance(subing.requests[0], LifecycleResearchRequest)
    assert isinstance(n.requests[0], NStructureResearchRequest)
    assert tuple(summary.product_count for summary in summaries) == (60, 60)


def test_zero_event_and_typed_unavailable_are_distinct_and_retained() -> None:
    subing = _Runner("subing", {"ag": MarketDataError("MISSING")})
    results, summaries = _service(subing=subing)._cross_symbol_results()
    unavailable = next(row for row in results if row.candidate_id.startswith("subing") and row.symbol == "ag")
    zero = next(row for row in results if row.candidate_id.startswith("subing") and row.symbol == "a")

    assert unavailable.status.value == "unavailable"
    assert unavailable.reason_code == "MULTI_CANDIDATE_SOURCE_UNAVAILABLE"
    assert unavailable.event_count is unavailable.evaluable_count is None
    assert unavailable.event_rate_per_1000_evaluable is None
    assert unavailable.horizon_summary is None
    assert zero.status.value == "available"
    assert zero.event_count == 0
    assert zero.event_rate_per_1000_evaluable == Decimal(0)
    assert summaries[0].product_count == 60
    assert summaries[0].unavailable_product_count == 1


def test_decimal_rate_and_horizon_sign_summary_are_exact() -> None:
    results, summaries = _service()._cross_symbol_results()
    subing_jm = next(row for row in results if row.candidate_id.startswith("subing") and row.symbol == "jm")
    n_jm = next(row for row in results if row.candidate_id.startswith("n_structure") and row.symbol == "jm")
    assert subing_jm.event_rate_per_1000_evaluable == Decimal(500)
    assert n_jm.event_rate_per_1000_evaluable == Decimal(250)
    assert summaries[0].horizon_sign_summary[3].positive_median_return_symbols == 1
    assert summaries[1].horizon_sign_summary[3].negative_median_return_symbols == 1


@pytest.mark.parametrize("error", (TypeError("bug"), ValueError("bug"), AssertionError("bug"), RuntimeError("bug")))
def test_unexpected_source_errors_abort_complete_run(error: Exception) -> None:
    with pytest.raises(type(error)) as captured:
        _service(subing=_Runner("subing", {"a": error}))._cross_symbol_results()
    assert captured.value is error


def test_source_identity_mismatch_aborts_complete_run() -> None:
    runner = _Runner("subing")
    original = runner.run

    def wrong(request: object) -> SimpleNamespace:
        result = original(request)
        result.products = ("other",)
        return result

    runner.run = wrong  # type: ignore[method-assign]
    with pytest.raises(MultiCandidateRobustnessSourceError, match="MULTI_CANDIDATE_SOURCE_IDENTITY_INVALID"):
        _service(subing=runner)._cross_symbol_results()


def test_real_n_source_data_failure_becomes_explicit_unavailable_cells() -> None:
    protocol = load_multi_candidate_robustness_protocol()
    real_n = NStructureResearchService(
        _FailingLoader(MarketDataError("DATASET_OR_PARTITION_MISSING")),
        products=protocol.cross_symbol_products,
        policy=load_n_structure_policy(),
    )

    results, summaries = _service(n=real_n)._cross_symbol_results()
    n_rows = tuple(row for row in results if row.candidate_id.startswith("n_structure"))

    assert len(n_rows) == 60
    assert all(row.status.value == "unavailable" for row in n_rows)
    assert summaries[1].unavailable_product_count == 60


@pytest.mark.parametrize(
    "error",
    (TypeError("bug"), ValueError("bug"), AssertionError("bug"), RuntimeError("bug")),
)
def test_real_n_source_unexpected_failure_aborts_collector(error: Exception) -> None:
    protocol = load_multi_candidate_robustness_protocol()
    real_n = NStructureResearchService(
        _FailingLoader(error),
        products=protocol.cross_symbol_products,
        policy=load_n_structure_policy(),
    )

    with pytest.raises(type(error)) as captured:
        _service(n=real_n)._cross_symbol_results()

    assert captured.value is error
