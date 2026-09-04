from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

from fastapi.testclient import TestClient
from guiyi_quant.newow import (
    CleanroomCompositeDecision,
    CompositeAction,
    CompositeDecision,
    CompositeVolatility,
    CertaintyBreakdown,
    DiagnosticFacts,
    DiagnosticSeverity,
    DiagnosticToken,
    DirectionToken,
    DisplayPeriod,
    DisplayPriceSelection,
    FirstActionPrinciple,
    OscillationBias,
    PageChannelWindowResult,
    PageSignalState,
    PositionRange,
    PrincipleLevel,
    PriceChannelPoint,
    TrendBandState,
    TrendBias,
    VolatilityLevel,
    diagnostic_tokens,
)
from pydantic import ValidationError
import pytest

from app.api import market_newow
from app.db.session import get_db
from app.main import app
from app.market_data.newow.trend_detail_service import NewowTrendDetailError
from app.market_data.newow.trend_detail_service import (
    NewowFrequencyPriceChannel,
    NewowPriceChannelFacts,
    NewowSemanticLabels,
)
from app.schemas.market_newow import NewowTrendDetailResponse


def test_openapi_schema_closes_newow_enums_and_formula_identities() -> None:
    definitions = NewowTrendDetailResponse.model_json_schema()["$defs"]

    meta = definitions["NewowMetaOut"]["properties"]
    assert meta["strategy_code"]["const"] == "newow_trend_v1"
    assert meta["profile_id"]["const"] == "newow_trend_d1_page_v2"
    assert meta["frequency"]["const"] == "1d"
    assert meta["series_kind"]["const"] == "actual_dominant"

    trend = definitions["NewowTrendBandOut"]["properties"]
    assert trend["state"]["enum"] == ["UNAVAILABLE", "YELLOW", "BLUE"]
    assert trend["transition"]["anyOf"][0]["enum"] == ["BUILD", "CLEAR"]

    marker = definitions["NewowMarkerOut"]["properties"]
    assert marker["marker_type"]["enum"] == [
        "BUILD",
        "CLEAR",
        "NEWOW_ESCAPE_D1",
        "NEWOW_ESCAPE_D2",
        "NEWOW_ESCAPE_D3",
        "CUP_HANDLE_READY",
        "CUP_HANDLE_BREAKOUT",
        "CUP_HANDLE_WEAKENED",
        "CUP_HANDLE_INVALIDATED",
        "CUP_HANDLE_EXPIRED",
    ]
    assert set(marker["formula_version"]["enum"]) == {
        "newow_trend_band_page_v2",
        "newow_escape_d123_page_v2",
        "newow_cup_handle_v1",
    }

    cup = definitions["NewowCupHandleOut"]["properties"]
    assert cup["direction"]["enum"] == ["BULLISH", "BEARISH"]
    assert cup["state"]["enum"] == [
        "FORMING",
        "READY",
        "BREAKOUT",
        "WEAKENED",
        "INVALIDATED",
        "EXPIRED",
    ]
    assert cup["formula_version"]["const"] == "newow_cup_handle_v1"

    diagnostic_facts = definitions["NewowDiagnosticFactsOut"]["properties"]
    assert diagnostic_facts["repainting_inputs_excluded"]["items"]["const"] == (
        "newow_zhaoyao_mirror_repainting_page_v1"
    )
    diagnostic_formulas = {
        "newow_diagnostic_rules_cleanroom_v1",
        "newow_diagnostic_facts_cleanroom_v1",
        "newow_target_absorb_display_selection_page_v2",
        "newow_trend_band_page_v2",
        "newow_oscillation_hhv_llv10_page_v1",
        "newow_main_force_control_page_v1",
        "newow_main_rise_ma35_ma45_page_v1",
        "newow_cup_handle_v1",
        "newow_ai_week_day_16_matrix_page_v1",
    }
    assert set(diagnostic_facts["formula_versions"]["items"]["enum"]) == (
        diagnostic_formulas
    ) - {
        "newow_diagnostic_rules_cleanroom_v1",
        "newow_ai_week_day_16_matrix_page_v1",
    }
    diagnostic_token = definitions["NewowDiagnosticTokenOut"]["properties"]
    assert set(diagnostic_token["formula_identities"]["items"]["enum"]) == (
        diagnostic_formulas
    )


