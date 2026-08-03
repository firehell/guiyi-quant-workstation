from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable, Mapping, Sequence

from app.data_core.contracts import BAR_FREQUENCY_VALUES


V1_AUDIT_END = date(2026, 7, 10)
V1_TIMEZONE = "Asia/Shanghai"

DIRECT_PERIODS = frozenset({"1m", "1d", "1w"})
DERIVED_FROM_1M_PERIODS = frozenset({"5m", "15m", "30m", "60m", "1d"})
ACTUAL_REQUIRED_PERIODS = frozenset(BAR_FREQUENCY_VALUES)
FROZEN_REPORT_IDS = frozenset({14})

PROVIDER_EARLIEST_EVIDENCE_PRIORITY = (
    "provider_earliest_snapshot",
    "complete_provider_raw_response",
    "canonical_manifest",
    "database_metadata",
    "listing_metadata",
)
AUTHORITATIVE_PROVIDER_EVIDENCE_KINDS = frozenset(PROVIDER_EARLIEST_EVIDENCE_PRIORITY[:2])


@dataclass(frozen=True)
class ProviderEarliestEvidence:
    period: str
    first_valid_bar: date
    source_kind: str
    source_ref: str
    provider: str
    data_version: str
    captured_at: datetime | None
    checksum: str
    authoritative: bool
    completed: bool = True


@dataclass(frozen=True)
class ExpectedWindow:
    product: str
    contract: str
    contract_role: str
    period: str
    expected_start: date | None
    expected_end: date | None
    start_reason: str
    end_reason: str
    source_role: str
    resolution_status: str


@dataclass(frozen=True)
class ActualRank1Range:
    product: str
    contract: str
    start: date
    end: date | None


@dataclass(frozen=True)
class ActualTarget:
    product: str
    contract: str
    contract_role: str
    period: str
    expected_start: date
    expected_end: date
    target_reason: str


@dataclass(frozen=True)
class FiveLayerState:
    physical_coverage: str
    registration: str
    quality: str
    reference_metadata: str
    profile_eligibility: str


@dataclass(frozen=True)
class ConsumerDecision:
    consumer: str
    allowed: bool
    mode: str
    warning_visible: bool
    block_reasons: tuple[str, ...]


def resolve_expected_window(
    *,
    product: str,
    contract: str,
    contract_role: str,
    period: str,
    listed_semantic_start: date,
    provider_evidence: ProviderEarliestEvidence | None = None,
    audit_end: date = V1_AUDIT_END,
    last_completed_trading_day: date | None = None,
    last_completed_week: date | None = None,
    source_1m_window: ExpectedWindow | None = None,
    source_1m_quality: str = "",
    source_interval: str = "",
) -> ExpectedWindow:
    normalized_period = period.strip().lower()
    if normalized_period in DERIVED_FROM_1M_PERIODS and (
        normalized_period != "1d" or source_1m_window is not None or source_interval
    ):
        return _resolve_derived_window(
            product=product,
            contract=contract,
            contract_role=contract_role,
            period=normalized_period,
            source_1m_window=source_1m_window,
            source_1m_quality=source_1m_quality,
            source_interval=source_interval,
        )

    if normalized_period not in DIRECT_PERIODS:
        return _unresolved_window(
            product=product,
            contract=contract,
            contract_role=contract_role,
            period=normalized_period,
            source_role="unsupported",
            resolution_status="unsupported_period",
        )

    if (
        provider_evidence is None
        or provider_evidence.period.strip().lower() != normalized_period
        or not provider_evidence.authoritative
        or provider_evidence.source_kind not in AUTHORITATIVE_PROVIDER_EVIDENCE_KINDS
        or normalized_period in {"1d", "1w"} and not provider_evidence.completed
    ):
        return _unresolved_window(
            product=product,
            contract=contract,
            contract_role=contract_role,
            period=normalized_period,
            source_role="direct",
            resolution_status="expected_start_unresolved",
        )

    expected_start = max(listed_semantic_start, provider_evidence.first_valid_bar)
    completed_end = last_completed_week if normalized_period == "1w" else last_completed_trading_day
    if completed_end is None:
        return ExpectedWindow(
            product=product,
            contract=contract,
            contract_role=contract_role,
            period=normalized_period,
            expected_start=expected_start,
            expected_end=None,
            start_reason="max_listed_semantic_and_provider_first_valid_bar",
            end_reason="completed_end_unresolved",
            source_role="direct",
            resolution_status="expected_end_unresolved",
        )

    expected_end = min(completed_end, audit_end)
    if expected_start > expected_end:
        return ExpectedWindow(
            product=product,
            contract=contract,
            contract_role=contract_role,
            period=normalized_period,
            expected_start=expected_start,
            expected_end=expected_end,
            start_reason="max_listed_semantic_and_provider_first_valid_bar",
            end_reason="min_completed_end_and_audit_end",
            source_role="direct",
            resolution_status="invalid_window",
        )

    return ExpectedWindow(
        product=product,
        contract=contract,
        contract_role=contract_role,
        period=normalized_period,
        expected_start=expected_start,
        expected_end=expected_end,
        start_reason="max_listed_semantic_and_provider_first_valid_bar",
        end_reason="last_completed_week_at_or_before_audit_end"
        if normalized_period == "1w"
        else "last_completed_trading_day_at_or_before_audit_end",
        source_role="direct",
        resolution_status="resolved",
    )


