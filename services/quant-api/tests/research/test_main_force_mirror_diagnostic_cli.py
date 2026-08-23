from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
import importlib
import io
import json

import pytest

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
    MainForceMirrorV2PageResult,
    MemberDatasetState,
)
from app.market_data.errors import InfrastructureError
from app.market_data.market_data_service import MarketDataError
from app.research.main_force.main_force_mirror_diagnostic import (
    MainForceMirrorDiagnosticGate,
    MainForceMirrorDiagnosticSide,
    MainForceMirrorDiagnosticStatus,
    MainForceMirrorDiagnosticUnavailableProductRow,
    MainForceMirrorDiagnosticUnavailableReason,
)
from app.research.main_force.main_force_mirror_diagnostic_analysis import (
    MainForceMirrorDiagnosticLabelEpisode,
    MainForceMirrorDiagnosticLegacyOutcome,
    MainForceMirrorDiagnosticProductInput,
    audit_main_force_mirror_labels,
)
from app.research.main_force.main_force_mirror_diagnostic_models import (
    audit_main_force_mirror_member_feasibility,
)
from app.guiyi_cli.data_parser import CliUsageError
from app.guiyi_cli.main import build_parser
from app.guiyi_cli.main import main
from app.guiyi_cli import research_payloads
from app.guiyi_cli.research_commands import run_research_command
from app.guiyi_cli.research_requests import build_research_request
from app.research.main_force.main_force_mirror_diagnostic_policy import (
    MainForceMirrorDiagnosticProtocolError,
    MainForceMirrorDiagnosticRequest,
)
from guiyi_quant.indicators.main_force_mirror_v2 import (
    compute_main_force_mirror_v2_with_audit,
)


PROTOCOL_ID = "main_force_mirror_diagnostic_phase_a_v1"


def _arguments() -> list[str]:
    return [
        "research",
        "main-force-mirror-diagnostic",
        "--protocol",
        PROTOCOL_ID,
    ]


def test_diagnostic_parser_builds_the_only_public_request() -> None:
    args = build_parser().parse_args(_arguments())

    assert build_research_request(args) == MainForceMirrorDiagnosticRequest(
        protocol_id=PROTOCOL_ID
    )


@pytest.mark.parametrize(
    "override",
    (
        ("--symbol", "jm"),
        ("--since", "2023-01-01"),
        ("--through", "2026-08-18"),
        ("--frequency", "60m"),
        ("--threshold", "70"),
        ("--model", "ridge"),
        ("--output", "report.json"),
        ("--member-dataset", "alternate"),
    ),
)
def test_diagnostic_parser_rejects_every_override(
    override: tuple[str, str],
) -> None:
    with pytest.raises(CliUsageError):
        build_parser().parse_args([*_arguments(), *override])


def test_diagnostic_parser_requires_the_exact_protocol() -> None:
    with pytest.raises(CliUsageError):
        build_parser().parse_args(_arguments()[:-2])
    with pytest.raises(CliUsageError):
        build_parser().parse_args(
            [*_arguments()[:-1], "main_force_mirror_diagnostic_phase_a_v2"]
        )


def _service_module():
    return importlib.import_module(
        "app.research.main_force.main_force_mirror_diagnostic_service"
    )


def _bar() -> CanonicalBar:
    return CanonicalBar(
        bar_end=datetime(2026, 3, 10, 1, tzinfo=UTC),
        trading_day=date(2026, 3, 10),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
        volume=Decimal("10"),
        turnover=None,
        open_interest=Decimal("1000"),
    )