def test_newow_response_serializes_real_core_diagnostic_token_lineage() -> None:
    result = _result()
    result.diagnostic_tokens = diagnostic_tokens(result.diagnostic_facts)

    response = market_newow._response(result)

    assert any(
        item.formula_identities == ["newow_ai_week_day_16_matrix_page_v1"]
        for item in response.diagnostic_tokens
    )


def _result() -> SimpleNamespace:
    stamp = datetime(2026, 1, 5, 7, tzinfo=UTC)
    bar = SimpleNamespace(
        bar_end=stamp,
        trading_day=date(2026, 1, 5),
        open=Decimal("10.10"),
        high=Decimal("11.20"),
        low=Decimal("9.90"),
        close=Decimal("10.50"),
        volume=100,
        open_interest=200,
        physical_contract="RB2605",
        segment_id="RB2605:2026-01-05:2026-01-05",
        source_identity="calculation",
        observation_eligible=True,
    )
    markers = (
        SimpleNamespace(
            marker_type=SimpleNamespace(value="BUILD"),
            marker_id="build",
            bar_end=stamp,
            price=Decimal("10.50"),
            label="BUILD",
            color_token="yellow",
            priority=1,
            related_marker_ids=(),
            trigger_facts={},
            formula_version="newow_trend_band_page_v2",
        ),
        SimpleNamespace(
            marker_type=SimpleNamespace(value="NEWOW_ESCAPE_D1"),
            marker_id="d1",
            bar_end=stamp,
            price=Decimal("10.50"),
            label="D1",
            color_token="red",
            priority=2,
            related_marker_ids=(),
            trigger_facts={},
            formula_version="newow_escape_d123_page_v2",
        ),
        SimpleNamespace(
            marker_type=SimpleNamespace(value="NEWOW_ESCAPE_D2"),
            marker_id="d2",
            bar_end=stamp,
            price=Decimal("10.50"),
            label="D2",
            color_token="red",
            priority=2,
            related_marker_ids=(),
            trigger_facts={},
            formula_version="newow_escape_d123_page_v2",
        ),
        SimpleNamespace(
            marker_type=SimpleNamespace(value="NEWOW_ESCAPE_D3"),
            marker_id="d3",
            bar_end=stamp,
            price=Decimal("10.50"),
            label="D3",
            color_token="red",
            priority=2,
            related_marker_ids=(),
            trigger_facts={},
            formula_version="newow_escape_d123_page_v2",
        ),
    )
    frame = SimpleNamespace(
        bar=bar,
        trend_band=SimpleNamespace(
            b_value=1.2,
            c_value=1.1,
            state=SimpleNamespace(value="YELLOW"),
            state_before=None,
            transition=None,
        ),
        markers=markers,
        cup_handle=None,
    )
    cup = SimpleNamespace(
        candidate_id="cup-1",
        direction=SimpleNamespace(value="BULLISH"),
        state=SimpleNamespace(value="READY"),
        left_rim=SimpleNamespace(
            pivot_at=stamp, confirmed_at=stamp, price=Decimal("11.20")
        ),
        bottom=SimpleNamespace(
            pivot_at=stamp, confirmed_at=stamp, price=Decimal("9.90")
        ),
        right_rim=SimpleNamespace(
            pivot_at=stamp, confirmed_at=stamp, price=Decimal("11.00")
        ),
        handle_start_at=stamp,
        handle_extreme=None,
        pivot_price=Decimal("11.30"),
        pivot_frozen_at=stamp,
        confirmed_at=stamp,
        first_seen_at=stamp,
        state_changed_at=stamp,
        score=88.0,
        score_breakdown={"shape": 42.0},
        hard_failures=(),
        diagnostics=("formed",),
        volume_facts={"ratio": 1.25},
        formula_version="newow_cup_handle_v1",
    )
    channel_point = PriceChannelPoint(
        stamp,
        Decimal("11.20"),
        Decimal("9.90"),
        10,
        True,
    )
    price_channel = NewowPriceChannelFacts(
        NewowFrequencyPriceChannel("1d", (channel_point,), ("segment-d",)),
        NewowFrequencyPriceChannel("1w", (channel_point,), ("segment-w",)),
        NewowFrequencyPriceChannel("60m", (channel_point,), ("segment-h",)),
        DisplayPriceSelection(
            Decimal("11.20"),
            Decimal("9.90"),
            Decimal("11.20"),
            Decimal("9.90"),
            DisplayPeriod.DAY,
            DisplayPeriod.DAY,
            "DAILY_POSITIVE",
            "DAILY_POSITIVE",
        ),
    )
    volatility = CompositeVolatility(Decimal("2.5"), VolatilityLevel.MID, 20)
    certainty = CertaintyBreakdown(30, 30, 20, 20, 100)
    position = PositionRange(Decimal("0.5"), Decimal("1"))
    composite_page = CompositeDecision(
        TrendBias.BULLISH,
        OscillationBias.BULLISH,
        DirectionToken.MULTIPERIOD_BULLISH,
        "bullish-bullish",
        CompositeAction.BUILD_OR_ADD,
        position,
        certainty,
        volatility,
        (),
    )
    composite_cleanroom = CleanroomCompositeDecision(
        TrendBias.BULLISH,
        OscillationBias.BULLISH,
        DirectionToken.MULTIPERIOD_BULLISH,
        "bullish-bullish",
        CompositeAction.BUILD_OR_ADD,
        position,
        certainty,
        volatility,
        (),
        None,
    )
    diagnostics = DiagnosticFacts(
        stamp,
        Decimal("11.20"),
        Decimal("9.90"),
        Decimal("6.6667"),
        Decimal("-5.7143"),
        Decimal("10.20"),
        "above",
        TrendBandState.YELLOW,
        4,
        True,
        None,
        True,
        None,
        PageSignalState.HOLD,
        PageSignalState.BUY,
        ("newow_zhaoyao_mirror_repainting_page_v1",),
        ("newow_diagnostic_facts_cleanroom_v1",),
    )
    return SimpleNamespace(
        calculation_identity="calculation",
        data_revision_identity=None,
        request_identity="request",
        instrument=SimpleNamespace(
            product="rb",
            display_name=None,
            last_visible_physical_contract=None,
            frequency="1d",
            series_kind="actual_dominant",
            profile_id="newow_trend_d1_page_v2",
            formula_versions=(
                "newow_trend_band_page_v2",
                "newow_escape_d123_page_v2",
                "newow_cup_handle_v1",
                "newow_oscillation_hhv_llv10_page_v1",
                "newow_main_force_control_page_v1",
                "newow_main_rise_ma35_ma45_page_v1",
                "newow_target_absorb_hhv_llv10_page_v1",
                "newow_target_absorb_display_selection_page_v2",
                "newow_hhv_llv_window_optimizer_page_v1",
                "newow_hhv_llv_window_optimizer_causal_v1",
                "newow_composite_decision_page_v3_2_82",
                "newow_composite_decision_cleanroom_v1",
                "newow_first_action_principle_page_v3_2_63",
                "newow_diagnostic_facts_cleanroom_v1",
                "newow_diagnostic_rules_cleanroom_v1",
            ),
        ),
        bars=(bar,),
        frames=(frame,),
        markers=markers,
        cup_handles=(cup,),
        rollover_seams=(
            SimpleNamespace(
                trading_day=date(2026, 1, 5),
                previous_contract="RB2605",
                next_contract="RB2610",
                previous_bar_end=stamp,
                next_bar_end=stamp,
                previous_segment_id="a",
                next_segment_id="b",
            ),
        ),
        price_channel=price_channel,
        page_window_comparison=tuple(
            PageChannelWindowResult(
                window,
                Decimal("1"),
                Decimal("0.5"),
                3,
                Decimal("50"),
                Decimal("0.5"),
                False,
            )
            for window in (10, 20, 24, 30, 52)
        ),
        composite_page=composite_page,
        composite_cleanroom=composite_cleanroom,
        first_action_principle=FirstActionPrinciple(
            PrincipleLevel.OK,
            "normal_observation",
            (),
        ),
        diagnostic_facts=diagnostics,
        diagnostic_tokens=(
            DiagnosticToken(
                "NEWOW_DIAG_TREND_YELLOW",
                DiagnosticSeverity.INFO,
                ("trend_state",),
                ("newow_diagnostic_rules_cleanroom_v1",),
            ),
        ),
        semantic_labels=NewowSemanticLabels(),
        warnings=("NEWOW_TREND_WARMUP_INSUFFICIENT",),
    )