def resolve_first_completed_week(
    *,
    listed_semantic_start: date,
    provider_first_weekly_bar: date,
    trading_days: Sequence[date],
    closed_through: date,
    provider_authoritative: bool,
    calendar_complete: bool,
) -> date | None:
    if not provider_authoritative or not calendar_complete or not trading_days:
        return None
    if provider_first_weekly_bar < listed_semantic_start:
        return None

    provider_iso = provider_first_weekly_bar.isocalendar()
    provider_week_days = sorted(
        day
        for day in set(trading_days)
        if (day.isocalendar().year, day.isocalendar().week) == (provider_iso.year, provider_iso.week)
    )
    if not provider_week_days:
        return None
    week_end = provider_week_days[-1]
    if provider_first_weekly_bar != week_end or closed_through < week_end:
        return None
    return provider_first_weekly_bar


def build_actual_rank1_targets(
    rank1_ranges: Iterable[ActualRank1Range],
    *,
    audit_end: date = V1_AUDIT_END,
    supported_starts: Mapping[tuple[str, str], date] | None = None,
) -> tuple[ActualTarget, ...]:
    targets: dict[tuple[str, str, str, date, date], ActualTarget] = {}
    for item in rank1_ranges:
        expected_end = min(item.end or audit_end, audit_end)
        for period in sorted(ACTUAL_REQUIRED_PERIODS):
            product = item.product.lower()
            supported_start = (supported_starts or {}).get((product, period))
            expected_start = max(item.start, supported_start) if supported_start else item.start
            if expected_start > expected_end:
                continue
            key = (product, item.contract, period, expected_start, expected_end)
            targets[key] = ActualTarget(
                product=product,
                contract=item.contract,
                contract_role="actual_contract",
                period=period,
                expected_start=expected_start,
                expected_end=expected_end,
                target_reason="main_contract_map_rank1_effective_range",
            )
    return tuple(targets[key] for key in sorted(targets))


def evaluate_profile_eligibility(
    *,
    physical_coverage: str,
    registration: str,
    quality: str,
    reference_metadata: str,
    identity_in_profile: bool,
    quality_policy: str,
    bar_status: str,
) -> FiveLayerState:
    quality_allowed = quality == "passed" or quality_policy == "active_entry" and quality == "warning"
    eligible = all(
        (
            physical_coverage == "covered",
            registration == "registered",
            quality_allowed,
            reference_metadata in {"passed", "not_applicable"},
            identity_in_profile,
            bar_status == "confirmed",
        )
    )
    return FiveLayerState(
        physical_coverage=physical_coverage,
        registration=registration,
        quality=quality,
        reference_metadata=reference_metadata,
        profile_eligibility="eligible" if eligible else "blocked",
    )