class _MarketData:
    def __init__(
        self,
        *,
        unavailable_symbol: str | None = None,
        unknown_symbol: str | None = None,
    ) -> None:
        self.unavailable_symbol = unavailable_symbol
        self.unknown_symbol = unknown_symbol
        self.calls: list[ActualDominantTradingDayQuery] = []

    def query_actual_dominant_trading_days(
        self,
        request: ActualDominantTradingDayQuery,
    ) -> MarketSeriesResult:
        self.calls.append(request)
        if request.symbol == self.unknown_symbol:
            raise RuntimeError("provider secret detail")
        if request.symbol == self.unavailable_symbol:
            raise MarketDataError("TRADING_SESSION_MISSING")
        contract = f"{request.symbol.upper()}2609"
        bar = _bar()
        return MarketSeriesResult(
            request_identity={
                "series_kind": "actual_dominant",
                "symbol": request.symbol,
                "contract": None,
                "frequency": "60m",
                "start": "2022-12-31T20:00:00+00:00",
                "end": "2026-08-18T08:00:00+00:00",
            },
            bars=(bar,),
            coverage=(bar.bar_end, bar.bar_end),
            resolved_contract_segments=(
                ResolvedContractSegment(
                    contract=contract,
                    start_trading_day=bar.trading_day,
                    end_trading_day=bar.trading_day,
                ),
            ),
        )


class _MirrorService:
    def __init__(self, *, drift: str | None = None) -> None:
        self.drift = drift
        self.calls: list[SeriesPageQuery] = []

    def query_diagnostic_page(
        self,
        request: SeriesPageQuery,
    ) -> MainForceMirrorV2DiagnosticPageResult:
        self.calls.append(request)
        contract = f"{request.symbol.upper()}2609"
        bar = _bar()
        computed = compute_main_force_mirror_v2_with_audit(
            bar_end=(bar.bar_end,),
            trading_day=(bar.trading_day,),
            physical_contract=(contract,),
            open_=(float(bar.open),),
            high=(float(bar.high),),
            low=(float(bar.low),),
            close=(float(bar.close),),
            volume=(float(bar.volume),),
            open_interest=(float(bar.open_interest),),
        )
        identity = {
            "series_kind": request.series_kind.value,
            "symbol": request.symbol,
            "contract": request.contract,
            "frequency": request.frequency.value,
            "before": request.before.isoformat() if request.before else None,
            "limit": request.limit,
        }
        if self.drift == "request_identity":
            identity["symbol"] = "ag"
        point = computed.result.points[0]
        if self.drift == "point_contract":
            point = replace(point, physical_contract="ZZ2609")
        points = (point,)
        trace = computed.trace
        has_more_before = False
        next_before = None
        if self.drift in {"coverage", "cursor"}:
            points = ()
            trace = ()
            has_more_before = self.drift == "cursor"
            next_before = request.before if self.drift == "cursor" else None
        parameters_hash = computed.result.parameters_hash
        if self.drift == "cross_product" and request.symbol == "ag":
            parameters_hash = "drifted-parameters"
        indicator_version = computed.result.indicator_version
        if self.drift == "wrong_v3":
            indicator_version = "3"
        if self.drift == "terminal_next_without_more":
            next_before = point.bar_end
        elif self.drift == "terminal_more_without_next":
            has_more_before = True
            next_before = None
        elif self.drift == "terminal_wrong_next":
            has_more_before = True
            next_before = point.bar_end - timedelta(microseconds=1)
        elif self.drift == "point_not_before":
            shifted = replace(point, bar_end=request.before)
            points = (point, shifted)
            trace = (trace[0], replace(trace[0], bar_end=request.before))
        elif self.drift == "descending_page":
            older = replace(
                point,
                bar_end=point.bar_end - timedelta(hours=1),
            )
            points = (point, older)
            trace = (
                trace[0],
                replace(trace[0], bar_end=older.bar_end),
            )
        return MainForceMirrorV2DiagnosticPageResult(
            page=MainForceMirrorV2PageResult(
                request_identity=identity,
                indicator_code=computed.result.indicator_code,
                indicator_version=indicator_version,
                formal_policy_id=computed.result.formal_policy_id,
                parameters_hash=parameters_hash,
                points=points,
                member_dataset=MemberDatasetState(
                    "unavailable", None, None, False, None
                ),
                has_more_before=has_more_before,
                next_before=next_before,
                resolved_contract_segments=(
                    ResolvedContractSegment(
                        contract=contract,
                        start_trading_day=bar.trading_day,
                        end_trading_day=bar.trading_day,
                    ),
                ),
            ),
            audit_trace=trace,
        )


def _service(market_data: _MarketData, mirror: _MirrorService):
    module = _service_module()
    return module.MainForceMirrorDiagnosticService(
        market_data=market_data,
        mirror_service=mirror,
    )