def _client(monkeypatch, result: object = None) -> TestClient:
    value = _result() if result is None else result
    monkeypatch.setattr(
        market_newow,
        "NewowTrendDetailService",
        lambda _market, **_kwargs: SimpleNamespace(query=lambda _query: value),
    )
    app.dependency_overrides[get_db] = lambda: object()
    return TestClient(app)


def test_get_newow_trend_detail_maps_safe_typed_facts(monkeypatch) -> None:
    with _client(monkeypatch) as client:
        response = client.get(
            "/api/v1/market/newow/trend-detail?product=rb&from=2026-01-05&through=2026-01-05"
        )
    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["meta"] == {
        "strategy_code": "newow_trend_v1",
        "profile_id": "newow_trend_d1_page_v2",
        "frequency": "1d",
        "series_kind": "actual_dominant",
            "calculation_identity": "calculation",
            "data_revision_identity": None,
        "request_identity": "request",
    }
    assert body["bars"][0]["close"] == "10.50"
    assert body["bars"][0]["bar_end"].endswith("Z")
    assert [marker["marker_type"] for marker in body["escape_markers"]] == [
        "NEWOW_ESCAPE_D1",
        "NEWOW_ESCAPE_D2",
        "NEWOW_ESCAPE_D3",
    ]
    assert body["cup_handles"][0]["confirmed_at"].endswith("Z")
    assert body["cup_handles"][0]["score_breakdown"] == {"shape": 42.0}
    assert body["cup_handles"][0]["hard_failures"] == []
    assert body["cup_handles"][0]["diagnostics"] == ["formed"]
    assert body["cup_handles"][0]["volume_facts"] == {"ratio": 1.25}
    assert body["bar_policy"] == "completed_only"
    assert body["price_channel"]["daily"]["frequency"] == "1d"
    assert body["price_channel"]["daily"]["points"][0]["target"] == "11.20"
    assert [item["window"] for item in body["page_window_comparison"]] == [
        10,
        20,
        24,
        30,
        52,
    ]
    assert all(
        item["trustworthy_for_research"] is False
        for item in body["page_window_comparison"]
    )
    assert body["composite_page"]["formula_version"] == (
        "newow_composite_decision_page_v3_2_82"
    )
    assert body["composite_cleanroom"]["formula_version"] == (
        "newow_composite_decision_cleanroom_v1"
    )
    assert body["semantic_labels"] == {
        "page_parity": True,
        "cleanroom_separated": True,
        "observation_only": True,
        "causal_research_result": False,
        "repainting_input_used": False,
    }
    assert set(body["formula_descriptions"]) == {
        "trend_band",
        "escape",
        "cup_handle",
        "oscillation",
        "main_force",
        "main_rise",
        "price_channel",
        "display_selection",
        "page_window_comparison",
        "causal_window_identity",
        "composite_page",
        "composite_cleanroom",
        "first_action",
        "diagnostic_facts",
        "diagnostic_rules",
    }
    body["unexpected"] = True
    with pytest.raises(ValidationError):
        NewowTrendDetailResponse.model_validate(body)


