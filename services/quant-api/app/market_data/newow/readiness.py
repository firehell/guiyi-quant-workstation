"""Serial, fixed-instant dependency audit; no provider or mutation capabilities."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import re
import time
from typing import Any

from guiyi_quant.newow.product_contracts import ProductFrequency, ProductStrategy
from guiyi_quant.newow.product_identity import utc_timestamp

from app.market_data.diagnostics import INTEGRITY_REASONS, MISSING_REASONS
from app.market_data.catalog import CatalogError
from app.market_data.market_data_service import MarketDataError
from app.market_data.session_clock import SessionClockError
from app.market_data.historical_data_manager import ContractWarmupRequest
from app.market_data.newow.product_reader import NewowProductReader
from app.market_data.newow.product_service import (
    AuxiliaryComponent,
    NewowProductService,
    ProductSection,
    ProductServiceQuery,
)
from app.market_data.newow.public_errors import public_product_error

_METADATA = MISSING_REASONS - {
    "REPLAY_PREFIX_MISSING",
    "REPLAY_ENDPOINTS_MISSING",
    "DATASET_OR_PARTITION_MISSING",
    "COMPLETE_PERIOD_MISSING",
}
_DOWNLOAD = {
    "REPLAY_PREFIX_MISSING",
    "REPLAY_ENDPOINTS_MISSING",
    "DATASET_OR_PARTITION_MISSING",
}


@dataclass(frozen=True, slots=True)
class ReadinessRequest:
    products: tuple[str, ...]
    as_of: datetime
    matrix: bool = False
    max_work: int = 10000
    timeout_seconds: int = 300

    def __post_init__(self) -> None:
        if (
            not self.products
            or len(self.products) > 60
            or len(set(self.products)) != len(self.products)
            or any(re.fullmatch(r"[a-z]{1,8}", item) is None for item in self.products)
            or type(self.max_work) is not int
            or not 1 <= self.max_work <= 100000
            or type(self.timeout_seconds) is not int
            or not 1 <= self.timeout_seconds <= 3600
            or type(self.matrix) is not bool
        ):
            raise ValueError("NEWOW_READINESS_ARGUMENT_INVALID")
        object.__setattr__(self, "as_of", utc_timestamp(self.as_of))


class AuditBudgetExceeded(RuntimeError):
    pass


class AuditBudget:
    def __init__(self, request: ReadinessRequest, clock: Callable[[], float]) -> None:
        self.clock = clock
        self.deadline = clock() + request.timeout_seconds
        self.limit = request.max_work
        self.used = 0
        self.exhausted = False

    def expired(self) -> bool:
        self.exhausted = self.exhausted or self.clock() >= self.deadline
        return self.exhausted

    def checkpoint(self) -> None:
        if self.expired():
            raise AuditBudgetExceeded

    def take(self) -> None:
        if self.used >= self.limit:
            self.exhausted = True
        self.checkpoint()
        self.used += 1


def _failure(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, (CatalogError, SessionClockError)):
        exc = MarketDataError(exc.code)
    _http, detail = public_product_error(exc)
    diagnostic = detail.get("diagnostic", {})
    reason = diagnostic.get("reason") if isinstance(diagnostic, dict) else None
    status = (
        "UNKNOWN"
        if reason in _METADATA
        else "DATA_UNAVAILABLE"
        if reason in MISSING_REASONS
        else "INTEGRITY_ERROR"
        if reason in INTEGRITY_REASONS
        else "SOURCE_EXCEPTION"
        if reason == "SOURCE_NONPOSITIVE_PRICE"
        else "UNKNOWN"
    )
    return {"status": status, "error": detail, "reason": reason}


class NewowReadinessAudit:
    def __init__(
        self,
        *,
        reader: NewowProductReader,
        plan: Callable[[ContractWarmupRequest], dict[str, Any]] | None = None,
        service: NewowProductService | None = None,
        clock: Callable[[], float] = time.monotonic,
        budget: AuditBudget | None = None,
    ) -> None:
        self.reader = reader
        self.plan = plan
        self.service = service
        self.clock = clock
        self.budget = budget

    def run(self, request: ReadinessRequest) -> dict[str, Any]:
        budget = self.budget or AuditBudget(request, self.clock)
        cases: list[dict[str, Any]] = (
            [
                {
                    "symbol": symbol,
                    "strategy": strategy.value,
                    "frequency": frequency.value,
                    "main": {"status": "UNSTARTED"},
                    "sections": {},
                }
                for symbol in request.products
                for strategy in ProductStrategy
                for frequency in ProductFrequency
            ]
            if request.matrix
            else []
        )
        enumerations: list[dict[str, Any]] = []
        dependencies: dict[tuple, dict[str, Any]] = {}
        metadata: list[dict[str, Any]] = []
        repairs: list[dict[str, Any]] = []
        # Every section's window is obtained from the same reader used by the API.
        # Full reference history may own contracts outside the latest chart window.
        for symbol in request.products:
            for selected in ProductFrequency:
                for section in ("chart", "auxiliary", "reference", "explanation"):
                    row: dict[str, Any] = {
                        "symbol": symbol,
                        "frequency": selected.value,
                        "section": section,
                        "status": "UNSTARTED",
                        "as_of": request.as_of.isoformat(),
                    }
                    enumerations.append(row)
                    try:
                        budget.take()
                        if section == "reference":
                            window = self.reader.resolve_performance_window(
                                symbol, selected, None, None, request.as_of
                            )
                            since, through, cutoff = (
                                window.requested_since,
                                window.actual_through,
                                window.cutoff,
                            )
                        else:
                            chart = self.reader.resolve_chart_window(
                                symbol, selected, 500, request.as_of
                            )
                            since, through, cutoff = (
                                chart.since,
                                chart.through,
                                request.as_of,
                            )
                        budget.checkpoint()
                        row.update(since=since.isoformat(), through=through.isoformat())
                        owners = self.reader.dependency_owners(symbol, since, through)
                        budget.checkpoint()
                        row.update(
                            status="ENUMERATED",
                            since=since.isoformat(),
                            through=through.isoformat(),
                            owner_count=len(owners),
                        )
                        frequencies = (
                            tuple(ProductFrequency)
                            if section == "explanation"
                            else (selected,)
                        )
                        for frequency in frequencies:
                            for owner in owners:
                                key = (
                                    symbol,
                                    owner.contract,
                                    frequency,
                                    owner.end_trading_day,
                                    cutoff,
                                )
                                dependency = dependencies.setdefault(
                                    key,
                                    {
                                        "symbol": symbol,
                                        "contract": owner.contract,
                                        "frequency": frequency.value,
                                        "through": owner.end_trading_day.isoformat(),
                                        "as_of": cutoff.isoformat(),
                                        "status": "UNSTARTED",
                                        "consumers": [],
                                        "owners": [],
                                        "_owner": owner,
                                        "_cutoff": cutoff,
                                    },
                                )
                                owner_fact = {
                                    "since": owner.start_trading_day.isoformat(),
                                    "through": owner.end_trading_day.isoformat(),
                                }
                                if owner_fact not in dependency["owners"]:
                                    dependency["owners"].append(owner_fact)
                                for strategy in ProductStrategy:
                                    consumer = {
                                        "strategy": strategy.value,
                                        "frequency": selected.value,
                                        "section": section,
                                    }
                                    if consumer not in dependency["consumers"]:
                                        dependency["consumers"].append(consumer)
                    except AuditBudgetExceeded:
                        continue
                    except Exception as exc:  # bounded public failures, never raw text
                        row.update(_failure(exc))
                        if budget.expired():
                            row.update(status="UNSTARTED", reason="BUDGET_EXHAUSTED")
                        elif row.get("reason") in _METADATA:
                            metadata.append(
                                {
                                    **row,
                                    "expected_bar_count": None,
                                    "provider_request_count": None,
                                    "proposal": "BOUNDED_METADATA_REPAIR_REVIEW_REQUIRED",
                                }
                            )
        for dependency in dependencies.values():
            try:
                budget.take()
                result = self.reader.check_dependency(
                    dependency["symbol"],
                    ProductFrequency(dependency["frequency"]),
                    dependency["_owner"],
                    dependency["_cutoff"],
                )
                budget.checkpoint()
                dependency.update(result)
            except AuditBudgetExceeded:
                continue
            except Exception as exc:
                dependency.update(_failure(exc))
                if budget.expired():
                    dependency.update(status="UNSTARTED", reason="BUDGET_EXHAUSTED")
                elif dependency.get("reason") in _METADATA:
                    metadata.append(
                        {
                            key: value
                            for key, value in dependency.items()
                            if not key.startswith("_")
                        }
                    )
                    metadata[-1].update(
                        expected_bar_count=None,
                        provider_request_count=None,
                        proposal="BOUNDED_METADATA_REPAIR_REVIEW_REQUIRED",
                    )
        # Planner deduplication is exact request identity, retaining every consumer.
        repair_groups: dict[tuple, dict[str, Any]] = {}
        for dependency in dependencies.values():
            if dependency.get("reason") not in _DOWNLOAD:
                continue
            repair_key = (
                dependency["symbol"],
                dependency["contract"],
                dependency["frequency"],
                dependency["_owner"].end_trading_day,
            )
            repair = repair_groups.setdefault(
                repair_key,
                {
                    "symbol": repair_key[0],
                    "contract": repair_key[1],
                    "frequency": repair_key[2],
                    "through": repair_key[3].isoformat(),
                    "consumers": [],
                    "status": "UNSTARTED",
                    "expected_bar_count": None,
                    "provider_request_count": None,
                    "plan_sha256": None,
                },
            )
            for consumer in dependency["consumers"]:
                if consumer not in repair["consumers"]:
                    repair["consumers"].append(consumer)
        for repair_key, repair in repair_groups.items():
            repairs.append(repair)
            try:
                budget.take()
                if self.plan is None:
                    repair.update(status="UNKNOWN", reason="PLANNER_UNAVAILABLE")
                    continue
                plan_result = self.plan(
                    ContractWarmupRequest(
                        symbol=repair_key[0],
                        contract=repair_key[1],
                        frequency=repair_key[2],
                        through=repair_key[3],
                    )
                )
                budget.checkpoint()
                repair.update(plan_result)
                diagnostics = plan_result.get("scope_diagnostics")
                if diagnostics is None:
                    repair.update(
                        status="UNKNOWN",
                        reason="PLANNER_SCOPE_DIAGNOSTICS_MISSING",
                        plan_sha256=None,
                        expected_bar_count=None,
                        provider_request_count=None,
                    )
                    continue
                scope_conflicts = [
                    item
                    for item in dependencies.values()
                    if item["symbol"] == repair_key[0]
                    and item["contract"] == repair_key[1]
                    and item["frequency"] in plan_result.get("frequencies", ())
                    and item["_owner"].end_trading_day <= repair_key[3]
                    and item["status"] in {"SOURCE_EXCEPTION", "INTEGRITY_ERROR"}
                ]
                if scope_conflicts or any(
                    set(item["reason_codes"])
                    & (INTEGRITY_REASONS | {"SOURCE_NONPOSITIVE_PRICE"})
                    for item in diagnostics
                ):
                    repair.update(
                        status="REVIEW_REQUIRED",
                        reason="REPAIR_SCOPE_SOURCE_OR_INTEGRITY",
                        plan_sha256=None,
                        expected_bar_count=None,
                        provider_request_count=None,
                    )
                    repair["scope_conflicts"] = [
                        {
                            key: row.get(key)
                            for key in (
                                "symbol",
                                "contract",
                                "frequency",
                                "through",
                                "status",
                                "reason",
                            )
                        }
                        for row in scope_conflicts
                    ]
                else:
                    repair["status"] = "PROPOSED"
            except AuditBudgetExceeded:
                continue
            except Exception as exc:
                repair.update(_failure(exc))
                repair.update(
                    plan_sha256=None,
                    expected_bar_count=None,
                    provider_request_count=None,
                )
                if repair.get("reason") in _METADATA:
                    metadata.append(
                        {
                            **repair,
                            "proposal": "BOUNDED_METADATA_REPAIR_REVIEW_REQUIRED",
                        }
                    )
        for case in cases:
            section_requests = [
                (ProductSection.CHART, None),
                *(
                    (ProductSection.AUXILIARY, component)
                    for component in AuxiliaryComponent
                ),
                (ProductSection.REFERENCE, None),
                (ProductSection.EXPLANATION, None),
                (ProductSection.COMPARATOR, None),
            ]
            for section, component in section_requests:
                section_name = (
                    f"auxiliary:{component.value}" if component else section.value
                )
                state: dict[str, Any] = {"status": "UNSTARTED"}
                case["sections"][section_name] = state
                if section is ProductSection.CHART:
                    case["main"] = state
                try:
                    budget.take()
                    if self.service is None:
                        state.update(
                            status="UNKNOWN", reason="VALIDATION_SERVICE_UNAVAILABLE"
                        )
                        continue
                    section_result = self.service.query(
                        ProductServiceQuery(
                            case["symbol"],
                            ProductStrategy(case["strategy"]),
                            ProductFrequency(case["frequency"]),
                            section=section,
                            component=component,
                            as_of=request.as_of,
                        )
                    )
                    budget.checkpoint()
                    delivery = getattr(section_result, section.value)
                    if delivery.status is None or delivery.delivery != "delivered":
                        state.update(status="UNKNOWN")
                    else:
                        state.update(
                            status=delivery.status.status.value.upper(),
                            evidence_status=delivery.status.evidence_status.value,
                            reason=delivery.status.reason_code,
                        )
                except AuditBudgetExceeded:
                    continue
                except Exception as exc:
                    state.update(_failure(exc))
                    if budget.expired():
                        state.update(status="UNSTARTED", reason="BUDGET_EXHAUSTED")
        public_dependencies = [
            {key: value for key, value in row.items() if not key.startswith("_")}
            for row in dependencies.values()
        ]
        incomplete = any(
            row["status"] in {"UNKNOWN", "UNSTARTED"}
            for row in [
                *enumerations,
                *public_dependencies,
                *repairs,
                *(state for case in cases for state in case["sections"].values()),
            ]
        )
        return {
            "schema_version": 1,
            "command": "data.newow-readiness",
            "readonly": True,
            "status": "incomplete" if incomplete or budget.exhausted else "audited",
            "complete": not incomplete and not budget.exhausted,
            "as_of": request.as_of.isoformat(),
            "matrix": request.matrix,
            "product_count": len(request.products),
            "main_case_count": len(cases),
            "main_ready_count": sum(
                case["main"]["status"] == "READY" for case in cases
            ),
            "budget_exhausted": budget.exhausted,
            "work_used": budget.used,
            "enumerations": enumerations,
            "dependencies": public_dependencies,
            "repair_targets": repairs,
            "metadata_proposals": metadata,
            "cases": cases,
            "provider_requests": 0,
            "writes": 0,
        }