def test_diagnostic_service_keeps_frozen_order_and_types_known_source_failure() -> None:
    market_data = _MarketData(unavailable_symbol="ao")
    mirror = _MirrorService()

    result = _service(market_data, mirror).run(
        MainForceMirrorDiagnosticRequest(PROTOCOL_ID)
    )

    assert len(result.report.product_rows) == 60
    assert tuple(row.symbol for row in result.report.product_rows) == tuple(
        request.symbol for request in market_data.calls
    )
    unavailable = result.report.product_rows[3]
    assert unavailable == MainForceMirrorDiagnosticUnavailableProductRow(
        symbol="ao",
        status=MainForceMirrorDiagnosticStatus.UNAVAILABLE,
        reason_code=MainForceMirrorDiagnosticUnavailableReason.MARKET_SOURCE_UNAVAILABLE,
    )
    assert result.report.validation.available_product_count == 59
    assert result.report.validation.unavailable_product_count == 1
    assert result.report.gate is MainForceMirrorDiagnosticGate.STOP
    assert all(
        request.frequency is BarFrequency.H1
        and request.since == date(2023, 1, 1)
        and request.through == date(2026, 8, 18)
        for request in market_data.calls
    )
    assert all(
        request.series_kind is SeriesKind.ACTUAL_DOMINANT
        and request.contract is None
        and request.frequency is BarFrequency.H1
        for request in mirror.calls
    )
    assert {request.symbol for request in mirror.calls} == {
        request.symbol for request in market_data.calls if request.symbol != "ao"
    }


def test_diagnostic_service_does_not_swallow_unknown_source_failure() -> None:
    market_data = _MarketData(unknown_symbol="ao")

    with pytest.raises(RuntimeError, match="provider secret detail"):
        _service(market_data, _MirrorService()).run(
            MainForceMirrorDiagnosticRequest(PROTOCOL_ID)
        )


def test_market_source_identity_corruption_is_error_without_report_gate() -> None:
    class _CorruptMarketData(_MarketData):
        def query_actual_dominant_trading_days(
            self,
            request: ActualDominantTradingDayQuery,
        ) -> MarketSeriesResult:
            self.calls.append(request)
            raise MarketDataError("BAR_IDENTITY_CONFLICT")

    module = _service_module()

    with pytest.raises(
        module.MainForceMirrorDiagnosticSourceError,
        match="MFM_DIAGNOSTIC_SOURCE_IDENTITY_INVALID",
    ):
        _service(_CorruptMarketData(), _MirrorService()).run(
            MainForceMirrorDiagnosticRequest(PROTOCOL_ID)
        )


def test_all_known_source_failures_still_emit_all_rows_and_stop() -> None:
    class _AllUnavailable(_MarketData):
        def query_actual_dominant_trading_days(
            self,
            request: ActualDominantTradingDayQuery,
        ) -> MarketSeriesResult:
            self.calls.append(request)
            raise MarketDataError("TRADING_SESSION_MISSING")

    market_data = _AllUnavailable()
    result = _service(market_data, _MirrorService()).run(
        MainForceMirrorDiagnosticRequest(PROTOCOL_ID)
    )

    assert len(result.report.product_rows) == 60
    assert all(
        type(row) is MainForceMirrorDiagnosticUnavailableProductRow
        for row in result.report.product_rows
    )
    assert result.report.validation.available_product_count == 0
    assert result.report.validation.unavailable_product_count == 60
    assert result.report.gate is MainForceMirrorDiagnosticGate.STOP


def test_protocol_failure_precedes_every_source_read() -> None:
    module = _service_module()
    market_data = _MarketData()
    mirror = _MirrorService()
    service = module.MainForceMirrorDiagnosticService(
        market_data=market_data,
        mirror_service=mirror,
        protocol_loader=lambda: (_ for _ in ()).throw(
            MainForceMirrorDiagnosticProtocolError()
        ),
    )

    with pytest.raises(MainForceMirrorDiagnosticProtocolError):
        service.run(MainForceMirrorDiagnosticRequest(PROTOCOL_ID))

    assert market_data.calls == []
    assert mirror.calls == []