def test_newow_route_rejects_nonfixed_params_and_is_get_only(monkeypatch) -> None:
    with _client(monkeypatch) as client:
        assert (
            client.get(
                "/api/v1/market/newow/trend-detail?product=rb&from=2026-01-05&through=2026-01-05&frequency=5m"
            ).status_code
            == 422
        )
        assert (
            client.get(
                "/api/v1/market/newow/trend-detail?product=rb&from=2026-01-05&through=2026-01-05&series_kind=continuous"
            ).status_code
            == 422
        )
        assert client.post("/api/v1/market/newow/trend-detail").status_code == 405
        assert client.get("/api/v1/market/bars/page").status_code == 422
    app.dependency_overrides.clear()


def test_newow_api_keeps_cup_marker_history_and_treats_range_limit_as_422(monkeypatch) -> None:
    value = _result()
    stamp = value.bars[0].bar_end
    value.markers = value.markers + tuple(
        SimpleNamespace(
            marker_type=SimpleNamespace(value=kind),
            marker_id=kind.lower(),
            bar_end=stamp,
            price=Decimal("10.50"),
            label=kind,
            color_token="newow-cup",
            priority=1,
            related_marker_ids=(),
            trigger_facts={},
            formula_version="newow_cup_handle_v1",
        )
        for kind in (
            "CUP_HANDLE_READY",
            "CUP_HANDLE_BREAKOUT",
            "CUP_HANDLE_WEAKENED",
            "CUP_HANDLE_INVALIDATED",
            "CUP_HANDLE_EXPIRED",
        )
    )
    with _client(monkeypatch, value) as client:
        response = client.get(
            "/api/v1/market/newow/trend-detail?product=rb&from=2026-01-05&through=2026-01-05"
        )
    app.dependency_overrides.clear()
    assert [item["marker_type"] for item in response.json()["cup_markers"]] == [
        "CUP_HANDLE_READY",
        "CUP_HANDLE_BREAKOUT",
        "CUP_HANDLE_WEAKENED",
        "CUP_HANDLE_INVALIDATED",
        "CUP_HANDLE_EXPIRED",
    ]

    monkeypatch.setattr(
        market_newow,
        "NewowTrendDetailService",
        lambda _market, **_kwargs: SimpleNamespace(
            query=lambda _query: (_ for _ in ()).throw(
                NewowTrendDetailError("NEWOW_RANGE_TOO_LARGE")
            )
        ),
    )
    app.dependency_overrides[get_db] = lambda: object()
    response = TestClient(app).get(
        "/api/v1/market/newow/trend-detail?product=rb&from=2026-01-05&through=2026-01-05"
    )
    app.dependency_overrides.clear()
    assert response.status_code == 422


