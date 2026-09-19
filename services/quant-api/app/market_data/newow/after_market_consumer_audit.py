"""Bounded, read-only summaries for post-maintenance Newow consumers."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import hashlib
import json
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.env import PROJECT_ROOT
from app.market_data.composition import build_market_data_service
from app.market_data.coverage_source import DatabaseCoverageSource
from app.market_data.operational_universe import load_operational_products
from app.models import (
    Contract,
    Exchange,
    Instrument,
    MainContractMap,
    MarketDataset,
    MarketPartition,
    TradingCalendar,
    TradingSession,
)
from guiyi_quant.newow.product_contracts import ProductFrequency

from .product_reader import NewowProductReader
from .product_release import CANDIDATE_WEEKLY_PRODUCTS
from .readiness import ReadinessRequest
from .readiness_composition import build_newow_readiness
from .weekly_snapshot import publication_state_from_status


_STRATEGIES = frozenset({"trend", "oscillation", "main_rise"})
_SECTIONS = frozenset({
    "chart",
    "reference",
    "auxiliary:macd",
    "auxiliary:main_force_control",
    "auxiliary:up_down_energy",
    "auxiliary:zhaoyao_mirror",
    "auxiliary:cup_handle",
})
_LEGAL_NON_READY = frozenset({"WARMING", "NOT_APPLICABLE", "UNAVAILABLE", "DATA_INTERRUPTED"})
_PRODUCT = re.compile(r"[a-z]{1,4}\Z")
_CONTRACT = re.compile(r"[A-Z]{1,4}[0-9]{3,4}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_SCOPE_TIMEOUT_SECONDS = 600
_TOTAL_TIMEOUT_SECONDS = 1200


def audit_newow_consumers(
    session: Session,
    *,
    products: tuple[str, ...],
    trading_day: date,
    audit_now: datetime,
    after_market_status: Mapping[str, object],
    clock: Callable[[], float],
) -> dict[str, dict[str, object]]:
    """Audit D1 operational and W1 staged consumers without mutation capabilities."""
    market = build_market_data_service(session)
    coverage = DatabaseCoverageSource(
        session,
        PROJECT_ROOT / "data/universe/product_window_starts.csv",
        now=lambda: audit_now,
    )
    reader = NewowProductReader(
        market,
        coverage=coverage,
        active_products=load_operational_products(),
        now=lambda: audit_now,
    )
    scopes = (
        ConsumerAuditScope(
            "newow_d1", products, "1d", _SCOPE_TIMEOUT_SECONDS
        ),
        ConsumerAuditScope(
            "newow_w1",
            tuple(CANDIDATE_WEEKLY_PRODUCTS),
            "1w",
            _SCOPE_TIMEOUT_SECONDS,
        ),
    )

    def resolve_cutoff(scope: ConsumerAuditScope, product: str) -> datetime:
        if scope.frequency == "1d":
            cutoff = max(
                window.end.astimezone(UTC)
                for window in market.session_windows(
                    symbol=product, trading_day=trading_day,
                )
            ) + timedelta(microseconds=1)
            if cutoff > audit_now:
                raise RuntimeError("NEWOW_CONSUMER_CUTOFF_INCOMPLETE")
            return cutoff
        candidates = reader.weekly_snapshot_candidates(product, as_of=audit_now, limit=2)
        if not candidates:
            raise RuntimeError("NEWOW_WEEKLY_UNKNOWN")
        day, cutoff = candidates[0]
        if reader.weekly_tail_unpublished(product, day):
            publication = publication_state_from_status(
                after_market_status, product, day, audit_now,
            )
            if publication == "pending_update" and len(candidates) > 1:
                return candidates[1][1]
        return cutoff

    def build_report(
        scope: ConsumerAuditScope,
        selected: tuple[str, ...],
        cutoff: datetime,
        timeout_seconds: int,
    ) -> Mapping[str, object]:
        return build_newow_readiness(session, request=ReadinessRequest(
            products=selected,
            as_of=cutoff,
            matrix=True,
            max_work=100000,
            timeout_seconds=timeout_seconds,
            frequencies=(ProductFrequency(scope.frequency),),
            candidate_weekly=scope.frequency == "1w",
            consumer_only=True,
        ))

    return run_bounded_consumer_audits(
        scopes,
        resolve_cutoff=resolve_cutoff,
        build_report=build_report,
        input_revision=lambda scope: catalog_revision(
            session,
            scope.products,
            trading_day,
            ("1d", "1w") if scope.frequency == "1w" else ("1d",),
        ),
        clock=clock,
        total_timeout_seconds=_TOTAL_TIMEOUT_SECONDS,
    )


def catalog_revision(
    session: Session,
    products: tuple[str, ...],
    day: date,
    frequencies: tuple[str, ...],
) -> str:
    """Hash exact Catalog inputs used by one post-maintenance consumer scope."""
    product_symbols = tuple(sorted(products))
    calendar_through = (
        day + timedelta(days=7 - day.isoweekday())
        if "1w" in frequencies
        else day
    )
    exchanges = tuple(sorted(set(session.scalars(
        select(Instrument.exchange_code).where(Instrument.symbol.in_(product_symbols))
    ))))
    tables = (
        ("instrument", select(Instrument.__table__).where(Instrument.symbol.in_(product_symbols))),
        ("exchange", select(Exchange.__table__).where(Exchange.code.in_(exchanges))),
        ("contract", select(Contract.__table__).where(Contract.instrument_symbol.in_(product_symbols))),
        ("calendar", select(TradingCalendar.__table__).where(
            TradingCalendar.exchange_code.in_(exchanges),
            TradingCalendar.trade_date <= calendar_through,
        )),
        ("session", select(TradingSession.__table__).where(
            TradingSession.instrument_symbol.in_(product_symbols)
        )),
        ("rank1", select(MainContractMap.__table__).where(
            MainContractMap.symbol.in_(product_symbols), MainContractMap.trade_date <= day,
        )),
        ("dataset", select(MarketDataset.__table__).where(
            MarketDataset.symbol.in_(product_symbols), MarketDataset.kind == "contract",
            MarketDataset.frequency.in_(frequencies),
        )),
        ("partition", select(MarketPartition.__table__).join(
            MarketDataset.__table__, MarketPartition.dataset_id == MarketDataset.id,
        ).where(
            MarketDataset.symbol.in_(product_symbols), MarketDataset.kind == "contract",
            MarketDataset.frequency.in_(frequencies),
        )),
    )
    digest = hashlib.sha256()
    for name, statement in tables:
        digest.update(name.encode("ascii"))
        for row in session.execute(statement.order_by(statement.selected_columns.id)).yield_per(1000):
            digest.update(json.dumps(
                tuple(row), sort_keys=True, default=str, ensure_ascii=True,
            ).encode("utf-8"))
            digest.update(b"\n")
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class ConsumerAuditScope:
    key: str
    products: tuple[str, ...]
    frequency: str
    timeout_seconds: int

    def __post_init__(self) -> None:
        if (
            self.key not in {"newow_d1", "newow_w1"}
            or not self.products
            or len(set(self.products)) != len(self.products)
            or any(_PRODUCT.fullmatch(product) is None for product in self.products)
            or self.frequency not in {"1d", "1w"}
            or type(self.timeout_seconds) is not int
            or not 1 <= self.timeout_seconds <= 900
        ):
            raise ValueError("NEWOW_CONSUMER_AUDIT_SCOPE_INVALID")


def run_bounded_consumer_audits(
    scopes: tuple[ConsumerAuditScope, ...], *,
    resolve_cutoff: Callable[[ConsumerAuditScope, str], datetime],
    build_report: Callable[[ConsumerAuditScope, tuple[str, ...], datetime, int], Mapping[str, object]],
    input_revision: Callable[[ConsumerAuditScope], str],
    clock: Callable[[], float],
    total_timeout_seconds: int,
) -> dict[str, dict[str, object]]:
    """Run independent scopes inside one wall-clock budget, without mutation hooks."""
    if (
        not scopes
        or len({scope.key for scope in scopes}) != len(scopes)
        or type(total_timeout_seconds) is not int
        or not 1 <= total_timeout_seconds <= 1800
    ):
        raise ValueError("NEWOW_CONSUMER_AUDIT_SCOPE_INVALID")
    global_deadline = clock() + total_timeout_seconds
    results: dict[str, dict[str, object]] = {}
    for scope in scopes:
        scope_deadline = min(global_deadline, clock() + scope.timeout_seconds)
        cutoffs: dict[str, datetime] = {}
        unverified: list[str] = []
        for product in scope.products:
            if clock() >= scope_deadline:
                unverified.extend(item for item in scope.products if item not in cutoffs)
                break
            try:
                cutoffs[product] = resolve_cutoff(scope, product)
            except Exception:  # noqa: BLE001 - consumer receipt contains bounded status only
                unverified.append(product)
        revision = input_revision(scope)
        grouped: dict[datetime, list[str]] = {}
        for product, cutoff in cutoffs.items():
            grouped.setdefault(cutoff, []).append(product)
        parts: list[dict[str, object]] = []
        for cutoff, products in grouped.items():
            remaining = int(scope_deadline - clock())
            if remaining < 1:
                unverified.extend(products)
                continue
            report = build_report(scope, tuple(products), cutoff, remaining)
            parts.append(summarize_readiness(
                report,
                products=tuple(products),
                frequency=scope.frequency,
                cutoffs={product: cutoff.isoformat() for product in products},
                input_revision=revision,
            ))
        results[scope.key] = _merge_scope_parts(scope, parts, cutoffs, unverified, revision)
    return results


def _merge_scope_parts(
    scope: ConsumerAuditScope,
    parts: list[dict[str, object]],
    cutoffs: Mapping[str, datetime],
    unverified: list[str],
    revision: str,
) -> dict[str, object]:
    unique_unverified = list(dict.fromkeys(unverified))
    failures = [row for part in parts for row in part["failures"]]  # type: ignore[index]
    proposals = [row for part in parts for row in part["warmup_proposals"]]  # type: ignore[index]
    complete = (
        len(cutoffs) == len(scope.products)
        and not unique_unverified
        and all(part["status"] == "audited" for part in parts)
    )
    return {
        "status": "audited" if complete else "incomplete",
        "frequency": scope.frequency,
        "input_revision": revision,
        "product_cutoffs": [
            {"product": product, "as_of": cutoffs[product].isoformat()}
            for product in scope.products if product in cutoffs
        ],
        "unverified_products": unique_unverified,
        "case_count": sum(int(part["case_count"]) for part in parts),
        "main_ready_count": sum(int(part["main_ready_count"]) for part in parts),
        "reference_ready_count": sum(int(part["reference_ready_count"]) for part in parts),
        "auxiliary_ready_count": sum(int(part["auxiliary_ready_count"]) for part in parts),
        "budget_exhausted": bool(unique_unverified) or any(
            part["budget_exhausted"] is True for part in parts
        ),
        "failures": failures,
        "warmup_proposals": proposals,
    }


def summarize_readiness(
    report: Mapping[str, object], *, products: tuple[str, ...], frequency: str,
    cutoffs: Mapping[str, str], input_revision: str,
) -> dict[str, object]:
    """Reduce a native readiness result without turning WARMING into failure."""
    if (
        frequency not in {"1d", "1w"}
        or not products
        or set(cutoffs) != set(products)
        or _HASH.fullmatch(input_revision) is None
        or report.get("provider_requests") != 0
        or report.get("writes") != 0
    ):
        raise ValueError("NEWOW_CONSUMER_AUDIT_INVALID")
    raw_cases = report.get("cases")
    raw_repairs = report.get("repair_targets")
    if not isinstance(raw_cases, Sequence) or isinstance(raw_cases, (str, bytes)):
        raise ValueError("NEWOW_CONSUMER_AUDIT_INVALID")
    if not isinstance(raw_repairs, Sequence) or isinstance(raw_repairs, (str, bytes)):
        raise ValueError("NEWOW_CONSUMER_AUDIT_INVALID")

    cases = [
        case for case in raw_cases
        if isinstance(case, Mapping) and case.get("frequency") == frequency
        and case.get("symbol") in products
    ]
    expected_cases = len(products) * len(_STRATEGIES)
    failures: list[dict[str, str]] = []
    ready = {"chart": 0, "reference": 0, "auxiliary": 0}
    seen: set[tuple[str, str]] = set()
    invalid_products: set[str] = set()
    structurally_complete = len(cases) == expected_cases
    for case in cases:
        product, strategy = case.get("symbol"), case.get("strategy")
        sections = case.get("sections")
        if (
            not isinstance(product, str) or _PRODUCT.fullmatch(product) is None
            or strategy not in _STRATEGIES
            or not isinstance(sections, Mapping)
            or (product, str(strategy)) in seen
        ):
            structurally_complete = False
            if isinstance(product, str) and product in products:
                invalid_products.add(product)
            continue
        seen.add((product, str(strategy)))
        if set(sections) != _SECTIONS:
            structurally_complete = False
            invalid_products.add(product)
            continue
        for section, state in sections.items():
            if not isinstance(state, Mapping) or not isinstance(state.get("status"), str):
                structurally_complete = False
                invalid_products.add(product)
                continue
            status = state["status"]
            family = "auxiliary" if str(section).startswith("auxiliary:") else str(section)
            if status == "READY":
                ready[family] += 1
                continue
            if status in _LEGAL_NON_READY:
                continue
            reason = state.get("reason")
            failures.append({
                "product": product,
                "strategy": str(strategy),
                "section": str(section),
                "reason": reason if isinstance(reason, str) else status,
            })

    proposals = [_warmup_proposal(row) for row in raw_repairs]
    budget_exhausted = report.get("budget_exhausted") is True
    audited = (
        report.get("complete") is True
        and structurally_complete
        and not budget_exhausted
        and not failures
        and not proposals
    )
    return {
        "status": "audited" if audited else "incomplete",
        "frequency": frequency,
        "input_revision": input_revision,
        "product_cutoffs": [
            {"product": product, "as_of": cutoffs[product]} for product in products
        ],
        "unverified_products": [] if structurally_complete else [
            product for product in products
            if product in invalid_products
            or any((product, strategy) not in seen for strategy in _STRATEGIES)
        ],
        "case_count": len(cases),
        "main_ready_count": ready["chart"],
        "reference_ready_count": ready["reference"],
        "auxiliary_ready_count": ready["auxiliary"],
        "budget_exhausted": budget_exhausted,
        "failures": failures,
        "warmup_proposals": proposals,
    }


def _warmup_proposal(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("NEWOW_CONSUMER_AUDIT_INVALID")
    product, contract = value.get("symbol"), value.get("contract")
    frequency, through, status = (
        value.get("frequency"), value.get("through"), value.get("status")
    )
    plan_hash = value.get("plan_sha256")
    expected = value.get("expected_bar_count")
    requests = value.get("provider_request_count")
    if (
        not isinstance(product, str) or _PRODUCT.fullmatch(product) is None
        or not isinstance(contract, str) or _CONTRACT.fullmatch(contract) is None
        or frequency not in {"1d", "1w"}
        or not isinstance(through, str)
        or status not in {"PROPOSED", "REVIEW_REQUIRED"}
        or (plan_hash is not None and (
            not isinstance(plan_hash, str) or _HASH.fullmatch(plan_hash) is None
        ))
        or (expected is not None and (type(expected) is not int or expected < 0))
        or (requests is not None and (type(requests) is not int or requests < 0))
    ):
        raise ValueError("NEWOW_CONSUMER_AUDIT_INVALID")
    return {
        "product": product,
        "contract": contract,
        "frequency": frequency,
        "through": through,
        "status": status,
        "expected_bar_count": expected,
        "provider_request_count": requests,
        "plan_sha256": plan_hash,
    }