def test_page_request_identity_drift_is_error_without_report_gate() -> None:
    module = _service_module()

    with pytest.raises(
        module.MainForceMirrorDiagnosticSourceError,
        match="MFM_DIAGNOSTIC_SOURCE_IDENTITY_INVALID",
    ):
        _service(_MarketData(), _MirrorService(drift="request_identity")).run(
            MainForceMirrorDiagnosticRequest(PROTOCOL_ID)
        )


def test_market_request_identity_drift_is_error_without_report_gate() -> None:
    class _MarketIdentityDrift(_MarketData):
        def query_actual_dominant_trading_days(
            self,
            request: ActualDominantTradingDayQuery,
        ) -> MarketSeriesResult:
            result = super().query_actual_dominant_trading_days(request)
            return replace(
                result,
                request_identity={**result.request_identity, "symbol": "ag"},
            )

    module = _service_module()

    with pytest.raises(
        module.MainForceMirrorDiagnosticSourceError,
        match="MFM_DIAGNOSTIC_SOURCE_IDENTITY_INVALID",
    ):
        _service(_MarketIdentityDrift(), _MirrorService()).run(
            MainForceMirrorDiagnosticRequest(PROTOCOL_ID)
        )


@pytest.mark.parametrize(
    "mutation",
    (
        "extra_identity_key",
        "wrong_contract",
        "invalid_start",
        "unordered_window",
        "empty_bars",
        "bars_not_tuple",
        "noncanonical_bar",
        "out_of_window_bar",
        "coverage_mismatch",
    ),
)
def test_successful_market_result_must_match_exact_canonical_contract(
    mutation: str,
) -> None:
    class _InvalidMarketResult(_MarketData):
        def query_actual_dominant_trading_days(
            self,
            request: ActualDominantTradingDayQuery,
        ) -> MarketSeriesResult:
            result = super().query_actual_dominant_trading_days(request)
            if mutation == "extra_identity_key":
                return replace(
                    result,
                    request_identity={**result.request_identity, "extra": "drift"},
                )
            if mutation == "wrong_contract":
                return replace(
                    result,
                    request_identity={**result.request_identity, "contract": "JM2609"},
                )
            if mutation == "invalid_start":
                return replace(
                    result,
                    request_identity={**result.request_identity, "start": "2023-01-01"},
                )
            if mutation == "unordered_window":
                return replace(
                    result,
                    request_identity={
                        **result.request_identity,
                        "start": "2026-08-18T08:00:00+00:00",
                        "end": "2022-12-31T20:00:00+00:00",
                    },
                )
            if mutation == "empty_bars":
                return replace(
                    result,
                    bars=(),
                    coverage=None,
                    resolved_contract_segments=(),
                )
            if mutation == "bars_not_tuple":
                return replace(result, bars=list(result.bars))  # type: ignore[arg-type]
            if mutation == "noncanonical_bar":
                return replace(result, bars=(object(),))  # type: ignore[arg-type]
            if mutation == "out_of_window_bar":
                outside = replace(result.bars[0], trading_day=date(2026, 8, 19))
                return replace(result, bars=(outside,), coverage=(outside.bar_end, outside.bar_end))
            if mutation == "coverage_mismatch":
                shifted = result.bars[0].bar_end + timedelta(hours=1)
                return replace(result, coverage=(shifted, shifted))
            raise AssertionError(mutation)

    module = _service_module()

    with pytest.raises(
        module.MainForceMirrorDiagnosticSourceError,
        match="MFM_DIAGNOSTIC_SOURCE_IDENTITY_INVALID",
    ):
        _service(_InvalidMarketResult(), _MirrorService()).run(
            MainForceMirrorDiagnosticRequest(PROTOCOL_ID)
        )


@pytest.mark.parametrize(
    "drift",
    ("point_contract", "coverage", "cursor", "cross_product"),
)
def test_page_alignment_cursor_coverage_and_cross_product_identity_fail_closed(
    drift: str,
) -> None:
    module = _service_module()

    with pytest.raises(
        module.MainForceMirrorDiagnosticSourceError,
        match="MFM_DIAGNOSTIC_SOURCE_IDENTITY_INVALID",
    ):
        _service(_MarketData(), _MirrorService(drift=drift)).run(
            MainForceMirrorDiagnosticRequest(PROTOCOL_ID)
        )