def test_newow_public_error_never_leaks_core_reason(monkeypatch) -> None:
    monkeypatch.setattr(
        market_newow,
        "NewowTrendDetailService",
        lambda _market, **_kwargs: SimpleNamespace(
            query=lambda _query: (_ for _ in ()).throw(
                NewowTrendDetailError("NEWOW_DATA_IDENTITY_INVALID")
            )
        ),
    )
    app.dependency_overrides[get_db] = lambda: object()
    response = TestClient(app).get(
        "/api/v1/market/newow/trend-detail?product=rb&from=2026-01-05&through=2026-01-05"
    )
    app.dependency_overrides.clear()

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "NEWOW_DATA_IDENTITY_INVALID"}}


def test_newow_invalid_product_and_range_are_public_422_codes(monkeypatch) -> None:
    errors = iter(
        (
            NewowTrendDetailError("NEWOW_INVALID_PRODUCT"),
            NewowTrendDetailError("NEWOW_INVALID_RANGE"),
        )
    )
    monkeypatch.setattr(
        market_newow,
        "NewowTrendDetailService",
        lambda _market, **_kwargs: SimpleNamespace(
            query=lambda _query: (_ for _ in ()).throw(next(errors))
        ),
    )
    app.dependency_overrides[get_db] = lambda: object()
    client = TestClient(app)
    product = client.get(
        "/api/v1/market/newow/trend-detail?product=bad&from=2026-01-05&through=2026-01-05"
    )
    window = client.get(
        "/api/v1/market/newow/trend-detail?product=rb&from=2026-01-06&through=2026-01-05"
    )
    app.dependency_overrides.clear()

    assert product.json() == {"detail": {"code": "NEWOW_INVALID_PRODUCT"}}
    assert window.json() == {"detail": {"code": "NEWOW_INVALID_RANGE"}}


