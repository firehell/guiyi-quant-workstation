"""Read-only orchestration for Main Force Mirror diagnostic Phase A."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Protocol

from app.market_data.domain import (
    ActualDominantTradingDayQuery,
    BarFrequency,
    CanonicalBar,
    MarketSeriesResult,
    ResolvedContractSegment,
    SeriesKind,
    SeriesPageQuery,
)
from app.market_data.main_force_mirror_v2_service import (
    MainForceMirrorV2DiagnosticPageResult,
    MainForceMirrorV2Error,
    MainForceMirrorV2PageResult,
    MemberDatasetState,
    _contracts_for_bars,
)
from app.market_data.errors import InfrastructureError
from app.market_data.market_data_service import MarketDataError
from app.research.main_force.main_force_mirror_diagnostic import (
    MainForceMirrorDiagnosticAvailableProductRow,
    MainForceMirrorDiagnosticFunnelSection,
    MainForceMirrorDiagnosticLabelSection,
    MainForceMirrorDiagnosticProductRow,
    MainForceMirrorDiagnosticReport,
    MainForceMirrorDiagnosticSequenceSection,
    MainForceMirrorDiagnosticStatus,
    MainForceMirrorDiagnosticUnavailableProductRow,
    MainForceMirrorDiagnosticUnavailableReason,
    MainForceMirrorDiagnosticValidationMetadata,
)
from app.research.main_force.main_force_mirror_diagnostic_analysis import (
    MainForceMirrorDiagnosticLabelAuditResult,
    MainForceMirrorDiagnosticProductInput,
    audit_main_force_mirror_funnel,
    audit_main_force_mirror_labels,
    audit_main_force_mirror_sequences,
)
from app.research.main_force.main_force_mirror_diagnostic_models import (
    MainForceMirrorDiagnosticMemberObservation,
    audit_main_force_mirror_member_feasibility,
    build_main_force_mirror_fold_datasets,
    evaluate_main_force_mirror_diagnostic_gate,
    run_main_force_mirror_model_diagnostics,
)
from app.research.main_force.main_force_mirror_diagnostic_policy import (
    MainForceMirrorDiagnosticProtocol,
    MainForceMirrorDiagnosticRequest,
    load_main_force_mirror_diagnostic_protocol,
    require_exact_main_force_mirror_diagnostic_protocol,
)
from guiyi_quant.indicators.main_force_mirror_v2 import (
    MainForceMirrorV2AuditTraceItem,
    MainForceMirrorV2Point,
    compute_main_force_mirror_v2_with_audit,
)


class MainForceMirrorDiagnosticSourceError(RuntimeError):
    code = "MFM_DIAGNOSTIC_SOURCE_IDENTITY_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticNamedViewAvailable:
    status: MainForceMirrorDiagnosticStatus
    symbol: str
    since: date
    through: date
    label: MainForceMirrorDiagnosticLabelSection
    sequence: MainForceMirrorDiagnosticSequenceSection
    funnel: MainForceMirrorDiagnosticFunnelSection


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticNamedViewUnavailable:
    status: MainForceMirrorDiagnosticStatus
    symbol: str
    since: date
    through: date
    reason_code: MainForceMirrorDiagnosticUnavailableReason


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticResult:
    protocol: MainForceMirrorDiagnosticProtocol
    source_mode: str
    frequency: str
    confirmed_only: bool
    requested_active_since: date
    requested_active_through: date
    jm_view_since: date
    jm_view_through: date
    known_retrospective_through: date
    prospective_begins_after: date
    prospective_consumed: bool
    indicator_code: str
    indicator_version: str
    formal_policy_id: str
    parameters_hash: str
    jm_named_view: (
        MainForceMirrorDiagnosticNamedViewAvailable
        | MainForceMirrorDiagnosticNamedViewUnavailable
    )
    report: MainForceMirrorDiagnosticReport


class _MarketDataReader(Protocol):
    def query_actual_dominant_trading_days(
        self,
        request: ActualDominantTradingDayQuery,
    ) -> MarketSeriesResult: ...


class _DiagnosticPageReader(Protocol):
    def query_diagnostic_page(
        self,
        request: SeriesPageQuery,
    ) -> MainForceMirrorV2DiagnosticPageResult: ...


_ProtocolLoader = Callable[[], MainForceMirrorDiagnosticProtocol]
_PreviousTradingDay = Callable[[str, date], date]
_MARKET_SOURCE_UNAVAILABLE_CODES = frozenset(
    {
        "PRODUCT_RETIRED",
        "CONTRACT_METADATA_MISSING",
        "CONTRACT_ACTIVE_WINDOW_MISSING",
        "TRADING_CALENDAR_MISSING",
        "TRADING_SESSION_MISSING",
        "DATASET_OR_PARTITION_MISSING",
        "QUERY_WINDOW_EMPTY",
        "MAPPED_CONTRACT_DATASET_MISSING",
        "MAIN_CONTRACT_MAP_MISSING",
        "DOMINANT_CONTEXT_MISSING",
        "COMPLETE_WEEK_MISSING",
    }
)


class MainForceMirrorDiagnosticService:
    """Build one immutable diagnostic report through canonical read boundaries."""

    def __init__(
        self,
        *,
        market_data: _MarketDataReader,
        mirror_service: _DiagnosticPageReader,
        protocol_loader: _ProtocolLoader = load_main_force_mirror_diagnostic_protocol,
        previous_trading_day: _PreviousTradingDay | None = None,
    ) -> None:
        if not callable(
            getattr(market_data, "query_actual_dominant_trading_days", None)
        ) or not callable(getattr(mirror_service, "query_diagnostic_page", None)):
            raise TypeError("diagnostic readers must implement read-only contracts")
        self._market_data = market_data
        self._mirror_service = mirror_service
        self._protocol_loader = protocol_loader
        self._previous_trading_day = previous_trading_day

    def run(
        self,
        request: MainForceMirrorDiagnosticRequest,
    ) -> MainForceMirrorDiagnosticResult:
        if type(request) is not MainForceMirrorDiagnosticRequest:
            raise TypeError("request must be MainForceMirrorDiagnosticRequest")
        protocol = require_exact_main_force_mirror_diagnostic_protocol(
            self._protocol_loader()
        )
        if request.protocol_id != protocol.protocol_id:
            raise MainForceMirrorDiagnosticSourceError()
        canonical_v2_identity = _default_v2_identity()

        inputs: list[MainForceMirrorDiagnosticProductInput] = []
        product_rows: list[MainForceMirrorDiagnosticProductRow] = []
        member_states: dict[str, MemberDatasetState] = {}
        jm_input: MainForceMirrorDiagnosticProductInput | None = None
        for symbol in protocol.products:
            market_request = ActualDominantTradingDayQuery(
                symbol=symbol,
                frequency=BarFrequency.H1,
                since=protocol.active60_since,
                through=protocol.active60_through,
            )
            try:
                market = self._market_data.query_actual_dominant_trading_days(
                    market_request
                )
            except MarketDataError as exc:
                if str(exc) not in _MARKET_SOURCE_UNAVAILABLE_CODES:
                    raise MainForceMirrorDiagnosticSourceError() from None
                product_rows.append(_source_unavailable_row(symbol))
                continue
            bars, contracts = _validate_market_result(
                market,
                market_request,
            )
            page_identity, points, trace, member_state = self._query_product_pages(
                symbol=symbol,
                bars=bars,
                contracts=contracts,
                expected_identity=canonical_v2_identity,
            )
            current_identity = (
                page_identity["indicator_code"],
                page_identity["indicator_version"],
                page_identity["formal_policy_id"],
                page_identity["parameters_hash"],
            )
            if current_identity != canonical_v2_identity:
                raise MainForceMirrorDiagnosticSourceError()
            product_input = MainForceMirrorDiagnosticProductInput(
                symbol=symbol,
                bars=bars,
                points=points,
                trace=trace,
            )
            inputs.append(product_input)
            if symbol == "jm":
                jm_input = product_input
            member_states[symbol] = member_state
            product_rows.append(
                MainForceMirrorDiagnosticAvailableProductRow(
                    symbol=symbol,
                    status=MainForceMirrorDiagnosticStatus.AVAILABLE,
                    observed_since=bars[0].trading_day,
                    observed_through=bars[-1].trading_day,
                    confirmed_bar_count=len(bars),
                    physical_contract_count=len(set(contracts)),
                )
            )

        product_inputs = tuple(inputs)
        labels = audit_main_force_mirror_labels(product_inputs)
        sequence = audit_main_force_mirror_sequences(product_inputs)
        funnel = audit_main_force_mirror_funnel(product_inputs, labels)
        balanced_facts = tuple(
            item for item in sequence.fact_sets if item.profile_id == "balanced"
        )
        datasets = build_main_force_mirror_fold_datasets(
            product_inputs,
            labels,
            balanced_facts,
        )
        model = run_main_force_mirror_model_diagnostics(datasets)
        member = audit_main_force_mirror_member_feasibility(
            self._member_observations(labels, member_states)
        )
        jm_named_view = _build_jm_named_view(protocol, jm_input)
        unavailable_count = sum(
            type(row) is MainForceMirrorDiagnosticUnavailableProductRow
            for row in product_rows
        )
        validation = MainForceMirrorDiagnosticValidationMetadata(
            source_mode=protocol.source_mode,
            frequency=protocol.frequency,
            confirmed_only=protocol.confirmed_only,
            active_universe_sha256=protocol.active_universe_sha256,
            known_retrospective_through=protocol.known_retrospective_through,
            prospective_consumed=protocol.prospective_consumed,
            available_product_count=len(product_rows) - unavailable_count,
            unavailable_product_count=unavailable_count,
            unknown_failure_count=0,
        )
        decision = evaluate_main_force_mirror_diagnostic_gate(
            protocol,
            validation,
            labels.section,
            sequence.section,
            model.section,
            member.section,
        )
        flags: list[str] = []
        if unavailable_count:
            flags.append("SOURCE_UNAVAILABLE_PRESENT")
        if labels.unavailable_products:
            flags.append("LABEL_BARRIER_INVALID_PRESENT")
        if datasets.unavailable_episodes:
            flags.append("FEATURE_UNAVAILABLE_PRESENT")
        if member.unavailable:
            flags.append("MEMBER_UNAVAILABLE_PRESENT")
        report = MainForceMirrorDiagnosticReport(
            schema_version=protocol.schema_version,
            protocol_id=protocol.protocol_id,
            model_subprotocol=protocol.model_subprotocol,
            research_only=protocol.research_only,
            readonly=protocol.readonly,
            validation=validation,
            product_rows=tuple(product_rows),
            label=labels.section,
            sequence=sequence.section,
            funnel=funnel,
            model=model.section,
            member=member.section,
            quality_flags=tuple(flags),
            gate=decision.gate,
            gate_reasons=decision.reasons,
        )
        return MainForceMirrorDiagnosticResult(
            protocol=protocol,
            source_mode=protocol.source_mode,
            frequency=protocol.frequency,
            confirmed_only=protocol.confirmed_only,
            requested_active_since=protocol.active60_since,
            requested_active_through=protocol.active60_through,
            jm_view_since=protocol.jm_since,
            jm_view_through=protocol.jm_through,
            known_retrospective_through=protocol.known_retrospective_through,
            prospective_begins_after=protocol.prospective_begins_after,
            prospective_consumed=protocol.prospective_consumed,
            indicator_code=canonical_v2_identity[0],
            indicator_version=canonical_v2_identity[1],
            formal_policy_id=canonical_v2_identity[2],
            parameters_hash=canonical_v2_identity[3],
            jm_named_view=jm_named_view,
            report=report,
        )

    def _query_product_pages(
        self,
        *,
        symbol: str,
        bars: tuple[CanonicalBar, ...],
        contracts: tuple[str, ...],
        expected_identity: tuple[str, str, str, str],
    ) -> tuple[
        Mapping[str, str],
        tuple[MainForceMirrorV2Point, ...],
        tuple[MainForceMirrorV2AuditTraceItem, ...],
        MemberDatasetState,
    ]:
        wanted = {bar.bar_end for bar in bars}
        points_by_end: dict[datetime, MainForceMirrorV2Point] = {}
        trace_by_end: dict[datetime, MainForceMirrorV2AuditTraceItem] = {}
        before = bars[-1].bar_end + timedelta(microseconds=1)
        identity: dict[str, str] | None = None
        member_state: MemberDatasetState | None = None
        while True:
            page_request = SeriesPageQuery(
                series_kind=SeriesKind.ACTUAL_DOMINANT,
                symbol=symbol,
                contract=None,
                frequency=BarFrequency.H1,
                before=before,
                limit=2000,
            )
            try:
                diagnostic = self._mirror_service.query_diagnostic_page(page_request)
            except MainForceMirrorV2Error:
                raise MainForceMirrorDiagnosticSourceError() from None
            page = diagnostic.page
            if (
                dict(page.request_identity) != _page_request_identity(page_request)
                or len(page.points) != len(diagnostic.audit_trace)
            ):
                raise MainForceMirrorDiagnosticSourceError()
            _validate_page_cursor(page, page_request)
            current_identity = {
                "indicator_code": page.indicator_code,
                "indicator_version": page.indicator_version,
                "formal_policy_id": page.formal_policy_id,
                "parameters_hash": page.parameters_hash,
            }
            if tuple(current_identity.values()) != expected_identity:
                raise MainForceMirrorDiagnosticSourceError()
            if identity is None:
                identity = current_identity
                member_state = page.member_dataset
            elif identity != current_identity or page.member_dataset != member_state:
                raise MainForceMirrorDiagnosticSourceError()
            try:
                page_contracts = _contracts_for_bars(
                    page.points,  # type: ignore[arg-type]
                    page.resolved_contract_segments,
                )
            except MainForceMirrorV2Error:
                raise MainForceMirrorDiagnosticSourceError() from None
            for point, audit_item, contract in zip(
                page.points,
                diagnostic.audit_trace,
                page_contracts,
                strict=True,
            ):
                if (
                    point.bar_end != audit_item.bar_end
                    or point.trading_day != audit_item.trading_day
                    or point.physical_contract != audit_item.physical_contract
                    or point.physical_contract != contract
                    or point.bar_end in points_by_end
                    or audit_item.bar_end in trace_by_end
                ):
                    raise MainForceMirrorDiagnosticSourceError()
                if point.bar_end in wanted:
                    points_by_end[point.bar_end] = point
                    trace_by_end[audit_item.bar_end] = audit_item
            if len(points_by_end) == len(wanted):
                break
            if not page.has_more_before or page.next_before is None:
                raise MainForceMirrorDiagnosticSourceError()
            if page.next_before >= before:
                raise MainForceMirrorDiagnosticSourceError()
            before = page.next_before
        if identity is None or member_state is None:
            raise MainForceMirrorDiagnosticSourceError()
        points = tuple(points_by_end[bar.bar_end] for bar in bars)
        trace = tuple(trace_by_end[bar.bar_end] for bar in bars)
        for bar, point, audit_item, contract in zip(
            bars,
            points,
            trace,
            contracts,
            strict=True,
        ):
            if (
                bar.bar_end != point.bar_end
                or bar.trading_day != point.trading_day
                or point.physical_contract != contract
                or audit_item.physical_contract != contract
            ):
                raise MainForceMirrorDiagnosticSourceError()
        return identity, points, trace, member_state

    def _member_observations(
        self,
        labels: MainForceMirrorDiagnosticLabelAuditResult,
        member_states: Mapping[str, MemberDatasetState],
    ) -> tuple[MainForceMirrorDiagnosticMemberObservation, ...]:
        observations: list[MainForceMirrorDiagnosticMemberObservation] = []
        if self._previous_trading_day is None:
            return ()
        products = {item.symbol: item for item in labels.inputs}
        for episode in labels.episodes:
            if not episode.kept:
                continue
            product = products[episode.symbol]
            point = product.points[episode.anchor_index]
            state = member_states[episode.symbol]
            try:
                expected_day = self._previous_trading_day(
                    episode.symbol,
                    episode.anchor_trading_day,
                )
            except InfrastructureError as exc:
                if exc.code != "COMPLETE_TRADING_DAY_MISSING":
                    raise MainForceMirrorDiagnosticSourceError() from None
                expected_day = None
            member = point.member
            ready = (
                state.status == "ready"
                and state.dataset_id is not None
                and state.admitted_product
                and member is not None
                and member.status == "ready"
            )
            observations.append(
                MainForceMirrorDiagnosticMemberObservation(
                    symbol=episode.symbol,
                    physical_contract=episode.physical_contract,
                    anchor_trading_day=episode.anchor_trading_day,
                    anchor_bar_end=point.bar_end,
                    expected_prior_trading_day=expected_day,
                    expected_dataset_id=state.dataset_id or "MEMBER_DATASET_UNAVAILABLE",
                    available=ready,
                    observed_dataset_id=state.dataset_id if ready else None,
                    observed_trade_date=(
                        member.member_trade_date if ready and member is not None else None
                    ),
                    observed_symbol=episode.symbol if ready else None,
                    observed_physical_contract=(
                        episode.physical_contract if ready else None
                    ),
                    observed_rank=1 if ready else None,
                )
            )
        return tuple(observations)


def _build_jm_named_view(
    protocol: MainForceMirrorDiagnosticProtocol,
    product: MainForceMirrorDiagnosticProductInput | None,
) -> (
    MainForceMirrorDiagnosticNamedViewAvailable
    | MainForceMirrorDiagnosticNamedViewUnavailable
):
    if product is None or not any(
        protocol.jm_since <= bar.trading_day <= protocol.jm_through
        for bar in product.bars
    ):
        return MainForceMirrorDiagnosticNamedViewUnavailable(
            status=MainForceMirrorDiagnosticStatus.UNAVAILABLE,
            symbol="jm",
            since=protocol.jm_since,
            through=protocol.jm_through,
            reason_code=(
                MainForceMirrorDiagnosticUnavailableReason.MARKET_SOURCE_UNAVAILABLE
            ),
        )
    scope = (protocol.jm_since, protocol.jm_through)
    products = (product,)
    labels = audit_main_force_mirror_labels(
        products,
        trading_day_scope=scope,
    )
    sequence = audit_main_force_mirror_sequences(
        products,
        trading_day_scope=scope,
    )
    funnel = audit_main_force_mirror_funnel(
        products,
        labels,
        trading_day_scope=scope,
    )
    return MainForceMirrorDiagnosticNamedViewAvailable(
        status=MainForceMirrorDiagnosticStatus.AVAILABLE,
        symbol="jm",
        since=protocol.jm_since,
        through=protocol.jm_through,
        label=labels.section,
        sequence=sequence.section,
        funnel=funnel,
    )


def _validate_market_result(
    result: MarketSeriesResult,
    request: ActualDominantTradingDayQuery,
) -> tuple[tuple[CanonicalBar, ...], tuple[str, ...]]:
    identity = result.request_identity
    if type(identity) is not dict or set(identity) != {
        "series_kind",
        "symbol",
        "contract",
        "frequency",
        "start",
        "end",
    }:
        raise MainForceMirrorDiagnosticSourceError()
    if (
        identity["series_kind"] != SeriesKind.ACTUAL_DOMINANT.value
        or identity["symbol"] != request.symbol
        or identity["contract"] is not None
        or identity["frequency"] != request.frequency.value
        or type(identity["start"]) is not str
        or type(identity["end"]) is not str
    ):
        raise MainForceMirrorDiagnosticSourceError()
    try:
        start = datetime.fromisoformat(identity["start"])
        end = datetime.fromisoformat(identity["end"])
    except ValueError:
        raise MainForceMirrorDiagnosticSourceError() from None
    if (
        start.tzinfo is None
        or start.utcoffset() is None
        or end.tzinfo is None
        or end.utcoffset() is None
        or start >= end
    ):
        raise MainForceMirrorDiagnosticSourceError()
    bars = result.bars
    if (
        type(bars) is not tuple
        or not bars
        or any(type(bar) is not CanonicalBar for bar in bars)
        or any(
            previous.bar_end >= current.bar_end
            for previous, current in zip(bars, bars[1:])
        )
        or any(
            not request.since <= bar.trading_day <= request.through
            or not start < bar.bar_end <= end
            for bar in bars
        )
        or type(result.coverage) is not tuple
        or result.coverage != (bars[0].bar_end, bars[-1].bar_end)
        or type(result.resolved_contract_segments) is not tuple
        or any(
            type(segment) is not ResolvedContractSegment
            for segment in result.resolved_contract_segments
        )
    ):
        raise MainForceMirrorDiagnosticSourceError()
    try:
        contracts = _contracts_for_bars(
            bars,
            result.resolved_contract_segments,
        )
    except (MainForceMirrorV2Error, AttributeError, TypeError):
        raise MainForceMirrorDiagnosticSourceError() from None
    return bars, contracts


def _validate_page_cursor(
    page: MainForceMirrorV2PageResult,
    request: SeriesPageQuery,
) -> None:
    points = page.points
    before = request.before
    if (
        type(points) is not tuple
        or not points
        or any(type(point) is not MainForceMirrorV2Point for point in points)
        or any(
            previous.bar_end >= current.bar_end
            for previous, current in zip(points, points[1:])
        )
        or before is None
        or any(point.bar_end >= before for point in points)
        or type(page.has_more_before) is not bool
        or page.has_more_before is not (page.next_before is not None)
        or (
            page.has_more_before
            and (
                page.next_before != points[0].bar_end
                or page.next_before >= before  # type: ignore[operator]
            )
        )
    ):
        raise MainForceMirrorDiagnosticSourceError()


def _source_unavailable_row(
    symbol: str,
) -> MainForceMirrorDiagnosticUnavailableProductRow:
    return MainForceMirrorDiagnosticUnavailableProductRow(
        symbol=symbol,
        status=MainForceMirrorDiagnosticStatus.UNAVAILABLE,
        reason_code=MainForceMirrorDiagnosticUnavailableReason.MARKET_SOURCE_UNAVAILABLE,
    )


def _page_request_identity(request: SeriesPageQuery) -> dict[str, object]:
    return {
        "series_kind": request.series_kind.value,
        "symbol": request.symbol,
        "contract": request.contract,
        "frequency": request.frequency.value,
        "before": request.before.isoformat() if request.before else None,
        "limit": request.limit,
    }


def _default_v2_identity() -> tuple[str, str, str, str]:
    computed = compute_main_force_mirror_v2_with_audit(
        bar_end=(),
        trading_day=(),
        physical_contract=(),
        open_=(),
        high=(),
        low=(),
        close=(),
        volume=(),
        open_interest=(),
    ).result
    return (
        computed.indicator_code,
        computed.indicator_version,
        computed.formal_policy_id,
        computed.parameters_hash,
    )