@pytest.mark.parametrize(
    "drift",
    (
        "terminal_next_without_more",
        "terminal_more_without_next",
        "terminal_wrong_next",
        "point_not_before",
        "descending_page",
    ),
)
def test_every_page_cursor_shape_is_validated_before_target_complete_break(
    drift: str,
) -> None:
    module = _service_module()

    with pytest.raises(
        module.MainForceMirrorDiagnosticSourceError,
        match="MFM_DIAGNOSTIC_SOURCE_IDENTITY_INVALID",
    ):
        _service(_MarketData(), _MirrorService(drift=drift)).run(
            MainForceMirrorDiagnosticRequest(PROTOCOL_ID)
        )


def test_consistent_noncanonical_v2_identity_is_rejected_without_gate() -> None:
    module = _service_module()

    with pytest.raises(
        module.MainForceMirrorDiagnosticSourceError,
        match="MFM_DIAGNOSTIC_SOURCE_IDENTITY_INVALID",
    ):
        _service(_MarketData(), _MirrorService(drift="wrong_v3")).run(
            MainForceMirrorDiagnosticRequest(PROTOCOL_ID)
        )


def test_jm_named_view_reuses_same_full_input_without_second_source_read() -> None:
    module = _service_module()
    market_data = _MarketData()
    mirror = _MirrorService()

    result = _service(market_data, mirror).run(
        MainForceMirrorDiagnosticRequest(PROTOCOL_ID)
    )

    view = result.jm_named_view
    assert type(view) is module.MainForceMirrorDiagnosticNamedViewAvailable
    assert view.status is MainForceMirrorDiagnosticStatus.AVAILABLE
    assert view.symbol == "jm"
    assert view.since == date(2026, 3, 10)
    assert view.through == date(2026, 3, 30)
    assert view.label.raw_sample_count == 0
    assert len(view.sequence.profiles) == 5
    assert view.funnel.evaluable_bar_count == 0
    assert sum(request.symbol == "jm" for request in market_data.calls) == 1
    assert sum(request.symbol == "jm" for request in mirror.calls) == 1


def test_jm_named_view_is_explicitly_typed_unavailable_with_no_second_read() -> None:
    module = _service_module()
    market_data = _MarketData(unavailable_symbol="jm")
    mirror = _MirrorService()

    result = _service(market_data, mirror).run(
        MainForceMirrorDiagnosticRequest(PROTOCOL_ID)
    )

    view = result.jm_named_view
    assert type(view) is module.MainForceMirrorDiagnosticNamedViewUnavailable
    assert view.status is MainForceMirrorDiagnosticStatus.UNAVAILABLE
    assert view.symbol == "jm"
    assert view.since == date(2026, 3, 10)
    assert view.through == date(2026, 3, 30)
    assert view.reason_code is (
        MainForceMirrorDiagnosticUnavailableReason.MARKET_SOURCE_UNAVAILABLE
    )
    assert sum(request.symbol == "jm" for request in market_data.calls) == 1
    assert all(request.symbol != "jm" for request in mirror.calls)


def test_jm_named_view_unavailable_payload_has_reason_and_no_fake_sections() -> None:
    result = _service(
        _MarketData(unavailable_symbol="jm"),
        _MirrorService(),
    ).run(MainForceMirrorDiagnosticRequest(PROTOCOL_ID))

    payload = run_research_command(
        MainForceMirrorDiagnosticRequest(PROTOCOL_ID),
        _FakeDiagnosticService(result),
    )

    assert payload["jm_named_view"] == {
        "status": "unavailable",
        "symbol": "jm",
        "window": {"since": "2026-03-10", "through": "2026-03-30"},
        "reason_code": "MARKET_SOURCE_UNAVAILABLE",
    }