def test_newow_marker_facts_recursively_serialize_safe_values(monkeypatch) -> None:
    result = _result()
    stamp = datetime(2026, 1, 5, 7, tzinfo=UTC)
    result.markers[0].trigger_facts = {
        "decimal": Decimal("1.2300"),
        "day": date(2026, 1, 5),
        "at": stamp,
        "nested": [True, {"price": Decimal("2.50")}],
    }

    with _client(monkeypatch, result) as client:
        response = client.get(
            "/api/v1/market/newow/trend-detail?product=rb&from=2026-01-05&through=2026-01-05"
        )
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["trend_markers"][0]["trigger_facts"] == {
        "decimal": "1.2300",
        "day": "2026-01-05",
        "at": "2026-01-05T07:00:00Z",
        "nested": [True, {"price": "2.50"}],
    }


def test_newow_rejects_unsafe_marker_facts_without_repr_or_path_leak(
    monkeypatch,
) -> None:
    result = _result()

    class _Unsafe:
        def __repr__(self) -> str:
            return "Unsafe(/private/secret)"

    result.markers[0].trigger_facts = {"unsafe": _Unsafe()}
    with _client(monkeypatch, result) as client:
        response = client.get(
            "/api/v1/market/newow/trend-detail?product=rb&from=2026-01-05&through=2026-01-05"
        )
    app.dependency_overrides.clear()

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "NEWOW_DATA_IDENTITY_INVALID"}}
    assert "/private/secret" not in response.text


def test_newow_unsupported_composite_state_is_public_409(monkeypatch) -> None:
    monkeypatch.setattr(
        market_newow,
        "NewowTrendDetailService",
        lambda _market, **_kwargs: SimpleNamespace(
            query=lambda _query: (_ for _ in ()).throw(
                NewowTrendDetailError("NEWOW_COMPOSITE_STATE_UNSUPPORTED")
            )
        ),
    )
    app.dependency_overrides[get_db] = lambda: object()
    response = TestClient(app).get(
        "/api/v1/market/newow/trend-detail?product=rb&from=2026-01-05&through=2026-01-05"
    )
    app.dependency_overrides.clear()

    assert response.status_code == 409
    assert response.json() == {
        "detail": {"code": "NEWOW_COMPOSITE_STATE_UNSUPPORTED"}
    }


def test_newow_formula_identity_mismatch_is_fail_closed_409(monkeypatch) -> None:
    result = _result()
    result.instrument.formula_versions = (
        "wrong-formula",
        *result.instrument.formula_versions[1:],
    )

    with _client(monkeypatch, result) as client:
        response = client.get(
            "/api/v1/market/newow/trend-detail?product=rb&from=2026-01-05&through=2026-01-05"
        )
    app.dependency_overrides.clear()

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "NEWOW_DATA_UNAVAILABLE"}}
    assert "wrong-formula" not in response.text


@pytest.mark.parametrize(
    "mutate",
    (
        lambda result: setattr(result.instrument, "profile_id", "wrong-profile"),
        lambda result: setattr(result.instrument, "frequency", "1w"),
        lambda result: setattr(result.instrument, "series_kind", "continuous"),
        lambda result: setattr(
            result.frames[0].trend_band,
            "state_before",
            SimpleNamespace(value="UNAVAILABLE"),
        ),
        lambda result: setattr(result.markers[0], "formula_version", "wrong-formula"),
        lambda result: setattr(
            result.cup_handles[0], "state", SimpleNamespace(value="UNKNOWN")
        ),
        lambda result: setattr(
            result.cup_handles[0], "formula_version", "wrong-formula"
        ),
    ),
)
def test_newow_serializer_rejects_noncanonical_literals_with_stable_code(
    monkeypatch,
    mutate,
) -> None:
    result = _result()
    mutate(result)

    with _client(monkeypatch, result) as client:
        response = client.get(
            "/api/v1/market/newow/trend-detail?product=rb&from=2026-01-05&through=2026-01-05"
        )
    app.dependency_overrides.clear()

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "NEWOW_DATA_IDENTITY_INVALID"}}