def resolve_consumer_decision(
    consumer: str,
    state: FiveLayerState,
    *,
    bar_status: str,
    allow_warning_quality: bool = False,
) -> ConsumerDecision:
    normalized = consumer.strip().lower()
    canonical_name = {
        "market": "Market",
        "backtest": "Backtest",
        "signal": "Signal",
        "review": "Review",
    }.get(normalized)
    if canonical_name is None:
        raise ValueError(f"unsupported consumer: {consumer}")

    reasons: list[str] = []
    if state.physical_coverage != "covered":
        reasons.append("physical_coverage_not_covered")
    if state.registration != "registered":
        reasons.append("registration_not_registered")
    if state.reference_metadata not in {"passed", "not_applicable"}:
        reasons.append("reference_metadata_not_eligible")
    if state.profile_eligibility != "eligible":
        reasons.append("profile_not_eligible")
    if bar_status != "confirmed":
        reasons.append("bar_not_confirmed")
    if state.quality in {"failed", "unchecked"}:
        reasons.append(f"quality_{state.quality}")

    warning_visible = state.quality == "warning"
    mode = "formal"
    if not reasons and state.quality == "warning":
        if canonical_name == "Market":
            mode = "formal_warning"
        elif canonical_name == "Backtest" and allow_warning_quality:
            mode = "research_warning_opt_in"
        elif canonical_name == "Review":
            mode = "display_only"
        else:
            reasons.append("warning_quality_blocked")
    elif not reasons and state.quality != "passed":
        reasons.append("quality_not_passed")

    return ConsumerDecision(
        consumer=canonical_name,
        allowed=not reasons,
        mode=mode if not reasons else "blocked",
        warning_visible=warning_visible,
        block_reasons=tuple(reasons),
    )


def report_mutation_allowed(report_id: int) -> bool:
    return report_id not in FROZEN_REPORT_IDS


def _resolve_derived_window(
    *,
    product: str,
    contract: str,
    contract_role: str,
    period: str,
    source_1m_window: ExpectedWindow | None,
    source_1m_quality: str,
    source_interval: str,
) -> ExpectedWindow:
    if source_interval.strip().lower() != "1m":
        status = "invalid_source_interval"
    elif source_1m_quality != "passed":
        status = "source_1m_not_passed"
    elif source_1m_window is None or source_1m_window.period != "1m" or source_1m_window.resolution_status != "resolved":
        status = "source_1m_window_unresolved"
    else:
        return ExpectedWindow(
            product=product,
            contract=contract,
            contract_role=contract_role,
            period=period,
            expected_start=source_1m_window.expected_start,
            expected_end=source_1m_window.expected_end,
            start_reason="inherited_from_passed_1m",
            end_reason="inherited_from_passed_1m",
            source_role="derived_from_1m",
            resolution_status="resolved",
        )
    return _unresolved_window(
        product=product,
        contract=contract,
        contract_role=contract_role,
        period=period,
        source_role="derived_from_1m",
        resolution_status=status,
    )


def _unresolved_window(
    *,
    product: str,
    contract: str,
    contract_role: str,
    period: str,
    source_role: str,
    resolution_status: str,
) -> ExpectedWindow:
    return ExpectedWindow(
        product=product,
        contract=contract,
        contract_role=contract_role,
        period=period,
        expected_start=None,
        expected_end=None,
        start_reason=resolution_status,
        end_reason="unresolved",
        source_role=source_role,
        resolution_status=resolution_status,
    )


__all__ = [
    "ACTUAL_REQUIRED_PERIODS",
    "AUTHORITATIVE_PROVIDER_EVIDENCE_KINDS",
    "DERIVED_FROM_1M_PERIODS",
    "DIRECT_PERIODS",
    "FROZEN_REPORT_IDS",
    "PROVIDER_EARLIEST_EVIDENCE_PRIORITY",
    "V1_AUDIT_END",
    "V1_TIMEZONE",
    "ActualRank1Range",
    "ActualTarget",
    "ConsumerDecision",
    "ExpectedWindow",
    "FiveLayerState",
    "ProviderEarliestEvidence",
    "build_actual_rank1_targets",
    "evaluate_profile_eligibility",
    "report_mutation_allowed",
    "resolve_consumer_decision",
    "resolve_expected_window",
    "resolve_first_completed_week",
]