def test_missing_previous_trading_day_is_typed_member_unavailable() -> None:
    module = _service_module()
    market = _MarketData().query_actual_dominant_trading_days(
        ActualDominantTradingDayQuery(
            "jm", BarFrequency.H1, date(2023, 1, 1), date(2026, 8, 18)
        )
    )
    page = _MirrorService().query_diagnostic_page(
        SeriesPageQuery(
            SeriesKind.ACTUAL_DOMINANT,
            "jm",
            BarFrequency.H1,
            before=_bar().bar_end,
            limit=2000,
        )
    )
    product = MainForceMirrorDiagnosticProductInput(
        symbol="jm",
        bars=market.bars,
        points=page.page.points,
        trace=page.audit_trace,
    )
    labels = audit_main_force_mirror_labels((product,))
    labels = replace(
        labels,
        episodes=(
            MainForceMirrorDiagnosticLabelEpisode(
                symbol="jm",
                anchor_index=0,
                anchor_trading_day=date(2023, 1, 1),
                physical_contract="JM2609",
                side=MainForceMirrorDiagnosticSide.LONG,
                kept=True,
                lower_barrier=Decimal("99"),
                upper_barrier=Decimal("101"),
                legacy_outcome=MainForceMirrorDiagnosticLegacyOutcome.NEITHER,
                outcome=None,
                first_touch_offset=None,
                binary_target=None,
                fold_outcomes=(),
            ),
        ),
    )

    def missing_day(_symbol: str, _day: date) -> date:
        raise InfrastructureError("COMPLETE_TRADING_DAY_MISSING")

    service = module.MainForceMirrorDiagnosticService(
        market_data=_MarketData(),
        mirror_service=_MirrorService(),
        previous_trading_day=missing_day,
    )
    observations = service._member_observations(
        labels,
        {"jm": MemberDatasetState("unavailable", None, None, False, None)},
    )
    member = audit_main_force_mirror_member_feasibility(observations)

    assert member.section.unique_earliest_count == 1
    assert member.section.eligible_count == 0
    assert member.unavailable[0].reason is (
        MainForceMirrorDiagnosticUnavailableReason.MEMBER_T_MINUS_1_UNAVAILABLE
    )


@pytest.fixture(scope="module")
def diagnostic_result():
    return _service(_MarketData(), _MirrorService()).run(
        MainForceMirrorDiagnosticRequest(PROTOCOL_ID)
    )


class _FakeDiagnosticService:
    def __init__(self, result: object) -> None:
        self.result = result
        self.requests: list[MainForceMirrorDiagnosticRequest] = []

    def run(self, request: MainForceMirrorDiagnosticRequest):
        self.requests.append(request)
        return self.result


def test_diagnostic_payload_is_explicit_and_excludes_internal_inputs(
    diagnostic_result,
) -> None:
    payload = run_research_command(
        MainForceMirrorDiagnosticRequest(PROTOCOL_ID),
        _FakeDiagnosticService(diagnostic_result),
    )

    assert payload["schema_version"] == 1
    assert payload["command"] == "research.main-force-mirror-diagnostic"
    assert payload["status"] == "ok"
    assert payload["protocol_id"] == PROTOCOL_ID
    assert payload["model_subprotocol"] == "mfm_v3_readonly_training_probe_v1"
    assert payload["readonly"] is True
    assert payload["research_only"] is True
    assert payload["evaluation_classification"] == (
        "retrospective_historical_diagnostic"
    )
    assert payload["source"] == {
        "series_kind": "actual_dominant",
        "frequency": "60m",
        "confirmed_only": True,
    }
    assert payload["windows"] == {
        "active60": {"since": "2023-01-01", "through": "2026-08-18"},
        "jm_view": {"since": "2026-03-10", "through": "2026-03-30"},
        "known_retrospective_through": "2026-08-20",
        "prospective": {"begins_after": "2026-08-20", "consumed": False},
    }
    view_payload = payload["jm_named_view"]
    assert tuple(view_payload) == (
        "status",
        "symbol",
        "window",
        "label",
        "sequence",
        "funnel",
    )
    assert view_payload["status"] == "available"
    assert view_payload["symbol"] == "jm"
    assert view_payload["window"] == {
        "since": "2026-03-10",
        "through": "2026-03-30",
    }
    assert view_payload["label"]["raw_sample_count"] == 0
    assert len(view_payload["sequence"]["profiles"]) == 5
    assert view_payload["funnel"]["evaluable_bar_count"] == 0
    assert payload["v2_identity"]["indicator_code"] == "main_force_mirror_v2"
    assert len(payload["product_rows"]) == 60
    assert tuple(payload) == (
        "schema_version",
        "command",
        "status",
        "protocol_id",
        "model_subprotocol",
        "readonly",
        "research_only",
        "evaluation_classification",
        "source",
        "windows",
        "jm_named_view",
        "v2_identity",
        "validation",
        "product_rows",
        "label",
        "sequence",
        "funnel",
        "model",
        "member",
        "quality_flags",
        "gate",
        "gate_reasons",
    )
    rendered = json.dumps(payload, sort_keys=True)
    for forbidden in ("bars", "points", "trace", "member_observations"):
        assert f'"{forbidden}"' not in rendered


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        (Decimal("-0"), "0"),
        (Decimal("-0.0000"), "0"),
        (Decimal("1.2300"), "1.23"),
        (Decimal("1E+3"), "1000"),
        (date(2026, 8, 20), "2026-08-20"),
    ),
)
def test_diagnostic_json_value_is_canonical(value: object, expected: str) -> None:
    assert research_payloads._main_force_mirror_diagnostic_json_value(value) == expected


@pytest.mark.parametrize("value", (Decimal("NaN"), Decimal("Infinity")))
def test_diagnostic_json_value_rejects_nonfinite_decimal(value: Decimal) -> None:
    with pytest.raises(ValueError, match="MFM_DIAGNOSTIC_REPORT_INVALID"):
        research_payloads._main_force_mirror_diagnostic_json_value(value)


def test_diagnostic_json_value_preserves_high_precision_decimal_exactly() -> None:
    value = Decimal("12345678901234567890.1234567890123456789000")

    rendered = research_payloads._main_force_mirror_diagnostic_json_value(value)

    assert rendered == "12345678901234567890.1234567890123456789"
    assert type(rendered) is str


def test_diagnostic_json_value_converts_strenum_to_plain_string() -> None:
    class _Value(StrEnum):
        ITEM = "item"

    rendered = research_payloads._main_force_mirror_diagnostic_json_value(
        _Value.ITEM
    )

    assert rendered == "item"
    assert type(rendered) is str


def test_diagnostic_cli_uses_only_dedicated_factory_and_is_byte_deterministic(
    diagnostic_result,
) -> None:
    service = _FakeDiagnosticService(diagnostic_result)
    unrelated: list[str] = []

    def invoke() -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        code = main(
            _arguments(),
            session_factory=lambda: nullcontext(object()),
            manager_factory=lambda _session: unrelated.append("manager"),
            live_service_factory=lambda _session: unrelated.append("live"),
            alert_runtime_factory=lambda: unrelated.append("alert"),
            alert_canary_sender_factory=lambda: unrelated.append("notification"),
            research_service_factory=lambda _session: unrelated.append("research"),
            main_force_mirror_diagnostic_service_factory=lambda _session: service,
            stdout=stdout,
            stderr=stderr,
        )
        return code, stdout.getvalue(), stderr.getvalue()

    first = invoke()
    second = invoke()

    assert first == second
    assert first[0] == 0
    assert first[1].endswith("\n") and not first[1].endswith("\n\n")
    assert first[2] == ""
    assert unrelated == []
    assert service.requests == [
        MainForceMirrorDiagnosticRequest(PROTOCOL_ID),
        MainForceMirrorDiagnosticRequest(PROTOCOL_ID),
    ]


def test_unknown_diagnostic_failure_is_redacted_cli_error_without_gate() -> None:
    class _UnknownFailure:
        def run(self, _request: MainForceMirrorDiagnosticRequest) -> object:
            raise RuntimeError("provider token and internal path")

    stdout = io.StringIO()
    stderr = io.StringIO()
    code = main(
        _arguments(),
        session_factory=lambda: nullcontext(object()),
        main_force_mirror_diagnostic_service_factory=lambda _session: _UnknownFailure(),
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 1
    assert stdout.getvalue() == ""
    payload = json.loads(stderr.getvalue())
    assert payload == {
        "schema_version": 1,
        "command": "research.main-force-mirror-diagnostic",
        "status": "error",
        "readonly": True,
        "error": {"code": "CLI_INTERNAL_ERROR", "type": "RuntimeError"},
    }
    assert "gate" not in payload
